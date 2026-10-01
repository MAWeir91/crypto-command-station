"""Immutable semantic risk configuration."""

from dataclasses import dataclass, fields
from decimal import Decimal

from command_station.accounting._exact import fingerprint, logical

RISK_POLICY_SCHEMA_VERSION = 1
RISK_MODEL_VERSION = 1
RISK_FINGERPRINT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    trading_enabled: bool = True
    max_order_notional: Decimal | None = None
    max_product_exposure: Decimal | None = None
    max_portfolio_exposure: Decimal | None = None
    minimum_cash_reserve: Decimal = Decimal(0)
    max_open_positions: int | None = None
    allow_quantity_reduction: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.trading_enabled) is not bool
            or type(self.allow_quantity_reduction) is not bool
        ):
            raise ValueError("risk switches require bool")
        for value in (
            self.max_order_notional,
            self.max_product_exposure,
            self.max_portfolio_exposure,
            self.minimum_cash_reserve,
        ):
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite() or value < 0
            ):
                raise ValueError("risk limits require finite nonnegative Decimal")
        if self.minimum_cash_reserve is None:
            raise ValueError("cash reserve is required")
        if self.max_open_positions is not None and (
            type(self.max_open_positions) is not int or self.max_open_positions < 0
        ):
            raise ValueError("position limit requires nonnegative int")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": RISK_POLICY_SCHEMA_VERSION,
            "risk_model_version": RISK_MODEL_VERSION,
            **{field.name: logical(getattr(self, field.name)) for field in fields(self)},
        }

    @property
    def fingerprint(self) -> str:
        return fingerprint((RISK_POLICY_SCHEMA_VERSION, RISK_MODEL_VERSION, self))
