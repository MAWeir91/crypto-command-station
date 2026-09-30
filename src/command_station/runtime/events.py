"""Closed deterministic trace records for the reference runtime."""

from dataclasses import dataclass
from enum import StrEnum

from command_station.domain import UtcTimestamp
from command_station.market_data.replay import BarReference


class RuntimeEventKind(StrEnum):
    RUNTIME_STARTED = "RUNTIME_STARTED"
    CLOCK_ADVANCED = "CLOCK_ADVANCED"
    MARKET_ACTIVITY = "MARKET_ACTIVITY"
    BARS_PUBLISHED = "BARS_PUBLISHED"
    MARKET_STATE_READY = "MARKET_STATE_READY"
    RUNTIME_STOPPED = "RUNTIME_STOPPED"


@dataclass(frozen=True, slots=True)
class RuntimeTraceEvent:
    sequence: int
    timestamp: UtcTimestamp
    kind: RuntimeEventKind
    market_refs: tuple[BarReference, ...] = ()

    def __post_init__(self) -> None:
        if self.sequence < 1 or not isinstance(self.timestamp, UtcTimestamp):
            raise ValueError("runtime trace event has invalid logical fields")
