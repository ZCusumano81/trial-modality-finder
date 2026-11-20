"""Turn analyzed trials into tables, apply the page's filters, and build exports."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app import taxonomy as T
from app.combos import TrialModalities
from app.sites import SiteSummary, summarize_trial_sites

DATA_NOTE = ("Sources: ClinicalTrials.gov; ChEMBL (EMBL-EBI, CC BY-SA 3.0); Wikidata (CC0); Wikipedia (CC BY-SA). "
             "Modality calls are curated with AI help and may contain errors.")


@dataclass
class Filters:
    site_flags: list[str] = field(default_factory=list)            # any of these
    experimental_modalities: list[str] = field(default_factory=list)  # experimental arms include any
    contains_modalities: list[str] = field(default_factory=list)   # any arm includes ALL of these
    combinations_only: bool = False
    pending_only: bool = False


def matches(tm: TrialModalities, sites: SiteSummary, f: Filters) -> bool:
    if f.site_flags and sites.flag not in f.site_flags:
        return False
    if f.experimental_modalities and not set(f.experimental_modalities) & set(tm.experimental_modalities):
        return False
    if f.contains_modalities and not set(f.contains_modalities) <= set(tm.modalities):
        return False
    if f.combinations_only and not any(a.is_combination for a in tm.experimental_arms):
        return False
    if f.pending_only and not tm.has_pending:
        return False
    return True


def filter_trials(analyses: list[TrialModalities], f: Filters,
                  count_greater_china: bool = False) -> list[tuple[TrialModalities, SiteSummary]]:
    out = []
    for tm in analyses:
        s = summarize_trial_sites(tm.trial, count_greater_china)
        if matches(tm, s, f):
            out.append((tm, s))
    return out


def _agents_text(tm: TrialModalities) -> str:
    return "; ".join(f"{a.name} ({a.short_label})" for a in tm.drugs)


def trials_table(rows: list[tuple[TrialModalities, SiteSummary]]) -> pd.DataFrame:
    """One row per trial."""
    records = []
    for tm, s in rows:
        t = tm.trial
        records.append({
            "NCT ID": t.nct_id,
            "Link": t.url,
            "Title": t.title,
            "Sponsor": t.sponsor,
            "Status": t.status_label,
            "Phase": t.phase_label,
            "Indication(s)": "; ".join(t.conditions),
            "Combination (experimental)": tm.combination_label,
            "Experimental modalities": "; ".join(tm.experimental_modalities),
            "All modalities": "; ".join(tm.modalities),
            "Agents": _agents_text(tm),
            "Pending review": "Yes" if tm.has_pending else "",
            "Sites": s.site_count,
            "Countries": s.country_count,
            "Site countries": s.countries_label,
            "Site flag": s.flag,
        })
    return pd.DataFrame.from_records(records, columns=[
        "NCT ID", "Link", "Title", "Sponsor", "Status", "Phase", "Indication(s)", "Combination (experimental)",
        "Experimental modalities", "All modalities", "Agents", "Pending review", "Sites", "Countries",
        "Site countries", "Site flag"])


def agents_table(rows: list[tuple[TrialModalities, SiteSummary]]) -> pd.DataFrame:
    """One row per agent per trial, with how each modality was decided."""
    records = []
    for tm, _ in rows:
        for iv_name, calls in tm.interventions.items():
            for a in calls:
                arms = [arm.label for arm in tm.arms if a in arm.agents]
                records.append({
                    "NCT ID": tm.trial.nct_id,
                    "Intervention as written": iv_name,
                    "Agent": a.name,
                    "Role": a.role,
                    "Modality": a.modality,
                    "Sub-type": a.sub_modality,
                    "Target": a.target,
                    "Source": a.source,
                    "Confidence": a.confidence,
                    "Evidence": a.evidence,
                    "Evidence link": a.url,
                    "Arms": "; ".join(arms),
                })
    return pd.DataFrame.from_records(records, columns=[
        "NCT ID", "Intervention as written", "Agent", "Role", "Modality", "Sub-type", "Target", "Source",
        "Confidence", "Evidence", "Evidence link", "Arms"])


def to_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")       # utf-8-sig so Excel shows accents correctly


def to_excel(trials: pd.DataFrame, agents: pd.DataFrame, search_description: str = "") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        trials.to_excel(xw, sheet_name="Trials", index=False)
        agents.to_excel(xw, sheet_name="Agents", index=False)
        pd.DataFrame({"About this export": [
            f"Exported {date.today().isoformat()} from Clinical Trial Modality Finder.",
            f"Search: {search_description}" if search_description else "",
            DATA_NOTE,
        ]}).to_excel(xw, sheet_name="About", index=False)
        for sheet in xw.book.worksheets:
            for col in sheet.columns:
                width = max(len(str(c.value or "")) for c in col[:200])
                sheet.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
            sheet.freeze_panes = "A2"
    return buf.getvalue()


def modality_options() -> list[str]:
    return [m for m in T.MODALITIES if m != T.UNKNOWN] + [T.PENDING]
