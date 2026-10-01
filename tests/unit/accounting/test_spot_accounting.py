from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, getcontext, localcontext

import pytest

from command_station.accounting import (
    USD,
    AccountBalance,
    AccountingInvariantError,
    AccountingValidationError,
    InitialHolding,
    InsufficientAvailableBalanceError,
    LedgerCategory,
    ReservationStatus,
    SpotAccountingEngine,
    SpotAccountSpec,
    replay_ledger,
)
from command_station.domain import AssetSymbol, ProductId, Side, Timeframe
from command_station.execution import (
    CancellationReason,
    OrderType,
    ReferenceExecutionSpec,
    SimulatedBroker,
)
from tests.accounting_fixtures import account, fill_fact, request, reserve
from tests.execution_fixtures import candle, product, timestamp

BTC = AssetSymbol("BTC")


def test_initial_deposits_immutable_views_ids_and_replay() -> None:
    engine = account(holding="2", cost="70")
    assert [t.transaction_id.value for t in engine.ledger] == [1, 2]
    assert all(t.category is LedgerCategory.INITIAL_DEPOSIT for t in engine.ledger)
    assert engine.account_view == replay_ledger(engine.ledger, (USD, BTC))
    assert engine.positions[0].total_cost_basis == 140
    assert engine.positions[0].gross_realized_pnl == 0
    assert engine.lots[0].original_quantity == 2
    with pytest.raises(FrozenInstanceError):
        engine.account_view.balances[0].total = Decimal(999)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        engine.ledger[0].postings = ()  # type: ignore[misc]
    assert engine.accounting_fingerprint == account(holding="2", cost="70").accounting_fingerprint


@pytest.mark.parametrize("cash", [True, 1.2, "-1", "NaN", "Infinity"])
def test_invalid_exact_funding(cash: object) -> None:
    with pytest.raises(ValueError):
        SpotAccountSpec(initial_cash=cash, product_specs=(product(),))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "products",
    [(product(), product()), (product("BTC-EUR"),)],
)
def test_account_product_mapping_validation(products: tuple[object, ...]) -> None:
    with pytest.raises(AccountingValidationError):
        SpotAccountSpec(initial_cash="1", product_specs=products)  # type: ignore[arg-type]


def test_duplicate_base_and_unknown_duplicate_holdings_rejected() -> None:
    alias = replace(product("ETH-USD"), base_currency=BTC)
    with pytest.raises(AccountingValidationError):
        SpotAccountSpec(initial_cash="1", product_specs=(product(), alias))
    holding = InitialHolding(ProductId("BTC-USD"), "1", "0")
    for holdings in ((holding, holding), (InitialHolding(ProductId("ETH-USD"), "1", "1"),)):
        with pytest.raises(AccountingValidationError):
            SpotAccountSpec(initial_cash="1", product_specs=(product(),), initial_holdings=holdings)
    with pytest.raises(TypeError):
        InitialHolding(ProductId("BTC-USD"), "1")  # type: ignore[call-arg]


@pytest.mark.parametrize("total,reserved", [("-1", "0"), ("0", "1"), ("1", "-1")])
def test_invalid_balance_invariants(total: str, reserved: str) -> None:
    with pytest.raises(AccountingInvariantError):
        AccountBalance(USD, Decimal(total), Decimal(reserved))


def test_buy_limit_exact_reservation_overlap_and_cancellation() -> None:
    engine = account(cash="202")
    broker = SimulatedBroker(engine.execution_spec)
    before = engine.positions, engine.lots
    order = reserve(engine, broker, request(kind=OrderType.LIMIT), None)
    assert engine.account_view.balance(USD).total == 202
    assert engine.account_view.balance(USD).reserved == 101
    assert (engine.positions, engine.lots) == before
    reserve(engine, broker, request(kind=OrderType.LIMIT), None)
    assert engine.account_view.balance(USD).available == 0
    fingerprint = engine.accounting_fingerprint
    with pytest.raises(InsufficientAvailableBalanceError):
        engine.prepare_reservation((request(kind=OrderType.LIMIT),))
    assert engine.accounting_fingerprint == fingerprint
    broker.cancel(order.order_id, timestamp())
    engine.apply_fill_batch((), broker.orders, timestamp())
    assert engine.account_view.balance(USD).reserved == 101
    assert engine.reservations[0].status is ReservationStatus.RELEASED
    assert (engine.positions, engine.lots) == before


@pytest.mark.parametrize("kind", [OrderType.MARKET, OrderType.STOP_MARKET])
def test_buy_gap_types_need_positive_explicit_cap(kind: OrderType) -> None:
    engine = account()
    req = request(kind=kind)
    for cap in (None, Decimal(0), Decimal("-1")):
        with pytest.raises(ValueError):
            engine.prepare_reservation((req,), max_quote_reservation=cap)
    assert engine.prepare_reservation((req,), max_quote_reservation=Decimal("102")).amount == 102


def test_reject_unnecessary_caps_and_product_drift() -> None:
    engine = account(holding="1")
    for req in (request(Side.SELL), request(kind=OrderType.LIMIT)):
        with pytest.raises(AccountingValidationError):
            engine.prepare_reservation((req,), max_quote_reservation=Decimal(100))
    drifted = replace(product(), price_increment=Decimal("0.02"))
    from command_station.execution import normalize_order_intent

    req = normalize_order_intent(request().source_intent, drifted)
    with pytest.raises(AccountingValidationError):
        engine.prepare_reservation((req,), max_quote_reservation=Decimal(100))
    with pytest.raises(InsufficientAvailableBalanceError):
        engine.prepare_reservation((request(Side.SELL, quantity="2"),))


def test_favorable_limit_full_fill_releases_excess_and_fee_separate() -> None:
    engine = account()
    broker = SimulatedBroker(engine.execution_spec)
    reserve(engine, broker, request(kind=OrderType.LIMIT, price="110"))
    fills = broker.process_market_activity((candle(0),), timestamp(1))
    transactions = engine.apply_fill_batch(fills, broker.orders, timestamp(1))
    assert engine.account_view.balance(USD).total == 9899
    assert engine.account_view.balance(USD).reserved == 0
    assert engine.account_view.balance(BTC).total == 1
    assert engine.lots[0].unit_cost == 100
    assert engine.fees_to_date == 1
    assert [t.category for t in transactions] == [
        LedgerCategory.TRADE_FILL,
        LedgerCategory.TRADING_FEE,
        LedgerCategory.ORDER_RESERVATION_RELEASE,
    ]
    assert engine.reservations[0].status is ReservationStatus.RELEASED


def test_fifo_partial_exit_preserves_original_lots_gross_pnl_and_fees() -> None:
    engine = account(holding="2", cost="80")
    broker = SimulatedBroker(engine.execution_spec)
    buy = reserve(engine, broker, request(quantity="1"), Decimal(101))
    buy_fill = fill_fact(buy, engine.execution_spec)
    engine.apply_fill_batch((buy_fill,), (buy.apply_fill("1"),), timestamp(1))
    # New broker OrderId=2, bind the second acquisition-era order.
    sell = reserve(engine, broker, request(Side.SELL, quantity="3", minute=1))
    original_lots = engine.lots
    first = fill_fact(sell, engine.execution_spec, quantity="2.5", price="120", fill_id=2, minute=1)
    partial = sell.apply_fill("2.5")
    engine.apply_fill_batch((first,), (buy.apply_fill("1"), partial), timestamp(2))
    assert engine.lots == original_lots
    assert [c.quantity for c in engine.lot_consumptions] == [Decimal(2), Decimal("0.5")]
    assert engine.positions[0].actual_quantity == Decimal("0.5")
    assert engine.positions[0].total_cost_basis == 50
    assert engine.positions[0].gross_realized_pnl == 90
    assert engine.account_view.balance(BTC).reserved == Decimal("0.5")
    assert engine.fees_to_date == 4
    second = fill_fact(
        sell, engine.execution_spec, quantity="0.5", price="120", fill_id=3, minute=2
    )
    engine.apply_fill_batch(
        (second,), (buy.apply_fill("1"), partial.apply_fill("0.5")), timestamp(3)
    )
    flat = engine.positions[0]
    assert flat.actual_quantity == flat.total_cost_basis == 0
    assert flat.average_cost_display is None
    assert flat.gross_realized_pnl == 100
    assert engine.fees_to_date == Decimal("4.6")


def test_buy_partial_fill_keeps_unused_reservation_and_only_filled_lot() -> None:
    engine = account()
    broker = SimulatedBroker(engine.execution_spec)
    order = reserve(engine, broker, request(quantity="2"), Decimal(202))
    fill = fill_fact(order, engine.execution_spec, quantity="0.5")
    partial = order.apply_fill("0.5")
    engine.apply_fill_batch((fill,), (partial,), timestamp(1))
    assert engine.account_view.balance(USD).reserved == Decimal("151.5")
    assert engine.account_view.balance(BTC).total == Decimal("0.5")
    assert engine.lots[0].original_quantity == Decimal("0.5")
    cancelled = partial.cancel(timestamp(1), CancellationReason.USER_REQUEST)
    engine.apply_fill_batch((), (cancelled,), timestamp(1))
    assert engine.account_view.balance(USD).reserved == 0


def test_duplicate_fill_and_bad_batch_have_no_financial_mutation() -> None:
    engine = account()
    broker = SimulatedBroker(engine.execution_spec)
    reserve(engine, broker, request(), Decimal(101))
    reserve(engine, broker, request(), Decimal(101))
    fills = broker.process_market_activity((candle(0),), timestamp(1))
    before = engine.accounting_fingerprint
    bad = replace(fills[1], fee_asset=BTC)
    with pytest.raises(AccountingInvariantError):
        engine.apply_fill_batch((fills[0], bad), broker.orders, timestamp(1))
    assert engine.accounting_fingerprint == before
    assert engine.applied_fill_ids == ()
    engine.apply_fill_batch(fills, broker.orders, timestamp(1))
    before = engine.accounting_fingerprint
    with pytest.raises(AccountingInvariantError):
        engine.apply_fill_batch((fills[0],), broker.orders, timestamp(1))
    assert engine.accounting_fingerprint == before


@pytest.mark.parametrize(
    "defect", ["cap", "unknown", "quantity", "fee", "product", "time", "duplicate"]
)
def test_invalid_fill_rejected_atomically(defect: str) -> None:
    engine = account()
    broker = SimulatedBroker(engine.execution_spec)
    order = reserve(engine, broker, request(), Decimal(100 if defect == "cap" else 101))
    fill = broker.process_market_activity((candle(0),), timestamp(1))[0]
    if defect == "unknown":
        from command_station.execution import OrderId

        fill = replace(fill, order_id=OrderId(999))
    elif defect == "quantity":
        fill = replace(fill, base_quantity=Decimal("2"))
    elif defect == "fee":
        fill = replace(fill, fee_amount=Decimal(2))
    elif defect == "product":
        fill = replace(fill, product_spec_fingerprint="a" * 64)
    elif defect == "time":
        fill = replace(fill, market_interval_open=timestamp(-1))
    facts = (fill, fill) if defect == "duplicate" else (fill,)
    before = engine.accounting_fingerprint
    with pytest.raises(AccountingInvariantError):
        engine.apply_fill_batch(facts, broker.orders, timestamp(1))
    assert engine.accounting_fingerprint == before
    assert engine.account_view.balance(USD).total == 10000
    assert order.order_id == broker.orders[0].order_id


def test_fill_without_reservation_rejected() -> None:
    engine = account()
    broker = SimulatedBroker(engine.execution_spec)
    broker.activate(request(), timestamp())
    fills = broker.process_market_activity((candle(0),), timestamp(1))
    before = engine.accounting_fingerprint
    with pytest.raises(AccountingInvariantError):
        engine.apply_fill_batch(fills, broker.orders, timestamp(1))
    assert engine.accounting_fingerprint == before


def test_dust_nonterminating_average_display_and_current_mark() -> None:
    engine = account(holding="0.0005", cost="80")
    position = engine.positions[0]
    assert position.actual_quantity == position.dust_quantity == Decimal("0.0005")
    assert position.tradable_quantity == 0
    snapshot = engine.update_portfolio((candle(0),), timestamp(1))
    assert snapshot.marked_asset_value == Decimal("0.05")
    assert snapshot.gross_unrealized_pnl == Decimal("0.01")
    assert snapshot.total_equity == Decimal("10000.05")
    from command_station.accounting import AccountView, AcquisitionLot, LotId, LotSource
    from command_station.accounting.positions import position_views

    lots = (
        AcquisitionLot(
            LotId(1),
            ProductId("BTC-USD"),
            BTC,
            Decimal(1),
            Decimal(1),
            timestamp(),
            LotSource.INITIAL_HOLDING,
        ),
        AcquisitionLot(
            LotId(2),
            ProductId("BTC-USD"),
            BTC,
            Decimal(2),
            Decimal(2),
            timestamp(),
            LotSource.INITIAL_HOLDING,
        ),
    )
    assert position_views(
        (product(),), AccountView((AccountBalance(BTC, Decimal(3), Decimal(0)),)), lots, ()
    )[0].average_cost_display == Decimal("1.66666667")


def test_portfolio_cash_only_reservations_equity_and_missing_derived_marks() -> None:
    engine = account()
    broker = SimulatedBroker(engine.execution_spec)
    reserve(engine, broker, request(kind=OrderType.LIMIT))
    snapshot = engine.update_portfolio((candle(0),), timestamp(1))
    assert snapshot.cash_reserved == 101
    assert snapshot.total_equity == snapshot.cash_total == 10000
    assert (
        snapshot.gross_realized_pnl == snapshot.gross_unrealized_pnl == snapshot.fees_to_date == 0
    )
    owned = account(holding="1")
    before = owned.accounting_fingerprint
    with pytest.raises(AccountingInvariantError):
        owned.update_portfolio((), timestamp(1))
    assert owned.accounting_fingerprint == before
    derived = replace(candle(0), timeframe=Timeframe.FIVE_MINUTES, close_time=timestamp(5))
    with pytest.raises(AccountingInvariantError):
        owned.update_portfolio((derived,), timestamp(5))
    assert owned.accounting_fingerprint == before


def test_low_precision_all_financial_state_and_context_unchanged() -> None:
    def run() -> tuple[object, ...]:
        engine = account(cash="10000.123456789", holding="2.3456789", cost="80.123456789")
        broker = SimulatedBroker(engine.execution_spec)
        reserve(engine, broker, request(Side.SELL, quantity="1.234"))
        fills = broker.process_market_activity(
            (candle(0, open="100.123456789", high="101", low="99", close="100.123456789"),),
            timestamp(1),
        )
        engine.apply_fill_batch(fills, broker.orders, timestamp(1))
        engine.update_portfolio(
            (candle(0, open="100.123456789", high="101", low="99", close="100.123456789"),),
            timestamp(1),
        )
        return (
            engine.account_view,
            engine.positions,
            engine.ledger,
            engine.portfolio_history,
            engine.accounting_fingerprint,
        )

    expected = run()
    with localcontext() as context:
        context.prec = 2
        context.clear_flags()
        assert run() == expected
        assert getcontext().prec == 2
        assert not any(context.flags.values())


def test_fees_at_or_above_proceeds_are_unsupported() -> None:
    with pytest.raises(AccountingValidationError):
        SpotAccountingEngine(
            SpotAccountSpec(initial_cash="1", product_specs=(product(),)),
            timestamp(),
            ReferenceExecutionSpec(fee_bps=10000),
        )
