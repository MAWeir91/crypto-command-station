"""Immutable completed-bar subscriptions."""

from dataclasses import dataclass

from command_station.domain import ProductId, Timeframe
from command_station.strategy._logical import StrategyContractError


@dataclass(frozen=True, slots=True)
class BarSubscription:
    product_id: ProductId
    timeframe: Timeframe
    primary: bool = False
    warmup_bars: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_id, ProductId)
            or not isinstance(self.timeframe, Timeframe)
            or type(self.primary) is not bool
            or type(self.warmup_bars) is not int
            or self.warmup_bars < 0
        ):
            raise StrategyContractError("invalid subscription")

    @property
    def key(self) -> tuple[ProductId, Timeframe]:
        return self.product_id, self.timeframe
