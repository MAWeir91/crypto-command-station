"""Closed FIFO lot segments joined from immutable Phase 009 accounting evidence."""

from dataclasses import dataclass
from decimal import Decimal

from command_station.accounting import (
    AcquisitionLot,
    LotConsumption,
    LotConsumptionId,
    LotId,
    LotSource,
)
from command_station.accounting._exact import add
from command_station.domain import ProductId, Side, UtcTimestamp
from command_station.execution import Fill, FillId


@dataclass(frozen=True, slots=True)
class ClosedLotTrade:
    product_id: ProductId
    lot_id: LotId
    consumption_id: LotConsumptionId
    entry_fill_id: FillId | None
    exit_fill_id: FillId
    source: LotSource
    quantity: Decimal
    entry_time: UtcTimestamp
    exit_time: UtcTimestamp
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    hold_seconds: float


def derive_closed_lot_trades(
    lots: tuple[AcquisitionLot, ...],
    consumptions: tuple[LotConsumption, ...],
    fills: tuple[Fill, ...],
) -> tuple[ClosedLotTrade, ...]:
    by_lot = {lot.lot_id: lot for lot in lots}
    by_fill = {fill.fill_id: fill for fill in fills}
    if (
        len(by_lot) != len(lots)
        or len(by_fill) != len(fills)
        or len({c.consumption_id for c in consumptions}) != len(consumptions)
    ):
        raise ValueError("duplicate accounting evidence identity")
    result: list[ClosedLotTrade] = []
    for consumption in sorted(consumptions, key=lambda c: (c.timestamp, c.consumption_id.value)):
        lot = by_lot[consumption.lot_id]
        fill = by_fill[consumption.sell_fill_id]
        duration = (consumption.timestamp.value - lot.opened_at.value).total_seconds()
        if (
            fill.side is not Side.SELL
            or fill.product_id != lot.product_id
            or fill.fill_price != consumption.sell_price
            or consumption.unit_cost != lot.unit_cost
            or consumption.timestamp != fill.executed_at
            or duration < 0
        ):
            raise ValueError("inconsistent lot-consumption/fill evidence")
        if lot.source_fill_id is not None:
            entry = by_fill[lot.source_fill_id]
            if (
                entry.side is not Side.BUY
                or entry.product_id != lot.product_id
                or entry.fill_price != lot.unit_cost
            ):
                raise ValueError("inconsistent acquisition fill")
        result.append(
            ClosedLotTrade(
                lot.product_id,
                lot.lot_id,
                consumption.consumption_id,
                lot.source_fill_id,
                fill.fill_id,
                lot.source,
                consumption.quantity,
                lot.opened_at,
                consumption.timestamp,
                lot.unit_cost,
                consumption.sell_price,
                consumption.gross_realized_pnl,
                duration,
            )
        )
    for fill in fills:
        if fill.side is Side.SELL:
            segments = tuple(t for t in result if t.exit_fill_id == fill.fill_id)
            if add(*(t.quantity for t in segments)) != fill.base_quantity:
                raise ValueError("closed lot quantity does not reconcile to sell fill")
    if add(*(t.gross_pnl for t in result)) != add(*(c.gross_realized_pnl for c in consumptions)):
        raise ValueError("closed lot PnL does not reconcile")
    return tuple(result)
