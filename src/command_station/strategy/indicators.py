"""Per-run SMA/EMA. SMA uses fsum; EMA seeds with SMA then alpha recurrence."""

import math
from dataclasses import dataclass
from enum import StrEnum

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.strategy._logical import StrategyContractError, identifier


class IndicatorKind(StrEnum):
    SMA = "SMA"
    EMA = "EMA"


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    name: str
    product_id: ProductId
    timeframe: Timeframe
    kind: IndicatorKind
    period: int

    def __post_init__(self) -> None:
        identifier(self.name)
        if (
            not isinstance(self.product_id, ProductId)
            or not isinstance(self.timeframe, Timeframe)
            or not isinstance(self.kind, IndicatorKind)
            or type(self.period) is not int
            or self.period < 1
        ):
            raise StrategyContractError("invalid indicator spec")


@dataclass(frozen=True, slots=True)
class IndicatorReading:
    name: str
    value: float | None
    updated_at: UtcTimestamp | None
    source_bar_count: int


@dataclass(frozen=True, slots=True)
class IndicatorView:
    readings: tuple[IndicatorReading, ...]

    def _reading(self, name: str) -> IndicatorReading:
        for reading in self.readings:
            if reading.name == name:
                return reading
        raise StrategyContractError("unknown indicator")

    def value(self, name: str) -> float | None:
        return self._reading(name).value

    def ready(self, name: str) -> bool:
        return self.value(name) is not None

    def updated_at(self, name: str) -> UtcTimestamp | None:
        return self._reading(name).updated_at


@dataclass(slots=True)
class _IndicatorState:
    closes: tuple[float, ...] = ()
    count: int = 0
    value: float | None = None
    updated_at: UtcTimestamp | None = None


class IndicatorEngine:
    """Internal built-ins only. No arbitrary stateful indicator callbacks."""

    def __init__(self, specs: tuple[IndicatorSpec, ...]):
        self.specs = tuple(sorted(specs, key=lambda spec: spec.name))
        if len({spec.name for spec in specs}) != len(specs):
            raise StrategyContractError("duplicate indicator name")
        self._states = {spec.name: _IndicatorState() for spec in self.specs}

    @property
    def view(self) -> IndicatorView:
        return IndicatorView(
            tuple(
                IndicatorReading(
                    spec.name,
                    self._states[spec.name].value,
                    self._states[spec.name].updated_at,
                    self._states[spec.name].count,
                )
                for spec in self.specs
            )
        )

    def update(self, bars: tuple[Candle, ...], timestamp: UtcTimestamp) -> None:
        by_stream = {(bar.product_id, bar.timeframe): bar for bar in bars}
        if len(by_stream) != len(bars) or any(bar.close_time != timestamp for bar in bars):
            raise StrategyContractError("indicator input must be one published closing batch")
        staged: dict[str, _IndicatorState] = {}
        for spec in self.specs:
            bar = by_stream.get((spec.product_id, spec.timeframe))
            if bar is None:
                continue
            old = self._states[spec.name]
            if old.updated_at is not None and timestamp <= old.updated_at:
                raise StrategyContractError("indicator source updated twice/out of order")
            close = float(bar.close)  # Explicit analytical conversion only here.
            if not math.isfinite(close):
                raise StrategyContractError("indicator source is not finite as float")
            closes = (old.closes + (close,))[-spec.period :]
            value: float | None = None
            if old.count + 1 >= spec.period:
                if spec.kind is IndicatorKind.SMA or old.value is None:
                    value = math.fsum(closes) / spec.period
                else:
                    alpha = 2 / (spec.period + 1)
                    value = alpha * close + (1 - alpha) * old.value
                if not math.isfinite(value):
                    raise StrategyContractError("nonfinite indicator output")
            staged[spec.name] = _IndicatorState(closes, old.count + 1, value, timestamp)
        self._states.update(staged)
