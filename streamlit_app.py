"""Clinical Trial Modality Finder - the web page.

Run locally:  uv run streamlit run streamlit_app.py
"""
from __future__ import annotations

import os
from urllib.parse import quote

import pandas as pd
import streamlit as st

from app.ctgov import PHASES, STATUSES, CTGovError, SearchQuery
from app.drugsearch import identify
from app.modalitysearch import TARGETS
from app.pipeline import SearchOutcome, run_search
from app.results import (Filters, agents_table, filter_trials, modality_options, to_csv, to_excel,
                         trials_table)
from app.sites import SITE_FLAGS
from app.trial import PHASE_LABELS

st.set_page_config(page_title="Clinical Trial Modality Finder", page_icon="🔬", layout="wide")


def corrections_email() -> str:
    """Address for "Suggest a correction" links: set CORRECTIONS_EMAIL in Streamlit secrets or the environment."""
    try:
        value = st.secrets.get("CORRECTIONS_EMAIL", "")
    except Exception:
        value = ""
    return value or os.environ.get("CORRECTIONS_EMAIL", "")


def status_label(code: str) -> str:
    words = code.replace("_", " ").lower().replace("active not", "active, not")
    return words[0].upper() + words[1:]


@st.cache_data(ttl=3600, show_spinner=False, max_entries=200)
def known_drug(text: str) -> str:
    """The drug's consistent name if this text is a known drug (curated table or ChEMBL), else ""."""
    if not text.strip() or len(text.split()) > 4:
        return ""
    display, _, identified = identify(text.strip())
    return display if identified else ""


@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def cached_search(fields: tuple, statuses: tuple, phases: tuple, nct_ids: tuple,
                  max_results: int, merge: bool, modality: str = "", any_arm: bool = False) -> SearchOutcome:
    text, condition, drug, sponsor, location = fields
    query = SearchQuery(text=text, condition=condition, intervention=drug, sponsor=sponsor, location=location,
                        statuses=list(statuses), phases=list(phases), nct_ids=list(nct_ids))
    return run_search(query, max_results=max_results, merge_drug_synonyms=merge, modality=modality,
                      any_arm=any_arm)


# ---------------------------------------------------------------- sidebar: search
with st.sidebar:
    st.header("Search ClinicalTrials.gov")
    with st.form("search"):
        modality = st.selectbox(
            "Modality", ["Any modality", *[t.label for t in TARGETS]], key="q_mod",
            help="Find trials by drug modality, e.g. every ADC trial. Combine with a condition, phase, "
                 "location etc. to narrow it. With a drug name too, keeps only that drug's trials "
                 "with this modality.")
        any_arm = st.checkbox("Also count comparator arms", value=False, key="q_anyarm",
                              help="Off: the modality must be in an experimental arm. "
                                   "On: any arm, including the comparator.")
        drug = st.text_input("Drug / intervention", key="q_drug", placeholder="e.g. ivonescimab, AK112, T-DXd")
        merge = st.checkbox("Include all known names for the drug", value=True,
                            help="Also searches code names, brand names and synonyms (e.g. AK112 for "
                                 "ivonescimab), then keeps only trials that really list the drug.")
        condition = st.text_input("Condition", placeholder="e.g. non-small cell lung cancer")
        text = st.text_input("Free text (anywhere in the record)")
        sponsor = st.text_input("Sponsor", placeholder="e.g. Akeso")
        location = st.text_input("Location", placeholder="e.g. China, Boston")
        nct_text = st.text_input("NCT ID(s)", placeholder="NCT05499390, NCT03529110")
        statuses = st.multiselect("Status", STATUSES, key="q_status", format_func=status_label)
        phases = st.multiselect("Phase", PHASES, key="q_phase", format_func=lambda p: PHASE_LABELS.get(p, p))
        max_results = st.select_slider("Maximum trials", options=[25, 50, 100, 200, 300, 500, 1000], value=100,
                                       help="Bigger numbers take longer the first time.")
        submitted = st.form_submit_button("Search", type="primary", width="stretch")

    st.header("Settings")
    greater_china = st.toggle("Count Hong Kong, Macau and Taiwan as China", value=False, key="s_gc",
                              help='Changes which trials are "China-only".')

# ---------------------------------------------------------------- run the search
st.title("Clinical Trial Modality Finder")
st.caption("Search ClinicalTrials.gov and see the drug modality of every agent in each trial, "
           "including each agent in combination trials, plus where the trial's sites are.")

if submitted:
    nct_ids = tuple(x.strip() for x in nct_text.replace(";", ",").replace(" ", ",").split(",") if x.strip())
    fields = (text, condition, drug, sponsor, location)
    chosen_modality = "" if modality == "Any modality" else modality
    if not any(f.strip() for f in fields) and not nct_ids and not statuses and not phases and not chosen_modality:
        st.warning("Enter at least one search term or filter in the sidebar.")
    else:
        try:
            with st.spinner("Searching ClinicalTrials.gov and classifying drugs. "
                            "The first search for a drug can take up to a minute; repeats are fast."):
                st.session_state["outcome"] = cached_search(
                    fields, tuple(statuses), tuple(phases), nct_ids, max_results, merge, chosen_modality,
                    any_arm)
                st.session_state["drug_hint"] = (
                    known_drug(text) if text.strip() and not drug.strip() else "")
                st.session_state["search_description"] = "; ".join(
                    f"{k}: {v}" for k, v in [("modality", chosen_modality), ("drug", drug), ("condition", condition), ("text", text),
                                             ("sponsor", sponsor), ("location", location),
                                             ("NCT IDs", ", ".join(nct_ids)),
                                             ("status", ", ".join(statuses)), ("phase", ", ".join(phases))] if v)
        except CTGovError as e:
            st.error(str(e))

outcome: SearchOutcome | None = st.session_state.get("outcome")

if outcome is None:
    st.info("Use the search panel on the left to find trials. Try a drug like **ivonescimab** or "
            "**trastuzumab deruxtecan**, a sponsor like **Akeso**, an NCT ID - or pick a **Modality** "
            "(e.g. ADC) with a condition such as **breast cancer**.")
else:
    # ------------------------------------------------------------ search summary
    if st.session_state.get("drug_hint"):
        st.info(f'"**{text.strip() or st.session_state["drug_hint"]}**" looks like a drug name '
                f'(**{st.session_state["drug_hint"]}**). Free text only finds these exact words. Put it in '
                "**Drug / intervention** instead to include every name the drug goes by (code names, brand "
                "names, synonyms).")
    modality_search = bool(outcome.modality_label) and outcome.candidates > 0
    if modality_search:
        where = "any arm" if outcome.modality_any_arm else "an experimental arm"
        n_possible = len(outcome.possible_ids)
        st.write(f"**{len(outcome.analyses) - n_possible} trials** with a confirmed "
                 f"**{outcome.modality_label}** in {where}"
                 + (f", plus **{n_possible} possible** matches." if n_possible else "."))
        st.caption(f"Searched {outcome.known_drugs} known drug names of this modality plus keywords, then "
                   f"classified {outcome.candidates} candidate trials. *Possible* = found by keyword and the "
                   "drug's own description mentions the modality, but the drug isn't classified yet "
                   "(it is pending review).")
        with st.expander("Searches run"):
            st.write("\n".join(f"- {n}: {c} trials" for n, c in outcome.names_searched.items()))
    elif outcome.names_searched:
        names = ", ".join(f"{n} ({c})" for n, c in outcome.names_searched.items())
        mod_note = f" with **{outcome.modality_label}**" if outcome.modality_label else ""
        st.write(f"**{len(outcome.analyses)} trials** of **{outcome.drug_display_name}**{mod_note}. "
                 f"Names searched (trials returned): {names}.")
        if outcome.dropped:
            st.caption(f"{outcome.dropped} other search hits were left out because they don't list this drug "
                       "as an intervention (a different drug with a similar name, or only a passing mention).")
    elif outcome.total_on_site is not None:
        st.write(f"**{outcome.total_on_site} trials** match on ClinicalTrials.gov; "
                 f"showing the first **{len(outcome.analyses)}**.")
    if outcome.truncated:
        st.caption("More trials match than the maximum you set; raise **Maximum trials** to see more.")
    for w in outcome.warnings:
        st.warning(w)

    # ------------------------------------------------------------ result filters
    with st.expander("Filter results", expanded=True):
        c1, c2, c3 = st.columns(3)
        site_flags = c1.multiselect("Site flag", SITE_FLAGS, key="f_site")
        exp_mods = c2.multiselect("Modality (experimental arms)", modality_options(), key="f_exp",
                                  help="Trials whose experimental arms include any of these.")
        contains = c3.multiselect("Contains modality (any arm)", modality_options(), key="f_contains",
                                  help="Trials that include all of these anywhere, comparator arms too. "
                                       "E.g. pick ADC to see any trial with an ADC.")
        c4, c5, c6 = st.columns(3)
        combos_only = c4.checkbox("Combination regimens only", key="f_combo")
        pending_only = c5.checkbox('Only trials with drugs "Pending review"', key="f_pending")
        show_possible = c6.checkbox("Include possible matches", value=True, key="f_possible",
                                    disabled=not modality_search)
    filters = Filters(site_flags=site_flags, experimental_modalities=exp_mods, contains_modalities=contains,
                      combinations_only=combos_only, pending_only=pending_only)
    rows = filter_trials(outcome.analyses, filters, greater_china)
    if modality_search and not show_possible:
        rows = [(tm, s) for tm, s in rows if tm.trial.nct_id not in outcome.possible_ids]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Trials shown", len(rows))
    m2.metric("China-only", sum(s.flag == "China-only" for _, s in rows))
    m3.metric("Combination regimens", sum(any(a.is_combination for a in tm.experimental_arms) for tm, _ in rows))
    m4.metric("With drugs pending review", sum(tm.has_pending for tm, _ in rows))

    trials_df = trials_table(rows, outcome.possible_ids if modality_search else None)
    agents_df = agents_table(rows)

    # ------------------------------------------------------------ results table
    shown_cols = ["NCT ID", *(["Modality match"] if modality_search else []), "Link", "Title", "Sponsor", "Phase", "Status", "Combination (experimental)",
                  "Agents", "Pending review", "Sites", "Site flag", "Site countries", "Indication(s)"]
    event = st.dataframe(
        trials_df[shown_cols], hide_index=True, width="stretch", height=420,
        on_select="rerun", selection_mode="single-row", key="results_table",
        column_config={
            "Link": st.column_config.LinkColumn("Link", display_text="open ↗", width="small"),
            "Title": st.column_config.TextColumn(width="large"),
            "Combination (experimental)": st.column_config.TextColumn(width="medium"),
            "Agents": st.column_config.TextColumn(width="large"),
            "Sites": st.column_config.NumberColumn(width="small"),
        },
    )
    st.caption("Click a row to see the trial's details below.")

    d1, d2, d3 = st.columns(3)
    d1.download_button("Download table (CSV)", to_csv(trials_df), "trials.csv", "text/csv",
                       width="stretch", disabled=trials_df.empty)
    d2.download_button("Download agents (CSV)", to_csv(agents_df), "trial_agents.csv", "text/csv",
                       width="stretch", disabled=agents_df.empty)
    d3.download_button("Download Excel (trials + agents)",
                       to_excel(trials_df, agents_df, st.session_state.get("search_description", "")),
                       "trials.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       width="stretch", disabled=trials_df.empty)

    # ------------------------------------------------------------ trial detail
    selected = event.selection.rows if event and event.selection else []
    by_id = {tm.trial.nct_id: (tm, s) for tm, s in rows}
    if rows:
        ids = list(by_id)
        default = trials_df.iloc[selected[0]]["NCT ID"] if selected else ids[0]
        st.divider()
        choice = st.selectbox("Trial details", ids, index=ids.index(default),
                              format_func=lambda i: f"{i} - {by_id[i][0].trial.title[:110]}")
        tm, s = by_id[choice]
        t = tm.trial

        st.subheader(t.title)
        badge = "  :orange-badge[Pending review]" if tm.has_pending else ""
        st.markdown(f"[{t.nct_id}]({t.url}) · {t.phase_label} · {t.status_label} · "
                    f"Sponsor: **{t.sponsor or 'not given'}**{badge}")
        st.markdown(f"**Indication(s):** {'; '.join(t.conditions) or 'not given'}  \n"
                    f"**Combination (experimental arms):** {tm.combination_label}  \n"
                    f"**Sites:** {s.site_count} in {s.country_count} countries · **{s.flag}**"
                    + (f"  \n**Countries:** {s.countries_label}" if s.countries_label else ""))

        st.markdown("##### Arms: which agents are given together")
        arm_records = [{"Arm": a.label, "Type": (a.type or "not given").replace("_", " ").lower(),
                        "Combination": a.combination_label,
                        "Agents": " + ".join(d.name for d in a.drugs) or "-",
                        "Also": ", ".join(a.tags)} for a in tm.arms]
        st.dataframe(pd.DataFrame(arm_records), hide_index=True, width="stretch")

        st.markdown("##### Each agent's modality, and how it was decided")
        trial_agents = agents_df[agents_df["NCT ID"] == t.nct_id].drop(columns=["NCT ID"])
        st.dataframe(trial_agents, hide_index=True, width="stretch",
                     column_config={"Evidence link": st.column_config.LinkColumn(display_text="source ↗"),
                                    "Evidence": st.column_config.TextColumn(width="large")})
        st.caption("Source: **curated** = reviewed table; **chembl** = ChEMBL molecule type; "
                   "**name rule** = drug-name stem; **wikipedia / wikidata** = free web lookup "
                   "(low confidence). *Pending review* = not yet classified.")

        email = corrections_email()
        if email:
            subject = quote(f"Modality correction: {t.nct_id}")
            body = quote(f"Trial: {t.nct_id} ({t.url})\n\nAgent:\nCurrent modality:\nCorrect modality:\n"
                         "Source / evidence:\n")
            st.markdown(f"Spotted a mistake? [Suggest a correction](mailto:{email}?subject={subject}&body={body})")

# ---------------------------------------------------------------- footer
st.divider()
st.caption(
    "Data: [ClinicalTrials.gov](https://clinicaltrials.gov) (U.S. National Library of Medicine); "
    "[ChEMBL](https://www.ebi.ac.uk/chembl/) (EMBL-EBI, CC BY-SA 3.0); "
    "[Wikidata](https://www.wikidata.org) (CC0); [Wikipedia](https://www.wikipedia.org) (CC BY-SA). "
    "Modality calls are curated with AI help and may contain errors. Not medical advice."
)
