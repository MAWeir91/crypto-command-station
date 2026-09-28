from decimal import Decimal, getcontext

import pytest

from command_station.domain import (
    InvalidDecimalError,
    decimal_to_text,
    require_non_negative,
    require_positive,
    to_decimal,
)


@pytest.mark.parametrize("value", [Decimal("1.2300"), 42, "0.00000001", "1E+3"])
def test_to_decimal_accepts_exact_values_without_quantizing(value: Decimal | int | str) -> None:
    assert to_decimal(value) == Decimal(value)


@pytest.mark.parametrize("value", [1.0, True, False, "NaN", "Infinity", "-Infinity", "nope", None])
def test_to_decimal_rejects_inexact_or_invalid_values(value: object) -> None:
    with pytest.raises(InvalidDecimalError):
        to_decimal(value)  # type: ignore[arg-type]


def test_decimal_text_is_ordinary_base_ten_and_context_is_unchanged() -> None:
    before = getcontext().copy()
    assert decimal_to_text("1.2300") == "1.2300"
    assert decimal_to_text("1E+3") == "1000"
    after = getcontext()
    assert (after.prec, after.rounding, after.Emin, after.Emax, after.capitals, after.clamp) == (
        before.prec,
        before.rounding,
        before.Emin,
        before.Emax,
        before.capitals,
        before.clamp,
    )
    assert after.flags == before.flags
    assert after.traps == before.traps


def test_decimal_text_rejects_unbounded_fixed_point_expansion_before_formatting() -> None:
    with pytest.raises(InvalidDecimalError, match="fixed-point text exceeds"):
        decimal_to_text("1e1000000")


def test_decimal_text_limit_preserves_exact_safe_exponent_round_trip() -> None:
    text = decimal_to_text("1e9999")
    assert len(text) == 10_000
    assert to_decimal(text) == to_decimal("1e9999")


@pytest.mark.parametrize("value", ["0", "-1"])
def test_require_positive_rejects_non_positive_values(value: str) -> None:
    with pytest.raises(InvalidDecimalError):
        require_positive(value)


def test_require_non_negative_rejects_negative_values() -> None:
    with pytest.raises(InvalidDecimalError):
        require_non_negative("-0.0001")
