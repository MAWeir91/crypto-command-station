from dataclasses import replace
from decimal import Decimal

import pytest

from command_station.domain import Candle, ProductId, Side
from command_station.execution import BaseQuantity, Fill, OrderId
from command_station.runtime import RuntimeEngineError, RuntimeLifecycle
from command_station.strategy import StateField, StateType, Strategy, StrategyContext
from tests.accounting_fixtures import request
from tests.golden.strategy.test_scenarios import Buyer
from tests.strategy_fixtures import BTC, compose, definition


class Canceller(Strategy):
    definition = definition()

    def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
        if not ctx.orders.orders:
            ctx.orders.limit(BTC, Side.BUY, BaseQuantity("1"), "90")
        elif not ctx.orders.results[-1].cancelled_orders:
            ctx.orders.cancel(ctx.orders.orders[0].order_id)


def test_cancel_releases_reservation_and_manual_mutation_blocked() -> None:
    runtime = compose(Canceller(), minutes=2)
    with pytest.raises(RuntimeEngineError):
        runtime.activate_order(request(), max_quote_reservation=Decimal("200"))
    runtime.step()
    assert runtime.accounting is not None
    assert runtime.accounting.reservations[0].remaining_amount == Decimal("90.9")
    with pytest.raises(RuntimeEngineError):
        runtime.cancel_order(runtime.broker.orders[0].order_id)
    runtime.run()
    assert runtime.accounting.reservations[0].remaining_amount == 0
    assert not runtime.broker.fills


def test_fresh_runs_strategy_and_financial_fingerprints() -> None:
    first = compose(Buyer(), minutes=4)
    second = compose(Buyer(), minutes=4, reverse=True)
    a, b = first.run(), second.run()
    assert a.strategy_fingerprint == b.strategy_fingerprint
    assert a.execution_fingerprint == b.execution_fingerprint
    assert a.accounting_fingerprint == b.accounting_fingerprint
    assert a.risk_fingerprint == b.risk_fingerprint
    assert a.final_positions[0].actual_quantity == Decimal("1")
    assert a.final_portfolio_snapshot is not None
    assert a.final_portfolio_snapshot.cash_total == Decimal("899")


@pytest.mark.parametrize("failure", ["callback", "product", "normalization", "cancel"])
def test_bad_batch_does_not_activate_earlier_valid_command(failure: str) -> None:
    class Broken(Strategy):
        definition = definition()

        def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
            ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")
            if failure == "callback":
                raise ValueError("callback failed")
            if failure == "product":
                ctx.orders.limit(ProductId("ETH-USD"), Side.BUY, BaseQuantity("1"), "90")
            if failure == "normalization":
                ctx.orders.limit(BTC, Side.BUY, BaseQuantity("0.0001"), "90")
            if failure == "cancel":
                ctx.orders.cancel(OrderId(9))

    runtime = compose(Broken(), minutes=4)
    with pytest.raises(RuntimeEngineError):
        runtime.run()
    assert runtime.lifecycle is RuntimeLifecycle.FAILED
    assert not runtime.broker.orders
    assert runtime.accounting is not None and not runtime.accounting.reservations
    assert runtime.risk is not None and not runtime.risk.decisions
    with pytest.raises(RuntimeEngineError):
        runtime.step()


@pytest.mark.parametrize("callback", ["fill", "stop"])
def test_forbidden_callback_command_fails_and_preserves_accounted_truth(callback: str) -> None:
    class Forbidden(Buyer):
        def on_fill(self, ctx: StrategyContext, fill: Fill) -> None:
            if callback == "fill":
                ctx.orders.cancel(fill.order_id)

        def on_stop(self, ctx: StrategyContext) -> None:
            if callback == "stop":
                ctx.orders.limit(BTC, Side.BUY, BaseQuantity("1"), "90")

    runtime = compose(Forbidden(), minutes=4)
    with pytest.raises(RuntimeEngineError):
        runtime.run()
    assert runtime.lifecycle is RuntimeLifecycle.FAILED
    assert runtime.accounting is not None and runtime.accounting.positions[0].actual_quantity == 1
    assert len(runtime.broker.fills) == 1


def test_start_commands_visible_to_first_bar_and_ids_are_sequential() -> None:
    class Starter(Strategy):
        definition = definition()

        def on_start(self, ctx: StrategyContext) -> None:
            ctx.orders.limit(BTC, Side.BUY, BaseQuantity("1"), "90")
            assert not ctx.orders.orders and not ctx.orders.results

        def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
            assert len(ctx.orders.orders) == 1 and len(ctx.orders.results) == 1
            ctx.orders.cancel(ctx.orders.orders[0].order_id)

    runtime = compose(Starter(), minutes=1)
    runtime.run()
    runner = runtime.strategy_runner
    assert runner is not None
    assert [result.command_id.value for result in runner.action_results] == [1, 2]
    assert (
        runtime.accounting is not None and runtime.accounting.reservations[0].remaining_amount == 0
    )


def test_two_commands_sequential_risk_current_available_cash() -> None:
    class Two(Strategy):
        definition = definition()

        def on_start(self, ctx: StrategyContext) -> None:
            ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")
            ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")

    runtime = compose(Two(), minutes=1, cash="300")
    runtime.run()
    runner = runtime.strategy_runner
    assert runner is not None
    assert [result.status.value for result in runner.action_results] == ["ACTIVATED", "REJECTED"]
    assert len(runtime.broker.orders) == 1


def test_two_fill_callbacks_sorted_and_state_visible_to_next_decision() -> None:
    class TwoFill(Strategy):
        definition = replace(
            definition(), state_schema=(StateField("sequence", StateType.STR, ""),)
        )

        def on_start(self, ctx: StrategyContext) -> None:
            for _ in range(2):
                ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")

        def on_fill(self, ctx: StrategyContext, fill: Fill) -> None:
            prior = ctx.state.get("sequence")
            assert isinstance(prior, str)
            ctx.state.set("sequence", prior + str(fill.fill_id.value))

        def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
            if ctx.clock.now.value.minute == 2:
                assert ctx.state.get("sequence") == "12"
                assert ctx.positions[0].actual_quantity == 2

    runtime = compose(TwoFill(), minutes=3)
    runtime.run()
    runner = runtime.strategy_runner
    assert runner is not None
    assert [event.fill_id.value for event in runner.audit_history if event.fill_id] == [1, 2]


@pytest.mark.parametrize("sell", [False, True])
def test_oco_shared_reservation_and_group_cancellation(sell: bool) -> None:
    class Oco(Strategy):
        definition = definition()

        def on_bar(self, ctx: StrategyContext, bar: Candle) -> None:
            minute = ctx.clock.now.value.minute
            if sell and minute == 1:
                ctx.orders.market(BTC, Side.BUY, BaseQuantity("1"), max_quote_reservation="200")
            elif minute == (2 if sell else 1):
                ctx.orders.oco_limit_stop(
                    BTC,
                    Side.SELL if sell else Side.BUY,
                    BaseQuantity("1"),
                    "110" if sell else "90",
                    "90" if sell else "110",
                    max_quote_reservation=None if sell else "200",
                )
            elif minute == (3 if sell else 2):
                group = ctx.orders.orders[-1].oco_group_id
                assert group is not None
                ctx.orders.cancel_oco(group)

    runtime = compose(Oco(), minutes=3 if sell else 2)
    runtime.run()
    assert runtime.accounting is not None
    reservation = runtime.accounting.reservations[-1]
    assert len(reservation.order_ids) == 2
    assert reservation.original_amount == (Decimal("1") if sell else Decimal("200"))
    assert reservation.remaining_amount == 0
    assert all(order.status.value == "CANCELLED" for order in runtime.broker.orders[-2:])
