from decimal import Decimal

from command_station.accounting import USD, LedgerCategory
from command_station.domain import Side
from command_station.execution import OrderType, SimulatedBroker
from tests.accounting_fixtures import account, request, reserve
from tests.execution_fixtures import candle, timestamp


def test_buy_exit_cancel_golden_financial_history() -> None:
    engine = account(cash="1000", fee_bps=100)
    broker = SimulatedBroker(engine.execution_spec)
    reserve(engine, broker, request(quantity="2"), Decimal(202))
    assert (engine.account_view.balance(USD).total, engine.account_view.balance(USD).reserved) == (
        Decimal(1000),
        Decimal(202),
    )
    engine.apply_fill_batch(
        broker.process_market_activity((candle(0),), timestamp(1)), broker.orders, timestamp(1)
    )
    reserve(engine, broker, request(Side.SELL, minute=1))
    engine.apply_fill_batch(
        broker.process_market_activity(
            (candle(1, open="120", high="120", low="120", close="120"),), timestamp(2)
        ),
        broker.orders,
        timestamp(2),
    )
    assert engine.account_view.balance(USD).total == Decimal("916.8")
    assert engine.positions[0].actual_quantity == 1
    assert engine.positions[0].total_cost_basis == 100
    assert engine.positions[0].gross_realized_pnl == 20
    assert engine.fees_to_date == Decimal("3.2")
    order = reserve(engine, broker, request(Side.SELL, OrderType.LIMIT, minute=2, price="150"))
    before = engine.lots, engine.lot_consumptions, engine.positions
    broker.cancel(order.order_id, timestamp(2))
    engine.apply_fill_batch((), broker.orders, timestamp(2))
    assert (engine.lots, engine.lot_consumptions, engine.positions) == before
    portfolio = engine.update_portfolio(
        (candle(2, open="120", high="120", low="120", close="120"),), timestamp(3)
    )
    assert portfolio.total_equity == Decimal("1036.8")
    assert portfolio.gross_unrealized_pnl == 20
    assert [t.category for t in engine.ledger] == [
        LedgerCategory.INITIAL_DEPOSIT,
        LedgerCategory.ORDER_RESERVATION,
        LedgerCategory.TRADE_FILL,
        LedgerCategory.TRADING_FEE,
        LedgerCategory.ORDER_RESERVATION,
        LedgerCategory.TRADE_FILL,
        LedgerCategory.TRADING_FEE,
        LedgerCategory.ORDER_RESERVATION,
        LedgerCategory.ORDER_RESERVATION_RELEASE,
    ]


def test_existing_stop_and_oco_settle_golden_before_publication() -> None:
    from command_station.accounting import InitialHolding, SpotAccountingEngine, SpotAccountSpec
    from command_station.domain import ProductId
    from command_station.execution import OrderStatus, ReferenceExecutionSpec
    from command_station.market_data.datasets import CanonicalCandleDataset
    from command_station.market_data.replay import HistoricalReplayFeed
    from command_station.runtime import ReferenceTradingRuntime, RuntimeEventKind, SimulatedClock
    from tests.execution_fixtures import product
    from tests.runtime_fixtures import canonical

    for oco in (False, True):
        source = canonical("BTC-USD", minutes=2)
        source = CanonicalCandleDataset(
            product_id=source.product_id,
            start=source.start,
            end=source.end,
            as_of=source.as_of,
            source_pages=source.source_pages,
            gaps=(),
            candles=(candle(0), candle(1, open="100", high="110", low="90", close="100")),
        )
        feed = HistoricalReplayFeed((source,))
        engine = SpotAccountingEngine(
            SpotAccountSpec(
                initial_cash="1000",
                product_specs=(product(),),
                initial_holdings=(InitialHolding(ProductId("BTC-USD"), "1", "80"),),
            ),
            feed.start,
            ReferenceExecutionSpec(fee_bps=100),
        )
        rt = ReferenceTradingRuntime(
            clock=SimulatedClock(feed.start),
            market_feed=feed,
            broker=SimulatedBroker(engine.execution_spec),
            accounting=engine,
        )
        rt.step()
        stop = request(Side.SELL, OrderType.STOP_MARKET, price="95", minute=1)
        if oco:
            rt.activate_oco(request(Side.SELL, OrderType.LIMIT, price="105", minute=1), stop)
        else:
            rt.activate_order(stop)
        assert engine.account_view.balance(product().base_currency).reserved == 1
        step = rt.step()
        assert step is not None and step.portfolio_snapshot is not None
        assert len(step.fills) == 1
        assert step.fills[0].fill_price == 95
        assert step.portfolio_snapshot.cash_total == Decimal("1094.05")
        assert step.portfolio_snapshot.gross_realized_pnl == 15
        assert step.portfolio_snapshot.fees_to_date == Decimal("0.95")
        assert engine.positions[0].actual_quantity == 0
        assert engine.reservations[0].remaining_amount == 0
        assert [e.kind for e in step.trace_events] == [
            RuntimeEventKind.CLOCK_ADVANCED,
            RuntimeEventKind.MARKET_ACTIVITY,
            RuntimeEventKind.EXECUTION_PROCESSED,
            RuntimeEventKind.ACCOUNTING_APPLIED,
            RuntimeEventKind.PORTFOLIO_UPDATED,
            RuntimeEventKind.BARS_PUBLISHED,
            RuntimeEventKind.MARKET_STATE_READY,
        ]
        if oco:
            assert [o.status for o in rt.broker.orders] == [
                OrderStatus.CANCELLED,
                OrderStatus.FILLED,
            ]
            assert len(engine.applied_fill_ids) == 1
