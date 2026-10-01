"""Callback-local queued intent capabilities with no live-engine reachability."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from command_station.domain import DecimalInput, ProductId, Side, UtcTimestamp, require_positive
from command_station.execution import (
    BaseQuantity,
    OcoGroupId,
    Order,
    OrderId,
    OrderIntent,
    OrderType,
)
from command_station.risk.models import RiskDecision
from command_station.strategy._logical import StrategyContractError


class StrategyCommandKind(StrEnum):
    ENTRY = "ENTRY"
    OCO = "OCO"
    CANCEL = "CANCEL"
    CANCEL_OCO = "CANCEL_OCO"


class StrategyActionStatus(StrEnum):
    ACTIVATED = "ACTIVATED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True, order=True)
class StrategyCommandId:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise StrategyContractError("command ID must be a positive integer")


@dataclass(frozen=True, slots=True)
class StrategyOrderCommand:
    command_id: StrategyCommandId
    timestamp: UtcTimestamp
    kind: StrategyCommandKind
    intents: tuple[OrderIntent, ...] = ()
    max_quote_reservation: Decimal | None = None
    order_id: OrderId | None = None
    group_id: OcoGroupId | None = None


@dataclass(frozen=True, slots=True)
class StrategyActionResult:
    command_id: StrategyCommandId
    timestamp: UtcTimestamp
    kind: StrategyCommandKind
    status: StrategyActionStatus
    risk_decision: RiskDecision | None
    order_ids: tuple[OrderId, ...]
    cancelled_orders: tuple[Order, ...] = ()


class StrategyOrderView:
    """Snapshot reads and local queue. Sealed permanently when its callback exits."""

    __slots__ = ("_now", "_first_id", "_allowed", "_sealed", "_queue", "_orders", "_results")

    def __init__(
        self,
        now: UtcTimestamp,
        first_id: int,
        allowed: bool,
        orders: tuple[Order, ...],
        results: tuple[StrategyActionResult, ...],
    ):
        self._now, self._first_id, self._allowed = now, first_id, allowed
        self._sealed = False
        self._queue: list[StrategyOrderCommand] = []
        self._orders, self._results = orders, results

    @property
    def orders(self) -> tuple[Order, ...]:
        return self._orders

    @property
    def results(self) -> tuple[StrategyActionResult, ...]:
        return self._results

    def _require_permission(self) -> None:
        if self._sealed or not self._allowed:
            raise StrategyContractError("orders are forbidden outside on_start/on_bar")

    def _entry(
        self,
        product_id: ProductId,
        side: Side,
        quantity: BaseQuantity,
        kind: OrderType,
        price: DecimalInput | None,
        cap: DecimalInput | None,
        second_price: DecimalInput | None = None,
    ) -> StrategyCommandId:
        self._require_permission()
        gap_buy = side is Side.BUY and (kind is not OrderType.LIMIT or second_price is not None)
        if gap_buy != (cap is not None):
            raise StrategyContractError(
                "BUY market/stop/OCO needs shared cap; other orders forbid it"
            )
        normalized_cap = None if cap is None else require_positive(cap)
        intent = OrderIntent(
            product_id=product_id,
            side=side,
            order_type=kind,
            base_quantity=quantity,
            created_at=self._now,
            limit_price=price if kind is OrderType.LIMIT else None,
            stop_price=price if kind is OrderType.STOP_MARKET else None,
        )
        intents: tuple[OrderIntent, ...] = (intent,)
        command_kind = StrategyCommandKind.ENTRY
        if second_price is not None:
            intents += (
                OrderIntent(
                    product_id=product_id,
                    side=side,
                    order_type=OrderType.STOP_MARKET,
                    base_quantity=quantity,
                    created_at=self._now,
                    stop_price=second_price,
                ),
            )
            command_kind = StrategyCommandKind.OCO
        return self._append(command_kind, intents, normalized_cap)

    def market(
        self,
        product_id: ProductId,
        side: Side,
        base_quantity: BaseQuantity,
        *,
        max_quote_reservation: DecimalInput | None = None,
    ) -> StrategyCommandId:
        return self._entry(
            product_id, side, base_quantity, OrderType.MARKET, None, max_quote_reservation
        )

    def limit(
        self,
        product_id: ProductId,
        side: Side,
        base_quantity: BaseQuantity,
        limit_price: DecimalInput,
    ) -> StrategyCommandId:
        return self._entry(product_id, side, base_quantity, OrderType.LIMIT, limit_price, None)

    def stop_market(
        self,
        product_id: ProductId,
        side: Side,
        base_quantity: BaseQuantity,
        stop_price: DecimalInput,
        *,
        max_quote_reservation: DecimalInput | None = None,
    ) -> StrategyCommandId:
        return self._entry(
            product_id,
            side,
            base_quantity,
            OrderType.STOP_MARKET,
            stop_price,
            max_quote_reservation,
        )

    def oco_limit_stop(
        self,
        product_id: ProductId,
        side: Side,
        base_quantity: BaseQuantity,
        limit_price: DecimalInput,
        stop_price: DecimalInput,
        *,
        max_quote_reservation: DecimalInput | None = None,
    ) -> StrategyCommandId:
        return self._entry(
            product_id,
            side,
            base_quantity,
            OrderType.LIMIT,
            limit_price,
            max_quote_reservation,
            stop_price,
        )

    def cancel(self, order_id: OrderId) -> StrategyCommandId:
        self._require_permission()
        if not isinstance(order_id, OrderId):
            raise StrategyContractError("cancel requires OrderId")
        return self._append(StrategyCommandKind.CANCEL, order_id=order_id)

    def cancel_oco(self, group_id: OcoGroupId) -> StrategyCommandId:
        self._require_permission()
        if not isinstance(group_id, OcoGroupId):
            raise StrategyContractError("cancel_oco requires OcoGroupId")
        return self._append(StrategyCommandKind.CANCEL_OCO, group_id=group_id)

    def _append(
        self,
        kind: StrategyCommandKind,
        intents: tuple[OrderIntent, ...] = (),
        cap: Decimal | None = None,
        order_id: OrderId | None = None,
        group_id: OcoGroupId | None = None,
    ) -> StrategyCommandId:
        command_id = StrategyCommandId(self._first_id + len(self._queue))
        self._queue.append(
            StrategyOrderCommand(command_id, self._now, kind, intents, cap, order_id, group_id)
        )
        return command_id

    def _seal(self) -> tuple[StrategyOrderCommand, ...]:
        self._sealed = True
        return tuple(self._queue)
