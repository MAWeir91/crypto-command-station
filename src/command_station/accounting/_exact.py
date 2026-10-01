"""Context-independent exact decimal arithmetic and logical serialization."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from hashlib import sha256

from command_station.domain import UtcTimestamp, decimal_to_text

ZERO = Decimal(0)


def decimal(value: Fraction) -> Decimal:
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("nonterminating financial decimal")
    scale = max(twos, fives)
    coefficient = value.numerator * 2 ** (scale - twos) * 5 ** (scale - fives)
    # Decimal(int) is exact, including integers beyond Python's string conversion limit.
    digits = Decimal(abs(coefficient)).as_tuple().digits
    return Decimal((int(coefficient < 0), digits, -scale))


def add(*values: Decimal) -> Decimal:
    return decimal(sum((Fraction(v) for v in values), Fraction(0)))


def sub(left: Decimal, right: Decimal) -> Decimal:
    return decimal(Fraction(left) - Fraction(right))


def mul(left: Decimal, right: Decimal) -> Decimal:
    return decimal(Fraction(left) * Fraction(right))


def neg(value: Decimal) -> Decimal:
    return value.copy_negate()


def fee(gross: Decimal, bps: int) -> Decimal:
    return decimal(Fraction(gross) * Fraction(bps, 10_000))


def logical(value: object) -> object:
    if isinstance(value, Decimal):
        text = decimal_to_text(value)
        return "0" if value == 0 else (text.rstrip("0").rstrip(".") if "." in text else text)
    if isinstance(value, UtcTimestamp):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: logical(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (tuple, list)):
        return [logical(v) for v in value]
    if isinstance(value, dict):
        return {str(k): logical(v) for k, v in value.items()}
    return value


def fingerprint(value: object) -> str:
    return sha256(
        json.dumps(
            logical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
