"""In-memory deterministic replay of accepted market-data datasets."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import timedelta

from command_station.domain import Candle, ProductId, ProductType, Timeframe, UtcTimestamp, Venue
from command_station.market_data.datasets import CanonicalCandleDataset, DatasetQuality
from command_station.market_data.resampling import ResampledCandleDataset


class ReplayDataError(ValueError):
    """Raised when data cannot safely enter the reference replay boundary."""


@dataclass(frozen=True, slots=True)
class MarketStreamKey:
    """Stable identity for a product/timeframe market stream."""

    product_id: ProductId
    timeframe: Timeframe

    def __post_init__(self) -> None:
        if not isinstance(self.product_id, ProductId) or not isinstance(self.timeframe, Timeframe):
            raise ReplayDataError("market stream key requires ProductId and Timeframe")


@dataclass(frozen=True, slots=True)
class BarReference:
    product_id: ProductId
    timeframe: Timeframe
    open_time: UtcTimestamp
    close_time: UtcTimestamp

    @classmethod
    def from_candle(cls, candle: Candle) -> BarReference:
        return cls(candle.product_id, candle.timeframe, candle.open_time, candle.close_time)


@dataclass(frozen=True, slots=True)
class MarketReplayBatch:
    timestamp: UtcTimestamp
    execution_intervals: tuple[Candle, ...]
    closing_bars: tuple[Candle, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, UtcTimestamp):
            raise ReplayDataError("replay batch timestamp must be a UtcTimestamp")
        seen: set[MarketStreamKey] = set()
        for candle in self.closing_bars:
            if not isinstance(candle, Candle) or candle.close_time != self.timestamp:
                raise ReplayDataError("closing bars must close at the batch timestamp")
            key = MarketStreamKey(candle.product_id, candle.timeframe)
            if key in seen:
                raise ReplayDataError("replay batch contains duplicate market streams")
            seen.add(key)
        execution_keys = {
            MarketStreamKey(candle.product_id, candle.timeframe)
            for candle in self.execution_intervals
        }
        if any(
            candle.timeframe is not Timeframe.ONE_MINUTE or candle.close_time != self.timestamp
            for candle in self.execution_intervals
        ):
            raise ReplayDataError(
                "execution intervals must be one-minute bars ending at the batch timestamp"
            )
        if not execution_keys.issubset(seen):
            raise ReplayDataError("execution intervals must also be closing bars")


class HistoricalReplayFeed:
    """Immutable, replayable merge of canonical one-minute and exact derived streams."""

    def __init__(
        self,
        canonical_sources: Iterable[CanonicalCandleDataset],
        derived_sources: Iterable[ResampledCandleDataset] = (),
        *,
        replay_end: UtcTimestamp | None = None,
    ) -> None:
        canonical = tuple(canonical_sources)
        derived = tuple(derived_sources)
        if not canonical:
            raise ReplayDataError("historical replay requires at least one canonical source")
        self._canonical = self._validate_canonical(canonical)
        self._derived = self._validate_derived(derived, self._canonical)
        first = self._canonical[0]
        self.start, self.end, self.as_of = first.start, first.end, first.as_of
        if replay_end is not None:
            if (
                not isinstance(replay_end, UtcTimestamp)
                or not self.start < replay_end <= self.end
                or replay_end.value.second != 0
                or replay_end.value.microsecond != 0
            ):
                raise ReplayDataError("replay end must be a covered UTC minute boundary")
            self.end = replay_end
        self._batches = self._build_batches()

    @property
    def canonical_sources(self) -> tuple[CanonicalCandleDataset, ...]:
        return self._canonical

    @property
    def derived_sources(self) -> tuple[ResampledCandleDataset, ...]:
        return self._derived

    def __iter__(self) -> Iterator[MarketReplayBatch]:
        return iter(self._batches)

    def _validate_canonical(
        self, sources: tuple[CanonicalCandleDataset, ...]
    ) -> tuple[CanonicalCandleDataset, ...]:
        products: set[ProductId] = set()
        normalized: list[CanonicalCandleDataset] = []
        period: tuple[UtcTimestamp, UtcTimestamp, UtcTimestamp] | None = None
        for source in sources:
            if not isinstance(source, CanonicalCandleDataset):
                raise ReplayDataError("canonical replay source must be CanonicalCandleDataset")
            if (
                source.venue is not Venue.COINBASE
                or source.product_type is not ProductType.SPOT
                or source.timeframe is not Timeframe.ONE_MINUTE
                or source.quality is not DatasetQuality.VALID
            ):
                raise ReplayDataError(
                    "canonical replay source must be valid Coinbase spot one-minute data"
                )
            if source.product_id in products:
                raise ReplayDataError("replay has duplicate canonical product sources")
            products.add(source.product_id)
            current = (source.start, source.end, source.as_of)
            if period is None:
                period = current
            elif current != period:
                raise ReplayDataError("canonical replay sources must share start, end, and as_of")
            normalized.append(source)
        return tuple(sorted(normalized, key=lambda value: value.product_id.value))

    def _validate_derived(
        self,
        sources: tuple[ResampledCandleDataset, ...],
        canonical: tuple[CanonicalCandleDataset, ...],
    ) -> tuple[ResampledCandleDataset, ...]:
        by_product = {value.product_id: value for value in canonical}
        streams: set[MarketStreamKey] = set()
        normalized: list[ResampledCandleDataset] = []
        for source in sources:
            if not isinstance(source, ResampledCandleDataset):
                raise ReplayDataError("derived replay source must be ResampledCandleDataset")
            parent = by_product.get(source.product_id)
            if parent is None or source.source_dataset_version != parent.version:
                raise ReplayDataError(
                    "derived replay source must match an exact canonical dataset version"
                )
            if (
                source.venue is not Venue.COINBASE
                or source.product_type is not ProductType.SPOT
                or source.target_timeframe is Timeframe.ONE_MINUTE
                or source.source_quality is not DatasetQuality.VALID
                or source.quality is not DatasetQuality.VALID
                or source.gaps
                or (source.source_start, source.source_end, source.source_as_of)
                != (parent.start, parent.end, parent.as_of)
            ):
                raise ReplayDataError(
                    "derived replay source is incompatible with canonical replay data"
                )
            key = MarketStreamKey(source.product_id, source.target_timeframe)
            if key in streams:
                raise ReplayDataError("replay has duplicate derived market streams")
            streams.add(key)
            normalized.append(source)
        return tuple(sorted(normalized, key=_derived_sort_key))

    def _build_batches(self) -> tuple[MarketReplayBatch, ...]:
        bars_by_close: dict[UtcTimestamp, list[Candle]] = defaultdict(list)
        streams: tuple[tuple[Candle, ...], ...] = tuple(
            source.candles for source in self._canonical
        ) + tuple(source.bars for source in self._derived)
        for stream in streams:
            for bar in stream:
                bars_by_close[bar.close_time].append(bar)
        canonical_by_close: dict[UtcTimestamp, tuple[Candle, ...]] = {}
        for source in self._canonical:
            for candle in source.candles:
                canonical_by_close.setdefault(candle.close_time, ())
                canonical_by_close[candle.close_time] += (candle,)
        batches: list[MarketReplayBatch] = []
        timestamp = UtcTimestamp(self.start.value + timedelta(minutes=1))
        while timestamp <= self.end:
            executions = tuple(sorted(canonical_by_close[timestamp], key=_candle_sort_key))
            if len(executions) != len(self._canonical):
                raise ReplayDataError(
                    "valid canonical replay data must provide every one-minute interval"
                )
            bars = tuple(sorted(bars_by_close[timestamp], key=_candle_sort_key))
            batches.append(MarketReplayBatch(timestamp, executions, bars))
            timestamp = UtcTimestamp(timestamp.value + timedelta(minutes=1))
        return tuple(batches)


def _candle_sort_key(value: Candle) -> tuple[str, timedelta, str]:
    return (value.product_id.value, value.timeframe.duration, value.timeframe.value)


def _derived_sort_key(value: ResampledCandleDataset) -> tuple[str, timedelta, str]:
    return (value.product_id.value, value.target_timeframe.duration, value.target_timeframe.value)
