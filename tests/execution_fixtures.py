from datetime import UTC, datetime, timedelta

from command_station.domain import (
    AssetSymbol,
    Candle,
    ProductId,
    ProductSpec,
    ProductType,
    Timeframe,
    UtcTimestamp,
    Venue,
)


def timestamp(minute: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute))


def product(product_id: str = "BTC-USD", **flags: bool) -> ProductSpec:
    base, quote = product_id.split("-")
    return ProductSpec(
        venue=Venue.COINBASE,
        product_type=ProductType.SPOT,
        product_id=ProductId(product_id),
        base_currency=AssetSymbol(base),
        quote_currency=AssetSymbol(quote),
        base_increment="0.001",
        quote_increment="0.01",
        price_increment="0.01",
        base_min_size="0.001",
        base_max_size="100",
        quote_min_size="1",
        quote_max_size="1000000",
        status="online",
        is_disabled=flags.get("is_disabled", False),
        trading_disabled=flags.get("trading_disabled", False),
        cancel_only=flags.get("cancel_only", False),
        limit_only=flags.get("limit_only", False),
        post_only=flags.get("post_only", False),
        auction_mode=flags.get("auction_mode", False),
        view_only=flags.get("view_only", False),
    )


def candle(
    minute: int,
    *,
    product_id: str = "BTC-USD",
    open: str = "100",
    high: str = "105",
    low: str = "95",
    close: str = "100",
) -> Candle:
    return Candle(
        ProductId(product_id),
        Timeframe.ONE_MINUTE,
        timestamp(minute),
        timestamp(minute + 1),
        open,
        high,
        low,
        close,
        "0",
    )
