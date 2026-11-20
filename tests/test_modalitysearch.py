"""Tests for searching by modality (offline: ClinicalTrials.gov, ChEMBL and the web are faked)."""
import pytest

from app import chembl, modalitysearch, weblookup
from app import taxonomy as T
from app.ctgov import CTGovError, SearchQuery
from app.modalitysearch import TARGETS_BY_LABEL, known_drug_names, or_batches, search_modality

ADC = TARGETS_BY_LABEL["Antibody-drug conjugate (ADC)"]
CAR_T = TARGETS_BY_LABEL["Cell therapy: CAR-T"]
MAB = TARGETS_BY_LABEL["Monoclonal antibody"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(chembl, "lookup", lambda name, client=None: None)
    monkeypatch.setattr(weblookup, "lookup", lambda name, client=None: None)
    monkeypatch.setattr(modalitysearch, "chembl_drugs", lambda t: ["disitamab vedotin", "SHR-A1811"])


def raw(nct_id, *interventions, arms=None):
    """interventions: (name, description) pairs; one experimental arm with all of them unless arms given."""
    ivs = [{"type": "DRUG", "name": n, "description": d} for n, d in interventions]
    groups = arms or [{"label": "A", "type": "EXPERIMENTAL", "interventionNames": [f"Drug: {n}" for n, _ in interventions]}]
    return {"protocolSection": {"identificationModule": {"nctId": nct_id, "briefTitle": nct_id},
                                "armsInterventionsModule": {"interventions": ivs, "armGroups": groups}}}


def fake_site(by_term):
    calls = []

    def run(q: SearchQuery, n):
        calls.append(q)
        hits = []
        for term, studies in by_term.items():
            if term.lower() in q.intervention.lower():
                hits += studies
        return hits, len(hits)
    return run, calls


def test_known_drug_names_include_curated_and_chembl():
    names = known_drug_names(ADC)
    assert "trastuzumab deruxtecan" in names and "T-DXd" in names       # curated + synonyms
    assert "disitamab vedotin" in names and "SHR-A1811" in names         # ChEMBL list (faked)
    assert "pembrolizumab" not in names


def test_or_batches_quote_and_split():
    batches = or_batches(["trastuzumab deruxtecan", "T-DXd", "osimertinib"] * 50, limit=200)
    assert len(batches) > 1
    assert batches[0].startswith('"trastuzumab deruxtecan" OR "T-DXd" OR osimertinib')
    assert all(len(b) <= 200 for b in batches)


def test_confirmed_possible_and_excluded():
    run, calls = fake_site({
        "trastuzumab deruxtecan": [raw("NCT1", ("Trastuzumab deruxtecan", ""))],
        "adc": [
            raw("NCT1", ("Trastuzumab deruxtecan", "")),                           # duplicate: merged
            raw("NCT2", ("XYZ-123", "XYZ-123 is a novel anti-B7-H3 ADC")),        # unknown, described as ADC
            raw("NCT3", ("XYZ-999", "a new drug")),                               # unknown, no ADC wording
            raw("NCT4", ("Pembrolizumab", "")),                                    # known, not an ADC
        ],
    })
    r = search_modality(ADC, SearchQuery(condition="breast cancer"), search_fn=run)
    assert [tm.trial.nct_id for tm in r.confirmed] == ["NCT1"]
    assert [tm.trial.nct_id for tm in r.possible] == ["NCT2"]
    assert all(q.condition == "breast cancer" for q in calls)                # narrowing passed through
    assert any("ADC" in q.intervention for q in calls)                        # keyword search ran


def test_experimental_arm_vs_any_arm():
    study = raw("NCT5", ("Pembrolizumab", ""), ("Trastuzumab deruxtecan", ""), arms=[
        {"label": "A", "type": "EXPERIMENTAL", "interventionNames": ["Drug: Pembrolizumab"]},
        {"label": "B", "type": "ACTIVE_COMPARATOR", "interventionNames": ["Drug: Trastuzumab deruxtecan"]},
    ])
    run, _ = fake_site({"deruxtecan": [study]})
    assert search_modality(ADC, search_fn=run).confirmed == []
    assert [tm.trial.nct_id for tm in search_modality(ADC, any_arm=True, search_fn=run).confirmed] == ["NCT5"]


def test_sub_type_target():
    run, _ = fake_site({"car": [raw("NCT6", ("Tisagenlecleucel", "")), raw("NCT7", ("Lifileucel", ""))],
                        "tisagenlecleucel": [raw("NCT6", ("Tisagenlecleucel", ""))]})
    r = search_modality(CAR_T, search_fn=run)
    assert [tm.trial.nct_id for tm in r.confirmed] == ["NCT6"]               # TIL therapy is not CAR-T


def test_broad_modality_needs_narrowing():
    with pytest.raises(CTGovError, match="too many trials"):
        search_modality(MAB, SearchQuery(phases=["PHASE3"]))
    run, calls = fake_site({"": [raw("NCT8", ("Pembrolizumab", "")), raw("NCT9", ("Osimertinib", ""))]})
    r = search_modality(MAB, SearchQuery(condition="lung cancer"), search_fn=run)
    assert [tm.trial.nct_id for tm in r.confirmed] == ["NCT8"]
    assert len(calls) == 1 and calls[0].intervention == ""


def test_every_target_is_in_the_taxonomy():
    for t in modalitysearch.TARGETS:
        assert t.modality in T.MODALITIES
        assert t.keywords or t.broad or t.chembl_type
