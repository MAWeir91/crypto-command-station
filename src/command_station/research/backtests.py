"""Synchronous orchestration of the sealed reference financial runtime."""

from dataclasses import dataclass, replace
from typing import Protocol

from command_station.accounting import (
    AccountView,
    OrderReservation,
    PortfolioSnapshot,
    PositionView,
    SpotAccountingEngine,
)
from command_station.domain import ProductId, Timeframe
from command_station.execution import SimulatedBroker
from command_station.market_data.datasets import CanonicalCandleDataset, DatasetVersion
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.market_data.resampling import derived_result_hash, resample_canonical_dataset
from command_station.research.analytics import BacktestMetrics, analytics_window, calculate_metrics
from command_station.research.artifacts import ArtifactManifest, LocalBacktestArtifactStore
from command_station.research.specs import (
    BacktestRunId,
    BacktestSpec,
    EngineIdentity,
    fingerprint,
    logical,
)
from command_station.research.strategy_artifacts import (
    StrategyArtifactCatalog,
    StrategyArtifactDescriptor,
)
from command_station.research.summaries import ExecutionSummary, RiskSummary
from command_station.research.trades import derive_closed_lot_trades
from command_station.risk import RiskEngine
from command_station.runtime import ReferenceTradingRuntime, SimulatedClock
from command_station.strategy import StrategyRunner


class DatasetResolver(Protocol):
    def load(self, version: DatasetVersion) -> CanonicalCandleDataset: ...


@dataclass(frozen=True, slots=True)
class DatasetProvenance:
    product_id: ProductId
    dataset_version: DatasetVersion
    candle_sha256: str
    product_spec_provenance: str | None
    account_product_spec_fingerprint: str


@dataclass(frozen=True, slots=True)
class DerivedProvenance:
    product_id: ProductId
    timeframe: Timeframe
    cache_key: str
    source_dataset_version: DatasetVersion
    resampler_version: int
    result_hash: str


@dataclass(frozen=True, slots=True)
class BacktestProvenance:
    engine_identity: EngineIdentity
    strategy_artifact: StrategyArtifactDescriptor
    strategy_artifact_fingerprint: str
    strategy_definition_fingerprint: str
    resolved_parameter_fingerprint: str
    datasets: tuple[DatasetProvenance, ...]
    derived: tuple[DerivedProvenance, ...]
    account_fingerprint: str
    risk_policy_fingerprint: str
    execution_spec_fingerprint: str
    random_seed: int
    runtime_trace_fingerprint: str
    execution_fingerprint: str
    accounting_fingerprint: str
    risk_fingerprint: str
    strategy_runtime_fingerprint: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    run_id: BacktestRunId
    spec_fingerprint: str
    provenance: BacktestProvenance
    metrics: BacktestMetrics
    risk_summary: RiskSummary
    execution_summary: ExecutionSummary
    final_account: AccountView
    final_positions: tuple[PositionView, ...]
    final_portfolio: PortfolioSnapshot
    final_reservations: tuple[OrderReservation, ...]
    result_fingerprint: str
    artifact_manifest: ArtifactManifest | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "run_id": self.run_id.value,
            "spec_fingerprint": self.spec_fingerprint,
            "provenance": logical(self.provenance),
            "metrics": logical(self.metrics),
            "risk_summary": logical(self.risk_summary),
            "execution_summary": logical(self.execution_summary),
            "final_account": logical(self.final_account),
            "final_positions": logical(self.final_positions),
            "final_portfolio": logical(self.final_portfolio),
            "final_reservations": logical(self.final_reservations),
        }


class BacktestService:
    def __init__(
        self,
        *,
        datasets: DatasetResolver,
        strategies: StrategyArtifactCatalog,
        artifacts: LocalBacktestArtifactStore,
        engine_identity: EngineIdentity,
    ) -> None:
        if type(engine_identity) is not EngineIdentity:
            raise ValueError("explicit immutable engine identity required")
        self.datasets, self.strategies, self.artifacts = datasets, strategies, artifacts
        self.engine_identity = engine_identity

    def run(self, spec: BacktestSpec) -> BacktestResult:
        if type(spec) is not BacktestSpec:
            raise ValueError("immutable backtest spec required")
        descriptor, strategy = self.strategies.resolve(spec.strategy_artifact)
        runner = StrategyRunner(
            strategy, trading_start=spec.period.trading_start, parameters=dict(spec.parameters)
        )
        products = {p.product_id: p for p in spec.account.product_specs}
        sources: list[CanonicalCandleDataset] = []
        identities: list[DatasetProvenance] = []
        for ref in spec.datasets:
            source = self.datasets.load(ref.dataset_version)
            if (
                type(source) is not CanonicalCandleDataset
                or source.version != ref.dataset_version
                or source.product_id != ref.product_id
                or not source.start < spec.period.trading_start
                or not spec.period.replay_end <= source.end
            ):
                raise ValueError("resolved dataset identity/product/period mismatch")
            verified = CanonicalCandleDataset(
                product_id=source.product_id,
                start=source.start,
                end=source.end,
                as_of=source.as_of,
                candles=source.candles,
                gaps=source.gaps,
                source_pages=source.source_pages,
                product_spec_provenance=source.product_spec_provenance,
            )
            if verified != source:
                raise ValueError("resolved dataset logical content failed integrity verification")
            product = products[ref.product_id]
            product_provenance = source.product_spec_provenance
            if (
                product_provenance is not None
                and product_provenance.fingerprint != product.fingerprint
            ):
                raise ValueError("dataset ProductSpec provenance differs from account authority")
            sources.append(source)
            identities.append(
                DatasetProvenance(
                    ref.product_id,
                    source.version,
                    source.logical_candle_content_sha256,
                    product_provenance.fingerprint if product_provenance else None,
                    product.fingerprint,
                )
            )
        source_map = {s.product_id: s for s in sources}
        derived = tuple(
            resample_canonical_dataset(source_map[sub.product_id], sub.timeframe)
            for sub in strategy.definition.subscriptions
            if sub.timeframe is not Timeframe.ONE_MINUTE
        )
        feed = HistoricalReplayFeed(sources, derived, replay_end=spec.period.replay_end)
        broker = SimulatedBroker(spec.execution)
        accounting = SpotAccountingEngine(spec.account, feed.start, spec.execution)
        risk = RiskEngine(spec.risk_policy)
        runtime = ReferenceTradingRuntime(
            clock=SimulatedClock(feed.start),
            market_feed=feed,
            broker=broker,
            accounting=accounting,
            risk=risk,
            strategy_runner=runner,
        )
        outcome = runtime.run()
        final = accounting.portfolio_snapshot
        if final is None or final.timestamp != spec.period.replay_end:
            raise ValueError("runtime did not reach final canonical mark")
        trades = derive_closed_lot_trades(
            accounting.lots, accounting.lot_consumptions, broker.fills
        )
        metrics = calculate_metrics(
            accounting.portfolio_history, spec.period, trades, broker.fills, accounting.fees_to_date
        )
        provenance = BacktestProvenance(
            self.engine_identity,
            descriptor,
            descriptor.fingerprint,
            strategy.definition.fingerprint,
            runner.parameters.fingerprint,
            tuple(identities),
            tuple(
                DerivedProvenance(
                    d.product_id,
                    d.target_timeframe,
                    d.cache_key.value,
                    d.source_dataset_version,
                    d.resampler_version,
                    derived_result_hash(d),
                )
                for d in derived
            ),
            spec.account.fingerprint,
            spec.risk_policy.fingerprint,
            spec.execution.fingerprint,
            spec.random_seed,
            outcome.trace_fingerprint,
            broker.execution_fingerprint,
            accounting.accounting_fingerprint,
            risk.risk_fingerprint,
            runner.fingerprint,
        )
        result = BacktestResult(
            BacktestRunId.derive(spec, self.engine_identity),
            spec.fingerprint,
            provenance,
            metrics,
            RiskSummary.derive(risk.decisions),
            ExecutionSummary.derive(broker.orders, broker.fills),
            accounting.account_view,
            accounting.positions,
            final,
            accounting.reservations,
            "",
        )
        result = replace(result, result_fingerprint=fingerprint(result.to_dict()))
        summary = {**result.to_dict(), "result_fingerprint": result.result_fingerprint}
        manifest = self.artifacts.publish(
            result.run_id,
            result.result_fingerprint,
            spec.to_dict(),
            summary,
            {
                "orders.parquet": broker.orders,
                "fills.parquet": broker.fills,
                "trades.parquet": trades,
                "equity.parquet": analytics_window(accounting.portfolio_history, spec.period),
                "risk_decisions.parquet": risk.decisions,
                "strategy_actions.parquet": runner.action_results,
            },
        )
        return replace(result, artifact_manifest=manifest)
