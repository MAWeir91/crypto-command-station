"""Trusted application strategy code and its immutable metadata declaration."""

from dataclasses import dataclass

from command_station.domain import Candle
from command_station.execution import Fill
from command_station.strategy._logical import StrategyContractError, fingerprint, identifier
from command_station.strategy.context import StrategyContext
from command_station.strategy.indicators import IndicatorSpec
from command_station.strategy.parameters import (
    BoolParam,
    ChoiceParam,
    DecimalParam,
    FloatParam,
    IntParam,
    ParameterSpec,
)
from command_station.strategy.state import StateField
from command_station.strategy.subscriptions import BarSubscription


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: str
    subscriptions: tuple[BarSubscription, ...]
    parameters: tuple[ParameterSpec, ...] = ()
    state_schema: tuple[StateField, ...] = ()
    indicators: tuple[IndicatorSpec, ...] = ()

    def __post_init__(self) -> None:
        identifier(self.strategy_id)
        for name, cls in (
            ("subscriptions", (BarSubscription,)),
            ("parameters", (IntParam, DecimalParam, FloatParam, BoolParam, ChoiceParam)),
            ("state_schema", (StateField,)),
            ("indicators", (IndicatorSpec,)),
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(type(value) not in cls for value in values):
                raise StrategyContractError("definition requires immutable built-in declarations")
        if sum(sub.primary for sub in self.subscriptions) != 1 or len(
            {sub.key for sub in self.subscriptions}
        ) != len(self.subscriptions):
            raise StrategyContractError("unique subscriptions and exactly one primary required")
        for values in (self.parameters, self.state_schema, self.indicators):
            if len({value.name for value in values}) != len(values):
                raise StrategyContractError("duplicate definition field")
        if any(
            (spec.product_id, spec.timeframe) not in {sub.key for sub in self.subscriptions}
            for spec in self.indicators
        ):
            raise StrategyContractError("indicator source must be subscribed")
        object.__setattr__(
            self,
            "subscriptions",
            tuple(
                sorted(
                    self.subscriptions,
                    key=lambda sub: (sub.product_id.value, sub.timeframe.duration),
                )
            ),
        )
        for name in ("parameters", "state_schema", "indicators"):
            object.__setattr__(
                self, name, tuple(sorted(getattr(self, name), key=lambda value: value.name))
            )
        fingerprint(self)  # Validate all metadata can be serialized now.

    @property
    def fingerprint(self) -> str:
        return fingerprint((1, self))

    @property
    def primary(self) -> BarSubscription:
        return next(sub for sub in self.subscriptions if sub.primary)


class Strategy:
    definition: StrategyDefinition

    def on_start(self, ctx: StrategyContext) -> None:
        pass

    def on_fill(self, ctx: StrategyContext, fill: Fill) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        pass

    def on_stop(self, ctx: StrategyContext) -> None:
        pass
