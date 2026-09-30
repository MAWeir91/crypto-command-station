import pytest

from command_station.domain import ProductId, Timeframe
from command_station.market_data.replay import HistoricalReplayFeed, ReplayDataError
from command_station.market_data.resampling import resample_canonical_dataset
from command_station.runtime import ReferenceTradingRuntime, SimulatedClock
from tests.runtime_fixtures import canonical


def _runtime(feed: HistoricalReplayFeed) -> ReferenceTradingRuntime:
    return ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed)


def test_real_canonical_and_resampled_streams_publish_atomically() -> None:
    source = canonical("BTC-USD", minutes=15)
    feed = HistoricalReplayFeed(
        (source,),
        (
            resample_canonical_dataset(source, Timeframe.FIVE_MINUTES),
            resample_canonical_dataset(source, Timeframe.FIFTEEN_MINUTES),
        ),
    )
    result = _runtime(feed).run()
    assert result.published_bar_count == 19


def test_multi_product_source_order_does_not_change_trace() -> None:
    btc, eth = canonical("BTC-USD", minutes=5), canonical("ETH-USD", minutes=5)
    first = _runtime(HistoricalReplayFeed((btc, eth))).run()
    second = _runtime(HistoricalReplayFeed((eth, btc))).run()
    assert first.trace_fingerprint == second.trace_fingerprint


def test_step_then_run_does_not_leak_future_bars() -> None:
    source = canonical("BTC-USD", minutes=5)
    feed = HistoricalReplayFeed((source,))
    runtime = _runtime(feed)
    step = runtime.step()
    assert step is not None
    assert (
        runtime.market_view.latest_bar(ProductId("BTC-USD"), Timeframe.ONE_MINUTE)
        == source.candles[0]
    )
    assert runtime.run().final_clock == feed.end


def test_equivalent_fresh_runtimes_are_deterministic() -> None:
    source = canonical("BTC-USD", minutes=5)
    first = _runtime(HistoricalReplayFeed((source,))).run()
    second = _runtime(HistoricalReplayFeed((source,))).run()
    assert first.trace_events == second.trace_events
    assert first.trace_fingerprint == second.trace_fingerprint


def test_invalid_derived_source_is_rejected_before_execution() -> None:
    source = canonical("BTC-USD", minutes=5)
    foreign = canonical("BTC-USD", minutes=5, as_of_hour=2)
    with pytest.raises(ReplayDataError):
        HistoricalReplayFeed(
            (source,), (resample_canonical_dataset(foreign, Timeframe.FIVE_MINUTES),)
        )
