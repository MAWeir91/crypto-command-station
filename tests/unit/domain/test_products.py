from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from command_station.domain import (
    AssetSymbol,
    InvalidProductSpecError,
    ProductCatalogSnapshot,
    ProductId,
    ProductSpec,
    ProductType,
    UtcTimestamp,
    Venue,
)


def _product(**overrides: object) -> ProductSpec:
    fields: dict[str, object] = {
        "venue": Venue.COINBASE,
        "product_type": ProductType.SPOT,
        "product_id": ProductId("BTC-USD"),
        "base_currency": AssetSymbol("BTC"),
        "quote_currency": AssetSymbol("USD"),
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "price_increment": "0.01",
        "base_min_size": "0.00000001",
        "base_max_size": "1000",
        "quote_min_size": "1",
        "quote_max_size": "1000000",
        "status": "online",
        "is_disabled": False,
        "trading_disabled": False,
        "cancel_only": False,
        "limit_only": False,
        "post_only": False,
        "auction_mode": False,
        "view_only": False,
    }
    fields.update(overrides)
    return ProductSpec(**fields)  # type: ignore[arg-type]


def _observed_at(hour: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, hour, tzinfo=UTC))


def test_product_spec_preserves_exact_decimals_and_is_immutable() -> None:
    product = _product(base_increment="0.00000001")
    assert product.base_increment == Decimal("0.00000001")
    with pytest.raises(FrozenInstanceError):
        product.status = "offline"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [("base_increment", "0"), ("quote_increment", "-1"), ("price_increment", "0")],
)
def test_product_spec_rejects_non_positive_increments(field: str, value: str) -> None:
    with pytest.raises(InvalidProductSpecError):
        _product(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_min_size", "-1"),
        ("quote_min_size", "-1"),
        ("base_max_size", "0"),
        ("quote_max_size", "0"),
    ],
)
def test_product_spec_rejects_invalid_size_bounds(field: str, value: str) -> None:
    with pytest.raises(InvalidProductSpecError):
        _product(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [("base_max_size", "0.000000001"), ("quote_max_size", "0.1")],
)
def test_product_spec_rejects_maximum_below_minimum(field: str, value: str) -> None:
    with pytest.raises(InvalidProductSpecError):
        _product(**{field: value})


def test_product_spec_rejects_invalid_identity_status_and_flags() -> None:
    with pytest.raises(InvalidProductSpecError):
        _product(quote_currency=AssetSymbol("BTC"))
    with pytest.raises(InvalidProductSpecError):
        _product(status=" ")
    with pytest.raises(InvalidProductSpecError):
        _product(view_only="false")


def test_product_spec_rejects_numeric_values_that_cannot_be_canonically_fingerprinted() -> None:
    with pytest.raises(InvalidProductSpecError):
        _product(base_increment=Decimal("1e10001"))


def test_fingerprint_is_deterministic_and_includes_constraints_status_and_flags() -> None:
    product = _product()
    assert product.fingerprint == _product().fingerprint
    assert product.fingerprint != _product(price_increment="0.1").fingerprint
    assert product.fingerprint != _product(base_max_size="999").fingerprint
    assert product.fingerprint != _product(status="offline").fingerprint
    assert product.fingerprint != _product(view_only=True).fingerprint


def test_snapshot_is_immutable_canonical_and_content_addressed() -> None:
    btc = _product()
    eth = _product(product_id=ProductId("ETH-USD"), base_currency=AssetSymbol("ETH"))
    first = ProductCatalogSnapshot(Venue.COINBASE, _observed_at(), [eth, btc])
    second = ProductCatalogSnapshot(Venue.COINBASE, _observed_at(1), [btc, eth])
    assert [product.product_id.value for product in first.products] == ["BTC-USD", "ETH-USD"]
    assert first.content_hash == second.content_hash
    assert (
        first.content_hash
        != ProductCatalogSnapshot(Venue.COINBASE, _observed_at(), [btc]).content_hash
    )
    with pytest.raises(FrozenInstanceError):
        first.products = ()  # type: ignore[misc]


def test_snapshot_rejects_duplicate_ids() -> None:
    with pytest.raises(InvalidProductSpecError):
        ProductCatalogSnapshot(Venue.COINBASE, _observed_at(), [_product(), _product()])
