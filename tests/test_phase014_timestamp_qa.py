"""Independent terminal timestamp and successful retry regression evidence."""

from pathlib import Path

import pytest

from command_station.research import store as store_module
from command_station.research.jobs import BatchBacktestSpec, JobState
from command_station.research.store import JobTransitionError, LocalResearchStore
from tests.test_research_batches import coordinator


def test_successful_retry_replaces_current_attempt_times_and_terminal_noops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = "2026-10-03T12:00:00+00:00"
    first_start = "2026-10-03T12:01:00+00:00"
    first_finish = "2026-10-03T12:02:00+00:00"
    retry_time = "2026-10-03T12:03:00+00:00"
    monkeypatch.setattr(store_module, "now", lambda: created)
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    token = service.store.acquire_lease()
    monkeypatch.setattr(store_module, "now", lambda: first_start)
    assert service.store.claim(pending.job_id, token)
    monkeypatch.setattr(store_module, "now", lambda: first_finish)
    service.store.fail(pending.job_id, token, ValueError("first attempt"))
    failed = service.get_job(pending.job_id)
    with pytest.raises(JobTransitionError):
        service.store.fail(pending.job_id, token, ValueError("lost claim"))
    assert service.get_job(pending.job_id) == failed
    service.store.release_lease(token)
    service.requeue(pending.job_id)
    monkeypatch.setattr(store_module, "now", lambda: retry_time)
    completed = service.run_pending()[0]
    assert completed.state == JobState.COMPLETED
    assert completed.attempt_count == 2
    assert completed.created_at == created
    assert completed.started_at == completed.finished_at == retry_time
    assert completed.job_id == pending.job_id
    assert completed.batch_id == pending.batch_id
    assert completed.run_id == pending.run_id
    assert completed.failure_code is None and completed.failure_message is None
    monkeypatch.setattr(store_module, "now", lambda: "2026-10-03T12:04:00+00:00")
    assert not service.cancel(completed.job_id)
    with pytest.raises(JobTransitionError):
        service.requeue(completed.job_id)
    assert service.recover_interrupted_runner() == 0
    assert LocalResearchStore(service.store.database_path).get_job(completed.job_id) == completed
