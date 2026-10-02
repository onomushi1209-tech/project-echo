"""Phase 1 contract and adversarial tests; every wire response is synthetic."""

from __future__ import annotations

import copy
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from echo.cli import app
from echo.models.affiliate import DestinationStatus, EvidenceStatus, EvidenceType
from echo.models.discovery import DiscoveryQuery, DiscoverySource
from echo.monetization.config import DiscoveryPolicy, load_discovery_policy
from echo.monetization.discovery import discover_products
from echo.monetization.fixtures import DEMO_AS_OF
from echo.monetization.rakuten import ENDPOINTS, LIVE_FLAG, RakutenCredentials, RakutenDiscoveryProvider
from echo.monetization.transport import HttpRequest, HttpResponse, ReadOnlyHttpTransport, TransportError, _DenyRedirect, send_https


FIXTURE = Path(__file__).parent / "fixtures/affiliate/rakuten_phase1.json"
QUERY = DiscoveryQuery(keyword="照明", category="home", lifestyle_context="reading corner")
ENDPOINT = ENDPOINTS[DiscoverySource.SEARCH]
REQUEST = HttpRequest(ENDPOINT, (("keyword", "照明"),), ())
SENTINELS = ("SYNTHETIC_APP_SENTINEL", "SYNTHETIC_ACCESS_SENTINEL", "SYNTHETIC_AFF_SENTINEL")


def data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def environment(*, affiliate=True):
    return {LIVE_FLAG: "1", "RAKUTEN_APPLICATION_ID": SENTINELS[0],
            "RAKUTEN_ACCESS_KEY": SENTINELS[1], **({"RAKUTEN_AFFILIATE_ID": SENTINELS[2]} if affiliate else {})}


def provider(bank=None, *, affiliate=True, status=200):
    bank = data() if bank is None else bank
    calls = []
    def sender(request, timeout, max_bytes):
        calls.append(request)
        source = next(s for s, endpoint in ENDPOINTS.items() if endpoint == request.endpoint)
        params = dict(request.parameters)
        key = source.value + ":" + params.get("page", "1")
        result = bank.get(key + ":" + params.get("keyword", ""), bank.get(key))
        return HttpResponse(status if result is not None else 404, json.dumps(result).encode())
    adapter = RakutenDiscoveryProvider.live(live_readonly=True, environment=environment(affiliate=affiliate),
        sender=sender, sleeper=lambda delay: None)
    return adapter, calls


def transport(sender, **kwargs):
    return ReadOnlyHttpTransport(allowed_endpoints=frozenset({ENDPOINT}), authorized=lambda: True,
                                 sender=sender, sleeper=lambda delay: None, **kwargs)


@pytest.mark.parametrize("changes", [
    {}, {"keyword":"x"}, {"keyword":"あ"}, {"keyword":" lamp"}, {"keyword":"a  b"},
    {"keyword":"照明\n"}, {"keyword":"照" * 43}, {"keyword":"照明", "limit":31},
    {"keyword":"照明", "page":0}, {"keyword":"照明", "page":True},
    {"keyword":"照明", "sort":"arbitrary"}, {"keyword":"照明", "minimum_price":10,"maximum_price":10},
    {"source":"ranking","keyword":"照明"}, {"source":"ranking","page":35},
    {"source":"genres"}, {"source":"genres","category_id":"0","page":2},
    {"category_id":"../"}, {"provider_item_id":"missing-colon"},
])
def test_adapter_query_rejects_invalid_intent(changes):
    with pytest.raises(ValidationError):
        DiscoveryQuery(**changes)


@pytest.mark.parametrize("changes", [{"keyword":"灯"}, {"keyword":"lamp"}, {"category_id":"0"},
    {"provider_item_id":"echo-fixture:lamp"}, {"merchant_id":"echo-fixture"},
    {"source":"ranking","page":34}, {"source":"genres","category_id":"0"}])
def test_adapter_query_valid_contract_subset(changes):
    DiscoveryQuery(**changes)


@pytest.mark.parametrize("intent,flag", [(False,"1"),(True,"0"),(True,None)])
def test_transport_double_guard_precedes_credential_lookup(intent, flag):
    class Probe(dict):
        def get(self, key, default=None):
            assert key == LIVE_FLAG, "credential lookup must not occur"
            return flag
    with pytest.raises(TransportError, match="not_authorized"):
        RakutenCredentials.from_environment(Probe(), live_readonly=intent)
    with pytest.raises(TransportError, match="not_authorized"):
        RakutenDiscoveryProvider.live(live_readonly=intent, environment=Probe())


def test_transport_missing_credentials_and_safe_repr():
    with pytest.raises(TransportError) as failure:
        RakutenDiscoveryProvider.live(live_readonly=True, environment={LIVE_FLAG:"1"})
    assert "credentials_missing" in str(failure.value)
    adapter, calls = provider()
    request = adapter.request(QUERY)
    assert dict(request.headers) == {"accessKey":SENTINELS[1]}
    assert "accessKey" not in dict(request.parameters)
    assert dict(request.parameters)["applicationId"] == SENTINELS[0]
    for value in SENTINELS:
        assert value not in repr(request) + repr(adapter) + repr(adapter.credentials)
    assert adapter.credentials.presence() == dict(application_id_present=True, access_key_present=True, affiliate_id_present=True)
    assert not calls


def test_transport_default_deny_and_revocation_including_cache():
    calls = []
    default = ReadOnlyHttpTransport(allowed_endpoints=frozenset({ENDPOINT}), sender=lambda *args: calls.append(args))
    with pytest.raises(TransportError, match="not_authorized"):
        default.fetch(REQUEST)
    env = environment()
    adapter = RakutenDiscoveryProvider.live(live_readonly=True, environment=env,
        sender=lambda *args: HttpResponse(200, json.dumps(data()["search:1"]).encode()))
    adapter.discover(QUERY, observed_at=DEMO_AS_OF)
    env[LIVE_FLAG] = "0"
    with pytest.raises(TransportError, match="not_authorized"):
        adapter.discover(QUERY, observed_at=DEMO_AS_OF)
    assert not calls


@pytest.mark.parametrize("url", ["http://example.invalid/path", "https://user:pass@example.invalid/path",
    "https://example.invalid:444/path", "https://example.invalid/path?key=value", "https://example.invalid/path#fragment", "https://example.invalid/\n"])
def test_transport_endpoint_restrictions(url):
    with pytest.raises(TransportError, match="unsafe_endpoint"):
        ReadOnlyHttpTransport(allowed_endpoints=frozenset({url}))


def test_transport_unlisted_endpoint_and_duplicate_params():
    wire = transport(lambda *args: pytest.fail("sender must not be called"))
    with pytest.raises(TransportError, match="endpoint_not_allowed"):
        wire.fetch(HttpRequest("https://unlisted.invalid/api", (), ()))
    with pytest.raises(TransportError, match="duplicate_request_parameter"):
        wire.fetch(HttpRequest(ENDPOINT, (("page","1"),("page","2")), ()))


def test_transport_redirect_and_wire_timeout_are_sanitized(monkeypatch):
    with pytest.raises(TransportError, match="redirect_denied"):
        _DenyRedirect().redirect_request(None, None, 302, SENTINELS[0], {}, "https://other.invalid")
    import echo.monetization.transport as module
    class Opener:
        def open(self, request, timeout):
            assert request.method == "GET" and timeout == 3
            raise TimeoutError(SENTINELS[1])
    monkeypatch.setattr(module, "build_opener", lambda *args: Opener())
    with pytest.raises(TransportError) as failure:
        send_https(REQUEST, 3, 100)
    assert failure.value.code == "timeout" and SENTINELS[1] not in str(failure.value)


@pytest.mark.parametrize("status,attempts", [(400,1),(401,1),(403,1),(404,1),(429,3),(500,3),(503,3),(302,1)])
def test_transport_retry_matrix_failure_cache(status, attempts):
    calls = []
    wire = transport(lambda *args: calls.append(args) or HttpResponse(status, SENTINELS[1].encode()))
    for _ in range(2):
        with pytest.raises(TransportError) as failure:
            wire.fetch(REQUEST)
        assert failure.value.status == status and failure.value.attempts == attempts
        assert SENTINELS[1] not in str(failure.value)
    assert len(calls) == attempts


def test_transport_timeout_recovery_bounded_backoff_and_memoized_copy():
    calls = []; delays = []
    def sender(*args):
        calls.append(args)
        if len(calls) < 3:
            raise TimeoutError(SENTINELS[1])
        return HttpResponse(200, b'{"price":1.25,"nested":{"n":1}}')
    wire = ReadOnlyHttpTransport(allowed_endpoints=frozenset({ENDPOINT}), authorized=lambda: True,
        sender=sender, sleeper=delays.append, backoff_seconds=2)
    result = wire.fetch(REQUEST);result["nested"]["n"] = 999
    assert wire.fetch(REQUEST) == {"price":Decimal("1.25"),"nested":{"n":1}}
    assert delays == [2,2] and len(calls) == 3


@pytest.mark.parametrize("body", [b"[]", b"null", b"{", b'{"x":1,"x":2}', b'{"x":NaN}',
    b'{"x":Infinity}', b'{"error":"SYNTHETIC_ACCESS_SENTINEL"}', b"\xff"])
def test_transport_malformed_json_fails_without_retry_or_echo(body):
    calls = []
    wire = transport(lambda *args: calls.append(args) or HttpResponse(200,body))
    with pytest.raises(TransportError) as failure:
        wire.fetch(REQUEST)
    assert failure.value.code == "malformed_response" and len(calls) == 1
    assert SENTINELS[1] not in str(failure.value)


def test_transport_size_budget_and_callback_redaction():
    with pytest.raises(TransportError, match="response_too_large"):
        transport(lambda *args: HttpResponse(200,b"{} "), max_bytes=2).fetch(REQUEST)
    wire = transport(lambda *args: HttpResponse(200,b"{}"), max_requests=1)
    wire.fetch(REQUEST)
    with pytest.raises(TransportError, match="budget_exhausted"):
        wire.fetch(HttpRequest(ENDPOINT, (("page","2"),), ()))
    def fail():
        raise ValueError(SENTINELS[0])
    wire.authorized = fail
    with pytest.raises(TransportError) as failure:
        wire.fetch(REQUEST)
    assert SENTINELS[0] not in str(failure.value)


@pytest.mark.parametrize("changes", [{"max_attempts":4},{"timeout":31},{"timeout":float("nan")},
    {"max_bytes":0},{"backoff_seconds":3},{"max_requests":51}])
def test_transport_policy_is_bounded(changes):
    with pytest.raises(TransportError):
        transport(lambda *args: HttpResponse(200,b"{}"), **changes)


def test_adapter_request_mapping_and_genre_root():
    adapter, _ = provider()
    query = DiscoveryQuery(keyword="照明", category_id="990001", minimum_price=10, maximum_price=10000,
        sort="price_asc", reviews_only=True, available_only=False, limit=5, page=2)
    request = adapter.request(query);params = dict(request.parameters)
    assert request.endpoint.endswith("/20260701")
    assert params["sort"] == "+itemPrice" and params["page"] == "2" and params["hits"] == "5"
    assert params["availability"] == "0" and params["hasReviewFlag"] == "1"
    assert params["formatVersion"] == "2" and params["genreId"] == "990001"
    assert params["minPrice"] == "10" and params["maxPrice"] == "10000"
    result = adapter.genres(DiscoveryQuery(source="genres",category_id="0"))
    assert result.current.category_id == "0" and len(result.children) == 2
    assert "affiliateId" not in dict(adapter.request(DiscoveryQuery(source="genres",category_id="0")).parameters)
    assert "hits" not in dict(adapter.request(DiscoveryQuery(source="ranking")).parameters)


def test_adapter_normalization_and_fixture_boundary():
    adapter = RakutenDiscoveryProvider.offline()
    page = adapter.discover(QUERY,observed_at=DEMO_AS_OF)
    first = page.observations[0];candidate = first.candidate
    assert page.total_pages == 2 and candidate.provider_item_id == "echo-fixture:lamp"
    assert candidate.offer.price.amount == 4500 and candidate.offer.affiliate_rate == Decimal(".1")
    assert all(r.status == EvidenceStatus.FIXTURE for r in candidate.evidence)
    assert candidate.offer.affiliate_destination.status == DestinationStatus.UNVERIFIED
    assert candidate.offer.affiliate_destination.destination_url is None
    assert first.returned_affiliate_url == "https://affiliate.invalid/lamp"
    assert all(a.rights_status == "unknown" and a.transformation_rights_proven is False for a in first.assets)
    assert all(r.source_reference == ENDPOINT for r in candidate.evidence)


def test_adapter_no_affiliate_id_never_creates_destination_and_alias_is_explicit():
    bank = data();bank["search:1"]["items"][0]["itemUrl"] = "https://affiliate.invalid/lamp"
    adapter, _ = provider(bank, affiliate=False)
    result = adapter.discover(QUERY,observed_at=DEMO_AS_OF).observations[0]
    assert result.returned_affiliate_url is None
    assert result.candidate.offer.affiliate_destination.status == DestinationStatus.NOT_CREATED
    assert "official_itemUrl_aliases_affiliateUrl" in result.normalization_notes
    adapter, _ = provider(bank)
    result = adapter.discover(QUERY,observed_at=DEMO_AS_OF).observations[0]
    assert result.source_url == result.returned_affiliate_url
    assert result.candidate.offer.affiliate_destination.destination_url == result.returned_affiliate_url


@pytest.mark.parametrize("field,value", [("itemCode","bad"),("itemName",""),("itemPrice",True),
    ("itemPrice",-1),("reviewAverage",6),("reviewCount",1.5),("availability",True),
    ("affiliateRate",101),("hasPriceRange",False),("itemUrl","http://shop.invalid"),
    ("affiliateUrl","https://user:pass@shop.invalid"),("mediumImageUrls",[None]),("pointRate",0)])
def test_adapter_rejects_malformed_record_without_values(field, value):
    bank = data();bank["search:1"]["items"][0][field] = value
    adapter, _ = provider(bank)
    with pytest.raises(TransportError, match="malformed_response") as failure:
        adapter.discover(QUERY,observed_at=DEMO_AS_OF)
    assert not any(s in str(failure.value) for s in SENTINELS)


@pytest.mark.parametrize("change", [{"page":2},{"pageCount":101},{"count":True},{"items":{}},
    {"items":[{"Item":{}}]}, {"Items":[]}])
def test_adapter_rejects_inconsistent_envelope(change):
    bank=data();bank["search:1"].update(change)
    adapter,_=provider(bank)
    with pytest.raises(TransportError):
        adapter.discover(QUERY,observed_at=DEMO_AS_OF)


def test_adapter_not_found_and_invalid_genre_shapes():
    adapter, calls = provider({},status=404)
    assert adapter.discover(QUERY,observed_at=DEMO_AS_OF).not_found
    assert adapter.genres(DiscoveryQuery(source="genres",category_id="0")).not_found
    assert len(calls) == 2
    bank=data();bank["genres:1"]["genre"]["genreId"]="1"
    adapter,_=provider(bank)
    with pytest.raises(TransportError):
        adapter.genres(DiscoveryQuery(source="genres",category_id="0"))


def test_adapter_naive_timing_unknown_and_offset_windows_remain_bounded():
    bank=data();row=bank["search:1"]["items"][0]
    row.update(startTime="2026-09-28 00:00",endTime="2026-09-30 00:00",pointRateStartTime="2026-09-28 00:00",pointRateEndTime="2026-09-30 00:00")
    adapter,_=provider(bank);o=adapter.discover(QUERY,observed_at=DEMO_AS_OF).observations[0]
    assert len(o.raw_timing)==4 and "sale_timezone_or_window_unknown" in o.normalization_notes
    assert not any(r.evidence_type==EvidenceType.SALE_END for r in o.candidate.evidence)
    assert next(r for r in o.candidate.evidence if r.evidence_type==EvidenceType.POINT_MULTIPLIER).status==EvidenceStatus.UNKNOWN
    row.update(startTime=(DEMO_AS_OF-timedelta(hours=1)).isoformat(),endTime=(DEMO_AS_OF+timedelta(hours=1)).isoformat(),
        pointRateStartTime=(DEMO_AS_OF+timedelta(hours=1)).isoformat(),pointRateEndTime=(DEMO_AS_OF+timedelta(hours=2)).isoformat())
    adapter,_=provider(bank)
    result=discover_products(adapter,(QUERY,),as_of=DEMO_AS_OF)
    lamp=next(c for c in result.candidates if c.provider_item_id.endswith(":lamp"))
    assert any(r.evidence_type==EvidenceType.SALE_END for r in lamp.evidence)
    assert not any(s.evidence_type==EvidenceType.POINT_MULTIPLIER for s in result.signals_by_product[lamp.product_id])


def test_adapter_ranking_price_range_and_invalid_rank():
    bank=data();bank["ranking:1"]["items"][0]["hasPriceRange"]=1
    adapter,_=provider(bank)
    page=adapter.discover(DiscoveryQuery(source="ranking"),observed_at=DEMO_AS_OF)
    assert page.observations[0].candidate.offer.price is None
    bank["ranking:1"]["items"][0]["rank"]=0
    adapter,_=provider(bank)
    with pytest.raises(TransportError):
        adapter.discover(DiscoveryQuery(source="ranking"),observed_at=DEMO_AS_OF)


def test_pipeline_cross_source_dedup_preserves_evidence_and_determinism():
    queries=(QUERY,DiscoveryQuery(source="ranking",category="home",lifestyle_context="reading corner"))
    adapter,calls=provider();result=discover_products(adapter,queries,as_of=DEMO_AS_OF)
    adapter2,_=provider();reverse=discover_products(adapter2,tuple(reversed(queries)),as_of=DEMO_AS_OF)
    assert result==reverse and len(result.candidates)==4 and len(result.observations)==6
    lamp=next(c for c in result.candidates if c.provider_item_id.endswith(":lamp"))
    assert {r.source_name for r in lamp.evidence}=={"Rakuten Ichiba search","Rakuten Ichiba ranking"}
    assert len([r for r in lamp.evidence if r.evidence_type==EvidenceType.PRICE])==2
    assert len(calls)==2 and len(result.selected)==2
    assert all(s.final_score>=Decimal(".5") for s in result.scores if s.product_id in {c.product_id for c in result.selected})


def test_pipeline_conflict_fails_closed_and_no_filler():
    bank=data();bank["ranking:1"]["items"][0]["itemPrice"]=9999
    adapter,_=provider(bank)
    result=discover_products(adapter,(QUERY,DiscoveryQuery(source="ranking")),as_of=DEMO_AS_OF,policy=DiscoveryPolicy(top_n=20))
    assert [c.provider_item_id for c in result.selected]==["echo-fixture:rug"]
    lamp=next(c for c in result.candidates if c.provider_item_id.endswith(":lamp"))
    assert "current_evidence_conflict" in result.exclusions[lamp.product_id]
    assert not result.can_publish and result.human_approval_required


@pytest.mark.parametrize("field,replacement", [("itemPrice",None),("hasPriceRange",1),
    ("availability",None),("affiliateRate",None),("affiliateUrl",None)])
def test_pipeline_sparse_ranking_cannot_erase_current_search_offer(field,replacement):
    bank=data();row=bank["ranking:1"]["items"][0]
    if replacement is None:
        row.pop(field,None)
    else:
        row[field]=replacement
    queries=(QUERY,DiscoveryQuery(source="ranking",category="home",lifestyle_context="reading corner"))
    adapter,_=provider(bank);result=discover_products(adapter,queries,as_of=DEMO_AS_OF)
    adapter,_=provider(bank);reverse=discover_products(adapter,tuple(reversed(queries)),as_of=DEMO_AS_OF)
    assert result==reverse
    lamp=next(c for c in result.selected if c.provider_item_id.endswith(":lamp"))
    assert lamp.offer.price.amount==4500 and lamp.offer.available is True
    assert lamp.offer.affiliate_rate==Decimal(".1")
    assert lamp.offer.affiliate_destination.destination_url=="https://affiliate.invalid/lamp"
    assert len([o for o in result.observations if o.candidate.product_id==lamp.product_id])==2


def test_pipeline_sparse_current_ranking_does_not_resurrect_expired_search_quote():
    bank=data();bank["ranking:1"]["items"][0].pop("itemPrice")
    adapter,_=provider(bank)
    old_page=adapter.discover(QUERY,observed_at=DEMO_AS_OF-timedelta(days=2))
    ranking_page=adapter.discover(DiscoveryQuery(source="ranking"),observed_at=DEMO_AS_OF)
    class Pages:
        def discover(self,query,*,observed_at):
            return old_page if query.source==DiscoverySource.SEARCH else ranking_page
    result=discover_products(Pages(),(QUERY,DiscoveryQuery(source="ranking")),as_of=DEMO_AS_OF)
    lamp=next(c for c in result.candidates if c.provider_item_id.endswith(":lamp"))
    assert lamp.offer.price is None and lamp.product_id in result.exclusions


def test_pipeline_expired_ranking_does_not_poison_current_search():
    bank=data();bank["ranking:1"]["lastBuildDate"]=(DEMO_AS_OF-timedelta(days=30)).isoformat()
    bank["ranking:1"]["items"][0]["itemPrice"]=9999
    adapter,_=provider(bank)
    result=discover_products(adapter,(QUERY,DiscoveryQuery(source="ranking")),as_of=DEMO_AS_OF)
    assert "echo-fixture:lamp" in {c.provider_item_id for c in result.selected}
    lamp=next(c for c in result.candidates if c.provider_item_id.endswith(":lamp"))
    assert lamp.offer.price.amount==4500


def test_pipeline_top_n_pages_and_request_dedup():
    adapter,calls=provider()
    result=discover_products(adapter,(QUERY,QUERY),as_of=DEMO_AS_OF,policy=DiscoveryPolicy(top_n=1,pages_per_query=2))
    assert len(calls)==2 and len(result.candidates)==6 and len(result.selected)==1
    assert result.selected[0].provider_item_id=="echo-fixture:lamp"
    assert any("current_exact_price_missing" in reasons for reasons in result.exclusions.values())


def test_pipeline_threshold_empty_result_and_bounds():
    adapter,_=provider()
    assert not discover_products(adapter,(QUERY,),as_of=DEMO_AS_OF,policy=DiscoveryPolicy(minimum_score=1)).selected
    adapter,_=provider({})
    assert not discover_products(adapter,(QUERY,),as_of=DEMO_AS_OF).selected
    for queries in ((),(QUERY,)*11,(DiscoveryQuery(source="genres",category_id="0"),)):
        with pytest.raises(ValueError):
            discover_products(adapter,queries,as_of=DEMO_AS_OF)
    assert load_discovery_policy().top_n==5


def test_pipeline_visual_rights_unknown_independent_destinations_and_human_gate():
    bank=data()
    bank["search:1:lamp"]={"items":[copy.deepcopy(bank["search:1"]["items"][0])],"page":1,"pageCount":1,"count":1}
    bank["search:1:rug"]={"items":[copy.deepcopy(bank["search:1"]["items"][1])],"page":1,"pageCount":1,"count":1}
    queries=(DiscoveryQuery(keyword="lamp",category="lighting",lifestyle_context="reading corner",complementary_role="task lighting"),
             DiscoveryQuery(keyword="rug",category="textiles",lifestyle_context="reading corner",complementary_role="floor comfort"))
    adapter,_=provider(bank);result=discover_products(adapter,queries,as_of=DEMO_AS_OF)
    assert result.bundle is not None and len(result.bundle.items)==2 and len(result.proposals)==3
    proposal=result.proposals[-1]
    assert len({c.offer.affiliate_destination.destination_url for c in result.selected})==2
    assert all(a.rights_status.value=="unknown" for a in proposal.visual_assets)
    assert all(not report.live_publish_authorized and not report.ready_for_human_approval for report in result.compliance)
    assert result.human_approval_required and not result.can_publish
    assert len(proposal.carousel.slides)==3 and len(proposal.carousel.slides[0].labels)==2
    adapter,_=provider(bank,affiliate=False)
    assert discover_products(adapter,queries,as_of=DEMO_AS_OF).bundle is None


def test_pipeline_unrelated_contexts_no_bundle():
    adapter,_=provider()
    result=discover_products(adapter,(QUERY,),as_of=DEMO_AS_OF)
    assert result.bundle is None and result.bundle_notes
    assert len(result.proposals)==2


@pytest.mark.parametrize("arguments,exit_code", [([],0),(["--source","ranking"],0),(["--source","genres"],0),
    (["--provider","rakuyoko"],2),(["--source","unsupported"],2),(["--top","0"],2),(["--live-readonly"],2)])
def test_pipeline_cli_safe_offline_default_and_denied_live(monkeypatch,arguments,exit_code):
    monkeypatch.delenv(LIVE_FLAG,raising=False)
    result=CliRunner().invoke(app,["affiliate","discover",*arguments])
    assert result.exit_code==exit_code
    assert not any(value in result.output for value in SENTINELS)
    if not arguments:
        assert "offline fixtures" in result.output and "can_publish=false" in result.output


def test_pipeline_architecture_keeps_http_and_provider_details_out_of_domain():
    root=Path(__file__).resolve().parents[1]/"src/echo"
    for relative in ("models/discovery.py","monetization/discovery.py"):
        content=(root/relative).read_text(encoding="utf-8")
        assert "urllib" not in content and "from echo.monetization.rakuten" not in content
    for relative in ("core","services","research"):
        folder=root/relative
        for path in folder.rglob("*.py"):
            assert "echo.monetization.rakuten" not in path.read_text(encoding="utf-8")
