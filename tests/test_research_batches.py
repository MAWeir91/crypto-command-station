"""Real sealed-service batch, durability, race and integrity scenarios."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from command_station.research.artifacts import BacktestReproducibilityError
from command_station.research.backtests import BacktestService
from command_station.research.batches import BatchBacktestService
from command_station.research.jobs import (
    BatchBacktestSpec,
    BatchExecutionPolicy,
    BatchJobId,
    BatchRunId,
    JobState,
)
from command_station.research.spec_codec import SpecCodecError, decode_spec, encode_spec
from command_station.research.specs import BacktestSpec, StrategyArtifactRef
from command_station.research.store import (
    JobNotCancellableError,
    JobTransitionError,
    LocalResearchStore,
    ResearchStoreError,
    RunnerLeaseError,
)
from command_station.research.strategy_artifacts import StrategyArtifactCatalog
from tests.research_fixtures import MultiProduct, setup


def coordinator(root: Path) -> tuple[BatchBacktestService, BacktestSpec]:
    single, spec = setup(root)

    def factory() -> BacktestService:
        catalog = StrategyArtifactCatalog()
        # Register the exact trusted factory after reconstruction.
        for descriptor, strategy_factory in single.strategies._entries.values():
            catalog.register(descriptor, strategy_factory)
        return BacktestService(
            datasets=single.datasets,
            strategies=catalog,
            artifacts=single.artifacts,
            engine_identity=single.engine_identity,
        )

    return BatchBacktestService(
        store=LocalResearchStore(root / "research.sqlite"),
        artifact_store=single.artifacts,
        engine_identity=single.engine_identity,
        worker_factory=factory,
    ), spec


def test_parallel_restart_cache_and_queries(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    members = tuple(replace(spec, random_seed=i) for i in range(3))
    batch = service.submit(BatchBacktestSpec(members))
    assert dict(batch.counts)[JobState.PENDING] == 3
    restarted = BatchBacktestService(
        store=LocalResearchStore(service.store.database_path),
        artifact_store=service.artifact_store,
        engine_identity=service.engine_identity,
        worker_factory=service.worker_factory,
    )
    jobs = restarted.run_pending(policy=BatchExecutionPolicy(3))
    assert all(j.state == JobState.COMPLETED and j.attempt_count == 1 for j in jobs)
    assert restarted.get_batch(batch.batch_id).state == JobState.COMPLETED
    assert len(service.list_results(strategy_id="research", product_id="BTC-USD")) == 3
    assert service.list_results(strategy_id="' OR 1=1 --") == ()
    for job in jobs:
        record = service.get_result(job.run_id)
        assert record is not None
        assert (
            service.artifact_store.load_manifest(job.run_id).fingerprint
            == record.manifest_fingerprint
        )
        direct = service.worker_factory().run(job.spec)
        assert record.result_fingerprint == direct.result_fingerprint
    service.submit(BatchBacktestSpec((spec,)))
    service.worker_factory = lambda: pytest.fail("cache must skip factory")
    assert service.run_pending()[0].state == JobState.COMPLETED


def test_failure_cancel_requeue_and_terminal(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    bad = replace(spec, strategy_artifact=StrategyArtifactRef("f" * 64))
    batch = service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=2), bad)))
    jobs = service.list_jobs(batch_id=batch.batch_id)
    cancelled = next(j for j in jobs if j.spec == spec)
    assert service.cancel(cancelled.job_id)
    service.run_pending(policy=BatchExecutionPolicy(3))
    assert service.get_job(cancelled.job_id).state == JobState.CANCELLED
    assert service.get_result(cancelled.run_id) is None
    service.requeue(cancelled.job_id)
    assert service.run_pending()[0].run_id == cancelled.run_id
    with pytest.raises(JobTransitionError):
        service.requeue(cancelled.job_id)
    assert service.get_batch(batch.batch_id).state == JobState.FAILED
    failed = next(j for j in service.list_jobs() if j.state == JobState.FAILED)
    assert service.get_result(failed.run_id) is None


def test_cache_corruption_fatal(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    job = service.run_pending()[0]
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=1))))
    (service.artifact_store.directory(job.run_id) / "summary.json").write_bytes(b"{}")
    with pytest.raises(BacktestReproducibilityError):
        service.run_pending()
    assert any(j.state == JobState.RUNNING for j in service.list_jobs())


def test_publication_failure_recovery_fences_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    original = service.store.complete

    def failure(*args: object) -> None:
        raise ResearchStoreError("injected index transaction failure")

    monkeypatch.setattr(service.store, "complete", failure)
    with pytest.raises(ResearchStoreError):
        service.run_pending()
    job = service.list_jobs()[0]
    before = (service.artifact_store.directory(job.run_id) / "manifest.json").read_bytes()
    stale = service.store.acquire_lease()
    with pytest.raises(RunnerLeaseError):
        service.run_pending()
    assert service.recover_interrupted_runner() == 1
    assert service.get_job(job.job_id).failure_code == "INTERRUPTED"
    record = service._verified_record(job)
    with pytest.raises(RunnerLeaseError):
        original(job, stale, record)
    service.requeue(job.job_id)
    monkeypatch.setattr(service.store, "complete", original)
    completed = service.run_pending()[0]
    assert completed.state == JobState.COMPLETED and completed.attempt_count == 2
    assert (service.artifact_store.directory(job.run_id) / "manifest.json").read_bytes() == before


@settings(
    deadline=None, max_examples=8, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.integers(min_value=2, max_value=5))
def test_single_winner_claim_and_cancel(tmp_path: Path, contenders: int) -> None:
    root = tmp_path / str(contenders)
    service, spec = coordinator(root)
    service.submit(BatchBacktestSpec((spec,)))
    job = service.list_jobs()[0]
    if job.state != JobState.PENDING:
        service.recover_interrupted_runner()
        service.requeue(job.job_id)
    token = service.store.acquire_lease()
    barrier = Barrier(contenders)

    def claim() -> bool:
        barrier.wait()
        return service.store.claim(job.job_id, token)

    with ThreadPoolExecutor(max_workers=contenders) as pool:
        assert sum(pool.map(lambda _: claim(), range(contenders))) == 1
    with pytest.raises(JobNotCancellableError):
        service.cancel(job.job_id)
    service.store.release_lease(token)


@settings(
    deadline=None, max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.permutations((0, 1, 2)),
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.text(max_size=8),
        st.floats(allow_nan=False, allow_infinity=False),
        st.decimals(allow_nan=False, allow_infinity=False, places=3),
    ),
)
def test_canonical_batch_codec_and_ids(tmp_path: Path, order: list[int], value: object) -> None:
    _, spec = coordinator(tmp_path)
    parameter_spec = replace(spec, parameters=(("x", value),))
    assert decode_spec(encode_spec(parameter_spec)).fingerprint == parameter_spec.fingerprint
    members = tuple(replace(spec, random_seed=i) for i in range(3))
    a, b = BatchBacktestSpec(members), BatchBacktestSpec(tuple(members[i] for i in order))
    assert a == b and a.fingerprint == b.fingerprint
    engine = coordinator(tmp_path)[0].engine_identity
    from command_station.research.specs import BacktestRunId

    batch_id = BatchRunId.derive(a, engine)
    assert len({BatchJobId.derive(batch_id, BacktestRunId.derive(s, engine)) for s in members}) == 3
    with pytest.raises(ValueError):
        BatchBacktestSpec((spec, spec))


def test_codec_rejects_tamper_and_unknown_database(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    with pytest.raises(SpecCodecError):
        decode_spec(encode_spec(spec) + b"\n")
    service.submit(BatchBacktestSpec((spec,)))
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("UPDATE jobs SET spec=?", (b"{}",))
    service.worker_factory = lambda: pytest.fail("tamper must fail before worker")
    with pytest.raises(ResearchStoreError):
        service.run_pending()
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ResearchStoreError):
        LocalResearchStore(service.store.database_path)


def test_worker_reuse_and_boundary(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    worker = service.worker_factory()
    service.worker_factory = lambda: worker
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=1))))
    jobs = service.run_pending(policy=BatchExecutionPolicy(2))
    assert sorted(j.state for j in jobs) == [JobState.COMPLETED, JobState.FAILED]


@settings(
    deadline=None, max_examples=3, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.integers(min_value=1, max_value=4))
def test_worker_count_invariance(tmp_path: Path, workers: int) -> None:
    records = []
    for name, count in ((f"serial{workers}", 1), (f"parallel{workers}", workers)):
        service, spec = coordinator(tmp_path / name)
        service.submit(BatchBacktestSpec(tuple(replace(spec, random_seed=i) for i in range(3))))
        jobs = service.run_pending(policy=BatchExecutionPolicy(count))
        assert all(j.state == JobState.COMPLETED for j in jobs)
        records.append(tuple(r.deterministic() for r in service.list_results()))
    assert records[0] == records[1]


def test_multi_product_filter(tmp_path: Path) -> None:
    single, spec = setup(tmp_path, MultiProduct)

    def factory() -> BacktestService:
        catalog = StrategyArtifactCatalog()
        for descriptor, fn in single.strategies._entries.values():
            catalog.register(descriptor, fn)
        return BacktestService(
            datasets=single.datasets,
            strategies=catalog,
            artifacts=single.artifacts,
            engine_identity=single.engine_identity,
        )

    service = BatchBacktestService(
        store=LocalResearchStore(tmp_path / "index.sqlite"),
        artifact_store=single.artifacts,
        engine_identity=single.engine_identity,
        worker_factory=factory,
    )
    service.submit(BatchBacktestSpec((spec,)))
    service.run_pending()
    assert len(service.list_results(product_id="ETH-USD")) == 1
    assert len(service.list_results(dataset_version=spec.datasets[1].dataset_version.value)) == 1


@settings(
    deadline=None, max_examples=6, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.integers(min_value=0, max_value=100))
def test_cancel_claim_mutual_exclusion(tmp_path: Path, seed: int) -> None:
    service, spec = coordinator(tmp_path / str(seed))
    service.submit(BatchBacktestSpec((replace(spec, random_seed=seed),)))
    job = service.list_jobs()[0]
    if job.state != JobState.PENDING:
        service.recover_interrupted_runner()
        service.requeue(job.job_id)
    token = service.store.acquire_lease()
    barrier = Barrier(2)

    def claim() -> bool:
        barrier.wait()
        return service.store.claim(job.job_id, token)

    def cancel() -> bool:
        barrier.wait()
        try:
            return service.cancel(job.job_id)
        except JobNotCancellableError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(claim), pool.submit(cancel)
        assert a.result() != b.result()
    service.store.release_lease(token)
    assert service.get_result(job.run_id) is None


@pytest.mark.parametrize("boundary", ["engine", "root", "catalog"])
def test_worker_boundaries(tmp_path: Path, boundary: str) -> None:
    service, spec = coordinator(tmp_path)
    worker = service.worker_factory()
    second = service.worker_factory()
    if boundary == "engine":
        worker.engine_identity = replace(worker.engine_identity, package_version="other")
    elif boundary == "root":
        from command_station.research.artifacts import LocalBacktestArtifactStore

        worker.artifacts = LocalBacktestArtifactStore(tmp_path / "wrong")
    else:
        second.strategies = worker.strategies
    workers = iter((worker, second))
    service.worker_factory = lambda: next(workers)
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=1))))
    jobs = service.run_pending()
    assert sum(j.state == JobState.FAILED for j in jobs) == 1


def test_index_conflict_cannot_overwrite(tmp_path: Path) -> None:
    from command_station.research.store import ResultIndexConflictError

    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    completed = service.run_pending()[0]
    record = service.get_result(completed.run_id)
    assert record is not None
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=9))))
    pending = next(
        j for j in service.list_jobs(state=JobState.PENDING) if j.run_id == completed.run_id
    )
    token = service.store.acquire_lease()
    assert service.store.claim(pending.job_id, token)
    job = service.get_job(pending.job_id)
    with pytest.raises(ResultIndexConflictError):
        service.store.complete(job, token, replace(record, net_profit="123"))
    assert service.get_job(job.job_id).state == JobState.RUNNING
    assert service.get_result(job.run_id) == record
    service.store.complete(job, token, replace(record, indexed_at="operational only"))
    assert service.get_job(job.job_id).state == JobState.COMPLETED
    service.store.release_lease(token)


def test_database_hardlink_and_schema_tamper(tmp_path: Path) -> None:
    import os

    service, _ = coordinator(tmp_path)
    linked = tmp_path / "linked.sqlite"
    os.link(service.store.database_path, linked)
    with pytest.raises(ResearchStoreError):
        LocalResearchStore(linked)
    linked.unlink()
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("DROP TABLE result_products")
    with pytest.raises(ResearchStoreError):
        service.run_pending()


def test_shared_strategy_across_fresh_catalogs_rejected(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    original_factory = service.worker_factory
    first = original_factory()
    descriptor, fn = next(iter(first.strategies._entries.values()))
    shared = fn()

    def factory() -> BacktestService:
        worker = original_factory()
        catalog = StrategyArtifactCatalog()
        catalog.register(descriptor, lambda: shared)
        worker.strategies = catalog
        return worker

    service.worker_factory = factory
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=1))))
    jobs = service.run_pending(policy=BatchExecutionPolicy(2))
    assert sum(j.state == JobState.FAILED for j in jobs) == 1
