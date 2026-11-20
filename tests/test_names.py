"""Tests for cleaning up intervention names."""
import pytest

from app.names import (DRUG, NON_DRUG, PLACEBO, STANDARD_OF_CARE, candidate_names, name_key, role_of,
                       split_agents)


@pytest.mark.parametrize("raw, expected", [
    ("Pembrolizumab 200 mg", ["Pembrolizumab"]),
    ("AZD9291 80 mg/40 mg + placebo", ["AZD9291", "placebo"]),
    ("Ivonescimab Dose 1", ["Ivonescimab"]),
    ("Ivonescimab RP3D", ["Ivonescimab"]),
    ("Erlotinib 150/100 mg", ["Erlotinib"]),
    ("Carboplatin AUC 5", ["Carboplatin"]),
    ("Paclitaxel 175 mg/m2", ["Paclitaxel"]),
    ("Datopotamab deruxtecan 6 mg/kg IV Q3W", ["Datopotamab deruxtecan"]),
    ("SHR-A1811 for injection", ["SHR-A1811"]),
    ("CAR-T cells 1x10^6 cells/kg", ["CAR-T cells"]),
    ("Nivolumab and Ipilimumab", ["Nivolumab", "Ipilimumab"]),
    ("BNT162b2 30 µg", ["BNT162b2"]),
    ("177Lu-PSMA-617", ["177Lu-PSMA-617"]),
])
def test_split_agents(raw, expected):
    assert split_agents(raw) == expected


def test_parenthetical_aliases():
    assert candidate_names("Trastuzumab deruxtecan (T-DXd)") == ["Trastuzumab deruxtecan", "T-DXd"]
    parts = split_agents("Pembrolizumab (MK-3475) 200 mg IV Q3W")
    assert candidate_names(parts[0]) == ["Pembrolizumab", "MK-3475"]


def test_parentheses_are_not_split():
    assert split_agents("Nivolumab (with or without ipilimumab)") == ["Nivolumab (with or without ipilimumab)"]


def test_name_key():
    assert name_key("DS-8201a") == name_key("DS 8201a") == "ds8201a"
    assert name_key("Ivonescimab") == name_key("IVONESCIMAB")


@pytest.mark.parametrize("text, itype, role", [
    ("Placebo", "DRUG", PLACEBO),
    ("Placebo Erlotinib", "DRUG", PLACEBO),
    ("Saline", "DRUG", PLACEBO),
    ("Standard of care", "OTHER", STANDARD_OF_CARE),
    ("Investigator's choice chemotherapy", "DRUG", STANDARD_OF_CARE),
    ("Platinum-based chemotherapy", "DRUG", STANDARD_OF_CARE),
    ("Best supportive care", "OTHER", STANDARD_OF_CARE),
    ("Radiotherapy", "RADIATION", NON_DRUG),
    ("Surgery", "PROCEDURE", NON_DRUG),
    ("Folic acid", "DIETARY_SUPPLEMENT", NON_DRUG),
    ("Pembrolizumab", "BIOLOGICAL", DRUG),
    ("Docetaxel", "DRUG", DRUG),
])
def test_roles(text, itype, role):
    assert role_of(text, itype) == role


@pytest.mark.parametrize("raw, expected", [
    ("AMG 386 with or without Trastuzumab", ["AMG 386", "Trastuzumab"]),
    ("Carboplatin/Cisplatin + Pemetrexed", ["Carboplatin", "Cisplatin", "Pemetrexed"]),
    ("irinotecan liposome", ["irinotecan"]),
    ("Paclitaxel Polymeric Micelles", ["Paclitaxel"]),
    ("nab-paclitaxel", ["paclitaxel"]),
    ("Ivonescimab,TAS-102", ["Ivonescimab", "TAS-102"]),
    ("AK112+AK104 group", ["AK112", "AK104"]),
    ("Docetaxel +/- ramucirumab", ["Docetaxel", "ramucirumab"]),
])
def test_split_agents_messier_cases(raw, expected):
    assert split_agents(raw) == expected


def test_fullwidth_punctuation():
    assert candidate_names(split_agents("Ivonescimab（AK112，a PD-1/VEGF bispecific antibody）")[0])[:2] == [
        "Ivonescimab", "AK112"]


@pytest.mark.parametrize("text", ["SCRT", "Questionnaire Administration", "Non-operative Management",
                                  "second-line group", "HAIC"])
def test_non_drug_phrases(text):
    assert role_of(text, "DRUG") == NON_DRUG


def test_code_variants():
    from app.names import code_variants
    assert code_variants("AMG 386") == ["AMG-386", "AMG386"]
    assert code_variants("pembrolizumab") == []
