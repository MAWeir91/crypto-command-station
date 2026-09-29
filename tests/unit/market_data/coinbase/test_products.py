from datetime import UTC, datetime

import pytest

from command_station.domain import ProductId, UtcTimestamp
from command_station.market_data.coinbase import (
    CoinbaseProductApiError,
    CoinbaseProductCatalogClient,
    CoinbaseProductPayloadError,
    normalize_coinbase_product,
)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "product_id": "BTC-USD",
        "product_type": "SPOT",
        "base_currency_id": "BTC",
        "quote_currency_id": "USD",
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
        "price": "99999.99",
        "volume_24h": "1.23",
        "unrelated": "ignored",
    }
    payload.update(overrides)
    return payload


class _Response:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def to_dict(self) -> dict[str, object]:
        return self._value


class _FakeSdk:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    def get_public_products(self, **kwargs: object) -> _Response:
        self.calls.append(kwargs)
        return _Response(self.pages[len(self.calls) - 1])

    def get_public_product(self, product_id: str, **kwargs: object) -> _Response:
        self.calls.append({"product_id": product_id, **kwargs})
        return _Response(_payload())


def _page(
    products: list[dict[str, object]], has_next: bool = False, next_cursor: str = ""
) -> dict[str, object]:
    return {"products": products, "pagination": {"has_next": has_next, "next_cursor": next_cursor}}


def test_normalizer_uses_explicit_currency_fields_and_ignores_volatile_fields() -> None:
    product = normalize_coinbase_product(
        _payload(product_id="OPAQUE", base_currency_id="BASE", quote_currency_id="QUOTE")
    )
    assert product.product_id.value == "OPAQUE"
    assert product.base_currency.value == "BASE"
    assert product.quote_currency.value == "QUOTE"


@pytest.mark.parametrize(
    "change",
    [
        {"base_increment": 0.1},
        {"view_only": "false"},
        {"product_type": "FUTURE"},
        {"base_increment": "not-a-decimal"},
    ],
)
def test_normalizer_rejects_malformed_provider_values(change: dict[str, object]) -> None:
    with pytest.raises(CoinbaseProductPayloadError):
        normalize_coinbase_product(_payload(**change))


def test_normalizer_rejects_missing_required_field() -> None:
    payload = _payload()
    del payload["status"]
    with pytest.raises(CoinbaseProductPayloadError):
        normalize_coinbase_product(payload)


def test_catalog_adapter_uses_only_public_methods_and_paginates_completely() -> None:
    sdk = _FakeSdk(
        [
            _page([_payload()], has_next=True, next_cursor="second"),
            _page([_payload(product_id="ETH-USD", base_currency_id="ETH")]),
        ]
    )
    snapshot = CoinbaseProductCatalogClient(sdk).list_spot_products(
        observed_at=UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
    )
    assert [product.product_id.value for product in snapshot.products] == ["BTC-USD", "ETH-USD"]
    assert sdk.calls == [
        {"product_type": "SPOT", "get_tradability_status": True},
        {"product_type": "SPOT", "get_tradability_status": True, "cursor": "second"},
    ]


def test_catalog_adapter_rejects_repeated_cursor_and_translates_sdk_errors() -> None:
    sdk = _FakeSdk(
        [_page([], has_next=True, next_cursor="same"), _page([], has_next=True, next_cursor="same")]
    )
    with pytest.raises(CoinbaseProductPayloadError):
        CoinbaseProductCatalogClient(sdk).list_spot_products(
            observed_at=UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
        )

    class FailingSdk:
        def get_public_products(self, **kwargs: object) -> object:
            raise RuntimeError("provider failure")

        def get_public_product(self, product_id: str, **kwargs: object) -> object:
            raise RuntimeError("provider failure")

    with pytest.raises(CoinbaseProductApiError):
        CoinbaseProductCatalogClient(FailingSdk()).get_spot_product(ProductId("BTC-USD"))


@pytest.mark.parametrize("method", ["list", "get"])
def test_adapter_translates_sdk_response_conversion_errors(method: str) -> None:
    class BrokenResponse:
        def to_dict(self) -> dict[str, object]:
            raise RuntimeError("unparseable SDK response")

    class BrokenResponseSdk:
        def get_public_products(self, **kwargs: object) -> BrokenResponse:
            return BrokenResponse()

        def get_public_product(self, product_id: str, **kwargs: object) -> BrokenResponse:
            return BrokenResponse()

    client = CoinbaseProductCatalogClient(BrokenResponseSdk())
    with pytest.raises(CoinbaseProductApiError, match="response conversion"):
        if method == "list":
            client.list_spot_products(observed_at=UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC)))
        else:
            client.get_spot_product(ProductId("BTC-USD"))


def test_catalog_adapter_rejects_whitespace_cursor() -> None:
    sdk = _FakeSdk([_page([], has_next=True, next_cursor=" \t ")])
    with pytest.raises(CoinbaseProductPayloadError, match="blank or repeated"):
        CoinbaseProductCatalogClient(sdk).list_spot_products(
            observed_at=UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
        )


def test_catalog_adapter_rejects_excessive_fresh_cursor_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import command_station.market_data.coinbase.products as product_adapter

    monkeypatch.setattr(product_adapter, "MAX_PUBLIC_PRODUCT_PAGES", 1)
    sdk = _FakeSdk([_page([], has_next=True, next_cursor="fresh")])
    with pytest.raises(CoinbaseProductPayloadError, match="page limit"):
        CoinbaseProductCatalogClient(sdk).list_spot_products(
            observed_at=UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC))
        )
