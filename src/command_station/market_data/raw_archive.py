"""Local immutable raw Coinbase response evidence archive (decoded JSON boundary)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast

from command_station.domain import UtcTimestamp
from command_station.market_data.historical import CoinbaseCandleRequest

RAW_ARCHIVE_SCHEMA_VERSION = 1
_PROVIDER, _ENDPOINT = "coinbase", "public_candles"


class RawArchiveError(Exception):
    pass


class RawArchiveCorruptionError(RawArchiveError):
    pass


class RawArchiveConflictError(RawArchiveError):
    pass


@dataclass(frozen=True, slots=True)
class ArchivedRawPage:
    request_id: str
    payload_sha256: str
    payload: Mapping[str, object]
    path: Path


class LocalRawCandleArchive:
    """Content-verified local archive of decoded SDK mappings, not wire bytes."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise RawArchiveError("archive root must be an explicit absolute Path")
        self._root = root

    def load(self, request: CoinbaseCandleRequest) -> ArchivedRawPage | None:
        path = self._path(request)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RawArchiveCorruptionError("raw archive JSON is corrupt") from error
        return self._validate(value, request, path)

    def store(
        self, request: CoinbaseCandleRequest, *, as_of: UtcTimestamp, payload: Mapping[str, object]
    ) -> ArchivedRawPage:
        if not isinstance(payload, Mapping):
            raise RawArchiveError("raw payload must be a mapping")
        path, record = self._path(request), self._record(request, as_of, payload)
        if path.exists():
            existing = self.load(request)
            if existing is None:
                raise RawArchiveCorruptionError("existing raw archive page disappeared")
            if existing.payload_sha256 != record["payload_sha256"]:
                raise RawArchiveConflictError("raw archive already contains different evidence")
            return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        try:
            temp.write_text(_json(record), encoding="utf-8")
            temp.replace(path)
        except OSError as error:
            raise RawArchiveError("raw archive write failed") from error
        return self._validate(record, request, path)

    def _path(self, request: CoinbaseCandleRequest) -> Path:
        return self._root / _PROVIDER / "candles" / "1m" / f"{request_identity(request)}.json"

    def _record(
        self, request: CoinbaseCandleRequest, as_of: UtcTimestamp, payload: Mapping[str, object]
    ) -> dict[str, object]:
        record = {
            "schema_version": RAW_ARCHIVE_SCHEMA_VERSION,
            "provider": _PROVIDER,
            "endpoint": _ENDPOINT,
            "request": _request_data(request),
            "as_of": str(as_of),
            "payload": payload,
            "payload_sha256": _hash(payload),
            "request_id": request_identity(request),
        }
        record["record_sha256"] = _hash(record)
        return record

    def _validate(
        self, value: object, request: CoinbaseCandleRequest, path: Path
    ) -> ArchivedRawPage:
        if not isinstance(value, Mapping):
            raise RawArchiveCorruptionError("raw archive record must be a mapping")
        record_hash = value.get("record_sha256")
        record_without_hash = {key: item for key, item in value.items() if key != "record_sha256"}
        if not isinstance(record_hash, str) or record_hash != _hash(record_without_hash):
            raise RawArchiveCorruptionError("raw archive record integrity check failed")
        if (
            value.get("schema_version") != RAW_ARCHIVE_SCHEMA_VERSION
            or value.get("provider") != _PROVIDER
            or value.get("endpoint") != _ENDPOINT
        ):
            raise RawArchiveCorruptionError("raw archive metadata is incompatible")
        if value.get("request") != _request_data(request) or value.get(
            "request_id"
        ) != request_identity(request):
            raise RawArchiveCorruptionError("raw archive request identity is invalid")
        payload = value.get("payload")
        if not isinstance(payload, Mapping) or value.get("payload_sha256") != _hash(payload):
            raise RawArchiveCorruptionError("raw archive payload integrity check failed")
        as_of = value.get("as_of")
        if not isinstance(as_of, str):
            raise RawArchiveCorruptionError("raw archive import provenance is invalid")
        try:
            if str(UtcTimestamp.parse(as_of)) != as_of:
                raise RawArchiveCorruptionError(
                    "raw archive import provenance is not canonical UTC"
                )
        except Exception as error:
            if isinstance(error, RawArchiveCorruptionError):
                raise
            raise RawArchiveCorruptionError("raw archive import provenance is invalid") from error
        return ArchivedRawPage(
            request_identity(request), _hash(payload), cast(Mapping[str, object], payload), path
        )


def request_identity(request: CoinbaseCandleRequest) -> str:
    return _hash(_request_data(request))


def unix_seconds_text(value: UtcTimestamp) -> str:
    epoch = UtcTimestamp.parse("1970-01-01T00:00:00Z")
    return str((value.value - epoch.value).days * 86400 + (value.value - epoch.value).seconds)


def _request_data(request: CoinbaseCandleRequest) -> dict[str, object]:
    return {
        "schema_version": RAW_ARCHIVE_SCHEMA_VERSION,
        "provider": _PROVIDER,
        "endpoint": _ENDPOINT,
        "product_id": request.product_id.value,
        "granularity": request.granularity.value,
        "start": unix_seconds_text(request.request_start),
        "end": unix_seconds_text(request.request_end),
        "limit": request.limit,
    }


def _hash(value: object) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise RawArchiveError("raw archive value is not canonical JSON") from error
