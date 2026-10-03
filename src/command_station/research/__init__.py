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
from command_station.research.batches import BatchBacktestService, WorkerIsolationError
from command_station.research.jobs import (
    BatchBacktestSpec,
    BatchExecutionPolicy,
    BatchJobId,
    BatchRunId,
    BatchView,
    JobState,
    JobView,
)
from command_station.research.spec_codec import SpecCodecError, decode_spec, encode_spec
from command_station.research.specs import (
    BacktestDatasetRef,
    BacktestPeriod,
    BacktestRunId,
    BacktestSpec,
    EngineIdentity,
    StrategyArtifactRef,
)
from command_station.research.store import (
    JobNotCancellableError,
    JobTransitionError,
    LocalResearchStore,
    ResearchStoreError,
    ResultIndexConflictError,
    ResultIndexRecord,
    RunnerLeaseError,
)
from command_station.research.strategy_artifacts import (
    StrategyArtifactCatalog,
    StrategyArtifactDescriptor,
)
from command_station.research.summaries import ExecutionSummary, RiskSummary
from command_station.research.trades import ClosedLotTrade, derive_closed_lot_trades

__all__ = [
    "BatchBacktestService",
    "BatchBacktestSpec",
    "BatchExecutionPolicy",
    "BatchJobId",
    "BatchRunId",
    "BatchView",
    "JobNotCancellableError",
    "JobState",
    "JobTransitionError",
    "JobView",
    "LocalResearchStore",
    "ResearchStoreError",
    "ResultIndexConflictError",
    "ResultIndexRecord",
    "RunnerLeaseError",
    "SpecCodecError",
    "WorkerIsolationError",
    "decode_spec",
    "encode_spec",
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
