"""Pure reservation planning before broker mutation."""

from dataclasses import dataclass
from decimal import Decimal

from command_station.accounting._exact import add, fee, mul
from command_station.accounting.models import (
    USD,
    AccountingValidationError,
    AccountView,
    InsufficientAvailableBalanceError,
    SpotAccountSpec,
)
from command_station.domain import AssetSymbol, Side, require_positive
from command_station.execution import NormalizedOrderRequest, OrderType, ReferenceExecutionSpec
from command_station.execution.normalization import verify_normalized_order_request


@dataclass(frozen=True, slots=True)
class ReservationPlan:
    requests: tuple[NormalizedOrderRequest, ...]
    asset: AssetSymbol
    amount: Decimal


def prepare_reservation(
    spec: SpotAccountSpec,
    execution: ReferenceExecutionSpec,
    account: AccountView,
    requests: tuple[NormalizedOrderRequest, ...],
    max_quote_reservation: Decimal | None,
) -> ReservationPlan:
    if len(requests) not in (1, 2):
        raise AccountingValidationError("reservation covers one order or one OCO pair")
    products = {p.product_id: p for p in spec.product_specs}
    for request in requests:
        verify_normalized_order_request(request)
        product = products.get(request.product_id)
        if (
            product is None
            or product.fingerprint != request.product_spec_fingerprint
            or product.base_currency != request.base_currency
            or product.quote_currency != request.quote_currency
        ):
            raise AccountingValidationError("reservation ProductSpec mismatch")
    first = requests[0]
    if len(requests) == 2:
        second = requests[1]
        if (
            first.product_id != second.product_id
            or first.side is not second.side
            or first.normalized_base_quantity != second.normalized_base_quantity
            or {first.order_type, second.order_type} != {OrderType.LIMIT, OrderType.STOP_MARKET}
        ):
            raise AccountingValidationError("invalid exclusive OCO reservation")
    if first.side is Side.SELL:
        if max_quote_reservation is not None:
            raise AccountingValidationError("SELL does not accept quote funding cap")
        asset, amount = first.base_currency, first.normalized_base_quantity.value
    elif len(requests) == 1 and first.order_type is OrderType.LIMIT:
        if max_quote_reservation is not None or first.limit_price is None:
            raise AccountingValidationError(
                "BUY LIMIT reserves exact limit settlement automatically"
            )
        gross = mul(first.limit_price, first.normalized_base_quantity.value)
        asset, amount = USD, add(gross, fee(gross, execution.fee_bps))
    else:
        if not isinstance(max_quote_reservation, Decimal):
            raise AccountingValidationError(
                "BUY market/stop/OCO requires explicit Decimal quote funding cap"
            )
        asset, amount = USD, require_positive(max_quote_reservation)
    if account.balance(asset).available < amount:
        raise InsufficientAvailableBalanceError("insufficient available owned balance")
    return ReservationPlan(requests, asset, amount)
