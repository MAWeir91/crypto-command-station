import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from command_station.domain import ProductId, UtcTimestamp
from command_station.market_data.historical import (
    CoinbaseCandleRequest,
    HistoricalCandleConflictError,
    HistoricalCandleImporter,
    HistoricalCandleImportError,
    HistoricalCandleImportSpec,
    HistoricalCandlePayloadError,
    normalize_coinbase_candle_page,
    plan_coinbase_candle_requests,
)
from command_station.market_data.raw_archive import (
    LocalRawCandleArchive,
    RawArchiveConflictError,
    RawArchiveCorruptionError,
)


def timestamp(minutes: int, seconds: int = 0) -> UtcTimestamp:
    return UtcTimestamp(
        datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes, seconds=seconds)
    )


def spec(minutes: int) -> HistoricalCandleImportSpec:
    return HistoricalCandleImportSpec(
        ProductId("BTC-USD"), timestamp(0), timestamp(minutes), timestamp(minutes, 30)
    )


def candle(minutes: int, close: str = "1") -> dict[str, object]:
    return {
        "start": str(1704067200 + minutes * 60),
        "low": "1",
        "high": close,
        "open": "1",
        "close": close,
        "volume": "0",
        "future_field": {"kept": True},
    }


def test_planner_caps_covers_and_overlaps() -> None:
    requests = plan_coinbase_candle_requests(spec(700))
    assert [request.limit for request in requests] == [350, 350, 2]
    assert requests[1].request_start == timestamp(349)
    assert requests[2].request_start == timestamp(698)
    covered = {
        start
        for request in requests
        for start in range(
            int((request.request_start.value - timestamp(0).value).total_seconds() // 60),
            int((request.request_end.value - timestamp(0).value).total_seconds() // 60),
        )
    }
    assert covered == set(range(700))


def test_planner_clamps_near_datetime_max_without_overflow() -> None:
    start = UtcTimestamp(
        datetime.max.replace(tzinfo=UTC, second=0, microsecond=0) - timedelta(minutes=2)
    )
    end = UtcTimestamp(start.value + timedelta(minutes=2))
    result = plan_coinbase_candle_requests(
        HistoricalCandleImportSpec(ProductId("BTC-USD"), start, end, end)
    )
    assert len(result) == 1 and result[0].request_end == end


def test_completed_boundary_and_normalization_errors() -> None:
    with pytest.raises(HistoricalCandleImportError):
        HistoricalCandleImportSpec(
            ProductId("BTC-USD"), timestamp(0), timestamp(2), timestamp(1, 59)
        )
    request = plan_coinbase_candle_requests(spec(1))[0]
    assert normalize_coinbase_candle_page({"candles": [candle(0)]}, request)[
        0
    ].close_time == timestamp(1)
    with pytest.raises(HistoricalCandlePayloadError):
        normalize_coinbase_candle_page({"candles": [{**candle(0), "start": " 1"}]}, request)
    with pytest.raises(HistoricalCandlePayloadError):
        normalize_coinbase_candle_page({"candles": [{**candle(0), "open": 1.0}]}, request)
    assert normalize_coinbase_candle_page(
        {"candles": [candle(0), candle(0)]}, request
    ) == normalize_coinbase_candle_page({"candles": [candle(0)]}, request)


def test_normalization_is_order_independent_and_import_excludes_overall_end(tmp_path: Path) -> None:
    request = plan_coinbase_candle_requests(spec(1))[0]
    reverse = normalize_coinbase_candle_page({"candles": [candle(1), candle(0)]}, request)
    assert [item.open_time for item in reverse] == [timestamp(0), timestamp(1)]
    importer = HistoricalCandleImporter(
        FakeClient({str(request.request_start): {"candles": [candle(1), candle(0)]}}),
        LocalRawCandleArchive(tmp_path.resolve()),
    )
    result = importer.import_candles(spec(1))
    assert tuple(item.open_time for item in result.candles) == (timestamp(0),)


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


def test_resume_overlap_dedup_missing_and_conflict(tmp_path: Path) -> None:
    import_spec = spec(351)
    requests = plan_coinbase_candle_requests(import_spec)
    first, second = str(requests[0].request_start), str(requests[1].request_start)
    page_one = {"candles": [candle(0), candle(349)]}
    page_two = {"candles": [candle(349), candle(350)]}
    archive = LocalRawCandleArchive(tmp_path.resolve())
    client = FakeClient({first: page_one, second: RuntimeError("offline")})
    importer = HistoricalCandleImporter(client, archive)
    with pytest.raises(RuntimeError):
        importer.import_candles(import_spec)
    client.pages[second] = page_two
    result = importer.import_candles(import_spec)
    assert result.fetched_page_count == 1 and result.reused_page_count == 1
    assert client.calls.count(first) == 1
    assert len(result.missing_open_times) == 348
    assert len(result.candles) == 3
    conflict_archive = LocalRawCandleArchive((tmp_path / "conflict").resolve())
    conflict = HistoricalCandleImporter(
        FakeClient({first: page_one, second: {"candles": [candle(349, "2")]}}), conflict_archive
    )
    with pytest.raises(HistoricalCandleConflictError):
        conflict.import_candles(import_spec)
    assert (
        conflict_archive.load(requests[0]) is not None
        and conflict_archive.load(requests[1]) is not None
    )


def test_raw_archive_integrity_path_safety_and_conflicting_evidence(tmp_path: Path) -> None:
    request = plan_coinbase_candle_requests(spec(1))[0]
    unsafe_request = CoinbaseCandleRequest(
        ProductId("../../escape"), request.request_start, request.request_end, 1
    )
    archive = LocalRawCandleArchive(tmp_path.resolve())
    payload = {"candles": [candle(0)]}
    page = archive.store(unsafe_request, as_of=timestamp(1, 30), payload=payload)
    assert page.path.is_relative_to(tmp_path.resolve())
    assert page.payload["candles"] == [candle(0)]
    assert archive.store(unsafe_request, as_of=timestamp(1, 30), payload=payload) == page
    with pytest.raises(RawArchiveConflictError):
        archive.store(unsafe_request, as_of=timestamp(1, 30), payload={"candles": []})
    value = json.loads(page.path.read_text(encoding="utf-8"))
    value["as_of"] = "2024-01-01T00:01:31Z"
    page.path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RawArchiveCorruptionError):
        archive.load(unsafe_request)


def test_raw_archive_rejects_bad_json_schema_and_payload_hash(tmp_path: Path) -> None:
    request = plan_coinbase_candle_requests(spec(1))[0]
    archive = LocalRawCandleArchive(tmp_path.resolve())
    page = archive.store(request, as_of=timestamp(1, 30), payload={"candles": [candle(0)]})
    page.path.write_text("{bad", encoding="utf-8")
    with pytest.raises(RawArchiveCorruptionError):
        archive.load(request)
    archive = LocalRawCandleArchive((tmp_path / "schema").resolve())
    page = archive.store(request, as_of=timestamp(1, 30), payload={"candles": [candle(0)]})
    value = json.loads(page.path.read_text(encoding="utf-8"))
    value["schema_version"] = 999
    page.path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RawArchiveCorruptionError):
        archive.load(request)
    archive = LocalRawCandleArchive((tmp_path / "payload").resolve())
    page = archive.store(request, as_of=timestamp(1, 30), payload={"candles": [candle(0)]})
    value = json.loads(page.path.read_text(encoding="utf-8"))
    value["payload_sha256"] = "0" * 64
    page.path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RawArchiveCorruptionError):
        archive.load(request)
