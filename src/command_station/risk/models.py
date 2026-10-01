"""Immutable risk evidence and authorization contracts."""

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from command_station.accounting import (
    USD,
    AccountView,
    OrderReservation,
    PortfolioSnapshot,
    PositionView,
    ReservationId,
    ReservationStatus,
    SpotAccountSpec,
)
from command_station.accounting._exact import add, fee, fingerprint, mul, sub
from command_station.accounting.reservations import ReservationPlan
from command_station.domain import ProductId, Side, UtcTimestamp
from command_station.execution import (
    NormalizedOrderRequest,
    Order,
    OrderStatus,
    OrderType,
    ReferenceExecutionSpec,
)
from command_station.risk.policy import RISK_FINGERPRINT_SCHEMA_VERSION


class ExposureDirection(StrEnum):
    INCREASE_EXPOSURE = "INCREASE_EXPOSURE"
    REDUCE_EXPOSURE = "REDUCE_EXPOSURE"
    NEUTRAL = "NEUTRAL"


class RiskDecisionStatus(StrEnum):
    APPROVE = "APPROVE"
    APPROVE_WITH_MODIFICATION = "APPROVE_WITH_MODIFICATION"
    REJECT = "REJECT"


class RiskReason(StrEnum):
    TRADING_DISABLED = "TRADING_DISABLED"
    INSUFFICIENT_BUYING_POWER = "INSUFFICIENT_BUYING_POWER"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    MAX_ORDER_NOTIONAL = "MAX_ORDER_NOTIONAL"
    MAX_PRODUCT_EXPOSURE = "MAX_PRODUCT_EXPOSURE"
    MAX_PORTFOLIO_EXPOSURE = "MAX_PORTFOLIO_EXPOSURE"
    MINIMUM_CASH_RESERVE = "MINIMUM_CASH_RESERVE"
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    MIN_ORDER_SIZE = "MIN_ORDER_SIZE"
    MODIFICATION_NOT_ALLOWED = "MODIFICATION_NOT_ALLOWED"


@dataclass(frozen=True, slots=True, order=True)
class RiskDecisionId:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise ValueError("risk identity must be positive int")


@dataclass(frozen=True, slots=True)
class RiskStateSnapshot:
    timestamp: UtcTimestamp
    account_spec: SpotAccountSpec
    account_view: AccountView
    positions: tuple[PositionView, ...]
    reservations: tuple[OrderReservation, ...]
    orders: tuple[Order, ...]
    portfolio_snapshot: PortfolioSnapshot | None
    execution_spec: ReferenceExecutionSpec

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "positions", tuple(sorted(self.positions, key=lambda p: p.product_id.value))
        )
        object.__setattr__(
            self,
            "reservations",
            tuple(
                sorted(
                    (replace(r, order_ids=tuple(sorted(r.order_ids))) for r in self.reservations),
                    key=lambda r: r.reservation_id,
                )
            ),
        )
        object.__setattr__(self, "orders", tuple(sorted(self.orders, key=lambda o: o.order_id)))
        object.__setattr__(
            self,
            "account_view",
            AccountView(tuple(sorted(self.account_view.balances, key=lambda b: b.asset.value))),
        )
        if self.portfolio_snapshot is not None:
            snapshot = self.portfolio_snapshot
            object.__setattr__(
                self,
                "portfolio_snapshot",
                replace(
                    snapshot,
                    positions=tuple(sorted(snapshot.positions, key=lambda p: p.product_id.value)),
                    marks=tuple(sorted(snapshot.marks, key=lambda item: item[0].value)),
                ),
            )
        if len({r.reservation_id for r in self.reservations}) != len(self.reservations) or len(
            {o.order_id for o in self.orders}
        ) != len(self.orders):
            raise ValueError("duplicate risk state identity")

        self.validate_consistency()

    def validate_consistency(self) -> None:
        """Reject contradictory evidence; the accounting producer owns mark provenance."""
        products = {p.product_id: p for p in self.account_spec.product_specs}
        positions = {p.product_id: p for p in self.positions}
        balances = {b.asset: b for b in self.account_view.balances}
        assets = {USD, *(p.base_currency for p in products.values())}
        if len(positions) != len(self.positions) or set(positions) != set(products):
            raise ValueError("risk positions must uniquely cover account products")
        if len(balances) != len(self.account_view.balances) or set(balances) != assets:
            raise ValueError("risk balances must uniquely cover account assets")
        for product_id, position in positions.items():
            position_product = products[product_id]
            if (
                position.base_asset != position_product.base_currency
                or not isinstance(position.actual_quantity, Decimal)
                or not position.actual_quantity.is_finite()
                or position.actual_quantity < 0
                or position.actual_quantity != balances[position_product.base_currency].total
            ):
                raise ValueError("risk position/account quantity mismatch")
        orders = {o.order_id: o for o in self.orders}
        if len(orders) != len(self.orders) or len(
            {r.reservation_id for r in self.reservations}
        ) != len(self.reservations):
            raise ValueError("duplicate risk state identity")
        owned: set[object] = set()
        active_statuses = (OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED)
        for reservation in self.reservations:
            ids = reservation.order_ids
            if len(ids) not in (1, 2) or len(set(ids)) != len(ids) or owned.intersection(ids):
                raise ValueError("overlapping or invalid reservation order ownership")
            if not set(ids).issubset(orders):
                raise ValueError("reservation references missing order")
            owned.update(ids)
            peers = tuple(orders[oid] for oid in ids)
            first = peers[0]
            product = products.get(first.product_id)
            if product is None or any(
                (
                    o.product_id,
                    o.side,
                    o.base_currency,
                    o.quote_currency,
                    o.product_spec_fingerprint,
                )
                != (first.product_id, first.side, product.base_currency, USD, product.fingerprint)
                for o in peers
            ):
                raise ValueError("reservation/order/product evidence mismatch")
            if len(peers) == 2:
                if (
                    first.oco_group_id is None
                    or peers[1].oco_group_id != first.oco_group_id
                    or first.activated_base_quantity != peers[1].activated_base_quantity
                    or {o.order_type for o in peers} != {OrderType.LIMIT, OrderType.STOP_MARKET}
                ):
                    raise ValueError("shared reservation requires matching OCO peers")
            elif first.oco_group_id is not None:
                raise ValueError("OCO reservation omitted a peer")
            expected_asset = USD if first.side is Side.BUY else product.base_currency
            if reservation.asset != expected_asset:
                raise ValueError("reservation asset does not match order direction")
            if (
                any(
                    not isinstance(v, Decimal) or not v.is_finite()
                    for v in (reservation.original_amount, reservation.remaining_amount)
                )
                or not (0 <= reservation.remaining_amount <= reservation.original_amount)
                or reservation.original_amount <= 0
            ):
                raise ValueError("invalid reservation commitment")
            if (reservation.status is ReservationStatus.ACTIVE) != (
                reservation.remaining_amount > 0
            ):
                raise ValueError("reservation status/commitment mismatch")
            if (
                any(o.status in active_statuses for o in peers)
                and not any(o.filled_base_quantity for o in peers)
                and reservation.remaining_amount != reservation.original_amount
            ):
                raise ValueError("unfilled active order has consumed commitment")
            if reservation.remaining_amount and not any(o.status in active_statuses for o in peers):
                raise ValueError("terminal orders retain active commitment")
            if first.side is Side.SELL:
                if reservation.original_amount != first.activated_base_quantity.value:
                    raise ValueError("SELL reservation quantity mismatch")
                if (
                    reservation.status is ReservationStatus.ACTIVE
                    and reservation.remaining_amount
                    != sub(
                        reservation.original_amount, add(*(o.filled_base_quantity for o in peers))
                    )
                ):
                    raise ValueError("SELL remaining reservation quantity mismatch")
            elif len(peers) == 1 and first.order_type is OrderType.LIMIT:
                if first.limit_price is None:
                    raise ValueError("BUY LIMIT lacks settlement price")
                gross = mul(first.limit_price, first.activated_base_quantity.value)
                if reservation.original_amount != add(
                    gross, fee(gross, self.execution_spec.fee_bps)
                ):
                    raise ValueError("BUY LIMIT reservation settlement mismatch")
        if owned != set(orders):
            raise ValueError("risk order lacks reservation evidence")
        for asset, balance in balances.items():
            reserved = add(*(r.remaining_amount for r in self.reservations if r.asset == asset))
            if reserved != balance.reserved:
                raise ValueError("risk reservation/balance mismatch")
        snapshot = self.portfolio_snapshot
        if snapshot is not None:
            if snapshot.positions != self.positions:
                raise ValueError("portfolio/state position mismatch")
            marks = dict(snapshot.marks)
            if len(marks) != len(snapshot.marks) or not set(marks).issubset(products):
                raise ValueError("portfolio marks must have unique registered products")
            if any(
                not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in marks.values()
            ):
                raise ValueError("portfolio marks require positive exact prices")
            # Missing marks remain a structured freshness failure in mark-dependent policy.
            held = tuple(p for p in self.positions if p.actual_quantity > 0)
            if all(p.product_id in marks for p in held):
                marked = add(*(mul(p.actual_quantity, marks[p.product_id]) for p in held))
                if snapshot.marked_asset_value != marked:
                    raise ValueError("portfolio marked asset total mismatch")
            if snapshot.total_equity != add(snapshot.cash_total, snapshot.marked_asset_value):
                raise ValueError("portfolio equity mismatch")
            if snapshot.cash_available != sub(snapshot.cash_total, snapshot.cash_reserved):
                raise ValueError("portfolio cash evidence mismatch")

    @property
    def fingerprint(self) -> str:
        return fingerprint((RISK_FINGERPRINT_SCHEMA_VERSION, self))


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision_id: RiskDecisionId
    timestamp: UtcTimestamp
    status: RiskDecisionStatus
    direction: ExposureDirection
    product_id: ProductId
    requested_base_quantity: Decimal
    approved_base_quantity: Decimal | None
    requested_quote_commitment: Decimal
    approved_quote_commitment: Decimal | None
    reasons: tuple[RiskReason, ...]
    policy_fingerprint: str
    state_fingerprint: str
    proposal_fingerprint: str
    baseline_product_exposure: Decimal
    projected_product_exposure: Decimal
    baseline_portfolio_exposure: Decimal
    projected_portfolio_exposure: Decimal
    projected_available_cash: Decimal
    projected_open_positions: int


@dataclass(frozen=True, slots=True)
class RiskAuthorization:
    decision: RiskDecision
    approved_requests: tuple[NormalizedOrderRequest, ...]
    reservation_plan: ReservationPlan | None


@dataclass(frozen=True, slots=True)
class RiskActivationResult:
    decision: RiskDecision
    orders: tuple[Order, ...]


@dataclass(frozen=True, slots=True)
class RiskOrderBinding:
    decision: RiskDecision
    approved_request: NormalizedOrderRequest
    original_order: Order
    reservation_id: ReservationId
