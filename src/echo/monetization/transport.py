"""Bounded, injectable HTTPS GET/JSON transport. Default authorization denies I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
from decimal import Decimal
import json
import math
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class TransportError(RuntimeError):
    """Fixed diagnostics deliberately exclude URLs, bodies and credential values."""

    def __init__(self, code: str, *, status: int | None = None, attempts: int = 0):
        self.code, self.status, self.attempts = code, status, attempts
        super().__init__(f"transport:{code}; status={status}; attempts={attempts}")


@dataclass(frozen=True)
class HttpRequest:
    endpoint: str
    parameters: tuple[tuple[str, str], ...] = field(repr=False)
    headers: tuple[tuple[str, str], ...] = field(repr=False)

    def __repr__(self) -> str:
        return "HttpRequest(GET, credentials=REDACTED)"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = field(repr=False)


class _DenyRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise TransportError("redirect_denied", status=code)


def send_https(request: HttpRequest, timeout: float, max_bytes: int) -> HttpResponse:
    """Private wire details never enter diagnostics; redirects are never followed."""
    try:
        url = request.endpoint + "?" + urlencode(request.parameters)
        wire = Request(url, headers=dict(request.headers), method="GET")
        with build_opener(_DenyRedirect()).open(wire, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise TransportError("response_too_large")
            return HttpResponse(response.status, body)
    except HTTPError as error:
        status = error.code
        error.close()
        return HttpResponse(status, b"")
    except TransportError:
        raise
    except (TimeoutError, URLError, OSError) as error:
        timeout_error = isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)
        raise TransportError("timeout" if timeout_error else "network_failure") from None
    except Exception:
        raise TransportError("network_failure") from None


def _strict_json(body: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite JSON number")
    try:
        result = json.loads(body.decode("utf-8"), object_pairs_hook=unique,
                            parse_float=Decimal, parse_constant=reject)
        if not isinstance(result, dict) or "error" in result:
            raise ValueError("invalid response envelope")
        return result
    except Exception:
        raise TransportError("malformed_response") from None


class ReadOnlyHttpTransport:
    """One execution's memoization; failures are memoized too, preventing storms."""

    def __init__(self, *, allowed_endpoints: frozenset[str],
                 authorized: Callable[[], bool] = lambda: False,
                 sender: Callable[[HttpRequest, float, int], HttpResponse] = send_https,
                 sleeper: Callable[[float], None] = time.sleep,
                 timeout: float = 10, max_bytes: int = 1048576,
                 max_attempts: int = 3, backoff_seconds: float = 0.25,
                 max_requests: int = 20):
        if (not allowed_endpoints or not math.isfinite(timeout) or not 0 < timeout <= 30
                or type(max_bytes) is not int or not 1 <= max_bytes <= 2097152
                or type(max_attempts) is not int or not 1 <= max_attempts <= 3
                or not math.isfinite(backoff_seconds) or not 0 <= backoff_seconds <= 2
                or type(max_requests) is not int or not 1 <= max_requests <= 50):
            raise TransportError("invalid_transport_policy")
        for endpoint in allowed_endpoints:
            self._https_endpoint(endpoint)
        self.allowed_endpoints = allowed_endpoints
        self.authorized, self.sender, self.sleeper = authorized, sender, sleeper
        self.timeout, self.max_bytes = timeout, max_bytes
        self.max_attempts, self.backoff_seconds = max_attempts, backoff_seconds
        self.max_requests = max_requests
        self._cache: dict[HttpRequest, dict | TransportError] = {}

    @staticmethod
    def _https_endpoint(endpoint: str) -> None:
        try:
            u = urlparse(endpoint)
            valid = (u.scheme == "https" and bool(u.hostname) and not u.username and not u.password
                     and u.port in (None, 443) and not u.query and not u.fragment
                     and not any(ord(c) < 33 for c in endpoint))
        except Exception:
            valid = False
        if not valid:
            raise TransportError("unsafe_endpoint")

    def fetch(self, request: HttpRequest) -> dict:
        # Check even cached access: revoked authorization cannot retrieve credential-bound data.
        if not self._authorized():
            raise TransportError("live_readonly_not_authorized")
        self._https_endpoint(request.endpoint)
        if request.endpoint not in self.allowed_endpoints:
            raise TransportError("endpoint_not_allowed")
        if len({key for key, value in request.parameters}) != len(request.parameters):
            raise TransportError("duplicate_request_parameter")
        if any(not isinstance(v, str) or any(ord(c) < 32 for c in v)
               for pair in (*request.parameters, *request.headers) for v in pair):
            raise TransportError("unsafe_request_value")
        if request in self._cache:
            cached = self._cache[request]
            if isinstance(cached, TransportError):
                raise TransportError(cached.code, status=cached.status, attempts=cached.attempts) from None
            return copy.deepcopy(cached)
        if len(self._cache) >= self.max_requests:
            raise TransportError("request_budget_exhausted")
        failure = None
        for attempt in range(1, self.max_attempts + 1):
            if not self._authorized():
                raise TransportError("live_readonly_not_authorized", attempts=attempt - 1)
            try:
                response = self.sender(request, self.timeout, self.max_bytes)
                if type(response.status) is not int or not isinstance(response.body, bytes):
                    raise TransportError("malformed_response")
                if len(response.body) > self.max_bytes:
                    raise TransportError("response_too_large")
                if response.status == 200:
                    result = _strict_json(response.body)
                    self._cache[request] = result
                    # A copy prevents callers from changing later memoized observations.
                    return _strict_json(response.body)
                code = "not_found" if response.status == 404 else "http_status"
                failure = TransportError(code, status=response.status, attempts=attempt)
                transient = response.status in (429, 500, 503)
            except TransportError as error:
                failure = TransportError(error.code, status=error.status, attempts=attempt)
                transient = error.code == "timeout"
            except TimeoutError:
                failure = TransportError("timeout", attempts=attempt)
                transient = True
            except Exception:
                failure = TransportError("network_failure", attempts=attempt)
                transient = False
            if not transient or attempt == self.max_attempts:
                break
            try:
                self.sleeper(min(2.0, self.backoff_seconds * 2 ** (attempt - 1)))
            except Exception:
                failure = TransportError("backoff_failure", attempts=attempt)
                break
        self._cache[request] = failure
        raise TransportError(failure.code, status=failure.status, attempts=failure.attempts) from None

    def _authorized(self) -> bool:
        try:
            return self.authorized() is True
        except Exception:
            raise TransportError("authorization_check_failed") from None
