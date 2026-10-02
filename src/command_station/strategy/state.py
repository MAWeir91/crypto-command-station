"""Explicit scalar schema-owned mutable state; snapshots contain values only."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from command_station.domain import UtcTimestamp
from command_station.strategy._logical import (
    StrategyContractError,
    fingerprint,
    identifier,
    logical,
    serialize,
)

StateValue = None | bool | int | str | Decimal | float | UtcTimestamp


class StateType(StrEnum):
    NONE = "none"
    BOOL = "bool"
    INT = "int"
    STR = "str"
    DECIMAL = "decimal"
    FLOAT = "float"
    UTC = "utc"


@dataclass(frozen=True, slots=True)
class StateField:
    name: str
    value_type: StateType
    default: StateValue

    def __post_init__(self) -> None:
        identifier(self.name)
        self.validate(self.default)

    def validate(self, value: object) -> None:
        types = {
            StateType.NONE: type(None),
            StateType.BOOL: bool,
            StateType.INT: int,
            StateType.STR: str,
            StateType.DECIMAL: Decimal,
            StateType.FLOAT: float,
            StateType.UTC: UtcTimestamp,
        }
        if not isinstance(self.value_type, StateType) or type(value) is not types[self.value_type]:
            raise StrategyContractError("state assignment does not match schema")
        logical(value)


class StrategyState:
    __slots__ = ("_schema", "_values")

    def __init__(
        self, schema: tuple[StateField, ...], initial: Mapping[str, StateValue] | None = None
    ):
        supplied = dict(initial or {})
        if len({field.name for field in schema}) != len(schema):
            raise StrategyContractError("duplicate state field")
        if supplied.keys() - {field.name for field in schema}:
            raise StrategyContractError("unknown initial state key")
        self._schema = tuple(sorted(schema, key=lambda field: field.name))
        self._values = {
            field.name: supplied.get(field.name, field.default) for field in self._schema
        }
        for field in self._schema:
            field.validate(self._values[field.name])

    def get(self, name: str) -> StateValue:
        if name not in self._values:
            raise StrategyContractError("unknown state key")
        return self._values[name]

    def set(self, name: str, value: StateValue) -> None:
        field = next((field for field in self._schema if field.name == name), None)
        if field is None:
            raise StrategyContractError("unknown state key")
        field.validate(value)
        self._values[name] = value

    @property
    def snapshot(self) -> tuple[tuple[str, StateValue], ...]:
        return tuple((field.name, self._values[field.name]) for field in self._schema)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.snapshot)

    def to_json(self) -> str:
        """Return canonical tagged scalar JSON, retaining Decimal/UTC type information."""
        return serialize(self.snapshot)
