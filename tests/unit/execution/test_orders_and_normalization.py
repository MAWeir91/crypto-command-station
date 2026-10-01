from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext

import pytest

from command_station.domain import ProductId, Side
from command_station.execution import (
    BaseQuantity,
    OrderIntent,
    OrderNormalizationError,
    OrderType,
    OrderValidationError,
    normalize_order_intent,
)
from tests.execution_fixtures import product, timestamp


def intent(
    order_type: OrderType = OrderType.MARKET,
    *,
    side: Side = Side.BUY,
    quantity: str = "1.2349",
    limit: str | None = None,
    stop: str | None = None,
) -> OrderIntent:
    return OrderIntent(
        product_id=ProductId("BTC-USD"),
        side=side,
        order_type=order_type,
        base_quantity=BaseQuantity(quantity),
        created_at=timestamp(),
        limit_price=limit,
        stop_price=stop,
    )


@pytest.mark.parametrize("bad", [0, -1, True, 1.2, "NaN", "Infinity"])
def test_base_quantity_rejects_non_exact_or_non_positive_values(bad: object) -> None:
    with pytest.raises(OrderValidationError):
        BaseQuantity(bad)  # type: ignore[arg-type]


def test_intent_is_immutable_and_enforces_order_shape() -> None:
    value = intent()
    with pytest.raises(FrozenInstanceError):
        value.order_type = OrderType.LIMIT  # type: ignore[misc]
    with pytest.raises(OrderValidationError):
        intent(OrderType.MARKET, limit="1")
    with pytest.raises(OrderValidationError):
        intent(OrderType.LIMIT)
    with pytest.raises(OrderValidationError):
        intent(OrderType.STOP_MARKET, limit="1")


def test_quantity_and_limit_normalization_are_conservative() -> None:
    spec = product()
    buy = normalize_order_intent(intent(OrderType.LIMIT, limit="100.019"), spec)
    sell = normalize_order_intent(intent(OrderType.LIMIT, side=Side.SELL, limit="100.011"), spec)
    assert buy.normalized_base_quantity.value == Decimal("1.234")
    assert buy.limit_price == Decimal("100.01")
    assert sell.limit_price == Decimal("100.02")
    assert buy.product_spec_fingerprint == spec.fingerprint


def test_stop_alignment_and_product_status_fail_closed() -> None:
    with pytest.raises(OrderNormalizationError, match="align"):
        normalize_order_intent(intent(OrderType.STOP_MARKET, stop="99.999"), product())
    unavailable = (
        product(is_disabled=True),
        product(trading_disabled=True),
        product(cancel_only=True),
        product(view_only=True),
    )
    for unavailable_product in unavailable:
        with pytest.raises(OrderNormalizationError):
            normalize_order_intent(intent(), unavailable_product)
    with pytest.raises(OrderNormalizationError):
        normalize_order_intent(intent(), product(post_only=True))


def test_normalization_is_independent_of_decimal_precision() -> None:
    with localcontext() as context:
        context.prec = 2
        normalized = normalize_order_intent(intent(quantity="12.3459"), product())
    assert normalized.normalized_base_quantity.value == Decimal("12.345")
