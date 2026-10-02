"""Typed immutable parameters. Float parameters are analytical configuration only."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from command_station.domain import to_decimal
from command_station.strategy._logical import StrategyContractError, fingerprint, identifier


class _Missing(Enum):
    REQUIRED = "REQUIRED"


REQUIRED = _Missing.REQUIRED
ParameterValue = int | Decimal | float | bool | str | None


@dataclass(frozen=True, slots=True)
class IntParam:
    name: str
    default: object = REQUIRED
    minimum: int | None = None
    maximum: int | None = None
    optional: bool = False

    def __post_init__(self) -> None:
        _validate_spec(self)


@dataclass(frozen=True, slots=True)
class DecimalParam:
    name: str
    default: object = REQUIRED
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    optional: bool = False

    def __post_init__(self) -> None:
        _validate_spec(self)


@dataclass(frozen=True, slots=True)
class FloatParam:
    name: str
    default: object = REQUIRED
    minimum: float | None = None
    maximum: float | None = None
    optional: bool = False

    def __post_init__(self) -> None:
        _validate_spec(self)


@dataclass(frozen=True, slots=True)
class BoolParam:
    name: str
    default: object = REQUIRED
    optional: bool = False

    def __post_init__(self) -> None:
        _validate_spec(self)


@dataclass(frozen=True, slots=True)
class ChoiceParam:
    name: str
    choices: tuple[str, ...]
    default: object = REQUIRED
    optional: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.choices, tuple)
            or not self.choices
            or any(type(choice) is not str for choice in self.choices)
            or len(set(self.choices)) != len(self.choices)
        ):
            raise StrategyContractError("choices must be unique immutable strings")
        _validate_spec(self)


ParameterSpec = IntParam | DecimalParam | FloatParam | BoolParam | ChoiceParam


def _resolve(spec: ParameterSpec, value: object) -> ParameterValue:
    if value is None and spec.optional:
        return None
    resolved: ParameterValue
    if isinstance(spec, DecimalParam):
        if not isinstance(value, (Decimal, int, str)) or isinstance(value, bool):
            raise StrategyContractError("Decimal parameter requires exact input")
        resolved = to_decimal(value)
    elif isinstance(spec, FloatParam):
        if type(value) not in (float, int):
            raise StrategyContractError("Float parameter requires finite float/int")
        assert isinstance(value, (float, int))
        try:
            resolved = float(value)
        except OverflowError as error:
            raise StrategyContractError("Float parameter overflow") from error
        if not math.isfinite(resolved):
            raise StrategyContractError("Float parameter must be finite")
    elif isinstance(spec, IntParam):
        if type(value) is not int:
            raise StrategyContractError("Int parameter requires int, not bool")
        assert isinstance(value, int)
        resolved = value
    elif isinstance(spec, BoolParam):
        if type(value) is not bool:
            raise StrategyContractError("Bool parameter requires bool")
        assert isinstance(value, bool)
        resolved = value
    else:
        if type(value) is not str or value not in spec.choices:
            raise StrategyContractError("Choice parameter requires a declared choice")
        assert isinstance(value, str)
        resolved = value
    if isinstance(spec, (IntParam, DecimalParam, FloatParam)):
        assert isinstance(resolved, (int, Decimal, float))
        if (spec.minimum is not None and resolved < spec.minimum) or (
            spec.maximum is not None and resolved > spec.maximum
        ):
            raise StrategyContractError("parameter outside bounds")
    return resolved


def _validate_spec(spec: ParameterSpec) -> None:
    identifier(spec.name)
    if type(spec.optional) is not bool:
        raise StrategyContractError("optional must be bool")
    if isinstance(spec, (IntParam, DecimalParam, FloatParam)):
        for bound in (spec.minimum, spec.maximum):
            if bound is not None:
                if isinstance(spec, IntParam) and type(bound) is not int:
                    raise StrategyContractError("Int bounds require int")
                if isinstance(spec, DecimalParam) and not isinstance(bound, Decimal):
                    raise StrategyContractError("Decimal bounds require Decimal")
                if isinstance(spec, FloatParam) and type(bound) not in (float, int):
                    raise StrategyContractError("Float bounds require float/int")
                fingerprint(bound)  # Reject nonfinite/unserializable bounds.
        if spec.minimum is not None and spec.maximum is not None and spec.minimum > spec.maximum:
            raise StrategyContractError("inverted bounds")
    if spec.default is not REQUIRED:
        object.__setattr__(spec, "default", _resolve(spec, spec.default))


@dataclass(frozen=True, slots=True, init=False)
class StrategyParameters:
    _values: tuple[tuple[str, ParameterValue], ...]

    def __init__(
        self, schema: tuple[ParameterSpec, ...], values: Mapping[str, object] | None = None
    ):
        supplied = dict(values or {})
        names = {spec.name for spec in schema}
        if len(names) != len(schema) or supplied.keys() - names:
            raise StrategyContractError("duplicate/unknown parameter")
        resolved: list[tuple[str, ParameterValue]] = []
        for spec in sorted(schema, key=lambda spec: spec.name):
            value = supplied.get(spec.name, spec.default)
            if value is REQUIRED:
                if not spec.optional:
                    raise StrategyContractError("missing required parameter")
                value = None
            resolved.append((spec.name, _resolve(spec, value)))
        object.__setattr__(self, "_values", tuple(resolved))

    def get(self, name: str) -> ParameterValue:
        for key, value in self._values:
            if key == name:
                return value
        raise StrategyContractError("unknown parameter")

    @property
    def fingerprint(self) -> str:
        return fingerprint(self._values)
