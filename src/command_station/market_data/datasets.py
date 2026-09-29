"""Immutable logical canonical one-minute dataset values."""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from command_station.domain import (
    Candle,
    ProductId,
    ProductType,
    Timeframe,
    UtcTimestamp,
    Venue,
    decimal_to_text,
)
from command_station.market_data.historical import (
    HistoricalCandleImportResult,
    HistoricalCandleImportSpec,
)
from command_station.market_data.raw_archive import ArchivedRawPage

CANONICAL_DATASET_SCHEMA_VERSION = 1
CANONICAL_MANIFEST_SCHEMA_VERSION = 1
CANONICALIZATION_SCHEMA_VERSION = 1
_MINUTE = timedelta(minutes=1)


class CanonicalDatasetError(Exception):
    """Base error for canonical dataset validation and persistence boundaries."""


class CanonicalDatasetValidationError(CanonicalDatasetError, ValueError):
    pass


class CanonicalDatasetIntegrityError(CanonicalDatasetError):
    pass


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or len(self.value) != 64
            or any(character not in "0123456789abcdef" for character in self.value)
        ):
            raise CanonicalDatasetValidationError("dataset version must be lowercase SHA-256 text")

    def __str__(self) -> str:
        return self.value


class GapReason(StrEnum):
    MISSING_SOURCE = "MISSING_SOURCE"
    CONFIRMED_NO_TRADE = "CONFIRMED_NO_TRADE"
    INACTIVE_NOT_YET_LISTED = "INACTIVE_NOT_YET_LISTED"
    UNKNOWN = "UNKNOWN"


class DatasetQuality(StrEnum):
    VALID = "VALID"
    VALID_WITH_KNOWN_NO_TRADE_INTERVALS = "VALID_WITH_KNOWN_NO_TRADE_INTERVALS"
    INCOMPLETE = "INCOMPLETE"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class GapRecord:
    open_time: UtcTimestamp
    reason: GapReason

    def __post_init__(self) -> None:
        if not isinstance(self.open_time, UtcTimestamp) or not isinstance(self.reason, GapReason):
            raise CanonicalDatasetValidationError("gap record has invalid fields")
        if not _minute_aligned(self.open_time):
            raise CanonicalDatasetValidationError("gap record must align to a UTC minute")


@dataclass(frozen=True, slots=True)
class SourcePageReference:
    request_id: str
    payload_sha256: str

    def __post_init__(self) -> None:
        for value in (self.request_id, self.payload_sha256):
            if not _is_sha256(value):
                raise CanonicalDatasetValidationError("source page evidence must use SHA-256 text")


@dataclass(frozen=True, slots=True)
class ProductSpecProvenance:
    fingerprint: str
    observed_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not _is_sha256(self.fingerprint) or not isinstance(self.observed_at, UtcTimestamp):
            raise CanonicalDatasetValidationError("invalid product specification provenance")


@dataclass(frozen=True, slots=True)
class ParquetArtifact:
    relative_path: str
    row_count: int
    first_open_time: UtcTimestamp
    last_open_time: UtcTimestamp
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.relative_path, str)
            or not self.relative_path
            or "\\" in self.relative_path
            or self.relative_path.startswith("/")
            or ".." in Path(self.relative_path).parts
            or self.row_count < 1
            or self.byte_size < 0
            or not isinstance(self.first_open_time, UtcTimestamp)
            or not isinstance(self.last_open_time, UtcTimestamp)
            or self.first_open_time > self.last_open_time
            or not _is_sha256(self.sha256)
        ):
            raise CanonicalDatasetValidationError("invalid Parquet artifact record")


@dataclass(frozen=True, slots=True, init=False)
class CanonicalCandleDataset:
    version: DatasetVersion
    venue: Venue
    product_type: ProductType
    product_id: ProductId
    timeframe: Timeframe
    start: UtcTimestamp
    end: UtcTimestamp
    as_of: UtcTimestamp
    candles: tuple[Candle, ...]
    gaps: tuple[GapRecord, ...]
    quality: DatasetQuality
    source_pages: tuple[SourcePageReference, ...]
    logical_candle_content_sha256: str
    product_spec_provenance: ProductSpecProvenance | None

    def __init__(
        self,
        *,
        product_id: ProductId,
        start: UtcTimestamp,
        end: UtcTimestamp,
        as_of: UtcTimestamp,
        candles: Iterable[Candle],
        gaps: Iterable[GapRecord],
        source_pages: Iterable[SourcePageReference],
        product_spec_provenance: ProductSpecProvenance | None = None,
    ) -> None:
        candle_values = tuple(sorted(tuple(candles), key=lambda candle: candle.open_time))
        gap_values = tuple(sorted(tuple(gaps), key=lambda gap: gap.open_time))
        page_values = tuple(
            sorted(set(source_pages), key=lambda page: (page.request_id, page.payload_sha256))
        )
        _validate_dataset_fields(
            product_id, start, end, as_of, candle_values, gap_values, page_values
        )
        if product_spec_provenance is not None and not isinstance(
            product_spec_provenance, ProductSpecProvenance
        ):
            raise CanonicalDatasetValidationError("invalid product specification provenance")
        quality = _derive_quality(gap_values)
        candle_hash = logical_candle_content_hash(candle_values)
        identity = _identity_data(
            product_id,
            start,
            end,
            as_of,
            candle_hash,
            gap_values,
            page_values,
            product_spec_provenance,
        )
        object.__setattr__(self, "version", DatasetVersion(_sha256(identity)))
        object.__setattr__(self, "venue", Venue.COINBASE)
        object.__setattr__(self, "product_type", ProductType.SPOT)
        object.__setattr__(self, "product_id", product_id)
        object.__setattr__(self, "timeframe", Timeframe.ONE_MINUTE)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "candles", candle_values)
        object.__setattr__(self, "gaps", gap_values)
        object.__setattr__(self, "quality", quality)
        object.__setattr__(self, "source_pages", page_values)
        object.__setattr__(self, "logical_candle_content_sha256", candle_hash)
        object.__setattr__(self, "product_spec_provenance", product_spec_provenance)


def build_canonical_dataset(
    import_result: HistoricalCandleImportResult,
    *,
    product_spec_provenance: ProductSpecProvenance | None = None,
) -> CanonicalCandleDataset:
    """Defensively transform Phase 004 evidence into canonical logical data."""
    if not isinstance(import_result, HistoricalCandleImportResult) or not isinstance(
        import_result.spec, HistoricalCandleImportSpec
    ):
        raise CanonicalDatasetValidationError("historical import result is invalid")
    references: list[SourcePageReference] = []
    for page in import_result.raw_pages:
        if not isinstance(page, ArchivedRawPage):
            raise CanonicalDatasetValidationError(
                "raw page must be concrete ArchivedRawPage evidence"
            )
        if not isinstance(page.payload, Mapping):
            raise CanonicalDatasetValidationError("raw page payload must be a mapping")
        if _raw_payload_sha256(page.payload) != page.payload_sha256:
            raise CanonicalDatasetValidationError(
                "raw page payload hash does not match its payload"
            )
        references.append(SourcePageReference(page.request_id, page.payload_sha256))
    # Phase 004 ArchivedRawPage carries request_id and payload evidence, but no
    # originating CoinbaseCandleRequest. Correspondence to the import plan is
    # therefore not independently provable here without changing Phase 004.
    return CanonicalCandleDataset(
        product_id=import_result.spec.product_id,
        start=import_result.spec.start,
        end=import_result.spec.end,
        as_of=import_result.spec.as_of,
        candles=import_result.candles,
        gaps=(
            GapRecord(value, GapReason.MISSING_SOURCE) for value in import_result.missing_open_times
        ),
        source_pages=references,
        product_spec_provenance=product_spec_provenance,
    )


def logical_candle_content_hash(candles: Iterable[Candle]) -> str:
    return _sha256(
        [
            {
                "product_id": candle.product_id.value,
                "timeframe": candle.timeframe.value,
                "open_time": str(candle.open_time),
                "close_time": str(candle.close_time),
                "open": decimal_to_text(candle.open),
                "high": decimal_to_text(candle.high),
                "low": decimal_to_text(candle.low),
                "close": decimal_to_text(candle.close),
                "volume": decimal_to_text(candle.volume),
            }
            for candle in candles
        ]
    )


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CanonicalDatasetValidationError(
            "canonical dataset value is not JSON serializable"
        ) from error


def _validate_dataset_fields(
    product_id: ProductId,
    start: UtcTimestamp,
    end: UtcTimestamp,
    as_of: UtcTimestamp,
    candles: tuple[Candle, ...],
    gaps: tuple[GapRecord, ...],
    pages: tuple[SourcePageReference, ...],
) -> None:
    if not isinstance(product_id, ProductId) or not all(
        isinstance(value, UtcTimestamp) for value in (start, end, as_of)
    ):
        raise CanonicalDatasetValidationError("canonical dataset has invalid identity fields")
    if start >= end or not _minute_aligned(start) or not _minute_aligned(end):
        raise CanonicalDatasetValidationError(
            "dataset interval must be ordered UTC-minute boundaries"
        )
    if not pages:
        raise CanonicalDatasetValidationError("canonical dataset requires raw source evidence")
    for gap in gaps:
        if not isinstance(gap, GapRecord) or gap.reason is not GapReason.MISSING_SOURCE:
            raise CanonicalDatasetValidationError("Phase 005 accepts only missing-source gaps")
    candle_index, gap_index, expected = 0, 0, start
    while expected < end:
        candle = candles[candle_index] if candle_index < len(candles) else None
        next_gap = gaps[gap_index] if gap_index < len(gaps) else None
        if candle is not None and candle.open_time == expected:
            _validate_candle(candle, product_id, start, end)
            candle_index += 1
        elif next_gap is not None and next_gap.open_time == expected:
            gap_index += 1
        else:
            raise CanonicalDatasetValidationError(
                "every expected minute must be a candle or explicit gap"
            )
        expected = UtcTimestamp(expected.value + _MINUTE)
    if candle_index != len(candles) or gap_index != len(gaps):
        raise CanonicalDatasetValidationError(
            "canonical data has duplicate or out-of-range minutes"
        )


def _validate_candle(
    candle: Candle, product_id: ProductId, start: UtcTimestamp, end: UtcTimestamp
) -> None:
    if not isinstance(candle, Candle) or candle.product_id != product_id:
        raise CanonicalDatasetValidationError("canonical candle product is inconsistent")
    if candle.timeframe is not Timeframe.ONE_MINUTE or not (start <= candle.open_time < end):
        raise CanonicalDatasetValidationError(
            "canonical candle is outside one-minute dataset interval"
        )


def _derive_quality(gaps: tuple[GapRecord, ...]) -> DatasetQuality:
    if not gaps:
        return DatasetQuality.VALID
    return DatasetQuality.INCOMPLETE


def _identity_data(
    product_id: ProductId,
    start: UtcTimestamp,
    end: UtcTimestamp,
    as_of: UtcTimestamp,
    candle_hash: str,
    gaps: tuple[GapRecord, ...],
    pages: tuple[SourcePageReference, ...],
    provenance: ProductSpecProvenance | None,
) -> dict[str, object]:
    return {
        "canonical_dataset_schema_version": CANONICAL_DATASET_SCHEMA_VERSION,
        "canonicalization_schema_version": CANONICALIZATION_SCHEMA_VERSION,
        "venue": Venue.COINBASE.value,
        "product_type": ProductType.SPOT.value,
        "product_id": product_id.value,
        "timeframe": Timeframe.ONE_MINUTE.value,
        "start": str(start),
        "end": str(end),
        "as_of": str(as_of),
        "logical_candle_content_sha256": candle_hash,
        "gaps": [{"open_time": str(gap.open_time), "reason": gap.reason.value} for gap in gaps],
        "source_pages": [
            {"request_id": page.request_id, "payload_sha256": page.payload_sha256} for page in pages
        ],
        "product_spec_provenance": (
            None
            if provenance is None
            else {"fingerprint": provenance.fingerprint, "observed_at": str(provenance.observed_at)}
        ),
    }


def identity_data(dataset: CanonicalCandleDataset) -> dict[str, object]:
    return _identity_data(
        dataset.product_id,
        dataset.start,
        dataset.end,
        dataset.as_of,
        dataset.logical_candle_content_sha256,
        dataset.gaps,
        dataset.source_pages,
        dataset.product_spec_provenance,
    )


def _minute_aligned(value: UtcTimestamp) -> bool:
    return value.value.second == 0 and value.value.microsecond == 0


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _sha256(value: object) -> str:
    return sha256(canonical_json(value)).hexdigest()


def _raw_payload_sha256(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CanonicalDatasetValidationError("raw page payload is not canonical JSON") from error
    return sha256(encoded).hexdigest()
