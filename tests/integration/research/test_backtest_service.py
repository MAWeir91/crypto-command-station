from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from command_station.market_data.replay import HistoricalReplayFeed
from command_station.research import BacktestReproducibilityError, BacktestRunId
from tests.execution_fixtures import timestamp
from tests.research_fixtures import MultiFrame, MultiProduct, NoTrade, setup


def test_fresh_rerun_and_verified_reuse(tmp_path: Path) -> None:
    service, spec = setup(tmp_path)
    a = service.run(spec)
    folder = service.artifacts.directory(a.run_id)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}
    b = service.run(spec)
    assert a == b
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}
    assert not tuple((service.artifacts.root / ".staging").iterdir())


def test_multiframe_warmup_and_bounded_replay(tmp_path: Path) -> None:
    service, spec = setup(tmp_path, MultiFrame, minutes=20, start=10, end=15)
    result = service.run(spec)
    assert len(result.provenance.derived) == 1
    assert result.provenance.derived[0].source_dataset_version == spec.datasets[0].dataset_version
    table = pq.read_table(service.artifacts.directory(result.run_id) / "equity.parquet")
    assert table.num_rows == 6
    assert table.to_pylist()[0]["timestamp"] == str(timestamp(10))
    source = service.datasets.load(spec.datasets[0].dataset_version)
    bounded = HistoricalReplayFeed((source,), replay_end=timestamp(15))
    legacy = HistoricalReplayFeed((source,))
    assert len(tuple(legacy)) == 20 and len(tuple(bounded)) == 15
    assert tuple(legacy)[:15] == tuple(bounded)
    assert bounded.canonical_sources[0].version == source.version


def test_multi_product_ordering(tmp_path: Path) -> None:
    first, a = setup(tmp_path / "first", MultiProduct)
    second, b = setup(tmp_path / "second", MultiProduct, reverse=True)
    assert a.fingerprint == b.fingerprint
    assert first.run(a) == second.run(b)


def test_existing_corruption_and_result_collision(tmp_path: Path) -> None:
    service, spec = setup(tmp_path)
    result = service.run(spec)
    folder = service.artifacts.directory(result.run_id)
    original = (folder / "summary.json").read_bytes()
    (folder / "summary.json").write_bytes(b"{}")
    with pytest.raises(BacktestReproducibilityError):
        service.run(spec)
    assert (folder / "summary.json").read_bytes() == b"{}"
    (folder / "summary.json").write_bytes(original)
    with pytest.raises(BacktestReproducibilityError):
        service.artifacts.publish(
            result.run_id,
            "b" * 64,
            spec.to_dict(),
            {},
            {
                name: ()
                for name in (
                    "orders.parquet",
                    "fills.parquet",
                    "trades.parquet",
                    "equity.parquet",
                    "risk_decisions.parquet",
                    "strategy_actions.parquet",
                )
            },
        )
    assert (folder / "summary.json").read_bytes() == original


def test_wrong_dataset_resolution_and_missing_coverage(tmp_path: Path) -> None:
    service, spec = setup(tmp_path, NoTrade)

    class WrongResolver:
        def load(self, version: object) -> object:
            return None

    service.datasets = WrongResolver()  # type: ignore[assignment]
    with pytest.raises(ValueError, match="resolved dataset"):
        service.run(spec)
    service, spec = setup(tmp_path / "coverage", NoTrade)
    from command_station.research import BacktestPeriod

    with pytest.raises(ValueError, match="period"):
        service.run(replace(spec, period=BacktestPeriod(timestamp(1), timestamp(11))))


def test_runtime_failure_publishes_nothing(tmp_path: Path) -> None:
    class Broken(NoTrade):
        def on_stop(self, ctx: object) -> None:
            raise RuntimeError("failure")

    service, spec = setup(tmp_path, Broken)
    with pytest.raises(RuntimeError):
        service.run(spec)
    assert not service.artifacts.directory(
        BacktestRunId.derive(spec, service.engine_identity)
    ).exists()
