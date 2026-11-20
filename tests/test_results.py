"""Tests for the results table, filters, exports and the web page."""
import io
import json
from pathlib import Path

import openpyxl
import pytest

from app import chembl, weblookup
from app import taxonomy as T
from app.combos import analyze_trial
from app.pipeline import analyze_all
from app.results import Filters, agents_table, filter_trials, to_csv, to_excel, trials_table
from app.trial import Intervention, parse_study

FIXTURES = Path(__file__).parent / "fixtures"
IDS = ["NCT02578680", "NCT03529110", "NCT02296125", "NCT05499390"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(chembl, "lookup", lambda name, client=None: None)
    monkeypatch.setattr(weblookup, "lookup", lambda name, client=None: None)


@pytest.fixture
def analyses():
    trials = [parse_study(json.loads((FIXTURES / f"{i}.json").read_text())) for i in IDS]
    return analyze_all(trials, online=False)


def ids(rows):
    return [tm.trial.nct_id for tm, _ in rows]


def test_analyze_all_keeps_order(analyses):
    assert [tm.trial.nct_id for tm in analyses] == IDS


def test_filters(analyses):
    assert ids(filter_trials(analyses, Filters())) == IDS
    assert ids(filter_trials(analyses, Filters(site_flags=["China-only"]))) == ["NCT05499390"]
    assert ids(filter_trials(analyses, Filters(site_flags=["No sites listed"]))) == ["NCT02578680"]
    assert ids(filter_trials(analyses, Filters(contains_modalities=[T.ADC]))) == ["NCT03529110"]
    # HARMONi-2 has a mAb only in its comparator arm:
    assert "NCT05499390" in ids(filter_trials(analyses, Filters(contains_modalities=[T.MAB])))
    assert "NCT05499390" not in ids(filter_trials(analyses, Filters(experimental_modalities=[T.MAB])))
    assert ids(filter_trials(analyses, Filters(experimental_modalities=[T.BISPECIFIC]))) == ["NCT05499390"]
    assert ids(filter_trials(analyses, Filters(combinations_only=True))) == ["NCT02578680"]


def test_contains_needs_all_selected_modalities(analyses):
    rows = filter_trials(analyses, Filters(contains_modalities=[T.MAB, T.SMALL_MOLECULE]))
    assert ids(rows) == ["NCT02578680"]


def test_tables(analyses):
    rows = filter_trials(analyses, Filters())
    trials = trials_table(rows)
    assert list(trials["NCT ID"]) == IDS
    h2 = trials.set_index("NCT ID").loc["NCT05499390"]
    assert h2["Combination (experimental)"] == "PD-1/VEGF bispecific"
    assert h2["Site flag"] == "China-only" and h2["Sites"] == 1
    agents = agents_table(rows)
    iv = agents[(agents["NCT ID"] == "NCT05499390") & (agents["Agent"] == "ivonescimab")].iloc[0]
    assert iv["Source"] == "curated" and iv["Modality"] == T.BISPECIFIC and iv["Arms"] == "AK112"
    assert set(agents.columns) >= {"Evidence", "Confidence", "Role", "Intervention as written"}


def test_exports(analyses):
    rows = filter_trials(analyses, Filters())
    trials, agents = trials_table(rows), agents_table(rows)
    assert to_csv(trials).decode("utf-8-sig").startswith("NCT ID,Link,Title")
    wb = openpyxl.load_workbook(io.BytesIO(to_excel(trials, agents, "drug: test")))
    assert wb.sheetnames == ["Trials", "Agents", "About"]
    assert wb["Trials"].max_row == len(IDS) + 1
    assert "ChEMBL" in str(wb["About"]["A4"].value)


def test_empty_results_export():
    trials, agents = trials_table([]), agents_table([])
    assert trials.empty and "NCT ID" in trials.columns
    assert openpyxl.load_workbook(io.BytesIO(to_excel(trials, agents))).sheetnames[0] == "Trials"


def test_other_names_are_only_a_fallback():
    # NCT07228832 lists the chemo partners as "other names" of ivonescimab.
    from app.modality import classify_intervention
    calls = classify_intervention(Intervention("DRUG", "Drug: Ivonescimab Injection",
                                               other_names=["Oxaliplatin", "Leucovorin"]), online=False)
    assert [c.name for c in calls] == ["ivonescimab"]
    calls = classify_intervention(Intervention("DRUG", "XYZ-1", other_names=["Ivonescimab"]), online=False)
    assert calls[0].name == "ivonescimab" and calls[0].confidence == "low"
    assert "other names" in calls[0].evidence


# ---- the web page itself (live: runs a real search) ----

@pytest.mark.live
def test_live_page_search():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).parent.parent / "streamlit_app.py"), default_timeout=300)
    at.run()
    assert not at.exception
    at.text_input(key="q_drug").set_value("ivonescimab")
    at.multiselect(key="q_phase").set_value(["PHASE3"])
    at.button[0].click()
    at.run()
    assert not at.exception and not at.error
    df = at.dataframe[0].value
    assert len(df) >= 5
    assert df["Combination (experimental)"].str.contains("PD-1/VEGF bispecific").any()
    at.multiselect(key="f_site").set_value(["China-only"])
    at.run()
    assert set(at.dataframe[0].value["Site flag"]) == {"China-only"}
