"""Owner regressions for terminal chronology and shared OCO exclusivity."""

from dataclasses import replace

import pytest

from command_station.accounting import AccountingInvariantError, SpotAccountingEngine
from command_station.domain import Side
from command_station.execution import CancellationReason, Order, OrderType, SimulatedBroker
from tests.accounting_fixtures import account, fill_fact, request, reserve
from tests.execution_fixtures import timestamp


def oco() -> tuple[SpotAccountingEngine, tuple[Order, Order]]:
    engine = account(holding="2")
    broker = SimulatedBroker(engine.execution_spec)
    requests = (request(Side.SELL, OrderType.LIMIT), request(Side.SELL, OrderType.STOP_MARKET))
    plan = engine.prepare_reservation(requests)
    orders = broker.activate_oco(*requests, timestamp())
    engine.bind_reservation(plan, orders, timestamp())
    return engine, orders


def test_oco_second_peer_cannot_settle_in_successive_batch() -> None:
    engine, (first, second) = oco()
    fill = fill_fact(first, engine.execution_spec, quantity="0.5")
    partial = first.apply_fill("0.5")
    engine.apply_fill_batch((fill,), (partial, second), timestamp(1))
    before = engine.accounting_fingerprint
    other_fill = fill_fact(second, engine.execution_spec, quantity="0.5", fill_id=2, minute=1)
    with pytest.raises(AccountingInvariantError, match="exclusive OCO"):
        engine.apply_fill_batch((other_fill,), (partial, second.apply_fill("0.5")), timestamp(2))
    assert engine.accounting_fingerprint == before


def test_multiple_partial_fills_of_same_oco_peer_remain_valid() -> None:
    engine, (first, second) = oco()
    initial = fill_fact(first, engine.execution_spec, quantity="0.25")
    partial = first.apply_fill("0.25")
    engine.apply_fill_batch((initial,), (partial, second), timestamp(1))
    later = fill_fact(first, engine.execution_spec, quantity="0.25", fill_id=2, minute=1)
    partial = partial.apply_fill("0.25")
    engine.apply_fill_batch((later,), (partial, second), timestamp(2))
    assert engine.positions[0].actual_quantity == 1.5
    assert engine.reservations[0].remaining_amount == 0.5
    assert len(engine.applied_fills) == 2


@pytest.mark.parametrize("partial", [False, True])
def test_future_normal_or_partial_cancellation_has_no_accounting_mutation(partial: bool) -> None:
    engine = account(holding="2")
    broker = SimulatedBroker(engine.execution_spec)
    order = reserve(engine, broker, request(Side.SELL))
    if partial:
        fill = fill_fact(order, engine.execution_spec, quantity="0.5")
        order = order.apply_fill("0.5")
        engine.apply_fill_batch((fill,), (order,), timestamp(1))
    cancelled = order.cancel(timestamp(10), CancellationReason.USER_REQUEST)
    before = engine.accounting_fingerprint
    with pytest.raises(AccountingInvariantError, match="cancellation chronology"):
        engine.apply_fill_batch((), (cancelled,), timestamp(1))
    assert engine.accounting_fingerprint == before
    with pytest.raises(AccountingInvariantError, match="cancellation chronology"):
        engine.validate_boundary(timestamp(1), (cancelled,))
    assert engine.accounting_fingerprint == before
    engine.apply_fill_batch((), (cancelled,), timestamp(10))
    assert engine.reservations[0].remaining_amount == 0


def test_cancellation_cannot_precede_applied_partial_fill() -> None:
    engine = account(holding="2")
    broker = SimulatedBroker(engine.execution_spec)
    order = reserve(engine, broker, request(Side.SELL))
    fill = fill_fact(order, engine.execution_spec, quantity="0.5", minute=1)
    partial = order.apply_fill("0.5")
    engine.apply_fill_batch((fill,), (partial,), timestamp(2))
    cancelled = partial.cancel(timestamp(), CancellationReason.USER_REQUEST)
    before = engine.accounting_fingerprint
    with pytest.raises(AccountingInvariantError, match="after cancellation"):
        engine.apply_fill_batch((), (cancelled,), timestamp(2))
    assert engine.accounting_fingerprint == before


def test_created_after_activation_rejected_before_reservation_binding() -> None:
    engine = account(holding="2")
    broker = SimulatedBroker(engine.execution_spec)
    req = request(Side.SELL)
    plan = engine.prepare_reservation((req,))
    order = broker.activate(req, timestamp())
    forged = replace(order, created_at=timestamp(1))
    before = engine.accounting_fingerprint
    with pytest.raises(AccountingInvariantError):
        engine.bind_reservation(plan, (forged,), timestamp())
    assert engine.accounting_fingerprint == before
