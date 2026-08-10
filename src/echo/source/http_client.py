"""Safe HTTP fetch layer.

Deliberately stdlib-only (``urllib.request``) -- no new dependency was
needed since every requirement (timeout, bounded retries, size cap,
content-type validation, structured errors) is expressible with the
standard library. See docs/SOURCE_INTELLIGENCE.md for why no HTTP client
library (httpx/requests) was added.

Bounded in every dimension so one misbehaving source can never hang or
blow up ingestion for the others:
  - ``timeout``: per-attempt socket timeout.
  - ``max_retries``: retries are capped (never infinite) and only happen
    for network-level failures (timeout/connection error), never for HTTP
    status errors -- retrying a 403/404/500 rarely helps and risks
    hammering a source.
  - ``max_bytes``: the response body is read with a hard cap; a source
    cannot exhaust memory by streaming an unbounded response.
  - content-type is validated against an allow-list before the body is
    read.

``fetch()`` never raises -- every failure mode is returned as a
``FetchOutcome(ok=False, ...)`` so a caller (echo.source.ingest) can
isolate one source's failure from the rest of the batch.
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DEFAULT_USER_AGENT = "Project-Echo/0.1 (+https://github.com/onomushi1209-tech/project-echo)"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 2  # total attempts = 1 + max_retries
DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
ALLOWED_CONTENT_TYPE_PREFIXES: tuple[str, ...] = (
    "text/xml",
    "application/xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/json",
    "text/plain",
)

# Every URL this module opens -- the initial request and every redirect hop
# -- must use one of these schemes. Enforced explicitly in code (see
# _SchemeRestrictedRedirectHandler and _build_restricted_opener below)
# rather than relied upon as an interpreter default, since urllib's own
# built-in redirect behavior for non-http(s) schemes has differed across
# Python versions.
ALLOWED_SCHEMES: tuple[str, ...] = ("http", "https")


class _SchemeRestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuses to follow a redirect whose target scheme is not in
    ``ALLOWED_SCHEMES`` (e.g. ``file:``, ``ftp:``, ``data:``,
    ``javascript:``) -- raised as an ``HTTPError`` carrying the original
    redirect status code, which ``fetch()`` already handles as a normal
    (non-retried) ``http_status`` failure."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        scheme = urllib.parse.urlsplit(newurl).scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            raise urllib.error.HTTPError(
                newurl, code, f"refusing to follow redirect to disallowed scheme {scheme!r}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_restricted_opener() -> urllib.request.OpenerDirector:
    """An opener with no handler capable of opening ``file://``/``ftp://``
    at all -- defense in depth alongside ``_SchemeRestrictedRedirectHandler``,
    so even a bug in the scheme check couldn't resurrect the risk.

    Built by hand rather than via ``urllib.request.build_opener()``:
    ``build_opener()`` always registers its own ``FTPHandler``/
    ``FileHandler`` unless a handler of that exact type is passed in --
    there is no "exclude this handler" option, so the only way to leave
    them out entirely is to assemble the opener's handler list ourselves.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.UnknownHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        _SchemeRestrictedRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


# Installed once, at import time, as the process-wide default opener: every
# urllib.request.urlopen() call in this process (including fetch()'s own
# call below) is routed through it, so the http(s)-only boundary applies to
# the initial request and to every redirect hop -- see
# docs/SOURCE_INTELLIGENCE.md "Redirect scheme security". echo.source is
# the only place in this codebase that makes HTTP requests, so this is the
# intended process-wide policy, not an incidental side effect.
urllib.request.install_opener(_build_restricted_opener())


@dataclass(frozen=True)
class FetchOutcome:
    ok: bool
    url: str
    status_code: int | None = None
    content_type: str | None = None
    body: bytes | None = None
    error_type: str | None = None
    message: str = ""
    attempts: int = 0


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    user_agent: str = DEFAULT_USER_AGENT,
    allowed_content_type_prefixes: tuple[str, ...] = ALLOWED_CONTENT_TYPE_PREFIXES,
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> FetchOutcome:
    """Fetch ``url`` with bounded timeout/retries/size. Never raises."""
    initial_scheme = urllib.parse.urlsplit(url).scheme.lower()
    if initial_scheme not in ALLOWED_SCHEMES:
        return FetchOutcome(
            ok=False,
            url=url,
            error_type="invalid_url",
            message=f"unsupported scheme: {initial_scheme!r}",
            attempts=0,
        )

    max_attempts = max(1, max_retries + 1)
    attempts = 0
    last_error_type = "unknown"
    last_message = ""

    while attempts < max_attempts:
        attempts += 1
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status_code = response.status
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()

                if status_code >= 400:
                    return FetchOutcome(
                        ok=False,
                        url=url,
                        status_code=status_code,
                        content_type=content_type,
                        error_type="http_status",
                        message=f"HTTP {status_code}",
                        attempts=attempts,
                    )

                if allowed_content_type_prefixes and not any(
                    content_type.startswith(prefix) for prefix in allowed_content_type_prefixes
                ):
                    return FetchOutcome(
                        ok=False,
                        url=url,
                        status_code=status_code,
                        content_type=content_type,
                        error_type="content_type_rejected",
                        message=f"unexpected content-type: {content_type!r}",
                        attempts=attempts,
                    )

                # Content-Length is not trusted (absent/lying servers) --
                # the read() cap is the real bound.
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    return FetchOutcome(
                        ok=False,
                        url=url,
                        status_code=status_code,
                        content_type=content_type,
                        error_type="size_exceeded",
                        message=f"response exceeded {max_bytes} bytes",
                        attempts=attempts,
                    )

                return FetchOutcome(
                    ok=True,
                    url=url,
                    status_code=status_code,
                    content_type=content_type,
                    body=body,
                    attempts=attempts,
                )

        except urllib.error.HTTPError as exc:
            # HTTP-level error (4xx/5xx): do not retry.
            return FetchOutcome(
                ok=False,
                url=url,
                status_code=exc.code,
                error_type="http_status",
                message=f"HTTP {exc.code}",
                attempts=attempts,
            )
        except (socket.timeout, TimeoutError) as exc:
            last_error_type = "timeout"
            last_message = str(exc) or "request timed out"
        except urllib.error.URLError as exc:
            last_error_type = "connection_error"
            last_message = str(exc.reason) if exc.reason else str(exc)
        except ValueError as exc:
            # Malformed URL, unsupported scheme, etc. -- retrying cannot help.
            return FetchOutcome(ok=False, url=url, error_type="invalid_url", message=str(exc), attempts=attempts)

        if attempts < max_attempts:
            time.sleep(retry_backoff_seconds)

    return FetchOutcome(ok=False, url=url, error_type=last_error_type, message=last_message, attempts=attempts)
