"""FIFO projections; original acquisitions and consumptions remain immutable."""

from decimal import Decimal
from fractions import Fraction

from command_station.accounting._exact import ZERO, add, decimal, mul, sub
from command_station.accounting.models import (
    AVERAGE_COST_DISPLAY_PLACES,
    AccountingInvariantError,
    AccountView,
    AcquisitionLot,
    LotConsumption,
    PositionView,
)
from command_station.domain import ProductSpec


def open_quantity(lot: AcquisitionLot, consumptions: tuple[LotConsumption, ...]) -> Decimal:
    quantity = sub(
        lot.original_quantity, add(*(c.quantity for c in consumptions if c.lot_id == lot.lot_id))
    )
    if quantity < 0:
        raise AccountingInvariantError("lot underflow")
    return quantity


def position_views(
    products: tuple[ProductSpec, ...],
    account: AccountView,
    lots: tuple[AcquisitionLot, ...],
    consumptions: tuple[LotConsumption, ...],
) -> tuple[PositionView, ...]:
    result = []
    for product in products:
        owned = tuple(lot for lot in lots if lot.product_id == product.product_id)
        quantity = add(*(open_quantity(lot, consumptions) for lot in owned))
        if quantity != account.balance(product.base_currency).total:
            raise AccountingInvariantError("account/position/lot quantity mismatch")
        cost = add(*(mul(open_quantity(lot, consumptions), lot.unit_cost) for lot in owned))
        count = Fraction(quantity) // Fraction(product.base_increment)
        tradable = mul(product.base_increment, Decimal(count))
        if tradable < product.base_min_size:
            tradable = ZERO
        average = None
        if quantity:
            ratio = Fraction(cost) / Fraction(quantity)
            # Fixed 8-place ROUND_HALF_EVEN using exact integer rational rounding.
            average = decimal(
                Fraction(
                    round(ratio * 10**AVERAGE_COST_DISPLAY_PLACES), 10**AVERAGE_COST_DISPLAY_PLACES
                )
            )
        ids = {lot.lot_id for lot in owned}
        realized = add(*(c.gross_realized_pnl for c in consumptions if c.lot_id in ids))
        result.append(
            PositionView(
                product.product_id,
                product.base_currency,
                quantity,
                tradable,
                sub(quantity, tradable),
                cost,
                average,
                realized,
            )
        )
    return tuple(result)
