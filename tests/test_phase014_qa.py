"""Independent durable-row, codec, and parallel parameter/state evidence."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from command_station.domain import Candle, Side, Timeframe
from command_station.execution import BaseQuantity
from command_station.research import (
    BacktestService,
    BatchBacktestService,
    BatchBacktestSpec,
    BatchExecutionPolicy,
    BatchJobId,
    BatchRunId,
    JobState,
    LocalResearchStore,
    StrategyArtifactCatalog,
)
from command_station.research.artifacts import BacktestReproducibilityError
from command_station.research.batches import _DispatchFence
from command_station.research.jobs import JobView
from command_station.research.spec_codec import SpecCodecError, decode_spec, encode_spec
from command_station.research.specs import BacktestRunId, canonical_json
from command_station.research.store import (
    JobTransitionError,
    ResearchStoreError,
    ResultIndexConflictError,
)
from command_station.strategy import (
    BarSubscription,
    IntParam,
    StateField,
    StateType,
    Strategy,
    StrategyContext,
    StrategyDefinition,
)
from tests.research_fixtures import BTC, setup
from tests.test_research_batches import coordinator


class ParameterTrade(Strategy):
    definition = StrategyDefinition(
        "qa-parameter",
        (BarSubscription(BTC, Timeframe.ONE_MINUTE, True),),
        parameters=(IntParam("quantity", minimum=1, maximum=3),),
        state_schema=(StateField("bars", StateType.INT, 0),),
    )

    def __init__(self, barrier: Barrier | None = None) -> None:
        self.barrier = barrier
        self.contexts: list[StrategyContext] = []

    def on_start(self, ctx: StrategyContext) -> None:
        assert ctx.state.get("bars") == 0
        self.contexts.append(ctx)
        if self.barrier:
            self.barrier.wait(timeout=10)

    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        count = ctx.state.get("bars")
        assert type(count) is int
        quantity = ctx.parameters.get("quantity")
        assert type(quantity) is int
        if count == 0:
            ctx.orders.market(
                BTC, Side.BUY, BaseQuantity(str(quantity)), max_quote_reservation="400"
            )
        ctx.state.set("bars", count + 1)


@settings(
    deadline=None, max_examples=3, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.permutations((1, 2, 3)))
def test_parallel_parameter_state_and_actual_rows(tmp_path: Path, quantities: list[int]) -> None:
    root = tmp_path / "".join(map(str, quantities))
    single, base = setup(root, ParameterTrade)
    descriptor = next(iter(single.strategies._entries.values()))[0]
    barrier = Barrier(3)
    issued: list[ParameterTrade] = []

    def factory() -> BacktestService:
        catalog = StrategyArtifactCatalog()

        def strategy() -> Strategy:
            instance = ParameterTrade(barrier)
            issued.append(instance)
            return instance

        catalog.register(descriptor, strategy)
        return BacktestService(
            datasets=single.datasets,
            strategies=catalog,
            artifacts=single.artifacts,
            engine_identity=single.engine_identity,
        )

    service = BatchBacktestService(
        store=LocalResearchStore(root / "qa.sqlite"),
        artifact_store=single.artifacts,
        engine_identity=single.engine_identity,
        worker_factory=factory,
    )
    members = tuple(replace(base, parameters=(("quantity", q),)) for q in quantities)
    service.submit(BatchBacktestSpec(members))
    # Hypothesis can repeat a permutation; operationally idempotent submissions must remain safe.
    if service.list_jobs(state=JobState.PENDING):
        jobs = service.run_pending(policy=BatchExecutionPolicy(3))
        assert len(issued) == 3
        assert len({id(s.contexts[0].state) for s in issued}) == 3
        assert len({id(s.contexts[0].parameters) for s in issued}) == 3
        assert {s.contexts[0].parameters.get("quantity") for s in issued} == {1, 2, 3}
    else:
        jobs = service.list_jobs()
    for job in jobs:
        assert job.state == JobState.COMPLETED
        record = service.get_result(job.run_id)
        direct = single.run(job.spec)
        assert record is not None and record.result_fingerprint == direct.result_fingerprint
        manifest = service.artifact_store.load_manifest(job.run_id)
        directory = service.artifact_store.directory(job.run_id)
        assert len(manifest.artifacts) == 8
        assert (directory / "spec.json").read_bytes() == encode_spec(job.spec)
        assert record.manifest_fingerprint == manifest.fingerprint
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM runner_lease").fetchone()[0] == 0
        rows = db.execute(
            "SELECT state,attempt_count,spec,result_fingerprint,manifest_fingerprint FROM jobs"
        ).fetchall()
        assert len(rows) == 3
        for state, attempts, persisted, result_hash, manifest_hash in rows:
            assert state == "COMPLETED" and attempts == 1
            assert encode_spec(decode_spec(persisted)) == persisted
            assert len(result_hash) == len(manifest_hash) == 64
        assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM result_products").fetchone()[0] == 3


@settings(
    deadline=None, max_examples=8, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.sampled_from(("PENDING", "RUNNING", "COMPLETED")))
def test_illegal_requeue_property(tmp_path: Path, state: str) -> None:
    service, spec = coordinator(tmp_path / state)
    service.submit(BatchBacktestSpec((spec,)))
    job = service.list_jobs()[0]
    if state == "RUNNING" and job.state == JobState.PENDING:
        token = service.store.acquire_lease()
        assert service.store.claim(job.job_id, token)
        service.store.release_lease(token)
    if state == "COMPLETED" and job.state == JobState.PENDING:
        service.run_pending()
    before = service.get_job(job.job_id)
    with pytest.raises(JobTransitionError):
        service.requeue(job.job_id)
    assert service.get_job(job.job_id) == before


@pytest.mark.parametrize(
    "field,value",
    [("random_seed", True), ("schema_version", 2), ("random_seed", 1.0)],
)
def test_codec_wrong_scalar_schema(tmp_path: Path, field: str, value: object) -> None:
    _, spec = coordinator(tmp_path)
    raw = json.loads(encode_spec(spec))
    raw[field] = value
    with pytest.raises(SpecCodecError):
        decode_spec(canonical_json(raw))


def test_transaction_failure_rolls_back_result_and_preserves_bundle(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    token = service.store.acquire_lease()
    assert service.store.claim(pending.job_id, token)
    job = service.get_job(pending.job_id)
    result = service.worker_factory().run(spec)
    before = (service.artifact_store.directory(job.run_id) / "manifest.json").read_bytes()
    record = service._verified_record(job)
    # A conflict at the completion boundary must leave the whole metadata transaction untouched.
    with pytest.raises(Exception, match="completion identity mismatch"):
        service.store.complete(job, token, replace(record, spec_fingerprint="f" * 64))
    assert service.get_job(job.job_id).state == JobState.RUNNING
    assert service.get_result(job.run_id) is None
    assert result.artifact_manifest is not None
    assert service.recover_interrupted_runner() == 1
    service.requeue(job.job_id)
    assert service.run_pending()[0].state == JobState.COMPLETED
    assert (service.artifact_store.directory(job.run_id) / "manifest.json").read_bytes() == before


@settings(
    deadline=None, max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.integers(min_value=0, max_value=100), st.booleans())
def test_requeue_and_index_properties(tmp_path: Path, seed: int, cancelled: bool) -> None:
    service, spec = coordinator(tmp_path / f"{seed}-{cancelled}")
    spec = replace(spec, random_seed=seed)
    batch = service.submit(BatchBacktestSpec((spec,)))
    job = service.list_jobs(batch_id=batch.batch_id)[0]
    if job.state == JobState.COMPLETED:
        return
    original_factory = service.worker_factory
    if cancelled:
        assert service.cancel(job.job_id)
    else:

        def unavailable() -> BacktestService:
            raise RuntimeError("deliberate worker factory failure")

        service.worker_factory = unavailable
        assert service.run_pending()[0].state == JobState.FAILED
        service.worker_factory = original_factory
    assert service.get_result(job.run_id) is None
    before = service.get_job(job.job_id)
    service.requeue(job.job_id)
    after = service.get_job(job.job_id)
    assert (after.job_id, after.run_id, after.attempt_count) == (
        before.job_id,
        before.run_id,
        before.attempt_count,
    )
    assert service.run_pending()[0].state == JobState.COMPLETED
    record = service.get_result(job.run_id)
    assert record is not None
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=seed + 101))))
    pending = next(j for j in service.list_jobs(state=JobState.PENDING) if j.run_id == job.run_id)
    token = service.store.acquire_lease()
    assert service.store.claim(pending.job_id, token)
    claimed = service.get_job(pending.job_id)
    with pytest.raises(ResultIndexConflictError):
        service.store.complete(claimed, token, replace(record, net_profit=str(seed + 123)))
    assert service.get_job(claimed.job_id).state == JobState.RUNNING
    assert service.get_result(job.run_id) == record
    service.store.complete(claimed, token, replace(record, indexed_at=f"operational-{seed}"))
    assert service.get_result(job.run_id) == record
    assert service.get_job(claimed.job_id).state == JobState.COMPLETED
    assert (
        service.artifact_store.load_manifest(job.run_id).fingerprint == record.manifest_fingerprint
    )
    service.store.release_lease(token)


def test_multiple_strategy_result_filters(tmp_path: Path) -> None:
    single, first = setup(tmp_path)
    other, second = setup(tmp_path, ParameterTrade)
    second = replace(second, parameters=(("quantity", 2),))

    def factory() -> BacktestService:
        catalog = StrategyArtifactCatalog()
        for source in (single, other):
            for descriptor, fn in source.strategies._entries.values():
                catalog.register(descriptor, fn)
        return BacktestService(
            datasets=single.datasets,
            strategies=catalog,
            artifacts=single.artifacts,
            engine_identity=single.engine_identity,
        )

    service = BatchBacktestService(
        store=LocalResearchStore(tmp_path / "multistrategy.sqlite"),
        artifact_store=single.artifacts,
        engine_identity=single.engine_identity,
        worker_factory=factory,
    )
    service.submit(BatchBacktestSpec((first, replace(first, random_seed=9), second)))
    assert all(j.state == JobState.COMPLETED for j in service.run_pending())
    assert len(service.list_results(strategy_id="research")) == 2
    assert len(service.list_results(strategy_id="qa-parameter", product_id="BTC-USD")) == 1
    assert len(service.list_results(limit=1, offset=1)) == 1
    assert service.list_results(strategy_id="' OR 1=1 --") == ()


def test_integrity_failure_stops_unstarted_financial_jobs(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    cached = service.run_pending()[0]
    # Choose canonical dispatch order explicitly; this is not a scheduling race.
    for seed in range(1, 100):
        later = replace(spec, random_seed=seed)
        batch_spec = BatchBacktestSpec((spec, later))
        batch_id = BatchRunId.derive(batch_spec, service.engine_identity)
        first_id = BatchJobId.derive(batch_id, cached.run_id)
        later_id = BatchJobId.derive(batch_id, BacktestRunId.derive(later, service.engine_identity))
        if first_id.value < later_id.value:
            break
    else:
        pytest.fail("could not construct canonical corrupt-first fixture")
    service.submit(batch_spec)
    (service.artifact_store.directory(cached.run_id) / "summary.json").write_bytes(b"{}")
    original = service.worker_factory
    calls: list[int] = []

    def observed_factory() -> BacktestService:
        calls.append(1)
        return original()

    service.worker_factory = observed_factory
    with pytest.raises(BacktestReproducibilityError):
        service.run_pending(batch_id=batch_id, policy=BatchExecutionPolicy(1))
    assert calls == [], "integrity failure must fence financial work that has not started"
    assert service.get_job(later_id).state == JobState.PENDING
    assert service.get_result(BacktestRunId.derive(later, service.engine_identity)) is None


def test_integrity_stop_preserves_admitted_parallel_simulation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    cached = service.run_pending()[0]
    for seed in range(1, 100):
        members = (spec, replace(spec, random_seed=seed), replace(spec, random_seed=seed + 100))
        candidate = BatchBacktestSpec(members)
        batch_id = BatchRunId.derive(candidate, service.engine_identity)
        ordered = sorted(
            (
                BatchJobId.derive(batch_id, BacktestRunId.derive(s, service.engine_identity)).value,
                s,
            )
            for s in members
        )
        if spec in (ordered[0][1], ordered[1][1]):
            break
    else:
        pytest.fail("could not construct cached job among first two")
    service.submit(candidate)
    admitted_spec = next(s for _, s in ordered[:2] if s != spec)
    unstarted_id = BatchJobId(ordered[2][0])
    (service.artifact_store.directory(cached.run_id) / "summary.json").write_bytes(b"{}")
    financial_started, integrity_stopped = Event(), Event()
    original_run = BacktestService.run
    original_verify = service._verified_record
    original_guard = service._execute_guarded

    def run(worker: BacktestService, experiment: object) -> object:
        # Keep the real admitted financial run alive until the cache failure sets the fence.
        assert experiment == admitted_spec
        financial_started.set()
        assert integrity_stopped.wait(timeout=10)
        return original_run(worker, admitted_spec)

    def verify(job: JobView) -> object:
        if job.run_id == cached.run_id:
            assert financial_started.wait(timeout=10)
        return original_verify(job)

    def guard(job: JobView, token: str, fence: _DispatchFence) -> None:
        try:
            original_guard(job, token, fence)
        except BacktestReproducibilityError:
            assert fence.stopped.is_set()
            integrity_stopped.set()
            raise

    monkeypatch.setattr(BacktestService, "run", run)
    monkeypatch.setattr(service, "_verified_record", verify)
    monkeypatch.setattr(service, "_execute_guarded", guard)
    with pytest.raises(BacktestReproducibilityError):
        service.run_pending(batch_id=batch_id, policy=BatchExecutionPolicy(2))
    admitted_id = BatchJobId.derive(
        batch_id, BacktestRunId.derive(admitted_spec, service.engine_identity)
    )
    admitted = service.get_job(admitted_id)
    assert admitted.state == JobState.COMPLETED
    assert service.get_result(admitted.run_id) is not None
    service.artifact_store.load_manifest(admitted.run_id)
    assert service.get_job(unstarted_id).state == JobState.PENDING
    assert service.get_job(unstarted_id).attempt_count == 0


@settings(
    deadline=None, max_examples=6, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.integers(min_value=0, max_value=100), st.sampled_from(("schema", "seed", "extra")))
def test_generated_persisted_spec_tamper_precedes_execution(
    tmp_path: Path, seed: int, attack: str
) -> None:
    service, spec = coordinator(tmp_path / f"tamper-{seed}-{attack}")
    spec = replace(spec, random_seed=seed)
    service.submit(BatchBacktestSpec((spec,)))
    raw = json.loads(encode_spec(spec))
    if attack == "schema":
        raw["schema_version"] = seed + 2
    elif attack == "seed":
        raw["random_seed"] = True
    else:
        raw["period"]["ignored"] = seed
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("UPDATE jobs SET spec=?", (canonical_json(raw),))
    service.worker_factory = lambda: pytest.fail("tampered persisted spec reached worker")
    try:
        with pytest.raises(ResearchStoreError):
            service.run_pending()
        with sqlite3.connect(service.store.database_path) as db:
            assert db.execute("SELECT state,attempt_count FROM jobs").fetchone() == ("PENDING", 0)
            assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0
    finally:
        # Hypothesis may repeat an example against the same fixture directory.
        with sqlite3.connect(service.store.database_path) as db:
            db.execute("UPDATE jobs SET spec=?", (encode_spec(spec),))
