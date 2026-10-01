"""Inspectable deterministic reference market-time runtime."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from command_station.accounting import (
    AccountView,
    LedgerTransaction,
    PortfolioSnapshot,
    PositionView,
    SpotAccountingEngine,
)
from command_station.domain import UtcTimestamp
from command_station.execution import (
    CancellationReason,
    Fill,
    NormalizedOrderRequest,
    OcoGroupId,
    Order,
    OrderId,
    OrderStatus,
    SimulatedBroker,
)
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
    fills: tuple[Fill, ...]
    trace_events: tuple[RuntimeTraceEvent, ...]
    ledger_transactions_created: tuple[LedgerTransaction, ...] = ()
    account_view: AccountView | None = None
    position_views: tuple[PositionView, ...] = ()
    portfolio_snapshot: PortfolioSnapshot | None = None


@dataclass(frozen=True, slots=True)
class ReferenceRuntimeResult:
    start: UtcTimestamp
    end: UtcTimestamp
    final_clock: UtcTimestamp
    batch_count: int
    published_bar_count: int
    fill_count: int
    trace_events: tuple[RuntimeTraceEvent, ...]
    trace_fingerprint: str
    execution_fingerprint: str
    ledger_transaction_count: int = 0
    accounting_fingerprint: str | None = None
    final_account_view: AccountView | None = None
    final_positions: tuple[PositionView, ...] = ()
    final_portfolio_snapshot: PortfolioSnapshot | None = None


class ReferenceTradingRuntime:
    def __init__(
        self,
        *,
        clock: SimulatedClock,
        market_feed: HistoricalReplayFeed,
        broker: SimulatedBroker | None = None,
        accounting: SpotAccountingEngine | None = None,
    ) -> None:
        if not isinstance(clock, SimulatedClock) or not isinstance(
            market_feed, HistoricalReplayFeed
        ):
            raise InvalidRuntimeConfigurationError(
                "runtime requires SimulatedClock and HistoricalReplayFeed"
            )
        if clock.now != market_feed.start:
            raise InvalidRuntimeConfigurationError("clock must start at replay feed start")
        if broker is not None and not isinstance(broker, SimulatedBroker):
            raise InvalidRuntimeConfigurationError("runtime broker must be SimulatedBroker")
        self.clock, self.market_feed = clock, market_feed
        self.broker = broker if broker is not None else SimulatedBroker()
        if self.broker.orders or self.broker.fills:
            raise InvalidRuntimeConfigurationError(
                "runtime requires fresh broker without orders/fills"
            )
        if accounting is not None:
            if (
                not isinstance(accounting, SpotAccountingEngine)
                or accounting.start != market_feed.start
            ):
                raise InvalidRuntimeConfigurationError("accounting must start at replay feed start")
            if {p.product_id for p in accounting.spec.product_specs} != {
                s.product_id for s in market_feed.canonical_sources
            }:
                raise InvalidRuntimeConfigurationError(
                    "account products must exactly cover canonical replay products"
                )
            if (
                accounting.execution_spec != self.broker.spec
                or accounting.reservations
                or accounting.applied_fill_ids
                or accounting.portfolio_history
            ):
                raise InvalidRuntimeConfigurationError(
                    "runtime requires fresh compatible accounting"
                )
        self.accounting = accounting
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

    def activate_order(
        self, request: NormalizedOrderRequest, *, max_quote_reservation: Decimal | None = None
    ) -> Order:
        """Activate at the current safe between-batch runtime boundary."""
        self._require_order_boundary()
        accounting = self._require_accounting()
        self._validate_financial_composition()
        plan = accounting.prepare_reservation(
            (request,), max_quote_reservation=max_quote_reservation
        )
        order = self.broker.activate(request, self.clock.now)
        accounting.bind_reservation(plan, (order,), self.clock.now)
        return order

    def activate_oco(
        self,
        first: NormalizedOrderRequest,
        second: NormalizedOrderRequest,
        *,
        max_quote_reservation: Decimal | None = None,
    ) -> tuple[Order, Order]:
        """Activate an exclusive pair at the current safe runtime boundary."""
        self._require_order_boundary()
        accounting = self._require_accounting()
        self._validate_financial_composition()
        plan = accounting.prepare_reservation(
            (first, second), max_quote_reservation=max_quote_reservation
        )
        orders = self.broker.activate_oco(first, second, self.clock.now)
        accounting.bind_reservation(plan, orders, self.clock.now)
        return orders

    def cancel_order(
        self,
        order_id: OrderId,
        reason: CancellationReason = CancellationReason.USER_REQUEST,
    ) -> Order:
        """Cancel an active order at the current safe runtime boundary."""
        self._require_order_boundary()
        accounting = self._require_accounting()
        self._validate_financial_composition()
        accounting.require_reserved_order(order_id)
        order = self.broker.get_order(order_id)
        if order.oco_group_id is not None:
            raise RuntimeEngineError(
                "OCO cancellation requires cancelling the whole exclusive group"
            )
        cancelled = self.broker.cancel(order_id, self.clock.now, reason)
        accounting.apply_fill_batch((), self.broker.orders, self.clock.now)
        return cancelled

    def cancel_oco(
        self, group_id: OcoGroupId, reason: CancellationReason = CancellationReason.USER_REQUEST
    ) -> tuple[Order, Order]:
        """Cancel both exclusive peers together; never leave a one-peer OCO."""
        self._require_order_boundary()
        accounting = self._require_accounting()
        self._validate_financial_composition()
        peers = tuple(order for order in self.broker.orders if order.oco_group_id == group_id)
        if (
            not isinstance(group_id, OcoGroupId)
            or len(peers) != 2
            or any(
                order.status not in (OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED)
                for order in peers
            )
        ):
            raise RuntimeEngineError("OCO cancellation requires two active peers")
        reservation = next(
            (
                r
                for r in accounting.reservations
                if r.order_ids == tuple(sorted(o.order_id for o in peers))
            ),
            None,
        )
        if reservation is None:
            raise RuntimeEngineError("OCO has no shared reservation")
        for order in peers:
            accounting.require_reserved_order(order.order_id)
            order.cancel(self.clock.now, reason)  # Validate both before broker mutation.
        first = self.broker.cancel(peers[0].order_id, self.clock.now, reason)
        second = self.broker.cancel(peers[1].order_id, self.clock.now, reason)
        accounting.apply_fill_batch((), self.broker.orders, self.clock.now)
        return first, second

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
            len(self.broker.fills),
            self.trace_events,
            self.trace_fingerprint,
            self.broker.execution_fingerprint,
            len(self.accounting.ledger) if self.accounting else 0,
            self.accounting.accounting_fingerprint if self.accounting else None,
            self.accounting.account_view if self.accounting else None,
            self.accounting.positions if self.accounting else (),
            self.accounting.portfolio_snapshot if self.accounting else None,
        )

    def _process(self, batch: MarketReplayBatch) -> RuntimeStepResult:
        self._validate_financial_composition()
        self.clock.advance_to(batch.timestamp)
        events: list[RuntimeTraceEvent] = []
        events.append(self._emit(RuntimeEventKind.CLOCK_ADVANCED, batch.timestamp))
        execution_refs = tuple(
            BarReference.from_candle(value) for value in batch.execution_intervals
        )
        events.append(self._emit(RuntimeEventKind.MARKET_ACTIVITY, batch.timestamp, execution_refs))
        fills = self.broker.process_market_activity(batch.execution_intervals, batch.timestamp)
        events.append(
            self._emit(RuntimeEventKind.EXECUTION_PROCESSED, batch.timestamp, execution_refs)
        )
        ledger_transactions: tuple[LedgerTransaction, ...] = ()
        portfolio: PortfolioSnapshot | None = None
        if self.accounting is not None:
            ledger_transactions = self.accounting.apply_fill_batch(
                fills, self.broker.orders, batch.timestamp
            )
            events.append(self._emit(RuntimeEventKind.ACCOUNTING_APPLIED, batch.timestamp))
            portfolio = self.accounting.update_portfolio(batch.execution_intervals, batch.timestamp)
            events.append(self._emit(RuntimeEventKind.PORTFOLIO_UPDATED, batch.timestamp))
        published_refs = tuple(BarReference.from_candle(value) for value in batch.closing_bars)
        self._state.publish(batch.timestamp, batch.closing_bars)
        self._published_count += len(batch.closing_bars)
        events.append(self._emit(RuntimeEventKind.BARS_PUBLISHED, batch.timestamp, published_refs))
        events.append(
            self._emit(RuntimeEventKind.MARKET_STATE_READY, batch.timestamp, published_refs)
        )
        return RuntimeStepResult(
            batch.timestamp,
            execution_refs,
            published_refs,
            fills,
            tuple(events),
            ledger_transactions,
            self.accounting.account_view if self.accounting else None,
            self.accounting.positions if self.accounting else (),
            portfolio,
        )

    def _require_accounting(self) -> SpotAccountingEngine:
        if self.accounting is None:
            raise RuntimeEngineError("order operations require spot accounting")
        return self.accounting

    def _validate_financial_composition(self) -> None:
        if self.accounting is None:
            if self.broker.orders or self.broker.fills:
                raise RuntimeEngineError("market-only runtime cannot process orders/fills")
        else:
            if self.broker.spec != self.accounting.execution_spec:
                raise RuntimeEngineError("broker/accounting execution specification changed")
            if self.broker.fills != self.accounting.applied_fills:
                raise RuntimeEngineError("broker contains unaccounted Fill facts")
            self.accounting.validate_boundary(self.clock.now, self.broker.orders)

    def _require_order_boundary(self) -> None:
        if self._lifecycle in (RuntimeLifecycle.COMPLETED, RuntimeLifecycle.FAILED):
            raise RuntimeEngineError("orders cannot change after runtime termination")

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
