from datetime import UTC, datetime, timedelta

import pytest

from command_station.domain import UtcTimestamp
from command_station.runtime import RuntimeStateError, SimulatedClock


def test_clock_moves_strictly_forward_and_is_instance_scoped() -> None:
    start = UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
    later = UtcTimestamp(start.value + timedelta(minutes=1))
    first, second = SimulatedClock(start), SimulatedClock(start)

    first.advance_to(later)

    assert first.now == later
    assert second.now == start
    with pytest.raises(RuntimeStateError):
        first.advance_to(later)
