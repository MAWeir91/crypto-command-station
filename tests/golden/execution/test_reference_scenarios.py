from decimal import Decimal

from command_station.accounting import InitialHolding, SpotAccountingEngine, SpotAccountSpec
from command_station.domain import ProductId, Side
from command_station.execution import (
    BaseQuantity,
    ExecutionResolution,
    NormalizedOrderRequest,
    OrderIntent,
    OrderStatus,
    OrderType,
    ReferenceExecutionSpec,
    SimulatedBroker,
    normalize_order_intent,
)
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.risk import RiskEngine
from command_station.runtime import ReferenceTradingRuntime, RuntimeEventKind, SimulatedClock
from tests.execution_fixtures import candle, product, timestamp
from tests.runtime_fixtures import canonical


def request(
    order_type: OrderType,
    *,
    side: Side = Side.BUY,
    limit: str | None = None,
    stop: str | None = None,
    created_minute: int = 1,
) -> NormalizedOrderRequest:
    return normalize_order_intent(
        OrderIntent(
            product_id=ProductId("BTC-USD"),
            side=side,
            order_type=order_type,
            base_quantity=BaseQuantity("1"),
            created_at=timestamp(created_minute),
            limit_price=limit,
            stop_price=stop,
        ),
        product(),
    )


def test_signal_bar_lookahead_golden() -> None:
    broker = SimulatedBroker()
    order = broker.activate(request(OrderType.LIMIT, limit="105"), timestamp(1))
    fills = broker.process_market_activity(
        (candle(0, open="100", high="110", low="90", close="100"),), timestamp(1)
    )
    assert fills == ()
    assert broker.get_order(order.order_id).status is OrderStatus.ACTIVE


def test_next_open_market_golden() -> None:
    broker = SimulatedBroker()
    broker.activate(request(OrderType.MARKET), timestamp(1))
    assert (
        broker.process_market_activity((candle(0, high="105", low="75", close="75"),), timestamp(1))
        == ()
    )
    fill = broker.process_market_activity(
        (candle(1, open="110", high="112", low="109", close="111"),), timestamp(2)
    )[0]
    assert fill.reference_price == Decimal("110")
    assert fill.resolution is ExecutionResolution.EXACT_NEXT_OPEN


def test_stop_gap_golden_uses_open_not_stop() -> None:
    broker = SimulatedBroker(ReferenceExecutionSpec(slippage_bps=50))
    broker.activate(request(OrderType.STOP_MARKET, side=Side.SELL, stop="95"), timestamp(1))
    fill = broker.process_market_activity(
        (candle(1, open="90", high="92", low="88", close="91"),), timestamp(2)
    )[0]
    assert (fill.reference_price, fill.fill_price, fill.resolution) == (
        Decimal("90"),
        Decimal("89.55"),
        ExecutionResolution.GAP,
    )


def test_same_minute_stop_target_golden_is_conservative() -> None:
    broker = SimulatedBroker()
    target, stop = broker.activate_oco(
        request(OrderType.LIMIT, side=Side.SELL, limit="105"),
        request(OrderType.STOP_MARKET, side=Side.SELL, stop="95"),
        timestamp(1),
    )
    fills = broker.process_market_activity(
        (candle(1, open="100", high="106", low="94", close="100"),), timestamp(2)
    )
    assert len(fills) == 1
    assert fills[0].order_id == stop.order_id
    assert fills[0].resolution is ExecutionResolution.AMBIGUOUS_CONSERVATIVE
    assert fills[0].ambiguity is True
    assert broker.get_order(target.order_id).status is OrderStatus.CANCELLED


def test_existing_stop_executes_before_bar_publication_golden() -> None:
    source = canonical("BTC-USD", minutes=2)
    feed = HistoricalReplayFeed((source,))
    runtime = ReferenceTradingRuntime(
        clock=SimulatedClock(feed.start),
        market_feed=feed,
        risk=RiskEngine(),
        accounting=SpotAccountingEngine(
            SpotAccountSpec(
                initial_cash="1000",
                product_specs=(product(),),
                initial_holdings=(InitialHolding(product().product_id, "10", "100"),),
            ),
            feed.start,
        ),
    )
    runtime.activate_order(
        request(
            OrderType.STOP_MARKET,
            side=Side.SELL,
            stop="1",
            created_minute=0,
        )
    )
    step = runtime.step()
    assert step is not None and len(step.fills) == 1
    kinds = [event.kind for event in step.trace_events]
    assert kinds.index(RuntimeEventKind.EXECUTION_PROCESSED) < kinds.index(
        RuntimeEventKind.BARS_PUBLISHED
    )
    assert kinds.index(RuntimeEventKind.EXECUTION_PROCESSED) < kinds.index(
        RuntimeEventKind.MARKET_STATE_READY
    )
