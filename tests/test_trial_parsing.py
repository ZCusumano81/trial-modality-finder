"""Parsing tests using saved copies of four real trials (tests/fixtures/*.json).

These run offline, so they're fast and don't break if the website is slow.
"""
import json
from pathlib import Path

import pytest

from app.trial import Trial, parse_study

FIXTURES = Path(__file__).parent / "fixtures"


def load(nct_id: str) -> Trial:
    return parse_study(json.loads((FIXTURES / f"{nct_id}.json").read_text()))


def test_keynote_189_combination_with_no_sites():
    t = load("NCT02578680")
    assert t.nct_id == "NCT02578680"
    assert "Pembrolizuma" in t.title
    assert t.sponsor == "Merck Sharp & Dohme LLC"
    assert t.status == "COMPLETED"
    assert t.phase_label == "Phase 3"
    names = [i.name for i in t.interventions]
    assert "Pembrolizumab 200 mg" in names and "Pemetrexed" in names
    assert t.sites == []                       # this record lists no sites
    assert len(t.arm_groups) >= 2


def test_destiny_breast03_adc_vs_adc():
    t = load("NCT03529110")
    assert t.sponsor == "Daiichi Sankyo"
    assert [i.name for i in t.interventions] == [
        "Trastuzumab deruxtecan (T-DXd)", "Ado-trastuzumab emtansine (T-DM1)",
    ]
    countries = {s.country for s in t.sites}
    assert {"China", "Hong Kong", "Taiwan", "United States"} <= countries
    assert len(t.sites) == 164


def test_flaura_placebos_are_kept_as_interventions():
    t = load("NCT02296125")
    assert t.sponsor == "AstraZeneca"
    assert any("Placebo" in i.name for i in t.interventions)


def test_harmoni_2_china_only():
    t = load("NCT05499390")
    assert t.sponsor == "Akeso"
    assert t.status_label == "Active, not recruiting"
    assert [s.country for s in t.sites] == ["China"]
    arms = {a.label: a for a in t.arm_groups}
    assert arms["AK112"].type == "EXPERIMENTAL"
    assert arms["AK112"].intervention_names == ["Drug: AK112"]


def test_missing_fields_do_not_crash():
    t = parse_study({"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}})
    assert t.nct_id == "NCT00000001"
    assert t.title == "(no title)"
    assert t.phases == [] and t.phase_label == "Not stated"
    assert t.status_label == "Unknown"
    assert t.interventions == [] and t.arm_groups == [] and t.sites == []


def test_interventions_without_names_are_skipped():
    raw = {"protocolSection": {
        "identificationModule": {"nctId": "NCT00000002", "briefTitle": "x"},
        "armsInterventionsModule": {"interventions": [{"type": "DRUG"}, {"type": "DRUG", "name": " Drug A "}]},
    }}
    assert [i.name for i in parse_study(raw).interventions] == ["Drug A"]


@pytest.mark.parametrize("phases, label", [
    (["PHASE2", "PHASE3"], "Phase 2/3"),
    (["PHASE1", "PHASE2"], "Phase 1/2"),
    (["EARLY_PHASE1"], "Early Phase 1"),
    (["NA"], "Not applicable"),
])
def test_phase_labels(phases, label):
    assert Trial(nct_id="X", title="x", phases=phases).phase_label == label
