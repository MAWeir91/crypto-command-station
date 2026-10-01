from dataclasses import replace
from decimal import Decimal

import pytest

from command_station.accounting import SpotAccountingEngine, SpotAccountSpec
from command_station.execution import OrderType, normalize_order_intent
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.risk import RiskDecisionStatus, RiskEngine, RiskPolicy, RiskReason
from command_station.runtime import (
    InvalidRuntimeConfigurationError,
    ReferenceTradingRuntime,
    RuntimeEngineError,
    SimulatedClock,
)
from tests.accounting_fixtures import request
from tests.execution_fixtures import product, timestamp
from tests.risk_fixtures import runtime, state
from tests.runtime_fixtures import canonical


def test_rejection_no_financial_mutation_and_cancel_restores_headroom() -> None:
    rt = runtime(RiskPolicy(max_order_notional=Decimal(101), minimum_cash_reserve=Decimal(850)))
    assert rt.accounting is not None and rt.risk is not None
    accepted = rt.activate_order(request(kind=OrderType.LIMIT))
    assert accepted.decision.status is RiskDecisionStatus.APPROVE
    before = (
        rt.accounting.accounting_fingerprint,
        rt.broker.execution_fingerprint,
        rt.accounting.ledger,
        rt.accounting.lots,
    )
    rejected = rt.activate_order(request(kind=OrderType.LIMIT))
    assert rejected.decision.status is RiskDecisionStatus.REJECT
    assert (
        rt.accounting.accounting_fingerprint,
        rt.broker.execution_fingerprint,
        rt.accounting.ledger,
        rt.accounting.lots,
    ) == before
    assert rt.risk.decisions == (accepted.decision, rejected.decision)
    rt.cancel_order(accepted.orders[0].order_id)
    assert (
        rt.activate_order(request(kind=OrderType.LIMIT)).decision.status
        is RiskDecisionStatus.APPROVE
    )


def test_modification_binding_broker_gets_only_approved_quantity() -> None:
    rt = runtime(RiskPolicy(max_order_notional=Decimal("50.5"), allow_quantity_reduction=True))
    result = rt.activate_order(request(kind=OrderType.LIMIT, quantity="2"))
    assert result.decision.status is RiskDecisionStatus.APPROVE_WITH_MODIFICATION
    assert result.orders[0].activated_base_quantity.value == Decimal("0.5")
    assert rt.accounting is not None
    reservation = rt.accounting.reservations[0]
    assert reservation.order_ids == (result.orders[0].order_id,)
    binding = rt.risk_bindings[0]
    assert binding.decision == result.decision
    assert binding.reservation_id == reservation.reservation_id
    assert (
        binding.approved_request.normalized_base_quantity
        == result.orders[0].activated_base_quantity
    )
    assert (
        reservation.original_amount == result.decision.approved_quote_commitment == Decimal("50.5")
    )
    assert rt.step() is not None


def test_direct_broker_with_real_reservation_still_cannot_execute() -> None:
    rt = runtime()
    assert rt.accounting is not None
    req = request()
    plan = rt.accounting.prepare_reservation((req,), max_quote_reservation=Decimal(100))
    order = rt.broker.activate(req, timestamp())
    rt.accounting.bind_reservation(plan, (order,), timestamp())
    with pytest.raises(RuntimeEngineError, match="risk authorization"):
        rt.step()
    assert rt.broker.fills == ()


def test_authorization_cannot_rebind_changed_request() -> None:
    rt = runtime()
    assert rt.accounting is not None
    approved = rt.activate_order(request(kind=OrderType.LIMIT))
    # A second properly reserved external activation cannot borrow the first decision.
    req = request(kind=OrderType.LIMIT, quantity="2")
    plan = rt.accounting.prepare_reservation((req,))
    order = rt.broker.activate(req, timestamp())
    rt.accounting.bind_reservation(plan, (order,), timestamp())
    with pytest.raises(RuntimeEngineError, match="risk authorization"):
        rt.step()
    assert len(approved.orders) == 1 and rt.broker.fills == ()


def test_runtime_requires_paired_fresh_risk() -> None:
    feed = HistoricalReplayFeed((canonical("BTC-USD", minutes=2),))
    a = SpotAccountingEngine(
        SpotAccountSpec(initial_cash="100", product_specs=(product(),)), feed.start
    )
    with pytest.raises(InvalidRuntimeConfigurationError):
        ReferenceTradingRuntime(clock=SimulatedClock(feed.start), market_feed=feed, accounting=a)
    with pytest.raises(InvalidRuntimeConfigurationError):
        ReferenceTradingRuntime(
            clock=SimulatedClock(feed.start), market_feed=feed, risk=RiskEngine()
        )
    used = RiskEngine()
    used.authorize(state(a), (request(),), max_quote_reservation=Decimal(1))
    with pytest.raises(InvalidRuntimeConfigurationError):
        ReferenceTradingRuntime(
            clock=SimulatedClock(feed.start), market_feed=feed, accounting=a, risk=used
        )


def test_multi_product_unique_open_position_limit() -> None:
    products = (product(), product("ETH-USD"))
    feed = HistoricalReplayFeed(tuple(canonical(p.product_id.value, minutes=3) for p in products))
    a = SpotAccountingEngine(
        SpotAccountSpec(initial_cash="1000", product_specs=products), feed.start
    )
    rt = ReferenceTradingRuntime(
        clock=SimulatedClock(feed.start),
        market_feed=feed,
        accounting=a,
        risk=RiskEngine(RiskPolicy(max_open_positions=1)),
    )
    first = rt.activate_order(request(kind=OrderType.LIMIT))
    assert first.orders
    same = rt.activate_order(request(kind=OrderType.LIMIT))
    assert same.orders
    intent = replace(request(kind=OrderType.LIMIT).source_intent, product_id=products[1].product_id)
    rejected = rt.activate_order(normalize_order_intent(intent, products[1]))
    assert RiskReason.MAX_OPEN_POSITIONS in rejected.decision.reasons
    rt.cancel_order(first.orders[0].order_id)
    rt.cancel_order(same.orders[0].order_id)
    assert rt.activate_order(normalize_order_intent(intent, products[1])).orders


def test_runtime_fresh_rerun_identity() -> None:
    def execute() -> tuple[object, ...]:
        rt = runtime(RiskPolicy(max_order_notional=Decimal("50.5"), allow_quantity_reduction=True))
        rt.activate_order(request(kind=OrderType.LIMIT, quantity="2"))
        result = rt.run()
        assert rt.risk is not None
        assert (
            result.risk_decision_count == 1 and result.risk_fingerprint == rt.risk.risk_fingerprint
        )
        return result, rt.risk.decisions, rt.broker.orders

    assert execute() == execute()
