"""Immutable, verified local cache for deterministic derived candle datasets."""

from __future__ import annotations

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

from command_station.domain import (
    Candle,
    ProductId,
    ProductType,
    Timeframe,
    UtcTimestamp,
    Venue,
    decimal_to_text,
)
from command_station.market_data.datasets import (
    CanonicalDatasetIntegrityError,
    DatasetQuality,
    DatasetVersion,
    GapReason,
    ParquetArtifact,
    canonical_json,
)
from command_station.market_data.resampling import (
    DERIVED_CACHE_KEY_SCHEMA_VERSION,
    DERIVED_RESULT_SCHEMA_VERSION,
    RESAMPLER_VERSION,
    DerivedCacheKey,
    DerivedDatasetValidationError,
    DerivedGapRecord,
    ResampledCandleDataset,
    derive_cache_key,
)

DERIVED_CACHE_MANIFEST_SCHEMA_VERSION = 1
DERIVED_CACHE_SCHEMA_VERSION = 1
DERIVED_PARQUET_SCHEMA = pa.schema(
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


class DerivedCacheIntegrityError(CanonicalDatasetIntegrityError):
    pass


class LocalDerivedCandleCache:
    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise DerivedDatasetValidationError(
                "derived cache root must be an explicit absolute Path"
            )
        self._configured_root, self._root = root, root.resolve()

    def publish(self, derived: ResampledCandleDataset) -> dict[str, object]:
        if not isinstance(derived, ResampledCandleDataset):
            raise DerivedDatasetValidationError("derived cache only publishes resampled datasets")
        final = self._cache_path(derived.cache_key, derived.target_timeframe)
        if final.exists():
            if self.load(derived.cache_key) != derived:
                raise DerivedCacheIntegrityError("existing derived cache has incompatible content")
            return self.load_manifest(derived.cache_key)
        self._prepare_root()
        staging_parent = self._root / ".staging"
        _safe_mkdir(self._root, staging_parent)
        staging = Path(tempfile.mkdtemp(prefix="derived-", dir=staging_parent))
        _inside(self._root, staging)
        try:
            artifacts = self._write_staging(staging, derived)
            manifest = _manifest_data(derived, artifacts)
            (staging / "manifest.json").write_bytes(canonical_json(manifest))
            self._verify_directory(staging, derived.cache_key, derived.target_timeframe)
            _safe_mkdir(self._root, final.parent)
            if final.exists():
                raise DerivedCacheIntegrityError("derived cache appeared during publication")
            staging.replace(final)
            return manifest
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def load_manifest(self, key: DerivedCacheKey) -> dict[str, object]:
        self._prepare_root()
        directory = self._find_key_directory(key)
        self._verify_directory(directory, key, _timeframe_from_directory(directory))
        return self._read_manifest(directory, key)

    def load(self, key: DerivedCacheKey) -> ResampledCandleDataset:
        self._prepare_root()
        directory = self._find_key_directory(key)
        return self._verify_directory(directory, key, _timeframe_from_directory(directory))

    def _find_key_directory(self, key: DerivedCacheKey) -> Path:
        if not isinstance(key, DerivedCacheKey):
            raise DerivedDatasetValidationError("invalid derived cache key")
        base = self._root / "coinbase" / "spot"
        _inside(self._root, base)
        if not base.is_dir() or base.is_symlink():
            raise DerivedCacheIntegrityError("derived cache key is unavailable")
        matches = tuple(
            path
            for path in base.iterdir()
            if path.is_dir()
            and not path.is_symlink()
            and path.name
            in {value.value for value in Timeframe if value is not Timeframe.ONE_MINUTE}
            and (path / key.value).exists()
        )
        if len(matches) != 1:
            raise DerivedCacheIntegrityError("derived cache key is unavailable or ambiguous")
        result = matches[0] / key.value
        _inside(self._root, result)
        return result

    def _cache_path(self, key: DerivedCacheKey, timeframe: Timeframe) -> Path:
        if (
            not isinstance(key, DerivedCacheKey)
            or not isinstance(timeframe, Timeframe)
            or timeframe is Timeframe.ONE_MINUTE
        ):
            raise DerivedDatasetValidationError("invalid derived cache identity")
        result = self._root / "coinbase" / "spot" / timeframe.value / key.value
        _inside(self._root, result)
        return result

    def _prepare_root(self) -> None:
        self._configured_root.mkdir(parents=True, exist_ok=True)
        if self._configured_root.is_symlink() or self._configured_root.resolve() != self._root:
            raise DerivedCacheIntegrityError("derived cache root must not be a symlink")
        _inside(self._root, self._root)

    def _write_staging(
        self, staging: Path, derived: ResampledCandleDataset
    ) -> tuple[ParquetArtifact, ...]:
        groups: dict[tuple[int, int], list[Candle]] = {}
        for bar in derived.bars:
            groups.setdefault((bar.open_time.value.year, bar.open_time.value.month), []).append(bar)
        artifacts: list[ParquetArtifact] = []
        for (year, month), bars in sorted(groups.items()):
            relative = f"year={year:04d}/month={month:02d}/part-00000.parquet"
            path = staging / relative
            _inside(staging, path)
            _safe_mkdir(staging, path.parent)
            pq.write_table(
                _table(bars), path, compression="zstd", version="2.6", write_statistics=True
            )
            artifacts.append(
                ParquetArtifact(
                    relative,
                    len(bars),
                    bars[0].open_time,
                    bars[-1].open_time,
                    path.stat().st_size,
                    _file_sha256(path),
                )
            )
        return tuple(artifacts)

    def _read_manifest(self, directory: Path, key: DerivedCacheKey) -> dict[str, object]:
        _inside(self._root, directory)
        if directory.is_symlink():
            raise DerivedCacheIntegrityError("derived cache directory must not be a symlink")
        path = directory / "manifest.json"
        _inside(directory, path)
        if path.is_symlink():
            raise DerivedCacheIntegrityError("derived manifest must not be a symlink")
        try:
            raw, value = path.read_bytes(), json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            raise DerivedCacheIntegrityError("derived manifest is missing or corrupt") from error
        if (
            not isinstance(value, dict)
            or canonical_json(value) != raw
            or value.get("cache_key") != key.value
        ):
            raise DerivedCacheIntegrityError("derived manifest encoding or key is invalid")
        return cast(dict[str, object], value)

    def _verify_directory(
        self, directory: Path, key: DerivedCacheKey, path_timeframe: Timeframe
    ) -> ResampledCandleDataset:
        manifest = self._read_manifest(directory, key)
        _validate_manifest_basics(manifest, path_timeframe)
        timeframe = Timeframe.parse(_text(manifest, "target_timeframe"))
        source_version = DatasetVersion(_text(manifest, "source_dataset_version"))
        version = _integer(manifest, "resampler_version")
        if (
            version != RESAMPLER_VERSION
            or derive_cache_key(source_version, timeframe, version) != key
        ):
            raise DerivedCacheIntegrityError("derived cache identity is incompatible")
        artifacts = tuple(_artifact(value) for value in _list(manifest, "parquet_artifacts"))
        if artifacts != tuple(sorted(artifacts, key=lambda value: value.relative_path)):
            raise DerivedCacheIntegrityError("derived artifacts are not in canonical order")
        bars: list[Candle] = []
        for artifact in artifacts:
            path = directory / artifact.relative_path
            _inside(directory, path)
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != artifact.byte_size
                or _file_sha256(path) != artifact.sha256
            ):
                raise DerivedCacheIntegrityError("derived Parquet artifact is missing or changed")
            bars.extend(_read_artifact(path, artifact, timeframe))
        gaps = tuple(_gap(value) for value in _list(manifest, "derived_gaps"))
        try:
            result = ResampledCandleDataset(
                key,
                source_version,
                DatasetQuality(_text(manifest, "source_quality")),
                Venue(_text(manifest, "venue")),
                ProductType(_text(manifest, "product_type")),
                ProductId(_text(manifest, "product_id")),
                timeframe,
                version,
                UtcTimestamp.parse(_text(manifest, "source_start")),
                UtcTimestamp.parse(_text(manifest, "source_end")),
                UtcTimestamp.parse(_text(manifest, "source_as_of")),
                tuple(bars),
                gaps,
                DatasetQuality(_text(manifest, "quality")),
                _integer(manifest, "eligible_bucket_count"),
                _integer(manifest, "excluded_edge_minute_count"),
                _text(manifest, "logical_bar_content_sha256"),
                _text(manifest, "logical_gap_content_sha256"),
                _text(manifest, "derived_result_sha256"),
            )
        except Exception as error:
            raise DerivedCacheIntegrityError(
                "derived manifest cannot reconstruct valid data"
            ) from error
        if manifest != _manifest_data(result, artifacts):
            raise DerivedCacheIntegrityError("derived manifest has unknown or noncanonical content")
        return result


def _table(bars: list[Candle]) -> Any:
    return pa.Table.from_pydict(
        {
            "product_id": [bar.product_id.value for bar in bars],
            "timeframe": [bar.timeframe.value for bar in bars],
            "open_time": [bar.open_time.value for bar in bars],
            "close_time": [bar.close_time.value for bar in bars],
            "open": [decimal_to_text(bar.open) for bar in bars],
            "high": [decimal_to_text(bar.high) for bar in bars],
            "low": [decimal_to_text(bar.low) for bar in bars],
            "close": [decimal_to_text(bar.close) for bar in bars],
            "volume": [decimal_to_text(bar.volume) for bar in bars],
        },
        schema=DERIVED_PARQUET_SCHEMA,
    )


def _read_artifact(path: Path, artifact: ParquetArtifact, timeframe: Timeframe) -> list[Candle]:
    table = pq.read_table(path)
    if table.schema != DERIVED_PARQUET_SCHEMA:
        raise DerivedCacheIntegrityError("derived Parquet schema is incompatible")
    text_columns = {
        name: table[name].to_pylist()
        for name in ("product_id", "timeframe", "open", "high", "low", "close", "volume")
    }
    opens, closes = (
        pc.cast(table["open_time"], pa.int64()).to_pylist(),
        pc.cast(table["close_time"], pa.int64()).to_pylist(),
    )
    rows: list[Candle] = []
    for index in range(table.num_rows):
        values = {name: text_columns[name][index] for name in text_columns}
        if (
            any(value is None for value in values.values())
            or not all(isinstance(value, str) for value in values.values())
            or type(opens[index]) is not int
            or type(closes[index]) is not int
        ):
            raise DerivedCacheIntegrityError("derived Parquet row has invalid values")
        try:
            bar = Candle(
                ProductId(cast(str, values["product_id"])),
                Timeframe.parse(cast(str, values["timeframe"])),
                _timestamp(opens[index]),
                _timestamp(closes[index]),
                cast(str, values["open"]),
                cast(str, values["high"]),
                cast(str, values["low"]),
                cast(str, values["close"]),
                cast(str, values["volume"]),
            )
        except Exception as error:
            raise DerivedCacheIntegrityError(
                "derived Parquet row cannot reconstruct Candle"
            ) from error
        if (
            bar.timeframe is not timeframe
            or bar.open_time.value.year != int(artifact.relative_path[5:9])
            or bar.open_time.value.month != int(artifact.relative_path[16:18])
        ):
            raise DerivedCacheIntegrityError(
                "derived Parquet row mismatches timeframe or partition"
            )
        rows.append(bar)
    if (
        len(rows) != artifact.row_count
        or not rows
        or rows[0].open_time != artifact.first_open_time
        or rows[-1].open_time != artifact.last_open_time
        or tuple(sorted(rows, key=lambda value: value.open_time)) != tuple(rows)
    ):
        raise DerivedCacheIntegrityError("derived artifact row range is inconsistent")
    return rows


def _manifest_data(
    value: ResampledCandleDataset, artifacts: tuple[ParquetArtifact, ...]
) -> dict[str, object]:
    return {
        "manifest_schema_version": DERIVED_CACHE_MANIFEST_SCHEMA_VERSION,
        "derived_cache_schema_version": DERIVED_CACHE_SCHEMA_VERSION,
        "derived_cache_key_schema_version": DERIVED_CACHE_KEY_SCHEMA_VERSION,
        "derived_result_schema_version": DERIVED_RESULT_SCHEMA_VERSION,
        "cache_key": value.cache_key.value,
        "source_dataset_version": value.source_dataset_version.value,
        "source_quality": value.source_quality.value,
        "venue": value.venue.value,
        "product_type": value.product_type.value,
        "product_id": value.product_id.value,
        "target_timeframe": value.target_timeframe.value,
        "resampler_version": value.resampler_version,
        "source_start": str(value.source_start),
        "source_end": str(value.source_end),
        "source_as_of": str(value.source_as_of),
        "source_expected_minute_count": value.source_expected_minute_count,
        "eligible_bucket_count": value.eligible_bucket_count,
        "eligible_source_minute_count": value.eligible_source_minute_count,
        "excluded_edge_minute_count": value.excluded_edge_minute_count,
        "quality": value.quality.value,
        "bar_count": len(value.bars),
        "derived_gap_count": len(value.gaps),
        "logical_bar_content_sha256": value.logical_bar_content_sha256,
        "logical_gap_content_sha256": value.logical_gap_content_sha256,
        "derived_result_sha256": value.derived_result_sha256,
        "derived_gaps": [
            {
                "open_time": str(gap.open_time),
                "close_time": str(gap.close_time),
                "reason": gap.reason.value,
                "source_gap_open_times": [str(moment) for moment in gap.source_gap_open_times],
            }
            for gap in value.gaps
        ],
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


def _validate_manifest_basics(value: dict[str, object], path_timeframe: Timeframe) -> None:
    exact = {
        "manifest_schema_version": DERIVED_CACHE_MANIFEST_SCHEMA_VERSION,
        "derived_cache_schema_version": DERIVED_CACHE_SCHEMA_VERSION,
        "derived_cache_key_schema_version": DERIVED_CACHE_KEY_SCHEMA_VERSION,
        "derived_result_schema_version": DERIVED_RESULT_SCHEMA_VERSION,
    }
    if (
        any(
            type(value.get(key)) is not int or value.get(key) != expected
            for key, expected in exact.items()
        )
        or value.get("venue") != "coinbase"
        or value.get("product_type") != "SPOT"
        or value.get("target_timeframe") != path_timeframe.value
        or not isinstance(value.get("parquet_artifacts"), list)
        or not isinstance(value.get("derived_gaps"), list)
    ):
        raise DerivedCacheIntegrityError("derived manifest schema is incompatible")


def _artifact(value: object) -> ParquetArtifact:
    if not isinstance(value, dict):
        raise DerivedCacheIntegrityError("derived artifact is invalid")
    try:
        return ParquetArtifact(
            _text(value, "relative_path"),
            _integer(value, "row_count"),
            UtcTimestamp.parse(_text(value, "first_open_time")),
            UtcTimestamp.parse(_text(value, "last_open_time")),
            _integer(value, "byte_size"),
            _text(value, "sha256"),
        )
    except Exception as error:
        raise DerivedCacheIntegrityError("derived artifact is invalid") from error


def _gap(value: object) -> DerivedGapRecord:
    if not isinstance(value, dict):
        raise DerivedCacheIntegrityError("derived gap is invalid")
    source_times = _list(value, "source_gap_open_times")
    if not all(isinstance(item, str) for item in source_times):
        raise DerivedCacheIntegrityError("derived gap is invalid")
    try:
        return DerivedGapRecord(
            UtcTimestamp.parse(_text(value, "open_time")),
            UtcTimestamp.parse(_text(value, "close_time")),
            GapReason(_text(value, "reason")),
            tuple(UtcTimestamp.parse(cast(str, item)) for item in source_times),
        )
    except Exception as error:
        raise DerivedCacheIntegrityError("derived gap is invalid") from error


def _timestamp(value: int) -> UtcTimestamp:
    try:
        return UtcTimestamp(datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value))
    except OverflowError as error:
        raise DerivedCacheIntegrityError("derived Parquet timestamp is out of range") from error


def _timeframe_from_directory(path: Path) -> Timeframe:
    try:
        return Timeframe.parse(path.parent.name)
    except Exception as error:
        raise DerivedCacheIntegrityError("derived cache path has invalid timeframe") from error


def _text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise DerivedCacheIntegrityError(f"derived manifest {key} is invalid")
    return item


def _integer(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if type(item) is not int:
        raise DerivedCacheIntegrityError(f"derived manifest {key} is invalid")
    return item


def _list(value: dict[str, object], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list):
        raise DerivedCacheIntegrityError(f"derived manifest {key} is invalid")
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
        raise DerivedCacheIntegrityError("derived path escapes configured root") from error


def _safe_mkdir(root: Path, directory: Path) -> None:
    try:
        relative = directory.relative_to(root)
    except ValueError as error:
        raise DerivedCacheIntegrityError("derived directory escapes configured root") from error
    current = root
    for segment in relative.parts:
        current = current / segment
        if current.exists() and current.is_symlink():
            raise DerivedCacheIntegrityError("derived directory must not traverse a symlink")
        current.mkdir(exist_ok=True)
        _inside(root, current)
