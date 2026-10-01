from decimal import Decimal, localcontext

from hypothesis import given
from hypothesis import strategies as st

from command_station.domain import ProductId, Side
from command_station.execution import (
    BaseQuantity,
    ExecutionResolution,
    NormalizedOrderRequest,
    OrderIntent,
    OrderType,
    ReferenceExecutionSpec,
    SimulatedBroker,
    normalize_order_intent,
)
from tests.execution_fixtures import candle, product, timestamp


def _request(
    order_type: OrderType,
    *,
    side: Side = Side.BUY,
    product_id: str = "BTC-USD",
    quantity: str = "1",
    limit: str | None = None,
    stop: str | None = None,
) -> NormalizedOrderRequest:
    return normalize_order_intent(
        OrderIntent(
            product_id=ProductId(product_id),
            side=side,
            order_type=order_type,
            base_quantity=BaseQuantity(quantity),
            created_at=timestamp(1),
            limit_price=limit,
            stop_price=stop,
        ),
        product(product_id),
    )


@given(st.integers(min_value=10, max_value=1_000_000))
def test_normalized_quantity_never_exceeds_requested(milliunits: int) -> None:
    requested = Decimal(milliunits) / Decimal(10_000)
    normalized = _request(OrderType.MARKET, quantity=str(requested))
    assert normalized.normalized_base_quantity.value <= requested


@given(st.integers(min_value=10, max_value=10_000))
def test_limit_normalization_never_becomes_more_aggressive(price_mills: int) -> None:
    requested = Decimal(price_mills) / Decimal(1000)
    buy = _request(OrderType.LIMIT, side=Side.BUY, limit=str(requested))
    sell = _request(OrderType.LIMIT, side=Side.SELL, limit=str(requested))
    assert buy.limit_price is not None and buy.limit_price <= requested
    assert sell.limit_price is not None and sell.limit_price >= requested


@given(st.integers(min_value=1, max_value=1000))
def test_activation_at_t_never_fills_interval_ending_t(open_price: int) -> None:
    broker = SimulatedBroker()
    broker.activate(_request(OrderType.MARKET), timestamp(1))
    interval = candle(
        0,
        open=str(open_price),
        high=str(open_price),
        low=str(open_price),
        close=str(open_price),
    )
    assert broker.process_market_activity((interval,), timestamp(1)) == ()


@given(
    prior_open=st.integers(min_value=1, max_value=1000),
    future_open=st.integers(min_value=1, max_value=1000),
)
def test_market_fills_first_eligible_future_open(prior_open: int, future_open: int) -> None:
    broker = SimulatedBroker()
    broker.activate(_request(OrderType.MARKET), timestamp(1))
    prior = candle(
        0,
        open=str(prior_open),
        high=str(prior_open),
        low=str(prior_open),
        close=str(prior_open),
    )
    future = candle(
        1,
        open=str(future_open),
        high=str(future_open),
        low=str(future_open),
        close=str(future_open),
    )
    assert broker.process_market_activity((prior,), timestamp(1)) == ()
    fill = broker.process_market_activity((future,), timestamp(2))[0]
    assert fill.reference_price == future_open
    assert fill.market_interval_open == timestamp(1)


@given(st.integers(min_value=2, max_value=1000))
def test_limit_fills_never_violate_limit(limit: int) -> None:
    buy_broker, sell_broker = SimulatedBroker(), SimulatedBroker()
    buy_broker.activate(_request(OrderType.LIMIT, side=Side.BUY, limit=str(limit)), timestamp(1))
    sell_broker.activate(_request(OrderType.LIMIT, side=Side.SELL, limit=str(limit)), timestamp(1))
    interval = candle(
        1,
        open=str(limit),
        high=str(limit + 1),
        low=str(limit - 1),
        close=str(limit),
    )
    assert buy_broker.process_market_activity((interval,), timestamp(2))[0].fill_price <= limit
    assert sell_broker.process_market_activity((interval,), timestamp(2))[0].fill_price >= limit


@given(st.integers(min_value=2, max_value=1000))
def test_strict_stop_gap_never_receives_stop_price(stop: int) -> None:
    broker = SimulatedBroker()
    broker.activate(_request(OrderType.STOP_MARKET, side=Side.SELL, stop=str(stop)), timestamp(1))
    gap_open = stop - 1
    interval = candle(
        1,
        open=str(gap_open),
        high=str(gap_open),
        low=str(gap_open),
        close=str(gap_open),
    )
    fill = broker.process_market_activity((interval,), timestamp(2))[0]
    assert fill.reference_price == gap_open
    assert fill.reference_price != stop
    assert fill.resolution is ExecutionResolution.GAP


@given(st.integers(min_value=10, max_value=100_000))
def test_filled_quantity_never_exceeds_normalized_quantity(milliunits: int) -> None:
    quantity = str(Decimal(milliunits) / Decimal(1000))
    normalized = _request(OrderType.MARKET, quantity=quantity)
    broker = SimulatedBroker()
    order = broker.activate(normalized, timestamp(1))
    fill = broker.process_market_activity((candle(1),), timestamp(2))[0]
    assert fill.base_quantity <= order.activated_base_quantity.value


@given(
    high=st.integers(min_value=105, max_value=200),
    low=st.integers(min_value=1, max_value=95),
)
def test_oco_produces_at_most_one_fill(high: int, low: int) -> None:
    broker = SimulatedBroker()
    broker.activate_oco(
        _request(OrderType.LIMIT, side=Side.SELL, limit="105"),
        _request(OrderType.STOP_MARKET, side=Side.SELL, stop="95"),
        timestamp(1),
    )
    fills = broker.process_market_activity(
        (candle(1, open="100", high=str(high), low=str(low)),), timestamp(2)
    )
    assert len(fills) <= 1


@given(st.integers(min_value=1, max_value=18))
def test_execution_arithmetic_and_fingerprint_ignore_decimal_precision(precision: int) -> None:
    def execute(context_precision: int) -> tuple[object, str]:
        broker = SimulatedBroker(ReferenceExecutionSpec(slippage_bps=37, fee_bps=19))
        broker.activate(_request(OrderType.MARKET, quantity="1.234"), timestamp(1))
        with localcontext() as context:
            context.prec = context_precision
            fills = broker.process_market_activity(
                (candle(1, open="123.4567", high="124", low="123", close="123.5"),),
                timestamp(2),
            )
        return fills, broker.execution_fingerprint

    assert execute(precision) == execute(28)


def test_fresh_identical_broker_sequences_have_identical_fingerprints() -> None:
    def execute() -> str:
        broker = SimulatedBroker(ReferenceExecutionSpec(slippage_bps=5, fee_bps=7))
        broker.activate(_request(OrderType.MARKET), timestamp(1))
        broker.process_market_activity((candle(1),), timestamp(2))
        return broker.execution_fingerprint

    assert execute() == execute()


def test_execution_interval_product_permutation_preserves_logical_fills() -> None:
    def execute(reverse: bool) -> tuple[object, str]:
        broker = SimulatedBroker()
        broker.activate(_request(OrderType.MARKET, product_id="BTC-USD"), timestamp(1))
        broker.activate(_request(OrderType.MARKET, product_id="ETH-USD"), timestamp(1))
        intervals = (
            candle(1, product_id="BTC-USD"),
            candle(1, product_id="ETH-USD"),
        )
        fills = broker.process_market_activity(
            tuple(reversed(intervals)) if reverse else intervals, timestamp(2)
        )
        return fills, broker.execution_fingerprint

    assert execute(False) == execute(True)
