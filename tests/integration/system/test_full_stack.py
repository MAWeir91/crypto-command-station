import os
import subprocess
import sys
from dataclasses import replace
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext
from pathlib import Path

import pytest

from command_station.market_data.datasets import CanonicalCandleDataset
from command_station.research import BacktestDatasetRef, BacktestPeriod, StrategyArtifactCatalog
from command_station.risk import RiskPolicy
from tests.execution_fixtures import candle, timestamp
from tests.property.system.test_reproducibility import Permuted
from tests.research_fixtures import MultiProduct, setup
from tests.system_fixtures import bundle


def test_separate_roots_complete_results_and_artifact_content(tmp_path: Path) -> None:
    first, spec = setup(tmp_path / "first")
    second, other = setup(tmp_path / "second")
    a, b = first.run(spec), second.run(other)
    assert first is not second and first.datasets is not second.datasets
    assert a == b  # Every result, provenance/component identity and manifest field.
    assert a.artifact_manifest is not None and b.artifact_manifest is not None
    assert a.artifact_manifest.fingerprint == b.artifact_manifest.fingerprint
    assert bundle(first, a) == bundle(second, b)
    assert {p.name: p.read_bytes() for p in first.artifacts.directory(a.run_id).iterdir()} == {
        p.name: p.read_bytes() for p in second.artifacts.directory(b.run_id).iterdir()
    }


@pytest.mark.parametrize("precision,rounding", [(2, ROUND_DOWN), (7, ROUND_UP), (50, ROUND_DOWN)])
def test_full_stack_decimal_context_matrix(tmp_path: Path, precision: int, rounding: str) -> None:
    service, spec = setup(tmp_path / "normal")
    expected = service.run(spec)
    with localcontext() as context:
        context.prec, context.rounding = precision, rounding
        other, copied = setup(tmp_path / "context")
        actual = other.run(copied)
    assert actual == expected
    assert bundle(service, expected) == bundle(other, actual)


def test_dataset_refs_and_product_specs_permutation(tmp_path: Path) -> None:
    first, spec = setup(tmp_path / "first", MultiProduct)
    second, other = setup(tmp_path / "second", MultiProduct, reverse=True)
    other = replace(
        other,
        datasets=tuple(reversed(other.datasets)),
        account=replace(other.account, product_specs=tuple(reversed(other.account.product_specs))),
    )
    assert spec == other
    a, b = first.run(spec), second.run(other)
    assert a == b
    assert bundle(first, a) == bundle(second, b)


def test_fresh_process_hash_seed_and_root_independence(tmp_path: Path) -> None:
    script = (
        "import sys; from pathlib import Path; from tests.research_fixtures import setup; "
        "s,p=setup(Path(sys.argv[1])); r=s.run(p); "
        "print(r.run_id.value, r.result_fingerprint, r.artifact_manifest.fingerprint)"
    )
    outputs = []
    for seed in ("1", "987"):
        process = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / seed)],
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        outputs.append(process.stdout.strip())
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize(
    "component",
    [
        "strategy",
        "parameters",
        "dataset",
        "product",
        "account",
        "risk",
        "execution",
        "seed",
        "period",
        "engine",
    ],
)
def test_material_input_changes_run_and_result_identity(tmp_path: Path, component: str) -> None:
    service, spec = setup(tmp_path, Permuted, minutes=15, start=5, end=10)
    baseline = service.run(spec)
    changed = spec
    if component == "strategy":
        descriptor, _ = service.strategies.resolve(spec.strategy_artifact)
        descriptor = replace(descriptor, code_sha256="b" * 64)
        catalog = StrategyArtifactCatalog()
        catalog.register(descriptor, Permuted)
        service.strategies = catalog
        changed = replace(spec, strategy_artifact=descriptor.ref)
    elif component == "parameters":
        changed = replace(spec, parameters=(("alpha", 3),))
    elif component == "dataset":
        source = service.datasets.load(spec.datasets[0].dataset_version)
        repaired = CanonicalCandleDataset(
            product_id=source.product_id,
            start=source.start,
            end=source.end,
            as_of=source.as_of,
            candles=(candle(0, close="101"), *source.candles[1:]),
            gaps=source.gaps,
            source_pages=source.source_pages,
        )
        service.datasets.publish(repaired)  # type: ignore[attr-defined]
        changed = replace(
            spec,
            datasets=(
                BacktestDatasetRef(repaired.product_id, repaired.version),
                *spec.datasets[1:],
            ),
        )
    elif component == "product":
        changed = replace(
            spec,
            account=replace(
                spec.account,
                product_specs=(
                    replace(spec.account.product_specs[0], base_increment=Decimal("0.01")),
                    *spec.account.product_specs[1:],
                ),
            ),
        )
    elif component == "account":
        changed = replace(spec, account=replace(spec.account, initial_cash=Decimal("999")))
    elif component == "risk":
        changed = replace(spec, risk_policy=RiskPolicy(max_order_notional=Decimal("50")))
    elif component == "execution":
        changed = replace(spec, execution=replace(spec.execution, fee_bps=17))
    elif component == "seed":
        changed = replace(spec, random_seed=1)
    elif component == "period":
        changed = replace(spec, period=BacktestPeriod(timestamp(5), timestamp(9)))
    else:
        service.engine_identity = replace(service.engine_identity, git_commit="e" * 40)
    result = service.run(changed)
    assert result.run_id != baseline.run_id
    assert result.result_fingerprint != baseline.result_fingerprint
    if component != "engine":
        assert changed.fingerprint != spec.fingerprint
