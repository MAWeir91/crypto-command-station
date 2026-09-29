"""Deterministic source-evidence-first historical candle importing."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp

COINBASE_MAX_CANDLE_BUCKETS = 350
_MINUTE = timedelta(minutes=1)


class HistoricalCandleImportError(Exception):
    pass


class HistoricalCandleRequestError(HistoricalCandleImportError):
    pass


class HistoricalCandlePayloadError(HistoricalCandleImportError, ValueError):
    pass


class HistoricalCandleConflictError(HistoricalCandleImportError):
    pass


@dataclass(frozen=True, slots=True)
class HistoricalCandleImportSpec:
    product_id: ProductId
    start: UtcTimestamp
    end: UtcTimestamp
    as_of: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.product_id, ProductId) or not all(
            isinstance(v, UtcTimestamp) for v in (self.start, self.end, self.as_of)
        ):
            raise HistoricalCandleImportError("invalid historical import specification")
        if self.start >= self.end or not _aligned(self.start) or not _aligned(self.end):
            raise HistoricalCandleImportError("import bounds must be ordered UTC-minute boundaries")
        if self.end > _floor_minute(self.as_of):
            raise HistoricalCandleImportError("import end exceeds completed-candle boundary")


@dataclass(frozen=True, slots=True)
class CoinbaseCandleRequest:
    product_id: ProductId
    request_start: UtcTimestamp
    request_end: UtcTimestamp
    limit: int
    granularity: Timeframe = Timeframe.ONE_MINUTE

    def __post_init__(self) -> None:
        if (
            self.granularity is not Timeframe.ONE_MINUTE
            or self.request_start >= self.request_end
            or not _aligned(self.request_start)
            or not _aligned(self.request_end)
        ):
            raise HistoricalCandleImportError("invalid one-minute request boundaries")
        if (
            self.limit != _minutes(self.request_start, self.request_end)
            or not 1 <= self.limit <= COINBASE_MAX_CANDLE_BUCKETS
        ):
            raise HistoricalCandleImportError("request limit must equal 1..350 requested minutes")


@dataclass(frozen=True, slots=True)
class HistoricalCandleImportResult:
    spec: HistoricalCandleImportSpec
    candles: tuple[Candle, ...]
    missing_open_times: tuple[UtcTimestamp, ...]
    raw_pages: tuple[object, ...]
    request_count: int
    fetched_page_count: int
    reused_page_count: int


class HistoricalPageClient(Protocol):
    def fetch_page(self, request: CoinbaseCandleRequest) -> Mapping[str, object]: ...


class RawPageArchive(Protocol):
    def load(self, request: CoinbaseCandleRequest) -> object | None: ...
    def store(
        self, request: CoinbaseCandleRequest, *, as_of: UtcTimestamp, payload: Mapping[str, object]
    ) -> object: ...


def plan_coinbase_candle_requests(
    spec: HistoricalCandleImportSpec,
) -> tuple[CoinbaseCandleRequest, ...]:
    cursor, output = spec.start, []
    while cursor < spec.end:
        window_minutes = min(COINBASE_MAX_CANDLE_BUCKETS, _minutes(cursor, spec.end))
        end = UtcTimestamp(cursor.value + window_minutes * _MINUTE)
        output.append(CoinbaseCandleRequest(spec.product_id, cursor, end, _minutes(cursor, end)))
        if end == spec.end:
            break
        cursor = UtcTimestamp(end.value - _MINUTE)
    return tuple(output)


class HistoricalCandleImporter:
    def __init__(self, client: HistoricalPageClient, archive: RawPageArchive) -> None:
        self._client, self._archive = client, archive

    def import_candles(self, spec: HistoricalCandleImportSpec) -> HistoricalCandleImportResult:
        requests = plan_coinbase_candle_requests(spec)
        pages: list[object] = []
        observations: dict[UtcTimestamp, Candle] = {}
        fetched = 0
        reused = 0
        for request in requests:
            page = self._archive.load(request)
            if page is None:
                fetched_payload = self._client.fetch_page(request)
                page = self._archive.store(request, as_of=spec.as_of, payload=fetched_payload)
                fetched += 1
            else:
                reused += 1
            pages.append(page)
            archived_payload: object = getattr(page, "payload", None)
            if not isinstance(archived_payload, Mapping):
                raise HistoricalCandleImportError("raw archive returned an invalid page")
            for candle in normalize_coinbase_candle_page(archived_payload, request):
                if spec.start <= candle.open_time < spec.end:
                    old = observations.get(candle.open_time)
                    if old is not None and old != candle:
                        raise HistoricalCandleConflictError(
                            f"conflicting Coinbase candle at {candle.open_time}"
                        )
                    observations[candle.open_time] = candle
        candles = tuple(observations[t] for t in sorted(observations))
        missing = tuple(t for t in _starts(spec.start, spec.end) if t not in observations)
        return HistoricalCandleImportResult(
            spec, candles, missing, tuple(pages), len(requests), fetched, reused
        )


def normalize_coinbase_candle_page(
    payload: Mapping[str, object], request: CoinbaseCandleRequest
) -> tuple[Candle, ...]:
    raw = payload.get("candles") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list):
        raise HistoricalCandlePayloadError("Coinbase candle response candles must be a list")
    output: dict[UtcTimestamp, Candle] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise HistoricalCandlePayloadError("Coinbase candle must be a mapping")
        candle = normalize_coinbase_candle(item, request.product_id)
        if candle.open_time < request.request_start:
            raise HistoricalCandlePayloadError("Coinbase candle is before its request start")
        old = output.get(candle.open_time)
        if old is not None and old != candle:
            raise HistoricalCandleConflictError(
                f"conflicting Coinbase candle at {candle.open_time}"
            )
        output[candle.open_time] = candle
    return tuple(output[t] for t in sorted(output))


def normalize_coinbase_candle(payload: Mapping[str, object], product_id: ProductId) -> Candle:
    fields = ("start", "low", "high", "open", "close", "volume")
    if any(not isinstance(payload.get(field), str) for field in fields):
        raise HistoricalCandlePayloadError("Coinbase candle fields must be strings")
    start_text = cast(str, payload["start"])
    low = cast(str, payload["low"])
    high = cast(str, payload["high"])
    opening = cast(str, payload["open"])
    close = cast(str, payload["close"])
    volume = cast(str, payload["volume"])
    start = _unix_timestamp(start_text)
    if not _aligned(start):
        raise HistoricalCandlePayloadError("Coinbase candle start must align to a UTC minute")
    try:
        return Candle(
            product_id,
            Timeframe.ONE_MINUTE,
            start,
            UtcTimestamp(start.value + _MINUTE),
            opening,
            high,
            low,
            close,
            volume,
        )
    except Exception as error:
        raise HistoricalCandlePayloadError("Coinbase candle has invalid OHLCV") from error


def _floor_minute(value: UtcTimestamp) -> UtcTimestamp:
    return UtcTimestamp(value.value.replace(second=0, microsecond=0))


def _aligned(value: UtcTimestamp) -> bool:
    return value.value.second == 0 and value.value.microsecond == 0


def _minutes(start: UtcTimestamp, end: UtcTimestamp) -> int:
    return int((end.value - start.value) // _MINUTE)


def _starts(start: UtcTimestamp, end: UtcTimestamp) -> tuple[UtcTimestamp, ...]:
    return tuple(UtcTimestamp(start.value + n * _MINUTE) for n in range(_minutes(start, end)))


def _unix_timestamp(text: str) -> UtcTimestamp:
    if not text or text != text.strip() or not text.isascii() or not text.isdecimal():
        raise HistoricalCandlePayloadError(
            "Coinbase candle start must be strict integral UNIX text"
        )
    try:
        return UtcTimestamp(datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=int(text)))
    except (OverflowError, ValueError) as error:
        raise HistoricalCandlePayloadError(
            "Coinbase candle start is outside supported UTC range"
        ) from error
