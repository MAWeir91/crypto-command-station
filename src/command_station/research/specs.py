"""Immutable, canonical experiment identity; no filesystem or wall-clock identity."""

import json
import math
import re
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256

from command_station.accounting import SpotAccountSpec
from command_station.domain import ProductId, UtcTimestamp, decimal_to_text
from command_station.execution import ReferenceExecutionSpec
from command_station.market_data.datasets import DatasetVersion
from command_station.risk import RiskPolicy


def logical(value: object) -> object:
    """Explicit value serialization; rejects unsupported and nonfinite values."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite Decimal")
        text = decimal_to_text(value)
        return "0" if value == 0 else (text.rstrip("0").rstrip(".") if "." in text else text)
    if isinstance(value, UtcTimestamp):
        return str(value)
    if isinstance(value, Enum):
        return logical(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: logical(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (tuple, list)):
        return [logical(v) for v in value]
    if isinstance(value, dict):
        if any(type(k) is not str for k in value):
            raise ValueError("JSON keys must be strings")
        return {k: logical(v) for k, v in value.items()}
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("unsupported canonical value")


def canonical_json(value: object) -> bytes:
    return json.dumps(
        logical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def fingerprint(value: object) -> str:
    return sha256(canonical_json(value)).hexdigest()


def require_sha256(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("exact lowercase SHA-256 required")


def require_commit(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("exact lowercase Git commit required")


def require_text(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("nonempty canonical text required")


@dataclass(frozen=True, slots=True)
class StrategyArtifactRef:
    fingerprint: str

    def __post_init__(self) -> None:
        require_sha256(self.fingerprint)


@dataclass(frozen=True, slots=True)
class BacktestPeriod:
    trading_start: UtcTimestamp
    replay_end: UtcTimestamp

    def __post_init__(self) -> None:
        for timestamp in (self.trading_start, self.replay_end):
            if (
                not isinstance(timestamp, UtcTimestamp)
                or timestamp.value.second
                or timestamp.value.microsecond
            ):
                raise ValueError("period requires UTC minute boundaries")
        if self.trading_start > self.replay_end:
            raise ValueError("trading start must not follow replay end")


@dataclass(frozen=True, slots=True)
class BacktestDatasetRef:
    product_id: ProductId
    dataset_version: DatasetVersion

    def __post_init__(self) -> None:
        if not isinstance(self.product_id, ProductId) or not isinstance(
            self.dataset_version, DatasetVersion
        ):
            raise ValueError("exact product and DatasetVersion required")


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    git_commit: str
    package_version: str
    reference_engine_version: str

    def __post_init__(self) -> None:
        require_commit(self.git_commit)
        require_text(self.package_version)
        require_text(self.reference_engine_version)

    @property
    def fingerprint(self) -> str:
        return fingerprint((1, self))


@dataclass(frozen=True, slots=True)
class BacktestRunId:
    value: str

    def __post_init__(self) -> None:
        require_sha256(self.value)

    @classmethod
    def derive(cls, spec: "BacktestSpec", engine: EngineIdentity) -> "BacktestRunId":
        return cls(fingerprint((1, spec.fingerprint, engine.fingerprint)))


@dataclass(frozen=True, slots=True)
class BacktestSpec:
    strategy_artifact: StrategyArtifactRef
    parameters: tuple[tuple[str, object], ...]
    datasets: tuple[BacktestDatasetRef, ...]
    period: BacktestPeriod
    account: SpotAccountSpec
    risk_policy: RiskPolicy
    execution: ReferenceExecutionSpec
    random_seed: int

    def __post_init__(self) -> None:
        for contract, cls in (
            (self.strategy_artifact, StrategyArtifactRef),
            (self.period, BacktestPeriod),
            (self.account, SpotAccountSpec),
            (self.risk_policy, RiskPolicy),
            (self.execution, ReferenceExecutionSpec),
        ):
            if type(contract) is not cls:
                raise ValueError("spec requires immutable built-in contracts")
        if type(self.random_seed) is not int:
            raise ValueError("random seed must be an integer, not bool")
        if not isinstance(self.datasets, tuple) or any(
            type(d) is not BacktestDatasetRef for d in self.datasets
        ):
            raise ValueError("immutable exact dataset references required")
        products = {d.product_id for d in self.datasets}
        if len(products) != len(self.datasets) or products != {
            p.product_id for p in self.account.product_specs
        }:
            raise ValueError("exactly one dataset per account product required")
        if not isinstance(self.parameters, tuple):
            raise ValueError("immutable parameters required")
        names: set[str] = set()
        for pair in self.parameters:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("parameter pairs required")
            name, value = pair
            require_text(name)
            if name in names or (
                value is not None and type(value) not in (int, str, bool, float, Decimal)
            ):
                raise ValueError("unique scalar parameters required")
            logical(value)
            names.add(name)
        object.__setattr__(
            self, "datasets", tuple(sorted(self.datasets, key=lambda d: d.product_id.value))
        )
        object.__setattr__(self, "parameters", tuple(sorted(self.parameters)))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "strategy_artifact": logical(self.strategy_artifact),
            "parameters": [
                {"name": k, "type": type(v).__name__, "value": logical(v)}
                for k, v in self.parameters
            ],
            "datasets": logical(self.datasets),
            "period": logical(self.period),
            "account": logical(self.account),
            "account_fingerprint": self.account.fingerprint,
            "risk_policy": self.risk_policy.to_dict(),
            "risk_policy_fingerprint": self.risk_policy.fingerprint,
            "execution": self.execution.to_dict(),
            "random_seed": self.random_seed,
        }

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())
