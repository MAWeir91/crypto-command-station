from decimal import Decimal

from command_station.accounting import InitialHolding, SpotAccountingEngine, SpotAccountSpec
from command_station.domain import ProductId, Side
from command_station.execution import (
    BaseQuantity,
    CancellationReason,
    ExecutionResolution,
    Fill,
    NormalizedOrderRequest,
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    normalize_order_intent,
)
from command_station.market_data.datasets import CanonicalCandleDataset
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.runtime import (
    ReferenceRuntimeResult,
    ReferenceTradingRuntime,
    RuntimeEventKind,
    SimulatedClock,
)
from tests.execution_fixtures import candle, product
from tests.runtime_fixtures import canonical


def test_runtime_activation_after_step_fills_only_next_open_before_publication() -> None:
    source = canonical("BTC-USD", minutes=3)
    feed = HistoricalReplayFeed((source,))
    runtime = _funded_runtime(feed)
    first = runtime.step()
    assert first is not None and first.fills == ()
    request = normalize_order_intent(
        OrderIntent(
            product_id=ProductId("BTC-USD"),
            side=Side.BUY,
            order_type=OrderType.MARKET,
            base_quantity=BaseQuantity("1"),
            created_at=runtime.clock.now,
        ),
        product(),
    )
    runtime.activate_order(request, max_quote_reservation=Decimal("1000"))
    second = runtime.step()
    assert second is not None and len(second.fills) == 1
    assert second.fills[0].market_interval_open == source.candles[1].open_time
    assert [event.kind for event in second.trace_events] == [
        RuntimeEventKind.CLOCK_ADVANCED,
        RuntimeEventKind.MARKET_ACTIVITY,
        RuntimeEventKind.EXECUTION_PROCESSED,
        RuntimeEventKind.ACCOUNTING_APPLIED,
        RuntimeEventKind.PORTFOLIO_UPDATED,
        RuntimeEventKind.BARS_PUBLISHED,
        RuntimeEventKind.MARKET_STATE_READY,
    ]


def test_multi_product_interval_order_does_not_change_execution() -> None:
    btc, eth = canonical("BTC-USD", minutes=2), canonical("ETH-USD", minutes=2)
    first_feed = HistoricalReplayFeed((btc, eth))
    second_feed = HistoricalReplayFeed((eth, btc))
    first = _funded_runtime(first_feed)
    second = _funded_runtime(second_feed)
    for runtime in (first, second):
        for product_id in ("BTC-USD", "ETH-USD"):
            runtime.activate_order(
                normalize_order_intent(
                    OrderIntent(
                        product_id=ProductId(product_id),
                        side=Side.BUY,
                        order_type=OrderType.MARKET,
                        base_quantity=BaseQuantity("1"),
                        created_at=runtime.clock.now,
                    ),
                    product(product_id),
                ),
                max_quote_reservation=Decimal("1000"),
            )
    assert first.run().execution_fingerprint == second.run().execution_fingerprint


def _runtime_with_prices(
    prices: tuple[tuple[str, str, str, str], ...],
) -> tuple[CanonicalCandleDataset, ReferenceTradingRuntime]:
    """Build a real replay/runtime composition with explicit OHLC intervals."""
    source = canonical("BTC-USD", minutes=len(prices))
    source = CanonicalCandleDataset(
        product_id=source.product_id,
        start=source.start,
        end=source.end,
        as_of=source.as_of,
        gaps=source.gaps,
        source_pages=source.source_pages,
        candles=tuple(
            candle(
                minute,
                open=open_price,
                high=high,
                low=low,
                close=close,
            )
            for minute, (open_price, high, low, close) in enumerate(prices)
        ),
    )
    feed = HistoricalReplayFeed((source,))
    return source, _funded_runtime(feed)


def _request(
    runtime: ReferenceTradingRuntime,
    *,
    side: Side,
    order_type: OrderType,
    limit_price: str | None = None,
    stop_price: str | None = None,
) -> NormalizedOrderRequest:
    return normalize_order_intent(
        OrderIntent(
            product_id=ProductId("BTC-USD"),
            side=side,
            order_type=order_type,
            base_quantity=BaseQuantity("1"),
            created_at=runtime.clock.now,
            limit_price=limit_price,
            stop_price=stop_price,
        ),
        product(),
    )


def test_runtime_limit_persists_until_a_later_interval_touches() -> None:
    source, runtime = _runtime_with_prices(
        (
            ("100", "101", "99", "100"),
            ("100", "102", "99", "101"),
            ("101", "106", "100", "105"),
            ("105", "106", "104", "105"),
        )
    )
    runtime.step()
    order = runtime.activate_order(
        _request(runtime, side=Side.SELL, order_type=OrderType.LIMIT, limit_price="105")
    )

    untouched = runtime.step()
    assert untouched is not None and untouched.fills == ()
    assert runtime.broker.orders[0].status is OrderStatus.ACTIVE

    touched = runtime.step()
    assert touched is not None and len(touched.fills) == 1
    fill = touched.fills[0]
    assert fill.order_id == order.order_id
    assert fill.fill_price == 105
    assert fill.resolution is ExecutionResolution.PRICE_CROSSED
    assert fill.market_interval_open == source.candles[2].open_time
    assert fill.activated_at <= fill.market_interval_open
    assert runtime.broker.orders[0].status.value == "FILLED"


def test_runtime_cancellation_prevents_later_limit_fill_and_is_fingerprinted() -> None:
    _, runtime = _runtime_with_prices(
        (
            ("100", "101", "99", "100"),
            ("100", "102", "99", "101"),
            ("101", "106", "100", "105"),
            ("105", "106", "104", "105"),
        )
    )
    runtime.step()
    activated = runtime.activate_order(
        _request(runtime, side=Side.SELL, order_type=OrderType.LIMIT, limit_price="105")
    )
    untouched = runtime.step()
    assert untouched is not None and untouched.fills == ()
    assert runtime.broker.orders[0].status is OrderStatus.ACTIVE
    before_cancel = runtime.broker.execution_fingerprint

    cancelled = runtime.cancel_order(activated.order_id, CancellationReason.USER_REQUEST)
    assert cancelled.status is OrderStatus.CANCELLED
    later = runtime.step()
    assert later is not None and later.fills == ()
    final = runtime.broker.orders[0]
    assert final.status is OrderStatus.CANCELLED
    assert final.cancellation_reason is CancellationReason.USER_REQUEST
    assert runtime.broker.execution_fingerprint != before_cancel


def test_runtime_oco_ambiguity_fills_conservatively_before_publication() -> None:
    _, runtime = _runtime_with_prices(
        (("100", "101", "99", "100"), ("100", "110", "90", "100"), ("100", "101", "99", "100"))
    )
    runtime.step()
    target = _request(runtime, side=Side.SELL, order_type=OrderType.LIMIT, limit_price="105")
    stop = _request(runtime, side=Side.SELL, order_type=OrderType.STOP_MARKET, stop_price="95")
    first, second = runtime.activate_oco(target, stop)

    result = runtime.step()
    assert result is not None and len(result.fills) == 1
    fill = result.fills[0]
    assert fill.order_id == second.order_id
    assert fill.fill_price == 95
    assert fill.resolution is ExecutionResolution.AMBIGUOUS_CONSERVATIVE
    assert fill.ambiguity is True
    assert fill.activated_at <= fill.market_interval_open
    snapshots = {order.order_id: order for order in runtime.broker.orders}
    assert snapshots[second.order_id].status is OrderStatus.FILLED
    assert snapshots[first.order_id].status is OrderStatus.CANCELLED
    assert snapshots[first.order_id].cancellation_reason is CancellationReason.OCO_PEER_FILLED
    kinds = [event.kind for event in result.trace_events]
    assert kinds.index(RuntimeEventKind.EXECUTION_PROCESSED) < kinds.index(
        RuntimeEventKind.BARS_PUBLISHED
    )
    assert runtime.step() is not None
    assert len(runtime.broker.fills) == 1


def test_fresh_equivalent_runtime_compositions_have_identical_execution() -> None:
    def execute() -> tuple[ReferenceRuntimeResult, tuple[Fill, ...], tuple[Order, ...], str]:
        _, runtime = _runtime_with_prices(
            (
                ("100", "101", "99", "100"),
                ("101", "102", "100", "101"),
                ("102", "103", "101", "102"),
            )
        )
        runtime.step()
        runtime.activate_order(
            _request(runtime, side=Side.BUY, order_type=OrderType.MARKET),
            max_quote_reservation=Decimal("1000"),
        )
        result = runtime.run()
        return result, runtime.broker.fills, runtime.broker.orders, runtime.trace_fingerprint

    first = execute()
    second = execute()
    assert len(first[1]) == 1
    assert first[1] == second[1]
    assert first[0].execution_fingerprint == second[0].execution_fingerprint
    assert first[2] == second[2]
    assert first[3] == second[3]


def _funded_runtime(feed: HistoricalReplayFeed) -> ReferenceTradingRuntime:
    products = tuple(product(source.product_id.value) for source in feed.canonical_sources)
    account = SpotAccountingEngine(
        SpotAccountSpec(
            initial_cash="100000",
            product_specs=products,
            initial_holdings=tuple(InitialHolding(p.product_id, "10", "100") for p in products),
        ),
        feed.start,
    )
    return ReferenceTradingRuntime(
        clock=SimulatedClock(feed.start), market_feed=feed, accounting=account
    )
