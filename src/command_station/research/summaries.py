"""Summaries from recorded broker/risk facts, never a second evaluation."""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from command_station.accounting._exact import add, mul
from command_station.execution import Fill, Order, OrderStatus
from command_station.risk import RiskDecision, RiskDecisionStatus


@dataclass(frozen=True, slots=True)
class RiskSummary:
    decision_count: int
    approve_count: int
    modified_count: int
    reject_count: int
    reason_counts: tuple[tuple[str, int], ...]

    @classmethod
    def derive(cls, decisions: tuple[RiskDecision, ...]) -> "RiskSummary":
        reasons = Counter(reason.value for d in decisions for reason in d.reasons)
        return cls(
            len(decisions),
            sum(d.status is RiskDecisionStatus.APPROVE for d in decisions),
            sum(d.status is RiskDecisionStatus.APPROVE_WITH_MODIFICATION for d in decisions),
            sum(d.status is RiskDecisionStatus.REJECT for d in decisions),
            tuple(sorted(reasons.items())),
        )


@dataclass(frozen=True, slots=True)
class ExecutionSummary:
    order_count: int
    fill_count: int
    active_order_count: int
    filled_order_count: int
    cancelled_order_count: int
    gap_fill_count: int
    ambiguous_fill_count: int
    total_fees: Decimal
    total_slippage_cost: Decimal

    @classmethod
    def derive(cls, orders: tuple[Order, ...], fills: tuple[Fill, ...]) -> "ExecutionSummary":
        return cls(
            len(orders),
            len(fills),
            sum(o.status not in (OrderStatus.FILLED, OrderStatus.CANCELLED) for o in orders),
            sum(o.status is OrderStatus.FILLED for o in orders),
            sum(o.status is OrderStatus.CANCELLED for o in orders),
            sum(f.gap for f in fills),
            sum(f.ambiguity for f in fills),
            add(*(f.fee_amount for f in fills)),
            add(*(mul(f.slippage_per_base, f.base_quantity) for f in fills)),
        )
