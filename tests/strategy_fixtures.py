"""Real sealed financial/runtime composition for strategy evidence."""

from command_station.accounting import SpotAccountingEngine, SpotAccountSpec
from command_station.domain import Candle, ProductId, Timeframe
from command_station.execution import ReferenceExecutionSpec, SimulatedBroker
from command_station.market_data.datasets import CanonicalCandleDataset
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.market_data.resampling import resample_canonical_dataset
from command_station.risk import RiskEngine, RiskPolicy
from command_station.runtime import ReferenceTradingRuntime, SimulatedClock
from command_station.strategy import (
    BarSubscription,
    Strategy,
    StrategyContext,
    StrategyDefinition,
    StrategyRunner,
)
from tests.execution_fixtures import candle, product, timestamp
from tests.runtime_fixtures import canonical

BTC = ProductId("BTC-USD")


def definition(primary: Timeframe = Timeframe.ONE_MINUTE) -> StrategyDefinition:
    return StrategyDefinition("example", (BarSubscription(BTC, primary, True),))


def compose(
    strategy: Strategy,
    *,
    minutes: int = 20,
    start: int = 1,
    policy: RiskPolicy | None = None,
    cash: str = "1000",
    reverse: bool = False,
) -> ReferenceTradingRuntime:
    products = {sub.product_id.value for sub in strategy.definition.subscriptions} | {"BTC-USD"}
    sources_list: list[CanonicalCandleDataset] = []
    for name in sorted(products, reverse=reverse):
        base = canonical(name, minutes=minutes)
        sources_list.append(
            CanonicalCandleDataset(
                product_id=base.product_id,
                start=base.start,
                end=base.end,
                as_of=base.as_of,
                candles=tuple(candle(index, product_id=name) for index in range(minutes)),
                gaps=(),
                source_pages=base.source_pages,
            )
        )
    sources = tuple(sources_list)
    derived = tuple(
        resample_canonical_dataset(source, frame)
        for source in sources
        for frame in (Timeframe.FIVE_MINUTES, Timeframe.FIFTEEN_MINUTES)
    )
    feed = HistoricalReplayFeed(sources, reversed(derived) if reverse else derived)
    execution = ReferenceExecutionSpec(fee_bps=100)
    accounting = SpotAccountingEngine(
        SpotAccountSpec(initial_cash=cash, product_specs=tuple(product(name) for name in products)),
        feed.start,
        execution,
    )
    return ReferenceTradingRuntime(
        clock=SimulatedClock(feed.start),
        market_feed=feed,
        broker=SimulatedBroker(execution),
        accounting=accounting,
        risk=RiskEngine(policy),
        strategy_runner=StrategyRunner(strategy, trading_start=timestamp(start)),
    )


class RecordingStrategy(Strategy):
    """Observation-only recorder for tests; trading state still uses ctx.state."""

    def __init__(self, metadata: StrategyDefinition | None = None):
        self.definition = metadata or definition()
        self.calls: list[tuple[str, StrategyContext]] = []
        self.contexts: list[StrategyContext] = []

    def on_start(self, ctx: StrategyContext) -> None:
        self.calls.append(("start", ctx))
        self.contexts.append(ctx)

    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        self.calls.append(("bar", ctx))
        self.contexts.append(ctx)

    def on_stop(self, ctx: StrategyContext) -> None:
        self.calls.append(("stop", ctx))
        self.contexts.append(ctx)
