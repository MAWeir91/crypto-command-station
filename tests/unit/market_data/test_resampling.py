from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, getcontext, localcontext
from hashlib import sha256

import pytest

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.datasets import (
    CanonicalCandleDataset,
    DatasetQuality,
    GapReason,
    GapRecord,
    SourcePageReference,
    canonical_json,
)
from command_station.market_data.resampling import (
    DERIVED_RESULT_SCHEMA_VERSION,
    RESAMPLER_VERSION,
    DerivedDatasetValidationError,
    DerivedGapRecord,
    derive_cache_key,
    logical_bar_content_hash,
    logical_gap_content_hash,
    plan_resample_buckets,
    resample_canonical_dataset,
)

PRODUCT = ProductId("BTC-USD")
PAGES = (SourcePageReference("a" * 64, "b" * 64),)


def moment(minutes: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes))


def candle(index: int, *, volume: str = "1", close: str | None = None) -> Candle:
    value = str(index + 1) if close is None else close
    return Candle(
        PRODUCT,
        Timeframe.ONE_MINUTE,
        moment(index),
        moment(index + 1),
        value,
        str(index + 3),
        "1",
        value,
        volume,
    )


def dataset(start: int, end: int, gaps: tuple[int, ...] = ()) -> CanonicalCandleDataset:
    gap_values = set(gaps)
    return CanonicalCandleDataset(
        product_id=PRODUCT,
        start=moment(start),
        end=moment(end),
        as_of=moment(end + 1),
        candles=(candle(index) for index in range(start, end) if index not in gap_values),
        gaps=(GapRecord(moment(index), GapReason.MISSING_SOURCE) for index in gaps),
        source_pages=PAGES,
    )


@pytest.mark.parametrize(
    "timeframe, start, end, expected",
    [
        (Timeframe.FIVE_MINUTES, 1, 16, ((5, 10), (10, 15))),
        (Timeframe.FIFTEEN_MINUTES, 1, 31, ((15, 30),)),
        (Timeframe.THIRTY_MINUTES, 1, 61, ((30, 60),)),
        (Timeframe.ONE_HOUR, 1, 121, ((60, 120),)),
        (Timeframe.TWO_HOURS, 1, 241, ((120, 240),)),
        (Timeframe.FOUR_HOURS, 1, 481, ((240, 480),)),
        (Timeframe.SIX_HOURS, 1, 721, ((360, 720),)),
        (Timeframe.ONE_DAY, 1, 2881, ((1440, 2880),)),
    ],
)
def test_planner_uses_epoch_aligned_complete_buckets(
    timeframe: Timeframe, start: int, end: int, expected: tuple[tuple[int, int], ...]
) -> None:
    values = plan_resample_buckets(moment(start), moment(end), timeframe)
    assert (
        tuple(
            (
                int((value.open_time.value - moment(0).value) // timedelta(minutes=1)),
                int((value.close_time.value - moment(0).value) // timedelta(minutes=1)),
            )
            for value in values
        )
        == expected
    )
    assert all(
        value.open_time >= moment(start) and value.close_time <= moment(end) for value in values
    )


def test_planner_rejects_one_minute_and_allows_empty() -> None:
    with pytest.raises(DerivedDatasetValidationError):
        plan_resample_buckets(moment(0), moment(5), Timeframe.ONE_MINUTE)
    assert plan_resample_buckets(moment(1), moment(4), Timeframe.FIVE_MINUTES) == ()


def test_aggregate_ohlcv_and_exact_volume_are_context_independent() -> None:
    source = dataset(0, 5)
    custom = CanonicalCandleDataset(
        product_id=PRODUCT,
        start=source.start,
        end=source.end,
        as_of=source.as_of,
        candles=(
            candle(index, volume=value, close=str(index + 1))
            for index, value in enumerate(("100000000000000000000.1", "0.1", "0.1", "0.1", "0.1"))
        ),
        gaps=(),
        source_pages=PAGES,
    )
    before = (getcontext().prec, getcontext().rounding, getcontext().Emin, getcontext().Emax)
    with localcontext() as context:
        context.prec = 4
        low_precision = resample_canonical_dataset(custom, Timeframe.FIVE_MINUTES)
    with localcontext() as context:
        context.prec = 50
        high_precision = resample_canonical_dataset(custom, Timeframe.FIVE_MINUTES)
    assert (
        getcontext().prec,
        getcontext().rounding,
        getcontext().Emin,
        getcontext().Emax,
    ) == before
    bar = low_precision.bars[0]
    assert low_precision.bars == high_precision.bars
    assert bar.open == Decimal("1")
    assert bar.close == Decimal("5")
    assert bar.high == Decimal("7")
    assert bar.low == Decimal("1")
    assert bar.volume == Decimal("100000000000000000000.5")
    assert bar.product_id == PRODUCT and bar.timeframe is Timeframe.FIVE_MINUTES


def test_edge_accounting_gaps_and_quality_are_explicit() -> None:
    result = resample_canonical_dataset(dataset(1, 16, (7, 12)), Timeframe.FIVE_MINUTES)
    assert result.eligible_bucket_count == 2
    assert result.eligible_source_minute_count == 10
    assert result.excluded_edge_minute_count == 5
    assert result.bars == ()
    assert result.quality is DatasetQuality.INCOMPLETE
    assert [
        (str(gap.open_time), [str(value) for value in gap.source_gap_open_times])
        for gap in result.gaps
    ] == [
        (str(moment(5)), [str(moment(7))]),
        (str(moment(10)), [str(moment(12))]),
    ]
    assert all(gap.reason is GapReason.MISSING_SOURCE for gap in result.gaps)


def test_excluded_edge_gap_does_not_create_a_derived_gap() -> None:
    result = resample_canonical_dataset(dataset(1, 9, (1,)), Timeframe.FIVE_MINUTES)
    assert result.bars == () and result.gaps == ()
    assert result.eligible_bucket_count == 0
    assert result.quality is DatasetQuality.INCOMPLETE


def test_identity_changes_only_for_identity_components() -> None:
    source = dataset(0, 5)
    result = resample_canonical_dataset(source, Timeframe.FIVE_MINUTES)
    assert result.cache_key == derive_cache_key(source.version, Timeframe.FIVE_MINUTES)
    assert result.cache_key != derive_cache_key(source.version, Timeframe.FIFTEEN_MINUTES)
    assert result.cache_key != derive_cache_key(source.version, Timeframe.FIVE_MINUTES, 2)
    changed = dataset(0, 5, (2,))
    changed_result = resample_canonical_dataset(changed, Timeframe.FIVE_MINUTES)
    assert changed.version != source.version and changed_result.cache_key != result.cache_key
    assert changed_result.logical_gap_content_sha256 != result.logical_gap_content_sha256
    assert RESAMPLER_VERSION == 1


def test_negative_zero_and_very_large_decimal_volume_are_exact() -> None:
    huge = "9" * 5000
    source = CanonicalCandleDataset(
        product_id=PRODUCT,
        start=moment(0),
        end=moment(5),
        as_of=moment(6),
        candles=(
            candle(0, volume="-0"),
            candle(1, volume=huge),
            candle(2, volume="1"),
            candle(3, volume="0"),
            candle(4, volume="0"),
        ),
        gaps=(),
        source_pages=PAGES,
    )
    with localcontext() as context:
        context.prec = 3
        result = resample_canonical_dataset(source, Timeframe.FIVE_MINUTES)
    assert result.bars[0].volume == Decimal("1" + "0" * 5000)


def _result_hash(
    source_version: str,
    eligible: int,
    excluded: int,
    quality: DatasetQuality,
    bar_hash: str,
    gap_hash: str,
) -> str:
    return sha256(
        canonical_json(
            {
                "derived_result_schema_version": DERIVED_RESULT_SCHEMA_VERSION,
                "source_dataset_version": source_version,
                "target_timeframe": Timeframe.FIVE_MINUTES.value,
                "resampler_version": RESAMPLER_VERSION,
                "eligible_bucket_count": eligible,
                "excluded_edge_minute_count": excluded,
                "quality": quality.value,
                "logical_bar_content_sha256": bar_hash,
                "logical_gap_content_sha256": gap_hash,
            }
        )
    ).hexdigest()


def test_self_consistent_omitted_eligible_bucket_is_rejected() -> None:
    result = resample_canonical_dataset(dataset(0, 15), Timeframe.FIVE_MINUTES)
    bars = (result.bars[0], result.bars[2])
    bar_hash = logical_bar_content_hash(bars)
    with pytest.raises(DerivedDatasetValidationError, match="every eligible bucket"):
        replace(
            result,
            bars=bars,
            eligible_bucket_count=2,
            excluded_edge_minute_count=5,
            logical_bar_content_sha256=bar_hash,
            derived_result_sha256=_result_hash(
                result.source_dataset_version.value,
                2,
                5,
                result.quality,
                bar_hash,
                result.logical_gap_content_sha256,
            ),
        )


def test_misaligned_derived_gap_is_rejected() -> None:
    result = resample_canonical_dataset(dataset(0, 10, (2,)), Timeframe.FIVE_MINUTES)
    gaps = (DerivedGapRecord(moment(1), moment(6), GapReason.MISSING_SOURCE, (moment(2),)),)
    gap_hash = logical_gap_content_hash(gaps)
    with pytest.raises(DerivedDatasetValidationError, match="every eligible bucket"):
        replace(
            result,
            gaps=gaps,
            logical_gap_content_sha256=gap_hash,
            derived_result_sha256=_result_hash(
                result.source_dataset_version.value,
                result.eligible_bucket_count,
                result.excluded_edge_minute_count,
                result.quality,
                result.logical_bar_content_sha256,
                gap_hash,
            ),
        )
