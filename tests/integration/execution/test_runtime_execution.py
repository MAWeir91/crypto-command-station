from command_station.domain import ProductId, Side
from command_station.execution import BaseQuantity, OrderIntent, OrderType, normalize_order_intent
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.runtime import ReferenceTradingRuntime, RuntimeEventKind, SimulatedClock
from tests.execution_fixtures import product
from tests.runtime_fixtures import canonical


def test_runtime_activation_after_step_fills_only_next_open_before_publication() -> None:
    source = canonical("BTC-USD", minutes=3)
    feed = HistoricalReplayFeed((source,))
    runtime = ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed)
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
    runtime.activate_order(request)
    second = runtime.step()
    assert second is not None and len(second.fills) == 1
    assert second.fills[0].market_interval_open == source.candles[1].open_time
    assert [event.kind for event in second.trace_events] == [
        RuntimeEventKind.CLOCK_ADVANCED,
        RuntimeEventKind.MARKET_ACTIVITY,
        RuntimeEventKind.EXECUTION_PROCESSED,
        RuntimeEventKind.BARS_PUBLISHED,
        RuntimeEventKind.MARKET_STATE_READY,
    ]


def test_multi_product_interval_order_does_not_change_execution() -> None:
    btc, eth = canonical("BTC-USD", minutes=2), canonical("ETH-USD", minutes=2)
    first_feed = HistoricalReplayFeed((btc, eth))
    second_feed = HistoricalReplayFeed((eth, btc))
    first = ReferenceTradingRuntime(clock=SimulatedClock(first_feed.start), market_feed=first_feed)
    second = ReferenceTradingRuntime(
        clock=SimulatedClock(second_feed.start), market_feed=second_feed
    )
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
                )
            )
    assert first.run().execution_fingerprint == second.run().execution_fingerprint
