"""Run a search and analyze every trial it returns. Used by the web app.

Kept separate from the page so it can be tested without Streamlit.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from app.combos import TrialModalities, analyze_trial
from app.ctgov import SearchQuery, search_studies
from app.drugsearch import search_drug
from app.trial import Trial, parse_study

WORKERS = 8      # trials analyzed at the same time (each may look drugs up online)


@dataclass
class SearchOutcome:
    analyses: list[TrialModalities]
    total_on_site: int | None = None              # plain searches: matches on ClinicalTrials.gov
    drug_display_name: str = ""                   # drug searches: the consistent drug name
    names_searched: dict[str, int] = field(default_factory=dict)
    dropped: int = 0                              # drug searches: hits that weren't this drug
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False                       # more trials existed than max_results
    modality_label: str = ""                      # modality searches: what was searched
    modality_any_arm: bool = False
    possible_ids: set[str] = field(default_factory=set)   # modality searches: unconfirmed keyword hits
    known_drugs: int = 0                          # modality searches: known drug names searched
    candidates: int = 0                           # modality searches: trials classified


def analyze_all(trials: list[Trial], progress: Callable[[int, int], None] | None = None,
                online: bool = True) -> list[TrialModalities]:
    """Analyze trials in parallel, keeping their order."""
    results: list[TrialModalities | None] = [None] * len(trials)
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(analyze_trial, t, online=online): i for i, t in enumerate(trials)}
        for fut in futures:
            results[futures[fut]] = fut.result()
            done += 1
            if progress:
                progress(done, len(trials))
    return [r for r in results if r is not None]


def run_search(query: SearchQuery, max_results: int = 200, *, merge_drug_synonyms: bool = True,
               modality: str = "", any_arm: bool = False,
               progress: Callable[[int, int], None] | None = None) -> SearchOutcome:
    """Search and analyze each trial.

    - modality (a label from app.modalitysearch.TARGETS) with no drug: modality search;
    - drug given: every known name of the drug (optionally keeping only trials with `modality`);
    - otherwise: a plain ClinicalTrials.gov search.
    """
    from app.modalitysearch import TARGETS_BY_LABEL, search_modality
    target = TARGETS_BY_LABEL.get(modality) if modality else None
    if target and not query.intervention.strip():
        r = search_modality(target, query, any_arm=any_arm, max_results=max_results, progress=progress)
        return SearchOutcome(
            analyses=[*r.confirmed, *r.possible], names_searched=r.searches, warnings=r.warnings,
            truncated=r.truncated, modality_label=target.label, modality_any_arm=any_arm,
            possible_ids={tm.trial.nct_id for tm in r.possible}, known_drugs=r.known_drugs,
            candidates=r.candidates)
    out = _run_plain_or_drug(query, max_results, merge_drug_synonyms, progress)
    if target:
        keep = []
        for tm in out.analyses:
            drugs = tm.drugs if any_arm else tm.experimental_drugs
            if any(target.matches(a.modality, a.sub_modality) for a in drugs):
                keep.append(tm)
        out.analyses, out.modality_label, out.modality_any_arm = keep, target.label, any_arm
    return out


def _run_plain_or_drug(query: SearchQuery, max_results: int, merge_drug_synonyms: bool,
                       progress: Callable[[int, int], None] | None) -> SearchOutcome:
    if query.intervention.strip() and merge_drug_synonyms:
        base = SearchQuery(**{**query.__dict__, "intervention": ""})
        r = search_drug(query.intervention, base, max_results_per_name=max(max_results, 200))
        trials = r.trials[:max_results]
        out = SearchOutcome(analyses=[], drug_display_name=r.display_name, names_searched=r.searched,
                            dropped=len(r.dropped), warnings=r.errors, truncated=len(r.trials) > max_results)
    else:
        studies, total = search_studies(query, max_results=max_results)
        trials = [parse_study(s) for s in studies]
        out = SearchOutcome(analyses=[], total_on_site=total, truncated=total > len(trials))
    out.analyses = analyze_all(trials, progress)
    return out
