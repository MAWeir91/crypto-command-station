"""Deterministic, pure financial authorization with append-only audit history."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

from command_station.accounting import USD, InsufficientAvailableBalanceError
from command_station.accounting._exact import ZERO, add, decimal, fee, fingerprint, mul, sub
from command_station.accounting.reservations import ReservationPlan, prepare_reservation
from command_station.domain import Side
from command_station.execution import (
    BaseQuantity,
    NormalizedOrderRequest,
    OrderType,
    normalize_order_intent,
)
from command_station.execution.normalization import OrderNormalizationError
from command_station.risk.models import (
    ExposureDirection,
    RiskAuthorization,
    RiskDecision,
    RiskDecisionId,
    RiskDecisionStatus,
    RiskReason,
    RiskStateSnapshot,
)
from command_station.risk.policy import (
    RISK_FINGERPRINT_SCHEMA_VERSION,
    RISK_MODEL_VERSION,
    RiskPolicy,
)
from command_station.risk.projection import baseline


class RiskEngine:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        if policy is None:
            policy = RiskPolicy()
        if not isinstance(policy, RiskPolicy):
            raise ValueError("risk engine requires RiskPolicy")
        self._policy = policy
        self._history: list[RiskDecision] = []

    @property
    def policy(self) -> RiskPolicy:
        return self._policy

    @property
    def decisions(self) -> tuple[RiskDecision, ...]:
        return tuple(self._history)

    @property
    def risk_fingerprint(self) -> str:
        return fingerprint(
            (
                RISK_FINGERPRINT_SCHEMA_VERSION,
                RISK_MODEL_VERSION,
                self.policy.fingerprint,
                self.decisions,
            )
        )

    def authorize(
        self,
        state: RiskStateSnapshot,
        requests: tuple[NormalizedOrderRequest, ...],
        *,
        max_quote_reservation: Decimal | None = None,
    ) -> RiskAuthorization:
        state.validate_consistency()
        requests = tuple(sorted(requests, key=lambda r: r.order_type.value))
        if any(request.created_at > state.timestamp for request in requests):
            raise ValueError("risk proposal precedes intent creation")
        # Structural failures propagate. Only ordinary resource insufficiency is a decision.
        plan: ReservationPlan | None = None
        funding_failed = False
        try:
            plan = prepare_reservation(
                state.account_spec,
                state.execution_spec,
                state.account_view,
                requests,
                max_quote_reservation,
            )
        except InsufficientAvailableBalanceError:
            funding_failed = True
        first = requests[0]
        buying = first.side is Side.BUY
        direction = (
            ExposureDirection.INCREASE_EXPOSURE if buying else ExposureDirection.REDUCE_EXPOSURE
        )
        commitment = ZERO
        if buying:
            if len(requests) == 1 and first.order_type is OrderType.LIMIT:
                assert first.limit_price is not None
                gross = mul(first.limit_price, first.normalized_base_quantity.value)
                commitment = add(gross, fee(gross, state.execution_spec.fee_bps))
            else:
                assert max_quote_reservation is not None
                commitment = max_quote_reservation
        requested_commitment = commitment
        product_base, portfolio_base, opened = baseline(state, first.product_id)
        cash = state.account_view.balance(USD).available
        count = len(opened | ({first.product_id} if buying else set()))
        reasons = self._reasons(state, first, commitment, product_base, portfolio_base, cash, count)
        if funding_failed:
            reasons.append(RiskReason.INSUFFICIENT_BUYING_POWER)
        modification_reasons: list[RiskReason] = []
        status = RiskDecisionStatus.APPROVE
        approved = requests
        modifiable = buying and len(requests) == 1 and first.order_type is OrderType.LIMIT
        terminal = {
            RiskReason.TRADING_DISABLED,
            RiskReason.STALE_MARKET_DATA,
            RiskReason.MAX_OPEN_POSITIONS,
        }
        if reasons and modifiable and not terminal.intersection(reasons):
            if not self.policy.allow_quantity_reduction:
                reasons.append(RiskReason.MODIFICATION_NOT_ALLOWED)
            else:
                headroom = [sub(cash, self.policy.minimum_cash_reserve)]
                if self.policy.max_order_notional is not None:
                    headroom.append(self.policy.max_order_notional)
                if self.policy.max_product_exposure is not None:
                    headroom.append(sub(self.policy.max_product_exposure, product_base))
                if self.policy.max_portfolio_exposure is not None:
                    headroom.append(sub(self.policy.max_portfolio_exposure, portfolio_base))
                increment = first.product_spec.base_increment
                assert first.limit_price is not None
                unit_commitment = Fraction(first.limit_price) * (
                    1 + Fraction(state.execution_spec.fee_bps, 10_000)
                )
                steps = max(0, Fraction(min(headroom)) // (unit_commitment * Fraction(increment)))
                quantity = min(
                    first.normalized_base_quantity.value, decimal(Fraction(increment) * steps)
                )
                try:
                    reduced = normalize_order_intent(
                        replace(first.source_intent, base_quantity=BaseQuantity(quantity)),
                        first.product_spec,
                    )
                except (OrderNormalizationError, ValueError):
                    reasons.append(RiskReason.MIN_ORDER_SIZE)
                else:
                    try:
                        reduced_plan = prepare_reservation(
                            state.account_spec,
                            state.execution_spec,
                            state.account_view,
                            (reduced,),
                            None,
                        )
                    except InsufficientAvailableBalanceError:
                        reasons.append(RiskReason.INSUFFICIENT_BUYING_POWER)
                    else:
                        recheck = self._reasons(
                            state,
                            reduced,
                            reduced_plan.amount,
                            product_base,
                            portfolio_base,
                            cash,
                            count,
                        )
                        if recheck:
                            reasons.extend(recheck)
                        elif (
                            reduced.normalized_base_quantity.value
                            > first.normalized_base_quantity.value
                            or reduced_plan.amount > requested_commitment
                        ):
                            raise ValueError("risk modification increased exposure")
                        else:
                            approved, plan, commitment = (
                                (reduced,),
                                reduced_plan,
                                reduced_plan.amount,
                            )
                            modification_reasons = reasons
                            reasons = []
                            status = RiskDecisionStatus.APPROVE_WITH_MODIFICATION
        if reasons:
            status, approved, plan = RiskDecisionStatus.REJECT, (), None
        ordered_reasons = tuple(r for r in RiskReason if r in (reasons or modification_reasons))
        decision = RiskDecision(
            RiskDecisionId(len(self._history) + 1),
            state.timestamp,
            status,
            direction,
            first.product_id,
            first.normalized_base_quantity.value,
            approved[0].normalized_base_quantity.value if approved else None,
            requested_commitment,
            commitment if approved else None,
            ordered_reasons,
            self.policy.fingerprint,
            state.fingerprint,
            fingerprint((requests, max_quote_reservation)),
            product_base,
            add(product_base, commitment),
            portfolio_base,
            add(portfolio_base, commitment),
            sub(cash, commitment),
            count,
        )
        self._history.append(decision)
        return RiskAuthorization(decision, approved, plan)

    def _reasons(
        self,
        state: RiskStateSnapshot,
        request: NormalizedOrderRequest,
        commitment: Decimal,
        product: Decimal,
        portfolio: Decimal,
        cash: Decimal,
        count: int,
    ) -> list[RiskReason]:
        if request.side is Side.SELL:
            return []
        policy = self.policy
        reasons = []
        if not policy.trading_enabled:
            reasons.append(RiskReason.TRADING_DISABLED)
        needs_marks = (
            policy.max_product_exposure is not None or policy.max_portfolio_exposure is not None
        )
        snapshot = state.portfolio_snapshot
        required = {p.product_id for p in state.positions if p.actual_quantity > 0}
        if policy.max_product_exposure is not None:
            required.add(request.product_id)
        if needs_marks and (
            snapshot is None
            or snapshot.timestamp != state.timestamp
            or not required.issubset(dict(snapshot.marks))
        ):
            reasons.append(RiskReason.STALE_MARKET_DATA)
        for limit, value, reason in (
            (policy.max_order_notional, commitment, RiskReason.MAX_ORDER_NOTIONAL),
            (
                policy.max_product_exposure,
                add(product, commitment),
                RiskReason.MAX_PRODUCT_EXPOSURE,
            ),
            (
                policy.max_portfolio_exposure,
                add(portfolio, commitment),
                RiskReason.MAX_PORTFOLIO_EXPOSURE,
            ),
        ):
            if limit is not None and value > limit:
                reasons.append(reason)
        if sub(cash, commitment) < policy.minimum_cash_reserve:
            reasons.append(RiskReason.MINIMUM_CASH_RESERVE)
        if policy.max_open_positions is not None and count > policy.max_open_positions:
            reasons.append(RiskReason.MAX_OPEN_POSITIONS)
        return reasons
