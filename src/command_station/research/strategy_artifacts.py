"""Injected trusted factories and explicit immutable strategy code provenance."""

import weakref
from collections.abc import Callable
from dataclasses import dataclass

from command_station.research.specs import (
    StrategyArtifactRef,
    fingerprint,
    require_commit,
    require_sha256,
    require_text,
)
from command_station.strategy import Strategy


@dataclass(frozen=True, slots=True)
class StrategyArtifactDescriptor:
    artifact_name: str
    strategy_id: str
    semantic_version: str
    git_commit: str
    code_sha256: str
    module: str
    qualname: str
    definition_fingerprint: str

    def __post_init__(self) -> None:
        for value in (
            self.artifact_name,
            self.strategy_id,
            self.semantic_version,
            self.module,
            self.qualname,
        ):
            require_text(value)
        require_commit(self.git_commit)
        require_sha256(self.code_sha256)
        require_sha256(self.definition_fingerprint)

    @property
    def fingerprint(self) -> str:
        return fingerprint((1, self))

    @property
    def ref(self) -> StrategyArtifactRef:
        return StrategyArtifactRef(self.fingerprint)


class StrategyArtifactCatalog:
    """Factories are trusted code; explicit code hashes are supplied by the registrar.

    Weak identity tracking rejects factories returning a previously issued live instance
    without retaining completed strategies or trusting custom equality/hash methods.
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[StrategyArtifactDescriptor, Callable[[], Strategy]]] = {}
        self._issued: dict[int, weakref.ReferenceType[Strategy]] = {}

    def register(
        self, descriptor: StrategyArtifactDescriptor, factory: Callable[[], Strategy]
    ) -> None:
        if type(descriptor) is not StrategyArtifactDescriptor or not callable(factory):
            raise ValueError("descriptor and strategy factory required")
        if descriptor.fingerprint in self._entries:
            raise ValueError("artifact already registered")
        self._entries[descriptor.fingerprint] = (descriptor, factory)

    def resolve(self, ref: StrategyArtifactRef) -> tuple[StrategyArtifactDescriptor, Strategy]:
        descriptor, factory = self._entries[ref.fingerprint]
        strategy = factory()
        if not isinstance(strategy, Strategy) or (
            strategy.definition.strategy_id != descriptor.strategy_id
            or strategy.definition.fingerprint != descriptor.definition_fingerprint
            or type(strategy).__module__ != descriptor.module
            or type(strategy).__qualname__ != descriptor.qualname
        ):
            raise ValueError("strategy factory does not match artifact descriptor")
        self._issued = {k: v for k, v in self._issued.items() if v() is not None}
        if id(strategy) in self._issued:
            raise ValueError("strategy factory reused mutable instance")
        self._issued[id(strategy)] = weakref.ref(strategy)
        return descriptor, strategy
