from datetime import UTC, datetime, timedelta
from decimal import Decimal, getcontext, localcontext
from typing import cast

from hypothesis import given
from hypothesis import strategies as st

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.datasets import (
    CanonicalCandleDataset,
    GapReason,
    GapRecord,
    SourcePageReference,
)
from command_station.market_data.resampling import (
    derive_cache_key,
    plan_resample_buckets,
    resample_canonical_dataset,
)

PRODUCT = ProductId("BTC-USD")
PAGES = (SourcePageReference("a" * 64, "b" * 64),)


def context_state() -> tuple[object, ...]:
    """Capture all mutable Decimal context fields without Context identity semantics."""
    context = getcontext()
    return (
        context.prec,
        context.rounding,
        context.Emin,
        context.Emax,
        context.capitals,
        context.clamp,
        tuple(sorted((str(signal), enabled) for signal, enabled in context.flags.items())),
        tuple(sorted((str(signal), enabled) for signal, enabled in context.traps.items())),
    )


def at(index: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=index))


@given(st.lists(st.decimals(min_value="0", max_value="99999", places=3), min_size=5, max_size=5))
def test_complete_bucket_aggregates_exactly(volumes: list[Decimal]) -> None:
    candles = tuple(
        Candle(
            PRODUCT,
            Timeframe.ONE_MINUTE,
            at(index),
            at(index + 1),
            "1",
            str(index + 2),
            "1",
            str(index + 1),
            str(volume),
        )
        for index, volume in enumerate(volumes)
    )
    source = CanonicalCandleDataset(
        product_id=PRODUCT,
        start=at(0),
        end=at(5),
        as_of=at(6),
        candles=candles,
        gaps=(),
        source_pages=PAGES,
    )
    with localcontext() as context:
        context.prec = 4
        result = resample_canonical_dataset(source, Timeframe.FIVE_MINUTES)
    bar = result.bars[0]
    # Decimal construction from integer coefficients avoids a context-sensitive expected sum.
    exponent = min(cast(int, value.as_tuple().exponent) for value in volumes)
    total = sum(
        int("".join(map(str, value.as_tuple().digits)) or "0")
        * 10 ** (cast(int, value.as_tuple().exponent) - exponent)
        for value in volumes
    )
    assert bar.volume == Decimal((0, tuple(map(int, str(total))), exponent))
    assert bar.open == candles[0].open and bar.close == candles[-1].close
    assert bar.high == max(value.high for value in candles) and bar.low == min(
        value.low for value in candles
    )


@given(st.integers(min_value=0, max_value=4))
def test_any_source_gap_suppresses_eligible_bar(gap_index: int) -> None:
    candles = [
        Candle(PRODUCT, Timeframe.ONE_MINUTE, at(index), at(index + 1), "1", "1", "1", "1", "1")
        for index in range(5)
        if index != gap_index
    ]
    source = CanonicalCandleDataset(
        product_id=PRODUCT,
        start=at(0),
        end=at(5),
        as_of=at(6),
        candles=candles,
        gaps=(GapRecord(at(gap_index), GapReason.MISSING_SOURCE),),
        source_pages=PAGES,
    )
    result = resample_canonical_dataset(source, Timeframe.FIVE_MINUTES)
    assert result.bars == () and len(result.gaps) == 1
    assert result.gaps[0].source_gap_open_times == (at(gap_index),)


@given(
    st.integers(min_value=0, max_value=4),
    st.integers(min_value=5, max_value=29),
    st.sets(st.integers(min_value=0, max_value=29), max_size=15),
)
def test_emitted_buckets_are_aligned_contained_and_accounted_for(
    start: int, end: int, gap_indexes: set[int]
) -> None:
    missing = {index for index in gap_indexes if start <= index < end}
    source = CanonicalCandleDataset(
        product_id=PRODUCT,
        start=at(start),
        end=at(end),
        as_of=at(end + 1),
        candles=(
            Candle(PRODUCT, Timeframe.ONE_MINUTE, at(index), at(index + 1), "1", "1", "1", "1", "1")
            for index in range(start, end)
            if index not in missing
        ),
        gaps=(GapRecord(at(index), GapReason.MISSING_SOURCE) for index in sorted(missing)),
        source_pages=PAGES,
    )
    result = resample_canonical_dataset(source, Timeframe.FIVE_MINUTES)
    planned = plan_resample_buckets(source.start, source.end, Timeframe.FIVE_MINUTES)
    actual = {bar.open_time for bar in result.bars} | {gap.open_time for gap in result.gaps}
    assert actual == {bucket.open_time for bucket in planned}
    assert len(result.bars) + len(result.gaps) == len(planned)
    assert result.eligible_source_minute_count + result.excluded_edge_minute_count == end - start
    for bar in result.bars:
        assert bar.open_time.value.minute % 5 == 0
        assert bar.close_time.value - bar.open_time.value == timedelta(minutes=5)
        assert source.start <= bar.open_time < bar.close_time <= source.end
        assert all(
            index not in missing
            for index in range(start, end)
            if bar.open_time <= at(index) < bar.close_time
        )
    for gap in result.gaps:
        expected = tuple(
            at(index) for index in sorted(missing) if gap.open_time <= at(index) < gap.close_time
        )
        assert gap.source_gap_open_times == expected


@given(st.integers(min_value=1, max_value=1000))
def test_cache_key_uses_source_identity_and_timeframe_only(volume: int) -> None:
    def make_source(value: int) -> CanonicalCandleDataset:
        return CanonicalCandleDataset(
            product_id=PRODUCT,
            start=at(0),
            end=at(5),
            as_of=at(6),
            candles=(
                Candle(
                    PRODUCT,
                    Timeframe.ONE_MINUTE,
                    at(index),
                    at(index + 1),
                    "1",
                    "1",
                    "1",
                    "1",
                    str(value if index == 0 else 1),
                )
                for index in range(5)
            ),
            gaps=(),
            source_pages=PAGES,
        )

    original, equivalent, changed = (
        make_source(volume),
        make_source(volume),
        make_source(volume + 1),
    )
    assert original is not equivalent and original.version == equivalent.version
    assert derive_cache_key(original.version, Timeframe.FIVE_MINUTES) == derive_cache_key(
        equivalent.version, Timeframe.FIVE_MINUTES
    )
    assert derive_cache_key(original.version, Timeframe.FIVE_MINUTES) != derive_cache_key(
        changed.version, Timeframe.FIVE_MINUTES
    )
    assert derive_cache_key(original.version, Timeframe.FIVE_MINUTES) != derive_cache_key(
        original.version, Timeframe.FIFTEEN_MINUTES
    )


@given(
    st.lists(
        st.decimals(min_value="0", max_value="999999999999999999.999", places=3),
        min_size=5,
        max_size=5,
    ),
    st.integers(min_value=2, max_value=12),
)
def test_decimal_precision_does_not_change_volume_or_ambient_context(
    volumes: list[Decimal], precision: int
) -> None:
    source = CanonicalCandleDataset(
        product_id=PRODUCT,
        start=at(0),
        end=at(5),
        as_of=at(6),
        candles=(
            Candle(
                PRODUCT,
                Timeframe.ONE_MINUTE,
                at(index),
                at(index + 1),
                "1",
                "1",
                "1",
                "1",
                str(volume),
            )
            for index, volume in enumerate(volumes)
        ),
        gaps=(),
        source_pages=PAGES,
    )
    before = context_state()
    with localcontext() as context:
        context.prec = precision
        low = resample_canonical_dataset(source, Timeframe.FIVE_MINUTES)
        assert context.prec == precision
    with localcontext() as context:
        context.prec = 50
        high = resample_canonical_dataset(source, Timeframe.FIVE_MINUTES)
    assert context_state() == before
    assert low.bars[0].volume == high.bars[0].volume
