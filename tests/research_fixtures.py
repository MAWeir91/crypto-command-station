"""Real dataset, catalog, runtime and artifact composition for Phase 012."""

from collections.abc import Callable
from pathlib import Path

from command_station.accounting import SpotAccountSpec
from command_station.domain import Candle, ProductId, Side, Timeframe
from command_station.execution import BaseQuantity, ReferenceExecutionSpec
from command_station.market_data.datasets import CanonicalCandleDataset
from command_station.market_data.parquet_store import LocalCanonicalDatasetStore
from command_station.research import (
    BacktestDatasetRef,
    BacktestPeriod,
    BacktestService,
    BacktestSpec,
    EngineIdentity,
    LocalBacktestArtifactStore,
    StrategyArtifactCatalog,
    StrategyArtifactDescriptor,
)
from command_station.risk import RiskPolicy
from command_station.strategy import BarSubscription, Strategy, StrategyContext, StrategyDefinition
from tests.execution_fixtures import candle, product, timestamp
from tests.runtime_fixtures import canonical

BTC = ProductId("BTC-USD")
PREDECESSOR = "390dc8a746789f819bcc44f60e1ecf13175991ef"


class NoTrade(Strategy):
    definition = StrategyDefinition("research", (BarSubscription(BTC, Timeframe.ONE_MINUTE, True),))


class BuyHold(NoTrade):
    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        if not ctx.orders.results:
            ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")


class RoundTrip(BuyHold):
    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        super().on_bar(ctx, bar)
        if ctx.clock.now == timestamp(3):
            ctx.orders.market(BTC, Side.SELL, BaseQuantity("1"))


class FinalOrder(NoTrade):
    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        if ctx.clock.now == timestamp(4):
            ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")


class MultiFrame(NoTrade):
    definition = StrategyDefinition(
        "research",
        (
            BarSubscription(BTC, Timeframe.ONE_MINUTE),
            BarSubscription(BTC, Timeframe.FIVE_MINUTES, True, 1),
        ),
    )


class MultiProduct(NoTrade):
    definition = StrategyDefinition(
        "research",
        (
            BarSubscription(BTC, Timeframe.ONE_MINUTE, True),
            BarSubscription(ProductId("ETH-USD"), Timeframe.ONE_MINUTE),
        ),
    )


def setup(
    root: Path,
    factory: Callable[[], Strategy] = RoundTrip,
    *,
    minutes: int = 10,
    start: int = 1,
    end: int = 4,
    policy: RiskPolicy | None = None,
    reverse: bool = False,
) -> tuple[BacktestService, BacktestSpec]:
    metadata = factory().definition
    catalog = StrategyArtifactCatalog()
    strategy_type = type(factory())
    descriptor = StrategyArtifactDescriptor(
        "test-artifact",
        metadata.strategy_id,
        "1.0.0",
        PREDECESSOR,
        "a" * 64,
        strategy_type.__module__,
        strategy_type.__qualname__,
        metadata.fingerprint,
    )
    catalog.register(descriptor, factory)
    store = LocalCanonicalDatasetStore(root / "datasets")
    refs: list[BacktestDatasetRef] = []
    names = sorted({s.product_id.value for s in metadata.subscriptions}, reverse=reverse)
    for name in names:
        base = canonical(name, minutes)
        source = CanonicalCandleDataset(
            product_id=base.product_id,
            start=base.start,
            end=base.end,
            as_of=base.as_of,
            candles=tuple(
                candle(
                    i,
                    product_id=name,
                    open="110" if i >= 3 else "100",
                    high="115",
                    low="95",
                    close="110" if i >= 3 else "100",
                )
                for i in range(minutes)
            ),
            gaps=(),
            source_pages=base.source_pages,
        )
        store.publish(source)
        refs.append(BacktestDatasetRef(source.product_id, source.version))
    artifacts = LocalBacktestArtifactStore(root / "artifacts")
    service = BacktestService(
        datasets=store,
        strategies=catalog,
        artifacts=artifacts,
        engine_identity=EngineIdentity(PREDECESSOR, "0.1.0", "reference-v1"),
    )
    spec = BacktestSpec(
        descriptor.ref,
        (),
        tuple(refs),
        BacktestPeriod(timestamp(start), timestamp(end)),
        SpotAccountSpec(initial_cash="1000", product_specs=tuple(product(name) for name in names)),
        policy or RiskPolicy(),
        ReferenceExecutionSpec(fee_bps=100),
        0,
    )
    return service, spec
