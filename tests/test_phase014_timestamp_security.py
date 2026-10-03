"""Timestamp integrity must precede durable terminal mutations."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from command_station.research.jobs import BatchBacktestSpec, BatchJobId, JobView
from command_station.research.store import ResearchStoreError
from tests.test_research_batches import coordinator


@pytest.mark.parametrize("operation", ["fail", "recover"])
def test_corrupt_running_timestamp_blocks_terminal_mutation(tmp_path: Path, operation: str) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    token = service.store.acquire_lease()
    assert service.store.claim(pending.job_id, token)
    with sqlite3.connect(service.store.database_path) as db:
        # RUNNING must have no finish; this is both malformed and incoherent.
        db.execute("UPDATE jobs SET finished_at=?", (b"corrupt",))
        before = db.execute("SELECT * FROM jobs").fetchall()
        lease = db.execute("SELECT * FROM runner_lease").fetchall()
    with pytest.raises(ResearchStoreError):
        service.get_job(pending.job_id)
    with pytest.raises(ResearchStoreError):
        if operation == "fail":
            service.store.fail(pending.job_id, token, ValueError("ordinary failure"))
        else:
            service.recover_interrupted_runner()
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT * FROM jobs").fetchall() == before
        assert db.execute("SELECT * FROM runner_lease").fetchall() == lease


@pytest.mark.parametrize("operation", ["claim", "cancel", "requeue"])
def test_lifecycle_validates_timestamp_inside_mutation_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    job = service.list_jobs()[0]
    if operation == "requeue":
        assert service.cancel(job.job_id)
    token = service.store.acquire_lease()
    original = service.store.get_job
    snapshot: dict[str, list[tuple[object, ...]]] = {}

    def read_then_corrupt(job_id: BatchJobId) -> JobView:
        view = original(job_id)
        # A separate metadata writer commits between preflight and BEGIN IMMEDIATE.
        with sqlite3.connect(service.store.database_path) as db:
            db.execute("UPDATE jobs SET finished_at=?", (b"corrupt",))
            snapshot["jobs"] = db.execute("SELECT * FROM jobs").fetchall()
            snapshot["lease"] = db.execute("SELECT * FROM runner_lease").fetchall()
        return view

    monkeypatch.setattr(service.store, "get_job", read_then_corrupt)
    with pytest.raises(ResearchStoreError):
        if operation == "claim":
            service.store.claim(job.job_id, token)
        elif operation == "cancel":
            service.cancel(job.job_id)
        else:
            service.requeue(job.job_id)
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT * FROM jobs").fetchall() == snapshot["jobs"]
        assert db.execute("SELECT * FROM runner_lease").fetchall() == snapshot["lease"]


def test_recovery_corruption_rolls_back_every_running_job(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=9))))
    jobs = service.list_jobs()
    token = service.store.acquire_lease()
    for job in jobs:
        assert service.store.claim(job.job_id, token)
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("UPDATE jobs SET started_at=NULL WHERE job_id=?", (jobs[0].job_id.value,))
        before = db.execute("SELECT * FROM jobs ORDER BY job_id").fetchall()
        lease = db.execute("SELECT * FROM runner_lease").fetchall()
    with pytest.raises(ResearchStoreError):
        service.recover_interrupted_runner()
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT * FROM jobs ORDER BY job_id").fetchall() == before
        assert db.execute("SELECT * FROM runner_lease").fetchall() == lease
