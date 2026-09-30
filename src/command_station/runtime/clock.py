"""Deterministic simulation clock."""

from command_station.domain import UtcTimestamp


class RuntimeStateError(RuntimeError):
    pass


class SimulatedClock:
    def __init__(self, initial_time: UtcTimestamp) -> None:
        if not isinstance(initial_time, UtcTimestamp):
            raise RuntimeStateError("simulated clock requires an explicit UtcTimestamp")
        self._now = initial_time

    @property
    def now(self) -> UtcTimestamp:
        return self._now

    def advance_to(self, timestamp: UtcTimestamp) -> None:
        if not isinstance(timestamp, UtcTimestamp) or timestamp <= self._now:
            raise RuntimeStateError("simulated clock must advance strictly forward")
        self._now = timestamp
