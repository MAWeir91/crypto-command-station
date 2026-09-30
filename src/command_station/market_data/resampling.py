"""Deterministic derivation of higher timeframe bars from canonical one-minute data."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import cast

from command_station.domain import (
    Candle,
    ProductId,
    ProductType,
    Timeframe,
    UtcTimestamp,
    Venue,
    decimal_to_text,
)
from command_station.market_data.datasets import (
    CanonicalCandleDataset,
    DatasetQuality,
    DatasetVersion,
    GapReason,
    canonical_json,
)

RESAMPLER_VERSION = 1
DERIVED_CACHE_KEY_SCHEMA_VERSION = 1
DERIVED_RESULT_SCHEMA_VERSION = 1
_MINUTE = timedelta(minutes=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class DerivedDatasetError(Exception):
    """Base failure at the derived-data boundary."""


class DerivedDatasetValidationError(DerivedDatasetError, ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DerivedCacheKey:
    value: str

    def __post_init__(self) -> None:
        if not _is_sha256(self.value):
            raise DerivedDatasetValidationError("derived cache key must be lowercase SHA-256 text")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ResampleBucket:
    open_time: UtcTimestamp
    close_time: UtcTimestamp
    timeframe: Timeframe
    required_minute_count: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.open_time, UtcTimestamp)
            or not isinstance(self.close_time, UtcTimestamp)
            or not isinstance(self.timeframe, Timeframe)
            or self.timeframe is Timeframe.ONE_MINUTE
            or type(self.required_minute_count) is not int
            or self.required_minute_count < 2
            or self.close_time.value - self.open_time.value != self.timeframe.duration
            or self.required_minute_count * _MINUTE != self.timeframe.duration
            or (self.open_time.value - _EPOCH) % self.timeframe.duration != timedelta(0)
        ):
            raise DerivedDatasetValidationError("invalid resample bucket")


@dataclass(frozen=True, slots=True)
class DerivedGapRecord:
    open_time: UtcTimestamp
    close_time: UtcTimestamp
    reason: GapReason
    source_gap_open_times: tuple[UtcTimestamp, ...]

    def __post_init__(self) -> None:
        times = tuple(self.source_gap_open_times)
        if (
            not isinstance(self.open_time, UtcTimestamp)
            or not isinstance(self.close_time, UtcTimestamp)
            or self.close_time <= self.open_time
            or self.reason is not GapReason.MISSING_SOURCE
            or not times
            or tuple(sorted(times)) != times
            or len(set(times)) != len(times)
            or not all(isinstance(value, UtcTimestamp) for value in times)
            or not all(self.open_time <= value < self.close_time for value in times)
        ):
            raise DerivedDatasetValidationError("invalid derived gap record")


@dataclass(frozen=True, slots=True)
class ResampledCandleDataset:
    cache_key: DerivedCacheKey
    source_dataset_version: DatasetVersion
    source_quality: DatasetQuality
    venue: Venue
    product_type: ProductType
    product_id: ProductId
    target_timeframe: Timeframe
    resampler_version: int
    source_start: UtcTimestamp
    source_end: UtcTimestamp
    source_as_of: UtcTimestamp
    bars: tuple[Candle, ...]
    gaps: tuple[DerivedGapRecord, ...]
    quality: DatasetQuality
    eligible_bucket_count: int
    excluded_edge_minute_count: int
    logical_bar_content_sha256: str
    logical_gap_content_sha256: str
    derived_result_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.cache_key, DerivedCacheKey)
            or not isinstance(self.source_dataset_version, DatasetVersion)
            or not isinstance(self.source_quality, DatasetQuality)
            or self.venue is not Venue.COINBASE
            or self.product_type is not ProductType.SPOT
            or not isinstance(self.product_id, ProductId)
            or not _valid_target(self.target_timeframe)
            or type(self.resampler_version) is not int
            or self.resampler_version < 1
            or not all(
                isinstance(value, UtcTimestamp)
                for value in (self.source_start, self.source_end, self.source_as_of)
            )
            or self.source_start >= self.source_end
            or type(self.eligible_bucket_count) is not int
            or type(self.excluded_edge_minute_count) is not int
            or self.eligible_bucket_count < 0
            or self.excluded_edge_minute_count < 0
            or not all(
                _is_sha256(value)
                for value in (
                    self.logical_bar_content_sha256,
                    self.logical_gap_content_sha256,
                    self.derived_result_sha256,
                )
            )
        ):
            raise DerivedDatasetValidationError("invalid resampled dataset identity")
        bars, gaps = tuple(self.bars), tuple(self.gaps)
        if (
            tuple(sorted(bars, key=lambda value: value.open_time)) != bars
            or tuple(sorted(gaps, key=lambda value: value.open_time)) != gaps
        ):
            raise DerivedDatasetValidationError("derived bars and gaps must be ordered")
        if len({value.open_time for value in bars}) != len(bars) or len(
            {value.open_time for value in gaps}
        ) != len(gaps):
            raise DerivedDatasetValidationError("derived bars and gaps must be unique")
        if {value.open_time for value in bars} & {value.open_time for value in gaps}:
            raise DerivedDatasetValidationError("derived bars and gaps must not collide")
        for bar in bars:
            if (
                not isinstance(bar, Candle)
                or bar.product_id != self.product_id
                or bar.timeframe is not self.target_timeframe
                or not (self.source_start <= bar.open_time < bar.close_time <= self.source_end)
            ):
                raise DerivedDatasetValidationError("derived bar is inconsistent")
        for gap in gaps:
            if (
                not isinstance(gap, DerivedGapRecord)
                or not (self.source_start <= gap.open_time < gap.close_time <= self.source_end)
                or gap.close_time.value - gap.open_time.value != self.target_timeframe.duration
            ):
                raise DerivedDatasetValidationError("derived gap is inconsistent")
        if len(bars) + len(gaps) != self.eligible_bucket_count:
            raise DerivedDatasetValidationError(
                "derived eligible bucket accounting is inconsistent"
            )
        planned_open_times = tuple(
            bucket.open_time
            for bucket in plan_resample_buckets(
                self.source_start, self.source_end, self.target_timeframe
            )
        )
        actual_open_times = tuple(
            sorted((*[bar.open_time for bar in bars], *[gap.open_time for gap in gaps]))
        )
        if actual_open_times != planned_open_times:
            raise DerivedDatasetValidationError(
                "derived bars and gaps must account for every eligible bucket"
            )
        expected = _source_expected_minutes(self.source_start, self.source_end)
        eligible_minutes = self.eligible_bucket_count * _minutes(self.target_timeframe)
        if self.excluded_edge_minute_count != expected - eligible_minutes:
            raise DerivedDatasetValidationError("derived excluded-edge accounting is inconsistent")
        expected_quality = (
            DatasetQuality.INCOMPLETE
            if (self.source_quality is DatasetQuality.INCOMPLETE or gaps)
            else DatasetQuality.VALID
        )
        if self.quality is not expected_quality:
            raise DerivedDatasetValidationError("derived quality cannot upgrade source quality")
        if self.cache_key != derive_cache_key(
            self.source_dataset_version, self.target_timeframe, self.resampler_version
        ):
            raise DerivedDatasetValidationError("derived cache key is inconsistent")
        if self.logical_bar_content_sha256 != logical_bar_content_hash(
            bars
        ) or self.logical_gap_content_sha256 != logical_gap_content_hash(gaps):
            raise DerivedDatasetValidationError("derived logical hashes are inconsistent")
        if self.derived_result_sha256 != derived_result_hash(self):
            raise DerivedDatasetValidationError("derived result hash is inconsistent")

    @property
    def source_expected_minute_count(self) -> int:
        return _source_expected_minutes(self.source_start, self.source_end)

    @property
    def eligible_source_minute_count(self) -> int:
        return self.eligible_bucket_count * _minutes(self.target_timeframe)


def plan_resample_buckets(
    source_start: UtcTimestamp, source_end: UtcTimestamp, target_timeframe: Timeframe
) -> tuple[ResampleBucket, ...]:
    """Plan only complete UTC epoch-aligned target buckets in ``[source_start, source_end)``."""
    if (
        not isinstance(source_start, UtcTimestamp)
        or not isinstance(source_end, UtcTimestamp)
        or source_start >= source_end
    ):
        raise DerivedDatasetValidationError("source interval must be ordered UtcTimestamp values")
    _require_target(target_timeframe)
    duration = target_timeframe.duration
    elapsed = source_start.value - _EPOCH
    remainder = elapsed % duration
    first = (
        source_start.value
        if remainder == timedelta(0)
        else source_start.value + (duration - remainder)
    )
    values: list[ResampleBucket] = []
    while first + duration <= source_end.value:
        values.append(
            ResampleBucket(
                UtcTimestamp(first),
                UtcTimestamp(first + duration),
                target_timeframe,
                _minutes(target_timeframe),
            )
        )
        first += duration
    return tuple(values)


def derive_cache_key(
    source_version: DatasetVersion,
    target_timeframe: Timeframe,
    resampler_version: int = RESAMPLER_VERSION,
) -> DerivedCacheKey:
    if not isinstance(source_version, DatasetVersion):
        raise DerivedDatasetValidationError("cache key requires DatasetVersion")
    _require_target(target_timeframe)
    if type(resampler_version) is not int or resampler_version < 1:
        raise DerivedDatasetValidationError("resampler version must be a positive integer")
    return DerivedCacheKey(
        _hash(
            {
                "derived_cache_key_schema_version": DERIVED_CACHE_KEY_SCHEMA_VERSION,
                "source_dataset_version": source_version.value,
                "target_timeframe": target_timeframe.value,
                "resampler_version": resampler_version,
            }
        )
    )


def resample_canonical_dataset(
    source: CanonicalCandleDataset, target_timeframe: Timeframe
) -> ResampledCandleDataset:
    if (
        not isinstance(source, CanonicalCandleDataset)
        or source.timeframe is not Timeframe.ONE_MINUTE
    ):
        raise DerivedDatasetValidationError("resampling requires a canonical one-minute dataset")
    _require_target(target_timeframe)
    buckets = plan_resample_buckets(source.start, source.end, target_timeframe)
    candles = {value.open_time: value for value in source.candles}
    gaps = {value.open_time: value for value in source.gaps}
    bars: list[Candle] = []
    derived_gaps: list[DerivedGapRecord] = []
    for bucket in buckets:
        moments = tuple(
            UtcTimestamp(bucket.open_time.value + _MINUTE * index)
            for index in range(bucket.required_minute_count)
        )
        unresolved = tuple(moment for moment in moments if moment in gaps)
        if unresolved:
            derived_gaps.append(
                DerivedGapRecord(
                    bucket.open_time, bucket.close_time, GapReason.MISSING_SOURCE, unresolved
                )
            )
            continue
        source_bars = tuple(candles.get(moment) for moment in moments)
        if any(value is None for value in source_bars):
            raise DerivedDatasetValidationError("canonical source coverage is inconsistent")
        concrete = tuple(value for value in source_bars if value is not None)
        bars.append(_aggregate_bucket(concrete, bucket))
    bars_value, gaps_value = tuple(bars), tuple(derived_gaps)
    quality = (
        DatasetQuality.INCOMPLETE
        if source.quality is DatasetQuality.INCOMPLETE or gaps_value
        else DatasetQuality.VALID
    )
    bar_hash, gap_hash = logical_bar_content_hash(bars_value), logical_gap_content_hash(gaps_value)
    key = derive_cache_key(source.version, target_timeframe)
    result_hash = _derived_result_hash_values(
        source.version,
        target_timeframe,
        RESAMPLER_VERSION,
        len(buckets),
        _source_expected_minutes(source.start, source.end)
        - len(buckets) * _minutes(target_timeframe),
        quality,
        bar_hash,
        gap_hash,
    )
    return ResampledCandleDataset(
        key,
        source.version,
        source.quality,
        Venue.COINBASE,
        ProductType.SPOT,
        source.product_id,
        target_timeframe,
        RESAMPLER_VERSION,
        source.start,
        source.end,
        source.as_of,
        bars_value,
        gaps_value,
        quality,
        len(buckets),
        _source_expected_minutes(source.start, source.end)
        - len(buckets) * _minutes(target_timeframe),
        bar_hash,
        gap_hash,
        result_hash,
    )


def logical_bar_content_hash(bars: Iterable[Candle]) -> str:
    return _hash([_bar_data(bar) for bar in bars])


def logical_gap_content_hash(gaps: Iterable[DerivedGapRecord]) -> str:
    return _hash([_gap_data(gap) for gap in gaps])


def derived_result_hash(value: ResampledCandleDataset) -> str:
    return _derived_result_hash_values(
        value.source_dataset_version,
        value.target_timeframe,
        value.resampler_version,
        value.eligible_bucket_count,
        value.excluded_edge_minute_count,
        value.quality,
        value.logical_bar_content_sha256,
        value.logical_gap_content_sha256,
    )


def _derived_result_hash_values(
    source: DatasetVersion,
    timeframe: Timeframe,
    version: int,
    eligible: int,
    excluded: int,
    quality: DatasetQuality,
    bar_hash: str,
    gap_hash: str,
) -> str:
    return _hash(
        {
            "derived_result_schema_version": DERIVED_RESULT_SCHEMA_VERSION,
            "source_dataset_version": source.value,
            "target_timeframe": timeframe.value,
            "resampler_version": version,
            "eligible_bucket_count": eligible,
            "excluded_edge_minute_count": excluded,
            "quality": quality.value,
            "logical_bar_content_sha256": bar_hash,
            "logical_gap_content_sha256": gap_hash,
        }
    )


def _aggregate_bucket(candles: tuple[Candle, ...], bucket: ResampleBucket) -> Candle:
    return Candle(
        candles[0].product_id,
        bucket.timeframe,
        bucket.open_time,
        bucket.close_time,
        candles[0].open,
        max(value.high for value in candles),
        min(value.low for value in candles),
        candles[-1].close,
        _exact_nonnegative_sum(value.volume for value in candles),
    )


def _exact_nonnegative_sum(values: Iterable[Decimal]) -> Decimal:
    """Sum finite nonnegative Decimal coefficients without using the decimal context."""
    parts = tuple(values)
    if not parts:
        return Decimal(0)
    tuples = tuple(value.as_tuple() for value in parts)
    if any(
        (item.sign and any(item.digits)) or not isinstance(item.exponent, int) for item in tuples
    ):
        raise DerivedDatasetValidationError(
            "volume aggregation requires finite nonnegative Decimal values"
        )
    exponent = min(cast(int, item.exponent) for item in tuples)
    width = max(len(item.digits) + cast(int, item.exponent) - exponent for item in tuples)
    total = [0] * max(width, 1)
    for item in tuples:
        shift = cast(int, item.exponent) - exponent
        start = len(total) - len(item.digits) - shift
        for index, digit in enumerate(item.digits):
            total[start + index] += digit
    for index in range(len(total) - 1, 0, -1):
        carry, total[index] = divmod(total[index], 10)
        total[index - 1] += carry
    while len(total) > 1 and total[0] >= 10:
        carry, total[0] = divmod(total[0], 10)
        total.insert(0, carry)
    while len(total) > 1 and total[0] == 0:
        total.pop(0)
    return Decimal((0, tuple(total), exponent))


def _bar_data(bar: Candle) -> dict[str, str]:
    return {
        "product_id": bar.product_id.value,
        "timeframe": bar.timeframe.value,
        "open_time": str(bar.open_time),
        "close_time": str(bar.close_time),
        "open": decimal_to_text(bar.open),
        "high": decimal_to_text(bar.high),
        "low": decimal_to_text(bar.low),
        "close": decimal_to_text(bar.close),
        "volume": decimal_to_text(bar.volume),
    }


def _gap_data(gap: DerivedGapRecord) -> dict[str, object]:
    return {
        "open_time": str(gap.open_time),
        "close_time": str(gap.close_time),
        "reason": gap.reason.value,
        "source_gap_open_times": [str(value) for value in gap.source_gap_open_times],
    }


def _hash(value: object) -> str:
    return sha256(canonical_json(value)).hexdigest()


def _minutes(timeframe: Timeframe) -> int:
    return int(timeframe.duration // _MINUTE)


def _source_expected_minutes(start: UtcTimestamp, end: UtcTimestamp) -> int:
    return int((end.value - start.value) // _MINUTE)


def _valid_target(value: object) -> bool:
    return isinstance(value, Timeframe) and value is not Timeframe.ONE_MINUTE


def _require_target(value: object) -> None:
    if not _valid_target(value):
        raise DerivedDatasetValidationError(
            "resampling target must be a supported timeframe above 1m"
        )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
