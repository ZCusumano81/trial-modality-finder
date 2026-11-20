"""Tests for fetching from ClinicalTrials.gov.

Most use a fake website (httpx.MockTransport) so we can test errors and paging
on demand. Tests marked "live" really call ClinicalTrials.gov; skip them with
`uv run pytest -m "not live"` when offline.
"""
import httpx
import pytest

from app import ctgov
from app.ctgov import CTGovError, SearchQuery, get_study, normalize_nct_id, search_studies
from app.trial import parse_study


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(ctgov.time, "sleep", lambda s: None)


def fake_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def study(nct_id):
    return {"protocolSection": {"identificationModule": {"nctId": nct_id, "briefTitle": nct_id}}}


# ---- input handling ----

def test_normalize_nct_id():
    assert normalize_nct_id("  nct02578680 ") == "NCT02578680"
    with pytest.raises(CTGovError, match="not a valid NCT ID"):
        normalize_nct_id("NCT123")


def test_search_params():
    q = SearchQuery(text="lung", intervention="ivonescimab", statuses=["RECRUITING", "COMPLETED"],
                    phases=["PHASE2", "PHASE3"], nct_ids=["nct05499390"])
    assert q.to_params() == {
        "query.term": "lung",
        "query.intr": "ivonescimab",
        "filter.overallStatus": "RECRUITING|COMPLETED",
        "filter.advanced": "AREA[Phase]PHASE2 OR AREA[Phase]PHASE3",
        "filter.ids": "NCT05499390",
    }


def test_empty_search_is_refused():
    with pytest.raises(CTGovError, match="at least one"):
        search_studies(SearchQuery(text="   "))


# ---- paging ----

def test_search_follows_page_tokens():
    pages = {
        None: {"totalCount": 3, "studies": [study("NCT00000001"), study("NCT00000002")], "nextPageToken": "p2"},
        "p2": {"studies": [study("NCT00000003")]},
    }
    seen = []

    def handler(request):
        token = request.url.params.get("pageToken")
        seen.append(token)
        return httpx.Response(200, json=pages[token])

    studies, total = search_studies(SearchQuery(text="x"), client=fake_client(handler))
    assert total == 3
    assert [s["protocolSection"]["identificationModule"]["nctId"] for s in studies] == [
        "NCT00000001", "NCT00000002", "NCT00000003"]
    assert seen == [None, "p2"]


def test_search_stops_at_max_results():
    def handler(request):
        return httpx.Response(200, json={"totalCount": 500, "studies": [study("NCT00000001")] * 2,
                                         "nextPageToken": "more"})

    studies, total = search_studies(SearchQuery(text="x"), max_results=3, client=fake_client(handler))
    assert len(studies) == 3 and total == 500


# ---- errors ----

def test_retries_after_rate_limit():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json=study("NCT05499390"))

    assert get_study("NCT05499390", client=fake_client(handler))
    assert len(calls) == 3


def test_gives_up_after_repeated_rate_limits():
    client = fake_client(lambda r: httpx.Response(429))
    with pytest.raises(CTGovError, match="busy"):
        get_study("NCT05499390", client=client)


def test_not_found():
    client = fake_client(lambda r: httpx.Response(404))
    with pytest.raises(CTGovError, match="No trial with that ID"):
        get_study("NCT99999999", client=client)


def test_server_error():
    client = fake_client(lambda r: httpx.Response(500))
    with pytest.raises(CTGovError, match="code 500"):
        get_study("NCT05499390", client=client)


def test_no_internet():
    def handler(request):
        raise httpx.ConnectError("offline")

    with pytest.raises(CTGovError, match="internet connection"):
        get_study("NCT05499390", client=fake_client(handler))


# ---- live (real website) ----

@pytest.mark.live
def test_live_get_study():
    t = parse_study(get_study("NCT03529110"))
    assert t.sponsor == "Daiichi Sankyo"
    assert t.phase_label == "Phase 3"
    assert any("deruxtecan" in i.name.lower() for i in t.interventions)


@pytest.mark.live
def test_live_search_with_filters():
    studies, total = search_studies(
        SearchQuery(intervention="ivonescimab", phases=["PHASE3"]), max_results=5)
    assert total >= 1 and studies
    for raw in studies:
        assert "PHASE3" in parse_study(raw).phases


@pytest.mark.live
def test_live_missing_trial():
    with pytest.raises(CTGovError, match="No trial with that ID"):
        get_study("NCT99999999")
