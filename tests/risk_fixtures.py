from command_station.accounting import SpotAccountingEngine
from command_station.execution import SimulatedBroker
from command_station.market_data.replay import HistoricalReplayFeed
from command_station.risk import RiskEngine, RiskPolicy, RiskStateSnapshot
from command_station.runtime import ReferenceTradingRuntime, SimulatedClock
from tests.accounting_fixtures import account
from tests.execution_fixtures import timestamp
from tests.runtime_fixtures import canonical


def state(
    engine: SpotAccountingEngine, broker: SimulatedBroker | None = None, minute: int = 0
) -> RiskStateSnapshot:
    return RiskStateSnapshot(
        timestamp(minute),
        engine.spec,
        engine.account_view,
        engine.positions,
        engine.reservations,
        broker.orders if broker else (),
        engine.portfolio_snapshot,
        engine.execution_spec,
    )


def runtime(
    policy: RiskPolicy | None = None, *, holding: str | None = None, cash: str = "1000"
) -> ReferenceTradingRuntime:
    feed = HistoricalReplayFeed((canonical("BTC-USD", minutes=4),))
    engine = account(cash=cash, holding=holding)
    return ReferenceTradingRuntime(
        clock=SimulatedClock(feed.start),
        market_feed=feed,
        broker=SimulatedBroker(engine.execution_spec),
        accounting=engine,
        risk=RiskEngine(policy),
    )
