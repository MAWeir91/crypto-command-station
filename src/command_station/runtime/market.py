"""Runtime-owned market state and its constrained read-only view."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.replay import MarketStreamKey


class MarketPublicationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MarketView:
    """Immutable published-market snapshot with no backing-state reachability."""

    visible_through: UtcTimestamp | None
    _streams: tuple[tuple[MarketStreamKey, tuple[Candle, ...]], ...]

    def latest_bar(self, product_id: ProductId, timeframe: Timeframe) -> Candle | None:
        bars = self._bars(MarketStreamKey(product_id, timeframe))
        return bars[-1] if bars else None

    def recent_bars(
        self, product_id: ProductId, timeframe: Timeframe, limit: int
    ) -> tuple[Candle, ...]:
        if type(limit) is not int or limit <= 0:
            raise ValueError("recent bar limit must be a positive integer")
        return self._bars(MarketStreamKey(product_id, timeframe))[-limit:]

    def latest_price(self, product_id: ProductId) -> Decimal | None:
        bar = self.latest_bar(product_id, Timeframe.ONE_MINUTE)
        return None if bar is None else bar.close

    def _bars(self, key: MarketStreamKey) -> tuple[Candle, ...]:
        for stream_key, bars in self._streams:
            if stream_key == key:
                return bars
        return ()


@dataclass(slots=True)
class _MarketState:
    bars: dict[MarketStreamKey, tuple[Candle, ...]]
    visible_through: UtcTimestamp | None = None

    @classmethod
    def create(cls) -> "_MarketState":
        return cls(defaultdict(tuple))

    def snapshot(self) -> MarketView:
        return MarketView(
            self.visible_through,
            tuple(sorted(self.bars.items(), key=lambda item: _stream_sort_key(item[0]))),
        )

    def publish(self, timestamp: UtcTimestamp, values: tuple[Candle, ...]) -> None:
        staged = dict(self.bars)
        seen: set[MarketStreamKey] = set()
        for bar in values:
            key = MarketStreamKey(bar.product_id, bar.timeframe)
            current = staged.get(key, ())
            if (
                key in seen
                or bar.close_time != timestamp
                or (current and bar.close_time <= current[-1].close_time)
            ):
                raise MarketPublicationError("publication batch is duplicate or out of order")
            seen.add(key)
            staged[key] = current + (bar,)
        self.bars = staged
        self.visible_through = timestamp


def _stream_sort_key(key: MarketStreamKey) -> tuple[str, timedelta, str]:
    return (key.product_id.value, key.timeframe.duration, key.timeframe.value)
