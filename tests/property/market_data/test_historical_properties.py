from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from command_station.domain import ProductId, UtcTimestamp
from command_station.market_data.historical import (
    CoinbaseCandleRequest,
    HistoricalCandleConflictError,
    HistoricalCandleImporter,
    HistoricalCandleImportSpec,
    normalize_coinbase_candle_page,
    plan_coinbase_candle_requests,
)


@given(st.integers(min_value=1, max_value=2_000))
def test_plans_are_bounded_cover_every_minute_and_overlap(minutes: int) -> None:
    start = UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC))
    end = UtcTimestamp(start.value + timedelta(minutes=minutes))
    spec = HistoricalCandleImportSpec(
        ProductId("BTC-USD"), start, end, UtcTimestamp(end.value + timedelta(seconds=1))
    )
    plan = plan_coinbase_candle_requests(spec)
    assert all(1 <= request.limit <= 350 for request in plan)
    assert all(
        left.request_end.value - timedelta(minutes=1) == right.request_start.value
        for left, right in zip(plan, plan[1:], strict=False)
    )
    covered: set[int] = set()
    for request in plan:
        covered.update(
            range(
                int((request.request_start.value - start.value).total_seconds() // 60),
                int((request.request_end.value - start.value).total_seconds() // 60),
            )
        )
    assert covered == set(range(minutes))


def _provider_candle(minute: int, value: int) -> dict[str, object]:
    return {
        "start": str(1704067200 + minute * 60),
        "low": str(value),
        "high": str(value),
        "open": str(value),
        "close": str(value),
        "volume": "1",
    }


class _MemoryPage:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload


class _MemoryArchive:
    def load(self, request: CoinbaseCandleRequest) -> object | None:
        return None

    def store(
        self,
        request: CoinbaseCandleRequest,
        *,
        as_of: UtcTimestamp,
        payload: Mapping[str, object],
    ) -> object:
        return _MemoryPage(payload)


class _MemoryClient:
    def __init__(self, pages: tuple[Mapping[str, object], ...]) -> None:
        self.pages = iter(pages)

    def fetch_page(self, request: CoinbaseCandleRequest) -> Mapping[str, object]:
        return next(self.pages)


@given(st.permutations((0, 1, 2)))
@settings(max_examples=6)
def test_provider_page_order_permutations_produce_same_sorted_import(
    page_order: tuple[int, ...],
) -> None:
    start = UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC))
    end = UtcTimestamp(start.value + timedelta(minutes=700))
    spec = HistoricalCandleImportSpec(ProductId("BTC-USD"), start, end, end)
    page_payloads: tuple[Mapping[str, object], ...] = (
        {"candles": [_provider_candle(698, 699)]},
        {"candles": [_provider_candle(699, 700)]},
        {"candles": []},
    )
    importer = HistoricalCandleImporter(
        _MemoryClient(tuple(page_payloads[index] for index in page_order)),
        _MemoryArchive(),
    )
    result = importer.import_candles(spec)
    assert result.request_count == 3
    assert tuple(item.open_time for item in result.candles) == (
        UtcTimestamp(start.value + timedelta(minutes=698)),
        UtcTimestamp(start.value + timedelta(minutes=699)),
    )
    assert all(
        left.open_time < right.open_time
        for left, right in zip(result.candles, result.candles[1:], strict=False)
    )


@given(st.integers(min_value=1, max_value=10_000))
def test_identical_duplicate_candles_are_idempotently_deduplicated(value: int) -> None:
    start = UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC))
    request = CoinbaseCandleRequest(
        ProductId("BTC-USD"), start, UtcTimestamp(start.value + timedelta(minutes=1)), 1
    )
    duplicate = _provider_candle(0, value)
    normalized = normalize_coinbase_candle_page({"candles": [duplicate, duplicate]}, request)
    assert normalized == normalize_coinbase_candle_page({"candles": [duplicate]}, request)
    assert len(normalized) == 1


@given(st.integers(min_value=1, max_value=10_000), st.integers(min_value=1, max_value=10_000))
def test_changed_ohlcv_for_same_timestamp_raises_explicit_conflict(
    first_value: int, second_value: int
) -> None:
    if first_value == second_value:
        second_value += 1
    start = UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC))
    end = UtcTimestamp(start.value + timedelta(minutes=1))
    spec = HistoricalCandleImportSpec(ProductId("BTC-USD"), start, end, end)
    payload = {"candles": [_provider_candle(0, first_value), _provider_candle(0, second_value)]}
    importer = HistoricalCandleImporter(_MemoryClient((payload,)), _MemoryArchive())
    with pytest.raises(HistoricalCandleConflictError):
        importer.import_candles(spec)
