"""Current official Rakuten contracts; live construction requires both gates.

Fixture construction never loads environment credentials or uses the wire sender.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import urlparse

from echo.models.affiliate import (
    AffiliateDestination, AffiliateOffer, AffiliateService, DestinationStatus, EvidenceStatus,
    EvidenceType, PriceQuote, ProductCandidate, ProductEvidence,
)
from echo.models.discovery import (
    DiscoveryIdentityMismatch, DiscoveryPage, DiscoveryQuery, DiscoverySource, GenreNode, GenreResult,
    ProviderObservation, SourceAssetReference,
)
from echo.monetization.config import DiscoveryPolicy
from echo.monetization.transport import HttpRequest, HttpResponse, ReadOnlyHttpTransport, TransportError


ENDPOINTS = {
    DiscoverySource.SEARCH: "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701",
    DiscoverySource.GENRES: "https://openapi.rakuten.co.jp/ichibagt/api/IchibaGenre/Search/20260701",
    DiscoverySource.RANKING: "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601",
}
SORTS = {"relevance": "standard", "price_asc": "+itemPrice", "price_desc": "-itemPrice", "reviews_desc": "-reviewCount"}
SERVICE = AffiliateService.RAKUTEN_ICHIBA
LIVE_FLAG = "ECHO_RAKUTEN_LIVE_READONLY"
CREDENTIAL_NAMES = ("RAKUTEN_APPLICATION_ID", "RAKUTEN_ACCESS_KEY", "RAKUTEN_AFFILIATE_ID")


class RakutenCredentials:
    """Not a serializable config model; every diagnostic representation is redacted."""

    __slots__ = ("_application_id", "_access_key", "_affiliate_id")

    def __init__(self, application_id: str, access_key: str, affiliate_id: str | None = None):
        if not application_id or not access_key:
            raise TransportError("credentials_missing")
        values = (application_id, access_key, affiliate_id)
        if any(v is not None and (not isinstance(v, str) or not v or len(v) > 512
                                 or any(ord(c) < 33 or ord(c) > 126 for c in v)) for v in values):
            raise TransportError("credential_configuration_invalid")
        self._application_id, self._access_key, self._affiliate_id = values

    def __repr__(self) -> str:
        return f"RakutenCredentials({self.presence()!r})"

    def presence(self) -> dict[str, bool]:
        return dict(application_id_present=bool(self._application_id), access_key_present=bool(self._access_key),
                    affiliate_id_present=bool(self._affiliate_id))

    @classmethod
    def from_environment(cls, environment: Mapping[str, str], *, live_readonly: bool = False):
        # No real credential lookup occurs until both explicit intent and environment authority pass.
        if live_readonly is not True or environment.get(LIVE_FLAG) != "1":
            raise TransportError("live_readonly_not_authorized")
        return cls(environment.get(CREDENTIAL_NAMES[0], ""), environment.get(CREDENTIAL_NAMES[1], ""),
                   environment.get(CREDENTIAL_NAMES[2]) or None)


def _safe_url(value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value):
        raise TransportError("malformed_response")
    try:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
    except Exception:
        raise TransportError("malformed_response") from None
    return value


def _number(value, *, low: Decimal = Decimal(0), high: Decimal | None = None, integer=False):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise ValueError()
        result = Decimal(value)
        if not result.is_finite() or result < low or (high is not None and result > high) or (integer and result != result.to_integral_value()):
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise TransportError("malformed_response") from None


def _aware_time(value: str | None) -> datetime | None:
    """Never assign a guessed timezone to an official wall-time string."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


class RakutenDiscoveryProvider:
    """Create a fresh provider/transport per discovery execution; cache is never persisted."""

    def __init__(self, transport: ReadOnlyHttpTransport, credentials: RakutenCredentials, *, fixture: bool = True,
                 live_readonly: bool = False, environment: Mapping[str, str] | None = None):
        if not fixture and (live_readonly is not True or environment is None or environment.get(LIVE_FLAG) != "1"):
            raise TransportError("live_readonly_not_authorized")
        self.transport, self.credentials, self.fixture = transport, credentials, fixture
        self._live_intent, self._environment = live_readonly, environment

    def __repr__(self):
        return f"RakutenDiscoveryProvider(fixture={self.fixture}, credentials=REDACTED)"

    @classmethod
    def live(cls, *, live_readonly: bool = False, environment: Mapping[str, str] | None = None,
             policy: DiscoveryPolicy | None = None, sender=None, sleeper=None):
        if live_readonly is not True:
            raise TransportError("live_readonly_not_authorized")
        env = os.environ if environment is None else environment
        credentials = RakutenCredentials.from_environment(env, live_readonly=live_readonly)
        policy = policy or DiscoveryPolicy()
        options = dict(allowed_endpoints=frozenset(ENDPOINTS.values()),
                       authorized=lambda: live_readonly is True and env.get(LIVE_FLAG) == "1",
                       timeout=policy.timeout_seconds, max_bytes=policy.max_response_bytes,
                       max_attempts=policy.max_attempts, backoff_seconds=policy.backoff_seconds,
                       max_requests=policy.runtime_request_budget,
                       minimum_interval=policy.request_interval_seconds)
        if sender is not None:
            options["sender"] = sender
        if sleeper is not None:
            options["sleeper"] = sleeper
        return cls(ReadOnlyHttpTransport(**options), credentials, fixture=False,
                   live_readonly=live_readonly, environment=env)

    @classmethod
    def offline(cls, fixture_path: Path | None = None, *, affiliate_present: bool = True):
        path = fixture_path or Path(__file__).resolve().parents[3] / "tests/fixtures/affiliate/rakuten_phase1.json"
        if path.suffix.lower() != ".json" or path.is_symlink():
            raise TransportError("fixture_path_invalid")
        # Synthetic file only. Explicit JSON loading uses the transport decoder for identical shape rules.
        from echo.monetization.transport import _strict_json
        size = path.stat().st_size
        if size > 2097152:
            raise TransportError("fixture_too_large")
        try:
            fixtures = _strict_json(path.read_bytes())
        except Exception:
            raise TransportError("fixture_invalid") from None
        credentials = RakutenCredentials("SYNTHETIC_APP", "SYNTHETIC_ACCESS", "SYNTHETIC_AFFILIATE" if affiliate_present else None)
        def sender(request, timeout, max_bytes):
            source = next(key for key, endpoint in ENDPOINTS.items() if endpoint == request.endpoint)
            params = dict(request.parameters)
            key = source.value + ":" + params.get("page", "1")
            selector = params.get("itemCode") or params.get("keyword", "")
            value = fixtures.get(key + ":" + selector, fixtures.get(key) if "itemCode" not in params else None)
            if value is None:
                return HttpResponse(404, b"")
            return HttpResponse(200, json.dumps(value, default=str).encode("utf-8"))
        transport = ReadOnlyHttpTransport(allowed_endpoints=frozenset(ENDPOINTS.values()),
                                         authorized=lambda: True, sender=sender, sleeper=lambda delay: None)
        return cls(transport, credentials, fixture=True)

    def request(self, query: DiscoveryQuery) -> HttpRequest:
        if not self.fixture and (self._live_intent is not True or self._environment.get(LIVE_FLAG) != "1"):
            raise TransportError("live_readonly_not_authorized")
        params = {"applicationId": self.credentials._application_id, "format": "json", "formatVersion": "2"}
        if query.source != DiscoverySource.GENRES and self.credentials._affiliate_id:
            params["affiliateId"] = self.credentials._affiliate_id
        if query.category_id is not None:
            params["genreId"] = query.category_id
        if query.source == DiscoverySource.SEARCH:
            for name, value in (("keyword", query.keyword), ("itemCode", query.provider_item_id), ("shopCode", query.merchant_id),
                                ("minPrice", query.minimum_price), ("maxPrice", query.maximum_price)):
                if value is not None:
                    params[name] = str(value)
            params.update(hits=str(query.limit), page=str(query.page), sort=SORTS[query.sort],
                          availability="1" if query.available_only else "0", hasReviewFlag="1" if query.reviews_only else "0")
        elif query.source == DiscoverySource.RANKING:
            params["page"] = str(query.page)
        return HttpRequest(ENDPOINTS[query.source], tuple(sorted(params.items())), (("accessKey", self.credentials._access_key),))

    def genres(self, query: DiscoveryQuery) -> GenreResult:
        if query.source != DiscoverySource.GENRES:
            raise TransportError("wrong_query_source")
        try:
            body = self.transport.fetch(self.request(query))
        except TransportError as error:
            if error.status == 404:
                return GenreResult(not_found=True)
            raise
        try:
            def node(value):
                if not isinstance(value, dict) or not str(value.get("genreId", "")).isdigit():
                    raise ValueError()
                return GenreNode(category_id=str(value["genreId"]), name=value["nameJa"], level=value["level"])
            def nodes(name):
                rows = body.get(name, [])
                if not isinstance(rows, list) or len(rows) > 10000:
                    raise ValueError()
                return tuple(node(row) for row in rows)
            current = node(body["genre"])
            if current.category_id != query.category_id:
                raise ValueError()
            return GenreResult(current=current, ancestors=nodes("ancestors"), siblings=nodes("siblings"), children=nodes("children"))
        except Exception:
            raise TransportError("malformed_response") from None

    def discover(self, query: DiscoveryQuery, *, observed_at: datetime) -> DiscoveryPage:
        if query.source == DiscoverySource.GENRES or observed_at.tzinfo is None:
            raise TransportError("invalid_discovery_intent")
        try:
            body = self.transport.fetch(self.request(query))
        except TransportError as error:
            if error.status == 404:
                return DiscoveryPage(page=query.page, not_found=True, total_pages=0, total_items=0)
            raise
        try:
            # Docs show formatVersion=2 flat items; accept the documented legacy capitalized envelope too.
            if "items" in body and "Items" in body:
                raise ValueError()
            rows = body.get("items", body.get("Items"))
            if not isinstance(rows, list) or len(rows) > 30:
                raise ValueError()
            if query.provider_item_id is not None and any(not isinstance(row, dict) or row.get("itemCode") != query.provider_item_id for row in rows):
                raise DiscoveryIdentityMismatch("hydration_identity_mismatch")
            page = body.get("page", query.page)
            if type(page) is not int or page != query.page:
                raise ValueError()
            page_count = body.get("pageCount") if query.source == DiscoverySource.SEARCH else None
            count = body.get("count") if query.source == DiscoverySource.SEARCH else None
            if page_count is not None and (type(page_count) is not int or not 0 <= page_count <= 100):
                raise ValueError()
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError()
            observations = tuple(self._normalize(row, query, observed_at, body.get("lastBuildDate")) for row in rows)
            return DiscoveryPage(observations=observations, page=page, total_pages=page_count, total_items=count)
        except DiscoveryIdentityMismatch:
            raise
        except Exception:
            raise TransportError("malformed_response") from None

    def _normalize(self, row: dict, query: DiscoveryQuery, observed_at: datetime, updated_raw) -> ProviderObservation:
        if not isinstance(row, dict):
            raise ValueError()
        item_code, name = row.get("itemCode"), row.get("itemName")
        if not isinstance(item_code, str) or not re.fullmatch(r"[A-Za-z0-9_-]+:[A-Za-z0-9_-]+", item_code) or not isinstance(name, str) or not name.strip():
            raise ValueError()
        product_id = "rakuten-" + hashlib.sha256(item_code.encode()).hexdigest()[:12]
        source = query.source.value
        observation_id = hashlib.sha256((source + observed_at.isoformat() + json.dumps(row, sort_keys=True, default=str)).encode()).hexdigest()[:16]
        prefix = f"{product_id}:{observation_id}"
        status = EvidenceStatus.FIXTURE if self.fixture else EvidenceStatus.VERIFIED
        updated = _aware_time(updated_raw) if isinstance(updated_raw, str) else None
        # lastBuildDate anchors conservative Ranking snapshot applicability only.
        # It is never a per-item merchant modification timestamp. Search observations
        # are fresh observations of the returned values, not merchant update times.
        evidence_time = min(observed_at, updated) if updated is not None else observed_at
        source_ref = ENDPOINTS[query.source]  # No credential-bearing request URL in provenance.
        evidence = []; notes = []; raw_timing = []
        def add(field, kind, value, *, unknown=False, start=None, end=None, provider_item_id=None):
            values = {"value_boolean": value} if isinstance(value, bool) else {"value_number": value} if isinstance(value, Decimal) else {"value_text": value}
            record = ProductEvidence(evidence_id=prefix + ":" + field, product_id=product_id, service=SERVICE,
                evidence_type=kind, source_name="Rakuten Ichiba " + source, source_reference=source_ref,
                source_field=field, observed_at=evidence_time, status=EvidenceStatus.UNKNOWN if unknown else status,
                valid_from=start, valid_until=end, provider_item_id=provider_item_id, **values)
            evidence.append(record);return record
        add("itemName", EvidenceType.PRODUCT_IDENTITY, name)
        amount = _number(row.get("itemPrice"), low=Decimal(1))
        if row.get("hasPriceRange") is not None and (type(row["hasPriceRange"]) is not int or row["hasPriceRange"] not in (0, 1)):
            raise ValueError()
        if row.get("hasPriceRange") == 1:
            amount = None;notes.append("price_range_not_an_exact_offer_quote")
        price = None
        if amount is not None:
            record = add("itemPrice", EvidenceType.PRICE, amount)
            price = PriceQuote(amount=amount, currency="JPY", evidence_id=record.evidence_id)
        available = row.get("availability")
        if available is not None and (type(available) is not int or available not in (0, 1)):
            raise ValueError()
        if available is not None:
            add("availability", EvidenceType.AVAILABILITY, available == 1)
        rate = _number(row.get("affiliateRate"), high=Decimal(100))
        for field, kind, high, integer in (("reviewCount", EvidenceType.REVIEW_COUNT, None, True),
                ("reviewAverage", EvidenceType.REVIEW_RATING, Decimal(5), False),
                ("affiliateRate", EvidenceType.AFFILIATE_RATE, Decimal(100), False)):
            value = _number(row.get(field), high=high, integer=integer)
            if value is not None:
                add(field, kind, value)
        if query.source == DiscoverySource.RANKING:
            rank = _number(row.get("rank"), low=Decimal(1), high=Decimal(1000), integer=True)
            if rank is None:
                raise ValueError()
            add("rank", EvidenceType.RANKING, rank, unknown=bool(updated_raw) and updated is None or updated is not None and updated > observed_at)
        for field in ("startTime", "endTime", "pointRateStartTime", "pointRateEndTime"):
            if row.get(field) not in (None, ""):
                if not isinstance(row[field], str) or len(row[field]) > 100:
                    raise ValueError()
                raw_timing.append((field, row[field]))
        start, end = _aware_time(row.get("startTime")), _aware_time(row.get("endTime"))
        if end is not None and (not row.get("startTime") or start is not None):
            add("endTime", EvidenceType.SALE_END, end.isoformat(), start=start, end=end)
        elif row.get("endTime"):
            notes.append("sale_timezone_or_window_unknown")
        points = _number(row.get("pointRate"), low=Decimal(1), high=Decimal(10), integer=True)
        if points is not None:
            ps, pe = _aware_time(row.get("pointRateStartTime")), _aware_time(row.get("pointRateEndTime"))
            ambiguous = bool(row.get("pointRateStartTime") and ps is None or row.get("pointRateEndTime") and pe is None)
            add("pointRate", EvidenceType.POINT_MULTIPLIER, points, unknown=ambiguous, start=ps, end=pe)
            if ambiguous:
                notes.append("point_window_timezone_unknown")
        source_url, affiliate_url = _safe_url(row.get("itemUrl")), _safe_url(row.get("affiliateUrl"))
        def destination(field, kind, url, permitted):
            identity = prefix + ":" + field
            if url and status == EvidenceStatus.VERIFIED and permitted:
                record = add(field, kind, url, provider_item_id=item_code)
                return AffiliateDestination(destination_id=identity, service=SERVICE, provider_item_id=item_code,
                    status=DestinationStatus.VERIFIED, destination_url=url, verification_evidence_id=record.evidence_id)
            return AffiliateDestination(destination_id=identity, service=SERVICE, provider_item_id=item_code,
                status=DestinationStatus.UNVERIFIED if url and permitted else DestinationStatus.NOT_CREATED)
        product_destination = destination("itemUrl", EvidenceType.PRODUCT_DESTINATION, source_url, True)
        affiliate_destination = destination("affiliateUrl", EvidenceType.AFFILIATE_DESTINATION, affiliate_url, bool(self.credentials._affiliate_id))
        if source_url and source_url == affiliate_url:
            notes.append("official_itemUrl_aliases_affiliateUrl")
        assets = []
        for field in ("smallImageUrls", "mediumImageUrls"):
            rows = row.get(field, [])
            if not isinstance(rows, list) or len(rows) > 3:
                raise ValueError()
            for asset in rows:
                value = asset.get("imageUrl") if isinstance(asset, dict) else asset
                url = _safe_url(value)
                if url is None:
                    raise ValueError()
                assets.append(SourceAssetReference(url=url, source_field=field, status=status))
        offer = AffiliateOffer(offer_id=prefix + ":offer", service=SERVICE, provider_item_id=item_code,
            product_destination=product_destination, affiliate_destination=affiliate_destination, price=price,
            affiliate_rate=rate / 100 if rate is not None else None,
            available=available == 1 if available is not None else None)
        candidate = ProductCandidate(product_id=product_id, name=name, category=query.category, service=SERVICE,
                                     provider_item_id=item_code, offer=offer, evidence=tuple(evidence))
        return ProviderObservation(candidate=candidate, query=query, source=query.source, observed_at=observed_at,
            source_url=source_url, returned_affiliate_url=affiliate_url if self.credentials._affiliate_id else None,
            assets=tuple(assets), shop_name=row.get("shopName"), shop_code=row.get("shopCode"),
            genre_id=str(row["genreId"]) if row.get("genreId") is not None else None,
            source_updated_at_raw=updated_raw, ranking_snapshot_at=updated,
            raw_timing=tuple(raw_timing), normalization_notes=tuple(notes))
