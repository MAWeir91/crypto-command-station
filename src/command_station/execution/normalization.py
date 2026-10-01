"""Pure Coinbase spot order normalization."""

from __future__ import annotations

from decimal import Decimal

from command_station.domain import ProductSpec, ProductType, Side, Venue
from command_station.execution.orders import (
    BaseQuantity,
    NormalizedOrderRequest,
    OrderIntent,
    OrderType,
    OrderValidationError,
)


class OrderNormalizationError(OrderValidationError):
    """Raised when an intent cannot be conservatively activated for a product."""


def normalize_order_intent(
    intent: OrderIntent, product_spec: ProductSpec
) -> NormalizedOrderRequest:
    """Return deterministic product-valid input without runtime mutation."""
    if not isinstance(intent, OrderIntent) or not isinstance(product_spec, ProductSpec):
        raise OrderNormalizationError("normalization requires OrderIntent and ProductSpec")
    if (
        product_spec.venue is not Venue.COINBASE
        or product_spec.product_type is not ProductType.SPOT
        or intent.product_id != product_spec.product_id
    ):
        raise OrderNormalizationError("intent must match a Coinbase spot ProductSpec")
    if any(
        (
            product_spec.is_disabled,
            product_spec.trading_disabled,
            product_spec.cancel_only,
            product_spec.view_only,
        )
    ):
        raise OrderNormalizationError("product state does not allow new activation")
    if product_spec.limit_only and intent.order_type is not OrderType.LIMIT:
        raise OrderNormalizationError("limit-only product requires a limit order")
    if product_spec.post_only or product_spec.auction_mode:
        raise OrderNormalizationError("unsupported product execution mode")

    quantity = _floor_to_increment(intent.base_quantity.value, product_spec.base_increment)
    if quantity <= 0 or quantity < product_spec.base_min_size:
        raise OrderNormalizationError("normalized quantity is below product minimum")
    if quantity > product_spec.base_max_size:
        raise OrderNormalizationError("normalized quantity exceeds product maximum")

    limit_price = intent.limit_price
    if limit_price is not None:
        if intent.side is Side.BUY:
            limit_price = _floor_to_increment(limit_price, product_spec.price_increment)
        else:
            limit_price = _ceil_to_increment(limit_price, product_spec.price_increment)
        if limit_price <= 0:
            raise OrderNormalizationError("normalized limit price is not positive")

    stop_price = intent.stop_price
    if stop_price is not None and not _is_aligned(stop_price, product_spec.price_increment):
        raise OrderNormalizationError("stop price must align exactly to price increment")

    return NormalizedOrderRequest(
        product_id=intent.product_id,
        base_currency=product_spec.base_currency,
        quote_currency=product_spec.quote_currency,
        side=intent.side,
        order_type=intent.order_type,
        requested_base_quantity=intent.base_quantity,
        normalized_base_quantity=BaseQuantity(quantity),
        created_at=intent.created_at,
        limit_price=limit_price,
        stop_price=stop_price,
        product_spec_fingerprint=product_spec.fingerprint,
        source_intent=intent,
        product_spec=product_spec,
    )


def verify_normalized_order_request(request: NormalizedOrderRequest) -> None:
    """Reject any request whose immutable normalization evidence does not reproduce it."""
    if not isinstance(request, NormalizedOrderRequest):
        raise OrderNormalizationError("activation requires a NormalizedOrderRequest")
    expected = normalize_order_intent(request.source_intent, request.product_spec)
    if request != expected:
        raise OrderNormalizationError(
            "normalized request does not match its intent and ProductSpec evidence"
        )


def _floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    count = _ratio_floor(value, increment)
    return _exact_integer_multiple(increment, count)


def _ceil_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    count = _ratio_floor(value, increment)
    result = _exact_integer_multiple(increment, count)
    return result if result == value else _exact_integer_multiple(increment, count + 1)


def _is_aligned(value: Decimal, increment: Decimal) -> bool:
    numerator, denominator = _ratio(value, increment)
    return numerator % denominator == 0


def _ratio_floor(value: Decimal, increment: Decimal) -> int:
    numerator, denominator = _ratio(value, increment)
    return numerator // denominator


def _ratio(value: Decimal, increment: Decimal) -> tuple[int, int]:
    value_numerator, value_denominator = value.as_integer_ratio()
    increment_numerator, increment_denominator = increment.as_integer_ratio()
    return (
        value_numerator * increment_denominator,
        value_denominator * increment_numerator,
    )


def _exact_integer_multiple(value: Decimal, count: int) -> Decimal:
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise OrderNormalizationError("increment must be finite")
    coefficient = int("".join(str(digit) for digit in digits) or "0") * count
    result_digits = tuple(int(char) for char in str(coefficient))
    return Decimal((sign, result_digits, exponent))
