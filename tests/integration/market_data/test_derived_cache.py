import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.datasets import (
    CanonicalCandleDataset,
    GapReason,
    GapRecord,
    SourcePageReference,
    canonical_json,
)
from command_station.market_data.derived_cache import (
    DERIVED_PARQUET_SCHEMA,
    DerivedCacheIntegrityError,
    LocalDerivedCandleCache,
)
from command_station.market_data.resampling import (
    ResampledCandleDataset,
    logical_bar_content_hash,
    logical_gap_content_hash,
    resample_canonical_dataset,
)

PAGES = (SourcePageReference("a" * 64, "b" * 64),)


def result_hash(value: ResampledCandleDataset, bar_hash: str, gap_hash: str) -> str:
    """Rebuild the manifest's derived-result hash without constructing invalid data."""
    derived = value
    return sha256(
        canonical_json(
            {
                "derived_result_schema_version": 1,
                "source_dataset_version": derived.source_dataset_version.value,
                "target_timeframe": derived.target_timeframe.value,
                "resampler_version": derived.resampler_version,
                "eligible_bucket_count": derived.eligible_bucket_count,
                "excluded_edge_minute_count": derived.excluded_edge_minute_count,
                "quality": derived.quality.value,
                "logical_bar_content_sha256": bar_hash,
                "logical_gap_content_sha256": gap_hash,
            }
        )
    ).hexdigest()


def source(start: datetime, count: int, gaps: tuple[int, ...] = ()) -> CanonicalCandleDataset:
    product = ProductId("../../not-a-path")
    values = tuple(UtcTimestamp(start + timedelta(minutes=index)) for index in range(count + 1))
    missing = set(gaps)
    return CanonicalCandleDataset(
        product_id=product,
        start=values[0],
        end=values[-1],
        as_of=UtcTimestamp(values[-1].value + timedelta(minutes=1)),
        candles=(
            Candle(
                product,
                Timeframe.ONE_MINUTE,
                values[index],
                values[index + 1],
                "1",
                "2",
                "1",
                "1",
                "1.25",
            )
            for index in range(count)
            if index not in missing
        ),
        gaps=(GapRecord(values[index], GapReason.MISSING_SOURCE) for index in gaps),
        source_pages=PAGES,
    )


def test_publish_load_idempotence_empty_gaps_and_partitions(tmp_path: Path) -> None:
    cache = LocalDerivedCandleCache(tmp_path.resolve())
    value = resample_canonical_dataset(
        source(datetime(2024, 1, 31, 23, 50, tzinfo=UTC), 20, (12,)), Timeframe.FIVE_MINUTES
    )
    manifest = cache.publish(value)
    assert cache.publish(value) == manifest and cache.load(value.cache_key) == value
    assert manifest["derived_gap_count"] == 1
    artifacts = manifest["parquet_artifacts"]
    assert isinstance(artifacts, list)
    assert [item["relative_path"] for item in artifacts if isinstance(item, dict)] == [
        "year=2024/month=01/part-00000.parquet",
        "year=2024/month=02/part-00000.parquet",
    ]
    assert [str(bar.open_time) for bar in value.bars] == [
        "2024-01-31T23:50:00Z",
        "2024-01-31T23:55:00Z",
        "2024-02-01T00:05:00Z",
    ]
    assert "not-a-path" not in str(tmp_path / "coinbase" / "spot" / "5m" / value.cache_key.value)
    empty = resample_canonical_dataset(
        source(datetime(2024, 1, 1, 0, 1, tzinfo=UTC), 3), Timeframe.FIVE_MINUTES
    )
    empty_manifest = cache.publish(empty)
    assert empty_manifest["parquet_artifacts"] == [] and cache.load(empty.cache_key) == empty


def test_corrupt_and_incompatible_cache_fail_loudly(tmp_path: Path) -> None:
    cache = LocalDerivedCandleCache(tmp_path.resolve())
    value = resample_canonical_dataset(
        source(datetime(2024, 1, 1, tzinfo=UTC), 5), Timeframe.FIVE_MINUTES
    )
    manifest = cache.publish(value)
    artifacts = manifest["parquet_artifacts"]
    assert isinstance(artifacts, list) and artifacts
    artifact = artifacts[0]
    assert isinstance(artifact, dict)
    relative_path = artifact["relative_path"]
    assert isinstance(relative_path, str)
    path = tmp_path / "coinbase" / "spot" / "5m" / value.cache_key.value / relative_path
    path.write_bytes(b"tampered")
    with pytest.raises(DerivedCacheIntegrityError):
        cache.load(value.cache_key)


def test_load_rejects_self_consistent_omitted_eligible_bucket(tmp_path: Path) -> None:
    """A forged cache cannot omit a planned bucket while retaining valid hashes."""
    cache = LocalDerivedCandleCache(tmp_path.resolve())
    value = resample_canonical_dataset(
        source(datetime(2024, 1, 1, tzinfo=UTC), 15), Timeframe.FIVE_MINUTES
    )
    manifest = cache.publish(value)
    artifact_data = manifest["parquet_artifacts"]
    assert isinstance(artifact_data, list) and len(artifact_data) == 1
    artifact = artifact_data[0]
    assert isinstance(artifact, dict)
    relative_path = artifact["relative_path"]
    assert isinstance(relative_path, str)
    directory = tmp_path / "coinbase" / "spot" / "5m" / value.cache_key.value
    path = directory / relative_path
    table = pq.read_table(path).take(pa.array([0, 2]))
    pq.write_table(table.cast(DERIVED_PARQUET_SCHEMA), path, compression="zstd", version="2.6")
    remaining = (value.bars[0], value.bars[2])
    bar_hash = logical_bar_content_hash(remaining)
    artifact["row_count"] = 2
    artifact["last_open_time"] = str(remaining[-1].open_time)
    artifact["byte_size"] = path.stat().st_size
    artifact["sha256"] = sha256(path.read_bytes()).hexdigest()
    manifest["logical_bar_content_sha256"] = bar_hash
    manifest["eligible_bucket_count"] = 2
    manifest["excluded_edge_minute_count"] = value.excluded_edge_minute_count
    manifest["derived_result_sha256"] = result_hash(
        value, bar_hash, value.logical_gap_content_sha256
    )
    (directory / "manifest.json").write_bytes(canonical_json(manifest))
    with pytest.raises(DerivedCacheIntegrityError, match="cannot reconstruct valid data"):
        cache.load(value.cache_key)


def test_load_rejects_self_consistent_misaligned_derived_gap(tmp_path: Path) -> None:
    cache = LocalDerivedCandleCache(tmp_path.resolve())
    value = resample_canonical_dataset(
        source(datetime(2024, 1, 1, tzinfo=UTC), 10, (2,)), Timeframe.FIVE_MINUTES
    )
    manifest = cache.publish(value)
    directory = tmp_path / "coinbase" / "spot" / "5m" / value.cache_key.value
    forged_gap = {
        "open_time": "2024-01-01T00:01:00Z",
        "close_time": "2024-01-01T00:06:00Z",
        "reason": "MISSING_SOURCE",
        "source_gap_open_times": ["2024-01-01T00:02:00Z"],
    }
    manifest["derived_gaps"] = [forged_gap]
    forged_gaps = value.gaps[0].__class__(
        UtcTimestamp.parse(cast(str, forged_gap["open_time"])),
        UtcTimestamp.parse(cast(str, forged_gap["close_time"])),
        GapReason.MISSING_SOURCE,
        (UtcTimestamp.parse(forged_gap["source_gap_open_times"][0]),),
    )
    gap_hash = logical_gap_content_hash((forged_gaps,))
    manifest["logical_gap_content_sha256"] = gap_hash
    # The result hash is also recomputed: failure must be coverage/alignment, not a stale hash.
    manifest["derived_result_sha256"] = result_hash(
        value, value.logical_bar_content_sha256, gap_hash
    )
    (directory / "manifest.json").write_bytes(canonical_json(manifest))
    with pytest.raises(DerivedCacheIntegrityError, match="cannot reconstruct valid data"):
        cache.load(value.cache_key)


def test_manifest_incompatibility_and_staging_symlink_are_rejected(tmp_path: Path) -> None:
    cache = LocalDerivedCandleCache(tmp_path.resolve())
    value = resample_canonical_dataset(
        source(datetime(2024, 1, 1, tzinfo=UTC), 5), Timeframe.FIVE_MINUTES
    )
    cache.publish(value)
    directory = tmp_path / "coinbase" / "spot" / "5m" / value.cache_key.value
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["resampler_version"] = 2
    manifest_path.write_bytes(canonical_json(manifest))
    with pytest.raises(DerivedCacheIntegrityError):
        cache.load(value.cache_key)
    safe_root = tmp_path / "symlink-cache"
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (safe_root / ".staging").parent.mkdir()
        (safe_root / ".staging").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks unsupported in this environment: {error}")
    another = resample_canonical_dataset(
        source(datetime(2024, 1, 1, tzinfo=UTC), 15), Timeframe.FIFTEEN_MINUTES
    )
    with pytest.raises(DerivedCacheIntegrityError):
        LocalDerivedCandleCache(safe_root.resolve()).publish(another)
