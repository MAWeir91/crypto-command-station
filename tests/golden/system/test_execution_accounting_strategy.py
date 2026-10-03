from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from command_station.accounting import USD, InitialHolding
from command_station.domain import Candle, Side, Timeframe
from command_station.execution import BaseQuantity, Fill, ReferenceExecutionSpec
from command_station.strategy import (
    BarSubscription,
    IndicatorKind,
    IndicatorSpec,
    StateField,
    StateType,
    StrategyContext,
    StrategyDefinition,
)
from tests.execution_fixtures import candle, timestamp
from tests.research_fixtures import BTC, BuyHold, NoTrade
from tests.system_fixtures import rows, scenario


def test_market_next_open_artifact_and_accounting(tmp_path: Path) -> None:
    bars = (candle(0),) + tuple(
        candle(i, open="120", high="125", low="115", close="121") for i in range(1, 4)
    )
    service, spec = scenario(tmp_path, BuyHold, bars)
    result = service.run(spec)
    order = rows(service, result, "orders.parquet")[0]
    fill = rows(service, result, "fills.parquet")[0]
    assert order["created_at"] == order["activated_at"] == str(timestamp(1))
    assert fill["market_interval_open"] == str(timestamp(1))
    assert fill["market_interval_close"] == str(timestamp(2))
    assert fill["reference_price"] == fill["fill_price"] == "120"
    assert fill["resolution"] == "EXACT_NEXT_OPEN"
    equity = rows(service, result, "equity.parquet")
    assert equity[0]["cash_total"] == "1000" and equity[0]["fees_to_date"] == "0"
    assert equity[1]["cash_total"] == "878.8" and equity[1]["fees_to_date"] == "1.2"
    assert result.final_account.balance(USD).total == Decimal("878.8")
    assert result.final_positions[0].actual_quantity == 1


class SignalLimit(NoTrade):
    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        if ctx.clock.now == timestamp(1):
            ctx.orders.limit(BTC, Side.BUY, BaseQuantity("1"), "90")


def test_signal_bar_limit_is_future_only(tmp_path: Path) -> None:
    bars = (
        candle(0, low="80"),
        candle(1),
        candle(2, low="85"),
        candle(3),
    )
    service, spec = scenario(tmp_path, SignalLimit, bars)
    result = service.run(spec)
    fills = rows(service, result, "fills.parquet")
    assert len(fills) == 1
    assert fills[0]["activated_at"] == str(timestamp(1))
    assert fills[0]["market_interval_open"] == str(timestamp(2))
    assert fills[0]["reference_price"] == "90"
    assert rows(service, result, "strategy_actions.parquet")[0]["timestamp"] == str(timestamp(1))
    assert rows(service, result, "equity.parquet")[1]["cash_total"] == "1000"
    assert result.final_account.balance(USD).total == Decimal("909.1")


class Stop(NoTrade):
    definition = replace(
        NoTrade.definition, state_schema=(StateField("filled", StateType.BOOL, False),)
    )

    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        if ctx.clock.now == timestamp(1):
            ctx.orders.stop_market(BTC, Side.SELL, BaseQuantity("1"), "90")
        if ctx.clock.now == timestamp(2):
            assert ctx.state.get("filled") is True
            assert ctx.positions[0].actual_quantity == 0
            assert ctx.account.balance(USD).total == Decimal("1083.3085")
            assert ctx.portfolio is not None and ctx.portfolio.total_equity == Decimal("1083.3085")

    def on_fill(self, ctx: StrategyContext, fill: Fill) -> None:
        assert ctx.positions[0].actual_quantity == 0
        ctx.state.set("filled", True)


def test_stop_gap_and_fill_accounting_before_same_time_decision(tmp_path: Path) -> None:
    bars = (candle(0),) + tuple(
        candle(i, open="85", high="88", low="80", close="85") for i in range(1, 4)
    )
    service, spec = scenario(tmp_path, Stop, bars)
    spec = replace(
        spec,
        account=replace(spec.account, initial_holdings=(InitialHolding(BTC, "1", "100"),)),
        execution=ReferenceExecutionSpec(slippage_bps=100, fee_bps=100),
    )
    result = service.run(spec)
    fill = rows(service, result, "fills.parquet")[0]
    assert fill["gap"] == "true" and fill["resolution"] == "GAP"
    assert fill["reference_price"] == "85" and fill["fill_price"] == "84.15"
    assert fill["fee_amount"] == "0.8415" and fill["slippage_per_base"] == "0.85"
    assert result.execution_summary.total_slippage_cost == Decimal("0.85")
    assert result.metrics.gross_closed_trade_pnl == Decimal("-15.85")
    assert result.final_positions[0].actual_quantity == 0


class Oco(NoTrade):
    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        if ctx.clock.now == timestamp(1):
            ctx.orders.oco_limit_stop(BTC, Side.SELL, BaseQuantity("1"), "110", "90")


def test_oco_ambiguity_one_settlement(tmp_path: Path) -> None:
    bars = tuple(candle(i, high="120", low="80") for i in range(4))
    service, spec = scenario(tmp_path, Oco, bars)
    spec = replace(
        spec, account=replace(spec.account, initial_holdings=(InitialHolding(BTC, "1", "100"),))
    )
    result = service.run(spec)
    fills = rows(service, result, "fills.parquet")
    assert len(fills) == 1 and fills[0]["fill_price"] == "90"
    assert fills[0]["ambiguity"] == "true"
    assert fills[0]["resolution"] == "AMBIGUOUS_CONSERVATIVE"
    assert [o["status"] for o in rows(service, result, "orders.parquet")] == ["CANCELLED", "FILLED"]
    assert len(result.final_reservations) == 1
    assert result.final_reservations[0].original_amount == 1
    assert result.final_reservations[0].remaining_amount == 0
    assert result.final_account.balance(USD).total == Decimal("1089.1")
    assert result.final_positions[0].actual_quantity == 0
    assert result.risk_summary.approve_count == 1
    assert len(rows(service, result, "trades.parquet")) == 1


class AtomicFrames(NoTrade):
    definition = StrategyDefinition(
        "research",
        (
            BarSubscription(BTC, Timeframe.ONE_MINUTE),
            BarSubscription(BTC, Timeframe.FIVE_MINUTES, True),
            BarSubscription(BTC, Timeframe.FIFTEEN_MINUTES),
        ),
        indicators=(
            IndicatorSpec("primary", BTC, Timeframe.FIVE_MINUTES, IndicatorKind.SMA, 1),
            IndicatorSpec("support", BTC, Timeframe.FIFTEEN_MINUTES, IndicatorKind.SMA, 1),
        ),
    )

    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        assert bar.timeframe is Timeframe.FIVE_MINUTES
        assert bar.close_time == ctx.clock.now
        assert ctx.indicators.updated_at("primary") == ctx.clock.now
        for frame in Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES, Timeframe.FIFTEEN_MINUTES:
            latest = ctx.market.latest_bar(BTC, frame)
            assert latest is None or latest.close_time <= ctx.clock.now
        if ctx.clock.now == timestamp(15):
            supporting = ctx.market.latest_bar(BTC, Timeframe.FIFTEEN_MINUTES)
            assert supporting is not None and supporting.close_time == ctx.clock.now
            assert ctx.indicators.updated_at("support") == ctx.clock.now
            assert ctx.indicators.value("support") == 100.0
            ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")


def test_multiframe_atomic_indicators_and_future_execution(tmp_path: Path) -> None:
    service, spec = scenario(
        tmp_path, AtomicFrames, tuple(candle(i) for i in range(20)), start=15, end=20
    )
    result = service.run(spec)
    assert len(result.provenance.derived) == 2
    fill = rows(service, result, "fills.parquet")[0]
    assert fill["activated_at"] == fill["market_interval_open"] == str(timestamp(15))
    assert fill["market_interval_close"] == str(timestamp(16))
    assert len(rows(service, result, "strategy_actions.parquet")) == 1
