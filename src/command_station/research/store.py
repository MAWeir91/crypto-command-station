"""SQLite application metadata; immutable files remain financial authority."""

import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from command_station.research.jobs import (
    BatchBacktestSpec,
    BatchJobId,
    BatchRunId,
    BatchView,
    JobState,
    JobView,
)
from command_station.research.spec_codec import decode_spec, encode_spec, strict_json
from command_station.research.specs import (
    BacktestRunId,
    EngineIdentity,
    canonical_json,
    require_sha256,
)


class ResearchStoreError(RuntimeError):
    """Metadata integrity or persistence failed."""


class JobTransitionError(ResearchStoreError):
    pass


class JobNotCancellableError(JobTransitionError):
    pass


class RunnerLeaseError(ResearchStoreError):
    pass


class ResultIndexConflictError(ResearchStoreError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class ResultIndexRecord:
    run_id: BacktestRunId
    spec_fingerprint: str
    result_fingerprint: str
    manifest_fingerprint: str
    engine_identity: EngineIdentity
    strategy_artifact_fingerprint: str
    strategy_id: str
    trading_start: str
    replay_end: str
    products: tuple[tuple[str, str], ...]
    net_profit: str
    total_return: float | None
    max_drawdown: float
    closed_trade_count: int
    indexed_at: str

    def __post_init__(self) -> None:
        for value in (
            self.spec_fingerprint,
            self.result_fingerprint,
            self.manifest_fingerprint,
            self.strategy_artifact_fingerprint,
        ):
            require_sha256(value)
        if (
            type(self.run_id) is not BacktestRunId
            or type(self.engine_identity) is not EngineIdentity
        ):
            raise ResearchStoreError("invalid result identity types")
        if type(self.products) is not tuple or self.products != tuple(sorted(set(self.products))):
            raise ResearchStoreError("canonical unique product relationships required")
        for product, version in self.products:
            if type(product) is not str or not product:
                raise ResearchStoreError("invalid result product")
            require_sha256(version)
        if type(self.net_profit) is not str or not Decimal(self.net_profit).is_finite():
            raise ResearchStoreError("finite exact profit required")
        if type(self.closed_trade_count) is not int or self.closed_trade_count < 0:
            raise ResearchStoreError("invalid trade count")
        if type(self.max_drawdown) is not float or not math.isfinite(self.max_drawdown):
            raise ResearchStoreError("finite drawdown required")
        if self.total_return is not None and (
            type(self.total_return) is not float or not math.isfinite(self.total_return)
        ):
            raise ResearchStoreError("finite return required")

    def deterministic(self) -> bytes:
        from dataclasses import replace

        return canonical_json(replace(self, indexed_at=""))


_SCHEMA = (
    (
        "CREATE TABLE batches(batch_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL"
        ",engine BLOB NOT NULL,created_at TEXT NOT NULL)"
    ),
    (
        "CREATE TABLE jobs(job_id TEXT PRIMARY KEY,batch_id TEXT NOT NULL REFEREN"
        "CES batches(batch_id),run_id TEXT NOT NULL,spec BLOB NOT NULL,spec_finge"
        "rprint TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('PENDING','RUNN"
        "ING','COMPLETED','FAILED','CANCELLED')),attempt_count INTEGER NOT NULL D"
        "EFAULT 0 CHECK(attempt_count>=0),claim_token TEXT,failure_code TEXT,fail"
        "ure_message TEXT,created_at TEXT NOT NULL,result_fingerprint TEXT,manife"
        "st_fingerprint TEXT,UNIQUE(batch_id,run_id))"
    ),
    (
        "CREATE TABLE results(run_id TEXT PRIMARY KEY,record BLOB NOT NULL,strate"
        "gy_id TEXT NOT NULL)"
    ),
    (
        "CREATE TABLE result_products(run_id TEXT NOT NULL REFERENCES results(run"
        "_id),product_id TEXT NOT NULL,dataset_version TEXT NOT NULL,PRIMARY KEY("
        "run_id,product_id))"
    ),
    (
        "CREATE TABLE runner_lease(singleton INTEGER PRIMARY KEY CHECK(singleton="
        "1),token TEXT NOT NULL,acquired_at TEXT NOT NULL)"
    ),
)


class LocalResearchStore:
    def __init__(self, database_path: Path) -> None:
        if (
            not isinstance(database_path, Path)
            or not database_path.is_absolute()
            or ".." in database_path.parts
        ):
            raise ResearchStoreError("absolute database path without traversal required")
        self.database_path = database_path
        self._safe()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(initialize=True) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if db.execute(
                    "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchall():
                    raise ResearchStoreError("unversioned nonempty database rejected")
                for statement in _SCHEMA:
                    db.execute(statement)
                db.execute("PRAGMA user_version=1")
            elif version != 1:
                raise ResearchStoreError("unknown schema version")
            self._schema(db)

    def _schema(self, db: sqlite3.Connection) -> None:
        actual = {
            r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
        }
        if actual != set(_SCHEMA):
            raise ResearchStoreError("schema v1 structure mismatch")

    def _safe(self) -> None:
        for path in (self.database_path, *self.database_path.parents):
            if path.is_symlink() or path.is_junction():
                raise ResearchStoreError("symlink/junction database rejected")
        for path in (
            self.database_path,
            Path(str(self.database_path) + "-journal"),
            Path(str(self.database_path) + "-wal"),
            Path(str(self.database_path) + "-shm"),
        ):
            if (
                path.is_symlink()
                or path.is_junction()
                or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1))
            ):
                raise ResearchStoreError("unsafe database or sidecar")

    @contextmanager
    def _connection(self, *, initialize: bool = False) -> Iterator[sqlite3.Connection]:
        self._safe()
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if not initialize and db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ResearchStoreError("schema version changed")
            if not initialize:
                self._schema(db)
            yield db
            db.commit()
        except sqlite3.Error as exc:
            db.rollback()
            raise ResearchStoreError("SQLite operation failed") from exc
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def submit(self, batch: BatchBacktestSpec, engine: EngineIdentity) -> BatchView:
        batch_id = BatchRunId.derive(batch, engine)
        engine_bytes = canonical_json(engine)
        with self._connection() as db:
            existing = db.execute(
                "SELECT * FROM batches WHERE batch_id=?", (batch_id.value,)
            ).fetchone()
            if existing:
                if (
                    existing["fingerprint"] != batch.fingerprint
                    or existing["engine"] != engine_bytes
                ):
                    raise ResearchStoreError("batch identity conflict")
                rows = db.execute(
                    "SELECT * FROM jobs WHERE batch_id=?", (batch_id.value,)
                ).fetchall()
                if {r["spec"] for r in rows} != {encode_spec(s) for s in batch.members}:
                    raise ResearchStoreError("batch membership conflict")
                for row in rows:
                    self._job(row, engine)
            else:
                created = now()
                db.execute(
                    "INSERT INTO batches VALUES(?,?,?,?)",
                    (batch_id.value, batch.fingerprint, engine_bytes, created),
                )
                for spec in batch.members:
                    run_id = BacktestRunId.derive(spec, engine)
                    job_id = BatchJobId.derive(batch_id, run_id)
                    db.execute(
                        (
                            "INSERT INTO jobs(job_id,batch_id,run_id,spec,spec_fingerprint,"
                            "state,created_at) VALUES(?,?,?,?,?,'PENDING',?)"
                        ),
                        (
                            job_id.value,
                            batch_id.value,
                            run_id.value,
                            encode_spec(spec),
                            spec.fingerprint,
                            created,
                        ),
                    )
        return self.get_batch(batch_id)

    def _engine(self, data: bytes) -> EngineIdentity:
        try:
            return EngineIdentity(**strict_json(data))
        except Exception as exc:
            raise ResearchStoreError("invalid engine identity") from exc

    def _job(self, row: sqlite3.Row, engine: EngineIdentity) -> JobView:
        try:
            spec = decode_spec(row["spec"])
            batch_id, run_id, job_id = (
                BatchRunId(row["batch_id"]),
                BacktestRunId(row["run_id"]),
                BatchJobId(row["job_id"]),
            )
            if (
                spec.fingerprint != row["spec_fingerprint"]
                or BacktestRunId.derive(spec, engine) != run_id
                or BatchJobId.derive(batch_id, run_id) != job_id
            ):
                raise ResearchStoreError("persisted job identity mismatch")
            return JobView(
                job_id,
                batch_id,
                run_id,
                spec,
                engine,
                JobState(row["state"]),
                row["attempt_count"],
                row["failure_code"],
                row["failure_message"],
                row["created_at"],
            )
        except Exception as exc:
            raise ResearchStoreError("invalid persisted job") from exc

    def get_job(self, job_id: BatchJobId) -> JobView:
        with self._connection() as db:
            row = db.execute(
                "SELECT j.*,b.engine FROM jobs j JOIN batches b USING(batch_id) WHERE job_id=?",
                (job_id.value,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            return self._job(row, self._engine(row["engine"]))

    @staticmethod
    def _bounds(limit: int, offset: int) -> None:
        if (
            type(limit) is not int
            or not 1 <= limit <= 1000
            or type(offset) is not int
            or offset < 0
        ):
            raise ValueError("invalid query bounds")

    def list_jobs(
        self,
        *,
        batch_id: BatchRunId | None = None,
        state: JobState | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[JobView, ...]:
        self._bounds(limit, offset)
        with self._connection() as db:
            rows = db.execute(
                (
                    "SELECT j.*,b.engine FROM jobs j JOIN batches b USING(batch_id) WHERE (? "
                    "IS NULL OR batch_id=?) AND (? IS NULL OR state=?) ORDER BY job_id LIMIT "
                    "? OFFSET ?"
                ),
                (
                    batch_id.value if batch_id else None,
                    batch_id.value if batch_id else None,
                    state,
                    state,
                    limit,
                    offset,
                ),
            ).fetchall()
            return tuple(self._job(r, self._engine(r["engine"])) for r in rows)

    def get_batch(self, batch_id: BatchRunId) -> BatchView:
        with self._connection() as db:
            row = db.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id.value,)).fetchone()
            if row is None:
                raise KeyError(batch_id)
            jobs = db.execute("SELECT * FROM jobs WHERE batch_id=?", (batch_id.value,)).fetchall()
            engine = self._engine(row["engine"])
            views = tuple(self._job(j, engine) for j in jobs)
            if (
                not views
                or BatchRunId.derive(BatchBacktestSpec(tuple(j.spec for j in views)), engine)
                != batch_id
                or BatchBacktestSpec(tuple(j.spec for j in views)).fingerprint != row["fingerprint"]
            ):
                raise ResearchStoreError("batch membership identity mismatch")
            return BatchView(
                batch_id,
                row["fingerprint"],
                engine,
                row["created_at"],
                tuple((s, sum(j.state == s for j in views)) for s in JobState),
            )

    def list_batches(self, *, limit: int = 100, offset: int = 0) -> tuple[BatchView, ...]:
        self._bounds(limit, offset)
        with self._connection() as db:
            ids = db.execute(
                "SELECT batch_id FROM batches ORDER BY batch_id LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return tuple(self.get_batch(BatchRunId(r[0])) for r in ids)

    def acquire_lease(self) -> str:
        token = uuid4().hex
        with self._connection() as db:
            if db.execute("SELECT 1 FROM runner_lease").fetchone():
                raise RunnerLeaseError(
                    "another coordinator holds the lease; explicit recovery required"
                )
            db.execute("INSERT INTO runner_lease VALUES(1,?,?)", (token, now()))
        return token

    def _lease(self, db: sqlite3.Connection, token: str) -> None:
        row = db.execute("SELECT token FROM runner_lease WHERE singleton=1").fetchone()
        if row is None or row[0] != token:
            raise RunnerLeaseError("coordinator lease revoked")

    def release_lease(self, token: str) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM runner_lease WHERE token=?", (token,))

    def claim(self, job_id: BatchJobId, token: str) -> bool:
        self.get_job(job_id)
        with self._connection() as db:
            self._lease(db, token)
            return (
                db.execute(
                    (
                        "UPDATE jobs SET state='RUNNING',attempt_count=attempt_count+1,claim_toke"
                        "n=?,failure_code=NULL,failure_message=NULL WHERE job_id=? AND state='PEN"
                        "DING'"
                    ),
                    (token, job_id.value),
                ).rowcount
                == 1
            )

    def cancel(self, job_id: BatchJobId) -> bool:
        self.get_job(job_id)
        with self._connection() as db:
            row = db.execute("SELECT state FROM jobs WHERE job_id=?", (job_id.value,)).fetchone()
            if row[0] == "RUNNING":
                raise JobNotCancellableError("running financial work cannot be cancelled")
            return (
                db.execute(
                    "UPDATE jobs SET state='CANCELLED' WHERE job_id=? AND state='PENDING'",
                    (job_id.value,),
                ).rowcount
                == 1
            )

    def requeue(self, job_id: BatchJobId) -> None:
        self.get_job(job_id)
        with self._connection() as db:
            if (
                db.execute(
                    (
                        "UPDATE jobs SET state='PENDING',claim_token=NULL,failure_code=NULL,failu"
                        "re_message=NULL WHERE job_id=? AND state IN ('FAILED','CANCELLED')"
                    ),
                    (job_id.value,),
                ).rowcount
                != 1
            ):
                raise JobTransitionError("only failed/cancelled jobs may be requeued")

    def fail(self, job_id: BatchJobId, token: str, exc: Exception) -> None:
        with self._connection() as db:
            self._lease(db, token)
            if (
                db.execute(
                    (
                        "UPDATE jobs SET state='FAILED',failure_code=?,failure_message=?,claim_to"
                        "ken=NULL WHERE job_id=? AND state='RUNNING' AND claim_token=?"
                    ),
                    (type(exc).__name__[:80], str(exc)[:1000], job_id.value, token),
                ).rowcount
                != 1
            ):
                raise JobTransitionError("failure claim lost")

    def recover_interrupted_runner(self) -> int:
        """Operator must know the old coordinator is gone; fences all old claims."""
        with self._connection() as db:
            count = db.execute(
                "UPDATE jobs SET state='FAILED',failure_code='INTERRUPTED',failure_messag"
                "e='Explicit interrupted coordinator recovery',claim_token=NULL WHERE sta"
                "te='RUNNING'"
            ).rowcount
            db.execute("DELETE FROM runner_lease")
            return count

    def _result(self, data: bytes) -> ResultIndexRecord:
        try:
            d = strict_json(data)
            d["run_id"] = BacktestRunId(d["run_id"]["value"])
            d["engine_identity"] = EngineIdentity(**d["engine_identity"])
            d["products"] = tuple(tuple(p) for p in d["products"])
            record = ResultIndexRecord(**d)
            if canonical_json(record) != data:
                raise ValueError("index roundtrip mismatch")
            return record
        except Exception as exc:
            raise ResearchStoreError("invalid result index") from exc

    def get_result(self, run_id: BacktestRunId) -> ResultIndexRecord | None:
        with self._connection() as db:
            return self._verified_index(db).get(run_id.value)

    def _verified_index(self, db: sqlite3.Connection) -> dict[str, ResultIndexRecord]:
        """Check redundant query metadata before any filtering can hide corruption."""
        records: dict[str, ResultIndexRecord] = {}
        for row in db.execute("SELECT run_id,strategy_id,record FROM results"):
            record = self._result(row["record"])
            if record.run_id.value != row["run_id"] or record.strategy_id != row["strategy_id"]:
                raise ResearchStoreError("result index SQL identity differs from canonical record")
            records[row["run_id"]] = record
        relationships: dict[str, list[tuple[str, str]]] = {}
        for row in db.execute(
            "SELECT run_id,product_id,dataset_version FROM result_products ORDER BY product_id"
        ):
            if row["run_id"] not in records:
                raise ResearchStoreError("orphan result product relationship")
            relationships.setdefault(row["run_id"], []).append(
                (row["product_id"], row["dataset_version"])
            )
        for run_id, record in records.items():
            if tuple(relationships.get(run_id, [])) != record.products:
                raise ResearchStoreError(
                    "result product relationships differ from canonical record"
                )
        return records

    def list_results(
        self,
        *,
        strategy_id: str | None = None,
        product_id: str | None = None,
        dataset_version: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[ResultIndexRecord, ...]:
        self._bounds(limit, offset)
        with self._connection() as db:
            records = self._verified_index(db)
            rows = db.execute(
                (
                    "SELECT run_id FROM results r WHERE (? IS NULL OR strategy_id=?) AND ((? "
                    "IS NULL AND ? IS NULL) OR EXISTS(SELECT 1 FROM result_products p WHERE p"
                    ".run_id=r.run_id AND (? IS NULL OR product_id=?) AND (? IS NULL OR datas"
                    "et_version=?))) ORDER BY run_id LIMIT ? OFFSET ?"
                ),
                (
                    strategy_id,
                    strategy_id,
                    product_id,
                    dataset_version,
                    product_id,
                    product_id,
                    dataset_version,
                    dataset_version,
                    limit,
                    offset,
                ),
            ).fetchall()
            return tuple(records[r[0]] for r in rows)

    def complete(self, job: JobView, token: str, record: ResultIndexRecord) -> None:
        with self._connection() as db:
            self._lease(db, token)
            indexed = self._verified_index(db)
            row = db.execute(
                "SELECT j.*,b.engine FROM jobs j JOIN batches b USING(batch_id) WHERE job_id=?",
                (job.job_id.value,),
            ).fetchone()
            current = self._job(row, self._engine(row["engine"]))
            if current != job or current.state != JobState.RUNNING or row["claim_token"] != token:
                raise JobTransitionError("completion claim changed")
            if (
                record.run_id != job.run_id
                or record.spec_fingerprint != job.spec.fingerprint
                or record.engine_identity != job.engine_identity
            ):
                raise ResearchStoreError("completion identity mismatch")
            if record.products != tuple(
                (d.product_id.value, d.dataset_version.value) for d in job.spec.datasets
            ):
                raise ResearchStoreError("completion product identity mismatch")
            existing = indexed.get(record.run_id.value)
            if existing is not None:
                if existing.deterministic() != record.deterministic():
                    raise ResultIndexConflictError("immutable result index conflict")
            else:
                db.execute(
                    "INSERT INTO results VALUES(?,?,?)",
                    (record.run_id.value, canonical_json(record), record.strategy_id),
                )
                db.executemany(
                    "INSERT INTO result_products VALUES(?,?,?)",
                    ((record.run_id.value, p, v) for p, v in record.products),
                )
            products = tuple(
                tuple(r)
                for r in db.execute(
                    (
                        "SELECT product_id,dataset_version FROM result_products WHERE run_id=? OR"
                        "DER BY product_id"
                    ),
                    (record.run_id.value,),
                )
            )
            if products != record.products:
                raise ResultIndexConflictError("result product mapping conflict")
            if (
                db.execute(
                    (
                        "UPDATE jobs SET state='COMPLETED',claim_token=NULL,result_fingerprint=?,"
                        "manifest_fingerprint=? WHERE job_id=? AND state='RUNNING' AND claim_toke"
                        "n=?"
                    ),
                    (
                        record.result_fingerprint,
                        record.manifest_fingerprint,
                        job.job_id.value,
                        token,
                    ),
                ).rowcount
                != 1
            ):
                raise JobTransitionError("completion claim lost")
