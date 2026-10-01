"""Independent adversarial probes for Phase009 financial lifecycle boundaries."""

from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from command_station.accounting import AccountingInvariantError
from command_station.domain import Side
from command_station.execution import Order, OrderType, SimulatedBroker
from command_station.runtime import RuntimeEngineError, RuntimeLifecycle
from tests.accounting_fixtures import account, fill_fact, request, reserve
from tests.execution_fixtures import candle, timestamp
from tests.integration.accounting.test_runtime_financial_authority import runtime


@pytest.mark.parametrize("oco", [False, True])
def test_future_external_cancellation_rejected_before_execution_or_release(oco: bool) -> None:
    rt = runtime()
    orders: tuple[Order, ...]
    if oco:
        orders = rt.activate_oco(
            request(kind=OrderType.LIMIT),
            request(kind=OrderType.STOP_MARKET),
            max_quote_reservation=Decimal(100),
        )
    else:
        orders = (rt.activate_order(request(), max_quote_reservation=Decimal(100)),)
    assert rt.accounting is not None
    before = rt.accounting.accounting_fingerprint
    for order in orders:
        rt.broker.cancel(order.order_id, timestamp(10))
    with pytest.raises(RuntimeEngineError):
        rt.step()
    assert rt.lifecycle is RuntimeLifecycle.FAILED
    assert rt.accounting.accounting_fingerprint == before
    assert rt.broker.fills == ()


def test_accounting_rejects_two_oco_peer_fills_atomically() -> None:
    engine = account(holding="2")
    broker = SimulatedBroker(engine.execution_spec)
    requests = (
        request(Side.SELL, OrderType.LIMIT),
        request(Side.SELL, OrderType.STOP_MARKET),
    )
    plan = engine.prepare_reservation(requests)
    orders = broker.activate_oco(*requests, timestamp())
    engine.bind_reservation(plan, orders, timestamp())
    fills = tuple(
        fill_fact(order, engine.execution_spec, quantity="0.5", fill_id=index + 1)
        for index, order in enumerate(orders)
    )
    before = engine.accounting_fingerprint
    with pytest.raises(AccountingInvariantError):
        engine.apply_fill_batch(
            fills, tuple(order.apply_fill("0.5") for order in orders), timestamp(1)
        )
    assert engine.accounting_fingerprint == before


def test_strict_decimal_traps_do_not_affect_financial_truth() -> None:
    def execute() -> str:
        engine = account(cash="10000.123456789", holding="2.123456789", cost="80.123456789")
        broker = SimulatedBroker(engine.execution_spec)
        reserve(engine, broker, request(Side.SELL, quantity="1.123"))
        intervals = (candle(0, open="100.123456789", high="101", low="99", close="100.123456789"),)
        fills = broker.process_market_activity(intervals, timestamp(1))
        engine.apply_fill_batch(fills, broker.orders, timestamp(1))
        engine.update_portfolio(intervals, timestamp(1))
        return engine.accounting_fingerprint

    expected = execute()
    with localcontext() as context:
        context.prec = 1
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        context.clear_flags()
        assert execute() == expected
        assert not any(context.flags.values())


@pytest.mark.parametrize("mark_minute", [-1, 1])
def test_stale_and_future_marks_are_atomic_failures(mark_minute: int) -> None:
    engine = account(holding="1")
    before = engine.accounting_fingerprint
    with pytest.raises(AccountingInvariantError):
        engine.update_portfolio((candle(mark_minute),), timestamp(1))
    assert engine.accounting_fingerprint == before
