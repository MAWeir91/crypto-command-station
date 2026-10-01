"""Instance-scoped deterministic one-minute candle execution broker."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction

from command_station.domain import Candle, ProductId, Side, Timeframe, UtcTimestamp, decimal_to_text
from command_station.execution.models import (
    EXECUTION_FINGERPRINT_SCHEMA_VERSION,
    EXECUTION_MODEL_VERSION,
    ExecutionEvent,
    ExecutionEventKind,
    ExecutionResolution,
    ExecutionSource,
    Fill,
    ReferenceExecutionSpec,
    _hash,
)
from command_station.execution.normalization import (
    OrderNormalizationError,
    verify_normalized_order_request,
)
from command_station.execution.orders import (
    CancellationReason,
    FillId,
    NormalizedOrderRequest,
    OcoGroupId,
    Order,
    OrderId,
    OrderStatus,
    OrderType,
    OrderValidationError,
)


class BrokerStateError(RuntimeError):
    """Raised when broker lifecycle or market input would violate execution truth."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    order: Order
    candle: Candle
    reference_price: Decimal
    fill_price: Decimal
    resolution: ExecutionResolution
    gap: bool
    executed_at: UtcTimestamp


class SimulatedBroker:
    """Reference broker owning only order/execution state and immutable fill facts."""

    def __init__(self, spec: ReferenceExecutionSpec | None = None) -> None:
        self.spec = spec if spec is not None else ReferenceExecutionSpec()
        if not isinstance(self.spec, ReferenceExecutionSpec):
            raise BrokerStateError("broker requires ReferenceExecutionSpec")
        self._next_order_id = 1
        self._next_fill_id = 1
        self._next_oco_group_id = 1
        self._orders: dict[OrderId, Order] = {}
        self._fills: list[Fill] = []
        self._events: list[ExecutionEvent] = []

    @property
    def orders(self) -> tuple[Order, ...]:
        return tuple(self._orders[key] for key in sorted(self._orders))

    @property
    def fills(self) -> tuple[Fill, ...]:
        return tuple(self._fills)

    @property
    def events(self) -> tuple[ExecutionEvent, ...]:
        return tuple(self._events)

    @property
    def execution_fingerprint(self) -> str:
        content = {
            "execution_fingerprint_schema_version": EXECUTION_FINGERPRINT_SCHEMA_VERSION,
            "execution_spec_fingerprint": self.spec.fingerprint,
            "events": [self._event_content(event) for event in self._events],
            "fills": [self._fill_content(fill) for fill in self.fills],
            "orders": [self._order_content(order) for order in self.orders],
        }
        return _hash(content)

    def get_order(self, order_id: OrderId) -> Order:
        try:
            return self._orders[order_id]
        except KeyError as error:
            raise BrokerStateError("unknown order ID") from error

    def activate(self, request: NormalizedOrderRequest, activated_at: UtcTimestamp) -> Order:
        self._validate_activation(request, activated_at)
        order_id = self._allocate_order_id()
        quantity = request.normalized_base_quantity.value
        order = Order(
            order_id=order_id,
            product_id=request.product_id,
            base_currency=request.base_currency,
            quote_currency=request.quote_currency,
            side=request.side,
            order_type=request.order_type,
            requested_base_quantity=request.requested_base_quantity,
            activated_base_quantity=request.normalized_base_quantity,
            filled_base_quantity=Decimal(0),
            remaining_base_quantity=quantity,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            created_at=request.created_at,
            activated_at=activated_at,
            status=OrderStatus.ACTIVE,
            product_spec_fingerprint=request.product_spec_fingerprint,
        )
        self._orders[order_id] = order
        self._emit(ExecutionEventKind.ORDER_ACTIVATED, activated_at, order_id=order_id)
        return order

    def activate_oco(
        self,
        first: NormalizedOrderRequest,
        second: NormalizedOrderRequest,
        activated_at: UtcTimestamp,
    ) -> tuple[Order, Order]:
        self._validate_oco_requests(first, second)
        self._validate_activation(first, activated_at)
        self._validate_activation(second, activated_at)
        group_id = OcoGroupId(self._next_oco_group_id)
        self._next_oco_group_id += 1
        first_order = replace(self.activate(first, activated_at), oco_group_id=group_id)
        second_order = replace(self.activate(second, activated_at), oco_group_id=group_id)
        self._orders[first_order.order_id] = first_order
        self._orders[second_order.order_id] = second_order
        self._emit(
            ExecutionEventKind.OCO_GROUP_ACTIVATED,
            activated_at,
            details=(
                ("oco_group_id", str(group_id.value)),
                ("first_order_id", str(first_order.order_id.value)),
                ("second_order_id", str(second_order.order_id.value)),
            ),
        )
        return first_order, second_order

    def cancel(
        self,
        order_id: OrderId,
        cancelled_at: UtcTimestamp,
        reason: CancellationReason = CancellationReason.USER_REQUEST,
    ) -> Order:
        order = self.get_order(order_id)
        try:
            cancelled = order.cancel(cancelled_at, reason)
        except OrderValidationError as error:
            raise BrokerStateError(str(error)) from error
        self._orders[order_id] = cancelled
        self._emit(
            ExecutionEventKind.ORDER_CANCELLED,
            cancelled_at,
            order_id=order_id,
            details=(("reason", reason.value),),
        )
        return cancelled

    def process_market_activity(
        self,
        execution_intervals: tuple[Candle, ...],
        processed_at: UtcTimestamp,
    ) -> tuple[Fill, ...]:
        candles = self._validate_intervals(execution_intervals, processed_at)
        by_product = {candle.product_id: candle for candle in candles}
        before = len(self._fills)
        processed_groups: set[OcoGroupId] = set()
        for order in self.orders:
            current = self._orders[order.order_id]
            if current.status not in (OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED):
                continue
            candle = by_product.get(current.product_id)
            if candle is None or current.activated_at > candle.open_time:
                continue
            if current.oco_group_id is None:
                candidate = self._candidate(current, candle)
                if candidate is not None:
                    self._execute(candidate)
                continue
            if current.oco_group_id in processed_groups:
                continue
            processed_groups.add(current.oco_group_id)
            peers = tuple(
                value
                for value in self.orders
                if value.oco_group_id == current.oco_group_id
                and value.status in (OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED)
            )
            if len(peers) != 2:
                raise BrokerStateError("active OCO group must contain exactly two peers")
            candidates = tuple(
                candidate
                for peer in peers
                if (candidate := self._candidate(peer, candle)) is not None
            )
            if not candidates:
                continue
            chosen = candidates[0]
            ambiguous = len(candidates) == 2
            if ambiguous:
                reverse = chosen.order.side is Side.BUY
                chosen = sorted(
                    candidates,
                    key=lambda item: (
                        (item.fill_price, -item.order.order_id.value)
                        if reverse
                        else (item.fill_price, item.order.order_id.value)
                    ),
                    reverse=reverse,
                )[0]
                chosen = replace(
                    chosen,
                    resolution=ExecutionResolution.AMBIGUOUS_CONSERVATIVE,
                )
            self._execute(chosen, ambiguity=ambiguous)
            sibling = next(peer for peer in peers if peer.order_id != chosen.order.order_id)
            self.cancel(sibling.order_id, processed_at, CancellationReason.OCO_PEER_FILLED)
        return tuple(self._fills[before:])

    def _execute(self, candidate: _Candidate, *, ambiguity: bool = False) -> Fill:
        current = self._orders[candidate.order.order_id]
        quantity = current.remaining_base_quantity
        updated = current.apply_fill(quantity)
        fill_id = FillId(self._next_fill_id)
        self._next_fill_id += 1
        fee_amount = _multiply_ratio(
            _exact_multiply(candidate.fill_price, quantity), self.spec.fee_bps, 10_000
        )
        slippage = _exact_absolute_difference(candidate.fill_price, candidate.reference_price)
        fill = Fill(
            fill_id=fill_id,
            order_id=current.order_id,
            product_id=current.product_id,
            side=current.side,
            base_quantity=quantity,
            reference_price=candidate.reference_price,
            fill_price=candidate.fill_price,
            fee_asset=current.quote_currency,
            fee_amount=fee_amount,
            fee_bps=self.spec.fee_bps,
            slippage_per_base=slippage,
            execution_source=ExecutionSource.SIMULATED_ONE_MINUTE_CANDLE,
            execution_model_version=EXECUTION_MODEL_VERSION,
            execution_spec_fingerprint=self.spec.fingerprint,
            resolution=candidate.resolution,
            ambiguity=ambiguity,
            gap=candidate.gap,
            activated_at=current.activated_at,
            market_interval_open=candidate.candle.open_time,
            market_interval_close=candidate.candle.close_time,
            executed_at=candidate.executed_at,
            product_spec_fingerprint=current.product_spec_fingerprint,
        )
        self._orders[current.order_id] = updated
        self._fills.append(fill)
        lifecycle_kind = (
            ExecutionEventKind.ORDER_FILLED
            if updated.status is OrderStatus.FILLED
            else ExecutionEventKind.ORDER_PARTIALLY_FILLED
        )
        self._emit(lifecycle_kind, fill.executed_at, order_id=current.order_id)
        self._emit(
            ExecutionEventKind.FILL_CREATED,
            fill.executed_at,
            order_id=current.order_id,
            fill_id=fill_id,
            details=(
                ("quantity", decimal_to_text(quantity)),
                ("fill_price", decimal_to_text(fill.fill_price)),
                ("resolution", fill.resolution.value),
            ),
        )
        return fill

    def _candidate(self, order: Order, candle: Candle) -> _Candidate | None:
        if order.order_type is OrderType.MARKET:
            reference = candle.open
            return self._priced_candidate(
                order,
                candle,
                reference,
                self._slipped(reference, order.side),
                ExecutionResolution.EXACT_NEXT_OPEN,
                False,
                candle.open_time,
            )
        if order.order_type is OrderType.LIMIT:
            if order.limit_price is None:
                raise BrokerStateError("limit order lacks limit price")
            limit = order.limit_price
            if order.side is Side.BUY:
                if candle.open <= limit:
                    return self._priced_candidate(
                        order,
                        candle,
                        candle.open,
                        candle.open,
                        ExecutionResolution.GAP
                        if candle.open < limit
                        else ExecutionResolution.PRICE_CROSSED,
                        candle.open < limit,
                        candle.open_time,
                    )
                touched = candle.low <= limit
            else:
                if candle.open >= limit:
                    return self._priced_candidate(
                        order,
                        candle,
                        candle.open,
                        candle.open,
                        ExecutionResolution.GAP
                        if candle.open > limit
                        else ExecutionResolution.PRICE_CROSSED,
                        candle.open > limit,
                        candle.open_time,
                    )
                touched = candle.high >= limit
            if touched:
                return self._priced_candidate(
                    order,
                    candle,
                    limit,
                    limit,
                    ExecutionResolution.PRICE_CROSSED,
                    False,
                    candle.close_time,
                )
            return None
        if order.stop_price is None:
            raise BrokerStateError("stop order lacks stop price")
        stop = order.stop_price
        if order.side is Side.BUY:
            if candle.open >= stop:
                reference, gap, executed_at = candle.open, candle.open > stop, candle.open_time
            elif candle.high >= stop:
                reference, gap, executed_at = stop, False, candle.close_time
            else:
                return None
        else:
            if candle.open <= stop:
                reference, gap, executed_at = candle.open, candle.open < stop, candle.open_time
            elif candle.low <= stop:
                reference, gap, executed_at = stop, False, candle.close_time
            else:
                return None
        return self._priced_candidate(
            order,
            candle,
            reference,
            self._slipped(reference, order.side),
            ExecutionResolution.GAP if gap else ExecutionResolution.PRICE_CROSSED,
            gap,
            executed_at,
        )

    @staticmethod
    def _priced_candidate(
        order: Order,
        candle: Candle,
        reference: Decimal,
        fill_price: Decimal,
        resolution: ExecutionResolution,
        gap: bool,
        executed_at: UtcTimestamp,
    ) -> _Candidate:
        return _Candidate(order, candle, reference, fill_price, resolution, gap, executed_at)

    def _slipped(self, reference: Decimal, side: Side) -> Decimal:
        factor = (
            10_000 + self.spec.slippage_bps if side is Side.BUY else 10_000 - self.spec.slippage_bps
        )
        return _multiply_ratio(reference, factor, 10_000)

    @staticmethod
    def _validate_oco_requests(
        first: NormalizedOrderRequest, second: NormalizedOrderRequest
    ) -> None:
        if not isinstance(first, NormalizedOrderRequest) or not isinstance(
            second, NormalizedOrderRequest
        ):
            raise BrokerStateError("OCO activation requires normalized requests")
        types = {first.order_type, second.order_type}
        if (
            first.product_id != second.product_id
            or first.side is not second.side
            or first.normalized_base_quantity != second.normalized_base_quantity
            or types != {OrderType.LIMIT, OrderType.STOP_MARKET}
        ):
            raise BrokerStateError("invalid OCO peer requests")

    @staticmethod
    def _validate_activation(request: NormalizedOrderRequest, activated_at: UtcTimestamp) -> None:
        if not isinstance(request, NormalizedOrderRequest) or not isinstance(
            activated_at, UtcTimestamp
        ):
            raise BrokerStateError("activation requires normalized request and timestamp")
        try:
            verify_normalized_order_request(request)
        except OrderNormalizationError as error:
            raise BrokerStateError("normalized request evidence verification failed") from error
        if activated_at < request.created_at:
            raise BrokerStateError("activation cannot precede intent creation")

    @staticmethod
    def _validate_intervals(
        intervals: tuple[Candle, ...], processed_at: UtcTimestamp
    ) -> tuple[Candle, ...]:
        if not isinstance(intervals, tuple) or not isinstance(processed_at, UtcTimestamp):
            raise BrokerStateError("market activity requires tuple intervals and timestamp")
        products: set[ProductId] = set()
        for candle in intervals:
            if (
                not isinstance(candle, Candle)
                or candle.timeframe is not Timeframe.ONE_MINUTE
                or candle.close_time != processed_at
            ):
                raise BrokerStateError(
                    "execution candle must be one minute and close when processed"
                )
            if candle.product_id in products:
                raise BrokerStateError("duplicate execution candle product")
            products.add(candle.product_id)
        return tuple(sorted(intervals, key=lambda candle: candle.product_id.value))

    def _allocate_order_id(self) -> OrderId:
        value = OrderId(self._next_order_id)
        self._next_order_id += 1
        return value

    def _emit(
        self,
        kind: ExecutionEventKind,
        timestamp: UtcTimestamp,
        *,
        order_id: OrderId | None = None,
        fill_id: FillId | None = None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._events.append(
            ExecutionEvent(
                len(self._events) + 1,
                timestamp,
                kind,
                order_id,
                fill_id,
                tuple(sorted(details)),
            )
        )

    @staticmethod
    def _event_content(event: ExecutionEvent) -> dict[str, object]:
        return {
            "sequence": event.sequence,
            "timestamp": str(event.timestamp),
            "kind": event.kind.value,
            "order_id": None if event.order_id is None else event.order_id.value,
            "fill_id": None if event.fill_id is None else event.fill_id.value,
            "details": list(event.details),
        }

    @staticmethod
    def _order_content(order: Order) -> dict[str, object]:
        return {
            "order_id": order.order_id.value,
            "product_id": order.product_id.value,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "requested_quantity": decimal_to_text(order.requested_base_quantity.value),
            "activated_quantity": decimal_to_text(order.activated_base_quantity.value),
            "filled_quantity": decimal_to_text(order.filled_base_quantity),
            "remaining_quantity": decimal_to_text(order.remaining_base_quantity),
            "limit_price": None
            if order.limit_price is None
            else decimal_to_text(order.limit_price),
            "stop_price": None if order.stop_price is None else decimal_to_text(order.stop_price),
            "created_at": str(order.created_at),
            "activated_at": str(order.activated_at),
            "status": order.status.value,
            "product_spec_fingerprint": order.product_spec_fingerprint,
            "oco_group_id": None if order.oco_group_id is None else order.oco_group_id.value,
            "cancelled_at": None if order.cancelled_at is None else str(order.cancelled_at),
            "cancellation_reason": None
            if order.cancellation_reason is None
            else order.cancellation_reason.value,
        }

    @staticmethod
    def _fill_content(fill: Fill) -> dict[str, object]:
        return {
            "fill_id": fill.fill_id.value,
            "order_id": fill.order_id.value,
            "product_id": fill.product_id.value,
            "side": fill.side.value,
            "base_quantity": decimal_to_text(fill.base_quantity),
            "reference_price": decimal_to_text(fill.reference_price),
            "fill_price": decimal_to_text(fill.fill_price),
            "fee_asset": fill.fee_asset.value,
            "fee_amount": decimal_to_text(fill.fee_amount),
            "fee_bps": fill.fee_bps,
            "slippage_per_base": decimal_to_text(fill.slippage_per_base),
            "execution_source": fill.execution_source.value,
            "execution_model_version": fill.execution_model_version,
            "execution_spec_fingerprint": fill.execution_spec_fingerprint,
            "resolution": fill.resolution.value,
            "ambiguity": fill.ambiguity,
            "gap": fill.gap,
            "activated_at": str(fill.activated_at),
            "market_interval_open": str(fill.market_interval_open),
            "market_interval_close": str(fill.market_interval_close),
            "executed_at": str(fill.executed_at),
            "product_spec_fingerprint": fill.product_spec_fingerprint,
        }


def _exact_multiply(left: Decimal, right: Decimal) -> Decimal:
    return _fraction_to_decimal(Fraction(left) * Fraction(right))


def _multiply_ratio(value: Decimal, numerator: int, denominator: int) -> Decimal:
    return _fraction_to_decimal(Fraction(value) * numerator / denominator)


def _exact_absolute_difference(left: Decimal, right: Decimal) -> Decimal:
    return _fraction_to_decimal(abs(Fraction(left) - Fraction(right)))


def _fraction_to_decimal(value: Fraction) -> Decimal:
    numerator, denominator = value.numerator, value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise BrokerStateError("execution arithmetic did not produce a finite decimal")
    scale = max(twos, fives)
    coefficient = numerator * (2 ** (scale - twos)) * (5 ** (scale - fives))
    sign = 1 if coefficient < 0 else 0
    digits = tuple(int(char) for char in str(abs(coefficient)))
    return Decimal((sign, digits, -scale))
