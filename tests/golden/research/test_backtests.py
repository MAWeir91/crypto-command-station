import json
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from command_station.accounting import USD
from command_station.risk import RiskPolicy
from tests.research_fixtures import BuyHold, FinalOrder, NoTrade, RoundTrip, setup


@pytest.mark.parametrize("scenario", ["roundtrip", "none", "reject", "open", "final"])
def test_golden_actual_artifacts(tmp_path: Path, scenario: str) -> None:
    factories = {
        "roundtrip": RoundTrip,
        "none": NoTrade,
        "reject": BuyHold,
        "open": BuyHold,
        "final": FinalOrder,
    }
    service, spec = setup(
        tmp_path, factories[scenario], policy=RiskPolicy(trading_enabled=scenario != "reject")
    )
    result = service.run(spec)
    assert result.artifact_manifest is not None
    service.artifacts.verify(result.artifact_manifest)
    folder = service.artifacts.directory(result.run_id)
    summary = json.loads((folder / "summary.json").read_bytes())
    assert summary["result_fingerprint"] == result.result_fingerprint
    assert json.loads((folder / "spec.json").read_bytes()) == spec.to_dict()
    fills = pq.read_table(folder / "fills.parquet").to_pylist()
    orders = pq.read_table(folder / "orders.parquet").to_pylist()
    trades = pq.read_table(folder / "trades.parquet").to_pylist()
    equity = pq.read_table(folder / "equity.parquet").to_pylist()
    assert len(equity) == 4
    assert result.metrics.starting_equity == Decimal("1000")
    if scenario == "roundtrip":
        assert [f["fill_price"] for f in fills] == ["100", "110"]
        assert [f["fee_amount"] for f in fills] == ["1", "1.1"]
        assert len(trades) == 1 and trades[0]["gross_pnl"] == "10"
        assert result.metrics.net_profit == Decimal("7.9")
        assert result.metrics.gross_closed_trade_pnl == Decimal("10")
        assert result.metrics.total_fees == Decimal("2.1")
        assert result.final_positions[0].actual_quantity == 0
        assert all(o["status"] == "FILLED" for o in orders)
        assert fills[0]["activated_at"] <= fills[0]["market_interval_open"]
        assert fills[0]["market_interval_open"] < fills[0]["market_interval_close"]
        assert result.metrics.win_rate == 1 and result.metrics.profit_factor is None
    elif scenario in ("none", "reject"):
        assert not fills and not orders and not trades
        assert result.metrics.net_profit == 0 and result.metrics.closed_trade_count == 0
        assert result.metrics.sharpe is None and result.metrics.sortino is None
        assert result.risk_summary.reject_count == (1 if scenario == "reject" else 0)
    elif scenario == "open":
        assert len(fills) == 1 and not trades
        assert result.final_positions[0].actual_quantity == 1
        assert result.final_portfolio.total_equity == Decimal("1009")
        assert result.final_portfolio.gross_unrealized_pnl == 10
    else:
        assert not fills and not trades and len(orders) == 1
        assert orders[0]["status"] == "ACTIVE"
        assert result.execution_summary.active_order_count == 1
        assert result.final_account.balance(USD).reserved == 200
        assert result.final_reservations[0].remaining_amount == 200
        assert summary["final_reservations"][0]["remaining_amount"] == "200"
        # Sealed mark snapshots precede callbacks, so this is pre-reservation.
        assert result.final_portfolio.cash_reserved == 0
