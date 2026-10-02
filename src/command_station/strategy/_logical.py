"""Bounded semantic serialization; no infrastructure or process identity."""

import json
import math
import re
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256

from command_station.domain import UtcTimestamp, decimal_to_text


class StrategyContractError(ValueError):
    pass


def identifier(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_-]*", value) is None:
        raise StrategyContractError("invalid strategy identifier")


def logical(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, Decimal):
        text = decimal_to_text(value)
        text = "0" if value == 0 else (text.rstrip("0").rstrip(".") if "." in text else text)
        return {"decimal": text}
    if isinstance(value, UtcTimestamp):
        return {"utc": str(value)}
    if type(value) is float:
        if not math.isfinite(value):
            raise StrategyContractError("nonfinite analytical value")
        return {"float": value.hex()}
    if isinstance(value, tuple):
        return [logical(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "type": type(value).__name__,
            "fields": {field.name: logical(getattr(value, field.name)) for field in fields(value)},
        }
    raise StrategyContractError("unsupported logical value")


def serialize(value: object) -> str:
    return json.dumps(logical(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: object) -> str:
    return sha256(serialize(value).encode("utf-8")).hexdigest()
