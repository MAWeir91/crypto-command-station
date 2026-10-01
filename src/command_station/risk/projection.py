"""Conservative reservation-aware exposure projection."""

from decimal import Decimal

from command_station.accounting import ReservationStatus
from command_station.accounting._exact import ZERO, add, mul
from command_station.domain import ProductId, Side
from command_station.risk.models import RiskStateSnapshot


def baseline(
    state: RiskStateSnapshot, product: ProductId
) -> tuple[Decimal, Decimal, set[ProductId]]:
    orders = {o.order_id: o for o in state.orders}
    pending: dict[ProductId, list[Decimal]] = {}
    for reservation in state.reservations:
        if reservation.status is not ReservationStatus.ACTIVE or reservation.remaining_amount == 0:
            continue
        peers = tuple(orders[oid] for oid in reservation.order_ids)
        if not peers or len({(o.product_id, o.side) for o in peers}) != 1:
            raise ValueError("reservation has inconsistent order evidence")
        if peers[0].side is Side.BUY:
            pending.setdefault(peers[0].product_id, []).append(reservation.remaining_amount)
    marks = dict(state.portfolio_snapshot.marks) if state.portfolio_snapshot else {}
    current = add(
        *(
            mul(p.actual_quantity, marks[p.product_id])
            for p in state.positions
            if p.product_id == product and p.product_id in marks
        )
    )
    marked = state.portfolio_snapshot.marked_asset_value if state.portfolio_snapshot else ZERO
    opened = {p.product_id for p in state.positions if p.actual_quantity > 0} | set(pending)
    return (
        add(current, *pending.get(product, [])),
        add(marked, *(v for values in pending.values() for v in values)),
        opened,
    )
