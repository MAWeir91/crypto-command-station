"""One run's strategy metadata, lifecycle, schema state, indicators and audit."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from command_station.domain import Candle, UtcTimestamp
from command_station.execution import Fill, FillId, OrderId
from command_station.strategy._logical import StrategyContractError, fingerprint
from command_station.strategy.base import Strategy, StrategyDefinition
from command_station.strategy.commands import (
    StrategyActionResult,
    StrategyCommandId,
    StrategyOrderCommand,
)
from command_station.strategy.context import StrategyContext
from command_station.strategy.indicators import IndicatorEngine
from command_station.strategy.parameters import StrategyParameters
from command_station.strategy.state import StateValue, StrategyState


class StrategyAuditKind(StrEnum):
    STRATEGY_STARTED = "STRATEGY_STARTED"
    FILL_CALLBACK = "FILL_CALLBACK"
    BAR_CALLBACK = "BAR_CALLBACK"
    COMMAND_PROCESSED = "COMMAND_PROCESSED"
    STRATEGY_STOPPED = "STRATEGY_STOPPED"
    CALLBACK_FAILED = "CALLBACK_FAILED"


@dataclass(frozen=True, slots=True)
class StrategyAuditEvent:
    sequence: int
    timestamp: UtcTimestamp
    kind: StrategyAuditKind
    state_fingerprint: str
    callback: str | None = None
    bar: Candle | None = None
    fill_id: FillId | None = None
    command_id: StrategyCommandId | None = None


class StrategyRunner:
    def __init__(
        self,
        strategy: Strategy,
        *,
        trading_start: UtcTimestamp,
        parameters: Mapping[str, object] | None = None,
        initial_state: Mapping[str, StateValue] | None = None,
    ):
        if (
            not isinstance(strategy, Strategy)
            or not isinstance(strategy.definition, StrategyDefinition)
            or not isinstance(trading_start, UtcTimestamp)
        ):
            raise StrategyContractError("runner requires Strategy/definition and UTC trading start")
        self._strategy = strategy
        self.definition = strategy.definition
        self.trading_start = trading_start
        self.parameters = StrategyParameters(self.definition.parameters, parameters)
        self.state = StrategyState(self.definition.state_schema, initial_state)
        self._initial_state = self.state.snapshot
        self.indicators = IndicatorEngine(self.definition.indicators)
        self._audit: list[StrategyAuditEvent] = []
        self._commands: list[StrategyOrderCommand] = []
        self._results: list[StrategyActionResult] = []
        self._owned: set[OrderId] = set()
        self._next_command = 1
        self.started = self.stopped = self.failed = self._attached = False

    @property
    def audit_history(self) -> tuple[StrategyAuditEvent, ...]:
        return tuple(self._audit)

    @property
    def commands(self) -> tuple[StrategyOrderCommand, ...]:
        return tuple(self._commands)

    @property
    def action_results(self) -> tuple[StrategyActionResult, ...]:
        return tuple(self._results)

    @property
    def owned_order_ids(self) -> tuple[OrderId, ...]:
        return tuple(sorted(self._owned))

    @property
    def fingerprint(self) -> str:
        return fingerprint(
            (
                1,
                self.definition.fingerprint,
                self.parameters.fingerprint,
                self.trading_start,
                self._initial_state,
                self.audit_history,
                self.commands,
                self.action_results,
                self.state.fingerprint,
                self.indicators.view,
                self.started,
                self.stopped,
                self.failed,
            )
        )

    def _attach(self) -> None:
        if (
            self._attached
            or self.started
            or self.stopped
            or self.failed
            or self._audit
            or self._commands
            or self._results
            or self._next_command != 1
            or self.state.snapshot != self._initial_state
            or any(reading.source_bar_count for reading in self.indicators.view.readings)
        ):
            raise StrategyContractError("runtime requires a fresh unattached strategy runner")
        self._attached = True

    def _invoke(
        self,
        callback: str,
        ctx: StrategyContext,
        *,
        bar: Candle | None = None,
        fill: Fill | None = None,
    ) -> tuple[StrategyOrderCommand, ...]:
        if self.failed or self.stopped or not self._attached:
            raise StrategyContractError("strategy lifecycle cannot continue")
        if callback == "on_start":
            if self.started:
                raise StrategyContractError("strategy already started")
        elif not self.started:
            raise StrategyContractError("strategy has not started")
        try:
            if callback == "on_start":
                self._strategy.on_start(ctx)
            elif callback == "on_fill":
                assert fill is not None
                self._strategy.on_fill(ctx, fill)
            elif callback == "on_bar":
                assert bar is not None
                self._strategy.on_bar(ctx, bar)
            elif callback == "on_stop":
                self._strategy.on_stop(ctx)
            else:
                raise StrategyContractError("unsupported callback")
        except Exception:
            ctx.orders._seal()
            self.failed = True
            self._emit(
                ctx.clock.now,
                StrategyAuditKind.CALLBACK_FAILED,
                callback=callback,
                bar=bar,
                fill_id=fill.fill_id if fill else None,
            )
            raise
        commands = ctx.orders._seal()
        self._next_command += len(commands)
        self._commands.extend(commands)
        if callback == "on_start":
            self.started = True
        if callback == "on_stop":
            self.stopped = True
        kinds = {
            "on_start": StrategyAuditKind.STRATEGY_STARTED,
            "on_fill": StrategyAuditKind.FILL_CALLBACK,
            "on_bar": StrategyAuditKind.BAR_CALLBACK,
            "on_stop": StrategyAuditKind.STRATEGY_STOPPED,
        }
        self._emit(
            ctx.clock.now,
            kinds[callback],
            callback=callback,
            bar=bar,
            fill_id=fill.fill_id if fill else None,
        )
        return commands

    def _record_result(self, result: StrategyActionResult) -> None:
        self._results.append(result)
        self._owned.update(result.order_ids)
        self._emit(
            result.timestamp, StrategyAuditKind.COMMAND_PROCESSED, command_id=result.command_id
        )

    def _emit(
        self,
        timestamp: UtcTimestamp,
        kind: StrategyAuditKind,
        *,
        callback: str | None = None,
        bar: Candle | None = None,
        fill_id: FillId | None = None,
        command_id: StrategyCommandId | None = None,
    ) -> None:
        self._audit.append(
            StrategyAuditEvent(
                len(self._audit) + 1,
                timestamp,
                kind,
                self.state.fingerprint,
                callback,
                bar,
                fill_id,
                command_id,
            )
        )
