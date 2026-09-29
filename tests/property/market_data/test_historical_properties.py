from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from command_station.domain import ProductId, UtcTimestamp
from command_station.market_data.historical import (
    HistoricalCandleImportSpec,
    plan_coinbase_candle_requests,
)


@given(st.integers(min_value=1, max_value=2_000))
def test_plans_are_bounded_cover_every_minute_and_overlap(minutes: int) -> None:
    start = UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC))
    end = UtcTimestamp(start.value + timedelta(minutes=minutes))
    spec = HistoricalCandleImportSpec(
        ProductId("BTC-USD"), start, end, UtcTimestamp(end.value + timedelta(seconds=1))
    )
    plan = plan_coinbase_candle_requests(spec)
    assert all(1 <= request.limit <= 350 for request in plan)
    assert all(
        left.request_end.value - timedelta(minutes=1) == right.request_start.value
        for left, right in zip(plan, plan[1:], strict=False)
    )
    covered: set[int] = set()
    for request in plan:
        covered.update(
            range(
                int((request.request_start.value - start.value).total_seconds() // 60),
                int((request.request_end.value - start.value).total_seconds() // 60),
            )
        )
    assert covered == set(range(minutes))
