import json
import tempfile
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from command_station.accounting import USD, SpotAccountingEngine, replay_ledger
from command_station.domain import Candle, Side, UtcTimestamp
from command_station.execution import BaseQuantity, CancellationReason, Fill, Order, SimulatedBroker
from command_station.risk import RiskPolicy
from command_station.strategy import IntParam, StrategyContext
from tests.accounting_fixtures import account, fill_fact, request, reserve
from tests.execution_fixtures import candle, timestamp
from tests.research_fixtures import BTC, NoTrade
from tests.system_fixtures import rows, scenario


@given(quantity=st.integers(1, 8), cap=st.integers(1, 500), exit_price=st.integers(80, 130))
@settings(max_examples=12, deadline=None)
def test_generated_service_financial_risk_and_trade_reconciliation(
    quantity: int, cap: int, exit_price: int
) -> None:
    original = SpotAccountingEngine.apply_fill_batch
    boundaries: list[UtcTimestamp] = []

    def observed(
        engine: SpotAccountingEngine,
        fills: tuple[Fill, ...],
        orders: tuple[Order, ...],
        now: UtcTimestamp,
    ) -> None:
        original(engine, fills, orders, now)
        boundaries.append(now)
        assert engine.account_view == replay_ledger(
            engine.ledger, tuple(b.asset for b in engine.account_view.balances)
        )
        open_quantity = sum(
            (Fraction(lot.original_quantity) for lot in engine.lots), Fraction(0)
        ) - sum((Fraction(c.quantity) for c in engine.lot_consumptions), Fraction(0))
        assert open_quantity == Fraction(engine.positions[0].actual_quantity)
        assert open_quantity == Fraction(
            engine.account_view.balance(engine.positions[0].base_asset).total
        )
        assert Fraction(engine.fees_to_date) == sum(
            (Fraction(f.fee_amount) for f in engine.applied_fills), Fraction(0)
        )
        assert Fraction(engine.positions[0].gross_realized_pnl) == sum(
            (Fraction(c.gross_realized_pnl) for c in engine.lot_consumptions), Fraction(0)
        )
        for balance in engine.account_view.balances:
            assert 0 <= balance.reserved <= balance.total

    class Generated(NoTrade):
        definition = replace(NoTrade.definition, parameters=(IntParam("quantity", quantity),))

        def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
            for balance in ctx.account.balances:
                assert 0 <= balance.reserved <= balance.total
                assert Fraction(balance.available) == Fraction(balance.total) - Fraction(
                    balance.reserved
                )
            assert ctx.positions[0].actual_quantity >= 0
            if ctx.clock.now == timestamp(1):
                requested = ctx.parameters.get("quantity")
                assert isinstance(requested, int)
                ctx.orders.limit(BTC, Side.BUY, BaseQuantity(str(requested)), "100")
            if ctx.clock.now == timestamp(2) and ctx.positions[0].actual_quantity > 0:
                ctx.orders.market(BTC, Side.SELL, BaseQuantity(ctx.positions[0].tradable_quantity))

    with tempfile.TemporaryDirectory() as directory:
        service, spec = scenario(
            Path(directory),
            Generated,
            (
                candle(0),
                candle(1),
                candle(2, open=str(exit_price), high="140", low="70", close=str(exit_price)),
                candle(3),
            ),
            policy=RiskPolicy(max_order_notional=Decimal(cap), allow_quantity_reduction=True),
        )
        with patch.object(SpotAccountingEngine, "apply_fill_batch", observed):
            result = service.run(spec)
        assert boundaries and boundaries[-1] == spec.period.replay_end
        fills = rows(service, result, "fills.parquet")
        decisions = rows(service, result, "risk_decisions.parquet")
        orders = rows(service, result, "orders.parquet")
        trades = rows(service, result, "trades.parquet")
        assert len(orders) == len(fills) == 2 * int(bool(trades))
        assert len(decisions) == 1 + int(bool(trades))
        assert all(
            Decimal(d["approved_base_quantity"]) <= Decimal(d["requested_base_quantity"])
            for d in decisions
            if d["approved_base_quantity"] is not None
        )
        assert all(
            Decimal(d["approved_quote_commitment"]) <= Decimal(d["requested_quote_commitment"])
            for d in decisions
            if d["approved_quote_commitment"] is not None
        )
        cash = Fraction(1000)
        fees = Fraction(0)
        for fill in fills:
            gross = Fraction(Decimal(fill["base_quantity"])) * Fraction(Decimal(fill["fill_price"]))
            fee = Fraction(Decimal(fill["fee_amount"]))
            fees += fee
            cash += gross * (-1 if fill["side"] == "BUY" else 1) - fee
            assert fill["activated_at"] <= fill["market_interval_open"]
        assert Fraction(result.final_account.balance(USD).total) == cash
        assert Fraction(result.metrics.total_fees) == fees
        assert result.final_positions[0].actual_quantity == 0
        assert all(r.remaining_amount == 0 for r in result.final_reservations)
        assert Fraction(result.final_portfolio.total_equity) == cash
        assert result.metrics.closed_trade_count == len(trades)
        assert sum((Fraction(Decimal(t["gross_pnl"])) for t in trades), Fraction(0)) == Fraction(
            result.metrics.gross_closed_trade_pnl
        )
        for point in rows(service, result, "equity.parquet"):
            assert Decimal(point["cash_total"]) >= Decimal(point["cash_reserved"]) >= 0
            assert Fraction(Decimal(point["total_equity"])) == Fraction(
                Decimal(point["cash_total"])
            ) + Fraction(Decimal(point["marked_asset_value"]))
        encoded = json.dumps(result.to_dict(), allow_nan=False)
        assert "NaN" not in encoded and "Infinity" not in encoded


@given(units=st.integers(1, 9), cancel=st.booleans())
@settings(max_examples=12, deadline=None)
def test_partial_fill_lifecycle_exact_replay_and_unused_reservation(
    units: int, cancel: bool
) -> None:
    engine = account()
    broker = SimulatedBroker(engine.execution_spec)
    order = reserve(engine, broker, request(), Decimal("202"))
    quantity = Decimal(f"0.{units}")
    fill = fill_fact(order, engine.execution_spec, quantity=str(quantity))
    partial = order.apply_fill(quantity)
    engine.apply_fill_batch((fill,), (partial,), timestamp(1))
    assert engine.positions[0].actual_quantity == quantity
    assert engine.reservations[0].remaining_amount == Decimal("202") - Decimal("101") * quantity
    assert engine.account_view == replay_ledger(
        engine.ledger, tuple(b.asset for b in engine.account_view.balances)
    )
    assert sum((lot.original_quantity for lot in engine.lots), Decimal(0)) == quantity
    if cancel:
        totals = tuple((b.asset, b.total) for b in engine.account_view.balances)
        cancelled = partial.cancel(timestamp(1), CancellationReason.USER_REQUEST)
        engine.apply_fill_batch((), (cancelled,), timestamp(1))
        assert tuple((b.asset, b.total) for b in engine.account_view.balances) == totals
        assert engine.positions[0].actual_quantity == quantity
    else:
        remaining = Decimal(1) - quantity
        final = fill_fact(
            order, engine.execution_spec, quantity=str(remaining), fill_id=2, minute=1
        )
        engine.apply_fill_batch((final,), (partial.apply_fill(remaining),), timestamp(2))
        assert engine.positions[0].actual_quantity == 1
    assert engine.reservations[0].remaining_amount == 0
    assert engine.account_view == replay_ledger(
        engine.ledger, tuple(b.asset for b in engine.account_view.balances)
    )
