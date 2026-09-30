"""Market-data infrastructure boundaries."""

from command_station.market_data.derived_cache import (
    DERIVED_CACHE_SCHEMA_VERSION,
    DerivedCacheIntegrityError,
    LocalDerivedCandleCache,
)
from command_station.market_data.replay import (
    BarReference,
    HistoricalReplayFeed,
    MarketReplayBatch,
    MarketStreamKey,
    ReplayDataError,
)
from command_station.market_data.resampling import (
    RESAMPLER_VERSION,
    DerivedCacheKey,
    DerivedDatasetError,
    DerivedDatasetValidationError,
    DerivedGapRecord,
    ResampleBucket,
    ResampledCandleDataset,
    derive_cache_key,
    plan_resample_buckets,
    resample_canonical_dataset,
)

__all__ = [
    "DERIVED_CACHE_SCHEMA_VERSION",
    "BarReference",
    "RESAMPLER_VERSION",
    "DerivedCacheIntegrityError",
    "DerivedCacheKey",
    "DerivedDatasetError",
    "DerivedDatasetValidationError",
    "DerivedGapRecord",
    "LocalDerivedCandleCache",
    "HistoricalReplayFeed",
    "MarketReplayBatch",
    "MarketStreamKey",
    "ReplayDataError",
    "ResampleBucket",
    "ResampledCandleDataset",
    "derive_cache_key",
    "plan_resample_buckets",
    "resample_canonical_dataset",
]
