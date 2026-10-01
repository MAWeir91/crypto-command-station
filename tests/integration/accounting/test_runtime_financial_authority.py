from dataclasses import replace
from decimal import Decimal

import pytest

from command_station.accounting import (
    USD,
    InsufficientAvailableBalanceError,
    SpotAccountingEngine,
    SpotAccountSpec,
)
from command_station.domain import ProductId, Side, Timeframe
from command_station.execution import OrderType, SimulatedBroker
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.runtime import (
    InvalidRuntimeConfigurationError,
    ReferenceTradingRuntime,
    RuntimeEngineError,
    RuntimeEventKind,
    RuntimeLifecycle,
    SimulatedClock,
)
from tests.accounting_fixtures import account, request
from tests.execution_fixtures import product, timestamp
from tests.runtime_fixtures import canonical


def runtime(
    *, holding: str | None = None, cash: str = "1000", fee_bps: int = 100
) -> ReferenceTradingRuntime:
    feed = HistoricalReplayFeed((canonical("BTC-USD", minutes=3),))
    accounting = account(cash=cash, holding=holding, fee_bps=fee_bps)
    return ReferenceTradingRuntime(
        clock=SimulatedClock(feed.start),
        market_feed=feed,
        broker=SimulatedBroker(accounting.execution_spec),
        accounting=accounting,
    )


def test_real_buy_before_publication_with_read_only_evidence() -> None:
    rt = runtime()
    rt.activate_order(request(), max_quote_reservation=Decimal(100))
    step = rt.step()
    assert (
        step is not None and step.account_view is not None and step.portfolio_snapshot is not None
    )
    # Runtime fixture canonical close/open prices are minute + 1.
    assert len(step.fills) == 1
    assert step.account_view.balance(USD).total == Decimal("998.99")
    assert step.position_views[0].actual_quantity == 1
    kinds = [e.kind for e in step.trace_events]
    assert (
        kinds.index(RuntimeEventKind.EXECUTION_PROCESSED)
        < kinds.index(RuntimeEventKind.ACCOUNTING_APPLIED)
        < kinds.index(RuntimeEventKind.PORTFOLIO_UPDATED)
        < kinds.index(RuntimeEventKind.BARS_PUBLISHED)
    )
    assert len(step.ledger_transactions_created) == 3
    result = rt.run()
    assert result.accounting_fingerprint is not None
    assert result.final_account_view is not None
    assert result.final_portfolio_snapshot is not None
    assert result.ledger_transaction_count == 5


def test_real_sell_initial_holding_before_publication() -> None:
    rt = runtime(holding="2")
    rt.activate_order(request(Side.SELL))
    step = rt.step()
    assert step is not None and step.portfolio_snapshot is not None
    snapshot = step.portfolio_snapshot
    assert snapshot.positions[0].actual_quantity == 1
    assert snapshot.gross_realized_pnl == -79
    assert snapshot.fees_to_date == Decimal("0.01")
    assert snapshot.cash_total == Decimal("1000.99")


def test_insufficient_activation_does_not_mutate_broker_or_account() -> None:
    rt = runtime(cash="10")
    assert rt.accounting is not None
    before = rt.broker.execution_fingerprint, rt.accounting.accounting_fingerprint
    with pytest.raises(InsufficientAvailableBalanceError):
        rt.activate_order(request(), max_quote_reservation=Decimal(11))
    assert (rt.broker.execution_fingerprint, rt.accounting.accounting_fingerprint) == before


def test_unaffordable_gap_fails_without_publication_or_accounting_mutation() -> None:
    rt = runtime()
    rt.activate_order(request(), max_quote_reservation=Decimal("0.5"))
    assert rt.accounting is not None
    before = rt.accounting.accounting_fingerprint
    with pytest.raises(RuntimeEngineError):
        rt.step()
    assert rt.lifecycle is RuntimeLifecycle.FAILED
    assert rt.accounting.accounting_fingerprint == before
    assert len(rt.broker.fills) == 1
    assert rt.market_view.latest_bar(ProductId("BTC-USD"), Timeframe.ONE_MINUTE) is None
    assert RuntimeEventKind.BARS_PUBLISHED not in [e.kind for e in rt.trace_events]
    with pytest.raises(RuntimeEngineError):
        rt.step()


def test_cancel_releases_availability_without_totals_or_lots() -> None:
    rt = runtime()
    assert rt.accounting is not None
    before = rt.accounting.account_view, rt.accounting.positions, rt.accounting.lots
    order = rt.activate_order(request(kind=OrderType.LIMIT, price="0.01"))
    assert rt.accounting.account_view.balance(USD).reserved > 0
    rt.cancel_order(order.order_id)
    assert (rt.accounting.account_view, rt.accounting.positions, rt.accounting.lots) == before
    assert rt.run().fill_count == 0


@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
def test_oco_shared_reservation_and_one_financial_settlement(side: Side) -> None:
    rt = runtime(holding="2" if side is Side.SELL else None)
    assert rt.accounting is not None
    target = request(side, OrderType.LIMIT, price="1")
    stop = request(side, OrderType.STOP_MARKET, price="1")
    rt.activate_oco(target, stop, max_quote_reservation=Decimal(10) if side is Side.BUY else None)
    assert len(rt.accounting.reservations) == 1
    assert rt.accounting.reservations[0].original_amount == (10 if side is Side.BUY else 1)
    first = rt.step()
    assert first is not None and len(first.fills) == 1
    assert rt.accounting.reservations[0].remaining_amount == 0
    assert len(rt.accounting.applied_fill_ids) == 1
    assert len(rt.broker.fills) == 1
    rt.run()
    assert len(rt.broker.fills) == 1


def test_oco_single_peer_cancel_rejects_and_whole_group_restores_availability() -> None:
    rt = runtime(holding="2")
    assert rt.accounting is not None
    before = rt.accounting.account_view, rt.accounting.lots, rt.accounting.positions
    target, stop = rt.activate_oco(
        request(Side.SELL, OrderType.LIMIT, price="100"),
        request(Side.SELL, OrderType.STOP_MARKET, price="0.01"),
    )
    fingerprint = rt.broker.execution_fingerprint, rt.accounting.accounting_fingerprint
    with pytest.raises(RuntimeEngineError):
        rt.cancel_order(target.order_id)
    assert (rt.broker.execution_fingerprint, rt.accounting.accounting_fingerprint) == fingerprint
    assert stop.oco_group_id is not None
    rt.cancel_oco(stop.oco_group_id)
    assert (rt.accounting.account_view, rt.accounting.lots, rt.accounting.positions) == before
    assert rt.run().fill_count == 0


def test_market_only_cannot_activate_or_process_external_orders() -> None:
    feed = HistoricalReplayFeed((canonical("BTC-USD", minutes=2),))
    rt = ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed)
    with pytest.raises(RuntimeEngineError):
        rt.activate_order(request(), max_quote_reservation=Decimal(100))
    assert rt.broker.orders == ()
    rt.broker.activate(request(), timestamp())
    with pytest.raises(RuntimeEngineError):
        rt.step()
    assert rt.broker.fills == ()


def test_constructor_rejects_preexisting_broker_and_incompatible_account() -> None:
    feed = HistoricalReplayFeed((canonical("BTC-USD", minutes=2),))
    broker = SimulatedBroker()
    broker.activate(request(), timestamp())
    with pytest.raises(InvalidRuntimeConfigurationError):
        ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed, broker=broker)
    for accounting in (
        SpotAccountingEngine(SpotAccountSpec(initial_cash="100", product_specs=()), timestamp()),
        account(),
    ):
        with pytest.raises(InvalidRuntimeConfigurationError):
            ReferenceTradingRuntime(
                clock=SimulatedClock(feed.start), market_feed=feed, accounting=accounting
            )
    with pytest.raises(InvalidRuntimeConfigurationError):
        ReferenceTradingRuntime(
            clock=SimulatedClock(feed.start),
            market_feed=feed,
            accounting=SpotAccountingEngine(
                SpotAccountSpec(initial_cash="100", product_specs=(product(),)), timestamp(1)
            ),
        )


def test_external_order_and_fill_paths_fail_closed() -> None:
    rt = runtime()
    rt.broker.activate(request(), timestamp())
    with pytest.raises(RuntimeEngineError):
        rt.step()
    assert rt.broker.fills == ()
    other = runtime()
    other.activate_order(request(), max_quote_reservation=Decimal(10))
    from tests.execution_fixtures import candle

    other.broker.process_market_activity((candle(0),), timestamp(1))
    with pytest.raises(RuntimeEngineError):
        other.step()


def test_multi_product_settlement_and_fresh_run_identity() -> None:
    def execute(reverse: bool) -> tuple[object, ...]:
        sources = (canonical("BTC-USD", minutes=3), canonical("ETH-USD", minutes=3))
        feed = HistoricalReplayFeed(tuple(reversed(sources)) if reverse else sources)
        products = (product(), product("ETH-USD"))
        spec = SpotAccountSpec(
            initial_cash="100", product_specs=tuple(reversed(products)) if reverse else products
        )
        engine = SpotAccountingEngine(spec, feed.start)
        rt = ReferenceTradingRuntime(
            clock=SimulatedClock(feed.start), market_feed=feed, accounting=engine
        )
        from command_station.execution import normalize_order_intent

        for p in products:
            req = request()
            intent = replace(req.source_intent, product_id=p.product_id)
            rt.activate_order(normalize_order_intent(intent, p), max_quote_reservation=Decimal(10))
        result = rt.run()
        return (
            rt.broker.fills,
            engine.ledger,
            engine.account_view,
            engine.positions,
            engine.portfolio_history,
            result.accounting_fingerprint,
        )

    assert execute(False) == execute(True)


def test_favorable_runtime_buy_limit_releases_worst_case_excess() -> None:
    rt = runtime()
    assert rt.accounting is not None
    rt.activate_order(request(kind=OrderType.LIMIT, price="100"))
    assert rt.accounting.account_view.balance(USD).reserved == 101
    step = rt.step()
    assert step is not None and step.portfolio_snapshot is not None
    assert step.fills[0].fill_price == 1
    assert step.portfolio_snapshot.cash_reserved == 0
    assert step.portfolio_snapshot.cash_total == Decimal("998.99")
    assert rt.accounting.reservations[0].remaining_amount == 0


def test_runtime_one_unaffordable_same_time_fill_rolls_back_whole_batch() -> None:
    rt = runtime()
    assert rt.accounting is not None
    rt.activate_order(request(), max_quote_reservation=Decimal(10))
    rt.activate_order(request(), max_quote_reservation=Decimal("0.5"))
    before = rt.accounting.accounting_fingerprint
    with pytest.raises(RuntimeEngineError):
        rt.step()
    assert len(rt.broker.fills) == 2
    assert rt.accounting.accounting_fingerprint == before
    assert rt.accounting.applied_fill_ids == ()
    assert rt.accounting.lots == ()
    assert RuntimeEventKind.ACCOUNTING_APPLIED not in [e.kind for e in rt.trace_events]


def test_future_accounting_timestamp_is_rejected_before_order_mutation() -> None:
    rt = runtime()
    assert rt.accounting is not None
    from tests.execution_fixtures import candle

    rt.accounting.update_portfolio((candle(0),), timestamp(1))
    before = rt.broker.execution_fingerprint, rt.accounting.accounting_fingerprint
    from command_station.accounting import AccountingInvariantError

    with pytest.raises(AccountingInvariantError):
        rt.activate_order(request(), max_quote_reservation=Decimal(10))
    assert (rt.broker.execution_fingerprint, rt.accounting.accounting_fingerprint) == before
