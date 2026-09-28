from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from command_station.domain import (
    AssetSymbol,
    EntityId,
    InvalidIdentifierError,
    InvalidTimestampError,
    ProductId,
    UtcTimestamp,
)


def test_utc_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(InvalidTimestampError):
        UtcTimestamp(datetime(2026, 1, 1))


def test_utc_timestamp_normalizes_offset_and_round_trips_canonical_text() -> None:
    local = datetime(2026, 1, 1, 9, 30, 15, 123456, tzinfo=timezone(timedelta(hours=-5)))
    timestamp = UtcTimestamp(local)

    assert str(timestamp) == "2026-01-01T14:30:15.123456Z"
    assert UtcTimestamp.parse(str(timestamp)) == timestamp
    assert timestamp.value.tzinfo is UTC


def test_entity_id_parses_and_formats_canonical_uuid() -> None:
    value = "12345678-1234-5678-1234-567812345678"
    entity_id = EntityId.parse(value)

    assert str(entity_id) == value
    assert entity_id.value == UUID(value)
    assert EntityId.parse(str(entity_id)) == entity_id


def test_entity_id_rejects_a_non_uuid_constructor_value() -> None:
    with pytest.raises(InvalidIdentifierError):
        EntityId("not-a-uuid")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-uuid",
        "12345678-1234-5678-1234-567812345678 ",
        "{12345678-1234-5678-1234-567812345678}",
        "12345678123456781234567812345678",
        "12345678-1234-5678-abcd-567812345678".upper(),
    ],
)
def test_entity_id_rejects_invalid_text(value: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        EntityId.parse(value)


@pytest.mark.parametrize("constructor", [AssetSymbol, ProductId])
@pytest.mark.parametrize("value", ["", " BTC", "BTC ", "BTC USD", "BTC\tUSD"])
def test_opaque_identifiers_reject_empty_or_whitespace(
    constructor: type[AssetSymbol] | type[ProductId], value: str
) -> None:
    with pytest.raises(InvalidIdentifierError):
        constructor(value)


def test_opaque_identifiers_preserve_exact_text_and_are_immutable() -> None:
    product = ProductId("btc-USD")
    assert str(product) == "btc-USD"
    with pytest.raises(FrozenInstanceError):
        product.value = "BTC-USD"  # type: ignore[misc]
