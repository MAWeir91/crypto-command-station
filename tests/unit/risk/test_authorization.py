import ast
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from command_station.accounting import USD
from command_station.domain import Side
from command_station.execution import OrderType, SimulatedBroker
from command_station.risk import (
    ExposureDirection,
    RiskDecisionStatus,
    RiskEngine,
    RiskPolicy,
    RiskReason,
)
from tests.accounting_fixtures import account, request, reserve
from tests.execution_fixtures import candle
from tests.risk_fixtures import state


@pytest.mark.parametrize(
    "field",
    [
        "max_order_notional",
        "max_product_exposure",
        "max_portfolio_exposure",
        "minimum_cash_reserve",
    ],
)
@pytest.mark.parametrize(
    "value", [True, 1.5, "1", Decimal("NaN"), Decimal("Infinity"), Decimal(-1)]
)
def test_policy_rejects_ambiguous_limits(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        RiskPolicy(**{field: value})  # type: ignore[arg-type]


def test_policy_immutable_semantic_fingerprint() -> None:
    p = RiskPolicy(max_order_notional=Decimal("1.00"))
    assert p.fingerprint == RiskPolicy(max_order_notional=Decimal(1)).fingerprint
    assert p.to_dict() == RiskPolicy(max_order_notional=Decimal(1)).to_dict()
    with pytest.raises(FrozenInstanceError):
        p.trading_enabled = False  # type: ignore[misc]
    for bad in (True, -1, 1.5):
        with pytest.raises(ValueError):
            RiskPolicy(max_open_positions=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "policy,reason",
    [
        (RiskPolicy(trading_enabled=False), RiskReason.TRADING_DISABLED),
        (RiskPolicy(max_order_notional=Decimal(100)), RiskReason.MAX_ORDER_NOTIONAL),
        (RiskPolicy(max_product_exposure=Decimal(100)), RiskReason.MAX_PRODUCT_EXPOSURE),
        (RiskPolicy(max_portfolio_exposure=Decimal(100)), RiskReason.MAX_PORTFOLIO_EXPOSURE),
        (RiskPolicy(minimum_cash_reserve=Decimal(9950)), RiskReason.MINIMUM_CASH_RESERVE),
        (RiskPolicy(max_open_positions=0), RiskReason.MAX_OPEN_POSITIONS),
    ],
)
def test_every_cap(policy: RiskPolicy, reason: RiskReason) -> None:
    a = account()
    a.update_portfolio((candle(0),), candle(0).close_time)
    auth = RiskEngine(policy).authorize(state(a, minute=1), (request(kind=OrderType.LIMIT),))
    assert auth.decision.status is RiskDecisionStatus.REJECT
    assert reason in auth.decision.reasons
    assert auth.approved_requests == () and auth.reservation_plan is None


def test_exact_boundary_and_local_history() -> None:
    a = account()
    r = RiskEngine(RiskPolicy(max_order_notional=Decimal(101)))
    one = r.authorize(state(a), (request(kind=OrderType.LIMIT),))
    two = r.authorize(state(a), (request(kind=OrderType.LIMIT),))
    assert one.decision.status is RiskDecisionStatus.APPROVE
    assert [d.decision_id.value for d in r.decisions] == [1, 2]
    assert one.decision != two.decision
    fresh = RiskEngine(r.policy)
    fresh.authorize(state(a), (request(kind=OrderType.LIMIT),))
    fresh.authorize(state(a), (request(kind=OrderType.LIMIT),))
    assert fresh.decisions == r.decisions and fresh.risk_fingerprint == r.risk_fingerprint


@pytest.mark.parametrize("minute", [0, 2])
def test_stale_future_marks(minute: int) -> None:
    a = account()
    a.update_portfolio((candle(0),), candle(0).close_time)
    auth = RiskEngine(RiskPolicy(max_product_exposure=Decimal(1000))).authorize(
        state(a, minute=minute), (request(kind=OrderType.LIMIT),)
    )
    assert RiskReason.STALE_MARKET_DATA in auth.decision.reasons


def test_missing_marks_and_pre_snapshot_non_mark_limits() -> None:
    a = account()
    assert (
        RiskEngine(RiskPolicy(max_order_notional=Decimal(101)))
        .authorize(state(a), (request(kind=OrderType.LIMIT),))
        .approved_requests
    )
    for policy in (
        RiskPolicy(max_product_exposure=Decimal(1000)),
        RiskPolicy(max_portfolio_exposure=Decimal(1000)),
    ):
        assert (
            RiskReason.STALE_MARKET_DATA
            in RiskEngine(policy)
            .authorize(state(a), (request(kind=OrderType.LIMIT),))
            .decision.reasons
        )


@pytest.mark.parametrize("kind", [OrderType.MARKET, OrderType.STOP_MARKET])
def test_nonlimit_never_resized(kind: OrderType) -> None:
    auth = RiskEngine(
        RiskPolicy(max_order_notional=Decimal(50), allow_quantity_reduction=True)
    ).authorize(state(account()), (request(kind=kind),), max_quote_reservation=Decimal(100))
    assert auth.decision.status is RiskDecisionStatus.REJECT and auth.approved_requests == ()


def test_oco_not_resized_and_counted_once() -> None:
    a = account()
    b = SimulatedBroker(a.execution_spec)
    peers = (request(kind=OrderType.LIMIT), request(kind=OrderType.STOP_MARKET))
    plan = a.prepare_reservation(peers, max_quote_reservation=Decimal(200))
    orders = b.activate_oco(*peers, candle(0).open_time)
    a.bind_reservation(plan, orders, candle(0).open_time)
    auth = RiskEngine(
        RiskPolicy(max_order_notional=Decimal(50), allow_quantity_reduction=True)
    ).authorize(state(a, b), peers, max_quote_reservation=Decimal(100))
    assert auth.decision.baseline_product_exposure == 200
    assert auth.decision.baseline_portfolio_exposure == 200
    assert auth.decision.projected_open_positions == 1
    assert auth.decision.status is RiskDecisionStatus.REJECT


def test_pending_sell_does_not_net_and_owned_sell_escapes_caps() -> None:
    a = account(holding="2")
    b = SimulatedBroker(a.execution_spec)
    reserve(a, b, request(Side.SELL, OrderType.LIMIT))
    a.update_portfolio((candle(0),), candle(0).close_time)
    policy = RiskPolicy(
        trading_enabled=False,
        max_order_notional=Decimal(0),
        max_product_exposure=Decimal(0),
        max_portfolio_exposure=Decimal(0),
        max_open_positions=0,
        minimum_cash_reserve=Decimal(20000),
    )
    auth = RiskEngine(policy).authorize(state(a, b, 1), (request(Side.SELL),))
    assert auth.decision.status is RiskDecisionStatus.APPROVE
    assert auth.decision.direction is ExposureDirection.REDUCE_EXPOSURE
    assert auth.decision.baseline_product_exposure == 200
    assert auth.decision.projected_product_exposure == 200
    assert auth.decision.projected_available_cash == a.account_view.balance(USD).available
    reject = RiskEngine(policy).authorize(state(a, b, 1), (request(Side.SELL, quantity="2"),))
    assert RiskReason.INSUFFICIENT_BUYING_POWER in reject.decision.reasons


def test_modification_real_normalization_and_context() -> None:
    policy = RiskPolicy(max_order_notional=Decimal("50.505"), allow_quantity_reduction=True)
    outputs = []
    for precision in (2, 28, 60):
        with localcontext() as ctx:
            ctx.prec = precision
            r = RiskEngine(policy)
            auth = r.authorize(
                state(account()),
                (request(kind=OrderType.LIMIT, quantity="2.123", price="100.009"),),
            )
            assert auth.decision.status is RiskDecisionStatus.APPROVE_WITH_MODIFICATION
            assert auth.approved_requests[0].normalized_base_quantity.value == Decimal("0.50")
            assert auth.reservation_plan is not None and auth.reservation_plan.amount == Decimal(
                "50.5"
            )
            assert auth.approved_requests[0].source_intent.base_quantity.value == Decimal("0.50")
            outputs.append((auth, r.risk_fingerprint))
    assert outputs[0] == outputs[1] == outputs[2]


def test_state_canonicalization_and_fingerprints() -> None:
    a = account(holding="2")
    original = state(a)
    assert (
        replace(
            original,
            positions=tuple(reversed(original.positions)),
            account_view=replace(
                original.account_view, balances=tuple(reversed(original.account_view.balances))
            ),
        ).fingerprint
        == original.fingerprint
    )
    assert (
        replace(original, execution_spec=replace(original.execution_spec, fee_bps=2)).fingerprint
        != original.fingerprint
    )


def test_risk_dependency_boundaries() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "command_station"
    for package in ("risk", "execution", "accounting"):
        for path in (root / package).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if package != "risk":
                        assert not node.module.startswith("command_station.risk")
                    else:
                        assert not node.module.startswith(
                            (
                                "command_station.market_data",
                                "command_station.strategy",
                                "command_station.api",
                                "command_station.mcp",
                                "command_station.cli",
                            )
                        )


def test_future_intent_and_modified_reason_evidence() -> None:
    risk = RiskEngine(RiskPolicy(max_order_notional=Decimal(50), allow_quantity_reduction=True))
    with pytest.raises(ValueError, match="intent creation"):
        risk.authorize(state(account()), (request(kind=OrderType.LIMIT, minute=1),))
    assert risk.decisions == ()
    auth = risk.authorize(state(account()), (request(kind=OrderType.LIMIT),))
    assert auth.decision.status is RiskDecisionStatus.APPROVE_WITH_MODIFICATION
    assert auth.decision.reasons == (RiskReason.MAX_ORDER_NOTIONAL,)
