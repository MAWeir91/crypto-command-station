"""Single financial authority: staged append-only spot accounting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal

from command_station.accounting._exact import ZERO, add, fee, fingerprint, mul, neg, sub
from command_station.accounting.ledger import replay_ledger
from command_station.accounting.models import (
    ACCOUNTING_FINGERPRINT_SCHEMA_VERSION,
    ACCOUNTING_MODEL_VERSION,
    LEDGER_SCHEMA_VERSION,
    LOT_DEPLETION_POLICY,
    USD,
    AccountingInvariantError,
    AccountingValidationError,
    AccountView,
    AcquisitionLot,
    LedgerCategory,
    LedgerPosting,
    LedgerTransaction,
    LedgerTransactionId,
    LotConsumption,
    LotConsumptionId,
    LotId,
    LotSource,
    OrderReservation,
    PortfolioSnapshot,
    PositionView,
    ReservationId,
    ReservationStatus,
    SpotAccountSpec,
)
from command_station.accounting.portfolio import mark_portfolio
from command_station.accounting.positions import open_quantity, position_views
from command_station.accounting.reservations import ReservationPlan, prepare_reservation
from command_station.domain import Candle, Side, UtcTimestamp
from command_station.execution import (
    Fill,
    FillId,
    NormalizedOrderRequest,
    Order,
    OrderId,
    OrderStatus,
    ReferenceExecutionSpec,
)
from command_station.execution.models import EXECUTION_MODEL_VERSION, ExecutionSource

_ACTIVE = (OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED)


@dataclass(frozen=True, slots=True)
class _State:
    ledger: tuple[LedgerTransaction, ...] = ()
    reservations: tuple[OrderReservation, ...] = ()
    lots: tuple[AcquisitionLot, ...] = ()
    consumptions: tuple[LotConsumption, ...] = ()
    fills: tuple[Fill, ...] = ()
    activated_orders: tuple[Order, ...] = ()
    portfolios: tuple[PortfolioSnapshot, ...] = ()


class SpotAccountingEngine:
    def __init__(
        self,
        spec: SpotAccountSpec,
        start: UtcTimestamp,
        execution_spec: ReferenceExecutionSpec | None = None,
    ) -> None:
        if not isinstance(spec, SpotAccountSpec) or not isinstance(start, UtcTimestamp):
            raise AccountingValidationError("accounting requires account spec and UTC start")
        execution = execution_spec if execution_spec is not None else ReferenceExecutionSpec()
        if not isinstance(execution, ReferenceExecutionSpec) or execution.fee_bps >= 10_000:
            raise AccountingValidationError(
                "spot accounting requires percentage fee below 10000 bps"
            )
        self._spec, self._start, self._execution_spec = spec, start, execution
        self._state = _State()
        state = self._post(
            self._state,
            start,
            LedgerCategory.INITIAL_DEPOSIT,
            (LedgerPosting(USD, spec.initial_cash),),
        )
        products = {p.product_id: p for p in spec.product_specs}
        for holding in spec.initial_holdings:
            product = products[holding.product_id]
            state = self._post(
                state,
                start,
                LedgerCategory.INITIAL_DEPOSIT,
                (LedgerPosting(product.base_currency, holding.base_quantity),),
            )
            lot = AcquisitionLot(
                LotId(len(state.lots) + 1),
                product.product_id,
                product.base_currency,
                holding.base_quantity,
                holding.unit_cost,
                start,
                LotSource.INITIAL_HOLDING,
            )
            state = replace(state, lots=(*state.lots, lot))
        self._reconcile(state)
        self._state = state

    @property
    def spec(self) -> SpotAccountSpec:
        return self._spec

    @property
    def start(self) -> UtcTimestamp:
        return self._start

    @property
    def execution_spec(self) -> ReferenceExecutionSpec:
        return self._execution_spec

    @property
    def applied_fills(self) -> tuple[Fill, ...]:
        return self._state.fills

    def validate_boundary(self, timestamp: UtcTimestamp, orders: tuple[Order, ...]) -> None:
        """Preflight financial time and broker facts before any external mutation."""
        self._require_time(timestamp, self._state)
        self.validate_broker_state(orders, timestamp)

    @property
    def ledger(self) -> tuple[LedgerTransaction, ...]:
        return self._state.ledger

    @property
    def account_view(self) -> AccountView:
        return self._account(self._state)

    @property
    def reservations(self) -> tuple[OrderReservation, ...]:
        return self._state.reservations

    @property
    def lots(self) -> tuple[AcquisitionLot, ...]:
        return self._state.lots

    @property
    def lot_consumptions(self) -> tuple[LotConsumption, ...]:
        return self._state.consumptions

    @property
    def applied_fill_ids(self) -> tuple[FillId, ...]:
        return tuple(fill.fill_id for fill in self._state.fills)

    @property
    def positions(self) -> tuple[PositionView, ...]:
        return self._positions(self._state)

    @property
    def portfolio_history(self) -> tuple[PortfolioSnapshot, ...]:
        return self._state.portfolios

    @property
    def portfolio_snapshot(self) -> PortfolioSnapshot | None:
        return self._state.portfolios[-1] if self._state.portfolios else None

    @property
    def fees_to_date(self) -> Decimal:
        return add(*(f.fee_amount for f in self._state.fills))

    @property
    def accounting_fingerprint(self) -> str:
        return fingerprint(
            (
                ACCOUNTING_FINGERPRINT_SCHEMA_VERSION,
                ACCOUNTING_MODEL_VERSION,
                LEDGER_SCHEMA_VERSION,
                LOT_DEPLETION_POLICY,
                self.spec.fingerprint,
                self.execution_spec.fingerprint,
                self.start,
                self._state,
            )
        )

    def prepare_reservation(
        self,
        requests: tuple[NormalizedOrderRequest, ...],
        *,
        max_quote_reservation: Decimal | None = None,
    ) -> ReservationPlan:
        return prepare_reservation(
            self.spec, self.execution_spec, self.account_view, requests, max_quote_reservation
        )

    def bind_reservation(
        self, plan: ReservationPlan, orders: tuple[Order, ...], timestamp: UtcTimestamp
    ) -> OrderReservation:
        """Bind validated broker facts within one non-interleaved activation boundary."""
        self._require_time(timestamp, self._state)
        if len(orders) != len(plan.requests) or len({o.order_id for o in orders}) != len(orders):
            raise AccountingInvariantError("reservation binding does not match prepared orders")
        if any(o.order_id in {a.order_id for a in self._state.activated_orders} for o in orders):
            raise AccountingInvariantError("order already reserved")
        # Revalidate all funding and normalization evidence before committing any facts.
        first = plan.requests[0]
        cap = (
            plan.amount
            if first.side is Side.BUY and (len(orders) == 2 or first.order_type.value != "LIMIT")
            else None
        )
        expected = self.prepare_reservation(plan.requests, max_quote_reservation=cap)
        if expected != plan:
            raise AccountingInvariantError("reservation plan differs from funding evidence")
        for order, request in zip(orders, plan.requests, strict=True):
            if (
                (
                    order.product_id,
                    order.side,
                    order.order_type,
                    order.base_currency,
                    order.quote_currency,
                    order.activated_base_quantity,
                    order.requested_base_quantity,
                    order.limit_price,
                    order.stop_price,
                    order.created_at,
                    order.product_spec_fingerprint,
                )
                != (
                    request.product_id,
                    request.side,
                    request.order_type,
                    request.base_currency,
                    request.quote_currency,
                    request.normalized_base_quantity,
                    request.requested_base_quantity,
                    request.limit_price,
                    request.stop_price,
                    request.created_at,
                    request.product_spec_fingerprint,
                )
                or order.status is not OrderStatus.ACTIVE
                or order.activated_at != timestamp
                or order.created_at > order.activated_at
            ):
                raise AccountingInvariantError("broker activation differs from reservation plan")
        if len(orders) == 2 and (
            orders[0].oco_group_id is None or orders[0].oco_group_id != orders[1].oco_group_id
        ):
            raise AccountingInvariantError("shared reservation requires exclusive broker OCO")
        reservation = OrderReservation(
            ReservationId(len(self.reservations) + 1),
            tuple(sorted(o.order_id for o in orders)),
            plan.asset,
            plan.amount,
            plan.amount,
            timestamp,
            ReservationStatus.ACTIVE,
        )
        state = self._post(
            self._state,
            timestamp,
            LedgerCategory.ORDER_RESERVATION,
            (LedgerPosting(plan.asset, ZERO, plan.amount),),
            reservation=reservation.reservation_id,
        )
        state = replace(
            state,
            reservations=(*state.reservations, reservation),
            activated_orders=(*state.activated_orders, *orders),
        )
        self._reconcile(state)
        self._state = state
        return reservation

    def require_reserved_order(self, order_id: OrderId) -> None:
        if not any(
            order_id in r.order_ids and r.status is ReservationStatus.ACTIVE
            for r in self.reservations
        ):
            raise AccountingInvariantError("order has no active reservation")

    def validate_broker_state(self, orders: tuple[Order, ...], timestamp: UtcTimestamp) -> None:
        self._require_time(timestamp, self._state)
        self._validate_orders(self._state, orders, timestamp)

    def apply_fill_batch(
        self, fills: tuple[Fill, ...], orders: tuple[Order, ...], timestamp: UtcTimestamp
    ) -> tuple[LedgerTransaction, ...]:
        """Stage the complete financial batch and commit only after reconciliation."""
        state = self._state
        self._require_time(timestamp, state)
        if any(
            not isinstance(fill, Fill)
            or not isinstance(fill.fill_id, FillId)
            or not isinstance(fill.order_id, OrderId)
            or not isinstance(fill.base_quantity, Decimal)
            or not fill.base_quantity.is_finite()
            or fill.base_quantity <= 0
            for fill in fills
        ):
            raise AccountingInvariantError("batch contains invalid Fill facts")
        self._validate_orders(state, orders, timestamp, fills)
        before = len(state.ledger)
        by_order = {o.order_id: o for o in orders}
        seen = {f.fill_id for f in state.fills}
        for fill in sorted(fills, key=lambda f: f.fill_id):
            if fill.fill_id in seen:
                raise AccountingInvariantError("duplicate Fill")
            seen.add(fill.fill_id)
            order = by_order.get(fill.order_id)
            if order is None:
                raise AccountingInvariantError("unknown Fill order")
            self._validate_fill(fill, order, timestamp)
            reservation = next(
                (r for r in state.reservations if fill.order_id in r.order_ids), None
            )
            if reservation is None or reservation.status is not ReservationStatus.ACTIVE:
                raise AccountingInvariantError("Fill has no active reservation")
            gross = mul(fill.fill_price, fill.base_quantity)
            consumption = (
                add(gross, fill.fee_amount) if fill.side is Side.BUY else fill.base_quantity
            )
            if consumption > reservation.remaining_amount:
                raise AccountingInvariantError("Fill settlement exceeds reservation")
            if fill.side is Side.BUY:
                postings = (
                    LedgerPosting(USD, neg(gross), neg(gross)),
                    LedgerPosting(order.base_currency, fill.base_quantity),
                )
                fee_reserved = neg(fill.fee_amount)
                lot = AcquisitionLot(
                    LotId(len(state.lots) + 1),
                    fill.product_id,
                    order.base_currency,
                    fill.base_quantity,
                    fill.fill_price,
                    fill.executed_at,
                    LotSource.BUY_FILL,
                    fill.fill_id,
                )
                state = replace(state, lots=(*state.lots, lot))
            else:
                postings = (
                    LedgerPosting(
                        order.base_currency, neg(fill.base_quantity), neg(fill.base_quantity)
                    ),
                    LedgerPosting(USD, gross),
                )
                fee_reserved = ZERO
                remaining = fill.base_quantity
                for lot in sorted(state.lots, key=lambda lot: (lot.opened_at, lot.lot_id)):
                    if lot.product_id != fill.product_id or not remaining:
                        continue
                    quantity = min(open_quantity(lot, state.consumptions), remaining)
                    if not quantity:
                        continue
                    record = LotConsumption(
                        LotConsumptionId(len(state.consumptions) + 1),
                        lot.lot_id,
                        fill.fill_id,
                        quantity,
                        lot.unit_cost,
                        fill.fill_price,
                        mul(sub(fill.fill_price, lot.unit_cost), quantity),
                        fill.executed_at,
                    )
                    state = replace(state, consumptions=(*state.consumptions, record))
                    remaining = sub(remaining, quantity)
                if remaining:
                    raise AccountingInvariantError("SELL exceeds open inventory")
            state = self._post(
                state,
                timestamp,
                LedgerCategory.TRADE_FILL,
                postings,
                order.order_id,
                fill.fill_id,
                reservation.reservation_id,
            )
            state = self._post(
                state,
                timestamp,
                LedgerCategory.TRADING_FEE,
                (LedgerPosting(USD, neg(fill.fee_amount), fee_reserved),),
                order.order_id,
                fill.fill_id,
                reservation.reservation_id,
            )
            remainder = sub(reservation.remaining_amount, consumption)
            updated = replace(
                reservation,
                remaining_amount=remainder,
                status=ReservationStatus.CONSUMED if not remainder else ReservationStatus.ACTIVE,
            )
            state = replace(
                state,
                reservations=tuple(
                    updated if r.reservation_id == updated.reservation_id else r
                    for r in state.reservations
                ),
                fills=(*state.fills, fill),
            )
        state = self._release_terminal(state, by_order, timestamp)
        self._reconcile(state)
        self._state = state
        return state.ledger[before:]

    def update_portfolio(
        self, intervals: tuple[Candle, ...], timestamp: UtcTimestamp
    ) -> PortfolioSnapshot:
        self._require_time(timestamp, self._state)
        if self._state.portfolios and timestamp <= self._state.portfolios[-1].timestamp:
            raise AccountingInvariantError("portfolio timestamps must increase")
        products = {p.product_id for p in self.spec.product_specs}
        if any(c.product_id not in products for c in intervals):
            raise AccountingInvariantError("unregistered mark product")
        snapshot = mark_portfolio(
            self.account_view, self.positions, self.fees_to_date, intervals, timestamp
        )
        self._state = replace(self._state, portfolios=(*self._state.portfolios, snapshot))
        return snapshot

    def _release_terminal(
        self, state: _State, orders: dict[OrderId, Order], timestamp: UtcTimestamp
    ) -> _State:
        for reservation in state.reservations:
            if reservation.remaining_amount and not any(
                orders[oid].status in _ACTIVE for oid in reservation.order_ids
            ):
                state = self._post(
                    state,
                    timestamp,
                    LedgerCategory.ORDER_RESERVATION_RELEASE,
                    (LedgerPosting(reservation.asset, ZERO, neg(reservation.remaining_amount)),),
                    reservation=reservation.reservation_id,
                )
                updated = replace(
                    reservation, remaining_amount=ZERO, status=ReservationStatus.RELEASED
                )
                state = replace(
                    state,
                    reservations=tuple(
                        updated if r.reservation_id == updated.reservation_id else r
                        for r in state.reservations
                    ),
                )
        return state

    def _validate_orders(
        self,
        state: _State,
        orders: tuple[Order, ...],
        timestamp: UtcTimestamp,
        new_fills: tuple[Fill, ...] = (),
    ) -> None:
        original = {o.order_id: o for o in state.activated_orders}
        if len({o.order_id for o in orders}) != len(orders) or set(original) != {
            o.order_id for o in orders
        }:
            raise AccountingInvariantError("broker contains unknown/unreserved orders")
        all_fills = (*state.fills, *new_fills)
        for reservation in state.reservations:
            if (
                len(reservation.order_ids) == 2
                and len(
                    {fill.order_id for fill in all_fills if fill.order_id in reservation.order_ids}
                )
                > 1
            ):
                raise AccountingInvariantError("exclusive OCO peers cannot both settle")
        for order in orders:
            if (
                not isinstance(order.created_at, UtcTimestamp)
                or not isinstance(order.activated_at, UtcTimestamp)
                or not (order.created_at <= order.activated_at <= timestamp)
            ):
                raise AccountingInvariantError(
                    "order activation chronology exceeds accounting boundary"
                )
            if order.status is OrderStatus.CANCELLED:
                if not isinstance(order.cancelled_at, UtcTimestamp) or not (
                    order.activated_at <= order.cancelled_at <= timestamp
                ):
                    raise AccountingInvariantError(
                        "order cancellation chronology exceeds accounting boundary"
                    )
                if any(
                    fill.executed_at > order.cancelled_at
                    for fill in all_fills
                    if fill.order_id == order.order_id
                ):
                    raise AccountingInvariantError("order Fill occurs after cancellation")
            activated = original[order.order_id]
            # Only lifecycle fields may differ from the bound immutable activation facts.
            reconstructed = replace(
                order,
                filled_base_quantity=activated.filled_base_quantity,
                remaining_base_quantity=activated.remaining_base_quantity,
                status=activated.status,
                cancelled_at=None,
                cancellation_reason=None,
            )
            if reconstructed != activated:
                raise AccountingInvariantError("broker order activation evidence changed")
            quantity = add(
                *(
                    f.base_quantity
                    for f in (*state.fills, *new_fills)
                    if f.order_id == order.order_id
                )
            )
            if quantity != order.filled_base_quantity:
                raise AccountingInvariantError("Fill quantity does not match broker lifecycle")

    def _validate_fill(self, fill: Fill, order: Order, timestamp: UtcTimestamp) -> None:
        if (
            type(fill.fee_bps) is not int
            or fill.execution_model_version != EXECUTION_MODEL_VERSION
            or fill.execution_source is not ExecutionSource.SIMULATED_ONE_MINUTE_CANDLE
        ):
            raise AccountingInvariantError("Fill has unsupported execution provenance")
        if any(
            not isinstance(t, UtcTimestamp)
            for t in (
                fill.activated_at,
                fill.market_interval_open,
                fill.market_interval_close,
                fill.executed_at,
            )
        ) or fill.market_interval_close.value - fill.market_interval_open.value != timedelta(
            minutes=1
        ):
            raise AccountingInvariantError("Fill requires completed one-minute UTC provenance")
        if (
            any(
                not isinstance(v, Decimal) or not v.is_finite()
                for v in (fill.base_quantity, fill.fill_price, fill.fee_amount)
            )
            or fill.base_quantity <= 0
            or fill.fill_price <= 0
            or fill.fee_amount < 0
        ):
            raise AccountingInvariantError("invalid exact Fill financial values")
        if (
            fill.product_id,
            fill.side,
            fill.product_spec_fingerprint,
            fill.activated_at,
            fill.fee_asset,
        ) != (
            order.product_id,
            order.side,
            order.product_spec_fingerprint,
            order.activated_at,
            order.quote_currency,
        ):
            raise AccountingInvariantError("Fill/order/product/fee asset mismatch")
        if (
            fill.fee_bps != self.execution_spec.fee_bps
            or fill.execution_spec_fingerprint != self.execution_spec.fingerprint
            or fill.fee_amount
            != fee(mul(fill.fill_price, fill.base_quantity), self.execution_spec.fee_bps)
        ):
            raise AccountingInvariantError("Fill fee/execution specification mismatch")
        if not (
            order.activated_at
            <= fill.market_interval_open
            <= fill.executed_at
            <= fill.market_interval_close
            == timestamp
        ):
            raise AccountingInvariantError("Fill violates activation/market timestamp provenance")
        if (
            fill.base_quantity > order.activated_base_quantity.value
            or order.filled_base_quantity == 0
        ):
            raise AccountingInvariantError("Fill exceeds activated/lifecycle quantity")
        if order.limit_price is not None and (
            (fill.side is Side.BUY and fill.fill_price > order.limit_price)
            or (fill.side is Side.SELL and fill.fill_price < order.limit_price)
        ):
            raise AccountingInvariantError("Fill violates limit price")

    def _require_time(self, timestamp: UtcTimestamp, state: _State) -> None:
        if (
            not isinstance(timestamp, UtcTimestamp)
            or timestamp < self.start
            or (state.ledger and timestamp < state.ledger[-1].timestamp)
            or (state.portfolios and timestamp < state.portfolios[-1].timestamp)
        ):
            raise AccountingInvariantError("accounting timestamp regressed")

    def _post(
        self,
        state: _State,
        timestamp: UtcTimestamp,
        category: LedgerCategory,
        postings: tuple[LedgerPosting, ...],
        order: OrderId | None = None,
        fill: FillId | None = None,
        reservation: ReservationId | None = None,
    ) -> _State:
        transaction = LedgerTransaction(
            LedgerTransactionId(len(state.ledger) + 1),
            timestamp,
            category,
            postings,
            order,
            fill,
            reservation,
        )
        return replace(state, ledger=(*state.ledger, transaction))

    def _account(self, state: _State) -> AccountView:
        return replay_ledger(
            state.ledger, (USD, *(p.base_currency for p in self.spec.product_specs))
        )

    def _positions(self, state: _State) -> tuple[PositionView, ...]:
        return position_views(
            self.spec.product_specs, self._account(state), state.lots, state.consumptions
        )

    def _reconcile(self, state: _State) -> None:
        account = self._account(state)
        self._positions(state)
        for balance in account.balances:
            reserved = add(
                *(r.remaining_amount for r in state.reservations if r.asset == balance.asset)
            )
            if reserved != balance.reserved:
                raise AccountingInvariantError("reservation/ledger replay mismatch")
        ledger_fees = add(
            *(
                neg(p.balance_delta)
                for t in state.ledger
                if t.category is LedgerCategory.TRADING_FEE
                for p in t.postings
            )
        )
        if ledger_fees != add(*(f.fee_amount for f in state.fills)):
            raise AccountingInvariantError("Fill/ledger fees mismatch")
