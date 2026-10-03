"""Current-attempt UTC metadata stays outside deterministic research truth."""

import sqlite3
from pathlib import Path

import pytest

from command_station.research import store as store_module
from command_station.research.jobs import BatchBacktestSpec, JobState
from command_station.research.store import LocalResearchStore, ResearchStoreError
from tests.test_research_batches import coordinator

CREATED = "2026-10-03T12:00:00+00:00"
STARTED = "2026-10-03T12:01:00.123456+00:00"
FINISHED = "2026-10-03T12:02:00+00:00"


def test_submission_pending_and_reopen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module, "now", lambda: CREATED)
    service, spec = coordinator(tmp_path)
    batch = service.submit(BatchBacktestSpec((spec,)))
    job = service.list_jobs()[0]
    assert job.state == JobState.PENDING and job.attempt_count == 0
    assert job.created_at == batch.created_at == CREATED
    assert job.started_at is None and job.finished_at is None
    reopened = LocalResearchStore(service.store.database_path)
    assert reopened.get_job(job.job_id) == job
    assert service.submit(BatchBacktestSpec((spec,))) == batch
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_atomic_claim_running_and_lost_claim_preserves_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "now", lambda: CREATED)
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    token = service.store.acquire_lease()
    monkeypatch.setattr(store_module, "now", lambda: STARTED)
    assert service.store.claim(pending.job_id, token)
    running = service.get_job(pending.job_id)
    assert running.state == JobState.RUNNING and running.attempt_count == 1
    assert running.created_at == CREATED and running.started_at == STARTED
    assert running.finished_at is None
    monkeypatch.setattr(store_module, "now", lambda: FINISHED)
    assert not service.store.claim(pending.job_id, token)
    assert service.get_job(pending.job_id) == running


def test_completed_keeps_claim_start_and_sets_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "now", lambda: CREATED)
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    original_complete = service.store.complete

    def complete(*args: object) -> None:
        monkeypatch.setattr(store_module, "now", lambda: FINISHED)
        original_complete(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(service.store, "complete", complete)
    monkeypatch.setattr(store_module, "now", lambda: STARTED)
    job = service.run_pending()[0]
    assert job.state == JobState.COMPLETED and job.attempt_count == 1
    assert (job.created_at, job.started_at, job.finished_at) == (CREATED, STARTED, FINISHED)
    assert LocalResearchStore(service.store.database_path).get_job(job.job_id) == job


def test_ordinary_worker_failure_finishes_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "now", lambda: CREATED)
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))

    def broken_worker() -> None:
        monkeypatch.setattr(store_module, "now", lambda: FINISHED)
        raise ValueError("ordinary worker failure")

    monkeypatch.setattr(service, "worker_factory", broken_worker)
    monkeypatch.setattr(store_module, "now", lambda: STARTED)
    job = service.run_pending()[0]
    assert job.state == JobState.FAILED and job.failure_code == "ValueError"
    assert job.attempt_count == 1
    assert (job.created_at, job.started_at, job.finished_at) == (CREATED, STARTED, FINISHED)


def test_pending_cancellation_has_no_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module, "now", lambda: CREATED)
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    monkeypatch.setattr(store_module, "now", lambda: FINISHED)
    assert service.cancel(pending.job_id)
    job = service.get_job(pending.job_id)
    assert job.state == JobState.CANCELLED and job.attempt_count == 0
    assert (job.created_at, job.started_at, job.finished_at) == (CREATED, None, FINISHED)


def test_explicit_recovery_finishes_interrupted_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "now", lambda: CREATED)
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    token = service.store.acquire_lease()
    monkeypatch.setattr(store_module, "now", lambda: STARTED)
    assert service.store.claim(pending.job_id, token)
    monkeypatch.setattr(store_module, "now", lambda: FINISHED)
    assert service.recover_interrupted_runner() == 1
    job = service.get_job(pending.job_id)
    assert job.state == JobState.FAILED and job.failure_code == "INTERRUPTED"
    assert job.attempt_count == 1
    assert (job.created_at, job.started_at, job.finished_at) == (CREATED, STARTED, FINISHED)
    assert service.recover_interrupted_runner() == 0
    assert service.get_job(job.job_id) == job


@pytest.mark.parametrize("terminal", ["failed", "cancelled"])
def test_requeue_clears_attempt_times_preserving_identity_and_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: str
) -> None:
    monkeypatch.setattr(store_module, "now", lambda: CREATED)
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    token = service.store.acquire_lease()
    monkeypatch.setattr(store_module, "now", lambda: STARTED)
    assert service.store.claim(pending.job_id, token)
    service.store.fail(pending.job_id, token, ValueError("first attempt"))
    service.store.release_lease(token)
    if terminal == "cancelled":
        service.requeue(pending.job_id)
        assert service.cancel(pending.job_id)
    before = service.get_job(pending.job_id)
    service.requeue(pending.job_id)
    after = service.get_job(pending.job_id)
    assert after.state == JobState.PENDING
    assert after.attempt_count == before.attempt_count == 1
    assert (after.job_id, after.batch_id, after.run_id, after.created_at) == (
        before.job_id,
        before.batch_id,
        before.run_id,
        before.created_at,
    )
    assert after.started_at is None and after.finished_at is None
    assert after.failure_code is None and after.failure_message is None
    monkeypatch.setattr(store_module, "now", lambda: FINISHED)
    token = service.store.acquire_lease()
    assert service.store.claim(after.job_id, token)
    retried = service.get_job(after.job_id)
    assert retried.attempt_count == 2 and retried.started_at == FINISHED
    assert retried.finished_at is None and retried.created_at == CREATED


def test_operational_times_do_not_change_financial_artifacts_or_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs, records, manifests = [], [], []
    for name, timestamp in (("first", CREATED), ("second", FINISHED)):
        monkeypatch.setattr(store_module, "now", lambda timestamp=timestamp: timestamp)
        service, spec = coordinator(tmp_path / name)
        service.submit(BatchBacktestSpec((spec,)))
        job = service.run_pending()[0]
        jobs.append(job)
        record = service.get_result(job.run_id)
        assert record is not None
        records.append(record)
        manifests.append(service.artifact_store.load_manifest(job.run_id))
    assert jobs[0].created_at != jobs[1].created_at
    assert jobs[0].started_at != jobs[1].started_at
    assert jobs[0].finished_at != jobs[1].finished_at
    assert (jobs[0].job_id, jobs[0].batch_id, jobs[0].run_id, jobs[0].spec.fingerprint) == (
        jobs[1].job_id,
        jobs[1].batch_id,
        jobs[1].run_id,
        jobs[1].spec.fingerprint,
    )
    assert records[0].deterministic() == records[1].deterministic()
    assert manifests[0] == manifests[1]


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_at", "invalid"),
        ("created_at", "2026-10-03T12:00:00"),
        ("created_at", "2026-10-03T12:00:00Z"),
        ("created_at", "2026-10-03T13:00:00+01:00"),
        ("created_at", "2026-10-03 12:00:00+00:00"),
        ("created_at", "2026-02-30T12:00:00+00:00"),
        ("started_at", "invalid"),
        ("finished_at", b"invalid"),
        ("started_at", STARTED),
        ("finished_at", FINISHED),
        ("state", "RUNNING"),
        ("state", "COMPLETED"),
        ("state", "FAILED"),
        ("state", "CANCELLED"),
    ],
)
def test_malformed_or_incoherent_pending_metadata_fails_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    service, spec = coordinator(tmp_path)
    batch = service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    with sqlite3.connect(service.store.database_path) as db:
        db.execute(f"UPDATE jobs SET {field}=?", (value,))
    with pytest.raises(ResearchStoreError, match="invalid persisted job"):
        service.get_job(pending.job_id)
    with pytest.raises(ResearchStoreError, match="invalid persisted job"):
        service.list_jobs()
    with pytest.raises(ResearchStoreError, match="invalid persisted job"):
        service.get_batch(batch.batch_id)
    if field != "state":
        service.worker_factory = lambda: pytest.fail("metadata corruption must start no worker")
        with pytest.raises(ResearchStoreError, match="invalid persisted job"):
            service.run_pending()


@pytest.mark.parametrize(
    "state,attempts,started,finished",
    [
        ("RUNNING", 0, STARTED, None),
        ("RUNNING", 1, None, None),
        ("RUNNING", 1, STARTED, FINISHED),
        ("COMPLETED", 0, STARTED, FINISHED),
        ("COMPLETED", 1, STARTED, None),
        ("FAILED", 1, None, FINISHED),
        ("FAILED", 1, STARTED, None),
        ("CANCELLED", 1, STARTED, FINISHED),
        ("CANCELLED", 1, None, None),
    ],
)
def test_tampered_current_attempt_state_coherence(
    tmp_path: Path, state: str, attempts: int, started: str | None, finished: str | None
) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    with sqlite3.connect(service.store.database_path) as db:
        db.execute(
            "UPDATE jobs SET state=?,attempt_count=?,started_at=?,finished_at=?",
            (state, attempts, started, finished),
        )
    with pytest.raises(ResearchStoreError, match="invalid persisted job"):
        service.list_jobs()
