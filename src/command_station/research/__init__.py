"""Synchronous deterministic backtest application service and research contracts."""

from command_station.research.analytics import (
    BacktestMetrics,
    DrawdownEpisode,
    ProductExposure,
    calculate_metrics,
)
from command_station.research.artifacts import (
    ArtifactManifest,
    BacktestReproducibilityError,
    LocalBacktestArtifactStore,
)
from command_station.research.backtests import BacktestProvenance, BacktestResult, BacktestService
from command_station.research.specs import (
    BacktestDatasetRef,
    BacktestPeriod,
    BacktestRunId,
    BacktestSpec,
    EngineIdentity,
    StrategyArtifactRef,
)
from command_station.research.strategy_artifacts import (
    StrategyArtifactCatalog,
    StrategyArtifactDescriptor,
)
from command_station.research.summaries import ExecutionSummary, RiskSummary
from command_station.research.trades import ClosedLotTrade, derive_closed_lot_trades

__all__ = [
    "ArtifactManifest",
    "BacktestDatasetRef",
    "BacktestMetrics",
    "BacktestPeriod",
    "BacktestProvenance",
    "BacktestReproducibilityError",
    "BacktestResult",
    "BacktestRunId",
    "BacktestService",
    "BacktestSpec",
    "ClosedLotTrade",
    "DrawdownEpisode",
    "EngineIdentity",
    "ExecutionSummary",
    "LocalBacktestArtifactStore",
    "ProductExposure",
    "RiskSummary",
    "StrategyArtifactCatalog",
    "StrategyArtifactDescriptor",
    "StrategyArtifactRef",
    "calculate_metrics",
    "derive_closed_lot_trades",
]
