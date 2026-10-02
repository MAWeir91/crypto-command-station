from dataclasses import FrozenInstanceError

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from command_station.domain import Candle, ProductId, Side, Timeframe
from command_station.execution import BaseQuantity
from command_station.strategy import (
    BarSubscription,
    IndicatorKind,
    IndicatorSpec,
    IntParam,
    StateField,
    StateType,
    Strategy,
    StrategyContext,
    StrategyContractError,
    StrategyDefinition,
    StrategyParameters,
    StrategyState,
)
from tests.execution_fixtures import timestamp
from tests.strategy_fixtures import BTC, compose


@settings(max_examples=16, deadline=None)
@given(start=st.integers(1, 3), extra=st.integers(1, 5), reverse=st.booleans())
def test_temporal_commands_indicator_state_and_fresh_run(
    start: int, extra: int, reverse: bool
) -> None:
    class Checked(Strategy):
        definition = StrategyDefinition(
            "checked",
            (BarSubscription(BTC, Timeframe.ONE_MINUTE, True),),
            state_schema=(StateField("bars", StateType.INT, 0),),
            indicators=(IndicatorSpec("sma", BTC, Timeframe.ONE_MINUTE, IndicatorKind.SMA, 1),),
        )

        def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
            assert ctx.clock.now >= timestamp(start)
            assert bar.close_time == ctx.clock.now
            assert all(
                item.close_time <= ctx.clock.now
                for item in ctx.market.recent_bars(BTC, Timeframe.ONE_MINUTE, 100)
            )
            assert ctx.indicators.updated_at("sma") == ctx.clock.now
            count = ctx.state.get("bars")
            assert isinstance(count, int)
            ctx.state.set("bars", count + 1)
            if count == 0:
                ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")

    first = compose(Checked(), start=start, minutes=start + extra, reverse=reverse)
    second = compose(Checked(), start=start, minutes=start + extra, reverse=not reverse)
    result, rerun = first.run(), second.run()
    assert result.strategy_fingerprint == rerun.strategy_fingerprint
    assert result.accounting_fingerprint == rerun.accounting_fingerprint
    runner = first.strategy_runner
    assert runner is not None
    assert all(
        command.timestamp == intent.created_at
        for command in runner.commands
        for intent in command.intents
    )
    assert first.broker.fills[0].market_interval_open >= first.broker.fills[0].activated_at
    assert first.broker.fills[0].market_interval_close > first.broker.fills[0].activated_at
    assert runner.state.get("bars") == extra + 1
    assert all(event.timestamp >= timestamp(start) for event in runner.audit_history)


@settings(max_examples=10, deadline=None)
@given(
    reverse=st.booleans(),
    primary=st.sampled_from([Timeframe.FIVE_MINUTES, Timeframe.FIFTEEN_MINUTES]),
)
def test_same_time_permutation_and_supporting_only(primary: Timeframe, reverse: bool) -> None:
    subscriptions = (
        BarSubscription(BTC, Timeframe.ONE_MINUTE),
        BarSubscription(BTC, primary, True),
        BarSubscription(ProductId("ETH-USD"), Timeframe.ONE_MINUTE),
    )

    class Checked(Strategy):
        definition = StrategyDefinition(
            "atomic",
            tuple(reversed(subscriptions)) if reverse else subscriptions,
            state_schema=(StateField("bars", StateType.INT, 0),),
            indicators=(IndicatorSpec("support", BTC, Timeframe.ONE_MINUTE, IndicatorKind.EMA, 2),),
        )

        def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
            assert bar.timeframe is primary and bar.close_time == ctx.clock.now
            for sub in subscriptions:
                current = ctx.market.latest_bar(sub.product_id, sub.timeframe)
                assert current is not None and current.close_time == ctx.clock.now
            assert ctx.indicators.updated_at("support") == ctx.clock.now
            count = ctx.state.get("bars")
            assert isinstance(count, int)
            ctx.state.set("bars", count + 1)

    runtime = compose(Checked(), minutes=20, start=15, reverse=reverse)
    runtime.run()
    runner = runtime.strategy_runner
    assert runner is not None
    assert runner.state.get("bars") == (2 if primary is Timeframe.FIVE_MINUTES else 1)
    assert runner.indicators.view.updated_at("support") == timestamp(20)
    equivalent = compose(Checked(), minutes=20, start=15, reverse=not reverse)
    assert equivalent.run().strategy_fingerprint == runner.fingerprint


@given(
    value=st.one_of(
        st.booleans(), st.text(), st.none(), st.floats(allow_nan=True, allow_infinity=True)
    )
)
def test_generated_wrong_type_state_assignment(value: object) -> None:
    state = StrategyState((StateField("counter", StateType.INT, 0),))
    before = state.fingerprint
    with pytest.raises(StrategyContractError):
        state.set("counter", value)  # type: ignore[arg-type]
    assert state.fingerprint == before


@given(value=st.integers(-10000, 10000))
def test_resolved_parameter_fingerprints_and_immutability(value: int) -> None:
    schema = (IntParam("count"),)
    params = StrategyParameters(schema, {"count": value})
    assert params.fingerprint == StrategyParameters(schema, {"count": value}).fingerprint
    with pytest.raises(FrozenInstanceError):
        params._values = (("count", value + 1),)  # type: ignore[misc]
