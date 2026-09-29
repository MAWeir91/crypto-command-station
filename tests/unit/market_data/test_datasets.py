from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from command_station.domain import Candle, ProductId, Timeframe, UtcTimestamp
from command_station.market_data.datasets import (
    CanonicalCandleDataset,
    CanonicalDatasetValidationError,
    DatasetQuality,
    DatasetVersion,
    GapReason,
    GapRecord,
    SourcePageReference,
    build_canonical_dataset,
)
from command_station.market_data.historical import (
    HistoricalCandleImportResult,
    HistoricalCandleImportSpec,
)
from command_station.market_data.raw_archive import ArchivedRawPage


def instant(minute: int) -> UtcTimestamp:
    return UtcTimestamp(datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=minute))


def candle(minute: int, close: str = "1.00") -> Candle:
    return Candle(
        ProductId("BTC-USD"),
        Timeframe.ONE_MINUTE,
        instant(minute),
        instant(minute + 1),
        "1.00",
        close,
        "1.00",
        close,
        "0.000",
    )


def source() -> SourcePageReference:
    return SourcePageReference("a" * 64, "b" * 64)


def test_version_and_complete_dataset_contract() -> None:
    with pytest.raises(CanonicalDatasetValidationError):
        DatasetVersion("A" * 64)
    dataset = CanonicalCandleDataset(
        product_id=ProductId("BTC-USD"),
        start=instant(0),
        end=instant(2),
        as_of=instant(3),
        candles=(candle(1), candle(0)),
        gaps=(),
        source_pages=(source(),),
    )
    assert dataset.quality is DatasetQuality.VALID
    assert tuple(value.open_time for value in dataset.candles) == (instant(0), instant(1))
    assert len(str(dataset.version)) == 64


def test_gap_coverage_is_explicit_and_changes_identity() -> None:
    missing = CanonicalCandleDataset(
        product_id=ProductId("BTC-USD"),
        start=instant(0),
        end=instant(2),
        as_of=instant(3),
        candles=(candle(0),),
        gaps=(GapRecord(instant(1), GapReason.MISSING_SOURCE),),
        source_pages=(source(),),
    )
    assert missing.quality is DatasetQuality.INCOMPLETE
    with pytest.raises(CanonicalDatasetValidationError):
        CanonicalCandleDataset(
            product_id=ProductId("BTC-USD"),
            start=instant(0),
            end=instant(2),
            as_of=instant(3),
            candles=(candle(0),),
            gaps=(GapRecord(instant(1), GapReason.UNKNOWN),),
            source_pages=(source(),),
        )
    with pytest.raises(CanonicalDatasetValidationError):
        CanonicalCandleDataset(
            product_id=ProductId("BTC-USD"),
            start=instant(0),
            end=instant(2),
            as_of=instant(3),
            candles=(candle(0),),
            gaps=(),
            source_pages=(source(),),
        )
    with pytest.raises(CanonicalDatasetValidationError):
        CanonicalCandleDataset(
            product_id=ProductId("BTC-USD"),
            start=instant(0),
            end=instant(2),
            as_of=instant(3),
            candles=(candle(0),),
            gaps=(GapRecord(instant(1), GapReason.CONFIRMED_NO_TRADE),),
            source_pages=(source(),),
        )


def test_large_interval_coverage_does_not_need_expected_minute_set() -> None:
    count = 10_000
    dataset = CanonicalCandleDataset(
        product_id=ProductId("BTC-USD"),
        start=instant(0),
        end=instant(count),
        as_of=instant(count + 1),
        candles=(),
        gaps=(GapRecord(instant(index), GapReason.MISSING_SOURCE) for index in range(count)),
        source_pages=(source(),),
    )
    assert len(dataset.gaps) == count


def test_phase_four_raw_evidence_must_be_concrete_and_hash_matched(tmp_path: Path) -> None:
    spec = HistoricalCandleImportSpec(ProductId("BTC-USD"), instant(0), instant(1), instant(2))
    invalid_page = ArchivedRawPage("a" * 64, "b" * 64, {"candles": []}, tmp_path / "raw.json")
    result = HistoricalCandleImportResult(spec, (candle(0),), (), (invalid_page,), 1, 1, 0)
    with pytest.raises(CanonicalDatasetValidationError):
        build_canonical_dataset(result)
    spoofed = HistoricalCandleImportResult(spec, (candle(0),), (), (object(),), 1, 1, 0)
    with pytest.raises(CanonicalDatasetValidationError):
        build_canonical_dataset(spoofed)
