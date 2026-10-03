from dataclasses import replace
from pathlib import Path

import pytest

from command_station.accounting import AccountingInvariantError, SpotAccountingEngine
from command_station.domain import Candle, Side
from command_station.execution import BaseQuantity, Fill, Order
from command_station.research import BacktestRunId, StrategyArtifactRef
from command_station.runtime import InvalidRuntimeConfigurationError, RuntimeEngineError
from command_station.strategy import StrategyContext
from tests.research_fixtures import BTC, MultiFrame, NoTrade, setup


@pytest.mark.parametrize("failure", ["dataset", "strategy", "parameters"])
def test_pre_runtime_failure_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    service, spec = setup(tmp_path, NoTrade)
    started = []

    def forbidden(*args: object, **kwargs: object) -> None:
        started.append(True)
        raise AssertionError("runtime must not be constructed")

    monkeypatch.setattr("command_station.research.backtests.ReferenceTradingRuntime", forbidden)
    if failure == "dataset":

        def missing(*args: object) -> None:
            raise ValueError("missing dataset")

        monkeypatch.setattr(service.datasets, "load", missing)
    elif failure == "strategy":
        spec = replace(spec, strategy_artifact=StrategyArtifactRef("b" * 64))
    else:
        spec = replace(spec, parameters=(("undeclared", 1),))
    with pytest.raises((ValueError, KeyError)):
        service.run(spec)
    assert not started
    assert not service.artifacts.directory(
        BacktestRunId.derive(spec, service.engine_identity)
    ).exists()


def test_callback_exception_publishes_no_completed_result(tmp_path: Path) -> None:
    class Broken(NoTrade):
        def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
            ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")
            raise ValueError("injected callback failure")

    service, spec = setup(tmp_path, Broken)
    with pytest.raises(RuntimeEngineError):
        service.run(spec)
    assert not service.artifacts.directory(
        BacktestRunId.derive(spec, service.engine_identity)
    ).exists()


def test_accounting_invariant_failure_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, spec = setup(tmp_path)
    original = SpotAccountingEngine.apply_fill_batch

    def fail(
        self: SpotAccountingEngine,
        fills: tuple[Fill, ...],
        orders: tuple[Order, ...],
        timestamp: object,
    ) -> None:
        if fills:
            raise AccountingInvariantError("injected settlement invariant")
        original(self, fills, orders, timestamp)  # type: ignore[arg-type]

    monkeypatch.setattr(SpotAccountingEngine, "apply_fill_batch", fail)
    with pytest.raises(RuntimeEngineError) as failure:
        service.run(spec)
    assert isinstance(failure.value.__cause__, AccountingInvariantError)
    assert not service.artifacts.directory(
        BacktestRunId.derive(spec, service.engine_identity)
    ).exists()


def test_insufficient_warmup_fails_before_financial_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, spec = setup(tmp_path, MultiFrame)
    mutations = []

    def forbidden(*args: object, **kwargs: object) -> None:
        mutations.append(True)
        raise AssertionError("warmup configuration must fail before financial mutation")

    monkeypatch.setattr(SpotAccountingEngine, "apply_fill_batch", forbidden)
    monkeypatch.setattr(SpotAccountingEngine, "bind_reservation", forbidden)
    with pytest.raises(InvalidRuntimeConfigurationError, match="warmup"):
        service.run(spec)
    assert not mutations
    assert not service.artifacts.directory(
        BacktestRunId.derive(spec, service.engine_identity)
    ).exists()


def test_artifact_serialization_failure_publishes_nothing_and_preserves_unrelated_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, spec = setup(tmp_path)
    unrelated = service.artifacts.root / ".staging" / "user-owned"
    unrelated.mkdir(parents=True)
    (unrelated / "keep").write_bytes(b"preserve")

    def fail(*args: object) -> None:
        raise ValueError("injected serialization failure")

    monkeypatch.setattr("command_station.research.artifacts.canonical_rows", fail)
    with pytest.raises(ValueError, match="serialization"):
        service.run(spec)
    assert tuple(unrelated.parent.iterdir()) == (unrelated,)
    assert (unrelated / "keep").read_bytes() == b"preserve"
    assert not service.artifacts.directory(
        BacktestRunId.derive(spec, service.engine_identity)
    ).exists()
