"""Immutable order intent, identity, and lifecycle values."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from command_station.domain import (
    AssetSymbol,
    DecimalInput,
    ProductId,
    ProductSpec,
    Side,
    UtcTimestamp,
    require_positive,
)


class OrderValidationError(ValueError):
    """Raised when an order value or lifecycle transition is invalid."""


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"


class OrderStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class CancellationReason(StrEnum):
    USER_REQUEST = "USER_REQUEST"
    OCO_PEER_FILLED = "OCO_PEER_FILLED"


@dataclass(frozen=True, slots=True, order=True)
class OrderId:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise OrderValidationError("order ID must be a positive integer")


@dataclass(frozen=True, slots=True, order=True)
class FillId:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise OrderValidationError("fill ID must be a positive integer")


@dataclass(frozen=True, slots=True, order=True)
class OcoGroupId:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise OrderValidationError("OCO group ID must be a positive integer")


@dataclass(frozen=True, slots=True)
class BaseQuantity:
    value: Decimal

    def __init__(self, value: DecimalInput) -> None:
        try:
            normalized = require_positive(value)
        except ValueError as error:
            raise OrderValidationError("base quantity must be an exact positive value") from error
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class OrderIntent:
    product_id: ProductId
    side: Side
    order_type: OrderType
    base_quantity: BaseQuantity
    created_at: UtcTimestamp
    limit_price: Decimal | None
    stop_price: Decimal | None

    def __init__(
        self,
        *,
        product_id: ProductId,
        side: Side,
        order_type: OrderType,
        base_quantity: BaseQuantity,
        created_at: UtcTimestamp,
        limit_price: DecimalInput | None = None,
        stop_price: DecimalInput | None = None,
    ) -> None:
        if not isinstance(product_id, ProductId):
            raise OrderValidationError("intent product_id must be a ProductId")
        if not isinstance(side, Side) or not isinstance(order_type, OrderType):
            raise OrderValidationError("intent requires supported side and order type")
        if not isinstance(base_quantity, BaseQuantity) or not isinstance(created_at, UtcTimestamp):
            raise OrderValidationError("intent requires BaseQuantity and UtcTimestamp")
        try:
            normalized_limit = None if limit_price is None else require_positive(limit_price)
            normalized_stop = None if stop_price is None else require_positive(stop_price)
        except ValueError as error:
            raise OrderValidationError("order prices must be exact positive values") from error
        if order_type is OrderType.MARKET and (
            normalized_limit is not None or normalized_stop is not None
        ):
            raise OrderValidationError("market intent cannot include limit or stop price")
        if order_type is OrderType.LIMIT and (
            normalized_limit is None or normalized_stop is not None
        ):
            raise OrderValidationError("limit intent requires only a limit price")
        if order_type is OrderType.STOP_MARKET and (
            normalized_stop is None or normalized_limit is not None
        ):
            raise OrderValidationError("stop-market intent requires only a stop price")
        object.__setattr__(self, "product_id", product_id)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(self, "base_quantity", base_quantity)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "limit_price", normalized_limit)
        object.__setattr__(self, "stop_price", normalized_stop)


@dataclass(frozen=True, slots=True)
class NormalizedOrderRequest:
    product_id: ProductId
    base_currency: AssetSymbol
    quote_currency: AssetSymbol
    side: Side
    order_type: OrderType
    requested_base_quantity: BaseQuantity
    normalized_base_quantity: BaseQuantity
    created_at: UtcTimestamp
    limit_price: Decimal | None
    stop_price: Decimal | None
    product_spec_fingerprint: str
    source_intent: OrderIntent
    product_spec: ProductSpec

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_id, ProductId)
            or not isinstance(self.base_currency, AssetSymbol)
            or not isinstance(self.quote_currency, AssetSymbol)
            or not isinstance(self.side, Side)
            or not isinstance(self.order_type, OrderType)
            or not isinstance(self.requested_base_quantity, BaseQuantity)
            or not isinstance(self.normalized_base_quantity, BaseQuantity)
            or not isinstance(self.created_at, UtcTimestamp)
            or not isinstance(self.source_intent, OrderIntent)
            or not isinstance(self.product_spec, ProductSpec)
        ):
            raise OrderValidationError("normalized request contains invalid value types")
        if self.normalized_base_quantity.value > self.requested_base_quantity.value:
            raise OrderValidationError("normalized quantity cannot exceed requested quantity")
        if not _is_fingerprint(self.product_spec_fingerprint):
            raise OrderValidationError("normalized request requires a ProductSpec fingerprint")


@dataclass(frozen=True, slots=True)
class Order:
    order_id: OrderId
    product_id: ProductId
    base_currency: AssetSymbol
    quote_currency: AssetSymbol
    side: Side
    order_type: OrderType
    requested_base_quantity: BaseQuantity
    activated_base_quantity: BaseQuantity
    filled_base_quantity: Decimal
    remaining_base_quantity: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    created_at: UtcTimestamp
    activated_at: UtcTimestamp
    status: OrderStatus
    product_spec_fingerprint: str
    oco_group_id: OcoGroupId | None = None
    cancelled_at: UtcTimestamp | None = None
    cancellation_reason: CancellationReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.order_id, OrderId) or not isinstance(self.status, OrderStatus):
            raise OrderValidationError("order identity or status is invalid")
        if not isinstance(self.filled_base_quantity, Decimal) or not isinstance(
            self.remaining_base_quantity, Decimal
        ):
            raise OrderValidationError("order lifecycle quantities must be Decimal")
        if (
            not self.filled_base_quantity.is_finite()
            or not self.remaining_base_quantity.is_finite()
            or self.filled_base_quantity < 0
            or self.remaining_base_quantity < 0
            or _exact_add(self.filled_base_quantity, self.remaining_base_quantity)
            != self.activated_base_quantity.value
        ):
            raise OrderValidationError("order lifecycle quantities do not reconcile")
        if self.status is OrderStatus.ACTIVE and self.filled_base_quantity != 0:
            raise OrderValidationError("active order cannot already have fills")
        if self.status is OrderStatus.PARTIALLY_FILLED and (
            self.filled_base_quantity == 0 or self.remaining_base_quantity == 0
        ):
            raise OrderValidationError("partial order requires filled and remaining quantity")
        if self.status is OrderStatus.FILLED and self.remaining_base_quantity != 0:
            raise OrderValidationError("filled order cannot have remaining quantity")
        cancelled = self.status is OrderStatus.CANCELLED
        if cancelled != (self.cancelled_at is not None and self.cancellation_reason is not None):
            raise OrderValidationError("cancellation metadata must match cancelled status")
        if not _is_fingerprint(self.product_spec_fingerprint):
            raise OrderValidationError("order requires a ProductSpec fingerprint")

    def apply_fill(self, quantity: DecimalInput) -> Order:
        """Return the next immutable lifecycle snapshot for an exact fill quantity."""
        if self.status not in (OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED):
            raise OrderValidationError("only active orders can be filled")
        try:
            amount = require_positive(quantity)
        except ValueError as error:
            raise OrderValidationError("fill quantity must be exact and positive") from error
        if amount > self.remaining_base_quantity:
            raise OrderValidationError("fill quantity exceeds order remainder")
        filled = _exact_add(self.filled_base_quantity, amount)
        remaining = _exact_subtract(self.activated_base_quantity.value, filled)
        status = OrderStatus.FILLED if remaining == 0 else OrderStatus.PARTIALLY_FILLED
        return replace(
            self,
            filled_base_quantity=filled,
            remaining_base_quantity=remaining,
            status=status,
        )

    def cancel(self, at: UtcTimestamp, reason: CancellationReason) -> Order:
        if self.status not in (OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED):
            raise OrderValidationError("only active orders can be cancelled")
        if not isinstance(at, UtcTimestamp) or at < self.activated_at:
            raise OrderValidationError("cancellation timestamp precedes activation")
        if not isinstance(reason, CancellationReason):
            raise OrderValidationError("cancellation reason is invalid")
        return replace(
            self,
            status=OrderStatus.CANCELLED,
            cancelled_at=at,
            cancellation_reason=reason,
        )


def _exact_add(left: Decimal, right: Decimal) -> Decimal:
    return _decimal_from_coefficient(*_align(left, right, add=True))


def _exact_subtract(left: Decimal, right: Decimal) -> Decimal:
    coefficient, exponent = _align(left, right, add=False)
    if coefficient < 0:
        raise OrderValidationError("decimal subtraction would become negative")
    return _decimal_from_coefficient(coefficient, exponent)


def _align(left: Decimal, right: Decimal, *, add: bool) -> tuple[int, int]:
    left_coefficient, left_exponent = _coefficient(left)
    right_coefficient, right_exponent = _coefficient(right)
    exponent = min(left_exponent, right_exponent)
    left_scaled = left_coefficient * 10 ** (left_exponent - exponent)
    right_scaled = right_coefficient * 10 ** (right_exponent - exponent)
    return (left_scaled + right_scaled if add else left_scaled - right_scaled, exponent)


def _coefficient(value: Decimal) -> tuple[int, int]:
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise OrderValidationError("decimal must be finite")
    coefficient = int("".join(str(digit) for digit in digits) or "0")
    return (-coefficient if sign else coefficient, exponent)


def _decimal_from_coefficient(coefficient: int, exponent: int) -> Decimal:
    sign = 1 if coefficient < 0 else 0
    digits = tuple(int(char) for char in str(abs(coefficient)))
    return Decimal((sign, digits, exponent))


def _is_fingerprint(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
