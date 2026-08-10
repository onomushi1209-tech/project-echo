"""RawRecord: the common shape every format adapter produces.

Intentionally looser than SourceItem -- fields are unvalidated strings
straight from the feed (e.g. ``published_at_raw`` may be malformed or
missing). ``echo.source.normalize`` is responsible for turning a
RawRecord into a validated SourceItem, or discarding it, without ever
raising.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawRecord:
    title: str
    url: str
    published_at_raw: str | None
    summary: str = ""
    guid: str | None = None
