from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from command_station.domain import ProductId, Side, Timeframe
from command_station.execution import BaseQuantity, OrderId
from command_station.strategy import (
    BarSubscription,
    BoolParam,
    ChoiceParam,
    DecimalParam,
    FloatParam,
    IndicatorKind,
    IndicatorSpec,
    IntParam,
    StateField,
    StateType,
    StrategyContractError,
    StrategyDefinition,
    StrategyOrderView,
    StrategyParameters,
    StrategyState,
)
from command_station.strategy.indicators import IndicatorEngine
from tests.execution_fixtures import candle, timestamp
from tests.strategy_fixtures import BTC, RecordingStrategy, compose, definition


def test_all_parameters_defaults_exactness_and_immutability() -> None:
    schema = (
        IntParam("count", 3, 1, 5),
        DecimalParam("size", "0.12345678901234567890"),
        FloatParam("alpha", 1),
        BoolParam("enabled", True),
        ChoiceParam("choice", ("a", "b"), "a"),
        IntParam("optional", optional=True),
    )
    params = StrategyParameters(schema)
    assert params.get("size") == Decimal("0.12345678901234567890")
    assert params.get("alpha") == 1.0 and params.get("optional") is None
    assert params.fingerprint == StrategyParameters(tuple(reversed(schema))).fingerprint
    with pytest.raises(FrozenInstanceError):
        params._values = ()  # type: ignore[misc]
    with pytest.raises(StrategyContractError):
        StrategyParameters(schema, {"unknown": 1})
    with pytest.raises(StrategyContractError):
        StrategyParameters((IntParam("required"),))
    for spec, value in (
        (IntParam("count"), True),
        (DecimalParam("size"), 0.1),
        (FloatParam("alpha"), float("nan")),
        (FloatParam("alpha"), float("inf")),
        (BoolParam("enabled"), 1),
        (ChoiceParam("choice", ("a",)), "b"),
        (IntParam("count", minimum=1), 0),
    ):
        with pytest.raises(ValueError):
            StrategyParameters((spec,), {spec.name: value})


def test_schema_state_scalar_snapshots_and_invalid_values() -> None:
    schema = (
        StateField("counter", StateType.INT, 0),
        StateField("amount", StateType.DECIMAL, Decimal("0")),
        StateField("time", StateType.UTC, timestamp()),
    )
    state = StrategyState(schema)
    snapshot = state.snapshot
    state.set("counter", 4)
    assert snapshot != state.snapshot
    assert state.fingerprint == StrategyState(schema, {"counter": 4}).fingerprint
    assert state.to_json() == StrategyState(tuple(reversed(schema)), {"counter": 4}).to_json()
    assert '"decimal":"0"' in state.to_json() and '"utc"' in state.to_json()
    for name, value in (("unknown", 1), ("counter", True), ("amount", float("nan"))):
        with pytest.raises(ValueError):
            state.set(name, value)
    with pytest.raises(StrategyContractError):
        StrategyState(schema, {"unknown": 3})
    with pytest.raises(StrategyContractError):
        StateField("container", StateType.STR, [])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        StateField("bad", StateType.DECIMAL, Decimal("Infinity"))


def test_definition_validations_and_semantic_order() -> None:
    primary = BarSubscription(BTC, Timeframe.FIVE_MINUTES, True)
    support = BarSubscription(BTC, Timeframe.ONE_MINUTE)
    a = StrategyDefinition("trend", (primary, support))
    assert a.fingerprint == StrategyDefinition("trend", (support, primary)).fingerprint
    for subs in ((), (support,), (primary, primary), (primary, replace(support, primary=True))):
        with pytest.raises(StrategyContractError):
            StrategyDefinition("trend", subs)
    with pytest.raises(StrategyContractError):
        replace(a, strategy_id="Bad ID")
    with pytest.raises(StrategyContractError):
        BarSubscription(BTC, Timeframe.ONE_MINUTE, warmup_bars=True)
    with pytest.raises(StrategyContractError):
        replace(
            a,
            indicators=(
                IndicatorSpec(
                    "sma", ProductId("ETH-USD"), Timeframe.ONE_MINUTE, IndicatorKind.SMA, 2
                ),
            ),
        )


def test_sma_ema_seed_source_specificity_and_snapshot() -> None:
    specs = (
        IndicatorSpec("sma", BTC, Timeframe.ONE_MINUTE, IndicatorKind.SMA, 3),
        IndicatorSpec("ema", BTC, Timeframe.ONE_MINUTE, IndicatorKind.EMA, 3),
    )
    engine = IndicatorEngine(specs)
    pristine = engine.view
    for index, price in enumerate(("1", "2", "3", "5")):
        bar = candle(index, open=price, low=price, high=price, close=price)
        engine.update((bar,), timestamp(index + 1))
        if index < 2:
            assert not engine.view.ready("sma")
    assert engine.view.value("sma") == 10 / 3
    assert engine.view.value("ema") == 3.5
    assert pristine.value("ema") is None
    engine.update((candle(4, product_id="ETH-USD"),), timestamp(5))
    assert engine.view.updated_at("ema") == timestamp(4)
    with pytest.raises(FrozenInstanceError):
        engine.view.readings = ()  # type: ignore[misc]
    with pytest.raises(StrategyContractError):
        engine.update((candle(3),), timestamp(4))
    with pytest.raises(StrategyContractError):
        engine.update(
            (candle(5, open="1e400", low="1e400", high="1e400", close="1e400"),), timestamp(6)
        )


def test_context_only_subscribed_value_snapshots() -> None:
    strategy = RecordingStrategy()
    runtime = compose(strategy, minutes=4)
    runtime.step()
    ctx = strategy.contexts[0]
    assert ctx.market.product_spec(BTC).product_id == BTC
    assert ctx.market.latest_price(BTC) == Decimal("100")
    with pytest.raises(StrategyContractError):
        ctx.market.latest_bar(BTC, Timeframe.FIVE_MINUTES)
    with pytest.raises(StrategyContractError):
        ctx.market.product_spec(ProductId("ETH-USD"))
    for name in (
        "runtime",
        "broker",
        "accounting_engine",
        "risk_engine",
        "feed",
        "dataset",
        "repository",
        "coinbase",
        "mode",
    ):
        assert not hasattr(ctx, name)
    with pytest.raises(FrozenInstanceError):
        ctx.clock.now = timestamp(2)  # type: ignore[misc]
    before = ctx.market.recent_bars(BTC, Timeframe.ONE_MINUTE, 100)
    runtime.run()
    assert ctx.market.recent_bars(BTC, Timeframe.ONE_MINUTE, 100) == before
    with pytest.raises(StrategyContractError):
        ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")


def test_command_caps_ids_and_forbidden_permissions() -> None:
    orders = StrategyOrderView(timestamp(3), 1, True, (), ())
    orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")
    orders.stop_market(BTC, Side.BUY, BaseQuantity("1"), "110", max_quote_reservation="200")
    orders.limit(BTC, Side.BUY, BaseQuantity("1"), "90")
    orders.oco_limit_stop(
        BTC, Side.BUY, BaseQuantity("1"), "90", "110", max_quote_reservation="200"
    )
    commands = orders._seal()
    assert [command.command_id.value for command in commands] == [1, 2, 3, 4]
    assert all(
        intent.created_at == timestamp(3) for command in commands for intent in command.intents
    )
    for allowed in (True, False):
        capability = StrategyOrderView(timestamp(1), 1, allowed, (), ())
        with pytest.raises(StrategyContractError):
            capability.market(BTC, Side.BUY, BaseQuantity("1"))
        with pytest.raises(StrategyContractError):
            capability.market(BTC, Side.SELL, BaseQuantity("1"), max_quote_reservation="200")
    forbidden = StrategyOrderView(timestamp(1), 1, False, (), ())
    with pytest.raises(StrategyContractError):
        forbidden.cancel(OrderId(1))
    with pytest.raises(StrategyContractError):
        forbidden.limit(BTC, Side.BUY, BaseQuantity("1"), "90")
    with pytest.raises(AttributeError):
        orders.results = ()  # type: ignore[misc]


def test_preflight_requires_fresh_runner_and_warmup() -> None:
    from command_station.runtime import InvalidRuntimeConfigurationError, ReferenceTradingRuntime

    metadata = replace(
        definition(),
        indicators=(IndicatorSpec("sma", BTC, Timeframe.ONE_MINUTE, IndicatorKind.SMA, 3),),
    )
    with pytest.raises(InvalidRuntimeConfigurationError):
        compose(RecordingStrategy(metadata), start=2)
    with pytest.raises(InvalidRuntimeConfigurationError):
        compose(RecordingStrategy(definition(Timeframe.FIVE_MINUTES)), start=2)
    original = compose(RecordingStrategy(), minutes=4)
    with pytest.raises(InvalidRuntimeConfigurationError):
        ReferenceTradingRuntime(
            clock=original.clock,
            market_feed=original.market_feed,
            broker=original.broker,
            accounting=original.accounting,
            risk=original.risk,
            strategy_runner=original.strategy_runner,
        )


def test_parameter_schema_type_identity_and_bounds() -> None:
    base = definition()
    assert (
        replace(base, parameters=(FloatParam("size"),)).fingerprint
        != replace(base, parameters=(DecimalParam("size"),)).fingerprint
    )
    assert StrategyParameters((DecimalParam("size"),), {"size": "1.00"}).fingerprint == (
        StrategyParameters((DecimalParam("size"),), {"size": "1"}).fingerprint
    )
    for create in (
        lambda: IntParam("size", minimum=True),
        lambda: DecimalParam("size", minimum=Decimal("NaN")),
        lambda: FloatParam("size", maximum=float("inf")),
        lambda: IntParam("size", minimum=2, maximum=1),
        lambda: ChoiceParam("size", ("a", "a")),
    ):
        with pytest.raises(ValueError):
            create()


def test_state_supported_scalars_and_definition_duplicates() -> None:
    fields = (
        StateField("none", StateType.NONE, None),
        StateField("enabled", StateType.BOOL, True),
        StateField("text", StateType.STR, "hello"),
        StateField("analytical", StateType.FLOAT, 1.0),
    )
    assert StrategyState(fields).snapshot == StrategyState(tuple(reversed(fields))).snapshot
    with pytest.raises(ValueError):
        StrategyState(fields).set("analytical", float("nan"))
    with pytest.raises(StrategyContractError):
        replace(definition(), parameters=(IntParam("size"), IntParam("size")))
    spec = IndicatorSpec("sma", BTC, Timeframe.ONE_MINUTE, IndicatorKind.SMA, 1)
    with pytest.raises(StrategyContractError):
        replace(definition(), indicators=(spec, spec))
    from command_station.runtime import InvalidRuntimeConfigurationError

    with pytest.raises(InvalidRuntimeConfigurationError):
        compose(RecordingStrategy(definition(Timeframe.ONE_HOUR)), minutes=60, start=60)
