from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from command_station.domain import AssetSymbol, ProductId, Side
from command_station.execution import (
    BaseQuantity,
    BrokerStateError,
    CancellationReason,
    ExecutionResolution,
    NormalizedOrderRequest,
    OrderIntent,
    OrderStatus,
    OrderType,
    OrderValidationError,
    ReferenceExecutionSpec,
    SimulatedBroker,
    normalize_order_intent,
)
from tests.execution_fixtures import candle, product, timestamp


def request(
    order_type: OrderType,
    *,
    side: Side = Side.BUY,
    limit: str | None = None,
    stop: str | None = None,
    product_id: str = "BTC-USD",
) -> NormalizedOrderRequest:
    spec = product(product_id)
    return normalize_order_intent(
        OrderIntent(
            product_id=ProductId(product_id),
            side=side,
            order_type=order_type,
            base_quantity=BaseQuantity("1"),
            created_at=timestamp(1),
            limit_price=limit,
            stop_price=stop,
        ),
        spec,
    )


def test_market_uses_first_eligible_open_with_exact_fee_and_adverse_slippage() -> None:
    broker = SimulatedBroker(ReferenceExecutionSpec(slippage_bps=25, fee_bps=10))
    order = broker.activate(request(OrderType.MARKET), timestamp(1))
    assert broker.process_market_activity((candle(0),), timestamp(1)) == ()
    with localcontext() as context:
        context.prec = 2
        fills = broker.process_market_activity((candle(1, open="100"),), timestamp(2))
    assert len(fills) == 1
    fill = fills[0]
    assert fill.order_id == order.order_id
    assert fill.reference_price == Decimal("100")
    assert fill.fill_price == Decimal("100.25")
    assert fill.fee_amount == Decimal("0.10025")
    assert fill.resolution is ExecutionResolution.EXACT_NEXT_OPEN
    assert fill.executed_at == timestamp(1)
    assert broker.get_order(order.order_id).status is OrderStatus.FILLED


def test_limit_touch_gap_and_stop_gap_semantics() -> None:
    limit_broker = SimulatedBroker()
    limit = limit_broker.activate(request(OrderType.LIMIT, limit="99"), timestamp(1))
    assert (
        limit_broker.process_market_activity((candle(1, low="99"),), timestamp(2))[0].fill_price
        == 99
    )
    assert limit_broker.get_order(limit.order_id).status is OrderStatus.FILLED

    stop_broker = SimulatedBroker(ReferenceExecutionSpec(slippage_bps=100))
    stop = stop_broker.activate(
        request(OrderType.STOP_MARKET, side=Side.SELL, stop="95"), timestamp(1)
    )
    fill = stop_broker.process_market_activity(
        (candle(1, open="90", high="91", low="89", close="90"),), timestamp(2)
    )[0]
    assert fill.order_id == stop.order_id
    assert fill.reference_price == 90
    assert fill.fill_price == Decimal("89.1")
    assert fill.resolution is ExecutionResolution.GAP
    assert fill.gap is True


def test_partial_fill_lifecycle_overfill_and_cancellation() -> None:
    broker = SimulatedBroker()
    order = broker.activate(request(OrderType.MARKET), timestamp(1))
    partial = order.apply_fill("0.4")
    assert partial.status is OrderStatus.PARTIALLY_FILLED
    assert partial.remaining_base_quantity == Decimal("0.6")
    with pytest.raises(OrderValidationError):
        partial.apply_fill("0.7")
    cancelled = broker.cancel(order.order_id, timestamp(1), CancellationReason.USER_REQUEST)
    assert cancelled.status is OrderStatus.CANCELLED
    assert broker.process_market_activity((candle(1),), timestamp(2)) == ()


def test_oco_ambiguity_chooses_conservative_price_and_cancels_peer() -> None:
    broker = SimulatedBroker()
    target = request(OrderType.LIMIT, side=Side.SELL, limit="105")
    stop = request(OrderType.STOP_MARKET, side=Side.SELL, stop="95")
    target_order, stop_order = broker.activate_oco(target, stop, timestamp(1))
    fills = broker.process_market_activity((candle(1, high="106", low="94"),), timestamp(2))
    assert len(fills) == 1
    assert fills[0].order_id == stop_order.order_id
    assert fills[0].fill_price == 95
    assert fills[0].resolution is ExecutionResolution.AMBIGUOUS_CONSERVATIVE
    assert fills[0].ambiguity is True
    assert broker.get_order(target_order.order_id).status is OrderStatus.CANCELLED


def test_instances_have_independent_ids_and_deterministic_fingerprints() -> None:
    first, second = SimulatedBroker(), SimulatedBroker()
    assert first.activate(request(OrderType.MARKET), timestamp(1)).order_id.value == 1
    assert second.activate(request(OrderType.MARKET), timestamp(1)).order_id.value == 1
    first.process_market_activity((candle(1),), timestamp(2))
    second.process_market_activity((candle(1),), timestamp(2))
    assert first.fills == second.fills
    assert first.execution_fingerprint == second.execution_fingerprint


def test_market_activity_rejects_duplicate_products() -> None:
    with pytest.raises(BrokerStateError):
        SimulatedBroker().process_market_activity((candle(0), candle(0)), timestamp(1))


@pytest.mark.parametrize(
    "forge",
    [
        lambda value: replace(
            value,
            requested_base_quantity=BaseQuantity("1000"),
            normalized_base_quantity=BaseQuantity("1000"),
        ),
        lambda value: replace(value, quote_currency=AssetSymbol("ETH")),
        lambda value: replace(value, limit_price=Decimal("101.001")),
        lambda value: replace(
            value,
            product_spec=product(is_disabled=True),
            product_spec_fingerprint=product(is_disabled=True).fingerprint,
        ),
    ],
)
def test_activation_rejects_forged_normalization_evidence(
    forge: Callable[[NormalizedOrderRequest], NormalizedOrderRequest],
) -> None:
    broker = SimulatedBroker()
    valid = request(OrderType.LIMIT, limit="100")
    forged = forge(valid)
    before = broker.execution_fingerprint
    with pytest.raises(BrokerStateError, match="evidence"):
        broker.activate(forged, timestamp(1))
    assert broker.orders == ()
    assert broker.events == ()
    assert broker.execution_fingerprint == before
    assert broker.activate(valid, timestamp(1)).order_id.value == 1


def test_failed_oco_activation_is_atomic() -> None:
    broker = SimulatedBroker()
    target = request(OrderType.LIMIT, side=Side.SELL, limit="105")
    stop = request(OrderType.STOP_MARKET, side=Side.SELL, stop="95")
    late_stop = replace(
        stop,
        created_at=timestamp(2),
        source_intent=replace(stop.source_intent, created_at=timestamp(2)),
    )
    before = broker.execution_fingerprint
    with pytest.raises(BrokerStateError, match="precede"):
        broker.activate_oco(target, late_stop, timestamp(1))
    assert broker.orders == ()
    assert broker.events == ()
    assert broker.fills == ()
    assert broker.execution_fingerprint == before
    first, second = broker.activate_oco(target, stop, timestamp(1))
    assert (first.order_id.value, second.order_id.value) == (1, 2)
    assert first.oco_group_id == second.oco_group_id
    assert first.oco_group_id is not None and first.oco_group_id.value == 1
