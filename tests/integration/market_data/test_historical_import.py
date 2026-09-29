from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from command_station.domain import ProductId, UtcTimestamp
from command_station.market_data.historical import (
    CoinbaseCandleRequest,
    HistoricalCandleConflictError,
    HistoricalCandleImporter,
    HistoricalCandleImportSpec,
    plan_coinbase_candle_requests,
)
from command_station.market_data.raw_archive import LocalRawCandleArchive


def timestamp(minutes: int, seconds: int = 0) -> UtcTimestamp:
    return UtcTimestamp(
        datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes, seconds=seconds)
    )


def candle(minutes: int, close: str = "1") -> dict[str, object]:
    return {
        "start": str(1704067200 + minutes * 60),
        "low": "1",
        "high": close,
        "open": "1",
        "close": close,
        "volume": "0",
    }


class FakeClient:
    def __init__(self, pages: dict[str, object]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def fetch_page(self, request: CoinbaseCandleRequest) -> dict[str, object]:
        key = str(request.request_start)
        self.calls.append(key)
        value = self.pages[key]
        if isinstance(value, Exception):
            raise value
        return cast(dict[str, object], value)


def test_resume_after_failure_and_overlap_deduplication(tmp_path: Path) -> None:
    import_spec = HistoricalCandleImportSpec(
        ProductId("BTC-USD"), timestamp(0), timestamp(351), timestamp(351, 30)
    )
    requests = plan_coinbase_candle_requests(import_spec)
    first, second = str(requests[0].request_start), str(requests[1].request_start)
    archive = LocalRawCandleArchive(tmp_path.resolve())
    client = FakeClient(
        {
            first: {"candles": [candle(0), candle(349)]},
            second: RuntimeError("offline"),
        }
    )
    importer = HistoricalCandleImporter(client, archive)
    with pytest.raises(RuntimeError):
        importer.import_candles(import_spec)

    client.pages[second] = {"candles": [candle(349), candle(350)]}
    result = importer.import_candles(import_spec)
    assert result.fetched_page_count == 1 and result.reused_page_count == 1
    assert client.calls.count(first) == 1
    assert len(result.missing_open_times) == 348
    assert len(result.candles) == 3
    assert sum(item.open_time == timestamp(349) for item in result.candles) == 1


def test_overlap_conflict_preserves_both_raw_pages(tmp_path: Path) -> None:
    import_spec = HistoricalCandleImportSpec(
        ProductId("BTC-USD"), timestamp(0), timestamp(351), timestamp(351, 30)
    )
    requests = plan_coinbase_candle_requests(import_spec)
    first, second = str(requests[0].request_start), str(requests[1].request_start)
    archive = LocalRawCandleArchive(tmp_path.resolve())
    importer = HistoricalCandleImporter(
        FakeClient(
            {
                first: {"candles": [candle(0), candle(349)]},
                second: {"candles": [candle(349, "2")]},
            }
        ),
        archive,
    )
    with pytest.raises(HistoricalCandleConflictError):
        importer.import_candles(import_spec)
    assert archive.load(requests[0]) is not None
    assert archive.load(requests[1]) is not None
