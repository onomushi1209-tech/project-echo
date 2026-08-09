"""Content Trace ID.

A trace ID threads a single piece of content through every pipeline stage:

    Trend -> Research -> Score -> Draft -> Review -> Publish -> Performance -> Memory

Format:  ECHO-{VERTICAL}-{YYYYMMDD}-{SEQUENCE:06d}
Example: ECHO-AI-20260809-000001

The formatting/parsing logic below is pure (no I/O) so it is trivially
testable. Sequence numbers themselves must be monotonic per (vertical, day),
which requires shared state -- that is supplied by a ``SequenceProvider``
injected into ``TraceIDGenerator``, keeping ID *generation* decoupled from ID
*storage*. Production code injects a storage-backed provider
(``echo.storage.repository.EchoRepository.next_trace_sequence``); tests
inject an in-memory one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

_TRACE_ID_PATTERN = re.compile(r"^ECHO-(?P<vertical>[A-Z0-9]+)-(?P<date>\d{8})-(?P<sequence>\d{6})$")


class TraceIDError(ValueError):
    """Raised when a trace ID cannot be formatted or parsed."""


@dataclass(frozen=True)
class TraceIDParts:
    vertical: str
    day: date
    sequence: int


def format_trace_id(vertical: str, day: date, sequence: int) -> str:
    """Build a trace ID string. Pure function, no I/O."""
    if not vertical or not vertical.isascii() or not vertical.replace("_", "").isalnum():
        raise TraceIDError(f"invalid vertical for trace id: {vertical!r}")
    if sequence < 1 or sequence > 999_999:
        raise TraceIDError(f"sequence out of range (1-999999): {sequence!r}")
    return f"ECHO-{vertical.upper()}-{day.strftime('%Y%m%d')}-{sequence:06d}"


def parse_trace_id(trace_id: str) -> TraceIDParts:
    """Parse a trace ID string back into its parts. Pure function, no I/O."""
    match = _TRACE_ID_PATTERN.match(trace_id)
    if not match:
        raise TraceIDError(f"malformed trace id: {trace_id!r}")
    day = date(
        int(match.group("date")[0:4]),
        int(match.group("date")[4:6]),
        int(match.group("date")[6:8]),
    )
    return TraceIDParts(
        vertical=match.group("vertical"),
        day=day,
        sequence=int(match.group("sequence")),
    )


class SequenceProvider(Protocol):
    """Supplies the next monotonic sequence number for (vertical, day)."""

    def __call__(self, vertical: str, day: date) -> int: ...


class InMemorySequenceProvider:
    """Non-persistent sequence provider, useful for tests and one-off scripts."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, date], int] = {}

    def __call__(self, vertical: str, day: date) -> int:
        key = (vertical.upper(), day)
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]


@dataclass
class TraceIDGenerator:
    """Generates trace IDs for a fixed vertical using an injected sequence source."""

    vertical: str
    sequence_provider: SequenceProvider
    clock: Callable[[], date] = field(default=date.today)

    def generate(self, on: date | None = None) -> str:
        day = on if on is not None else self.clock()
        sequence = self.sequence_provider(self.vertical, day)
        return format_trace_id(self.vertical, day, sequence)
