from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

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

POSITIVE = st.decimals(min_value=Decimal("0.000001"), max_value=Decimal("1000000"), places=6)


def _product(base_min: Decimal = Decimal("0"), base_max: Decimal = Decimal("1")) -> ProductSpec:
    return ProductSpec(
        Venue.COINBASE,
        ProductType.SPOT,
        ProductId("BTC-USD"),
        AssetSymbol("BTC"),
        AssetSymbol("USD"),
        "0.000001",
        "0.01",
        "0.01",
        base_min,
        base_max,
        "0",
        "10",
        "online",
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    )


@given(POSITIVE)
def test_positive_increments_remain_exact(value: Decimal) -> None:
    product = ProductSpec(
        Venue.COINBASE,
        ProductType.SPOT,
        ProductId("BTC-USD"),
        AssetSymbol("BTC"),
        AssetSymbol("USD"),
        value,
        "0.01",
        "0.01",
        "0",
        "1",
        "0",
        "1",
        "online",
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    )
    assert product.base_increment == value


@given(st.decimals(min_value=0, max_value=100, places=4), POSITIVE)
def test_min_max_pairs_obey_invariant(minimum: Decimal, range_size: Decimal) -> None:
    maximum = minimum + range_size
    assert _product(minimum, maximum).base_max_size == maximum


@given(st.decimals(min_value=Decimal("0.0001"), max_value=100, places=4))
def test_max_below_min_is_rejected(minimum: Decimal) -> None:
    with pytest.raises(InvalidProductSpecError):
        _product(minimum, minimum - Decimal("0.0001"))


@given(st.permutations(("BTC-USD", "ETH-USD")))
def test_catalog_order_permutations_have_same_hash(order: tuple[str, str]) -> None:
    products = [
        _product()
        if identifier == "BTC-USD"
        else ProductSpec(
            Venue.COINBASE,
            ProductType.SPOT,
            ProductId("ETH-USD"),
            AssetSymbol("ETH"),
            AssetSymbol("USD"),
            "0.000001",
            "0.01",
            "0.01",
            "0",
            "1",
            "0",
            "10",
            "online",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        for identifier in order
    ]
    snapshot = ProductCatalogSnapshot(
        Venue.COINBASE, UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC)), products
    )
    baseline = ProductCatalogSnapshot(
        Venue.COINBASE, UtcTimestamp(datetime(2026, 1, 2, tzinfo=UTC)), list(reversed(products))
    )
    assert snapshot.content_hash == baseline.content_hash


@given(POSITIVE)
def test_changed_included_constraint_changes_fingerprint(value: Decimal) -> None:
    baseline = _product()
    changed = ProductSpec(
        Venue.COINBASE,
        ProductType.SPOT,
        ProductId("BTC-USD"),
        AssetSymbol("BTC"),
        AssetSymbol("USD"),
        value,
        "0.01",
        "0.01",
        "0",
        "1",
        "0",
        "10",
        "online",
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    )
    if value != Decimal("0.000001"):
        assert baseline.fingerprint != changed.fingerprint
    assert changed.fingerprint == changed.fingerprint
