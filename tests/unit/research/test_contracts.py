from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from command_station.research import (
    BacktestPeriod,
    BacktestReproducibilityError,
    BacktestRunId,
    EngineIdentity,
    LocalBacktestArtifactStore,
    StrategyArtifactCatalog,
    StrategyArtifactDescriptor,
)
from command_station.research.specs import canonical_json
from tests.execution_fixtures import timestamp
from tests.research_fixtures import PREDECESSOR, NoTrade, RoundTrip, setup


def descriptor(strategy: NoTrade) -> StrategyArtifactDescriptor:
    return StrategyArtifactDescriptor(
        "artifact",
        strategy.definition.strategy_id,
        "1.0.0",
        PREDECESSOR,
        "a" * 64,
        type(strategy).__module__,
        type(strategy).__qualname__,
        strategy.definition.fingerprint,
    )


def test_spec_material_identity_exactness_and_immutability(tmp_path: Path) -> None:
    service, spec = setup(tmp_path)
    for changed in (
        replace(spec, random_seed=1),
        replace(spec, period=BacktestPeriod(timestamp(2), timestamp(4))),
        replace(spec, parameters=(("amount", Decimal("0.12345678901234567890123456789")),)),
    ):
        assert changed.fingerprint != spec.fingerprint
        assert BacktestRunId.derive(changed, service.engine_identity) != BacktestRunId.derive(
            spec, service.engine_identity
        )
    assert b"0.12345678901234567890123456789" in canonical_json(changed.to_dict())
    a = replace(spec, parameters=(("b", Decimal("1.000")), ("a", 1)))
    b = replace(spec, parameters=(("a", 1), ("b", Decimal("1"))))
    assert a.fingerprint == b.fingerprint
    for invalid in (True, 1.1, "1"):
        with pytest.raises(ValueError):
            replace(spec, random_seed=invalid)  # type: ignore[arg-type]
    invalid_values: tuple[object, ...] = (float("nan"), float("inf"), Decimal("NaN"), [])
    for value in invalid_values:
        with pytest.raises(ValueError):
            replace(spec, parameters=(("a", value),))
    with pytest.raises(ValueError):
        replace(spec, datasets=spec.datasets * 2)
    with pytest.raises(ValueError):
        EngineIdentity("main", "0.1.0", "v1")


def test_catalog_mismatch_and_mutable_instance_reuse() -> None:
    catalog = StrategyArtifactCatalog()
    instance = NoTrade()
    d = descriptor(instance)
    catalog.register(d, lambda: instance)
    assert catalog.resolve(d.ref)[1] is instance
    with pytest.raises(ValueError, match="reused"):
        catalog.resolve(d.ref)
    for mismatched in (
        replace(d, definition_fingerprint="b" * 64),
        replace(d, strategy_id="other"),
        replace(d, module="wrong"),
        replace(d, qualname="wrong"),
    ):
        bad = StrategyArtifactCatalog()
        bad.register(mismatched, NoTrade)
        with pytest.raises(ValueError, match="descriptor"):
            bad.resolve(mismatched.ref)
    with pytest.raises(ValueError):
        replace(d, code_sha256="abc")


def test_artifact_relative_root_and_symlink_guard(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        LocalBacktestArtifactStore(Path("relative"))
    with pytest.raises(ValueError):
        BacktestRunId("../escape")
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(BacktestReproducibilityError):
        LocalBacktestArtifactStore(link / "artifacts")


def test_parameters_reuse_phase011_validation(tmp_path: Path) -> None:
    service, spec = setup(tmp_path, RoundTrip)
    with pytest.raises(ValueError):
        service.run(replace(spec, parameters=(("unknown", 1),)))
