"""Explicit exceptions for invalid pure-domain values."""


class DomainError(Exception):
    """Base exception for command-station domain failures."""


class DomainValidationError(DomainError, ValueError):
    """Raised when supplied data cannot form a valid domain value."""


class InvalidDecimalError(DomainValidationError):
    """Raised when a value is not a finite exact decimal."""


class InvalidTimestampError(DomainValidationError):
    """Raised when a timestamp is not an explicit UTC instant."""


class InvalidIdentifierError(DomainValidationError):
    """Raised when an opaque identifier is malformed."""


class UnsupportedTimeframeError(DomainValidationError):
    """Raised when a timeframe code is outside the supported fixed set."""


class InvalidCandleError(DomainValidationError):
    """Raised when OHLCV data cannot form a structurally valid candle."""


class InvalidProductSpecError(DomainValidationError):
    """Raised when product constraints cannot form a valid spot specification."""
