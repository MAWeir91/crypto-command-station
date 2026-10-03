import os
from pathlib import Path

import pytest

from command_station.research import BacktestReproducibilityError
from command_station.research.artifacts import BUNDLE_NAMES
from tests.research_fixtures import setup


@pytest.mark.parametrize("name", sorted(BUNDLE_NAMES))
def test_every_corrupted_bundle_member_rejects_reuse_without_overwrite(
    tmp_path: Path, name: str
) -> None:
    service, spec = setup(tmp_path)
    result = service.run(spec)
    folder = service.artifacts.directory(result.run_id)
    target = folder / name
    target.write_bytes(target.read_bytes() + b"corrupted")
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(BacktestReproducibilityError):
        service.run(spec)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert not tuple((service.artifacts.root / ".staging").iterdir())


def test_hardlinked_bundle_member_rejects_reuse(tmp_path: Path) -> None:
    service, spec = setup(tmp_path)
    result = service.run(spec)
    folder = service.artifacts.directory(result.run_id)
    os.link(folder / "summary.json", tmp_path / "linked-summary.json")
    before = (folder / "summary.json").read_bytes()
    with pytest.raises(BacktestReproducibilityError, match="hardlinked"):
        service.run(spec)
    assert (folder / "summary.json").read_bytes() == before


def test_existing_publication_lock_fails_without_touching_bundle_or_lock(tmp_path: Path) -> None:
    service, spec = setup(tmp_path)
    result = service.run(spec)
    folder = service.artifacts.directory(result.run_id)
    lock = folder.parent / (result.run_id.value + ".lock")
    lock.write_bytes(b"other-writer")
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(FileExistsError):
        service.run(spec)
    assert lock.read_bytes() == b"other-writer"
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
