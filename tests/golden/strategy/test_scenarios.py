from dataclasses import replace
from decimal import Decimal

from command_station.domain import Candle, Side, Timeframe
from command_station.execution import BaseQuantity, Fill
from command_station.risk import RiskPolicy
from command_station.runtime import RuntimeEventKind
from command_station.strategy import (
    BarSubscription,
    IndicatorKind,
    IndicatorSpec,
    StateField,
    StateType,
    StrategyActionStatus,
    StrategyContext,
    StrategyDefinition,
)
from tests.execution_fixtures import timestamp
from tests.strategy_fixtures import BTC, RecordingStrategy, compose, definition


class Buyer(RecordingStrategy):
    def __init__(self) -> None:
        super().__init__(
            replace(definition(), state_schema=(StateField("fills", StateType.INT, 0),))
        )

    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        super().on_bar(ctx, bar)
        if not ctx.orders.results:
            ctx.orders.market(BTC, Side.BUY, BaseQuantity("1.0009"), max_quote_reservation="200")

    def on_fill(self, ctx: StrategyContext, fill: Fill) -> None:
        assert ctx.positions[0].actual_quantity == Decimal("1")
        assert ctx.portfolio is not None and ctx.portfolio.fees_to_date == Decimal("1")
        assert ctx.market.visible_through == ctx.clock.now
        count = ctx.state.get("fills")
        assert isinstance(count, int)
        ctx.state.set("fills", count + 1)
        self.calls.append(("fill", ctx))


def test_same_time_multi_timeframe_decision() -> None:
    subscriptions = (
        BarSubscription(BTC, Timeframe.ONE_MINUTE),
        BarSubscription(BTC, Timeframe.FIVE_MINUTES, True),
        BarSubscription(BTC, Timeframe.FIFTEEN_MINUTES),
    )
    indicators = tuple(
        IndicatorSpec("i" + frame.value.replace("m", "minute"), BTC, frame, IndicatorKind.SMA, 1)
        for frame in (Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES, Timeframe.FIFTEEN_MINUTES)
    )
    strategy = RecordingStrategy(
        StrategyDefinition("multiframe", subscriptions, indicators=indicators)
    )
    runtime = compose(strategy, minutes=20, start=15)
    runtime.run()
    first = next(ctx for name, ctx in strategy.calls if name == "bar")
    for frame in (Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES, Timeframe.FIFTEEN_MINUTES):
        latest = first.market.latest_bar(BTC, frame)
        assert latest is not None and latest.close_time == timestamp(15)
    assert all(reading.updated_at == timestamp(15) for reading in first.indicators.readings)
    assert [ctx.clock.now for name, ctx in strategy.calls if name == "bar"] == [
        timestamp(15),
        timestamp(20),
    ]


def test_signal_bar_order_anti_lookahead() -> None:
    runtime = compose(Buyer(), minutes=4)
    first = runtime.step()
    assert first is not None and not first.fills
    assert (
        runtime.broker.orders[0].created_at == runtime.broker.orders[0].activated_at == timestamp(1)
    )
    assert runtime.broker.orders[0].activated_base_quantity.value == Decimal("1")
    second = runtime.step()
    assert second is not None and len(second.fills) == 1
    assert second.fills[0].activated_at == timestamp(1)
    assert second.fills[0].market_interval_open == timestamp(1)


def test_fill_callback_before_next_decision_exact_order() -> None:
    strategy = Buyer()
    runtime = compose(strategy, minutes=4)
    runtime.run()
    calls_at_two = [(name, ctx) for name, ctx in strategy.calls if ctx.clock.now == timestamp(2)]
    assert [name for name, _ in calls_at_two] == ["fill", "bar"]
    assert calls_at_two[1][1].state.get("fills") == 1
    kinds = [event.kind for event in runtime.trace_events if event.timestamp == timestamp(2)]
    assert kinds == [
        RuntimeEventKind.CLOCK_ADVANCED,
        RuntimeEventKind.MARKET_ACTIVITY,
        RuntimeEventKind.EXECUTION_PROCESSED,
        RuntimeEventKind.ACCOUNTING_APPLIED,
        RuntimeEventKind.PORTFOLIO_UPDATED,
        RuntimeEventKind.BARS_PUBLISHED,
        RuntimeEventKind.INDICATORS_UPDATED,
        RuntimeEventKind.FILL_CALLBACKS_PROCESSED,
        RuntimeEventKind.MARKET_STATE_READY,
        RuntimeEventKind.STRATEGY_DECISION_PROCESSED,
        RuntimeEventKind.STRATEGY_COMMANDS_PROCESSED,
    ]


def test_supporting_only_updates_without_decision() -> None:
    metadata = StrategyDefinition(
        "supporting",
        (
            BarSubscription(BTC, Timeframe.ONE_MINUTE),
            BarSubscription(BTC, Timeframe.FIVE_MINUTES, True),
        ),
        indicators=(IndicatorSpec("sma", BTC, Timeframe.ONE_MINUTE, IndicatorKind.SMA, 2),),
    )
    strategy = RecordingStrategy(metadata)
    runtime = compose(strategy, minutes=10, start=5)
    for _ in range(6):
        runtime.step()
    runner = runtime.strategy_runner
    assert runner is not None
    assert runner.indicators.view.updated_at("sma") == timestamp(6)
    assert [ctx.clock.now for name, ctx in strategy.calls if name == "bar"] == [timestamp(5)]
    assert not any(
        event.kind is RuntimeEventKind.STRATEGY_DECISION_PROCESSED
        for event in runtime.trace_events
        if event.timestamp == timestamp(6)
    )


def test_warmup_no_callback_ready_first_start_then_bar() -> None:
    metadata = replace(
        definition(),
        subscriptions=(BarSubscription(BTC, Timeframe.ONE_MINUTE, True, 3),),
        indicators=(IndicatorSpec("sma", BTC, Timeframe.ONE_MINUTE, IndicatorKind.SMA, 3),),
    )
    strategy = RecordingStrategy(metadata)
    runtime = compose(strategy, minutes=5, start=3)
    runtime.step()
    runtime.step()
    assert not strategy.calls and not runtime.broker.orders
    runtime.run()
    assert [name for name, _ in strategy.calls] == ["start", "bar", "bar", "bar", "stop"]
    assert strategy.calls[0][1].indicators.ready("sma")
    assert all(ctx.clock.now >= timestamp(3) for _, ctx in strategy.calls)


def test_risk_rejection_continues_to_later_callbacks() -> None:
    strategy = Buyer()
    runtime = compose(strategy, minutes=4, policy=RiskPolicy(trading_enabled=False))
    runtime.run()
    runner = runtime.strategy_runner
    assert runner is not None and runner.action_results[0].status is StrategyActionStatus.REJECTED
    assert runner.action_results[0].risk_decision is not None
    assert not runtime.broker.orders and not runtime.broker.fills
    assert runtime.accounting is not None and not runtime.accounting.reservations
    assert len([name for name, _ in strategy.calls if name == "bar"]) == 4
