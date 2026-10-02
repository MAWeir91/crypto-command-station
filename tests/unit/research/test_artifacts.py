from dataclasses import replace
from pathlib import Path

import pytest

from command_station.research.artifacts import BacktestReproducibilityError
from tests.research_fixtures import setup


def test_partial_write_cleans_only_owned_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, spec = setup(tmp_path)
    unrelated = tmp_path / "artifacts" / ".staging" / "user-owned"
    unrelated.mkdir(parents=True)
    (unrelated / "keep.txt").write_text("preserve")

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("injected parquet write failure")

    monkeypatch.setattr("command_station.research.artifacts.pq.write_table", fail)
    with pytest.raises(OSError, match="injected"):
        service.run(spec)
    assert (unrelated / "keep.txt").read_text() == "preserve"
    assert tuple(unrelated.parent.iterdir()) == (unrelated,)
    assert not tuple((tmp_path / "artifacts" / "backtests").iterdir())


@pytest.mark.parametrize("name", ["spec.json", "manifest.json", "fills.parquet"])
def test_forged_manifest_hash_or_json_cannot_be_reused(tmp_path: Path, name: str) -> None:
    service, spec = setup(tmp_path)
    result = service.run(spec)
    path = service.artifacts.directory(result.run_id) / name
    path.write_bytes(path.read_bytes() + b" ")
    corrupt = path.read_bytes()
    with pytest.raises(BacktestReproducibilityError):
        service.run(spec)
    assert path.read_bytes() == corrupt


def test_no_absolute_path_leakage_and_all_schema_metadata(tmp_path: Path) -> None:
    import json

    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    from command_station.research.artifacts import TABLE_MODELS, table_schema
    from command_station.research.specs import fingerprint

    service, spec = setup(tmp_path)
    result = service.run(spec)
    assert result.artifact_manifest is not None
    folder = service.artifacts.directory(result.run_id)
    for path in folder.iterdir():
        assert str(tmp_path).encode() not in path.read_bytes()
    for name in TABLE_MODELS:
        table = pq.read_table(folder / name)
        assert table.schema.equals(table_schema(name), check_metadata=True)
    assert len(result.artifact_manifest.artifacts) == 8
    manifest = json.loads((folder / "manifest.json").read_bytes())
    manifest_fingerprint = manifest.pop("manifest_fingerprint")
    assert fingerprint(manifest) == manifest_fingerprint == result.artifact_manifest.fingerprint


@pytest.mark.parametrize("forgery", ["empty", "incomplete", "duplicate"])
def test_incomplete_or_duplicate_manifest_cannot_bypass_verification(
    tmp_path: Path, forgery: str
) -> None:
    from command_station.research.specs import canonical_json

    service, spec = setup(tmp_path)
    result = service.run(spec)
    original = result.artifact_manifest
    assert original is not None
    records = {
        "empty": (),
        "incomplete": original.artifacts[:-1],
        "duplicate": (original.artifacts[0], *original.artifacts[:-1]),
    }[forgery]
    with pytest.raises(BacktestReproducibilityError, match="eight unique"):
        replace(original, artifacts=records)
    # Revalidate at the public boundary even if frozen construction is bypassed.
    forged = replace(original)
    object.__setattr__(forged, "artifacts", records)
    folder = service.artifacts.directory(result.run_id)
    (folder / "manifest.json").write_bytes(canonical_json(forged.to_dict()))
    (folder / "fills.parquet").write_bytes(b"corrupt and unverified")
    with pytest.raises(BacktestReproducibilityError, match="eight unique"):
        service.artifacts.verify(forged)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("byte_size", True),
        ("byte_size", -1),
        ("row_count", None),
        ("row_count", True),
        ("row_count", -1),
        ("sha256", "invalid"),
        ("relative_path", "../fills.parquet"),
    ],
)
def test_artifact_record_rejects_wrong_types_versions_and_values(field: str, value: object) -> None:
    from command_station.research.artifacts import ArtifactRecord

    record = ArtifactRecord("fills.parquet", 0, 0, "a" * 64)
    with pytest.raises(BacktestReproducibilityError):
        replace(record, **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("run_id", "a" * 64),
        ("result_fingerprint", "invalid"),
        ("artifacts", []),
    ],
)
def test_manifest_rejects_wrong_types_versions_and_identity(
    tmp_path: Path, field: str, value: object
) -> None:
    service, spec = setup(tmp_path)
    original = service.run(spec).artifact_manifest
    assert original is not None
    with pytest.raises(BacktestReproducibilityError):
        replace(original, **{field: value})  # type: ignore[arg-type]
