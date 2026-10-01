"""Immutable spot account input and financial evidence values."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from command_station.accounting._exact import fingerprint, sub
from command_station.domain import (
    AssetSymbol,
    DecimalInput,
    ProductId,
    ProductSpec,
    ProductType,
    UtcTimestamp,
    Venue,
    require_non_negative,
    require_positive,
)
from command_station.execution import FillId, OrderId

ACCOUNTING_MODEL_VERSION = 1
LEDGER_SCHEMA_VERSION = 1
ACCOUNTING_FINGERPRINT_SCHEMA_VERSION = 1
LOT_DEPLETION_POLICY = "FIFO-v1"
AVERAGE_COST_DISPLAY_PLACES = 8
AVERAGE_COST_DISPLAY_ROUNDING = "ROUND_HALF_EVEN"
USD = AssetSymbol("USD")


class AccountingValidationError(ValueError):
    """Invalid account input or activation funding."""


class InsufficientAvailableBalanceError(AccountingValidationError):
    """An order cannot reserve resources not already owned."""


class AccountingInvariantError(RuntimeError):
    """Financial truth cannot be preserved; the runtime must fail."""


@dataclass(frozen=True, slots=True, order=True)
class LedgerTransactionId:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise AccountingValidationError("identity must be positive integer")


@dataclass(frozen=True, slots=True, order=True)
class ReservationId(LedgerTransactionId):
    pass


@dataclass(frozen=True, slots=True, order=True)
class LotId(LedgerTransactionId):
    pass


@dataclass(frozen=True, slots=True, order=True)
class LotConsumptionId(LedgerTransactionId):
    pass


@dataclass(frozen=True, slots=True)
class InitialHolding:
    product_id: ProductId
    base_quantity: Decimal
    unit_cost: Decimal

    def __init__(
        self, product_id: ProductId, base_quantity: DecimalInput, unit_cost: DecimalInput
    ) -> None:
        if not isinstance(product_id, ProductId):
            raise AccountingValidationError("holding requires ProductId")
        object.__setattr__(self, "product_id", product_id)
        object.__setattr__(self, "base_quantity", require_positive(base_quantity))
        object.__setattr__(self, "unit_cost", require_non_negative(unit_cost))


@dataclass(frozen=True, slots=True)
class SpotAccountSpec:
    initial_cash: Decimal
    initial_holdings: tuple[InitialHolding, ...]
    product_specs: tuple[ProductSpec, ...]

    def __init__(
        self,
        *,
        initial_cash: DecimalInput,
        product_specs: tuple[ProductSpec, ...],
        initial_holdings: tuple[InitialHolding, ...] = (),
    ) -> None:
        cash = require_non_negative(initial_cash)
        products = tuple(product_specs)
        holdings = tuple(initial_holdings)
        if any(
            not isinstance(p, ProductSpec)
            or p.venue is not Venue.COINBASE
            or p.product_type is not ProductType.SPOT
            or p.quote_currency != USD
            or p.base_currency == USD
            for p in products
        ):
            raise AccountingValidationError(
                "account supports Coinbase spot with distinct noncash base and USD quote"
            )
        if len({p.product_id for p in products}) != len(products) or len(
            {p.base_currency for p in products}
        ) != len(products):
            raise AccountingValidationError("duplicate product or base asset")
        if any(
            not isinstance(h, InitialHolding)
            or h.product_id not in {p.product_id for p in products}
            for h in holdings
        ) or len({h.product_id for h in holdings}) != len(holdings):
            raise AccountingValidationError("holdings must map uniquely to registered products")
        object.__setattr__(self, "initial_cash", cash)
        object.__setattr__(
            self, "product_specs", tuple(sorted(products, key=lambda p: p.product_id.value))
        )
        object.__setattr__(
            self, "initial_holdings", tuple(sorted(holdings, key=lambda h: h.product_id.value))
        )

    @property
    def fingerprint(self) -> str:
        return fingerprint(
            (
                ACCOUNTING_MODEL_VERSION,
                self.initial_cash,
                self.initial_holdings,
                tuple(p.fingerprint for p in self.product_specs),
            )
        )


class LedgerCategory(StrEnum):
    INITIAL_DEPOSIT = "INITIAL_DEPOSIT"
    ORDER_RESERVATION = "ORDER_RESERVATION"
    ORDER_RESERVATION_RELEASE = "ORDER_RESERVATION_RELEASE"
    TRADE_FILL = "TRADE_FILL"
    TRADING_FEE = "TRADING_FEE"


@dataclass(frozen=True, slots=True)
class LedgerPosting:
    asset: AssetSymbol
    balance_delta: Decimal = Decimal(0)
    reserved_delta: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if not isinstance(self.asset, AssetSymbol) or any(
            not isinstance(v, Decimal) or not v.is_finite()
            for v in (self.balance_delta, self.reserved_delta)
        ):
            raise AccountingValidationError("posting requires asset and finite exact deltas")


@dataclass(frozen=True, slots=True)
class LedgerTransaction:
    transaction_id: LedgerTransactionId
    timestamp: UtcTimestamp
    category: LedgerCategory
    postings: tuple[LedgerPosting, ...]
    order_id: OrderId | None = None
    fill_id: FillId | None = None
    reservation_id: ReservationId | None = None


@dataclass(frozen=True, slots=True)
class AccountBalance:
    asset: AssetSymbol
    total: Decimal
    reserved: Decimal

    @property
    def available(self) -> Decimal:
        return sub(self.total, self.reserved)

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(v, Decimal) or not v.is_finite() for v in (self.total, self.reserved)
            )
            or not 0 <= self.reserved <= self.total
        ):
            raise AccountingInvariantError("balance invariant: total >= reserved >= 0")


@dataclass(frozen=True, slots=True)
class AccountView:
    balances: tuple[AccountBalance, ...]

    def balance(self, asset: AssetSymbol) -> AccountBalance:
        for balance in self.balances:
            if balance.asset == asset:
                return balance
        return AccountBalance(asset, Decimal(0), Decimal(0))


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class OrderReservation:
    reservation_id: ReservationId
    order_ids: tuple[OrderId, ...]
    asset: AssetSymbol
    original_amount: Decimal
    remaining_amount: Decimal
    created_at: UtcTimestamp
    status: ReservationStatus


class LotSource(StrEnum):
    INITIAL_HOLDING = "INITIAL_HOLDING"
    BUY_FILL = "BUY_FILL"


@dataclass(frozen=True, slots=True)
class AcquisitionLot:
    lot_id: LotId
    product_id: ProductId
    base_asset: AssetSymbol
    original_quantity: Decimal
    unit_cost: Decimal
    opened_at: UtcTimestamp
    source: LotSource
    source_fill_id: FillId | None = None


@dataclass(frozen=True, slots=True)
class LotConsumption:
    consumption_id: LotConsumptionId
    lot_id: LotId
    sell_fill_id: FillId
    quantity: Decimal
    unit_cost: Decimal
    sell_price: Decimal
    gross_realized_pnl: Decimal
    timestamp: UtcTimestamp


@dataclass(frozen=True, slots=True)
class PositionView:
    product_id: ProductId
    base_asset: AssetSymbol
    actual_quantity: Decimal
    tradable_quantity: Decimal
    dust_quantity: Decimal
    total_cost_basis: Decimal
    average_cost_display: Decimal | None
    gross_realized_pnl: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    timestamp: UtcTimestamp
    cash_total: Decimal
    cash_reserved: Decimal
    cash_available: Decimal
    marked_asset_value: Decimal
    total_equity: Decimal
    gross_realized_pnl: Decimal
    gross_unrealized_pnl: Decimal
    fees_to_date: Decimal
    positions: tuple[PositionView, ...]
    marks: tuple[tuple[ProductId, Decimal], ...]
