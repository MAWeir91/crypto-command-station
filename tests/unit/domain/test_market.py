from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from command_station.domain import (
    Candle,
    InvalidCandleError,
    ProductId,
    Side,
    Timeframe,
    UnsupportedTimeframeError,
    UtcTimestamp,
)


def _open_time(timeframe: Timeframe = Timeframe.FIVE_MINUTES) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))


def _candle(**overrides: object) -> Candle:
    timeframe = overrides.pop("timeframe", Timeframe.FIVE_MINUTES)
    assert isinstance(timeframe, Timeframe)
    open_time = overrides.pop("open_time", _open_time(timeframe))
    assert isinstance(open_time, UtcTimestamp)
    fields: dict[str, object] = {
        "product_id": ProductId("BTC-USD"),
        "timeframe": timeframe,
        "open_time": open_time,
        "close_time": UtcTimestamp(open_time.value + timeframe.duration),
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("90"),
        "close": Decimal("105"),
        "volume": Decimal("3"),
    }
    fields.update(overrides)
    return Candle(**fields)  # type: ignore[arg-type]


def test_timeframe_codes_and_durations_are_exactly_supported_set() -> None:
    expected = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "2h": timedelta(hours=2),
        "4h": timedelta(hours=4),
        "6h": timedelta(hours=6),
        "1d": timedelta(days=1),
    }
    assert {timeframe.value: timeframe.duration for timeframe in Timeframe} == expected
    assert {Timeframe.parse(code).duration for code in expected} == set(expected.values())


@pytest.mark.parametrize("value", ["", "1M", "1w", None])
def test_timeframe_parse_rejects_unsupported_codes(value: object) -> None:
    with pytest.raises(UnsupportedTimeframeError):
        Timeframe.parse(value)  # type: ignore[arg-type]


def test_candle_accepts_structurally_valid_values_and_is_immutable() -> None:
    candle = _candle()
    assert candle.close_time.value - candle.open_time.value == timedelta(minutes=5)
    with pytest.raises(FrozenInstanceError):
        candle.close = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open", "0"),
        ("high", "-1"),
        ("low", "0"),
        ("close", "-1"),
        ("volume", "-0.1"),
    ],
)
def test_candle_rejects_invalid_price_or_volume(field: str, value: str) -> None:
    with pytest.raises(InvalidCandleError):
        _candle(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [("high", "99"), ("low", "106")],
)
def test_candle_rejects_invalid_ohlc_bounds(field: str, value: str) -> None:
    with pytest.raises(InvalidCandleError):
        _candle(**{field: value})


def test_candle_rejects_duration_mismatch_and_misaligned_open_time() -> None:
    with pytest.raises(InvalidCandleError):
        _candle(close_time=UtcTimestamp(datetime(2026, 1, 1, 12, 4, tzinfo=UTC)))
    with pytest.raises(InvalidCandleError):
        _candle(open_time=UtcTimestamp(datetime(2026, 1, 1, 12, 1, tzinfo=UTC)))


def test_side_has_only_stable_buy_and_sell_values() -> None:
    assert [(side.name, side.value) for side in Side] == [("BUY", "BUY"), ("SELL", "SELL")]
