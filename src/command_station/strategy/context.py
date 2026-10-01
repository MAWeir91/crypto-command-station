"""Strategy snapshots; only schema state and a callback-local queue are mutable."""

from dataclasses import dataclass
from decimal import Decimal

from command_station.accounting.models import AccountView, PortfolioSnapshot, PositionView
from command_station.domain import Candle, ProductId, ProductSpec, Timeframe, UtcTimestamp
from command_station.strategy._logical import StrategyContractError
from command_station.strategy.commands import StrategyOrderView
from command_station.strategy.indicators import IndicatorView
from command_station.strategy.parameters import StrategyParameters
from command_station.strategy.state import StrategyState


@dataclass(frozen=True, slots=True)
class StrategyClockView:
    now: UtcTimestamp


@dataclass(frozen=True, slots=True)
class StrategyMarketView:
    visible_through: UtcTimestamp | None
    _streams: tuple[tuple[ProductId, Timeframe, tuple[Candle, ...]], ...]
    _products: tuple[ProductSpec, ...]

    def _bars(self, product_id: ProductId, timeframe: Timeframe) -> tuple[Candle, ...]:
        for product, frame, bars in self._streams:
            if product == product_id and frame == timeframe:
                return bars
        raise StrategyContractError("undeclared market stream")

    def latest_bar(self, product_id: ProductId, timeframe: Timeframe) -> Candle | None:
        bars = self._bars(product_id, timeframe)
        return bars[-1] if bars else None

    def recent_bars(
        self, product_id: ProductId, timeframe: Timeframe, limit: int
    ) -> tuple[Candle, ...]:
        if type(limit) is not int or limit < 1:
            raise StrategyContractError("history limit must be positive integer")
        return self._bars(product_id, timeframe)[-limit:]

    def latest_price(self, product_id: ProductId) -> Decimal | None:
        bar = self.latest_bar(product_id, Timeframe.ONE_MINUTE)
        return bar.close if bar else None

    def product_spec(self, product_id: ProductId) -> ProductSpec:
        for spec in self._products:
            if spec.product_id == product_id:
                return spec
        raise StrategyContractError("undeclared product")


@dataclass(frozen=True, slots=True)
class StrategyContext:
    clock: StrategyClockView
    market: StrategyMarketView
    parameters: StrategyParameters
    state: StrategyState
    indicators: IndicatorView
    account: AccountView
    positions: tuple[PositionView, ...]
    portfolio: PortfolioSnapshot | None
    orders: StrategyOrderView
