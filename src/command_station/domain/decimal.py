"""Exact, finite decimal conversion and validation helpers."""

from decimal import Decimal, InvalidOperation, localcontext

from command_station.domain.errors import InvalidDecimalError

DecimalInput = Decimal | int | str
_MAX_DECIMAL_TEXT_LENGTH = 10_000


def to_decimal(value: DecimalInput) -> Decimal:
    """Return a finite :class:`Decimal` without rounding or quantization.

    Floats and booleans are rejected explicitly: neither is an acceptable exact
    representation for financial or market values.
    """
    if isinstance(value, (bool, float)):
        raise InvalidDecimalError("decimal input must be a Decimal, int, or decimal string")
    if not isinstance(value, (Decimal, int, str)):
        raise InvalidDecimalError("decimal input must be a Decimal, int, or decimal string")

    try:
        # Decimal parsing may signal InvalidOperation for malformed text. Keep
        # that signal local so validation cannot alter the process context.
        with localcontext():
            decimal_value = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise InvalidDecimalError("decimal input is malformed") from error

    if not decimal_value.is_finite():
        raise InvalidDecimalError("decimal input must be finite")
    return decimal_value


def require_positive(value: DecimalInput) -> Decimal:
    """Return a finite decimal that is strictly greater than zero."""
    decimal_value = to_decimal(value)
    if decimal_value <= 0:
        raise InvalidDecimalError("decimal value must be positive")
    return decimal_value


def require_non_negative(value: DecimalInput) -> Decimal:
    """Return a finite decimal that is greater than or equal to zero."""
    decimal_value = to_decimal(value)
    if decimal_value < 0:
        raise InvalidDecimalError("decimal value must be non-negative")
    return decimal_value


def decimal_to_text(value: DecimalInput) -> str:
    """Return bounded ordinary base-10 text for a validated finite decimal.

    The limit is an encoding safety boundary, not a financial precision rule:
    values remain exact and no rounding or quantization is performed. Inputs
    whose fixed-point representation would exceed the limit are rejected
    before formatting can allocate an unbounded string.
    """
    decimal_value = to_decimal(value)
    if _plain_text_length(decimal_value) > _MAX_DECIMAL_TEXT_LENGTH:
        raise InvalidDecimalError(
            f"decimal fixed-point text exceeds {_MAX_DECIMAL_TEXT_LENGTH} characters"
        )
    return format(decimal_value, "f")


def _plain_text_length(value: Decimal) -> int:
    """Calculate ``format(value, 'f')`` length without materializing it."""
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise InvalidDecimalError("decimal input must be finite")
    sign_length = 1 if sign else 0
    digits_length = len(digits)

    if value.is_zero():
        return sign_length + (1 if exponent >= 0 else 2 - exponent)
    if exponent >= 0:
        return sign_length + digits_length + exponent
    if digits_length + exponent > 0:
        return sign_length + digits_length + 1
    return sign_length + 2 - exponent
