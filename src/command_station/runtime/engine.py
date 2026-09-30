"""Inspectable deterministic reference market-time runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from command_station.domain import UtcTimestamp
from command_station.market_data.datasets import canonical_json
from command_station.market_data.replay import BarReference, HistoricalReplayFeed, MarketReplayBatch
from command_station.runtime.clock import SimulatedClock
from command_station.runtime.events import RuntimeEventKind, RuntimeTraceEvent
from command_station.runtime.market import MarketView, _MarketState


class InvalidRuntimeConfigurationError(ValueError):
    pass


class RuntimeEngineError(RuntimeError):
    pass


class RuntimeLifecycle(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RuntimeStepResult:
    timestamp: UtcTimestamp
    execution_intervals: tuple[BarReference, ...]
    published_bars: tuple[BarReference, ...]
    trace_events: tuple[RuntimeTraceEvent, ...]


@dataclass(frozen=True, slots=True)
class ReferenceRuntimeResult:
    start: UtcTimestamp
    end: UtcTimestamp
    final_clock: UtcTimestamp
    batch_count: int
    published_bar_count: int
    trace_events: tuple[RuntimeTraceEvent, ...]
    trace_fingerprint: str


class ReferenceTradingRuntime:
    def __init__(self, *, clock: SimulatedClock, market_feed: HistoricalReplayFeed) -> None:
        if not isinstance(clock, SimulatedClock) or not isinstance(
            market_feed, HistoricalReplayFeed
        ):
            raise InvalidRuntimeConfigurationError(
                "runtime requires SimulatedClock and HistoricalReplayFeed"
            )
        if clock.now != market_feed.start:
            raise InvalidRuntimeConfigurationError("clock must start at replay feed start")
        self.clock, self.market_feed = clock, market_feed
        self._batches = tuple(market_feed)
        self._cursor = 0
        self._state = _MarketState.create()
        self._trace: list[RuntimeTraceEvent] = []
        self._lifecycle = RuntimeLifecycle.CREATED
        self._published_count = 0

    @property
    def lifecycle(self) -> RuntimeLifecycle:
        return self._lifecycle

    @property
    def trace_events(self) -> tuple[RuntimeTraceEvent, ...]:
        return tuple(self._trace)

    @property
    def market_view(self) -> MarketView:
        """Return a current immutable market snapshot, never runtime-owned state."""
        return self._state.snapshot()

    @property
    def trace_fingerprint(self) -> str:
        return _fingerprint(self.trace_events)

    def step(self) -> RuntimeStepResult | None:
        if self._lifecycle is RuntimeLifecycle.COMPLETED:
            return None
        if self._lifecycle is RuntimeLifecycle.FAILED:
            raise RuntimeEngineError("failed runtime cannot continue")
        if self._lifecycle is RuntimeLifecycle.CREATED:
            self._lifecycle = RuntimeLifecycle.RUNNING
            self._emit(RuntimeEventKind.RUNTIME_STARTED, self.clock.now)
        if self._cursor == len(self._batches):
            self._complete()
            return None
        batch = self._batches[self._cursor]
        try:
            result = self._process(batch)
        except Exception as error:
            self._lifecycle = RuntimeLifecycle.FAILED
            if isinstance(error, RuntimeEngineError):
                raise
            raise RuntimeEngineError("reference runtime batch processing failed") from error
        self._cursor += 1
        if self._cursor == len(self._batches):
            self._complete()
        return result

    def run(self) -> ReferenceRuntimeResult:
        while self.step() is not None:
            pass
        if self._lifecycle is not RuntimeLifecycle.COMPLETED:
            raise RuntimeEngineError("runtime did not complete")
        return ReferenceRuntimeResult(
            self.market_feed.start,
            self.market_feed.end,
            self.clock.now,
            self._cursor,
            self._published_count,
            self.trace_events,
            self.trace_fingerprint,
        )

    def _process(self, batch: MarketReplayBatch) -> RuntimeStepResult:
        self.clock.advance_to(batch.timestamp)
        events: list[RuntimeTraceEvent] = []
        events.append(self._emit(RuntimeEventKind.CLOCK_ADVANCED, batch.timestamp))
        execution_refs = tuple(
            BarReference.from_candle(value) for value in batch.execution_intervals
        )
        events.append(self._emit(RuntimeEventKind.MARKET_ACTIVITY, batch.timestamp, execution_refs))
        published_refs = tuple(BarReference.from_candle(value) for value in batch.closing_bars)
        self._state.publish(batch.timestamp, batch.closing_bars)
        self._published_count += len(batch.closing_bars)
        events.append(self._emit(RuntimeEventKind.BARS_PUBLISHED, batch.timestamp, published_refs))
        events.append(
            self._emit(RuntimeEventKind.MARKET_STATE_READY, batch.timestamp, published_refs)
        )
        return RuntimeStepResult(batch.timestamp, execution_refs, published_refs, tuple(events))

    def _complete(self) -> None:
        if self._lifecycle is RuntimeLifecycle.RUNNING:
            self._emit(RuntimeEventKind.RUNTIME_STOPPED, self.clock.now)
            self._lifecycle = RuntimeLifecycle.COMPLETED

    def _emit(
        self, kind: RuntimeEventKind, timestamp: UtcTimestamp, refs: tuple[BarReference, ...] = ()
    ) -> RuntimeTraceEvent:
        event = RuntimeTraceEvent(len(self._trace) + 1, timestamp, kind, refs)
        self._trace.append(event)
        return event


def _fingerprint(events: tuple[RuntimeTraceEvent, ...]) -> str:
    content = {
        "trace_schema_version": 1,
        "events": [
            {
                "sequence": event.sequence,
                "timestamp": str(event.timestamp),
                "kind": event.kind.value,
                "market_refs": [
                    {
                        "product_id": ref.product_id.value,
                        "timeframe": ref.timeframe.value,
                        "open_time": str(ref.open_time),
                        "close_time": str(ref.close_time),
                    }
                    for ref in event.market_refs
                ],
            }
            for event in events
        ],
    }
    return sha256(canonical_json(content)).hexdigest()
