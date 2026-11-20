"""Tests for the synonym-merged drug search (offline: the website is faked)."""
import pytest

from app import chembl
from app.ctgov import SearchQuery
from app.drugsearch import learn_code_names, name_patterns, search_drug, trial_has_drug
from app.trial import Intervention, Trial


def raw(nct_id, *interventions):
    """A minimal raw trial; each intervention is (name, [other names])."""
    return {"protocolSection": {
        "identificationModule": {"nctId": nct_id, "briefTitle": nct_id},
        "armsInterventionsModule": {"interventions": [
            {"type": "DRUG", "name": n, "otherNames": o} for n, o in interventions]},
    }}


@pytest.fixture(autouse=True)
def no_chembl(monkeypatch):
    monkeypatch.setattr(chembl, "lookup", lambda name, client=None: None)


def fake_site(db):
    """db: search name (lower-case) -> list of raw trials. Records which names were searched."""
    searched = []

    def run(query: SearchQuery, n):
        searched.append((query.intervention, query.condition))
        studies = db.get(query.intervention.lower(), [])
        return studies, len(studies)
    return run, searched


def test_merges_synonyms_and_deduplicates():
    db = {
        "ivonescimab": [raw("NCT1", ("Ivonescimab Dose 1", [])), raw("NCT2", ("Ivonescimab", ["AK112"]))],
        "ak112": [raw("NCT2", ("Ivonescimab", ["AK112"])), raw("NCT3", ("AK112", []))],
        "smt112": [raw("NCT4", ("SMT112", []))],
    }
    run, searched = fake_site(db)
    r = search_drug("ivonescimab", search_fn=run)
    assert r.display_name == "ivonescimab"
    assert sorted(t.nct_id for t in r.trials) == ["NCT1", "NCT2", "NCT3", "NCT4"]
    assert [s for s, _ in searched][:3] == ["ivonescimab", "AK112", "SMT112"]


def test_code_name_finds_curated_drug():
    run, searched = fake_site({"ak112": [raw("NCT3", ("AK112", []))]})
    r = search_drug("AK112", search_fn=run)
    assert r.display_name == "ivonescimab"
    assert "ivonescimab" in [s for s, _ in searched]


def test_drops_other_drugs_and_text_only_mentions():
    db = {
        "t-dxd": [
            raw("NCT1", ("Trastuzumab deruxtecan (T-DXd)", [])),
            raw("NCT2", ("Datopotamab deruxtecan (Dato-DXd)", [])),     # different ADC
            raw("NCT3", ("Trastuzumab (Herceptin)", [])),               # different drug
            raw("NCT4", ("Ifinatamab Deruxtecan (I-DXd)", [])),
        ],
    }
    run, _ = fake_site(db)
    r = search_drug("T-DXd", search_fn=run)
    assert [t.nct_id for t in r.trials] == ["NCT1"]
    assert sorted(t.nct_id for t in r.dropped) == ["NCT2", "NCT3", "NCT4"]


def test_matches_messy_intervention_text():
    patterns = name_patterns(["ivonescimab", "AK112"])
    for name in ["Ivonescimab（AK112，a PD-1/VEGF bispecific antibody）", "Ivonescimab,TAS-102",
                 "Anti-PD-1/VEGF Bispecific Antibody AK112", "AK112 with SCRT and CapeOX"]:
        assert trial_has_drug(Trial("N", "t", interventions=[Intervention("DRUG", name)]), patterns), name
    assert not trial_has_drug(Trial("N", "t", interventions=[Intervention("DRUG", "AK1120")]), patterns)


def test_passes_other_filters_through():
    run, searched = fake_site({})
    search_drug("ivonescimab", SearchQuery(condition="lung cancer", phases=["PHASE3"]), search_fn=run)
    assert all(cond == "lung cancer" for _, cond in searched)


def test_learns_code_names_seen_in_two_trials_only():
    trials = [
        Trial("NCT1", "t", interventions=[Intervention("DRUG", "Fooximab", other_names=["FX-101", "Akeso"])]),
        Trial("NCT2", "t", interventions=[Intervention("DRUG", "Fooximab", other_names=["FX-101", "Standard of care"])]),
        Trial("NCT3", "t", interventions=[Intervention("DRUG", "Fooximab", other_names=["ZZ-9"])]),
    ]
    learned = learn_code_names(trials, {"fooximab"}, name_patterns(["fooximab"]), online=False)
    assert learned == ["FX-101"]          # not "Akeso" (no digit), not "ZZ-9" (one trial only)


def test_short_names_are_not_searched():
    run, searched = fake_site({})
    search_drug("enfortumab vedotin", search_fn=run)
    assert "EV" not in [s for s, _ in searched]


@pytest.mark.live
def test_live_ivonescimab_finds_ak112_only_trials(monkeypatch):
    monkeypatch.undo()                       # use the real ChEMBL for this one
    from app.ctgov import search_studies
    one_name, _ = search_studies(SearchQuery(intervention="ivonescimab"), max_results=1000)
    r = search_drug("ivonescimab")
    assert len(r.trials) > len(one_name) + 20          # AK112-only trials are now included
    assert "AK112" in r.searched
