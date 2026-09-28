"""Explicit immutable UTC instant values."""

from dataclasses import dataclass
from datetime import UTC, datetime

from command_station.domain.errors import InvalidTimestampError


@dataclass(frozen=True, slots=True, order=True)
class UtcTimestamp:
    """A timezone-aware instant stored canonically in UTC."""

    value: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.value, datetime):
            raise InvalidTimestampError("timestamp must be a datetime")
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise InvalidTimestampError("timestamp must be timezone-aware")
        object.__setattr__(self, "value", self.value.astimezone(UTC))

    @classmethod
    def parse(cls, text: str) -> "UtcTimestamp":
        """Parse an ISO-8601 timestamp with an explicit UTC offset."""
        if not isinstance(text, str):
            raise InvalidTimestampError("timestamp text must be a string")
        try:
            parsed = datetime.fromisoformat(f"{text[:-1]}+00:00" if text.endswith("Z") else text)
        except ValueError as error:
            raise InvalidTimestampError("timestamp text is malformed") from error
        return cls(parsed)

    def __str__(self) -> str:
        """Return canonical RFC 3339 text using a UTC ``Z`` suffix."""
        return self.value.isoformat().replace("+00:00", "Z")
