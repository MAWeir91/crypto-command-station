"""Adversarial checks of durable metadata and coordinator authority."""

import json
import os
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from command_station.research.jobs import BatchBacktestSpec, JobState
from command_station.research.spec_codec import SpecCodecError, decode_spec, encode_spec
from command_station.research.specs import canonical_json
from command_station.research.store import LocalResearchStore, ResearchStoreError, RunnerLeaseError
from tests.test_research_batches import coordinator


def test_result_record_cannot_disagree_with_sql_identity(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=7))))
    jobs = service.run_pending()
    first, second = jobs
    second_record = service.get_result(second.run_id)
    assert second_record is not None
    with sqlite3.connect(service.store.database_path) as db:
        db.execute(
            "UPDATE results SET record=? WHERE run_id=?",
            (canonical_json(second_record), first.run_id.value),
        )
    with pytest.raises(ResearchStoreError):
        service.get_result(first.run_id)
    with pytest.raises(ResearchStoreError):
        service.list_results()


@pytest.mark.parametrize("column", ["strategy", "product", "dataset"])
def test_result_filter_metadata_corruption_fails_closed(tmp_path: Path, column: str) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    job = service.run_pending()[0]
    with sqlite3.connect(service.store.database_path) as db:
        if column == "strategy":
            db.execute("UPDATE results SET strategy_id=?", ("forged-strategy",))
        elif column == "product":
            db.execute("UPDATE result_products SET product_id=?", ("FORGED-USD",))
        else:
            db.execute("UPDATE result_products SET dataset_version=?", ("f" * 64,))
    with pytest.raises(ResearchStoreError):
        service.get_result(job.run_id)
    with pytest.raises(ResearchStoreError):
        if column == "strategy":
            service.list_results(strategy_id="forged-strategy")
        elif column == "product":
            service.list_results(product_id="FORGED-USD")
        else:
            service.list_results(dataset_version="f" * 64)


@pytest.mark.parametrize("hidden_by", ["filter", "offset", "empty_page"])
def test_hidden_result_corruption_is_validated_before_query(tmp_path: Path, hidden_by: str) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=9))))
    first, second = service.run_pending()
    with sqlite3.connect(service.store.database_path) as db:
        db.execute(
            "UPDATE results SET strategy_id=? WHERE run_id=?",
            ("hidden-corruption", first.run_id.value),
        )
    with pytest.raises(ResearchStoreError):
        service.get_result(second.run_id)
    with pytest.raises(ResearchStoreError):
        if hidden_by == "filter":
            service.list_results(strategy_id="does-not-match-any-row")
        elif hidden_by == "offset":
            service.list_results(limit=1, offset=1)
        else:
            service.list_results(limit=1, offset=100)


def test_orphan_product_relationship_blocks_queries_and_completion(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    token = service.store.acquire_lease()
    assert service.store.claim(pending.job_id, token)
    job = service.get_job(pending.job_id)
    service.worker_factory().run(spec)
    record = service._verified_record(job)
    # External tamper can bypass SQLite's per-connection foreign-key setting.
    with sqlite3.connect(service.store.database_path) as db:
        db.execute("INSERT INTO result_products VALUES(?,?,?)", ("f" * 64, "BTC-USD", "e" * 64))
    with pytest.raises(ResearchStoreError):
        service.get_result(job.run_id)
    with pytest.raises(ResearchStoreError):
        service.list_results(strategy_id="nonexistent", offset=100)
    with pytest.raises(ResearchStoreError):
        service.store.complete(job, token, record)
    with sqlite3.connect(service.store.database_path) as db:
        assert db.execute("SELECT count(*) FROM results").fetchone()[0] == 0
    assert service.get_job(job.job_id).state == JobState.RUNNING
    service.store.release_lease(token)


def test_consistent_but_forged_cache_record_fails_artifact_verification(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    completed = service.run_pending()[0]
    record = service.get_result(completed.run_id)
    assert record is not None
    with sqlite3.connect(service.store.database_path) as db:
        db.execute(
            "UPDATE results SET record=? WHERE run_id=?",
            (canonical_json(replace(record, net_profit="999")), completed.run_id.value),
        )
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=10))))
    unrelated = next(j for j in service.list_jobs(state=JobState.PENDING) if j.spec != spec)
    assert service.cancel(unrelated.job_id)
    service.worker_factory = lambda: pytest.fail("forged cache reached worker")
    with pytest.raises(ResearchStoreError):
        service.run_pending()
    assert any(j.state == JobState.RUNNING for j in service.list_jobs())


@pytest.mark.parametrize("field", ["job_id", "run_id", "spec_fingerprint"])
def test_forged_persisted_identity_prevents_worker(tmp_path: Path, field: str) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    with sqlite3.connect(service.store.database_path) as db:
        statements = {
            "job_id": "UPDATE jobs SET job_id=?",
            "run_id": "UPDATE jobs SET run_id=?",
            "spec_fingerprint": "UPDATE jobs SET spec_fingerprint=?",
        }
        db.execute(statements[field], ("f" * 64,))
    service.worker_factory = lambda: pytest.fail("forged identity reached financial worker")
    with pytest.raises(ResearchStoreError):
        service.run_pending()


@pytest.mark.parametrize(
    "attack", ["seed_bool", "parameter_type", "extra", "nonfinite", "duplicate"]
)
def test_strict_codec_rejects_malformed_canonical_input(tmp_path: Path, attack: str) -> None:
    _, spec = coordinator(tmp_path)
    raw = json.loads(encode_spec(replace(spec, parameters=(("p", 1),))))
    if attack == "seed_bool":
        raw["random_seed"] = True
    elif attack == "parameter_type":
        raw["parameters"][0]["value"] = True
    elif attack == "extra":
        raw["account"]["extra"] = "ignored?"
    elif attack == "nonfinite":
        raw["parameters"][0] = {"name": "p", "type": "Decimal", "value": "NaN"}
    else:
        encoded = encode_spec(spec)
        duplicate = b'{"random_seed":0,' + encoded[1:]
        with pytest.raises(SpecCodecError):
            decode_spec(duplicate)
        return
    with pytest.raises(SpecCodecError):
        decode_spec(canonical_json(raw))


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_hardlinked_sqlite_sidecars_rejected(tmp_path: Path, suffix: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    victim = tmp_path / "victim"
    victim.write_bytes(b"untouched external bytes")
    os.link(victim, Path(str(root / "index.sqlite") + suffix))
    with pytest.raises(ResearchStoreError):
        LocalResearchStore(root / "index.sqlite")
    assert victim.read_bytes() == b"untouched external bytes"


def test_database_symlink_parent_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable")
        raise
    try:
        with pytest.raises(ResearchStoreError):
            LocalResearchStore(linked / "index.sqlite")
        assert not (target / "index.sqlite").exists()
    finally:
        linked.unlink()


def test_traversal_database_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResearchStoreError):
        LocalResearchStore(tmp_path / "child" / ".." / "index.sqlite")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
def test_database_junction_parent_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "junction"
    creation = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(linked), str(target)],
        capture_output=True,
        check=True,
    )
    assert creation.returncode == 0 and linked.is_junction()
    try:
        with pytest.raises(ResearchStoreError):
            LocalResearchStore(linked / "index.sqlite")
        assert not (target / "index.sqlite").exists()
    finally:
        os.rmdir(linked)


def test_recovery_completion_race_has_one_terminal_winner(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec,)))
    pending = service.list_jobs()[0]
    token = service.store.acquire_lease()
    assert service.store.claim(pending.job_id, token)
    job = service.get_job(pending.job_id)
    service.worker_factory().run(spec)
    record = service._verified_record(job)
    barrier = Barrier(2)

    def complete() -> bool:
        barrier.wait()
        try:
            service.store.complete(job, token, record)
            return True
        except RunnerLeaseError:
            return False

    def recover() -> int:
        barrier.wait()
        return service.recover_interrupted_runner()

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion, recovery = pool.submit(complete), pool.submit(recover)
        completed, interrupted = completion.result(), recovery.result()
    final = service.get_job(job.job_id)
    assert completed == (interrupted == 0)
    assert final.attempt_count == 1
    assert final.state == (JobState.COMPLETED if completed else JobState.FAILED)
    assert (service.get_result(job.run_id) is not None) == completed
    service.artifact_store.load_manifest(job.run_id)


def test_wrong_result_completion_has_no_index_side_effects(tmp_path: Path) -> None:
    service, spec = coordinator(tmp_path)
    service.submit(BatchBacktestSpec((spec, replace(spec, random_seed=8))))
    first, second = service.list_jobs()
    token = service.store.acquire_lease()
    assert service.store.claim(first.job_id, token)
    first = service.get_job(first.job_id)
    service.worker_factory().run(second.spec)
    wrong = service._verified_record(second)
    with pytest.raises(ResearchStoreError):
        service.store.complete(first, token, wrong)
    assert service.get_job(first.job_id).state == JobState.RUNNING
    assert service.list_results() == ()
    service.store.release_lease(token)
