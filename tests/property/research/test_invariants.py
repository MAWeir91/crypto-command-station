import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from command_station.research import BacktestPeriod, BacktestRunId, calculate_metrics
from command_station.research.artifacts import canonical_rows
from command_station.research.specs import canonical_json
from tests.execution_fixtures import timestamp
from tests.research_fixtures import setup
from tests.unit.research.test_analytics import snapshots


@given(st.lists(st.integers(min_value=0, max_value=1000000), min_size=1, max_size=20))
def test_metrics_finite_drawdown_exposure_and_warmup(values: list[int]) -> None:
    history = snapshots(tuple([999999999, *values]))
    metrics = calculate_metrics(
        history, BacktestPeriod(timestamp(1), timestamp(len(values))), (), (), Decimal(0)
    )
    content = canonical_json(metrics)
    json.loads(content)
    assert b"NaN" not in content and b"Infinity" not in content
    assert metrics.starting_equity == values[0]
    assert metrics.max_drawdown <= 0 and 0 <= metrics.time_in_market <= 1
    assert metrics.total_fees == 0 and metrics.total_slippage_cost >= 0


@given(st.integers(min_value=-1000, max_value=1000))
@settings(max_examples=5, deadline=None)
def test_fresh_identity_and_immutable_publication(seed: int) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        service, spec = setup(Path(directory))
        changed = replace(spec, random_seed=seed)
        a, b = service.run(changed), service.run(changed)
        assert a == b
        if seed != spec.random_seed:
            assert changed.fingerprint != spec.fingerprint
            assert a.run_id != BacktestRunId.derive(spec, service.engine_identity)


@given(st.permutations((0, 1, 2)))
def test_artifact_row_permutation(indices: list[int]) -> None:
    history = snapshots((100, 90, 95))
    assert canonical_rows("equity.parquet", tuple(history[i] for i in indices)) == canonical_rows(
        "equity.parquet", history
    )
