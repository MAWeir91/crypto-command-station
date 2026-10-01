"""Immutable reference-execution configuration, fill facts, and events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from command_station.domain import AssetSymbol, ProductId, Side, UtcTimestamp, decimal_to_text
from command_station.execution.orders import FillId, OrderId

EXECUTION_SPEC_SCHEMA_VERSION = 1
EXECUTION_FINGERPRINT_SCHEMA_VERSION = 1
EXECUTION_MODEL_VERSION = "reference-candle-v1"


class ExecutionValidationError(ValueError):
    """Raised when reference execution configuration is invalid."""


class ExecutionResolution(StrEnum):
    EXACT_NEXT_OPEN = "EXACT_NEXT_OPEN"
    PRICE_CROSSED = "PRICE_CROSSED"
    GAP = "GAP"
    AMBIGUOUS_CONSERVATIVE = "AMBIGUOUS_CONSERVATIVE"


class ExecutionSource(StrEnum):
    SIMULATED_ONE_MINUTE_CANDLE = "SIMULATED_ONE_MINUTE_CANDLE"


class ExecutionEventKind(StrEnum):
    ORDER_ACTIVATED = "ORDER_ACTIVATED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
    ORDER_FILLED = "ORDER_FILLED"
    FILL_CREATED = "FILL_CREATED"
    OCO_GROUP_ACTIVATED = "OCO_GROUP_ACTIVATED"


@dataclass(frozen=True, slots=True)
class ReferenceExecutionSpec:
    slippage_bps: int = 0
    fee_bps: int = 0

    def __post_init__(self) -> None:
        if (
            type(self.slippage_bps) is not int
            or not 0 <= self.slippage_bps < 10_000
            or type(self.fee_bps) is not int
            or self.fee_bps < 0
        ):
            raise ExecutionValidationError("execution basis points are invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(self.to_dict())

    def to_dict(self) -> dict[str, int]:
        """Return the stable serializable v1 configuration content."""
        return {
            "schema_version": EXECUTION_SPEC_SCHEMA_VERSION,
            "slippage_bps": self.slippage_bps,
            "fee_bps": self.fee_bps,
        }


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: FillId
    order_id: OrderId
    product_id: ProductId
    side: Side
    base_quantity: Decimal
    reference_price: Decimal
    fill_price: Decimal
    fee_asset: AssetSymbol
    fee_amount: Decimal
    fee_bps: int
    slippage_per_base: Decimal
    execution_source: ExecutionSource
    execution_model_version: str
    execution_spec_fingerprint: str
    resolution: ExecutionResolution
    ambiguity: bool
    gap: bool
    activated_at: UtcTimestamp
    market_interval_open: UtcTimestamp
    market_interval_close: UtcTimestamp
    executed_at: UtcTimestamp
    product_spec_fingerprint: str


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    sequence: int
    timestamp: UtcTimestamp
    kind: ExecutionEventKind
    order_id: OrderId | None = None
    fill_id: FillId | None = None
    details: tuple[tuple[str, str], ...] = ()


def _hash(content: object) -> str:
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return sha256(encoded).hexdigest()


def decimal_content(value: Decimal) -> str:
    return decimal_to_text(value)
