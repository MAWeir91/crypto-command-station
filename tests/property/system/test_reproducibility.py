import tempfile
from dataclasses import replace
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from command_station.accounting import InitialHolding
from command_station.domain import ProductId, Timeframe
from command_station.strategy import (
    BarSubscription,
    IndicatorKind,
    IndicatorSpec,
    IntParam,
    StrategyDefinition,
)
from tests.research_fixtures import BTC, NoTrade, setup
from tests.system_fixtures import bundle


class Permuted(NoTrade):
    def __init__(self, reverse: bool = False):
        subscriptions = (
            BarSubscription(BTC, Timeframe.ONE_MINUTE),
            BarSubscription(BTC, Timeframe.FIVE_MINUTES, True),
            BarSubscription(ProductId("ETH-USD"), Timeframe.FIVE_MINUTES),
        )
        indicators = (
            IndicatorSpec("btc", BTC, Timeframe.FIVE_MINUTES, IndicatorKind.SMA, 1),
            IndicatorSpec(
                "eth", ProductId("ETH-USD"), Timeframe.FIVE_MINUTES, IndicatorKind.SMA, 1
            ),
        )
        self.definition = StrategyDefinition(
            "research",
            tuple(reversed(subscriptions)) if reverse else subscriptions,
            parameters=(IntParam("alpha", 1), IntParam("beta", 2)),
            indicators=tuple(reversed(indicators)) if reverse else indicators,
        )


@given(reverse=st.booleans(), seed=st.integers(-5, 5))
@settings(max_examples=6, deadline=None)
def test_generated_full_service_declaration_and_input_permutations(
    reverse: bool, seed: int
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first, a = setup(root / "a", Permuted, minutes=15, start=5, end=10)
        second, b = setup(
            root / "b", lambda: Permuted(reverse), minutes=15, start=5, end=10, reverse=reverse
        )
        holdings = (
            InitialHolding(BTC, "0.001", "80"),
            InitialHolding(ProductId("ETH-USD"), "0.002", "80"),
        )
        a = replace(
            a,
            parameters=(("alpha", 1), ("beta", 2)),
            random_seed=seed,
            account=replace(a.account, initial_holdings=holdings),
        )
        b = replace(
            b,
            parameters=(("beta", 2), ("alpha", 1)),
            random_seed=seed,
            datasets=tuple(reversed(b.datasets)),
            account=replace(
                b.account,
                initial_holdings=tuple(reversed(holdings)),
                product_specs=tuple(reversed(b.account.product_specs)),
            ),
        )
        assert a == b
        x, y = first.run(a), second.run(b)
        assert x == y
        assert bundle(first, x) == bundle(second, y)
