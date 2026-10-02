import math
import statistics
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from command_station.accounting import PortfolioSnapshot
from command_station.research import BacktestPeriod, calculate_metrics
from tests.execution_fixtures import timestamp
from tests.research_fixtures import setup


def snapshots(values: tuple[int, ...]) -> tuple[PortfolioSnapshot, ...]:
    return tuple(
        PortfolioSnapshot(
            timestamp(i),
            Decimal(v),
            Decimal(0),
            Decimal(v),
            Decimal(0),
            Decimal(v),
            Decimal(0),
            Decimal(0),
            Decimal(0),
            (),
            (),
        )
        for i, v in enumerate(values)
    )


def test_documented_return_risk_drawdown_formulas() -> None:
    history = snapshots((100, 90, 95, 100, 80, 90))
    metrics = calculate_metrics(
        history, BacktestPeriod(timestamp(0), timestamp(5)), (), (), Decimal(0)
    )
    returns = [
        b.total_equity / a.total_equity - 1 for a, b in zip(history, history[1:], strict=False)
    ]
    r = [float(x) for x in returns]
    assert (
        metrics.starting_equity == 100 and metrics.ending_equity == 90 and metrics.net_profit == -10
    )
    assert metrics.total_return == pytest.approx(-0.1)
    assert metrics.cagr == pytest.approx((0.9 ** (365 * 86400 / 300)) - 1)
    assert metrics.sharpe == pytest.approx(
        statistics.fmean(r) / statistics.pstdev(r) * math.sqrt(525600)
    )
    downside = math.sqrt(statistics.fmean(min(x, 0) ** 2 for x in r))
    assert metrics.sortino == pytest.approx(statistics.fmean(r) / downside * math.sqrt(525600))
    assert metrics.max_drawdown == pytest.approx(-0.2)
    assert metrics.average_drawdown == pytest.approx(-0.15)
    assert metrics.longest_drawdown_seconds == 180
    assert len(metrics.drawdown_episodes) == 2
    assert metrics.drawdown_episodes[0].trough_time == timestamp(1)
    assert metrics.drawdown_episodes[0].end_time == timestamp(3)
    assert metrics.calmar == pytest.approx(metrics.cagr / 0.2)  # type: ignore[operator]


@pytest.mark.parametrize(
    "values", [(0,), (100,), (0, 0, 0), (100, 100, 100), (100, 110), (100, 0, 0)]
)
def test_undefined_metrics(values: tuple[int, ...]) -> None:
    m = calculate_metrics(
        snapshots(values),
        BacktestPeriod(timestamp(0), timestamp(len(values) - 1)),
        (),
        (),
        Decimal(0),
    )
    assert m.sharpe is None and m.sortino is None
    assert m.win_rate is None and m.profit_factor is None and m.gross_expectancy is None
    assert m.max_win_streak == m.max_loss_streak == 0
    assert m.time_in_market == 0 and m.total_fees == m.total_slippage_cost == 0
    if values[0] == 0:
        assert m.total_return is None and m.cagr is None


def test_trade_streak_flat_denominator_costs_exposure_and_fee_guard(tmp_path: Path) -> None:
    from command_station.accounting import LotConsumptionId, LotId, LotSource
    from command_station.execution import FillId
    from command_station.research.trades import ClosedLotTrade
    from tests.research_fixtures import BTC

    trades = tuple(
        ClosedLotTrade(
            BTC,
            LotId(i + 1),
            LotConsumptionId(i + 1),
            None,
            FillId(i + 1),
            LotSource.INITIAL_HOLDING,
            Decimal(1),
            timestamp(0),
            timestamp(i + 1),
            Decimal(100),
            Decimal(100 + p),
            Decimal(p),
            (i + 1) * 60,
        )
        for i, p in enumerate((10, 20, 0, -5, -15, 5))
    )
    metrics = calculate_metrics(
        snapshots((100, 100)), BacktestPeriod(timestamp(0), timestamp(1)), trades, (), Decimal(0)
    )
    assert metrics.closed_trade_count == 6 and metrics.win_rate == 0.5
    assert metrics.gross_closed_trade_pnl == 15 and metrics.gross_expectancy == 2.5
    assert metrics.profit_factor == 1.75
    assert metrics.average_winner == pytest.approx(35 / 3) and metrics.median_winner == 10
    assert metrics.average_loser == -10 and metrics.median_loser == -10
    assert metrics.max_win_streak == metrics.max_loss_streak == 2
    assert metrics.average_hold_seconds == metrics.median_hold_seconds == 210
    service, spec = setup(tmp_path)
    result = service.run(spec)
    assert result.metrics.time_in_market == 0.5
    assert result.metrics.max_capital_deployed == 100
    assert result.metrics.average_capital_deployed == 50
    assert result.metrics.product_exposures[0].maximum == 100
    with pytest.raises(ValueError, match="fees"):
        calculate_metrics(
            (replace(result.final_portfolio, fees_to_date=Decimal(9)),),
            BacktestPeriod(timestamp(4), timestamp(4)),
            (),
            (),
            Decimal(0),
        )


def test_warmup_and_invalid_minute_series() -> None:
    history = snapshots((99999, 100, 100))
    m = calculate_metrics(history, BacktestPeriod(timestamp(1), timestamp(2)), (), (), Decimal(0))
    assert m.starting_equity == 100 and m.net_profit == 0
    with pytest.raises(ValueError, match="one-minute"):
        calculate_metrics(
            (history[0], history[2]), BacktestPeriod(timestamp(0), timestamp(2)), (), (), Decimal(0)
        )
