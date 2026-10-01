from dataclasses import replace
from decimal import Decimal

from command_station.accounting import InitialHolding, SpotAccountingEngine, SpotAccountSpec
from command_station.accounting._exact import fee, mul
from command_station.domain import ProductId, Side
from command_station.execution import (
    BaseQuantity,
    Fill,
    FillId,
    NormalizedOrderRequest,
    Order,
    OrderIntent,
    OrderType,
    ReferenceExecutionSpec,
    SimulatedBroker,
    normalize_order_intent,
)
from tests.execution_fixtures import candle, product, timestamp


def account(
    *, cash: str = "10000", holding: str | None = None, cost: str = "80", fee_bps: int = 100
) -> SpotAccountingEngine:
    return SpotAccountingEngine(
        SpotAccountSpec(
            initial_cash=cash,
            product_specs=(product(),),
            initial_holdings=()
            if holding is None
            else (InitialHolding(ProductId("BTC-USD"), holding, cost),),
        ),
        timestamp(),
        ReferenceExecutionSpec(fee_bps=fee_bps),
    )


def request(
    side: Side = Side.BUY,
    kind: OrderType = OrderType.MARKET,
    *,
    quantity: str = "1",
    price: str = "100",
    minute: int = 0,
) -> NormalizedOrderRequest:
    return normalize_order_intent(
        OrderIntent(
            product_id=ProductId("BTC-USD"),
            side=side,
            order_type=kind,
            base_quantity=BaseQuantity(quantity),
            created_at=timestamp(minute),
            limit_price=price if kind is OrderType.LIMIT else None,
            stop_price=price if kind is OrderType.STOP_MARKET else None,
        ),
        product(),
    )


def reserve(
    engine: SpotAccountingEngine,
    broker: SimulatedBroker,
    req: NormalizedOrderRequest,
    cap: Decimal | None = None,
) -> Order:
    plan = engine.prepare_reservation((req,), max_quote_reservation=cap)
    order = broker.activate(req, req.created_at)
    engine.bind_reservation(plan, (order,), req.created_at)
    return order


def fill_fact(
    order: Order,
    spec: ReferenceExecutionSpec,
    *,
    quantity: str = "1",
    price: str = "100",
    fill_id: int = 1,
    minute: int = 0,
) -> Fill:
    # Generate reference provenance from a real broker, then construct a partial-fact fixture.
    req = request(
        order.side,
        order.order_type,
        quantity=str(order.activated_base_quantity.value),
        price=str(order.limit_price or order.stop_price or Decimal("100")),
        minute=minute,
    )
    temporary = SimulatedBroker(spec)
    temporary.activate(req, timestamp(minute))
    full = temporary.process_market_activity(
        (candle(minute, open=price, high=price, low=price, close=price),), timestamp(minute + 1)
    )[0]
    amount = Decimal(quantity)
    return replace(
        full,
        order_id=order.order_id,
        fill_id=FillId(fill_id),
        activated_at=order.activated_at,
        base_quantity=amount,
        fee_amount=fee(mul(Decimal(price), amount), spec.fee_bps),
    )
