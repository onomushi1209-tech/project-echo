"""Normalization: RawRecord + SourceConfig -> SourceItem.

Never raises. A record that is missing something essential (title/url) is
dropped (``NormalizeResult.item is None``, with a reason); a record with a
malformed or missing timestamp is *not* dropped -- it falls back to
``retrieved_at`` so one bad date never takes down the whole ingest run.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from echo.models.source import SourceItem
from echo.source.config import SourceConfig
from echo.source.records import RawRecord

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizeResult:
    item: SourceItem | None
    dropped_reason: str | None = None
    used_fallback_timestamp: bool = False


def normalize_record(
    record: RawRecord, source: SourceConfig, retrieved_at: datetime
) -> NormalizeResult:
    title = _clean_text(record.title)
    if not title:
        return NormalizeResult(item=None, dropped_reason="missing_title")
    if not record.url:
        return NormalizeResult(item=None, dropped_reason="missing_url")

    published_at = _parse_timestamp(record.published_at_raw)
    used_fallback = published_at is None
    if published_at is None:
        published_at = retrieved_at

    content = _clean_text(record.summary)

    try:
        item = SourceItem(
            source_id=_stable_item_id(source.id, record.guid or record.url),
            source_key=source.id,
            url=record.url,
            source_name=source.name,
            title=title,
            published_at=published_at,
            retrieved_at=retrieved_at,
            content=content,
            language=source.language,
            vertical=source.vertical,
        )
    except ValueError as exc:
        # e.g. url fails HttpUrl validation -- isolate, don't crash the batch.
        return NormalizeResult(item=None, dropped_reason=f"invalid_source_item: {exc}")

    return NormalizeResult(item=item, used_fallback_timestamp=used_fallback)


def _stable_item_id(source_key: str, unique_part: str) -> str:
    digest = hashlib.sha256(unique_part.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{source_key}-{digest}"


def _clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    without_tags = _TAG_RE.sub(" ", raw)
    unescaped = html.unescape(without_tags)
    return _WHITESPACE_RE.sub(" ", unescaped).strip()


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw or not raw.strip():
        return None
    raw = raw.strip()

    # RFC 822 / RFC 2822 (RSS pubDate), e.g. "Fri, 07 Aug 2026 15:20:00 GMT"
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass

    # ISO 8601 (Atom updated/published), e.g. "2026-08-09T01:40:53Z"
    iso_candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
