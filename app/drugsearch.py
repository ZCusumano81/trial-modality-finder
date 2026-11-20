"""Search for a drug under ALL its names, merge the results, and drop false hits.

Why: ClinicalTrials.gov only merges names for well-known drugs. Searching
"ivonescimab" misses trials listed as "AK112"; searching "T-DXd" also returns
Dato-DXd trials. So:

1. Gather every name for the drug: curated table, ChEMBL synonyms, and the
   "other names" trials themselves list for it.
2. Search each name separately; merge and de-duplicate by NCT ID.
3. Keep a trial only if one of its interventions really is this drug.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from app import chembl
from app.ctgov import CTGovError, SearchQuery, search_studies
from app.curated import CuratedTable, default_table
from app.names import candidate_names, name_key, split_agents
from app.trial import Intervention, Trial, parse_study

MAX_SEARCH_NAMES = 12        # don't fire off dozens of searches for one drug
MIN_KEY_LENGTH = 4           # skip searching very short names ("EV") - too many false hits

SearchFn = Callable[[SearchQuery, int], tuple[list[dict], int]]


@dataclass
class DrugSearchResult:
    drug: str                                  # the name the user typed
    display_name: str                          # one consistent name ("ivonescimab")
    names: list[str]                           # every name we matched against
    searched: dict[str, int] = field(default_factory=dict)   # name searched -> trials returned
    trials: list[Trial] = field(default_factory=list)        # verified, de-duplicated
    dropped: list[Trial] = field(default_factory=list)       # returned by a search but not this drug
    errors: list[str] = field(default_factory=list)


def _unique(names: list[str]) -> list[str]:
    seen, out = set(), []
    for n in names:
        n = n.strip()
        k = name_key(n)
        if n and k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def known_names(drug: str, *, online: bool = True, table: CuratedTable | None = None) -> tuple[str, list[str]]:
    """(display name, every known name) from the curated table and ChEMBL."""
    table = table or default_table()
    names = [drug]
    display = drug.strip()
    entry = table.find(drug)
    if online:
        hit = chembl.lookup(entry.agent if entry else drug) or (chembl.lookup(drug) if entry else None)
        if hit:
            names += [hit.pref_name, *hit.synonyms]
            entry = entry or next((e for n in [hit.pref_name, *hit.synonyms] if (e := table.find(n))), None)
            if not entry and hit.pref_name:
                display = hit.pref_name if re.search(r"\d", hit.pref_name) else hit.pref_name.lower()
    if entry:
        names = [entry.agent, *entry.synonyms, *names]
        display = entry.agent
    return display, _unique(names)


def intervention_keys(iv: Intervention) -> set[str]:
    """Every cleaned name an intervention goes by (name parts, aliases, other names)."""
    keys = set()
    for text in [iv.name, *iv.other_names]:
        for part in split_agents(text) or [text]:
            for n in candidate_names(part) or [part]:
                keys.add(name_key(n))
    keys.discard("")
    return keys


def _tokens(text: str) -> list[str]:
    """Words of a text as comparison keys; hyphenated codes stay one word ("DS-8201a")."""
    return [k for w in re.split(r"[^\w\-]+", text.replace("_", " ")) if (k := name_key(w))]


def name_patterns(names: list[str]) -> list[list[str]]:
    """Each name as a word sequence to look for, skipping very short names."""
    return [toks for n in names if len(name_key(n)) >= MIN_KEY_LENGTH and (toks := _tokens(n))]


def _contains(words: list[str], seq: list[str]) -> bool:
    n = len(seq)
    return any(words[i:i + n] == seq for i in range(len(words) - n + 1))


def intervention_has_drug(iv: Intervention, patterns: list[list[str]]) -> bool:
    """Does the drug's name appear, as whole words, in this intervention's name or other names?"""
    for text in [iv.name, *iv.other_names]:
        words = _tokens(text)
        if any(_contains(words, p) for p in patterns):
            return True
    return False


def trial_has_drug(trial: Trial, patterns: list[list[str]]) -> bool:
    return any(intervention_has_drug(iv, patterns) for iv in trial.interventions)


def learn_code_names(trials: list[Trial], keys: set[str], patterns: list[list[str]],
                     *, online: bool = True, min_trials: int = 2) -> list[str]:
    """Code names that trials pair with this drug, e.g. "AK112" for ivonescimab.

    Trials' "other names" are messy (other drugs, company names, "standard of
    care"), so a learned name must look like a code (contain a digit, at most two
    words), be seen in at least `min_trials` trials, and not be a different drug in ChEMBL.
    """
    seen_in: dict[str, set[str]] = {}
    for t in trials:
        for iv in t.interventions:
            parts = split_agents(iv.name)
            if len(parts) != 1 or not intervention_has_drug(iv, patterns):
                continue
            for text in [iv.name, *iv.other_names]:
                sub = split_agents(text)
                if len(sub) != 1:
                    continue
                for n in candidate_names(sub[0]):
                    if (name_key(n) not in keys and re.search(r"\d", n) and len(n.split()) <= 2
                            and _searchable(n) and not re.search(r"placebo", n, re.I)):
                        seen_in.setdefault(n, set()).add(t.nct_id)
    learned = []
    for n, ids in sorted(seen_in.items(), key=lambda kv: -len(kv[1])):
        if len(ids) < min_trials or name_key(n) in {name_key(x) for x in learned}:
            continue
        if online and (hit := chembl.lookup(n)) and name_key(hit.pref_name) not in keys:
            continue              # ChEMBL says it's a different drug
        learned.append(n)
    return learned


def _searchable(name: str) -> bool:
    """Worth a search: not too short, and not a long descriptive phrase."""
    return len(name_key(name)) >= MIN_KEY_LENGTH and len(name.split()) <= 3 and " component of " not in name.lower()


def search_drug(
    drug: str,
    base_query: SearchQuery | None = None,
    *,
    max_results_per_name: int = 500,
    online: bool = True,
    table: CuratedTable | None = None,
    search_fn: SearchFn | None = None,
) -> DrugSearchResult:
    """Find every trial of `drug` under any of its names.

    base_query carries the user's other search fields and filters (condition,
    sponsor, status, phase, ...); its intervention field is replaced per name.
    """
    if not drug.strip():
        raise CTGovError("Please enter a drug name.")
    base = base_query or SearchQuery()
    run = search_fn or (lambda q, n: search_studies(q, max_results=n))
    display, names = known_names(drug, online=online, table=table)
    keys = {name_key(n) for n in names}
    result = DrugSearchResult(drug=drug, display_name=display, names=names)

    raw_by_id: dict[str, Trial] = {}

    def search(name: str) -> None:
        q = SearchQuery(**{**base.__dict__, "intervention": name})
        try:
            studies, _ = run(q, max_results_per_name)
        except CTGovError as e:
            result.errors.append(f'"{name}": {e}')
            return
        result.searched[name] = len(studies)
        for raw in studies:
            t = parse_study(raw)
            raw_by_id.setdefault(t.nct_id, t)

    to_search = [n for n in names if _searchable(n)][:MAX_SEARCH_NAMES]
    for n in to_search:
        search(n)

    # Learn extra code names from trials that clearly are this drug (e.g. a trial
    # listing "Ivonescimab" with other name "AK112"), then search those too.
    patterns = name_patterns(names)
    for n in learn_code_names(list(raw_by_id.values()), keys, patterns, online=online)[
            : max(0, MAX_SEARCH_NAMES - len(to_search))]:
        result.names.append(n)
        keys.add(name_key(n))
        patterns = name_patterns(result.names)
        search(n)

    for t in raw_by_id.values():
        (result.trials if trial_has_drug(t, patterns) else result.dropped).append(t)
    if result.errors and not result.searched:
        raise CTGovError(result.errors[0])
    return result
