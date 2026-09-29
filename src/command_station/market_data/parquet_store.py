"""Safe local Parquet publication for immutable canonical datasets."""

import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp, decimal_to_text
from command_station.market_data.datasets import (
    CANONICAL_DATASET_SCHEMA_VERSION,
    CANONICAL_MANIFEST_SCHEMA_VERSION,
    CANONICALIZATION_SCHEMA_VERSION,
    CanonicalCandleDataset,
    CanonicalDatasetIntegrityError,
    CanonicalDatasetValidationError,
    DatasetVersion,
    GapReason,
    GapRecord,
    ParquetArtifact,
    ProductSpecProvenance,
    SourcePageReference,
    canonical_json,
)

CANONICAL_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("product_id", pa.string(), nullable=False),
        pa.field("timeframe", pa.string(), nullable=False),
        pa.field("open_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("close_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("open", pa.string(), nullable=False),
        pa.field("high", pa.string(), nullable=False),
        pa.field("low", pa.string(), nullable=False),
        pa.field("close", pa.string(), nullable=False),
        pa.field("volume", pa.string(), nullable=False),
    ]
)


class LocalCanonicalDatasetStore:
    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise CanonicalDatasetValidationError(
                "canonical store root must be an explicit absolute Path"
            )
        self._configured_root = root
        self._root = root.resolve()

    def publish(self, dataset: CanonicalCandleDataset) -> dict[str, object]:
        if not isinstance(dataset, CanonicalCandleDataset):
            raise CanonicalDatasetValidationError(
                "canonical store only publishes canonical datasets"
            )
        final = self._dataset_path(dataset.version)
        if final.exists():
            loaded = self.load(dataset.version)
            if loaded != dataset:
                raise CanonicalDatasetIntegrityError(
                    "existing dataset version has incompatible content"
                )
            return self.load_manifest(dataset.version)
        self._prepare_root()
        staging_parent = self._root / ".staging"
        _safe_mkdir(self._root, staging_parent)
        staging = Path(tempfile.mkdtemp(prefix="dataset-", dir=staging_parent))
        _inside(self._root, staging)
        try:
            artifacts = self._write_staging(staging, dataset)
            manifest = _manifest_data(dataset, artifacts)
            (staging / "manifest.json").write_bytes(canonical_json(manifest))
            self._verify_directory(staging, dataset.version)
            _safe_mkdir(self._root, final.parent)
            if final.exists():
                raise CanonicalDatasetIntegrityError("dataset version appeared during publication")
            staging.replace(final)
            return manifest
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def load_manifest(self, version: DatasetVersion) -> dict[str, object]:
        self._prepare_root()
        directory = self._dataset_path(version)
        self._verify_directory(directory, version)
        return self._read_manifest(directory, version)

    def load(self, version: DatasetVersion) -> CanonicalCandleDataset:
        self._prepare_root()
        return self._verify_directory(self._dataset_path(version), version)

    def _dataset_path(self, version: DatasetVersion) -> Path:
        if not isinstance(version, DatasetVersion):
            raise CanonicalDatasetValidationError("invalid dataset version")
        path = self._root / "coinbase" / "spot" / "1m" / version.value
        _inside(self._root, path)
        return path

    def _prepare_root(self) -> None:
        self._configured_root.mkdir(parents=True, exist_ok=True)
        if self._configured_root.is_symlink() or self._configured_root.resolve() != self._root:
            raise CanonicalDatasetIntegrityError("canonical store root must not be a symlink")
        _inside(self._root, self._root)

    def _write_staging(
        self, staging: Path, dataset: CanonicalCandleDataset
    ) -> tuple[ParquetArtifact, ...]:
        groups: dict[tuple[int, int], list[Candle]] = {}
        for candle in dataset.candles:
            key = (candle.open_time.value.year, candle.open_time.value.month)
            groups.setdefault(key, []).append(candle)
        artifacts: list[ParquetArtifact] = []
        for (year, month), candles in sorted(groups.items()):
            relative = f"year={year:04d}/month={month:02d}/part-00000.parquet"
            path = staging / relative
            _inside(staging, path)
            _safe_mkdir(staging, path.parent)
            table = _table(candles)
            pq.write_table(table, path, compression="zstd", version="2.6", write_statistics=True)
            artifacts.append(
                ParquetArtifact(
                    relative,
                    len(candles),
                    candles[0].open_time,
                    candles[-1].open_time,
                    path.stat().st_size,
                    _file_sha256(path),
                )
            )
        return tuple(artifacts)

    def _read_manifest(self, directory: Path, version: DatasetVersion) -> dict[str, object]:
        _inside(self._root, directory)
        if directory.is_symlink():
            raise CanonicalDatasetIntegrityError(
                "canonical dataset directory must not be a symlink"
            )
        path = directory / "manifest.json"
        _inside(directory, path)
        if path.is_symlink():
            raise CanonicalDatasetIntegrityError("canonical manifest must not be a symlink")
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
        except (OSError, json.JSONDecodeError) as error:
            raise CanonicalDatasetIntegrityError(
                "canonical manifest is missing or corrupt"
            ) from error
        if not isinstance(value, dict) or canonical_json(value) != raw:
            raise CanonicalDatasetIntegrityError("canonical manifest encoding is invalid")
        if value.get("dataset_version") != version.value:
            raise CanonicalDatasetIntegrityError(
                "manifest version does not match requested dataset"
            )
        return cast(dict[str, object], value)

    def _verify_directory(self, directory: Path, version: DatasetVersion) -> CanonicalCandleDataset:
        manifest = self._read_manifest(directory, version)
        _validate_manifest_basics(manifest)
        artifacts_data = manifest["parquet_artifacts"]
        assert isinstance(artifacts_data, list)
        artifacts = tuple(_artifact_from_data(value) for value in artifacts_data)
        expected_artifacts = tuple(sorted(artifacts, key=lambda artifact: artifact.relative_path))
        if artifacts != expected_artifacts:
            raise CanonicalDatasetIntegrityError("manifest artifacts are not in canonical order")
        candles: list[Candle] = []
        for artifact in artifacts:
            path = directory / artifact.relative_path
            _inside(directory, path)
            if not path.is_file() or path.stat().st_size != artifact.byte_size:
                raise CanonicalDatasetIntegrityError(
                    "canonical Parquet artifact is missing or changed"
                )
            if _file_sha256(path) != artifact.sha256:
                raise CanonicalDatasetIntegrityError("canonical Parquet artifact hash mismatch")
            candles.extend(_read_artifact(path, artifact))
        gaps = tuple(_gap_from_data(value) for value in _required_list(manifest, "gaps"))
        pages = tuple(_page_from_data(value) for value in _required_list(manifest, "source_pages"))
        provenance = _provenance_from_data(manifest.get("product_spec_provenance"))
        dataset = CanonicalCandleDataset(
            product_id=ProductId(_required_text(manifest, "product_id")),
            start=UtcTimestamp.parse(_required_text(manifest, "start")),
            end=UtcTimestamp.parse(_required_text(manifest, "end")),
            as_of=UtcTimestamp.parse(_required_text(manifest, "as_of")),
            candles=candles,
            gaps=gaps,
            source_pages=pages,
            product_spec_provenance=provenance,
        )
        if (
            dataset.version != version
            or manifest.get("logical_candle_content_sha256")
            != dataset.logical_candle_content_sha256
        ):
            raise CanonicalDatasetIntegrityError("canonical logical identity verification failed")
        if manifest.get("quality") != dataset.quality.value:
            raise CanonicalDatasetIntegrityError("manifest quality is inconsistent")
        expected = _required_int(manifest, "expected_interval_count")
        if (
            expected != len(dataset.candles) + len(dataset.gaps)
            or _required_int(manifest, "row_count") != len(dataset.candles)
            or _required_int(manifest, "gap_count") != len(dataset.gaps)
        ):
            raise CanonicalDatasetIntegrityError("manifest coverage counts are inconsistent")
        if manifest != _manifest_data(dataset, expected_artifacts):
            raise CanonicalDatasetIntegrityError(
                "canonical manifest has unknown or noncanonical content"
            )
        return dataset


def _table(candles: list[Candle]) -> Any:
    return pa.Table.from_pydict(
        {
            "product_id": [candle.product_id.value for candle in candles],
            "timeframe": [candle.timeframe.value for candle in candles],
            "open_time": [candle.open_time.value for candle in candles],
            "close_time": [candle.close_time.value for candle in candles],
            "open": [decimal_to_text(candle.open) for candle in candles],
            "high": [decimal_to_text(candle.high) for candle in candles],
            "low": [decimal_to_text(candle.low) for candle in candles],
            "close": [decimal_to_text(candle.close) for candle in candles],
            "volume": [decimal_to_text(candle.volume) for candle in candles],
        },
        schema=CANONICAL_PARQUET_SCHEMA,
    )


def _read_artifact(path: Path, artifact: ParquetArtifact) -> list[Candle]:
    table = pq.read_table(path)
    if table.schema != CANONICAL_PARQUET_SCHEMA:
        raise CanonicalDatasetIntegrityError("canonical Parquet schema is incompatible")
    columns = {
        name: table[name].to_pylist()
        for name in ("product_id", "timeframe", "open", "high", "low", "close", "volume")
    }
    # PyArrow 25 on Python 3.14 Windows may require an unavailable timezone-name
    # package to materialize timestamp scalars. The validated physical schema
    # already proves UTC; casting Arrow-native values to exact epoch microseconds
    # preserves that instant without invoking timezone-name materialization.
    open_microseconds = pc.cast(table["open_time"], pa.int64()).to_pylist()
    close_microseconds = pc.cast(table["close_time"], pa.int64()).to_pylist()
    rows: list[Candle] = []
    for index in range(table.num_rows):
        values = {name: columns[name][index] for name in columns}
        if any(value is None for value in values.values()) or not all(
            isinstance(values[name], str)
            for name in ("product_id", "timeframe", "open", "high", "low", "close", "volume")
        ):
            raise CanonicalDatasetIntegrityError(
                "canonical Parquet row has invalid null or text values"
            )
        open_time, close_time = open_microseconds[index], close_microseconds[index]
        if type(open_time) is not int or type(close_time) is not int:
            raise CanonicalDatasetIntegrityError("canonical Parquet timestamps are invalid")
        try:
            candle = Candle(
                ProductId(cast(str, values["product_id"])),
                Timeframe.parse(cast(str, values["timeframe"])),
                _utc_from_epoch_microseconds(open_time),
                _utc_from_epoch_microseconds(close_time),
                cast(str, values["open"]),
                cast(str, values["high"]),
                cast(str, values["low"]),
                cast(str, values["close"]),
                cast(str, values["volume"]),
            )
        except Exception as error:
            raise CanonicalDatasetIntegrityError(
                "canonical Parquet row cannot reconstruct Candle"
            ) from error
        if candle.open_time.value.year != int(
            artifact.relative_path[5:9]
        ) or candle.open_time.value.month != int(artifact.relative_path[16:18]):
            raise CanonicalDatasetIntegrityError("Parquet row does not match partition path")
        rows.append(candle)
    if (
        len(rows) != artifact.row_count
        or not rows
        or rows[0].open_time != artifact.first_open_time
        or rows[-1].open_time != artifact.last_open_time
    ):
        raise CanonicalDatasetIntegrityError("Parquet artifact row range is inconsistent")
    return rows


def _utc_from_epoch_microseconds(value: int) -> UtcTimestamp:
    try:
        return UtcTimestamp(datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value))
    except OverflowError as error:
        raise CanonicalDatasetIntegrityError(
            "canonical Parquet timestamp is out of range"
        ) from error


def _manifest_data(
    dataset: CanonicalCandleDataset, artifacts: tuple[ParquetArtifact, ...]
) -> dict[str, object]:
    expected = int((dataset.end.value - dataset.start.value).total_seconds() // 60)
    return {
        "manifest_schema_version": CANONICAL_MANIFEST_SCHEMA_VERSION,
        "dataset_schema_version": CANONICAL_DATASET_SCHEMA_VERSION,
        "canonicalization_schema_version": CANONICALIZATION_SCHEMA_VERSION,
        "dataset_version": dataset.version.value,
        "venue": dataset.venue.value,
        "product_type": dataset.product_type.value,
        "product_id": dataset.product_id.value,
        "timeframe": dataset.timeframe.value,
        "start": str(dataset.start),
        "end": str(dataset.end),
        "as_of": str(dataset.as_of),
        "quality": dataset.quality.value,
        "row_count": len(dataset.candles),
        "expected_interval_count": expected,
        "gap_count": len(dataset.gaps),
        "logical_candle_content_sha256": dataset.logical_candle_content_sha256,
        "gaps": [
            {"open_time": str(gap.open_time), "reason": gap.reason.value} for gap in dataset.gaps
        ],
        "source_pages": [
            {"request_id": page.request_id, "payload_sha256": page.payload_sha256}
            for page in dataset.source_pages
        ],
        "product_spec_provenance": (
            None
            if dataset.product_spec_provenance is None
            else {
                "fingerprint": dataset.product_spec_provenance.fingerprint,
                "observed_at": str(dataset.product_spec_provenance.observed_at),
            }
        ),
        "parquet_artifacts": [
            {
                "relative_path": artifact.relative_path,
                "row_count": artifact.row_count,
                "first_open_time": str(artifact.first_open_time),
                "last_open_time": str(artifact.last_open_time),
                "byte_size": artifact.byte_size,
                "sha256": artifact.sha256,
            }
            for artifact in artifacts
        ],
    }


def _validate_manifest_basics(value: dict[str, object]) -> None:
    if (
        not _exact_int(value.get("manifest_schema_version"), CANONICAL_MANIFEST_SCHEMA_VERSION)
        or not _exact_int(value.get("dataset_schema_version"), CANONICAL_DATASET_SCHEMA_VERSION)
        or not _exact_int(
            value.get("canonicalization_schema_version"), CANONICALIZATION_SCHEMA_VERSION
        )
        or value.get("venue") != "coinbase"
        or value.get("product_type") != "SPOT"
        or value.get("timeframe") != "1m"
        or not isinstance(value.get("parquet_artifacts"), list)
    ):
        raise CanonicalDatasetIntegrityError("canonical manifest schema is incompatible")


def _exact_int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _artifact_from_data(value: object) -> ParquetArtifact:
    if not isinstance(value, dict):
        raise CanonicalDatasetIntegrityError("manifest artifact is invalid")
    try:
        return ParquetArtifact(
            _required_text(value, "relative_path"),
            _required_int(value, "row_count"),
            UtcTimestamp.parse(_required_text(value, "first_open_time")),
            UtcTimestamp.parse(_required_text(value, "last_open_time")),
            _required_int(value, "byte_size"),
            _required_text(value, "sha256"),
        )
    except Exception as error:
        raise CanonicalDatasetIntegrityError("manifest artifact is invalid") from error


def _gap_from_data(value: object) -> GapRecord:
    if not isinstance(value, dict):
        raise CanonicalDatasetIntegrityError("manifest gap is invalid")
    try:
        return GapRecord(
            UtcTimestamp.parse(_required_text(value, "open_time")),
            GapReason(_required_text(value, "reason")),
        )
    except Exception as error:
        raise CanonicalDatasetIntegrityError("manifest gap is invalid") from error


def _page_from_data(value: object) -> SourcePageReference:
    if not isinstance(value, dict):
        raise CanonicalDatasetIntegrityError("manifest source evidence is invalid")
    try:
        return SourcePageReference(
            _required_text(value, "request_id"), _required_text(value, "payload_sha256")
        )
    except Exception as error:
        raise CanonicalDatasetIntegrityError("manifest source evidence is invalid") from error


def _provenance_from_data(value: object) -> ProductSpecProvenance | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CanonicalDatasetIntegrityError("manifest product provenance is invalid")
    try:
        return ProductSpecProvenance(
            _required_text(value, "fingerprint"),
            UtcTimestamp.parse(_required_text(value, "observed_at")),
        )
    except Exception as error:
        raise CanonicalDatasetIntegrityError("manifest product provenance is invalid") from error


def _required_text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise CanonicalDatasetIntegrityError(f"manifest {key} is invalid")
    return item


def _required_int(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if type(item) is not int:
        raise CanonicalDatasetIntegrityError(f"manifest {key} is invalid")
    return item


def _required_list(value: dict[str, object], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list):
        raise CanonicalDatasetIntegrityError(f"manifest {key} is invalid")
    return cast(list[object], item)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(root: Path, candidate: Path) -> None:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise CanonicalDatasetIntegrityError("canonical path escapes configured root") from error


def _safe_mkdir(root: Path, directory: Path) -> None:
    try:
        relative = directory.relative_to(root)
    except ValueError as error:
        raise CanonicalDatasetIntegrityError(
            "canonical directory escapes configured root"
        ) from error
    current = root
    for segment in relative.parts:
        current = current / segment
        if current.exists() and current.is_symlink():
            raise CanonicalDatasetIntegrityError("canonical directory must not traverse a symlink")
        current.mkdir(exist_ok=True)
        _inside(root, current)
