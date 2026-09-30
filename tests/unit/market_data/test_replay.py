import pytest

from command_station.domain import Timeframe
from command_station.market_data.replay import HistoricalReplayFeed, ReplayDataError
from command_station.market_data.resampling import resample_canonical_dataset
from tests.runtime_fixtures import canonical


def test_replay_is_reiterable_and_uses_one_minute_cadence() -> None:
    source = canonical("BTC-USD", minutes=5)
    feed = HistoricalReplayFeed((source,))

    first, second = tuple(feed), tuple(feed)

    assert first == second
    assert len(first) == 5
    assert all(len(batch.execution_intervals) == 1 for batch in first)
    assert all(batch.execution_intervals[0] in batch.closing_bars for batch in first)


def test_replay_rejects_duplicate_canonical_product() -> None:
    source = canonical("BTC-USD", minutes=5)
    with pytest.raises(ReplayDataError, match="duplicate"):
        HistoricalReplayFeed((source, source))


def test_replay_rejects_foreign_derived_dataset_version() -> None:
    source = canonical("BTC-USD", minutes=5)
    foreign = canonical("BTC-USD", minutes=5, as_of_hour=2)
    derived = resample_canonical_dataset(foreign, Timeframe.FIVE_MINUTES)

    with pytest.raises(ReplayDataError, match="exact canonical"):
        HistoricalReplayFeed((source,), (derived,))
