"""Tests for arm-by-arm combinations and labels (offline, using saved real trials)."""
import json
from pathlib import Path

import pytest

from app import chembl, taxonomy as T, weblookup
from app.combos import analyze_trial
from app.trial import ArmGroup, Intervention, Trial, parse_study

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(chembl, "lookup", lambda name, client=None: None)
    monkeypatch.setattr(weblookup, "lookup", lambda name, client=None: None)


def load(nct_id):
    return parse_study(json.loads((FIXTURES / f"{nct_id}.json").read_text()))


def test_harmoni_2_arms():
    tm = analyze_trial(load("NCT05499390"))
    labels = {a.label: a.combination_label for a in tm.arms}
    assert labels == {"AK112": "PD-1/VEGF bispecific", "Pembrolizumab": "PD-1 mAb"}
    assert tm.combination_label == "PD-1/VEGF bispecific"           # experimental arm only
    assert tm.modalities == [T.BISPECIFIC, T.MAB]                    # all arms
    assert tm.experimental_modalities == [T.BISPECIFIC]


def test_destiny_breast03_adc_vs_adc():
    tm = analyze_trial(load("NCT03529110"))
    assert tm.combination_label == "HER2 ADC"
    assert {d.name for d in tm.drugs} == {"trastuzumab deruxtecan", "trastuzumab emtansine"}


def test_flaura_placebo_tagged_not_classified():
    tm = analyze_trial(load("NCT02296125"))
    exp = tm.experimental_arms[0]
    assert [d.name for d in exp.drugs] == ["osimertinib"]
    assert "placebo" in exp.tags
    assert exp.combination_label == "EGFR small molecule (+ placebo)"
    assert all(a.is_drug or a.modality == T.NOT_CLASSIFIED for a in tm.all_agents)


def test_keynote_189_combination():
    tm = analyze_trial(load("NCT02578680"))
    exp = tm.experimental_arms[0]
    names = [d.name for d in exp.drugs]
    assert names[0] == "pembrolizumab"                               # mAb sorts before small molecules
    assert "cisplatin" in names and "carboplatin" in names           # "-platin" name rule offline
    assert exp.is_combination
    assert exp.combination_label.startswith("PD-1 mAb + small molecule")
    assert "non-drug" in exp.tags                                    # folic acid / vitamin B12


def test_label_sorted_by_modality():
    t = Trial("N", "t",
              interventions=[Intervention("DRUG", "Pembrolizumab"), Intervention("DRUG", "Enfortumab vedotin")],
              arm_groups=[ArmGroup("A", "EXPERIMENTAL", intervention_names=["Drug: Pembrolizumab",
                                                                            "Drug: Enfortumab vedotin"])])
    assert analyze_trial(t).combination_label == "Nectin-4 ADC + PD-1 mAb"


def test_no_arm_groups_uses_all_interventions():
    t = Trial("N", "t", interventions=[Intervention("DRUG", "Ivonescimab"), Intervention("DRUG", "Placebo")])
    tm = analyze_trial(t)
    assert tm.combination_label == "PD-1/VEGF bispecific (+ placebo)"


def test_several_experimental_arms_are_joined():
    t = Trial("N", "t",
              interventions=[Intervention("DRUG", "Ivonescimab"), Intervention("DRUG", "Trastuzumab deruxtecan")],
              arm_groups=[ArmGroup("A", "EXPERIMENTAL", intervention_names=["Drug: Ivonescimab"]),
                          ArmGroup("B", "EXPERIMENTAL", intervention_names=["Drug: Trastuzumab deruxtecan"])])
    assert analyze_trial(t).combination_label == "PD-1/VEGF bispecific | HER2 ADC"


def test_pending_is_flagged():
    t = Trial("N", "t", interventions=[Intervention("DRUG", "XYZ-99999")])
    tm = analyze_trial(t)
    assert tm.has_pending and tm.combination_label == "pending review"
