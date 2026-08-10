from __future__ import annotations

from pathlib import Path

import pytest

from echo.source.adapters import AdapterError, load_fixture, parse_atom, parse_json_items, parse_rss

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _read(path: Path) -> bytes:
    return path.read_bytes()


def test_parse_rss_extracts_items() -> None:
    body = _read(FIXTURES_DIR / "feeds" / "rss_valid.xml")
    records = parse_rss(body)
    assert len(records) == 2
    assert records[0].title == "First Test Article"
    assert records[0].url == "https://example.com/articles/first-test-article"
    assert records[0].published_at_raw == "Fri, 07 Aug 2026 15:20:00 GMT"
    assert records[0].summary


def test_parse_rss_malformed_raises_adapter_error() -> None:
    body = _read(FIXTURES_DIR / "feeds" / "rss_malformed.xml")
    with pytest.raises(AdapterError):
        parse_rss(body)


def test_parse_rss_missing_channel_raises() -> None:
    with pytest.raises(AdapterError):
        parse_rss(b"<rss version='2.0'></rss>")


def test_parse_rss_skips_items_missing_title_or_link() -> None:
    body = b"""<rss version="2.0"><channel>
        <item><title>Has Both</title><link>https://example.com/a</link></item>
        <item><link>https://example.com/b</link></item>
        <item><title>No Link</title></item>
    </channel></rss>"""
    records = parse_rss(body)
    assert len(records) == 1
    assert records[0].title == "Has Both"


def test_parse_atom_extracts_entries() -> None:
    body = _read(FIXTURES_DIR / "feeds" / "atom_valid.xml")
    records = parse_atom(body)
    assert len(records) == 2
    assert records[0].title == "First Atom Entry"
    assert records[0].url == "https://example.com/entries/first-atom-entry"
    assert records[0].published_at_raw == "2026-08-08T09:00:00Z"
    assert records[0].summary


def test_parse_atom_malformed_raises_adapter_error() -> None:
    with pytest.raises(AdapterError):
        parse_atom(b"<feed><entry><title>Unclosed</feed>")


def test_parse_atom_self_closing_link_element_is_not_falsy() -> None:
    """Regression test: xml.etree Elements with no children (e.g. a
    self-closing <link href="..."/>) are falsy in a boolean context, so
    the adapter must use `is not None` checks, not `a or b`."""
    body = b"""<feed xmlns="http://www.w3.org/2005/Atom">
        <entry>
            <title>Entry With Self Closing Link</title>
            <link href="https://example.com/self-closing"/>
            <id>https://example.com/self-closing</id>
            <updated>2026-08-08T09:00:00Z</updated>
        </entry>
    </feed>"""
    records = parse_atom(body)
    assert len(records) == 1
    assert records[0].url == "https://example.com/self-closing"


def test_parse_json_items_from_object_with_items_key() -> None:
    body = _read(FIXTURES_DIR / "feeds" / "json_valid.json")
    records = parse_json_items(body)
    assert len(records) == 2
    assert records[0].title == "JSON Item One"
    assert records[0].published_at_raw == "2026-08-08T12:00:00Z"


def test_parse_json_items_from_bare_list() -> None:
    body = b'[{"title": "Bare List Item", "url": "https://example.com/x"}]'
    records = parse_json_items(body)
    assert len(records) == 1
    assert records[0].title == "Bare List Item"


def test_parse_json_items_malformed_raises_adapter_error() -> None:
    with pytest.raises(AdapterError):
        parse_json_items(b"{not valid json")


def test_parse_json_items_wrong_shape_raises_adapter_error() -> None:
    with pytest.raises(AdapterError):
        parse_json_items(b'{"not_items": []}')


def test_parse_json_items_skips_entries_missing_title_or_url() -> None:
    body = b'{"items": [{"title": "Only Title"}, {"url": "https://example.com/only-url"}, {"title": "Both", "url": "https://example.com/both"}]}'
    records = parse_json_items(body)
    assert len(records) == 1
    assert records[0].title == "Both"


def test_load_fixture_reads_local_json_file() -> None:
    fixture_path = FIXTURES_DIR / "sources" / "dummy_fixture.json"
    records = load_fixture(fixture_path)
    assert len(records) == 5


def test_load_fixture_missing_file_raises_adapter_error(tmp_path: Path) -> None:
    with pytest.raises(AdapterError):
        load_fixture(tmp_path / "does_not_exist.json")
