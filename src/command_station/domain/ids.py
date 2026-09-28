"""Opaque immutable internal and provider identifiers."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from command_station.domain.errors import InvalidIdentifierError


@dataclass(frozen=True, slots=True)
class EntityId:
    """Opaque internal UUID-backed entity identity."""

    value: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.value, UUID):
            raise InvalidIdentifierError("entity ID must be a UUID")

    @classmethod
    def new(cls) -> "EntityId":
        """Create a new internal identity using standard-library UUID generation."""
        return cls(uuid4())

    @classmethod
    def parse(cls, text: str) -> "EntityId":
        """Parse canonical UUID text into an immutable identity."""
        if not isinstance(text, str):
            raise InvalidIdentifierError("entity ID must be UUID text")
        try:
            parsed = UUID(text)
        except (ValueError, AttributeError) as error:
            raise InvalidIdentifierError("entity ID must be valid UUID text") from error
        if str(parsed) != text:
            raise InvalidIdentifierError("entity ID must use canonical UUID text")
        return cls(parsed)

    def __str__(self) -> str:
        return str(self.value)


def _validate_opaque_text(value: str, kind: str) -> str:
    if not isinstance(value, str):
        raise InvalidIdentifierError(f"{kind} must be a string")
    if not value:
        raise InvalidIdentifierError(f"{kind} must not be empty")
    if value != value.strip() or any(character.isspace() for character in value):
        raise InvalidIdentifierError(f"{kind} must not contain whitespace")
    return value


@dataclass(frozen=True, slots=True)
class AssetSymbol:
    """An opaque, whitespace-free asset symbol."""

    value: str

    def __post_init__(self) -> None:
        _validate_opaque_text(self.value, "asset symbol")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ProductId:
    """An opaque, whitespace-free provider product identifier."""

    value: str

    def __post_init__(self) -> None:
        _validate_opaque_text(self.value, "product ID")

    def __str__(self) -> str:
        return self.value
