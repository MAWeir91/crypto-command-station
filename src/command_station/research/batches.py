"""Bounded orchestration over the sealed single-run financial service."""

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import suppress
from threading import Event, Lock
from weakref import ReferenceType, ref

from command_station.research.artifacts import (
    BacktestReproducibilityError,
    LocalBacktestArtifactStore,
)
from command_station.research.backtests import BacktestService
from command_station.research.jobs import (
    BatchBacktestSpec,
    BatchExecutionPolicy,
    BatchJobId,
    BatchRunId,
    BatchView,
    JobState,
    JobView,
)
from command_station.research.spec_codec import encode_spec, strict_json
from command_station.research.specs import (
    BacktestRunId,
    EngineIdentity,
    StrategyArtifactRef,
    fingerprint,
)
from command_station.research.store import (
    LocalResearchStore,
    ResearchStoreError,
    ResultIndexRecord,
    now,
)
from command_station.research.strategy_artifacts import (
    StrategyArtifactCatalog,
    StrategyArtifactDescriptor,
)
from command_station.strategy import Strategy


class WorkerIsolationError(ValueError):
    pass


class _DispatchFence:
    def __init__(self) -> None:
        self.lock = Lock()
        self.stopped = Event()


class _IsolatedCatalog(StrategyArtifactCatalog):
    def __init__(self, catalog: StrategyArtifactCatalog, owner: "BatchBacktestService") -> None:
        super().__init__()
        self.catalog, self.owner = catalog, owner

    def resolve(self, artifact: StrategyArtifactRef) -> tuple[StrategyArtifactDescriptor, Strategy]:
        descriptor, strategy = self.catalog.resolve(artifact)
        with self.owner._worker_lock:
            if any(previous() is strategy for previous in self.owner._strategies):
                raise WorkerIsolationError("strategy factory reused an instance across catalogs")
            self.owner._strategies = [r for r in self.owner._strategies if r() is not None]
            self.owner._strategies.append(ref(strategy))
        return descriptor, strategy


class BatchBacktestService:
    def __init__(
        self,
        *,
        store: LocalResearchStore,
        artifact_store: LocalBacktestArtifactStore,
        engine_identity: EngineIdentity,
        worker_factory: Callable[[], BacktestService],
    ) -> None:
        if type(engine_identity) is not EngineIdentity:
            raise ValueError("exact engine identity required")
        self.store, self.artifact_store, self.engine_identity, self.worker_factory = (
            store,
            artifact_store,
            engine_identity,
            worker_factory,
        )
        self._workers: list[BacktestService] = []
        self._catalogs: list[StrategyArtifactCatalog] = []
        self._strategies: list[ReferenceType[Strategy]] = []
        self._worker_lock = Lock()

    def submit(self, spec: BatchBacktestSpec) -> BatchView:
        return self.store.submit(spec, self.engine_identity)

    def get_batch(self, batch_id: BatchRunId) -> BatchView:
        return self.store.get_batch(batch_id)

    def list_batches(self, *, limit: int = 100, offset: int = 0) -> tuple[BatchView, ...]:
        return self.store.list_batches(limit=limit, offset=offset)

    def get_job(self, job_id: BatchJobId) -> JobView:
        return self.store.get_job(job_id)

    def list_jobs(
        self,
        *,
        batch_id: BatchRunId | None = None,
        state: JobState | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[JobView, ...]:
        return self.store.list_jobs(batch_id=batch_id, state=state, limit=limit, offset=offset)

    def get_result(self, run_id: BacktestRunId) -> ResultIndexRecord | None:
        return self.store.get_result(run_id)

    def list_results(
        self,
        *,
        strategy_id: str | None = None,
        product_id: str | None = None,
        dataset_version: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[ResultIndexRecord, ...]:
        return self.store.list_results(
            strategy_id=strategy_id,
            product_id=product_id,
            dataset_version=dataset_version,
            limit=limit,
            offset=offset,
        )

    def cancel(self, job_id: BatchJobId) -> bool:
        return self.store.cancel(job_id)

    def cancel_batch(self, batch_id: BatchRunId) -> int:
        count, offset = 0, 0
        while jobs := self.list_jobs(batch_id=batch_id, limit=1000, offset=offset):
            for job in jobs:
                if job.state == JobState.PENDING:
                    # Cancellation may lose to a claim; batch cancellation leaves it running.
                    from command_station.research.store import JobNotCancellableError

                    with suppress(JobNotCancellableError):
                        count += self.cancel(job.job_id)
            offset += len(jobs)
        return count

    def requeue(self, job_id: BatchJobId) -> None:
        self.store.requeue(job_id)

    def recover_interrupted_runner(self) -> int:
        """Call only after establishing the prior coordinator is gone."""
        return self.store.recover_interrupted_runner()

    def _verified_record(self, job: JobView) -> ResultIndexRecord:
        manifest = self.artifact_store.load_manifest(job.run_id)
        directory = self.artifact_store.directory(job.run_id)
        if (directory / "spec.json").read_bytes() != encode_spec(job.spec):
            raise BacktestReproducibilityError("artifact experiment mismatch")
        summary = strict_json((directory / "summary.json").read_bytes())
        result_fingerprint = summary.pop("result_fingerprint")
        provenance = summary["provenance"]
        if (
            fingerprint(summary) != result_fingerprint
            or manifest.result_fingerprint != result_fingerprint
            or summary["run_id"] != job.run_id.value
            or summary["spec_fingerprint"] != job.spec.fingerprint
            or EngineIdentity(**provenance["engine_identity"]) != job.engine_identity
            or provenance["strategy_artifact_fingerprint"] != job.spec.strategy_artifact.fingerprint
        ):
            raise BacktestReproducibilityError("artifact result identity mismatch")
        metrics = summary["metrics"]
        return ResultIndexRecord(
            job.run_id,
            job.spec.fingerprint,
            result_fingerprint,
            manifest.fingerprint,
            job.engine_identity,
            job.spec.strategy_artifact.fingerprint,
            provenance["strategy_artifact"]["strategy_id"],
            str(job.spec.period.trading_start),
            str(job.spec.period.replay_end),
            tuple((d.product_id.value, d.dataset_version.value) for d in job.spec.datasets),
            metrics["net_profit"],
            metrics["total_return"],
            metrics["max_drawdown"],
            metrics["closed_trade_count"],
            now(),
        )

    def _execute_guarded(self, job: JobView, token: str, fence: _DispatchFence) -> None:
        try:
            self._execute(job, token, fence)
        except BaseException:
            # Signal from the failing worker, before the coordinator consumes its future.
            with fence.lock:
                fence.stopped.set()
            raise

    def _execute(self, job: JobView, token: str, fence: _DispatchFence) -> None:
        with fence.lock:
            if fence.stopped.is_set() or not self.store.claim(job.job_id, token):
                return
        job = self.store.get_job(job.job_id)
        cached = self.store.get_result(job.run_id)
        if cached is not None:
            record = self._verified_record(job)
            if record.deterministic() != cached.deterministic():
                raise ResearchStoreError("cached index differs from verified artifacts")
            self.store.complete(job, token, cached)
            return
        try:
            with fence.lock, self._worker_lock:
                if fence.stopped.is_set():
                    # Claimed but not admitted financial work requires explicit recovery.
                    return
                worker = self.worker_factory()
                if type(worker) is not BacktestService or any(worker is w for w in self._workers):
                    raise WorkerIsolationError(
                        "worker must have fresh service and strategy catalog"
                    )
                if any(worker.strategies is c for c in self._catalogs):
                    raise WorkerIsolationError("worker reused strategy catalog")
                if (
                    worker.engine_identity != self.engine_identity
                    or worker.artifacts.root != self.artifact_store.root
                ):
                    raise WorkerIsolationError("worker engine/artifact root mismatch")
                self._workers.append(worker)
                self._catalogs.append(worker.strategies)
                worker.strategies = _IsolatedCatalog(worker.strategies, self)
                # Admission linearizes against integrity detection under fence.lock.
                # Once admitted, a simulation finishes normally even if another fails.
            result = worker.run(job.spec)
        except (ResearchStoreError, BacktestReproducibilityError):
            raise
        except Exception as exc:
            self.store.fail(job.job_id, token, exc)
            return
        if (
            result.run_id != job.run_id
            or result.spec_fingerprint != job.spec.fingerprint
            or result.provenance.engine_identity != self.engine_identity
            or result.artifact_manifest is None
        ):
            raise BacktestReproducibilityError("worker returned mismatched result")
        record = self._verified_record(job)
        if (
            record.result_fingerprint != result.result_fingerprint
            or record.manifest_fingerprint != result.artifact_manifest.fingerprint
        ):
            raise BacktestReproducibilityError("worker result/manifest mismatch")
        self.store.complete(job, token, record)

    def run_pending(
        self,
        *,
        batch_id: BatchRunId | None = None,
        policy: BatchExecutionPolicy | None = None,
    ) -> tuple[JobView, ...]:
        policy = policy if policy is not None else BatchExecutionPolicy()
        token = self.store.acquire_lease()
        try:
            pending: list[JobView] = []
            offset = 0
            while page := self.store.list_jobs(
                batch_id=batch_id, state=JobState.PENDING, limit=1000, offset=offset
            ):
                pending.extend(page)
                offset += len(page)
            for identity in {j.batch_id for j in pending}:
                batch = self.store.get_batch(identity)
                if batch.engine_identity != self.engine_identity:
                    raise ResearchStoreError("persisted batch engine differs from coordinator")
            fence = _DispatchFence()
            remaining = iter(pending)
            with ThreadPoolExecutor(max_workers=policy.max_workers) as pool:
                active = set()
                for _ in range(policy.max_workers):
                    if (job := next(remaining, None)) is not None:
                        active.add(pool.submit(self._execute_guarded, job, token, fence))
                while active:
                    completed, active = wait(active, return_when=FIRST_COMPLETED)
                    # Consume all observed completions before admitting replacement work.
                    for future in completed:
                        future.result()
                    if fence.stopped.is_set():
                        continue
                    for _ in completed:
                        if (job := next(remaining, None)) is not None:
                            active.add(pool.submit(self._execute_guarded, job, token, fence))
            return tuple(self.store.get_job(j.job_id) for j in pending)
        finally:
            self.store.release_lease(token)
