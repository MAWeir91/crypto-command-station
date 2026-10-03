"""Fixed, verified immutable research bundles with atomic directory publication.

Parquet schema v1 uses nullable UTF-8 columns: decimals are canonical exact text,
timestamps are UTC ISO text, enum values are stable text, structured fields are
canonical JSON. Column names/order and schema metadata are fixed per artifact.
"""

import json
import shutil
import tempfile
from dataclasses import dataclass, fields
from hashlib import sha256
from pathlib import Path
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from command_station.accounting import PortfolioSnapshot
from command_station.domain import UtcTimestamp
from command_station.execution import Fill, Order
from command_station.research.specs import (
    BacktestRunId,
    canonical_json,
    fingerprint,
    logical,
    require_sha256,
)
from command_station.research.trades import ClosedLotTrade
from command_station.risk import RiskDecision
from command_station.strategy import StrategyActionResult


class BacktestReproducibilityError(RuntimeError):
    """Immutable artifact identity or content failed verification."""


TABLE_MODELS = {
    "orders.parquet": Order,
    "fills.parquet": Fill,
    "trades.parquet": ClosedLotTrade,
    "equity.parquet": PortfolioSnapshot,
    "risk_decisions.parquet": RiskDecision,
    "strategy_actions.parquet": StrategyActionResult,
}
TABLE_COLUMNS = {name: tuple(f.name for f in fields(model)) for name, model in TABLE_MODELS.items()}
TABLE_COLUMNS["strategy_actions.parquet"] += ("risk_decision_id",)
BUNDLE_NAMES = frozenset((*TABLE_MODELS, "spec.json", "summary.json", "manifest.json"))


def table_schema(name: str) -> pa.Schema:
    return pa.schema(
        [pa.field(c, pa.string()) for c in TABLE_COLUMNS[name]],
        metadata={b"artifact_schema_version": b"1", b"artifact": name.encode()},
    )


def _cell(value: object) -> str | None:
    # IDs, ProductId and quantity wrappers expose a single immutable value.
    if value is not None and hasattr(value, "value") and not isinstance(value, (str, UtcTimestamp)):
        value = value.value if len(getattr(value, "__dataclass_fields__", {})) == 1 else value
    encoded = logical(value)
    if encoded is None:
        return None
    if isinstance(encoded, str):
        return encoded
    return canonical_json(encoded).decode("utf-8")


def canonical_rows(name: str, records: tuple[object, ...]) -> list[dict[str, str | None]]:
    if any(type(record) is not TABLE_MODELS[name] for record in records):
        raise ValueError("incorrect artifact record type")
    keys = {
        "orders.parquet": "order_id",
        "fills.parquet": "fill_id",
        "risk_decisions.parquet": "decision_id",
        "strategy_actions.parquet": "command_id",
        "equity.parquet": "timestamp",
    }
    if name == "trades.parquet":
        ordered = sorted(
            records,
            key=lambda r: (
                cast(ClosedLotTrade, r).exit_time,
                cast(ClosedLotTrade, r).consumption_id.value,
            ),
        )
    else:
        ordered = sorted(records, key=lambda r: getattr(r, keys[name]))
    rows = [
        {c: _cell(getattr(r, c)) for c in TABLE_COLUMNS[name] if c != "risk_decision_id"}
        for r in ordered
    ]
    if name == "strategy_actions.parquet":
        for row, record in zip(rows, ordered, strict=True):
            decision = cast(StrategyActionResult, record).risk_decision
            row["risk_decision_id"] = _cell(decision.decision_id) if decision else None
    if len({tuple(row.items()) for row in rows}) != len(rows):
        raise ValueError("duplicate artifact rows")
    return rows


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    relative_path: str
    row_count: int | None
    byte_size: int
    sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_record(self)


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    run_id: BacktestRunId
    result_fingerprint: str
    artifacts: tuple[ArtifactRecord, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_manifest(self)

    @property
    def fingerprint(self) -> str:
        return fingerprint(
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id.value,
                "result_fingerprint": self.result_fingerprint,
                "artifacts": logical(self.artifacts),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id.value,
            "result_fingerprint": self.result_fingerprint,
            "artifacts": logical(self.artifacts),
            "manifest_fingerprint": self.fingerprint,
        }


def _validate_record(record: ArtifactRecord) -> None:
    if (
        type(record) is not ArtifactRecord
        or type(record.relative_path) is not str
        or record.relative_path not in BUNDLE_NAMES - {"manifest.json"}
        or type(record.schema_version) is not int
        or record.schema_version != 1
        or type(record.byte_size) is not int
        or record.byte_size < 0
    ):
        raise BacktestReproducibilityError("invalid artifact record path/version/size")
    if record.relative_path in TABLE_MODELS:
        if type(record.row_count) is not int or record.row_count < 0:
            raise BacktestReproducibilityError("Parquet artifact requires nonnegative row count")
    elif record.row_count is not None:
        raise BacktestReproducibilityError("JSON artifact must omit row count")
    try:
        require_sha256(record.sha256)
    except ValueError as exc:
        raise BacktestReproducibilityError("invalid artifact SHA-256") from exc


def _validate_manifest(manifest: ArtifactManifest) -> None:
    if (
        type(manifest) is not ArtifactManifest
        or type(manifest.run_id) is not BacktestRunId
        or type(manifest.schema_version) is not int
        or manifest.schema_version != 1
        or type(manifest.artifacts) is not tuple
    ):
        raise BacktestReproducibilityError("invalid manifest identity/version/record types")
    try:
        require_sha256(manifest.run_id.value)
        require_sha256(manifest.result_fingerprint)
    except ValueError as exc:
        raise BacktestReproducibilityError("invalid manifest run/result identity") from exc
    for record in manifest.artifacts:
        _validate_record(record)
    paths = tuple(record.relative_path for record in manifest.artifacts)
    if len(paths) != 8 or set(paths) != BUNDLE_NAMES - {"manifest.json"}:
        raise BacktestReproducibilityError("manifest requires exactly eight unique fixed artifacts")
    if paths != tuple(sorted(paths)):
        raise BacktestReproducibilityError("manifest artifact records must be canonically ordered")


def _safe(path: Path) -> None:
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise BacktestReproducibilityError("symlink/junction artifact path rejected")


class LocalBacktestArtifactStore:
    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts:
            raise ValueError("explicit absolute artifact root without traversal required")
        _safe(root)
        self.root = root

    def directory(self, run_id: BacktestRunId) -> Path:
        if type(run_id) is not BacktestRunId:
            raise ValueError("validated run ID required")
        path = self.root / "backtests" / run_id.value
        _safe(path)
        return path

    def publish(
        self,
        run_id: BacktestRunId,
        result_fingerprint: str,
        spec: dict[str, object],
        summary: dict[str, object],
        tables: dict[str, tuple[object, ...]],
    ) -> ArtifactManifest:
        require_sha256(result_fingerprint)
        if set(tables) != set(TABLE_MODELS):
            raise ValueError("fixed Phase012 artifact tables required")
        final = self.directory(run_id)
        _safe(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        parent = self.root / "backtests"
        _safe(parent)
        parent.mkdir(exist_ok=True)
        staging_parent = self.root / ".staging"
        _safe(staging_parent)
        staging_parent.mkdir(exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="backtest-", dir=staging_parent))
        try:
            counts: dict[str, int | None] = {"spec.json": None, "summary.json": None}
            (staging / "spec.json").write_bytes(canonical_json(spec))
            (staging / "summary.json").write_bytes(canonical_json(summary))
            for name in sorted(tables):
                rows = canonical_rows(name, tables[name])
                table = pa.Table.from_pylist(rows, schema=table_schema(name))
                pq.write_table(
                    table,
                    staging / name,
                    compression="NONE",
                    use_dictionary=False,
                    write_statistics=False,
                    version="2.6",
                )
                counts[name] = len(rows)
            records = tuple(
                ArtifactRecord(
                    name,
                    counts[name],
                    (staging / name).stat().st_size,
                    sha256((staging / name).read_bytes()).hexdigest(),
                )
                for name in sorted(counts)
            )
            manifest = ArtifactManifest(run_id, result_fingerprint, records)
            (staging / "manifest.json").write_bytes(canonical_json(manifest.to_dict()))
            self._verify(staging, manifest)
            # Serialize publication among cooperating writers. An existing stale lock
            # fails explicitly, leaving any published bundle untouched.
            lock = parent / (run_id.value + ".lock")
            _safe(lock)
            with lock.open("xb"):
                pass
            try:
                _safe(final)
                if final.exists():
                    self._verify(final, manifest)
                else:
                    staging.rename(final)
                return manifest
            finally:
                lock.unlink()
        finally:
            if staging.exists():
                _safe(staging)
                shutil.rmtree(staging)

    def verify(self, manifest: ArtifactManifest) -> None:
        _validate_manifest(manifest)
        self._verify(self.directory(manifest.run_id), manifest)

    def load_manifest(self, run_id: BacktestRunId) -> ArtifactManifest:
        """Strictly reconstruct and verify a complete immutable bundle."""
        from command_station.research.spec_codec import strict_json

        path = self.directory(run_id) / "manifest.json"
        _safe(path)
        try:
            if not path.is_file() or path.stat().st_nlink != 1:
                raise BacktestReproducibilityError("unsafe manifest file")
            data = path.read_bytes()
            raw = strict_json(data)
            manifest = ArtifactManifest(
                BacktestRunId(raw["run_id"]),
                raw["result_fingerprint"],
                tuple(ArtifactRecord(**r) for r in raw["artifacts"]),
                raw["schema_version"],
            )
            if manifest.run_id != run_id or canonical_json(manifest.to_dict()) != data:
                raise BacktestReproducibilityError("manifest canonical schema/identity mismatch")
            self.verify(manifest)
            return manifest
        except BacktestReproducibilityError:
            raise
        except Exception as exc:
            raise BacktestReproducibilityError("strict manifest load failed") from exc

    def _verify(self, directory: Path, expected: ArtifactManifest) -> None:
        _validate_manifest(expected)
        _safe(directory)
        try:
            if {p.name for p in directory.iterdir()} != BUNDLE_NAMES:
                raise BacktestReproducibilityError("unexpected or missing artifact files")
            for name in BUNDLE_NAMES:
                path = directory / name
                _safe(path)
                if not path.is_file() or path.stat().st_nlink != 1:
                    raise BacktestReproducibilityError("nonregular or hardlinked artifact")
            if (directory / "manifest.json").read_bytes() != canonical_json(expected.to_dict()):
                raise BacktestReproducibilityError("same run identity produced different manifest")
            for record in expected.artifacts:
                if record.relative_path not in BUNDLE_NAMES - {"manifest.json"}:
                    raise BacktestReproducibilityError("unsafe manifest path")
                path = directory / record.relative_path
                data = path.read_bytes()
                if len(data) != record.byte_size or sha256(data).hexdigest() != record.sha256:
                    raise BacktestReproducibilityError("artifact size/hash mismatch")
                if record.relative_path.endswith(".parquet"):
                    table = pq.read_table(path)
                    if (
                        not table.schema.equals(
                            table_schema(record.relative_path), check_metadata=True
                        )
                        or table.num_rows != record.row_count
                    ):
                        raise BacktestReproducibilityError("artifact schema/row count mismatch")
                elif canonical_json(json.loads(data)) != data:
                    raise BacktestReproducibilityError("noncanonical JSON artifact")
        except BacktestReproducibilityError:
            raise
        except Exception as exc:
            raise BacktestReproducibilityError("artifact verification failed") from exc
