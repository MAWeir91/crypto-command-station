from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings
from hypothesis import strategies as st

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.datasets import (
    CanonicalCandleDataset,
    DatasetQuality,
    GapReason,
    GapRecord,
    SourcePageReference,
)
from command_station.market_data.parquet_store import LocalCanonicalDatasetStore

_START = UtcTimestamp(datetime(2025, 1, 1, tzinfo=UTC))
_PRODUCT = ProductId("BTC-USD")


def _page(index: int) -> SourcePageReference:
    value = f"{index:064x}"
    return SourcePageReference(value, f"{index + 1000:064x}")


def _candle(index: int, price: Decimal, volume: Decimal = Decimal("0")) -> Candle:
    opened = UtcTimestamp(_START.value + timedelta(minutes=index))
    text = str(price)
    return Candle(
        _PRODUCT,
        Timeframe.ONE_MINUTE,
        opened,
        UtcTimestamp(opened.value + timedelta(minutes=1)),
        text,
        text,
        text,
        text,
        str(volume),
    )


def _dataset(
    candles: tuple[Candle, ...],
    *,
    count: int,
    gaps: tuple[GapRecord, ...] = (),
    pages: tuple[SourcePageReference, ...] = (_page(1),),
) -> CanonicalCandleDataset:
    return CanonicalCandleDataset(
        product_id=_PRODUCT,
        start=_START,
        end=UtcTimestamp(_START.value + timedelta(minutes=count)),
        as_of=UtcTimestamp(_START.value + timedelta(minutes=count + 1)),
        candles=candles,
        gaps=gaps,
        source_pages=pages,
    )


@given(st.lists(st.integers(min_value=1, max_value=9999), min_size=1, max_size=8))
def test_exact_decimal_content_changes_or_is_stable(values: list[int]) -> None:
    start = UtcTimestamp(datetime(2025, 1, 1, tzinfo=UTC))
    candles = tuple(
        Candle(
            ProductId("BTC-USD"),
            Timeframe.ONE_MINUTE,
            UtcTimestamp(start.value + timedelta(minutes=index)),
            UtcTimestamp(start.value + timedelta(minutes=index + 1)),
            str(value),
            str(value),
            str(value),
            str(value),
            "0",
        )
        for index, value in enumerate(values)
    )
    first = CanonicalCandleDataset(
        product_id=ProductId("BTC-USD"),
        start=start,
        end=UtcTimestamp(start.value + timedelta(minutes=len(candles))),
        as_of=UtcTimestamp(start.value + timedelta(minutes=len(candles) + 1)),
        candles=candles,
        gaps=(),
        source_pages=(SourcePageReference("a" * 64, "b" * 64),),
    )
    second = CanonicalCandleDataset(
        product_id=ProductId("BTC-USD"),
        start=start,
        end=UtcTimestamp(start.value + timedelta(minutes=len(candles))),
        as_of=UtcTimestamp(start.value + timedelta(minutes=len(candles) + 1)),
        candles=candles,
        gaps=(),
        source_pages=(SourcePageReference("a" * 64, "b" * 64),),
    )
    assert first.version == second.version


@given(st.lists(st.integers(min_value=1, max_value=999_999), min_size=2, max_size=6, unique=True))
def test_source_page_permutation_preserves_dataset_identity(page_ids: list[int]) -> None:
    pages = tuple(_page(value) for value in page_ids)
    candles = (_candle(0, Decimal("1.25")),)

    forward = _dataset(candles, count=1, pages=pages)
    reverse = _dataset(candles, count=1, pages=tuple(reversed(pages)))

    assert forward.version == reverse.version
    assert forward.source_pages == reverse.source_pages


@given(st.lists(st.integers(min_value=1, max_value=999_999), min_size=1, max_size=8, unique=True))
def test_candle_input_permutation_is_canonicalized(values: list[int]) -> None:
    candles = tuple(_candle(index, Decimal(value)) for index, value in enumerate(values))
    forward = _dataset(candles, count=len(candles))
    reverse = _dataset(tuple(reversed(candles)), count=len(candles))

    assert forward.candles == reverse.candles
    assert [candle.open_time for candle in forward.candles] == sorted(
        candle.open_time for candle in candles
    )
    assert forward.logical_candle_content_sha256 == reverse.logical_candle_content_sha256
    assert forward.version == reverse.version


@given(
    st.integers(min_value=1, max_value=999_999),
    st.integers(min_value=1, max_value=999_999),
)
def test_valid_ohlcv_mutation_changes_logical_identity(first_price: int, delta: int) -> None:
    original = _dataset((_candle(0, Decimal(first_price)),), count=1)
    changed = _dataset((_candle(0, Decimal(first_price + delta)),), count=1)

    assert original.logical_candle_content_sha256 != changed.logical_candle_content_sha256
    assert original.version != changed.version


@given(
    st.integers(min_value=1, max_value=8),
    st.sets(st.integers(min_value=0, max_value=7), min_size=0, max_size=8),
)
def test_generated_gap_sets_account_for_every_expected_minute(
    count: int, missing_indices: set[int]
) -> None:
    missing = {index for index in missing_indices if index < count}
    candles = tuple(
        _candle(index, Decimal(index + 1)) for index in range(count) if index not in missing
    )
    gaps = tuple(
        GapRecord(UtcTimestamp(_START.value + timedelta(minutes=index)), GapReason.MISSING_SOURCE)
        for index in missing
    )

    value = _dataset(candles, count=count, gaps=gaps)

    assert len(value.candles) + len(value.gaps) == count
    assert value.quality is (DatasetQuality.INCOMPLETE if missing else DatasetQuality.VALID)
    assert tuple(sorted(value.gaps, key=lambda gap: gap.open_time)) == value.gaps
    assert not (
        {candle.open_time for candle in value.candles} & {gap.open_time for gap in value.gaps}
    )


def _decimal_text(coefficient: int, scale: int) -> Decimal:
    sign = "-" if coefficient < 0 else ""
    digits = str(abs(coefficient)).zfill(scale + 1)
    if scale == 0:
        return Decimal(f"{sign}{digits}")
    return Decimal(f"{sign}{digits[:-scale]}.{digits[-scale:]}")


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=999_999),
            st.integers(min_value=0, max_value=6),
            st.integers(min_value=0, max_value=999_999),
            st.integers(min_value=0, max_value=6),
        ),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=20, deadline=None)
def test_exact_decimal_values_round_trip_through_parquet(
    values: list[tuple[int, int, int, int]],
) -> None:
    candles = tuple(
        _candle(index, _decimal_text(price, price_scale), _decimal_text(volume, volume_scale))
        for index, (price, price_scale, volume, volume_scale) in enumerate(values)
    )
    original = _dataset(candles, count=len(candles))
    with TemporaryDirectory() as directory:
        store = LocalCanonicalDatasetStore((Path(directory) / original.version.value).resolve())
        store.publish(original)
        loaded = store.load(original.version)

        assert loaded.version == original.version
        assert loaded.candles == original.candles
