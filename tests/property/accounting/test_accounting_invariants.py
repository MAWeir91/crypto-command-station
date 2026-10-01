from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from command_station.accounting import USD, AccountingInvariantError, replay_ledger
from command_station.domain import AssetSymbol, Side
from command_station.execution import SimulatedBroker
from tests.accounting_fixtures import account, request, reserve
from tests.execution_fixtures import candle, timestamp


@given(
    st.lists(st.tuples(st.integers(1, 5000), st.integers(1, 500)), min_size=1, max_size=5),
    st.integers(1, 999),
    st.integers(1, 9),
)
@settings(max_examples=30, deadline=None)
def test_generated_buy_fifo_exit_cancel_replay_and_context_identity(
    purchases: list[tuple[int, int]], exit_fraction: int, precision: int
) -> None:
    def execute() -> tuple[object, ...]:
        engine = account(cash="1000000000", fee_bps=17)
        broker = SimulatedBroker(engine.execution_spec)
        BTC = AssetSymbol("BTC")
        total_quantity = Fraction(0)
        expected_cash = Fraction(1000000000)
        expected_fees = Fraction(0)
        for minute, (units, price) in enumerate(purchases):
            quantity = Decimal((0, Decimal(units).as_tuple().digits, -3))
            before = (
                tuple((b.asset, b.total) for b in engine.account_view.balances),
                engine.positions,
            )
            reserve(
                engine, broker, request(quantity=str(quantity), minute=minute), Decimal(1000000)
            )
            assert (
                tuple((b.asset, b.total) for b in engine.account_view.balances),
                engine.positions,
            ) == before
            interval = candle(
                minute, open=str(price), high=str(price), low=str(price), close=str(price)
            )
            fills = broker.process_market_activity((interval,), timestamp(minute + 1))
            engine.apply_fill_batch(fills, broker.orders, timestamp(minute + 1))
            gross = Fraction(quantity) * price
            fees = gross * Fraction(17, 10000)
            total_quantity += Fraction(quantity)
            expected_cash -= gross + fees
            expected_fees += fees
            assert Fraction(engine.account_view.balance(USD).total) == expected_cash
            assert Fraction(engine.account_view.balance(BTC).total) == total_quantity
            assert Fraction(engine.fees_to_date) == expected_fees
            assert engine.account_view == replay_ledger(engine.ledger, (USD, BTC))
        minute = len(purchases)
        # Cancel an untouched SELL, proving reservation-only lifecycle conservation.
        before_account, before_positions = engine.account_view, engine.positions
        cancelled = reserve(
            engine,
            broker,
            request(Side.SELL, quantity=str(engine.positions[0].tradable_quantity), minute=minute),
        )
        broker.cancel(cancelled.order_id, timestamp(minute))
        engine.apply_fill_batch((), broker.orders, timestamp(minute))
        assert engine.account_view == before_account and engine.positions == before_positions
        # Exit a generated, increment-aligned fraction of total inventory.
        units_to_sell = max(1, int(total_quantity * 1000 * Fraction(exit_fraction, 1000)))
        sell_quantity = Decimal((0, Decimal(units_to_sell).as_tuple().digits, -3))
        reserve(engine, broker, request(Side.SELL, quantity=str(sell_quantity), minute=minute))
        interval = candle(minute, open="300", high="300", low="300", close="300")
        fills = broker.process_market_activity((interval,), timestamp(minute + 1))
        engine.apply_fill_batch(fills, broker.orders, timestamp(minute + 1))
        expected_cash += Fraction(sell_quantity) * 300 * Fraction(9983, 10000)
        expected_fees += Fraction(sell_quantity) * 300 * Fraction(17, 10000)
        total_quantity -= Fraction(sell_quantity)
        assert Fraction(engine.account_view.balance(USD).total) == expected_cash
        assert Fraction(engine.account_view.balance(BTC).total) == total_quantity
        assert Fraction(engine.fees_to_date) == expected_fees
        assert sum(
            (Fraction(c.quantity) for c in engine.lot_consumptions), Fraction(0)
        ) == Fraction(sell_quantity)
        open_total = Fraction(0)
        for lot in engine.lots:
            used = sum(
                (Fraction(c.quantity) for c in engine.lot_consumptions if c.lot_id == lot.lot_id),
                Fraction(0),
            )
            assert 0 <= used <= Fraction(lot.original_quantity)
            open_total += Fraction(lot.original_quantity) - used
        assert open_total == total_quantity == Fraction(engine.positions[0].actual_quantity)
        snapshot = engine.update_portfolio((interval,), timestamp(minute + 1))
        assert Fraction(snapshot.total_equity) == expected_cash + total_quantity * 300
        for balance in engine.account_view.balances:
            assert balance.total >= balance.reserved >= 0
            assert Fraction(balance.available) == Fraction(balance.total) - Fraction(
                balance.reserved
            )
        before_fingerprint = engine.accounting_fingerprint
        with pytest.raises(AccountingInvariantError):
            engine.apply_fill_batch(fills, broker.orders, timestamp(minute + 1))
        assert engine.accounting_fingerprint == before_fingerprint
        return (
            engine.ledger,
            engine.account_view,
            engine.lots,
            engine.lot_consumptions,
            engine.positions,
            engine.portfolio_history,
            engine.accounting_fingerprint,
        )

    expected = execute()
    assert execute() == expected
    with localcontext() as context:
        context.prec = precision
        context.clear_flags()
        assert execute() == expected
        assert not any(context.flags.values())
