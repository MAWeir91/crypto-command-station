from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from command_station.accounting._exact import add
from command_station.research import derive_closed_lot_trades
from tests.research_fixtures import RoundTrip
from tests.strategy_fixtures import compose


@given(
    st.decimals(min_value="0.01", max_value="100", places=2, allow_nan=False, allow_infinity=False)
)
def test_segments_preserve_consumption_quantity_and_pnl(pnl: Decimal) -> None:
    runtime = compose(RoundTrip(), minutes=4)
    runtime.run()
    assert runtime.accounting is not None
    accounting = runtime.accounting
    consumptions = tuple(replace(c, gross_realized_pnl=pnl) for c in accounting.lot_consumptions)
    trades = derive_closed_lot_trades(accounting.lots, consumptions, runtime.broker.fills)
    assert add(*(t.gross_pnl for t in trades)) == add(*(c.gross_realized_pnl for c in consumptions))
    assert add(*(t.quantity for t in trades)) == add(*(c.quantity for c in consumptions))
    # Research consumes accounting's PnL authority without recalculating from prices.
    assert trades[0].gross_pnl == pnl


def test_missing_lot_fill_and_inconsistent_quantities_fail() -> None:
    runtime = compose(RoundTrip(), minutes=4)
    runtime.run()
    assert runtime.accounting is not None
    accounting = runtime.accounting
    with pytest.raises(KeyError):
        derive_closed_lot_trades((), accounting.lot_consumptions, runtime.broker.fills)
    bad = tuple(replace(c, quantity=Decimal("0.5")) for c in accounting.lot_consumptions)
    with pytest.raises(ValueError, match="quantity"):
        derive_closed_lot_trades(accounting.lots, bad, runtime.broker.fills)
