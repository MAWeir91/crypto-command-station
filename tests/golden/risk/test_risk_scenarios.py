from decimal import Decimal

from command_station.domain import Side
from command_station.execution import OrderType
from command_station.risk import RiskDecisionStatus, RiskPolicy, RiskReason
from tests.accounting_fixtures import request
from tests.risk_fixtures import runtime


def test_golden_trading_disabled_escape() -> None:
    rt = runtime(RiskPolicy(trading_enabled=False), holding="2")
    buy = rt.activate_order(request(), max_quote_reservation=Decimal(100))
    sell = rt.activate_order(request(Side.SELL))
    assert (buy.decision.status, buy.decision.reasons, sell.decision.status) == (
        RiskDecisionStatus.REJECT,
        (RiskReason.TRADING_DISABLED,),
        RiskDecisionStatus.APPROVE,
    )
    assert rt.step() is not None
    assert rt.accounting is not None and rt.accounting.positions[0].actual_quantity == 1


def test_golden_pending_buy_counts() -> None:
    rt = runtime(RiskPolicy(max_product_exposure=Decimal(150)))
    rt.step()
    first = rt.activate_order(request(kind=OrderType.LIMIT))
    second = rt.activate_order(request(kind=OrderType.LIMIT))
    assert first.decision.status is RiskDecisionStatus.APPROVE
    assert second.decision.baseline_product_exposure == 101
    assert second.decision.projected_product_exposure == 202
    assert second.decision.reasons == (
        RiskReason.MAX_PRODUCT_EXPOSURE,
        RiskReason.MODIFICATION_NOT_ALLOWED,
    )


def test_golden_conservative_modification() -> None:
    rt = runtime(RiskPolicy(max_order_notional=Decimal("50.505"), allow_quantity_reduction=True))
    result = rt.activate_order(request(kind=OrderType.LIMIT, quantity="2"))
    assert result.decision.status is RiskDecisionStatus.APPROVE_WITH_MODIFICATION
    assert (
        result.decision.requested_base_quantity,
        result.decision.approved_base_quantity,
        result.decision.requested_quote_commitment,
        result.decision.approved_quote_commitment,
    ) == (Decimal(2), Decimal("0.5"), Decimal(202), Decimal("50.5"))
    assert result.orders[0].activated_base_quantity.value == Decimal("0.5")


def test_golden_minimum_after_reduction() -> None:
    rt = runtime(RiskPolicy(max_order_notional=Decimal("0.01"), allow_quantity_reduction=True))
    result = rt.activate_order(request(kind=OrderType.LIMIT))
    assert result.orders == ()
    assert result.decision.reasons == (RiskReason.MAX_ORDER_NOTIONAL, RiskReason.MIN_ORDER_SIZE)


def test_golden_post_fill_state() -> None:
    rt = runtime(RiskPolicy(max_portfolio_exposure=Decimal(101)))
    rt.step()
    first = rt.activate_order(request(kind=OrderType.LIMIT))
    rt.step()
    second = rt.activate_order(request(kind=OrderType.LIMIT))
    assert second.decision.baseline_portfolio_exposure == 1
    assert second.decision.projected_portfolio_exposure == 102
    assert second.decision.status is RiskDecisionStatus.REJECT
    assert RiskReason.MAX_PORTFOLIO_EXPOSURE in second.decision.reasons
    assert first.decision.state_fingerprint != second.decision.state_fingerprint
    assert second.decision.projected_available_cash == Decimal("897.99")
    assert rt.accounting is not None and rt.accounting.positions[0].actual_quantity == 1


def test_golden_oco_once() -> None:
    rt = runtime(RiskPolicy(max_portfolio_exposure=Decimal(250)))
    rt.step()
    peers = (request(kind=OrderType.LIMIT), request(kind=OrderType.STOP_MARKET))
    rt.activate_oco(*peers, max_quote_reservation=Decimal(100))
    result = rt.activate_order(request(kind=OrderType.LIMIT))
    assert result.decision.baseline_portfolio_exposure == 100
    assert result.decision.projected_portfolio_exposure == 201
    assert result.decision.projected_open_positions == 1
    assert result.decision.status is RiskDecisionStatus.APPROVE
