from hypothesis import given
from hypothesis import strategies as st

from command_station.domain import ProductId, Timeframe
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.market_data.resampling import resample_canonical_dataset
from command_station.runtime import ReferenceTradingRuntime, RuntimeEventKind, SimulatedClock
from tests.runtime_fixtures import canonical


def _runtime(feed: HistoricalReplayFeed) -> ReferenceTradingRuntime:
    return ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed)


@given(st.integers(min_value=1, max_value=20))
def test_generated_lengths_have_monotonic_clocks_and_final_end(minutes: int) -> None:
    source = canonical("BTC-USD", minutes)
    runtime = _runtime(HistoricalReplayFeed((source,)))
    timestamps = []
    while (result := runtime.step()) is not None:
        timestamps.append(result.timestamp)
    assert timestamps == sorted(timestamps)
    assert runtime.clock.now == source.end


@given(st.integers(min_value=1, max_value=12))
def test_visible_bars_never_close_after_clock(minutes: int) -> None:
    source = canonical("BTC-USD", minutes)
    runtime = _runtime(HistoricalReplayFeed((source,)))
    while runtime.step() is not None:
        for bar in runtime.market_view.recent_bars(ProductId("BTC-USD"), Timeframe.ONE_MINUTE, 100):
            assert bar.close_time <= runtime.clock.now


@given(st.integers(min_value=2, max_value=12))
def test_later_batch_bar_is_never_visible_early(minutes: int) -> None:
    source = canonical("BTC-USD", minutes)
    runtime = _runtime(HistoricalReplayFeed((source,)))
    runtime.step()
    visible = runtime.market_view.recent_bars(ProductId("BTC-USD"), Timeframe.ONE_MINUTE, 100)
    assert source.candles[1] not in visible


@given(st.booleans())
def test_source_permutations_preserve_batches_and_fingerprint(reverse: bool) -> None:
    btc, eth = canonical("BTC-USD", 5), canonical("ETH-USD", 5)
    ordered = (eth, btc) if reverse else (btc, eth)
    first, second = HistoricalReplayFeed((btc, eth)), HistoricalReplayFeed(ordered)
    assert tuple(first) == tuple(second)
    assert _runtime(first).run().trace_fingerprint == _runtime(second).run().trace_fingerprint


@given(st.integers(min_value=1, max_value=12))
def test_fresh_equivalent_runtimes_have_same_fingerprint(minutes: int) -> None:
    source = canonical("BTC-USD", minutes)
    assert (
        _runtime(HistoricalReplayFeed((source,))).run().trace_fingerprint
        == _runtime(HistoricalReplayFeed((source,))).run().trace_fingerprint
    )


@given(st.sampled_from([Timeframe.FIVE_MINUTES, Timeframe.FIFTEEN_MINUTES]))
def test_same_time_derived_stream_is_in_publication_before_ready(timeframe: Timeframe) -> None:
    minutes = int(timeframe.duration.total_seconds() // 60)
    source = canonical("BTC-USD", minutes)
    feed = HistoricalReplayFeed((source,), (resample_canonical_dataset(source, timeframe),))
    result = _runtime(feed).run()
    end_events = [event for event in result.trace_events if event.timestamp == feed.end]
    publication = next(
        event for event in end_events if event.kind is RuntimeEventKind.BARS_PUBLISHED
    )
    ready = next(event for event in end_events if event.kind is RuntimeEventKind.MARKET_STATE_READY)
    assert len(publication.market_refs) == 2
    assert publication.sequence < ready.sequence


@given(st.integers(min_value=1, max_value=12), st.integers(min_value=1, max_value=20))
def test_recent_history_obeys_positive_bound_and_chronological_order(
    minutes: int, limit: int
) -> None:
    source = canonical("BTC-USD", minutes)
    runtime = _runtime(HistoricalReplayFeed((source,)))
    runtime.run()
    bars = runtime.market_view.recent_bars(ProductId("BTC-USD"), Timeframe.ONE_MINUTE, limit)
    assert len(bars) <= limit
    assert tuple(bar.close_time for bar in bars) == tuple(sorted(bar.close_time for bar in bars))
