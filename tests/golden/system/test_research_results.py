from decimal import Decimal
from pathlib import Path

from command_station.accounting import USD
from tests.research_fixtures import BuyHold, FinalOrder, setup
from tests.system_fixtures import bundle, rows


def test_final_active_order_preserves_sealed_portfolio_distinction(tmp_path: Path) -> None:
    service, spec = setup(tmp_path / "first", FinalOrder)
    result = service.run(spec)
    assert not rows(service, result, "fills.parquet")
    order = rows(service, result, "orders.parquet")[0]
    assert order["created_at"] == order["activated_at"] == str(spec.period.replay_end)
    assert order["status"] == "ACTIVE"
    assert result.final_account.balance(USD).reserved == 200
    assert result.final_reservations[0].remaining_amount == 200
    assert result.final_portfolio.cash_reserved == 0
    assert result.final_portfolio.cash_available == 1000
    second, other = setup(tmp_path / "second", FinalOrder)
    rerun = second.run(other)
    assert result == rerun
    assert bundle(service, result) == bundle(second, rerun)


def test_open_final_position_no_liquidation_and_marked_equity(tmp_path: Path) -> None:
    service, spec = setup(tmp_path, BuyHold)
    result = service.run(spec)
    assert len(rows(service, result, "fills.parquet")) == 1
    assert not rows(service, result, "trades.parquet")
    assert result.final_positions[0].actual_quantity == 1
    assert result.final_positions[0].gross_realized_pnl == 0
    assert result.final_portfolio.gross_unrealized_pnl == 10
    assert result.final_portfolio.marked_asset_value == 110
    assert result.final_portfolio.cash_total == 899
    assert result.final_portfolio.total_equity == Decimal("1009")
    assert result.metrics.closed_trade_count == 0
    assert result.metrics.total_fees == 1
