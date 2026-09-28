from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from command_station.domain import (
    Candle,
    EntityId,
    InvalidCandleError,
    ProductId,
    Timeframe,
    UtcTimestamp,
    decimal_to_text,
    to_decimal,
)

FINITE_DECIMALS = st.decimals(allow_nan=False, allow_infinity=False, places=6)
POSITIVE_DECIMALS = st.decimals(
    min_value=Decimal("0.000001"), max_value=Decimal("10000000000000000000"), places=6
)


@given(FINITE_DECIMALS)
def test_finite_decimal_text_round_trips_exactly(value: Decimal) -> None:
    text = decimal_to_text(value)
    assert to_decimal(text) == value


@given(
    st.datetimes(
        timezones=st.integers(min_value=-12, max_value=14).map(
            lambda hours: timezone(timedelta(hours=hours))
        )
    )
)
def test_aware_datetimes_normalize_without_changing_the_instant(value: datetime) -> None:
    timestamp = UtcTimestamp(value)
    assert timestamp.value == value.astimezone(UTC)


@given(st.uuids())
def test_uuid_text_round_trips(value: UUID) -> None:
    assert EntityId.parse(str(value)).value == value


@given(
    st.sampled_from(list(Timeframe)),
    st.integers(min_value=0, max_value=100_000),
    POSITIVE_DECIMALS,
    POSITIVE_DECIMALS,
    POSITIVE_DECIMALS,
)
def test_valid_ohlc_and_aligned_interval_construct(
    timeframe: Timeframe,
    interval_index: int,
    low: Decimal,
    open_offset: Decimal,
    close_offset: Decimal,
) -> None:
    open_time = UtcTimestamp(datetime(1970, 1, 1, tzinfo=UTC) + interval_index * timeframe.duration)
    open_value = low + open_offset
    close_value = low + close_offset
    high = max(open_value, close_value) + Decimal("1")

    candle = Candle(
        ProductId("BTC-USD"),
        timeframe,
        open_time,
        UtcTimestamp(open_time.value + timeframe.duration),
        open_value,
        high,
        low,
        close_value,
        "0",
    )
    assert candle.close_time.value - candle.open_time.value == timeframe.duration


@given(POSITIVE_DECIMALS)
def test_candle_rejects_high_below_open(value: Decimal) -> None:
    open_time = UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(InvalidCandleError):
        Candle(
            ProductId("BTC-USD"),
            Timeframe.ONE_MINUTE,
            open_time,
            UtcTimestamp(open_time.value + timedelta(minutes=1)),
            value,
            value - Decimal("0.000001"),
            Decimal("0.000001"),
            value,
            "0",
        )
