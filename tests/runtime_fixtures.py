"""Small real domain fixtures for Phase 007 runtime tests."""

from datetime import UTC, datetime, timedelta

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.datasets import CanonicalCandleDataset, SourcePageReference


def canonical(product: str, minutes: int = 15, as_of_hour: int = 1) -> CanonicalCandleDataset:
    start = UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
    candles = tuple(
        Candle(
            ProductId(product),
            Timeframe.ONE_MINUTE,
            UtcTimestamp(start.value + timedelta(minutes=index)),
            UtcTimestamp(start.value + timedelta(minutes=index + 1)),
            "1",
            "1",
            "1",
            "1",
            "0",
        )
        for index in range(minutes)
    )
    return CanonicalCandleDataset(
        product_id=ProductId(product),
        start=start,
        end=UtcTimestamp(start.value + timedelta(minutes=minutes)),
        as_of=UtcTimestamp(start.value + timedelta(hours=as_of_hour)),
        candles=candles,
        gaps=(),
        source_pages=(SourcePageReference("a" * 64, "b" * 64),),
    )
