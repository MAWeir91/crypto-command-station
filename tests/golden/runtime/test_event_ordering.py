from command_station.domain import ProductId, Timeframe
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.market_data.resampling import resample_canonical_dataset
from command_station.runtime import ReferenceTradingRuntime, RuntimeEventKind, SimulatedClock
from tests.runtime_fixtures import canonical


def test_golden_visibility_and_exact_stage_order() -> None:
    source = canonical("BTC-USD", minutes=5)
    feed = HistoricalReplayFeed(
        (source,), (resample_canonical_dataset(source, Timeframe.FIVE_MINUTES),)
    )
    runtime = ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed)

    assert runtime.market_view.visible_through is None
    assert runtime.market_view.latest_bar(ProductId("BTC-USD"), Timeframe.ONE_MINUTE) is None
    first = runtime.step()

    assert first is not None
    assert [event.kind for event in first.trace_events] == [
        RuntimeEventKind.CLOCK_ADVANCED,
        RuntimeEventKind.MARKET_ACTIVITY,
        RuntimeEventKind.BARS_PUBLISHED,
        RuntimeEventKind.MARKET_STATE_READY,
    ]
    assert runtime.market_view.visible_through == first.timestamp
    assert (
        runtime.market_view.latest_bar(ProductId("BTC-USD"), Timeframe.ONE_MINUTE)
        == source.candles[0]
    )
    assert runtime.market_view.recent_bars(ProductId("BTC-USD"), Timeframe.ONE_MINUTE, 5) == (
        source.candles[0],
    )


def test_golden_same_time_derived_bars_are_published_together() -> None:
    source = canonical("BTC-USD", minutes=15)
    feed = HistoricalReplayFeed(
        (source,),
        (
            resample_canonical_dataset(source, Timeframe.FIVE_MINUTES),
            resample_canonical_dataset(source, Timeframe.FIFTEEN_MINUTES),
        ),
    )
    runtime = ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed)

    result = runtime.run()
    publication = [
        event
        for event in result.trace_events
        if event.kind is RuntimeEventKind.BARS_PUBLISHED and event.timestamp == feed.end
    ][0]

    assert [reference.timeframe for reference in publication.market_refs] == [
        Timeframe.ONE_MINUTE,
        Timeframe.FIVE_MINUTES,
        Timeframe.FIFTEEN_MINUTES,
    ]
