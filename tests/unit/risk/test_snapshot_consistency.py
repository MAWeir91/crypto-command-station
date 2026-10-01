"""Reject contradictory public snapshots before risk history can change."""

from dataclasses import replace
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from command_station.accounting import USD, ReservationId, ReservationStatus
from command_station.domain import Side
from command_station.execution import CancellationReason, Order, OrderType, SimulatedBroker
from command_station.risk import (
    RiskDecisionStatus,
    RiskEngine,
    RiskPolicy,
    RiskReason,
    RiskStateSnapshot,
)
from tests.accounting_fixtures import account, fill_fact, request, reserve
from tests.execution_fixtures import candle, timestamp
from tests.risk_fixtures import state


def marked_state(*, pending: bool = False) -> RiskStateSnapshot:
    a = account(holding="2")
    b = SimulatedBroker(a.execution_spec)
    if pending:
        reserve(a, b, request(), Decimal(100))
    a.update_portfolio((candle(0),), timestamp(1))
    return state(a, b, 1)


def test_forged_portfolio_value_rejects_before_history_mutation() -> None:
    original = marked_state()
    assert original.portfolio_snapshot is not None
    risk = RiskEngine(RiskPolicy(max_portfolio_exposure=Decimal(250)))
    honest = risk.authorize(original, (request(kind=OrderType.LIMIT),))
    assert honest.decision.status is RiskDecisionStatus.REJECT
    assert honest.decision.projected_portfolio_exposure == 301
    before = risk.decisions, risk.risk_fingerprint
    for forged in (
        replace(original.portfolio_snapshot, marked_asset_value=Decimal(0)),
        replace(
            original.portfolio_snapshot, marked_asset_value=Decimal(0), total_equity=Decimal(10000)
        ),
    ):
        with pytest.raises(ValueError, match="marked asset total"):
            risk.authorize(
                replace(original, portfolio_snapshot=forged), (request(kind=OrderType.LIMIT),)
            )
        assert (risk.decisions, risk.risk_fingerprint) == before


@pytest.mark.parametrize("kind", ["positions", "marks", "portfolio_positions", "balances"])
def test_unique_state_collections(kind: str) -> None:
    original = marked_state()
    assert original.portfolio_snapshot is not None
    with pytest.raises(ValueError):
        if kind == "positions":
            replace(original, positions=(*original.positions, original.positions[0]))
        elif kind == "marks":
            snapshot = original.portfolio_snapshot
            replace(
                original,
                portfolio_snapshot=replace(snapshot, marks=(*snapshot.marks, snapshot.marks[0])),
            )
        elif kind == "portfolio_positions":
            replace(original, portfolio_snapshot=replace(original.portfolio_snapshot, positions=()))
        else:
            replace(
                original,
                account_view=replace(
                    original.account_view,
                    balances=(*original.account_view.balances, original.account_view.balances[0]),
                ),
            )


@pytest.mark.parametrize(
    "kind",
    [
        "omitted",
        "overlap",
        "asset",
        "remaining",
        "status",
        "balance",
        "missing_order",
        "position_quantity",
    ],
)
def test_reservation_balance_order_coherence(kind: str) -> None:
    original = marked_state(pending=True)
    r = original.reservations[0]
    risk = RiskEngine()
    before = risk.risk_fingerprint
    with pytest.raises(ValueError):
        if kind == "omitted":
            changed = replace(original, reservations=())
        elif kind == "overlap":
            changed = replace(
                original, reservations=(r, replace(r, reservation_id=ReservationId(2)))
            )
        elif kind == "asset":
            changed = replace(
                original, reservations=(replace(r, asset=original.positions[0].base_asset),)
            )
        elif kind == "remaining":
            changed = replace(original, reservations=(replace(r, remaining_amount=Decimal(50)),))
        elif kind == "status":
            changed = replace(
                original, reservations=(replace(r, status=ReservationStatus.RELEASED),)
            )
        elif kind == "balance":
            balances = tuple(
                replace(b, reserved=Decimal(0)) if b.asset == USD else b
                for b in original.account_view.balances
            )
            changed = replace(
                original, account_view=replace(original.account_view, balances=balances)
            )
        elif kind == "missing_order":
            changed = replace(original, orders=())
        else:
            changed = replace(
                original, positions=(replace(original.positions[0], actual_quantity=Decimal(1)),)
            )
        risk.authorize(changed, (request(kind=OrderType.LIMIT),))
    assert risk.decisions == () and risk.risk_fingerprint == before


def test_authorization_revalidates_snapshot_before_history_mutation() -> None:
    original = marked_state(pending=True)
    # Deliberately breach Python's frozen object convention to exercise entry preflight.
    object.__setattr__(original, "reservations", ())
    risk = RiskEngine()
    before = risk.risk_fingerprint
    with pytest.raises(ValueError, match="reservation evidence"):
        risk.authorize(original, (request(kind=OrderType.LIMIT),))
    assert risk.decisions == () and risk.risk_fingerprint == before


@pytest.mark.parametrize("minute", [0, 1, 2])
def test_stale_future_missing_marks_remain_structured_rejections(minute: int) -> None:
    original = marked_state()
    assert original.portfolio_snapshot is not None
    if minute == 1:
        original = replace(
            original, portfolio_snapshot=replace(original.portfolio_snapshot, marks=())
        )
    else:
        original = replace(original, timestamp=timestamp(minute))
    auth = RiskEngine(RiskPolicy(max_portfolio_exposure=Decimal(1000))).authorize(
        original, (request(kind=OrderType.LIMIT),)
    )
    assert auth.decision.status is RiskDecisionStatus.REJECT
    assert RiskReason.STALE_MARKET_DATA in auth.decision.reasons


@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
@pytest.mark.parametrize("oco", [False, True])
def test_real_partial_reservation_and_terminal_states_remain_coherent(
    side: Side, oco: bool
) -> None:
    a = account(holding="2")
    b = SimulatedBroker(a.execution_spec)
    orders: tuple[Order, ...]
    if oco:
        peers = (request(side, OrderType.LIMIT), request(side, OrderType.STOP_MARKET))
        plan = a.prepare_reservation(
            peers, max_quote_reservation=Decimal(202) if side is Side.BUY else None
        )
        orders = b.activate_oco(*peers, timestamp())
        a.bind_reservation(plan, orders, timestamp())
    else:
        orders = (reserve(a, b, request(side), Decimal(202) if side is Side.BUY else None),)
    partial = orders[0].apply_fill("0.5")
    advanced = (partial, *orders[1:])
    fill = fill_fact(orders[0], a.execution_spec, quantity="0.5")
    a.apply_fill_batch((fill,), advanced, timestamp(1))
    a.update_portfolio((candle(0),), timestamp(1))
    current = RiskStateSnapshot(
        timestamp(1),
        a.spec,
        a.account_view,
        a.positions,
        a.reservations,
        advanced,
        a.portfolio_snapshot,
        a.execution_spec,
    )
    assert RiskEngine().authorize(current, (request(kind=OrderType.LIMIT),)).approved_requests
    cancelled = tuple(
        order.cancel(timestamp(1), CancellationReason.USER_REQUEST) for order in advanced
    )
    a.apply_fill_batch((), cancelled, timestamp(1))
    terminal = RiskStateSnapshot(
        timestamp(1),
        a.spec,
        a.account_view,
        a.positions,
        a.reservations,
        cancelled,
        a.portfolio_snapshot,
        a.execution_spec,
    )
    assert RiskEngine().authorize(terminal, (request(kind=OrderType.LIMIT),)).approved_requests


def test_snapshot_coherence_is_decimal_context_independent() -> None:
    original = marked_state(pending=True)
    for precision in (1, 2, 28):
        with localcontext() as ctx:
            ctx.prec = precision
            ctx.traps[Inexact] = True
            ctx.traps[Rounded] = True
            original.validate_consistency()
            assert replace(original).fingerprint == original.fingerprint


def test_unfilled_commitment_cannot_be_removed_with_balances() -> None:
    original = marked_state(pending=True)
    r = original.reservations[0]
    balances = tuple(
        replace(b, reserved=Decimal(0)) if b.asset == USD else b
        for b in original.account_view.balances
    )
    with pytest.raises(ValueError, match="unfilled active order"):
        replace(
            original,
            account_view=replace(original.account_view, balances=balances),
            reservations=(
                replace(r, remaining_amount=Decimal(0), status=ReservationStatus.CONSUMED),
            ),
        )
