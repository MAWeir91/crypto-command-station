"""Coinbase Advanced public market-data adapters."""

from command_station.market_data.coinbase.candles import CoinbasePublicCandleClient
from command_station.market_data.coinbase.products import (
    CoinbaseProductApiError,
    CoinbaseProductCatalogClient,
    CoinbaseProductError,
    CoinbaseProductPayloadError,
    normalize_coinbase_product,
)

__all__ = [
    "CoinbaseProductApiError",
    "CoinbaseProductCatalogClient",
    "CoinbaseProductError",
    "CoinbaseProductPayloadError",
    "CoinbasePublicCandleClient",
    "normalize_coinbase_product",
]
