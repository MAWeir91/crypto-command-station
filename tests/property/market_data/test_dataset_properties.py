from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.datasets import CanonicalCandleDataset, SourcePageReference


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
