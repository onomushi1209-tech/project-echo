"""Format adapters: turn a fetched response body into ``list[RawRecord]``.

One function per ``SourceType``. Adding a new fetch mechanism (HTML, an
API, X, ...) means adding one ``SourceType`` member (echo.models.enums)
and one function here + an ``ADAPTERS`` entry -- never a Core change.

Every adapter raises only ``AdapterError`` on malformed input; callers
(echo.source.ingest) catch that one exception type to isolate a single
source's bad response from the rest of the batch.

Note: ``xml.etree.ElementTree.Element`` objects are falsy when they have
no children (e.g. a self-closing ``<link href="..."/>``), so this module
never uses ``a or b`` to pick between two ``Element`` results -- see
``_find_first`` below, which checks ``is not None`` explicitly.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.etree.ElementTree import Element

from echo.models.enums import SourceType
from echo.source.records import RawRecord

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class AdapterError(ValueError):
    """Raised when a fetched body cannot be parsed as its declared SourceType."""


def parse_rss(body: bytes) -> list[RawRecord]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise AdapterError(f"malformed RSS/XML: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise AdapterError("RSS document has no <channel>")

    records: list[RawRecord] = []
    for item in channel.findall("item"):
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        if not title or not link:
            continue
        records.append(
            RawRecord(
                title=title,
                url=link,
                published_at_raw=_text(item.find("pubDate")),
                summary=_text(item.find("description")) or "",
                guid=_text(item.find("guid")) or link,
            )
        )
    return records


def parse_atom(body: bytes) -> list[RawRecord]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise AdapterError(f"malformed Atom/XML: {exc}") from exc

    entries = root.findall("atom:entry", _ATOM_NS)
    if not entries:
        entries = root.findall("entry")

    records: list[RawRecord] = []
    for entry in entries:
        title_el = _find_first(entry, "atom:title", "title")
        link_el = _find_first(entry, "atom:link", "link")
        title = _text(title_el)
        link = link_el.get("href") if link_el is not None else None
        if not title or not link:
            continue

        updated_el = _find_first(entry, "atom:updated", "updated", "atom:published", "published")
        summary_el = _find_first(entry, "atom:summary", "summary", "atom:content", "content")
        guid_el = _find_first(entry, "atom:id", "id")

        records.append(
            RawRecord(
                title=title,
                url=link,
                published_at_raw=_text(updated_el),
                summary=_text(summary_el) or "",
                guid=_text(guid_el) or link,
            )
        )
    return records


def parse_json_items(body: bytes) -> list[RawRecord]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"malformed JSON: {exc}") from exc

    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise AdapterError("JSON source must be a list, or an object with an 'items' list")

    records: list[RawRecord] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        url = entry.get("url") or entry.get("link")
        if not title or not url:
            continue
        records.append(
            RawRecord(
                title=str(title),
                url=str(url),
                published_at_raw=entry.get("published_at") or entry.get("date"),
                summary=str(entry.get("summary") or entry.get("content") or ""),
                guid=str(entry.get("id") or url),
            )
        )
    return records


def load_fixture(path: Path) -> list[RawRecord]:
    """STATIC_FIXTURE adapter: reads a local JSON file in the same shape
    ``parse_json_items`` expects. Used for offline demos/tests -- no
    network access."""
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise AdapterError(f"cannot read fixture {path}: {exc}") from exc
    return parse_json_items(body)


ADAPTERS = {
    SourceType.RSS: parse_rss,
    SourceType.ATOM: parse_atom,
    SourceType.JSON: parse_json_items,
    # SourceType.STATIC_FIXTURE is handled by echo.source.ingest directly,
    # since it reads from a local path rather than a fetched body.
}


def _find_first(parent: Element, *paths: str) -> Element | None:
    for path in paths:
        found = parent.find(path, _ATOM_NS if path.startswith("atom:") else None)
        if found is not None:
            return found
    return None


def _text(el: Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    stripped = el.text.strip()
    return stripped or None
