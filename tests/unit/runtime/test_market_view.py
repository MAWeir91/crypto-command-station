import inspect

import pytest

from command_station.domain import ProductId, Timeframe
from command_station.runtime.market import MarketPublicationError, MarketView, _MarketState
from tests.runtime_fixtures import canonical


def test_market_view_is_bounded_and_publication_failure_is_atomic() -> None:
    source = canonical("BTC-USD", minutes=2)
    state = _MarketState.create()
    first, second = source.candles
    state.publish(first.close_time, (first,))
    view = state.snapshot()

    with pytest.raises(ValueError):
        view.recent_bars(ProductId("BTC-USD"), Timeframe.ONE_MINUTE, 0)
    with pytest.raises(MarketPublicationError):
        state.publish(second.close_time, (second, second))

    assert view.visible_through == first.close_time
    assert view.recent_bars(ProductId("BTC-USD"), Timeframe.ONE_MINUTE, 3) == (first,)
    assert view.latest_price(ProductId("BTC-USD")) == first.close


def test_market_view_does_not_retain_state_or_transitive_callable_access() -> None:
    state = _MarketState.create()
    view = state.snapshot()

    assert not hasattr(view, "_state")
    assert not any(callable(value) for value in (view.visible_through, view._streams))
    assert not inspect.getclosurevars(MarketView.latest_bar).nonlocals
    with pytest.raises((AttributeError, TypeError)):
        setattr(view, "_state", state)  # noqa: B010 - adversarial API-boundary regression
    with pytest.raises((AttributeError, TypeError)):
        setattr(view, "visible_through", canonical("BTC-USD", minutes=1).end)  # noqa: B010
    assert view.visible_through is None


def test_market_view_is_a_snapshot_not_a_live_mutable_state_handle() -> None:
    source = canonical("BTC-USD", minutes=1)
    state = _MarketState.create()
    before = state.snapshot()
    state.publish(source.candles[0].close_time, (source.candles[0],))
    after = state.snapshot()

    assert before.visible_through is None
    assert before.latest_bar(ProductId("BTC-USD"), Timeframe.ONE_MINUTE) is None
    assert after.visible_through == source.candles[0].close_time


def test_market_view_rejects_out_of_order_stream_publication() -> None:
    source = canonical("BTC-USD", minutes=2)
    state = _MarketState.create()
    state.publish(source.candles[1].close_time, (source.candles[1],))
    with pytest.raises(MarketPublicationError):
        state.publish(source.candles[1].close_time, (source.candles[0],))
