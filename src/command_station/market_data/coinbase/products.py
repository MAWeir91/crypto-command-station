"""Unauthenticated Coinbase Advanced public product catalog adapter."""

from collections.abc import Mapping
from typing import Protocol, cast

from command_station.domain import (
    AssetSymbol,
    ProductCatalogSnapshot,
    ProductId,
    ProductSpec,
    ProductType,
    UtcTimestamp,
    Venue,
)
from command_station.domain.errors import DomainValidationError

_REQUIRED_FIELDS = (
    "product_id",
    "product_type",
    "base_currency_id",
    "quote_currency_id",
    "base_increment",
    "quote_increment",
    "price_increment",
    "base_min_size",
    "base_max_size",
    "quote_min_size",
    "quote_max_size",
    "status",
    "is_disabled",
    "trading_disabled",
    "cancel_only",
    "limit_only",
    "post_only",
    "auction_mode",
    "view_only",
)
MAX_PUBLIC_PRODUCT_PAGES = 10_000


class CoinbaseProductError(Exception):
    """Base error for the bounded Coinbase public product boundary."""


class CoinbaseProductPayloadError(CoinbaseProductError, ValueError):
    """Raised when Coinbase public product metadata is incomplete or invalid."""


class CoinbaseProductApiError(CoinbaseProductError):
    """Raised when the Coinbase SDK public product call fails."""


class _SdkProductClient(Protocol):
    def get_public_products(self, **kwargs: object) -> object: ...

    def get_public_product(self, product_id: str, **kwargs: object) -> object: ...


class CoinbaseProductCatalogClient:
    """Fetch and normalize only Coinbase's unauthenticated public product endpoints."""

    def __init__(self, sdk_client: _SdkProductClient | None = None) -> None:
        if sdk_client is None:
            from coinbase.rest import RESTClient  # type: ignore[import-untyped]

            sdk_client = cast(
                _SdkProductClient,
                RESTClient(api_key=None, api_secret=None, key_file=None, timeout=10),
            )
        self._sdk_client = sdk_client

    def list_spot_products(self, *, observed_at: UtcTimestamp) -> ProductCatalogSnapshot:
        """Fetch every public SPOT page and atomically normalize the complete catalog."""
        payloads: list[Mapping[str, object]] = []
        seen_cursors: set[str] = set()
        cursor: str | None = None
        page_count = 0
        while True:
            kwargs: dict[str, object] = {"product_type": "SPOT", "get_tradability_status": True}
            if cursor is not None:
                kwargs["cursor"] = cursor
            try:
                response = self._sdk_client.get_public_products(**kwargs)
            except Exception as error:
                raise CoinbaseProductApiError(
                    "Coinbase public product catalog request failed"
                ) from error
            page = _response_mapping(response)
            page_count += 1
            page_products = _required_list(page, "products")
            payloads.extend(_mapping_item(item, "products") for item in page_products)
            pagination = _required_mapping(page, "pagination")
            has_next = _required_bool(pagination, "has_next")
            if not has_next:
                break
            next_cursor = _required_string(pagination, "next_cursor")
            if not next_cursor.strip() or next_cursor in seen_cursors:
                raise CoinbaseProductPayloadError("Coinbase pagination cursor is blank or repeated")
            if page_count >= MAX_PUBLIC_PRODUCT_PAGES:
                raise CoinbaseProductPayloadError(
                    "Coinbase pagination exceeded the configured page limit"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        try:
            products = tuple(normalize_coinbase_product(payload) for payload in payloads)
            return ProductCatalogSnapshot(Venue.COINBASE, observed_at, products)
        except (CoinbaseProductPayloadError, DomainValidationError) as error:
            raise CoinbaseProductPayloadError(
                "Coinbase product catalog normalization failed"
            ) from error

    def get_spot_product(self, product_id: ProductId) -> ProductSpec:
        """Fetch and normalize one public Coinbase spot product without authentication."""
        if not isinstance(product_id, ProductId):
            raise CoinbaseProductPayloadError("product_id must be a ProductId")
        try:
            response = self._sdk_client.get_public_product(
                product_id.value, product_type="SPOT", get_tradability_status=True
            )
        except Exception as error:
            raise CoinbaseProductApiError("Coinbase public product request failed") from error
        return normalize_coinbase_product(_response_mapping(response))


def normalize_coinbase_product(payload: Mapping[str, object]) -> ProductSpec:
    """Strictly convert one plain Coinbase provider payload into a ProductSpec."""
    if not isinstance(payload, Mapping):
        raise CoinbaseProductPayloadError("Coinbase product payload must be a mapping")
    for field in _REQUIRED_FIELDS:
        if field not in payload:
            raise CoinbaseProductPayloadError(f"Coinbase product payload is missing {field}")
    if _required_string(payload, "product_type") != ProductType.SPOT.value:
        raise CoinbaseProductPayloadError("Coinbase product payload is not SPOT")
    try:
        return ProductSpec(
            venue=Venue.COINBASE,
            product_type=ProductType.SPOT,
            product_id=ProductId(_required_string(payload, "product_id")),
            base_currency=AssetSymbol(_required_string(payload, "base_currency_id")),
            quote_currency=AssetSymbol(_required_string(payload, "quote_currency_id")),
            base_increment=_required_decimal_string(payload, "base_increment"),
            quote_increment=_required_decimal_string(payload, "quote_increment"),
            price_increment=_required_decimal_string(payload, "price_increment"),
            base_min_size=_required_decimal_string(payload, "base_min_size"),
            base_max_size=_required_decimal_string(payload, "base_max_size"),
            quote_min_size=_required_decimal_string(payload, "quote_min_size"),
            quote_max_size=_required_decimal_string(payload, "quote_max_size"),
            status=_required_string(payload, "status"),
            is_disabled=_required_bool(payload, "is_disabled"),
            trading_disabled=_required_bool(payload, "trading_disabled"),
            cancel_only=_required_bool(payload, "cancel_only"),
            limit_only=_required_bool(payload, "limit_only"),
            post_only=_required_bool(payload, "post_only"),
            auction_mode=_required_bool(payload, "auction_mode"),
            view_only=_required_bool(payload, "view_only"),
        )
    except DomainValidationError as error:
        raise CoinbaseProductPayloadError("Coinbase product payload is invalid") from error


def _response_mapping(response: object) -> Mapping[str, object]:
    try:
        to_dict = getattr(response, "to_dict", None)
        converted = to_dict() if callable(to_dict) else response
    except Exception as error:
        raise CoinbaseProductApiError("Coinbase SDK response conversion failed") from error
    return _mapping_item(converted, "Coinbase SDK response")


def _mapping_item(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CoinbaseProductPayloadError(f"{name} must be a mapping")
    return cast(Mapping[str, object], value)


def _required_mapping(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
    if name not in payload:
        raise CoinbaseProductPayloadError(f"Coinbase response is missing {name}")
    return _mapping_item(payload[name], name)


def _required_list(payload: Mapping[str, object], name: str) -> list[object]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise CoinbaseProductPayloadError(f"Coinbase response field {name} must be a list")
    return value


def _required_string(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        raise CoinbaseProductPayloadError(f"Coinbase field {name} must be a string")
    return value


def _required_decimal_string(payload: Mapping[str, object], name: str) -> str:
    return _required_string(payload, name)


def _required_bool(payload: Mapping[str, object], name: str) -> bool:
    value = payload.get(name)
    if type(value) is not bool:
        raise CoinbaseProductPayloadError(f"Coinbase field {name} must be a boolean")
    return value
