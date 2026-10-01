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
from command_station.domain import Side, UtcTimestamp, require_positive
from command_station.execution import (
    CancellationReason,
    Fill,
    NormalizedOrderRequest,
    OcoGroupId,
    Order,
    OrderId,
    OrderStatus,
    OrderType,
    SimulatedBroker,
    normalize_order_intent,
)
from command_station.market_data.datasets import canonical_json
from command_station.market_data.replay import BarReference, HistoricalReplayFeed, MarketReplayBatch
from command_station.risk import (
    RiskActivationResult,
    RiskDecisionStatus,
    RiskEngine,
    RiskOrderBinding,
    RiskStateSnapshot,
)
from command_station.runtime.clock import SimulatedClock
from command_station.runtime.events import RuntimeEventKind, RuntimeTraceEvent
from command_station.runtime.market import MarketView, _MarketState
from command_station.strategy import (
    StrategyActionResult,
    StrategyActionStatus,
    StrategyClockView,
    StrategyCommandKind,
    StrategyContext,
    StrategyContractError,
    StrategyMarketView,
    StrategyOrderCommand,
    StrategyOrderView,
    StrategyRunner,
)


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
    risk_decision_count: int = 0
    risk_fingerprint: str | None = None
    strategy_fingerprint: str | None = None


class ReferenceTradingRuntime:
    def __init__(
        self,
        *,
        clock: SimulatedClock,
        market_feed: HistoricalReplayFeed,
        broker: SimulatedBroker | None = None,
        accounting: SpotAccountingEngine | None = None,
        risk: RiskEngine | None = None,
        strategy_runner: StrategyRunner | None = None,
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
        if (accounting is None) != (risk is None):
            raise InvalidRuntimeConfigurationError(
                "financial runtime requires accounting and risk together"
            )
        if risk is not None and (not isinstance(risk, RiskEngine) or risk.decisions):
            raise InvalidRuntimeConfigurationError("runtime requires fresh RiskEngine")
        self.risk = risk
        self._risk_bindings: dict[OrderId, RiskOrderBinding] = {}
        self.accounting = accounting
        self._batches = tuple(market_feed)
        self._cursor = 0
        self._state = _MarketState.create()
        self._trace: list[RuntimeTraceEvent] = []
        self._lifecycle = RuntimeLifecycle.CREATED
        self._published_count = 0
        self.strategy_runner = strategy_runner
        if strategy_runner is not None:
            self._preflight_strategy()

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

    @property
    def risk_bindings(self) -> tuple[RiskOrderBinding, ...]:
        return tuple(self._risk_bindings[oid] for oid in sorted(self._risk_bindings))

    def activate_order(
        self, request: NormalizedOrderRequest, *, max_quote_reservation: Decimal | None = None
    ) -> RiskActivationResult:
        self._require_manual_orders()
        return self._authorize_and_activate((request,), max_quote_reservation)

    def activate_oco(
        self,
        first: NormalizedOrderRequest,
        second: NormalizedOrderRequest,
        *,
        max_quote_reservation: Decimal | None = None,
    ) -> RiskActivationResult:
        self._require_manual_orders()
        return self._authorize_and_activate((first, second), max_quote_reservation)

    def _authorize_and_activate(
        self, requests: tuple[NormalizedOrderRequest, ...], cap: Decimal | None
    ) -> RiskActivationResult:
        self._require_order_boundary()
        accounting = self._require_accounting()
        self._validate_financial_composition()
        assert self.risk is not None
        state = RiskStateSnapshot(
            self.clock.now,
            accounting.spec,
            accounting.account_view,
            accounting.positions,
            accounting.reservations,
            self.broker.orders,
            accounting.portfolio_snapshot,
            accounting.execution_spec,
        )
        authorization = self.risk.authorize(state, requests, max_quote_reservation=cap)
        if authorization.decision.status is RiskDecisionStatus.REJECT:
            return RiskActivationResult(authorization.decision, ())
        plan = authorization.reservation_plan
        approved = authorization.approved_requests
        assert plan is not None and plan.requests == approved
        orders: tuple[Order, ...]
        if len(approved) == 1:
            orders = (self.broker.activate(approved[0], self.clock.now),)
        else:
            orders = self.broker.activate_oco(approved[0], approved[1], self.clock.now)
        accounting.bind_reservation(plan, orders, self.clock.now)
        for request, order in zip(approved, orders, strict=True):
            reservation = next(r for r in accounting.reservations if order.order_id in r.order_ids)
            self._risk_bindings[order.order_id] = RiskOrderBinding(
                authorization.decision, request, order, reservation.reservation_id
            )
        return RiskActivationResult(authorization.decision, orders)

    def cancel_order(
        self,
        order_id: OrderId,
        reason: CancellationReason = CancellationReason.USER_REQUEST,
    ) -> Order:
        """Cancel an active order at the current safe runtime boundary."""
        self._require_manual_orders()
        return self._cancel_order(order_id, reason)

    def _cancel_order(self, order_id: OrderId, reason: CancellationReason) -> Order:
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
        self._require_manual_orders()
        return self._cancel_oco(group_id, reason)

    def _cancel_oco(self, group_id: OcoGroupId, reason: CancellationReason) -> tuple[Order, Order]:
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
            self._cursor += 1
            if self._cursor == len(self._batches):
                self._complete()
        except Exception as error:
            self._lifecycle = RuntimeLifecycle.FAILED
            if self.strategy_runner is not None:
                self.strategy_runner.failed = True
            if isinstance(error, RuntimeEngineError):
                raise
            raise RuntimeEngineError("reference runtime batch processing failed") from error
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
            len(self.risk.decisions) if self.risk else 0,
            self.risk.risk_fingerprint if self.risk else None,
            self.strategy_runner.fingerprint if self.strategy_runner else None,
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
        runner = self.strategy_runner
        if runner is not None:
            runner.indicators.update(batch.closing_bars, batch.timestamp)
            events.append(self._emit(RuntimeEventKind.INDICATORS_UPDATED, batch.timestamp))
            if runner.started:
                for fill in sorted(fills, key=lambda fill: fill.fill_id):
                    runner._invoke("on_fill", self._strategy_context(False), fill=fill)
            elif fills:
                raise RuntimeEngineError("strategy fills cannot occur before trading start")
            events.append(self._emit(RuntimeEventKind.FILL_CALLBACKS_PROCESSED, batch.timestamp))
        events.append(
            self._emit(RuntimeEventKind.MARKET_STATE_READY, batch.timestamp, published_refs)
        )
        if runner is not None and batch.timestamp >= runner.trading_start:
            if not runner.started:
                commands = runner._invoke("on_start", self._strategy_context(True))
                events.append(self._emit(RuntimeEventKind.STRATEGY_STARTED, batch.timestamp))
                self._process_strategy_commands(commands)
                events.append(
                    self._emit(RuntimeEventKind.STRATEGY_COMMANDS_PROCESSED, batch.timestamp)
                )
            primary = runner.definition.primary
            bar = next(
                (
                    bar
                    for bar in batch.closing_bars
                    if (bar.product_id, bar.timeframe) == primary.key
                ),
                None,
            )
            if bar is not None:
                commands = runner._invoke("on_bar", self._strategy_context(True), bar=bar)
                events.append(
                    self._emit(RuntimeEventKind.STRATEGY_DECISION_PROCESSED, batch.timestamp)
                )
                self._process_strategy_commands(commands)
                events.append(
                    self._emit(RuntimeEventKind.STRATEGY_COMMANDS_PROCESSED, batch.timestamp)
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
            if self.risk is None:
                raise RuntimeEngineError("financial runtime lost risk authority")
            for order in self.broker.orders:
                if (
                    self.strategy_runner is not None
                    and order.order_id not in self.strategy_runner.owned_order_ids
                ):
                    raise RuntimeEngineError("broker order has no strategy attribution")
                binding = self._risk_bindings.get(order.order_id)
                if binding is None:
                    raise RuntimeEngineError("broker order has no risk authorization")
                decision, request, original = (
                    binding.decision,
                    binding.approved_request,
                    binding.original_order,
                )
                if (
                    decision not in self.risk.decisions
                    or decision.status is RiskDecisionStatus.REJECT
                ):
                    raise RuntimeEngineError("broker order lost risk decision")
                reservation = next(
                    (
                        r
                        for r in self.accounting.reservations
                        if r.reservation_id == binding.reservation_id
                    ),
                    None,
                )
                if reservation is None or order.order_id not in reservation.order_ids:
                    raise RuntimeEngineError("risk reservation/order binding mismatch")
                names = (
                    "product_id",
                    "base_currency",
                    "quote_currency",
                    "side",
                    "order_type",
                    "requested_base_quantity",
                    "activated_base_quantity",
                    "limit_price",
                    "stop_price",
                    "created_at",
                    "activated_at",
                    "product_spec_fingerprint",
                    "oco_group_id",
                )
                if any(getattr(order, name) != getattr(original, name) for name in names):
                    raise RuntimeEngineError("broker order differs from authorized activation")
                if (
                    original.activated_base_quantity != request.normalized_base_quantity
                    or original.product_id != decision.product_id
                    or original.activated_at != decision.timestamp
                ):
                    raise RuntimeEngineError("risk request/order binding mismatch")
            self.accounting.validate_boundary(self.clock.now, self.broker.orders)

    def _require_order_boundary(self) -> None:
        if self._lifecycle in (RuntimeLifecycle.COMPLETED, RuntimeLifecycle.FAILED):
            raise RuntimeEngineError("orders cannot change after runtime termination")

    def _complete(self) -> None:
        if self._lifecycle is RuntimeLifecycle.RUNNING:
            if self.strategy_runner is not None:
                self.strategy_runner._invoke("on_stop", self._strategy_context(False))
                self._emit(RuntimeEventKind.STRATEGY_STOPPED, self.clock.now)
            self._emit(RuntimeEventKind.RUNTIME_STOPPED, self.clock.now)
            self._lifecycle = RuntimeLifecycle.COMPLETED

    def _require_manual_orders(self) -> None:
        if self.strategy_runner is not None:
            raise RuntimeEngineError("strategy runtime accepts only attributed callback commands")

    def _preflight_strategy(self) -> None:
        runner = self.strategy_runner
        if not isinstance(runner, StrategyRunner) or self.accounting is None or self.risk is None:
            raise InvalidRuntimeConfigurationError(
                "strategy runtime requires runner/accounting/risk"
            )
        counts = {sub.key: 0 for sub in runner.definition.subscriptions}
        primary_at_start = False
        streams = {
            (source.product_id, source.timeframe) for source in self.market_feed.canonical_sources
        }
        streams.update(
            (source.product_id, source.target_timeframe)
            for source in self.market_feed.derived_sources
        )
        products = {spec.product_id for spec in self.accounting.spec.product_specs}
        if (
            not self.market_feed.start < runner.trading_start <= self.market_feed.end
            or set(counts) - streams
            or {sub.product_id for sub in runner.definition.subscriptions} - products
        ):
            raise InvalidRuntimeConfigurationError(
                "strategy subscription/trading start incompatible"
            )
        for batch in self._batches:
            if batch.timestamp > runner.trading_start:
                break
            for bar in batch.closing_bars:
                key = (bar.product_id, bar.timeframe)
                if key in counts:
                    counts[key] += 1
                if batch.timestamp == runner.trading_start and key == runner.definition.primary.key:
                    primary_at_start = True
        if (
            not primary_at_start
            or any(counts[sub.key] < sub.warmup_bars for sub in runner.definition.subscriptions)
            or any(
                counts[(spec.product_id, spec.timeframe)] < spec.period
                for spec in runner.definition.indicators
            )
        ):
            raise InvalidRuntimeConfigurationError(
                "trading start lacks primary close/sufficient warmup"
            )
        try:
            runner._attach()
        except StrategyContractError as error:
            raise InvalidRuntimeConfigurationError(str(error)) from error

    def _strategy_context(self, commands_allowed: bool) -> StrategyContext:
        runner = self.strategy_runner
        assert runner is not None and self.accounting is not None
        market = self.market_view
        subscriptions = runner.definition.subscriptions
        # Copy only subscribed published value tuples, not even the unrestricted MarketView.
        streams = tuple(
            (
                sub.product_id,
                sub.timeframe,
                market.recent_bars(sub.product_id, sub.timeframe, self._published_count or 1),
            )
            for sub in subscriptions
        )
        products = tuple(
            spec
            for spec in self.accounting.spec.product_specs
            if spec.product_id in {sub.product_id for sub in subscriptions}
        )
        orders = tuple(
            order for order in self.broker.orders if order.order_id in runner.owned_order_ids
        )
        return StrategyContext(
            StrategyClockView(self.clock.now),
            StrategyMarketView(market.visible_through, streams, products),
            runner.parameters,
            runner.state,
            runner.indicators.view,
            self.accounting.account_view,
            self.accounting.positions,
            self.accounting.portfolio_snapshot,
            StrategyOrderView(
                self.clock.now,
                runner._next_command,
                commands_allowed,
                orders,
                runner.action_results,
            ),
        )

    def _process_strategy_commands(self, commands: tuple[StrategyOrderCommand, ...]) -> None:
        """Prevalidate whole callback, then commit sequentially against current financial truth."""
        runner = self.strategy_runner
        accounting = self._require_accounting()
        assert runner is not None
        prepared: list[tuple[StrategyOrderCommand, tuple[NormalizedOrderRequest, ...]]] = []
        cancelled_ids: set[OrderId] = set()
        products = {spec.product_id: spec for spec in accounting.spec.product_specs}
        subscribed = {sub.product_id for sub in runner.definition.subscriptions}
        for command in commands:
            if command.timestamp != self.clock.now:
                raise StrategyContractError("command timestamp must equal callback time")
            requests: tuple[NormalizedOrderRequest, ...] = ()
            if command.kind in (StrategyCommandKind.ENTRY, StrategyCommandKind.OCO):
                if (
                    len(command.intents) != (1 if command.kind is StrategyCommandKind.ENTRY else 2)
                    or command.order_id is not None
                    or command.group_id is not None
                ):
                    raise StrategyContractError("invalid entry shape")
                if any(
                    intent.product_id not in subscribed or intent.created_at != self.clock.now
                    for intent in command.intents
                ):
                    raise StrategyContractError("intent product/time outside callback authority")
                requests = tuple(
                    normalize_order_intent(intent, products[intent.product_id])
                    for intent in command.intents
                )
                needs_cap = requests[0].side is Side.BUY and (
                    len(requests) == 2 or requests[0].order_type is not OrderType.LIMIT
                )
                if needs_cap != (command.max_quote_reservation is not None):
                    raise StrategyContractError("invalid command funding cap")
                if command.max_quote_reservation is not None:
                    require_positive(command.max_quote_reservation)
                if len(requests) == 2:
                    self.broker._validate_oco_requests(requests[0], requests[1])
                for request in requests:
                    self.broker._validate_activation(request, self.clock.now)
            else:
                if command.intents or command.max_quote_reservation is not None:
                    raise StrategyContractError("cancellation cannot carry entry fields")
                peers: tuple[Order, ...]
                if command.kind is StrategyCommandKind.CANCEL:
                    if (
                        command.order_id not in runner.owned_order_ids
                        or command.group_id is not None
                    ):
                        raise StrategyContractError("cancel requires attributed order")
                    assert command.order_id is not None
                    peers = (self.broker.get_order(command.order_id),)
                    if peers[0].oco_group_id is not None:
                        raise StrategyContractError("cancel OCO as a group")
                elif command.kind is StrategyCommandKind.CANCEL_OCO:
                    if command.group_id is None or command.order_id is not None:
                        raise StrategyContractError("cancel OCO requires group identity")
                    peers = tuple(
                        order
                        for order in self.broker.orders
                        if order.oco_group_id == command.group_id
                    )
                    if len(peers) != 2 or any(
                        order.order_id not in runner.owned_order_ids for order in peers
                    ):
                        raise StrategyContractError("cancel OCO requires attributed peers")
                else:
                    raise StrategyContractError("unsupported command")
                for order in peers:
                    if order.order_id in cancelled_ids:
                        raise StrategyContractError("duplicate callback cancellation")
                    order.cancel(self.clock.now, CancellationReason.USER_REQUEST)
                    accounting.require_reserved_order(order.order_id)
                    cancelled_ids.add(order.order_id)
            prepared.append((command, requests))
        for command, requests in prepared:
            if requests:
                activated = self._authorize_and_activate(requests, command.max_quote_reservation)
                status = (
                    StrategyActionStatus.REJECTED
                    if activated.decision.status is RiskDecisionStatus.REJECT
                    else StrategyActionStatus.ACTIVATED
                )
                result = StrategyActionResult(
                    command.command_id,
                    self.clock.now,
                    command.kind,
                    status,
                    activated.decision,
                    tuple(order.order_id for order in activated.orders),
                )
            else:
                cancelled: tuple[Order, ...]
                if command.kind is StrategyCommandKind.CANCEL:
                    assert command.order_id is not None
                    cancelled = (
                        self._cancel_order(command.order_id, CancellationReason.USER_REQUEST),
                    )
                else:
                    assert command.group_id is not None
                    cancelled = self._cancel_oco(command.group_id, CancellationReason.USER_REQUEST)
                result = StrategyActionResult(
                    command.command_id,
                    self.clock.now,
                    command.kind,
                    StrategyActionStatus.CANCELLED,
                    None,
                    tuple(order.order_id for order in cancelled),
                    cancelled,
                )
            runner._record_result(result)

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
