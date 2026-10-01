"""Current canonical one-minute valuation without stale or derived marks."""

from decimal import Decimal

from command_station.accounting._exact import add, mul, sub
from command_station.accounting.models import (
    USD,
    AccountingInvariantError,
    AccountView,
    PortfolioSnapshot,
    PositionView,
)
from command_station.domain import Candle, Timeframe, UtcTimestamp


def mark_portfolio(
    account: AccountView,
    positions: tuple[PositionView, ...],
    fees_to_date: Decimal,
    intervals: tuple[Candle, ...],
    timestamp: UtcTimestamp,
) -> PortfolioSnapshot:
    if any(
        not isinstance(c, Candle)
        or c.timeframe is not Timeframe.ONE_MINUTE
        or c.close_time != timestamp
        for c in intervals
    ):
        raise AccountingInvariantError(
            "portfolio requires current completed canonical one-minute intervals"
        )
    marks = {c.product_id: c.close for c in intervals}
    if len(marks) != len(intervals):
        raise AccountingInvariantError("duplicate portfolio mark")
    marked = []
    unrealized = []
    for position in positions:
        if position.actual_quantity:
            if position.product_id not in marks:
                raise AccountingInvariantError("owned asset has no current one-minute mark")
            value = mul(position.actual_quantity, marks[position.product_id])
            marked.append(value)
            unrealized.append(sub(value, position.total_cost_basis))
    cash = account.balance(USD)
    asset_value = add(*marked)
    return PortfolioSnapshot(
        timestamp,
        cash.total,
        cash.reserved,
        cash.available,
        asset_value,
        add(cash.total, asset_value),
        add(*(p.gross_realized_pnl for p in positions)),
        add(*unrealized),
        fees_to_date,
        positions,
        tuple(sorted(marks.items(), key=lambda item: item[0].value)),
    )
