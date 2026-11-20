"""Tests for the lookup order: curated table -> ChEMBL -> name rules -> web -> pending.

ChEMBL and the web are replaced with fakes so these run offline and predictably.
Tests marked "live" use the real services.
"""
import pytest

from app import chembl, modality, weblookup
from app import taxonomy as T
from app.chembl import ChemblHit
from app.curated import CuratedTable
from app.modality import classify_agent, classify_intervention
from app.trial import Intervention
from app.weblookup import WebHit


@pytest.fixture
def fake_sources(monkeypatch):
    """Fake ChEMBL and web answers, keyed by lower-case name."""
    chembl_db: dict[str, ChemblHit] = {}
    web_db: dict[str, WebHit] = {}
    calls = {"chembl": [], "web": []}

    def fake_chembl(name, client=None):
        calls["chembl"].append(name)
        return chembl_db.get(name.lower())

    def fake_web(name, client=None):
        calls["web"].append(name)
        return web_db.get(name.lower())

    monkeypatch.setattr(chembl, "lookup", fake_chembl)
    monkeypatch.setattr(weblookup, "lookup", fake_web)
    return chembl_db, web_db, calls


def test_curated_table_has_all_columns_and_33_drugs():
    table = CuratedTable.load()
    assert len(table.entries) >= 30
    assert {e.modality for e in table.entries} >= set(T.MODALITIES) - {T.UNKNOWN}


def test_curated_wins_and_matches_synonyms(fake_sources):
    _, _, calls = fake_sources
    call = classify_agent("AK112", ["AK112"])
    assert call.name == "ivonescimab"
    assert call.modality == T.BISPECIFIC and call.source == "curated"
    assert calls["chembl"] == []                       # no need to ask ChEMBL


def test_chembl_synonym_leads_back_to_curated(fake_sources):
    chembl_db, _, _ = fake_sources
    chembl_db["sch-900475"] = ChemblHit("CHEMBL3137343", "PEMBROLIZUMAB", "Antibody", ["Keytruda"])
    call = classify_agent("SCH-900475x", ["SCH-900475"])
    assert call.name == "pembrolizumab" and call.source == "curated"


def test_chembl_answer(fake_sources):
    chembl_db, _, _ = fake_sources
    chembl_db["gefitinib"] = ChemblHit("CHEMBL939", "GEFITINIB", "Small molecule", ["Iressa"])
    call = classify_agent("Gefitinib 250 mg", ["Gefitinib"])
    assert (call.name, call.modality, call.source, call.confidence) == (
        "gefitinib", T.SMALL_MOLECULE, "chembl", "medium")
    assert "Iressa" in call.synonyms


def test_name_rule_refines_broad_chembl(fake_sources):
    chembl_db, _, _ = fake_sources
    chembl_db["foozumab vedotin"] = ChemblHit("CHEMBL1", "FOOZUMAB VEDOTIN", "Antibody", [])
    call = classify_agent("x", ["foozumab vedotin"])
    assert call.modality == T.ADC and call.source == "chembl + name rule"


def test_web_refines_broad_antibody(fake_sources):
    chembl_db, web_db, _ = fake_sources
    chembl_db["barmab"] = ChemblHit("CHEMBL2", "BARMAB", "Antibody", [])
    web_db["barmab"] = WebHit(T.BISPECIFIC, "", "wikipedia", "Barmab is a bispecific antibody.", "u")
    call = classify_agent("Barmab", ["Barmab"])
    assert call.modality == T.BISPECIFIC
    assert call.source == "chembl + wikipedia" and call.confidence == "low"


def test_web_does_not_override_specific_chembl(fake_sources):
    chembl_db, web_db, calls = fake_sources
    chembl_db["bazinib"] = ChemblHit("CHEMBL3", "BAZINIB", "Small molecule", [])
    call = classify_agent("Bazinib", ["Bazinib"])
    assert call.modality == T.SMALL_MOLECULE
    assert calls["web"] == []                          # web only asked when needed


def test_name_rule_when_nothing_else(fake_sources):
    call = classify_agent("Quxtinib", ["Quxtinib"])
    assert call.modality == T.SMALL_MOLECULE and call.source == "name rule" and call.confidence == "low"


def test_web_when_nothing_else(fake_sources):
    _, web_db, _ = fake_sources
    web_db["ab-123"] = WebHit(T.ADC, "", "wikipedia", "AB-123 is an antibody-drug conjugate.", "u", "Zapotamab")
    call = classify_agent("AB-123", ["AB-123"])
    assert call.modality == T.ADC and call.source == "wikipedia"
    assert call.name == "zapotamab"


def test_pending_review(fake_sources):
    call = classify_agent("XYZ-99999", ["XYZ-99999"])
    assert call.pending and call.modality == T.PENDING
    assert call.short_label == "pending review"


def test_offline_mode_skips_web_services(fake_sources):
    _, _, calls = fake_sources
    call = classify_agent("Quxtinib", ["Quxtinib"], online=False)
    assert call.source == "name rule"
    assert calls == {"chembl": [], "web": []}


def test_intervention_with_placebo_and_other_names(fake_sources):
    calls = classify_intervention(Intervention("DRUG", "AZD9291 80 mg/40 mg + placebo"))
    assert [(c.name, c.role) for c in calls] == [("osimertinib", "drug"), ("placebo", "placebo")]
    assert calls[1].modality == T.NOT_CLASSIFIED

    calls = classify_intervention(Intervention("DRUG", "Study drug X", other_names=["Ivonescimab"]))
    assert calls[0].name == "ivonescimab"


# ---- live ----

@pytest.mark.live
@pytest.mark.parametrize("name, expected", [
    ("cisplatin", T.SMALL_MOLECULE),
    ("disitamab vedotin", T.ADC),
    ("tarlatamab", T.BISPECIFIC),
    ("lisocabtagene maraleucel", T.CELL_THERAPY),
    ("olezarsen", T.OLIGONUCLEOTIDE),
])
def test_live_lookups(name, expected):
    assert classify_agent(name, [name], table=CuratedTable([])).modality == expected
