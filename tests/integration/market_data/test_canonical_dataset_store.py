import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.datasets import (
    CanonicalCandleDataset,
    CanonicalDatasetIntegrityError,
    GapReason,
    GapRecord,
    SourcePageReference,
    canonical_json,
)
from command_station.market_data.parquet_store import LocalCanonicalDatasetStore


def instant(day: int, minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2024, 1, day, tzinfo=UTC) + timedelta(minutes=minute))


def item(product_id: ProductId, time: UtcTimestamp, close: str) -> Candle:
    return Candle(
        product_id,
        Timeframe.ONE_MINUTE,
        time,
        UtcTimestamp(time.value + timedelta(minutes=1)),
        "1.00",
        close,
        "1.00",
        close,
        "0.000",
    )


def dataset() -> CanonicalCandleDataset:
    start = UtcTimestamp(datetime(2024, 1, 31, 23, 59, tzinfo=UTC))
    product_id = ProductId("../../opaque")
    return CanonicalCandleDataset(
        product_id=product_id,
        start=start,
        end=UtcTimestamp(start.value + timedelta(minutes=2)),
        as_of=UtcTimestamp(start.value + timedelta(minutes=3)),
        candles=(
            item(product_id, start, "1.2300"),
            item(product_id, UtcTimestamp(start.value + timedelta(minutes=1)), "2.3400"),
        ),
        gaps=(),
        source_pages=(SourcePageReference("a" * 64, "b" * 64),),
    )


def test_publish_load_partition_idempotence_and_corruption(tmp_path: Path) -> None:
    value, store = dataset(), LocalCanonicalDatasetStore(tmp_path.resolve())
    manifest = store.publish(value)
    assert store.publish(value) == manifest
    assert store.load(value.version) == value
    artifacts = manifest["parquet_artifacts"]
    assert isinstance(artifacts, list) and len(artifacts) == 2
    assert "../../opaque" not in str(tmp_path)
    artifact = (
        tmp_path / "coinbase" / "spot" / "1m" / value.version.value / artifacts[0]["relative_path"]
    )
    artifact.write_bytes(b"tampered")
    with pytest.raises(CanonicalDatasetIntegrityError):
        store.load(value.version)
    with pytest.raises(CanonicalDatasetIntegrityError):
        store.load_manifest(value.version)


def test_utc_arrow_read_back_does_not_require_timezone_name_materialization(tmp_path: Path) -> None:
    """Regression for PyArrow 25/Python 3.14 Windows UTC scalar conversion."""
    value = dataset()
    store = LocalCanonicalDatasetStore(tmp_path.resolve())
    store.publish(value)
    assert store.load(value.version).candles == value.candles


def test_empty_incomplete_dataset_has_no_fake_parquet(tmp_path: Path) -> None:
    start = instant(1, 0)
    value = CanonicalCandleDataset(
        product_id=ProductId("BTC-USD"),
        start=start,
        end=instant(1, 2),
        as_of=instant(1, 3),
        candles=(),
        gaps=(
            GapRecord(start, GapReason.MISSING_SOURCE),
            GapRecord(instant(1, 1), GapReason.MISSING_SOURCE),
        ),
        source_pages=(SourcePageReference("a" * 64, "b" * 64),),
    )
    manifest = LocalCanonicalDatasetStore(tmp_path.resolve()).publish(value)
    assert manifest["parquet_artifacts"] == []


def test_symlinked_staging_directory_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    try:
        (tmp_path / ".staging").symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks unsupported in this environment: {error}")
    with pytest.raises(CanonicalDatasetIntegrityError):
        LocalCanonicalDatasetStore(tmp_path.resolve()).publish(dataset())


def test_manifest_rejects_extra_fields_and_reordered_artifacts(tmp_path: Path) -> None:
    value = dataset()
    store = LocalCanonicalDatasetStore(tmp_path.resolve())
    store.publish(value)
    path = tmp_path / "coinbase" / "spot" / "1m" / value.version.value / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["unexpected"] = "claim"
    path.write_bytes(canonical_json(manifest))
    with pytest.raises(CanonicalDatasetIntegrityError):
        store.load_manifest(value.version)
    manifest.pop("unexpected")
    artifacts = manifest["parquet_artifacts"]
    assert isinstance(artifacts, list)
    manifest["parquet_artifacts"] = list(reversed(artifacts))
    path.write_bytes(canonical_json(manifest))
    with pytest.raises(CanonicalDatasetIntegrityError):
        store.load_manifest(value.version)


def test_manifest_rejects_boolean_schema_version(tmp_path: Path) -> None:
    value = dataset()
    store = LocalCanonicalDatasetStore(tmp_path.resolve())
    store.publish(value)
    path = tmp_path / "coinbase" / "spot" / "1m" / value.version.value / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["manifest_schema_version"] = True
    path.write_bytes(canonical_json(manifest))
    with pytest.raises(CanonicalDatasetIntegrityError):
        store.load_manifest(value.version)


def test_external_manifest_symlink_is_rejected_where_supported(tmp_path: Path) -> None:
    value = dataset()
    store = LocalCanonicalDatasetStore(tmp_path.resolve())
    store.publish(value)
    path = tmp_path / "coinbase" / "spot" / "1m" / value.version.value / "manifest.json"
    external = tmp_path / "external.json"
    external.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(external)
    except OSError as error:
        pytest.skip(f"symlinks unsupported in this environment: {error}")
    with pytest.raises(CanonicalDatasetIntegrityError):
        store.load_manifest(value.version)
