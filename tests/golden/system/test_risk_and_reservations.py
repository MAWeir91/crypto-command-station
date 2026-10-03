from decimal import Decimal
from pathlib import Path

from command_station.accounting import USD
from command_station.domain import Candle, Side
from command_station.execution import BaseQuantity
from command_station.risk import RiskPolicy
from command_station.strategy import StrategyContext
from tests.execution_fixtures import candle, timestamp
from tests.research_fixtures import BTC, NoTrade, setup
from tests.system_fixtures import rows, scenario


class CancelRestore(NoTrade):
    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        minute = ctx.clock.now.value.minute
        if minute in (1, 3):
            assert ctx.account.balance(USD).available == 1000
            assert ctx.positions[0].actual_quantity == 0
            ctx.orders.limit(BTC, Side.BUY, BaseQuantity("1"), "90")
        if minute == 2:
            assert ctx.account.balance(USD).reserved == Decimal("90.9")
            ctx.orders.cancel(ctx.orders.orders[0].order_id)


def test_cancel_restores_risk_headroom_and_cannot_fill_later(tmp_path: Path) -> None:
    service, spec = scenario(
        tmp_path,
        CancelRestore,
        (candle(0), candle(1), candle(2), candle(3, low="80")),
        policy=RiskPolicy(max_product_exposure=Decimal("91")),
    )
    result = service.run(spec)
    orders = rows(service, result, "orders.parquet")
    assert [o["status"] for o in orders] == ["CANCELLED", "FILLED"]
    fills = rows(service, result, "fills.parquet")
    assert len(fills) == 1 and fills[0]["order_id"] == "2"
    assert fills[0]["market_interval_open"] == str(timestamp(3))
    decisions = rows(service, result, "risk_decisions.parquet")
    assert [d["baseline_product_exposure"] for d in decisions] == ["0", "0"]
    assert result.risk_summary.approve_count == 2
    assert result.final_reservations[0].remaining_amount == 0


class LargeLimit(NoTrade):
    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        if ctx.clock.now == timestamp(1):
            ctx.orders.limit(BTC, Side.BUY, BaseQuantity("2"), "100")
        elif ctx.clock.now == timestamp(2):
            assert ctx.positions[0].actual_quantity == Decimal("0.5")


def test_modified_quantity_is_the_only_broker_and_accounting_quantity(tmp_path: Path) -> None:
    service, spec = setup(
        tmp_path,
        LargeLimit,
        policy=RiskPolicy(max_order_notional=Decimal("50.5"), allow_quantity_reduction=True),
    )
    result = service.run(spec)
    decision = rows(service, result, "risk_decisions.parquet")[0]
    assert decision["status"] == "APPROVE_WITH_MODIFICATION"
    assert decision["requested_base_quantity"] == "2"
    assert decision["approved_base_quantity"] == "0.5"
    assert decision["requested_quote_commitment"] == "202"
    assert decision["approved_quote_commitment"] == "50.5"
    order = rows(service, result, "orders.parquet")[0]
    assert order["activated_base_quantity"] == "0.5"
    assert rows(service, result, "fills.parquet")[0]["base_quantity"] == "0.5"
    assert result.final_reservations[0].original_amount == Decimal("50.5")
    assert result.final_account.balance(USD).total == Decimal("949.5")
    assert result.risk_summary.modified_count == 1


class RejectContinue(NoTrade):
    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        if ctx.clock.now == timestamp(1):
            ctx.orders.limit(BTC, Side.BUY, BaseQuantity("2"), "100")
        elif ctx.clock.now == timestamp(2):
            assert not ctx.orders.orders
            assert ctx.account.balance(USD).total == ctx.account.balance(USD).available == 1000
            assert ctx.positions[0].actual_quantity == 0
            assert ctx.orders.results[0].status.value == "REJECTED"
            ctx.orders.limit(BTC, Side.BUY, BaseQuantity("0.5"), "100")


def test_rejection_has_no_financial_effect_and_run_continues(tmp_path: Path) -> None:
    service, spec = setup(
        tmp_path, RejectContinue, policy=RiskPolicy(max_order_notional=Decimal("60"))
    )
    result = service.run(spec)
    assert result.risk_summary.decision_count == 2
    assert result.risk_summary.reject_count == result.risk_summary.approve_count == 1
    assert result.risk_summary.reason_counts == (
        ("MAX_ORDER_NOTIONAL", 1),
        ("MODIFICATION_NOT_ALLOWED", 1),
    )
    assert len(result.final_reservations) == 1
    assert result.execution_summary.order_count == result.execution_summary.fill_count == 1
    assert result.final_account.balance(USD).total == Decimal("949.5")
    assert rows(service, result, "fills.parquet")[0]["activated_at"] == str(timestamp(2))
