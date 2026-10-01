from datetime import UTC, datetime, timedelta

import pytest

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.datasets import CanonicalCandleDataset, SourcePageReference
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.market_data.resampling import resample_canonical_dataset
from command_station.runtime import (
    InvalidRuntimeConfigurationError,
    ReferenceTradingRuntime,
    RuntimeEventKind,
    SimulatedClock,
)


def _canonical(product: str) -> CanonicalCandleDataset:
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
        for index in range(5)
    )
    return CanonicalCandleDataset(
        product_id=ProductId(product),
        start=start,
        end=UtcTimestamp(start.value + timedelta(minutes=5)),
        as_of=UtcTimestamp(start.value + timedelta(hours=1)),
        candles=candles,
        gaps=(),
        source_pages=(SourcePageReference("a" * 64, "b" * 64),),
    )


def test_step_keeps_market_activity_before_atomic_publication() -> None:
    source = _canonical("BTC-USD")
    feed = HistoricalReplayFeed(
        (source,), (resample_canonical_dataset(source, Timeframe.FIVE_MINUTES),)
    )
    runtime = ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed)

    step = runtime.step()

    assert step is not None
    assert [event.kind for event in step.trace_events] == [
        RuntimeEventKind.CLOCK_ADVANCED,
        RuntimeEventKind.MARKET_ACTIVITY,
        RuntimeEventKind.EXECUTION_PROCESSED,
        RuntimeEventKind.BARS_PUBLISHED,
        RuntimeEventKind.MARKET_STATE_READY,
    ]
    assert runtime.market_view.visible_through == step.timestamp
    assert runtime.market_view.latest_price(ProductId("BTC-USD")) == 1


def test_runtime_rejects_wrong_clock_start_and_does_not_reset_after_completion() -> None:
    source = _canonical("BTC-USD")
    feed = HistoricalReplayFeed((source,))
    with pytest.raises(InvalidRuntimeConfigurationError):
        ReferenceTradingRuntime(
            clock=SimulatedClock(source.candles[0].close_time), market_feed=feed
        )

    runtime = ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed)
    result = runtime.run()
    assert runtime.step() is None
    assert runtime.run() == result
