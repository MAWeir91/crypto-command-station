"""Immutable batch identities and operational views."""

from dataclasses import dataclass
from enum import StrEnum

from command_station.research.specs import (
    BacktestRunId,
    BacktestSpec,
    EngineIdentity,
    fingerprint,
    require_sha256,
)


class JobState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class BatchBacktestSpec:
    members: tuple[BacktestSpec, ...]

    def __post_init__(self) -> None:
        if (
            type(self.members) is not tuple
            or not self.members
            or any(type(s) is not BacktestSpec for s in self.members)
        ):
            raise ValueError("nonempty immutable batch members required")
        if len({s.fingerprint for s in self.members}) != len(self.members):
            raise ValueError("duplicate logical experiment")
        object.__setattr__(
            self, "members", tuple(sorted(self.members, key=lambda s: s.fingerprint))
        )

    @property
    def fingerprint(self) -> str:
        return fingerprint((1, tuple(s.fingerprint for s in self.members)))


@dataclass(frozen=True, slots=True)
class BatchRunId:
    value: str

    def __post_init__(self) -> None:
        require_sha256(self.value)

    @classmethod
    def derive(cls, spec: BatchBacktestSpec, engine: EngineIdentity) -> "BatchRunId":
        return cls(fingerprint((1, spec.fingerprint, engine.fingerprint)))


@dataclass(frozen=True, slots=True)
class BatchJobId:
    value: str

    def __post_init__(self) -> None:
        require_sha256(self.value)

    @classmethod
    def derive(cls, batch_id: BatchRunId, run_id: BacktestRunId) -> "BatchJobId":
        return cls(fingerprint((1, batch_id.value, run_id.value)))


@dataclass(frozen=True, slots=True)
class BatchExecutionPolicy:
    max_workers: int = 1

    def __post_init__(self) -> None:
        if type(self.max_workers) is not int or not 1 <= self.max_workers <= 32:
            raise ValueError("worker count must be an integer in [1,32]")


@dataclass(frozen=True, slots=True)
class JobView:
    job_id: BatchJobId
    batch_id: BatchRunId
    run_id: BacktestRunId
    spec: BacktestSpec
    engine_identity: EngineIdentity
    state: JobState
    attempt_count: int
    failure_code: str | None
    failure_message: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class BatchView:
    batch_id: BatchRunId
    fingerprint: str
    engine_identity: EngineIdentity
    created_at: str
    counts: tuple[tuple[JobState, int], ...]

    @property
    def state(self) -> JobState:
        counts = dict(self.counts)
        return next(
            (
                s
                for s in (JobState.RUNNING, JobState.PENDING, JobState.FAILED, JobState.CANCELLED)
                if counts[s]
            ),
            JobState.COMPLETED,
        )
