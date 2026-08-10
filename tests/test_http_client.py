"""http_client tests use a monkeypatched urllib.request.urlopen -- no real
network access, fully offline and deterministic."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request

import pytest

from echo.source.http_client import _SchemeRestrictedRedirectHandler, fetch


class _FakeResponse:
    def __init__(self, status: int, content_type: str | None, body: bytes) -> None:
        self.status = status
        self._body = body
        self.headers = {"Content-Type": content_type} if content_type else {}

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def test_fetch_success_returns_body_and_status(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):
        return _FakeResponse(200, "application/rss+xml", b"<rss></rss>")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    outcome = fetch("https://example.com/feed")

    assert outcome.ok is True
    assert outcome.status_code == 200
    assert outcome.body == b"<rss></rss>"
    assert outcome.attempts == 1


def test_fetch_sets_user_agent_header(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    def fake_urlopen(request, timeout=None):
        headers = {k.lower(): v for k, v in request.header_items()}
        captured["ua"] = headers.get("user-agent")
        return _FakeResponse(200, "application/json", b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    fetch("https://example.com/ua-check", user_agent="Custom-UA/1.0")

    assert captured["ua"] == "Custom-UA/1.0"


def test_fetch_http_error_returns_failure_without_retry(monkeypatch) -> None:
    calls: list[int] = []

    def fake_urlopen(request, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    outcome = fetch("https://example.com/missing", max_retries=2)

    assert outcome.ok is False
    assert outcome.status_code == 404
    assert outcome.error_type == "http_status"
    assert len(calls) == 1  # HTTP status errors are never retried


def test_fetch_status_5xx_reported_as_http_status_without_retry(monkeypatch) -> None:
    calls: list[int] = []

    def fake_urlopen(request, timeout=None):
        calls.append(1)
        return _FakeResponse(503, "application/json", b"")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    outcome = fetch("https://example.com/down", max_retries=2)

    assert outcome.ok is False
    assert outcome.status_code == 503
    assert outcome.error_type == "http_status"
    assert len(calls) == 1


def test_fetch_timeout_retries_up_to_bounded_cap(monkeypatch) -> None:
    calls: list[int] = []

    def fake_urlopen(request, timeout=None):
        calls.append(1)
        raise socket.timeout("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    outcome = fetch("https://example.com/slow", max_retries=2, retry_backoff_seconds=0)

    assert outcome.ok is False
    assert outcome.error_type == "timeout"
    assert len(calls) == 3  # 1 initial attempt + 2 retries, never unbounded


def test_fetch_retries_then_succeeds(monkeypatch) -> None:
    calls: list[int] = []

    def fake_urlopen(request, timeout=None):
        calls.append(1)
        if len(calls) < 2:
            raise socket.timeout("timed out")
        return _FakeResponse(200, "application/json", b'{"items": []}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    outcome = fetch("https://example.com/flaky", max_retries=2, retry_backoff_seconds=0)

    assert outcome.ok is True
    assert outcome.attempts == 2


def test_fetch_connection_error_isolated_as_failure(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    outcome = fetch("https://example.com/down", max_retries=1, retry_backoff_seconds=0)

    assert outcome.ok is False
    assert outcome.error_type == "connection_error"


def test_fetch_rejects_unexpected_content_type(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):
        return _FakeResponse(200, "text/html", b"<html></html>")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    outcome = fetch("https://example.com/page")

    assert outcome.ok is False
    assert outcome.error_type == "content_type_rejected"


def test_fetch_rejects_oversized_response(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):
        return _FakeResponse(200, "application/json", b"x" * 100)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    outcome = fetch("https://example.com/big", max_bytes=10)

    assert outcome.ok is False
    assert outcome.error_type == "size_exceeded"


def test_fetch_never_raises_on_repeated_failures(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):
        raise ValueError("unsupported url scheme")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    outcome = fetch("bad://url", max_retries=3)  # must not raise

    assert outcome.ok is False
    assert outcome.error_type == "invalid_url"


# -- redirect scheme security (Pre-Commit Hardening) -------------------------
#
# fetch()'s own scheme check (initial URL) needs no monkeypatch -- it's
# rejected before any I/O is attempted. _SchemeRestrictedRedirectHandler is
# tested directly: redirect_request() is a pure request-building method (it
# does not itself open a connection), so this stays fully offline while
# still exercising the real handler class fetch() installs as the process
# opener -- not a reimplementation of it.


def test_fetch_rejects_unsupported_initial_scheme_without_any_io() -> None:
    outcome = fetch("ftp://example.com/feed")

    assert outcome.ok is False
    assert outcome.error_type == "invalid_url"
    assert outcome.attempts == 0


def test_fetch_rejects_file_scheme_initial_url() -> None:
    outcome = fetch("file:///etc/passwd")

    assert outcome.ok is False
    assert outcome.error_type == "invalid_url"


def test_redirect_handler_allows_http_to_https() -> None:
    handler = _SchemeRestrictedRedirectHandler()
    req = urllib.request.Request("http://example.com/")

    new_req = handler.redirect_request(req, None, 302, "Found", {}, "https://example.com/new")

    assert new_req.full_url == "https://example.com/new"


def test_redirect_handler_allows_https_to_http() -> None:
    handler = _SchemeRestrictedRedirectHandler()
    req = urllib.request.Request("https://example.com/")

    new_req = handler.redirect_request(req, None, 302, "Found", {}, "http://example.com/new")

    assert new_req.full_url == "http://example.com/new"


def test_redirect_handler_rejects_file_target() -> None:
    handler = _SchemeRestrictedRedirectHandler()
    req = urllib.request.Request("http://example.com/")

    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(req, None, 302, "Found", {}, "file:///etc/passwd")


def test_redirect_handler_rejects_ftp_target() -> None:
    handler = _SchemeRestrictedRedirectHandler()
    req = urllib.request.Request("http://example.com/")

    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(req, None, 302, "Found", {}, "ftp://example.com/file")


def test_redirect_handler_rejects_data_and_javascript_targets() -> None:
    handler = _SchemeRestrictedRedirectHandler()
    req = urllib.request.Request("http://example.com/")

    for disallowed_target in ("data:text/plain;base64,SGVsbG8=", "javascript:alert(1)"):
        with pytest.raises(urllib.error.HTTPError):
            handler.redirect_request(req, None, 302, "Found", {}, disallowed_target)
