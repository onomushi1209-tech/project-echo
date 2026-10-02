"""Exact identity, temporal safety and acquisition-budget regression cases."""

import copy
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from echo.cli import app
from echo.models.affiliate import DestinationStatus, EvidenceType
from echo.models.discovery import DiscoveryIdentityMismatch, DiscoveryQuery, DiscoverySource
from echo.monetization.config import DiscoveryPolicy
from echo.monetization.discovery import discover_products
from echo.monetization.fixtures import DEMO_AS_OF
from echo.monetization.rakuten import ENDPOINTS, RakutenDiscoveryProvider
from echo.monetization.transport import HttpRequest, HttpResponse, ReadOnlyHttpTransport, TransportError

FIXTURE = Path(__file__).parent / "fixtures/affiliate/ranked_hydration.json"
RANKING = DiscoveryQuery(source="ranking", category="lighting", lifestyle_context="reading corner")
ITEM = "echo-hydration:lamp"


def bank():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def provider(data=None):
    data = bank() if data is None else data
    calls = []
    def sender(request, timeout, max_bytes):
        calls.append(request)
        source = next(s for s, endpoint in ENDPOINTS.items() if endpoint == request.endpoint)
        p = dict(request.parameters)
        key = source.value + ":" + p.get("page", "1")
        if p.get("itemCode"):
            key += ":" + p["itemCode"]
        elif p.get("genreId") and key + ":" + p["genreId"] in data:
            key += ":" + p["genreId"]
        result = data.get(key)
        return HttpResponse(200 if result is not None else 404, json.dumps(result).encode())
    environment = {"ECHO_RAKUTEN_LIVE_READONLY": "1", "RAKUTEN_APPLICATION_ID": "SYNTHETIC_APP",
                   "RAKUTEN_ACCESS_KEY": "SYNTHETIC_ACCESS", "RAKUTEN_AFFILIATE_ID": "SYNTHETIC_AFFILIATE"}
    return RakutenDiscoveryProvider.live(live_readonly=True, environment=environment,
        sender=sender, sleeper=lambda delay: None), calls


def run(data=None, policy=None):
    adapter, calls = provider(data)
    return discover_products(adapter, (RANKING,), as_of=DEMO_AS_OF, policy=policy), calls


def test_hyd_t01_to_t06_stale_offer_hydrates_and_retains_legitimate_rank_price_stock_destination():
    result, calls = run()
    assert len(calls) == 2 and dict(calls[1].parameters)["itemCode"] == ITEM
    assert "keyword" not in dict(calls[1].parameters)
    assert result.hydration.requests == 1 and result.hydration.outcomes[0].status == "success"
    assert len(result.observations) == 2 and len(result.selected) == 1
    c = result.selected[0]
    assert c.provider_item_id == ITEM and c.offer.price.amount == 4500 and c.offer.available is True
    assert c.offer.affiliate_destination.status == DestinationStatus.VERIFIED
    assert c.offer.affiliate_destination.destination_url == "https://affiliate.invalid/hydrated-lamp"
    rank = next(e for e in c.evidence if e.evidence_type == EvidenceType.RANKING)
    price = next(e for e in c.evidence if e.evidence_id == c.offer.price.evidence_id)
    assert rank.source_name == "Rakuten Ichiba ranking" and rank.value_number == 1
    assert rank.observed_at == DEMO_AS_OF - timedelta(days=2)
    assert price.source_name == "Rakuten Ichiba search" and price.observed_at == DEMO_AS_OF
    assert result.observations[0].observed_at == DEMO_AS_OF
    assert next(o for o in result.observations if o.source == DiscoverySource.RANKING).ranking_snapshot_at == rank.observed_at
    score = next(s for s in result.scores if s.product_id == c.product_id)
    assert score.final_score >= Decimal(".50")
    demand = next(x for x in score.components if x.component.value == "demand")
    assert rank.evidence_id in demand.evidence_ids
    assert not result.can_publish and result.human_approval_required
    assert all(not r.can_publish for r in result.compliance)


def test_hyd_t07_wrong_item_identity_rejected_before_merge():
    data = bank(); data["search:1:" + ITEM]["items"][0]["itemCode"] = "echo-hydration:other"
    result, calls = run(data)
    assert len(calls) == 2 and result.hydration.outcomes[0].status == "identity_mismatch"
    assert result.logical_requests == 2
    assert len(result.observations) == 1 and not result.selected
    adapter, _ = provider(data)
    with pytest.raises(DiscoveryIdentityMismatch):
        adapter.discover(DiscoveryQuery(provider_item_id=ITEM), observed_at=DEMO_AS_OF)


@pytest.mark.parametrize("field,value,status", [("availability",0,"out_of_stock"),
    ("availability",None,"availability_unknown"),("itemPrice",None,"missing_exact_price")])
def test_hyd_t08_t09_failed_offer_cannot_fall_back_to_old_ranking(field,value,status):
    data = bank(); data["search:1:" + ITEM]["items"][0][field] = value
    result, calls = run(data)
    assert len(calls) == 2 and result.hydration.outcomes[0].status == status and not result.selected


def test_hyd_t10_simultaneously_applicable_price_difference_keeps_both_and_conflicts():
    data = bank(); data["search:1:" + ITEM]["items"][0]["itemPrice"] = 5000
    result, _ = run(data)
    c = result.candidates[0]
    assert {e.value_number for e in c.evidence if e.evidence_type == EvidenceType.PRICE} == {4500,5000}
    assert "current_evidence_conflict" in result.exclusions[c.product_id] and not result.selected


def test_hyd_t11_ranking_range_is_retained_without_exact_quote_search_supplies_price():
    data = bank(); data["ranking:1"]["items"][0]["hasPriceRange"] = 1
    result, _ = run(data)
    assert result.selected[0].offer.price.amount == 4500
    old = next(o for o in result.observations if o.source == DiscoverySource.RANKING)
    assert old.candidate.offer.price is None and "price_range_not_an_exact_offer_quote" in old.normalization_notes


def test_hyd_t12_explicit_historical_windows_do_not_poison_current_search():
    adapter, calls = provider()
    old = adapter.discover(RANKING, observed_at=DEMO_AS_OF)
    original = old.observations[0]
    records = tuple(e.model_copy(update={"valid_until":DEMO_AS_OF-timedelta(days=1),
        **({"value_number":Decimal(9999)} if e.evidence_type == EvidenceType.PRICE else {})})
        if e.evidence_type != EvidenceType.RANKING else e for e in original.candidate.evidence)
    candidate = original.candidate.model_copy(update={"evidence":records, "offer":original.candidate.offer.model_copy(
        update={"price":original.candidate.offer.price.model_copy(update={"amount":Decimal(9999)})})})
    historical = old.model_copy(update={"observations":(original.model_copy(update={"candidate":candidate}),)})
    class Pages:
        def discover(self,q,*,observed_at):
            return historical if q.source == DiscoverySource.RANKING else adapter.discover(q,observed_at=observed_at)
    result = discover_products(Pages(),(RANKING,),as_of=DEMO_AS_OF)
    c = result.selected[0]
    assert c.offer.price.amount == 4500 and len(result.observations) == 2
    assert any(e.value_number == 9999 for e in c.evidence if e.evidence_type == EvidenceType.PRICE)


def many(count=30):
    data = bank(); sample = data["ranking:1"]["items"][0]
    data["ranking:1"]["items"] = []
    for i in range(count):
        item = f"echo-hydration:item{i:02d}"
        row = {**copy.deepcopy(sample), "itemCode":item,"rank":i+1}
        data["ranking:1"]["items"].append(row)
        current = {**copy.deepcopy(row)}; current.pop("rank")
        data["search:1:"+item] = {"items":[current],"page":1,"pageCount":1,"count":1}
    return data


def test_hyd_b01_b02_thirty_rows_hydrate_only_fixed_top_five():
    result, calls = run(many())
    assert result.hydration.selected_count == result.hydration.requests == 5
    assert len(calls) == result.logical_requests == 6
    assert [dict(r.parameters)["itemCode"] for r in calls[1:]] == [f"echo-hydration:item{i:02d}" for i in range(5)]


def test_hyd_b03_duplicate_identity_and_reversed_input_do_not_duplicate_hydration():
    data = many(3); data["ranking:1"]["items"] += copy.deepcopy(data["ranking:1"]["items"])
    result, calls = run(data)
    data["ranking:1"]["items"].reverse()
    reversed_result, reversed_calls = run(data)
    assert len(calls) == len(reversed_calls) == 4 and result == reversed_result


@pytest.mark.parametrize("values", [{"ranking_hydration_top_k":0},{"ranking_hydration_top_k":6},
    {"max_hydration_requests":6},{"runtime_request_budget":9},{"ranking_hydration_top_k":5,"max_hydration_requests":4},
    {"runtime_request_budget":4},{"ranking_hydration_top_k":True},{"request_interval_seconds":0.5}])
def test_hyd_b04_invalid_configuration_rejected(values):
    with pytest.raises(ValidationError):DiscoveryPolicy(**values)


def test_hyd_b05_hard_logical_budget_stops_before_excess_request():
    adapter,calls = provider(many())
    policy = DiscoveryPolicy(ranking_hydration_top_k=2,max_hydration_requests=2,runtime_request_budget=2)
    with pytest.raises(ValueError,match="discovery_request_budget_exhausted"):
        discover_products(adapter,(RANKING,),as_of=DEMO_AS_OF,policy=policy)
    assert len(calls) == 2


def test_hyd_b06_wire_pacing_includes_retry_and_cached_hits_do_not_send():
    clock=[0.0];times=[];statuses=iter((429,200,200))
    def sleep(delay):clock[0]+=delay
    def sender(request,timeout,max_bytes):
        times.append(clock[0]);return HttpResponse(next(statuses),b'{}')
    endpoint=ENDPOINTS[DiscoverySource.SEARCH]
    transport=ReadOnlyHttpTransport(allowed_endpoints=frozenset({endpoint}),authorized=lambda:True,
        sender=sender,sleeper=sleep,clock=lambda:clock[0],minimum_interval=1)
    first=HttpRequest(endpoint,(("itemCode","synthetic:a"),),())
    second=HttpRequest(endpoint,(("itemCode","synthetic:b"),),())
    transport.fetch(first);transport.fetch(first);transport.fetch(second)
    assert times == [0.0,1.0,2.0]


def test_hyd_b07_not_found_does_not_replace_with_sixth_ranked_product():
    data=many();data.pop("search:1:echo-hydration:item00")
    result,calls=run(data)
    assert len(calls)==6 and result.hydration.requests==5
    assert result.hydration.outcomes[0].status=="not_found"
    assert all(dict(r.parameters).get("itemCode")!="echo-hydration:item05" for r in calls)


def test_current_search_skips_redundant_exact_hydration():
    adapter,calls=provider()
    q=DiscoveryQuery(provider_item_id=ITEM,limit=1)
    result=discover_products(adapter,(q,RANKING),as_of=DEMO_AS_OF)
    assert len(calls)==2 and result.hydration.requests==0 and result.hydration.skipped_current_search==1


def test_hydration_disabled_and_offline_fixture_cli_remains_safe():
    result,calls=run(policy=DiscoveryPolicy(ranking_hydration_enabled=False))
    assert len(calls)==1 and not result.selected
    output=CliRunner().invoke(app,["affiliate","discover","--source","ranking","--fixture",str(FIXTURE)])
    assert output.exit_code==0 and "selected=1" in output.stdout and "Hydration requests=1" in output.stdout
    assert "can_publish=false" in output.stdout


def test_malformed_hydration_transport_failure_stops_without_replacement():
    data=many();data["search:1:echo-hydration:item00"]["items"][0]["itemPrice"]=-1
    adapter,calls=provider(data)
    with pytest.raises(TransportError):discover_products(adapter,(RANKING,),as_of=DEMO_AS_OF)
    assert len(calls)==2


def test_memoized_acquisition_retains_distinct_intents_and_reverse_order():
    first=DiscoveryQuery(provider_item_id=ITEM,limit=1,category="lighting",lifestyle_context="reading corner",complementary_role="task lighting")
    second=DiscoveryQuery(provider_item_id=ITEM,limit=1,category="office",lifestyle_context="work desk",complementary_role="office lighting")
    adapter,calls=provider()
    forward=discover_products(adapter,(first,second),as_of=DEMO_AS_OF)
    adapter,reverse_calls=provider()
    reverse=discover_products(adapter,(second,first),as_of=DEMO_AS_OF)
    assert forward==reverse and len(calls)==len(reverse_calls)==forward.logical_requests==1
    assert {o.query.lifestyle_context for o in forward.observations}=={"reading corner","work desk"}
    assert {o.candidate.category for o in forward.observations}=={"lighting","office"}
    assert not forward.proposals and forward.bundle is None


def test_identity_mismatches_consume_budget_before_next_hydration():
    data=many(3)
    for key in list(data):
        if key.startswith("search:1:"):
            data[key]["items"][0]["itemCode"]="echo-hydration:mismatch"
    adapter,calls=provider(data)
    queries=tuple(DiscoveryQuery(keyword=f"synthetic{i}") for i in range(3))+(RANKING,)
    policy=DiscoveryPolicy(ranking_hydration_top_k=3,max_hydration_requests=3,runtime_request_budget=5)
    with pytest.raises(ValueError,match="discovery_request_budget_exhausted"):
        discover_products(adapter,queries,as_of=DEMO_AS_OF,policy=policy)
    assert len(calls)==5


def test_memoized_conflicting_intent_blocks_otherwise_valid_two_product_bundle():
    data=bank();fresh=copy.deepcopy(data["ranking:1"])
    fresh["lastBuildDate"]="Mon, 28 Sep 2026 12:00:00 +0000"
    other=copy.deepcopy(fresh)
    other["items"][0].update(itemCode="echo-hydration:chair",rank=2,genreId="990002")
    data["ranking:1:990001"]=fresh;data["ranking:1:990002"]=other
    lamp=DiscoveryQuery(source="ranking",category_id="990001",category="lighting",
        lifestyle_context="reading corner",complementary_role="task lighting")
    conflicting=lamp.model_copy(update={"lifestyle_context":"kitchen","complementary_role":"decoration"})
    chair=DiscoveryQuery(source="ranking",category_id="990002",category="furniture",
        lifestyle_context="reading corner",complementary_role="seating")
    adapter,control_calls=provider(data)
    control=discover_products(adapter,(lamp,chair),as_of=DEMO_AS_OF)
    assert len(control.selected)==2 and control.bundle is not None and len(control_calls)==2
    adapter,calls=provider(data)
    result=discover_products(adapter,(lamp,conflicting,chair),as_of=DEMO_AS_OF)
    adapter,reverse_calls=provider(data)
    reverse=discover_products(adapter,(chair,conflicting,lamp),as_of=DEMO_AS_OF)
    assert result==reverse and len(result.selected)==2
    assert len(calls)==len(reverse_calls)==result.logical_requests==2
    assert result.bundle is None and result.bundle_notes and not result.can_publish
