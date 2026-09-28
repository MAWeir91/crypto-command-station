"""Pure immutable market-domain primitives."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from command_station.domain.decimal import DecimalInput, require_non_negative, require_positive
from command_station.domain.errors import (
    InvalidCandleError,
    InvalidDecimalError,
    UnsupportedTimeframeError,
)
from command_station.domain.ids import ProductId
from command_station.domain.time import UtcTimestamp


class Timeframe(StrEnum):
    """The agreed fixed UTC candle intervals."""

    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    TWO_HOURS = "2h"
    FOUR_HOURS = "4h"
    SIX_HOURS = "6h"
    ONE_DAY = "1d"

    @property
    def duration(self) -> timedelta:
        return _TIMEFRAME_DURATIONS[self]

    @classmethod
    def parse(cls, code: str) -> "Timeframe":
        try:
            return cls(code)
        except (ValueError, TypeError) as error:
            raise UnsupportedTimeframeError(f"unsupported timeframe: {code!r}") from error


_TIMEFRAME_DURATIONS: Mapping[Timeframe, timedelta] = MappingProxyType(
    {
        Timeframe.ONE_MINUTE: timedelta(minutes=1),
        Timeframe.FIVE_MINUTES: timedelta(minutes=5),
        Timeframe.FIFTEEN_MINUTES: timedelta(minutes=15),
        Timeframe.THIRTY_MINUTES: timedelta(minutes=30),
        Timeframe.ONE_HOUR: timedelta(hours=1),
        Timeframe.TWO_HOURS: timedelta(hours=2),
        Timeframe.FOUR_HOURS: timedelta(hours=4),
        Timeframe.SIX_HOURS: timedelta(hours=6),
        Timeframe.ONE_DAY: timedelta(days=1),
    }
)


class Side(StrEnum):
    """Stable trading-side vocabulary."""

    BUY = "BUY"
    SELL = "SELL"


_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Candle:
    """A structurally valid immutable canonical OHLCV interval."""

    product_id: ProductId
    timeframe: Timeframe
    open_time: UtcTimestamp
    close_time: UtcTimestamp
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __init__(
        self,
        product_id: ProductId,
        timeframe: Timeframe,
        open_time: UtcTimestamp,
        close_time: UtcTimestamp,
        open: DecimalInput,
        high: DecimalInput,
        low: DecimalInput,
        close: DecimalInput,
        volume: DecimalInput,
    ) -> None:
        if not isinstance(product_id, ProductId):
            raise InvalidCandleError("candle product_id must be a ProductId")
        if not isinstance(timeframe, Timeframe):
            raise InvalidCandleError("candle timeframe must be a supported Timeframe")
        if not isinstance(open_time, UtcTimestamp) or not isinstance(close_time, UtcTimestamp):
            raise InvalidCandleError("candle times must be UtcTimestamp values")

        try:
            open_value = require_positive(open)
            high_value = require_positive(high)
            low_value = require_positive(low)
            close_value = require_positive(close)
            volume_value = require_non_negative(volume)
        except InvalidDecimalError as error:
            raise InvalidCandleError(f"invalid candle numeric value: {error}") from error

        if close_time <= open_time:
            raise InvalidCandleError("candle close_time must be after open_time")
        if close_time.value - open_time.value != timeframe.duration:
            raise InvalidCandleError("candle interval must equal its timeframe duration")
        if (open_time.value - _UNIX_EPOCH) % timeframe.duration != timedelta(0):
            raise InvalidCandleError("candle open_time must align to its UTC timeframe boundary")
        if high_value < open_value or high_value < close_value or high_value < low_value:
            raise InvalidCandleError("candle high must not be below OHLC values")
        if low_value > open_value or low_value > close_value:
            raise InvalidCandleError("candle low must not exceed open or close")

        object.__setattr__(self, "product_id", product_id)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "open_time", open_time)
        object.__setattr__(self, "close_time", close_time)
        object.__setattr__(self, "open", open_value)
        object.__setattr__(self, "high", high_value)
        object.__setattr__(self, "low", low_value)
        object.__setattr__(self, "close", close_value)
        object.__setattr__(self, "volume", volume_value)
