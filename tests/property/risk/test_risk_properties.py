from dataclasses import replace
from decimal import Decimal, localcontext

from hypothesis import given
from hypothesis import strategies as st

from command_station.domain import Side
from command_station.execution import OrderType, SimulatedBroker
from command_station.risk import RiskDecisionStatus, RiskEngine, RiskPolicy, RiskReason
from tests.accounting_fixtures import account, request, reserve
from tests.execution_fixtures import candle
from tests.risk_fixtures import state


@given(quantity=st.integers(1, 100), cap=st.integers(1, 1000), precision=st.integers(1, 50))
def test_modification_caps_context_and_fresh_identity(
    quantity: int, cap: int, precision: int
) -> None:
    policy = RiskPolicy(
        max_order_notional=Decimal(cap),
        minimum_cash_reserve=Decimal(9000),
        allow_quantity_reduction=True,
    )
    req = request(kind=OrderType.LIMIT, quantity=str(quantity), price="100")

    def evaluate() -> tuple[object, str]:
        r = RiskEngine(policy)
        auth = r.authorize(state(account()), (req,))
        if auth.decision.status is not RiskDecisionStatus.REJECT:
            assert auth.reservation_plan is not None
            assert auth.decision.approved_base_quantity is not None
            assert auth.decision.approved_base_quantity <= req.normalized_base_quantity.value
            assert auth.reservation_plan.amount <= auth.decision.requested_quote_commitment
            assert auth.reservation_plan.amount <= cap
            assert auth.decision.projected_available_cash >= 9000
        return auth, r.risk_fingerprint

    expected = evaluate()
    with localcontext() as ctx:
        ctx.prec = precision
        assert evaluate() == expected


@given(quantity=st.integers(1, 50))
def test_disabled_buy_and_safe_sell(quantity: int) -> None:
    a = account(holding=str(quantity))
    p = RiskPolicy(
        trading_enabled=False,
        max_product_exposure=Decimal(0),
        max_portfolio_exposure=Decimal(0),
        max_order_notional=Decimal(0),
        max_open_positions=0,
    )
    r = RiskEngine(p)
    assert (
        r.authorize(
            state(a), (request(quantity=str(quantity)),), max_quote_reservation=Decimal(100)
        ).decision.status
        is RiskDecisionStatus.REJECT
    )
    assert (
        r.authorize(state(a), (request(Side.SELL, quantity=str(quantity)),)).decision.status
        is RiskDecisionStatus.APPROVE
    )


@given(cap=st.integers(1, 1000), sell=st.booleans(), oco=st.booleans())
def test_pending_projection_non_netting_unique_oco(cap: int, sell: bool, oco: bool) -> None:
    a = account(holding="2")
    b = SimulatedBroker(a.execution_spec)
    a.update_portfolio((candle(0),), candle(0).close_time)
    before = RiskEngine().authorize(state(a, b, 1), (request(kind=OrderType.LIMIT),)).decision
    side = Side.SELL if sell else Side.BUY
    req = request(side, OrderType.LIMIT, price="0.01", minute=1)
    if oco:
        peers = (req, request(side, OrderType.STOP_MARKET, minute=1))
        plan = a.prepare_reservation(peers, max_quote_reservation=None if sell else Decimal(cap))
        orders = b.activate_oco(*peers, candle(0).close_time)
        a.bind_reservation(plan, orders, candle(0).close_time)
    else:
        reserve(a, b, request(side, minute=1), None if sell else Decimal(cap))
    after = RiskEngine().authorize(state(a, b, 1), (request(kind=OrderType.LIMIT),)).decision
    assert after.baseline_product_exposure == before.baseline_product_exposure + (
        0 if sell else cap
    )
    assert after.baseline_portfolio_exposure >= before.baseline_portfolio_exposure
    assert after.projected_open_positions == before.projected_open_positions == 1
    assert after.reasons == tuple(dict.fromkeys(after.reasons))
    shuffled = replace(state(a, b, 1), orders=tuple(reversed(b.orders)))
    assert shuffled.fingerprint == state(a, b, 1).fingerprint


@given(limit=st.integers(1, 500), pending=st.integers(1, 500))
def test_all_applicable_approval_caps(limit: int, pending: int) -> None:
    a = account()
    b = SimulatedBroker(a.execution_spec)
    reserve(a, b, request(), Decimal(pending))
    a.update_portfolio((candle(0),), candle(0).close_time)
    policy = RiskPolicy(
        max_order_notional=Decimal(limit),
        max_product_exposure=Decimal(limit),
        max_portfolio_exposure=Decimal(limit),
        minimum_cash_reserve=Decimal(9000),
        max_open_positions=1,
        allow_quantity_reduction=True,
    )
    auth = RiskEngine(policy).authorize(state(a, b, 1), (request(kind=OrderType.LIMIT),))
    if auth.approved_requests:
        d = auth.decision
        assert d.approved_quote_commitment is not None and d.approved_quote_commitment <= limit
        assert d.projected_product_exposure <= limit
        assert d.projected_portfolio_exposure <= limit
        assert d.projected_available_cash >= 9000
        assert d.projected_open_positions <= 1
    assert auth.decision.reasons == tuple(r for r in RiskReason if r in auth.decision.reasons)


@given(first_count=st.integers(1, 5), cap=st.integers(0, 2))
def test_open_positions_unique_products(first_count: int, cap: int) -> None:
    from command_station.accounting import SpotAccountingEngine, SpotAccountSpec
    from command_station.execution import normalize_order_intent
    from tests.execution_fixtures import product, timestamp

    products = (product(), product("ETH-USD"))
    a = SpotAccountingEngine(
        SpotAccountSpec(initial_cash="1000", product_specs=products), timestamp()
    )
    b = SimulatedBroker(a.execution_spec)
    for _ in range(first_count):
        reserve(a, b, request(), Decimal(1))
    intent = replace(request().source_intent, product_id=products[1].product_id)
    req = normalize_order_intent(intent, products[1])
    auth = RiskEngine(RiskPolicy(max_open_positions=cap)).authorize(
        state(a, b), (req,), max_quote_reservation=Decimal(1)
    )
    assert auth.decision.projected_open_positions == 2
    assert (auth.decision.status is RiskDecisionStatus.APPROVE) == (cap == 2)
