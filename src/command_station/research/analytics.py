"""Snapshot performance and FIFO lot-segment metrics.

Simple one-minute returns, population variance, zero risk-free rate, 365-day
annualization. Average drawdown is the mean depth of explicit peak/recovery
episodes. Financial totals use exact arithmetic; ratios use finite float or None.
"""

import math
import statistics
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from command_station.accounting import PortfolioSnapshot
from command_station.accounting._exact import add, mul, sub
from command_station.domain import ProductId, UtcTimestamp
from command_station.execution import Fill
from command_station.research.specs import BacktestPeriod, logical
from command_station.research.trades import ClosedLotTrade

ANNUAL_MINUTES = 365 * 24 * 60


def finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def ratio(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator == 0:
        return None
    try:
        return finite(float(Fraction(numerator) / Fraction(denominator)))
    except OverflowError:
        return None


def mean(values: tuple[Decimal, ...]) -> float | None:
    return ratio(add(*values), Decimal(len(values))) if values else None


def median(values: tuple[Decimal, ...]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (
        ratio(ordered[middle], Decimal(1))
        if len(ordered) % 2
        else ratio(add(ordered[middle - 1], ordered[middle]), Decimal(2))
    )


@dataclass(frozen=True, slots=True)
class DrawdownEpisode:
    peak_time: UtcTimestamp
    trough_time: UtcTimestamp
    end_time: UtcTimestamp
    deepest_drawdown: float
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class ProductExposure:
    product_id: ProductId
    maximum: Decimal
    average: float | None


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    starting_equity: Decimal
    ending_equity: Decimal
    net_profit: Decimal
    total_return: float | None
    cagr: float | None
    max_drawdown: float
    average_drawdown: float
    longest_drawdown_seconds: float
    drawdown_episodes: tuple[DrawdownEpisode, ...]
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    closed_trade_count: int
    win_rate: float | None
    gross_expectancy: float | None
    profit_factor: float | None
    average_winner: float | None
    median_winner: float | None
    average_loser: float | None
    median_loser: float | None
    max_win_streak: int
    max_loss_streak: int
    average_hold_seconds: float | None
    median_hold_seconds: float | None
    gross_closed_trade_pnl: Decimal
    total_fees: Decimal
    total_slippage_cost: Decimal
    time_in_market: float
    max_capital_deployed: Decimal
    average_capital_deployed: float | None
    product_exposures: tuple[ProductExposure, ...]

    def __post_init__(self) -> None:
        logical(self)


def analytics_window(
    history: tuple[PortfolioSnapshot, ...], period: BacktestPeriod
) -> tuple[PortfolioSnapshot, ...]:
    snapshots = tuple(
        sorted(
            (s for s in history if period.trading_start <= s.timestamp <= period.replay_end),
            key=lambda s: s.timestamp,
        )
    )
    if not snapshots or len({s.timestamp for s in snapshots}) != len(snapshots):
        raise ValueError("nonempty unique analytics snapshots required")
    if any(
        (b.timestamp.value - a.timestamp.value).total_seconds() != 60
        for a, b in zip(snapshots, snapshots[1:], strict=False)
    ):
        raise ValueError("analytics requires consecutive one-minute snapshots")
    return snapshots


def calculate_metrics(
    history: tuple[PortfolioSnapshot, ...],
    period: BacktestPeriod,
    trades: tuple[ClosedLotTrade, ...],
    fills: tuple[Fill, ...],
    accounting_fees: Decimal,
) -> BacktestMetrics:
    snapshots = analytics_window(history, period)
    start, end = snapshots[0].total_equity, snapshots[-1].total_equity
    total_fees = add(*(fill.fee_amount for fill in fills))
    if total_fees != snapshots[-1].fees_to_date or total_fees != accounting_fees:
        raise ValueError("fill fees do not reconcile to accounting and portfolio")
    slippage = add(*(mul(fill.slippage_per_base, fill.base_quantity) for fill in fills))
    if slippage < 0:
        raise ValueError("negative slippage evidence")
    growth = ratio(end, start) if start > 0 else None
    total_return = finite(growth - 1) if growth is not None else None
    seconds = (snapshots[-1].timestamp.value - snapshots[0].timestamp.value).total_seconds()
    cagr = None
    if growth is not None and growth >= 0 and seconds > 0:
        with suppress(OverflowError, ValueError):
            cagr = finite(growth ** (365 * 86400 / seconds) - 1)
    episodes: list[DrawdownEpisode] = []
    peak = snapshots[0]
    trough = peak
    depth = 0.0
    for snapshot in snapshots[1:]:
        if snapshot.total_equity >= peak.total_equity:
            if depth < 0:
                episodes.append(
                    DrawdownEpisode(
                        peak.timestamp,
                        trough.timestamp,
                        snapshot.timestamp,
                        depth,
                        (snapshot.timestamp.value - peak.timestamp.value).total_seconds(),
                    )
                )
            peak, trough, depth = snapshot, snapshot, 0.0
        elif peak.total_equity > 0:
            relative = ratio(snapshot.total_equity, peak.total_equity)
            if relative is None:
                raise ValueError("unrepresentable drawdown")
            current = relative - 1
            if current < depth:
                trough, depth = snapshot, current
    if depth < 0:
        episodes.append(
            DrawdownEpisode(
                peak.timestamp,
                trough.timestamp,
                snapshots[-1].timestamp,
                depth,
                (snapshots[-1].timestamp.value - peak.timestamp.value).total_seconds(),
            )
        )
    max_dd = min((e.deepest_drawdown for e in episodes), default=0.0)
    returns: list[float] = []
    for a, b in zip(snapshots, snapshots[1:], strict=False):
        value = ratio(b.total_equity, a.total_equity) if a.total_equity > 0 else None
        if value is None:
            returns = []
            break
        returns.append(value - 1)
    sharpe = sortino = None
    if len(returns) >= 2:
        try:
            average = statistics.fmean(returns)
            deviation = statistics.pstdev(returns)
            downside = math.sqrt(statistics.fmean(min(r, 0) ** 2 for r in returns))
            sharpe = finite(average / deviation * math.sqrt(ANNUAL_MINUTES)) if deviation else None
            sortino = finite(average / downside * math.sqrt(ANNUAL_MINUTES)) if downside else None
        except (OverflowError, ValueError):
            pass
    ordered = tuple(sorted(trades, key=lambda t: (t.exit_time, t.consumption_id.value)))
    wins = tuple(t.gross_pnl for t in ordered if t.gross_pnl > 0)
    losses = tuple(t.gross_pnl for t in ordered if t.gross_pnl < 0)
    ws = ls = mw = ml = 0
    for trade in ordered:
        ws = ws + 1 if trade.gross_pnl > 0 else 0
        ls = ls + 1 if trade.gross_pnl < 0 else 0
        mw, ml = max(mw, ws), max(ml, ls)
    holds = tuple(t.hold_seconds for t in ordered)
    exposures: list[ProductExposure] = []
    for product in sorted(
        {p.product_id for s in snapshots for p in s.positions}, key=lambda p: p.value
    ):
        values = tuple(
            mul(
                next(p.actual_quantity for p in s.positions if p.product_id == product),
                dict(s.marks)[product],
            )
            for s in snapshots
        )
        exposures.append(ProductExposure(product, max(values), mean(values)))
    deployed = tuple(s.marked_asset_value for s in snapshots)
    return BacktestMetrics(
        start,
        end,
        sub(end, start),
        total_return,
        cagr,
        max_dd,
        statistics.fmean(e.deepest_drawdown for e in episodes) if episodes else 0.0,
        max((e.duration_seconds for e in episodes), default=0.0),
        tuple(episodes),
        sharpe,
        sortino,
        finite(cagr / abs(max_dd)) if cagr is not None and max_dd else None,
        len(ordered),
        len(wins) / len(ordered) if ordered else None,
        mean(tuple(t.gross_pnl for t in ordered)),
        ratio(add(*wins), add(*losses).copy_negate()) if losses else None,
        mean(wins),
        median(wins),
        mean(losses),
        median(losses),
        mw,
        ml,
        statistics.fmean(holds) if holds else None,
        statistics.median(holds) if holds else None,
        add(*(t.gross_pnl for t in ordered)),
        total_fees,
        slippage,
        sum(v > 0 for v in deployed) / len(snapshots),
        max(deployed),
        mean(deployed),
        tuple(exposures),
    )
