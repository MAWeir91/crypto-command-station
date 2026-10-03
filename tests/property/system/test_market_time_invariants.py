import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from command_station.domain import Candle, Timeframe
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.strategy import StrategyContext
from tests.execution_fixtures import timestamp
from tests.research_fixtures import BTC, NoTrade, setup


@given(end=st.integers(2, 9))
@settings(max_examples=6, deadline=None)
def test_generated_service_visibility_and_replay_clipping(end: int) -> None:
    class Visible(NoTrade):
        def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
            assert timestamp(1) <= ctx.clock.now <= timestamp(end)
            history = ctx.market.recent_bars(BTC, Timeframe.ONE_MINUTE, 20)
            assert all(b.close_time <= ctx.clock.now for b in history)
            assert tuple(b.open_time for b in history) == tuple(
                sorted({b.open_time for b in history})
            )
            assert history[-1] == bar

    with tempfile.TemporaryDirectory() as directory:
        service, spec = setup(Path(directory), Visible, end=end)
        source = service.datasets.load(spec.datasets[0].dataset_version)
        bounded = HistoricalReplayFeed((source,), replay_end=timestamp(end))
        assert bounded.canonical_sources[0].version == source.version
        assert len(tuple(bounded)) == end
        result = service.run(spec)
        assert result.execution_summary.fill_count == 0
        assert result.final_portfolio.timestamp == timestamp(end)
