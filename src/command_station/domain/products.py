"""Pure immutable Coinbase spot product constraint vocabulary."""

import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from command_station.domain.decimal import (
    DecimalInput,
    decimal_to_text,
    require_non_negative,
    require_positive,
)
from command_station.domain.errors import InvalidDecimalError, InvalidProductSpecError
from command_station.domain.ids import AssetSymbol, ProductId
from command_station.domain.time import UtcTimestamp

PRODUCT_SPEC_SCHEMA_VERSION = 1
PRODUCT_CATALOG_SCHEMA_VERSION = 1


class Venue(StrEnum):
    """The sole venue represented by the initial product catalog."""

    COINBASE = "coinbase"


class ProductType(StrEnum):
    """The sole supported product type."""

    SPOT = "SPOT"


@dataclass(frozen=True, slots=True)
class ProductSpec:
    """Immutable normalized constraints and status facts for one Coinbase spot product."""

    venue: Venue
    product_type: ProductType
    product_id: ProductId
    base_currency: AssetSymbol
    quote_currency: AssetSymbol
    base_increment: Decimal
    quote_increment: Decimal
    price_increment: Decimal
    base_min_size: Decimal
    base_max_size: Decimal
    quote_min_size: Decimal
    quote_max_size: Decimal
    status: str
    is_disabled: bool
    trading_disabled: bool
    cancel_only: bool
    limit_only: bool
    post_only: bool
    auction_mode: bool
    view_only: bool

    def __init__(
        self,
        venue: Venue,
        product_type: ProductType,
        product_id: ProductId,
        base_currency: AssetSymbol,
        quote_currency: AssetSymbol,
        base_increment: DecimalInput,
        quote_increment: DecimalInput,
        price_increment: DecimalInput,
        base_min_size: DecimalInput,
        base_max_size: DecimalInput,
        quote_min_size: DecimalInput,
        quote_max_size: DecimalInput,
        status: str,
        is_disabled: bool,
        trading_disabled: bool,
        cancel_only: bool,
        limit_only: bool,
        post_only: bool,
        auction_mode: bool,
        view_only: bool,
    ) -> None:
        if venue is not Venue.COINBASE:
            raise InvalidProductSpecError("product venue must be Coinbase")
        if product_type is not ProductType.SPOT:
            raise InvalidProductSpecError("product type must be spot")
        if not isinstance(product_id, ProductId):
            raise InvalidProductSpecError("product_id must be a ProductId")
        if not isinstance(base_currency, AssetSymbol) or not isinstance(
            quote_currency, AssetSymbol
        ):
            raise InvalidProductSpecError("product currencies must be AssetSymbol values")
        if base_currency == quote_currency:
            raise InvalidProductSpecError("base and quote currencies must differ")
        if not isinstance(status, str) or not status or status != status.strip():
            raise InvalidProductSpecError("product status must be a non-empty unpadded string")
        flags = (
            is_disabled,
            trading_disabled,
            cancel_only,
            limit_only,
            post_only,
            auction_mode,
            view_only,
        )
        if any(type(flag) is not bool for flag in flags):
            raise InvalidProductSpecError("product capability fields must be booleans")
        try:
            base_increment_value = require_positive(base_increment)
            quote_increment_value = require_positive(quote_increment)
            price_increment_value = require_positive(price_increment)
            base_min_size_value = require_non_negative(base_min_size)
            base_max_size_value = require_positive(base_max_size)
            quote_min_size_value = require_non_negative(quote_min_size)
            quote_max_size_value = require_positive(quote_max_size)
            # A ProductSpec is only valid if its required canonical fingerprint
            # representation is bounded and can be produced immediately.
            for numeric_value in (
                base_increment_value,
                quote_increment_value,
                price_increment_value,
                base_min_size_value,
                base_max_size_value,
                quote_min_size_value,
                quote_max_size_value,
            ):
                decimal_to_text(numeric_value)
        except InvalidDecimalError as error:
            raise InvalidProductSpecError(f"invalid product numeric value: {error}") from error
        if base_max_size_value < base_min_size_value:
            raise InvalidProductSpecError("base maximum size must not be below minimum size")
        if quote_max_size_value < quote_min_size_value:
            raise InvalidProductSpecError("quote maximum size must not be below minimum size")

        for name, value in (
            ("venue", venue),
            ("product_type", product_type),
            ("product_id", product_id),
            ("base_currency", base_currency),
            ("quote_currency", quote_currency),
            ("base_increment", base_increment_value),
            ("quote_increment", quote_increment_value),
            ("price_increment", price_increment_value),
            ("base_min_size", base_min_size_value),
            ("base_max_size", base_max_size_value),
            ("quote_min_size", quote_min_size_value),
            ("quote_max_size", quote_max_size_value),
            ("status", status),
            ("is_disabled", is_disabled),
            ("trading_disabled", trading_disabled),
            ("cancel_only", cancel_only),
            ("limit_only", limit_only),
            ("post_only", post_only),
            ("auction_mode", auction_mode),
            ("view_only", view_only),
        ):
            object.__setattr__(self, name, value)

    @property
    def fingerprint(self) -> str:
        """Return the SHA-256 fingerprint of explicit product-constraint content."""
        return _sha256_canonical(self._canonical_content())

    def _canonical_content(self) -> dict[str, object]:
        return {
            "schema_version": PRODUCT_SPEC_SCHEMA_VERSION,
            "venue": self.venue.value,
            "product_type": self.product_type.value,
            "product_id": self.product_id.value,
            "base_currency": self.base_currency.value,
            "quote_currency": self.quote_currency.value,
            "base_increment": decimal_to_text(self.base_increment),
            "quote_increment": decimal_to_text(self.quote_increment),
            "price_increment": decimal_to_text(self.price_increment),
            "base_min_size": decimal_to_text(self.base_min_size),
            "base_max_size": decimal_to_text(self.base_max_size),
            "quote_min_size": decimal_to_text(self.quote_min_size),
            "quote_max_size": decimal_to_text(self.quote_max_size),
            "status": self.status,
            "is_disabled": self.is_disabled,
            "trading_disabled": self.trading_disabled,
            "cancel_only": self.cancel_only,
            "limit_only": self.limit_only,
            "post_only": self.post_only,
            "auction_mode": self.auction_mode,
            "view_only": self.view_only,
        }


@dataclass(frozen=True, slots=True)
class ProductCatalogSnapshot:
    """Immutable observation of a complete normalized Coinbase spot catalog."""

    venue: Venue
    observed_at: UtcTimestamp
    products: tuple[ProductSpec, ...]

    def __init__(
        self,
        venue: Venue,
        observed_at: UtcTimestamp,
        products: tuple[ProductSpec, ...] | list[ProductSpec],
    ) -> None:
        if venue is not Venue.COINBASE:
            raise InvalidProductSpecError("catalog venue must be Coinbase")
        if not isinstance(observed_at, UtcTimestamp):
            raise InvalidProductSpecError("catalog observation must be a UtcTimestamp")
        normalized_products = tuple(products)
        product_ids: set[ProductId] = set()
        for product in normalized_products:
            if not isinstance(product, ProductSpec):
                raise InvalidProductSpecError("catalog products must be ProductSpec values")
            if product.venue is not venue or product.product_type is not ProductType.SPOT:
                raise InvalidProductSpecError("catalog products must be Coinbase spot products")
            if product.product_id in product_ids:
                raise InvalidProductSpecError("catalog contains duplicate product IDs")
            product_ids.add(product.product_id)
        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(
            self,
            "products",
            tuple(sorted(normalized_products, key=lambda product: product.product_id.value)),
        )

    @property
    def content_hash(self) -> str:
        """Return the order- and observation-time-independent catalog content hash."""
        return _sha256_canonical(
            {
                "schema_version": PRODUCT_CATALOG_SCHEMA_VERSION,
                "venue": self.venue.value,
                "product_fingerprints": [product.fingerprint for product in self.products],
            }
        )


def _sha256_canonical(content: dict[str, object]) -> str:
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return sha256(encoded).hexdigest()
