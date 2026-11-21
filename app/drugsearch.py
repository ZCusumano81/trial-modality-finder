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
from app.names import DRUG, candidate_names, name_key, role_of, split_agents
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


def identify(drug: str, *, online: bool = True,
             table: CuratedTable | None = None) -> tuple[str, list[str], bool]:
    """(display name, every known name, identified?) from the curated table and ChEMBL.

    identified is False when neither source knows the name (e.g. a new code name).
    """
    table = table or default_table()
    names = [drug]
    display = drug.strip()
    entry = table.find(drug)
    hit = None
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
    return display, _unique(names), bool(entry or hit)


def known_names(drug: str, *, online: bool = True, table: CuratedTable | None = None) -> tuple[str, list[str]]:
    """(display name, every known name) from the curated table and ChEMBL."""
    display, names, _ = identify(drug, online=online, table=table)
    return display, names


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


# Words that show up in "other names" but aren't names of this drug.
GENERIC_NAME = re.compile(
    r"^(?:study drug|investigational (?:product|drug|agent)|experimental (?:product|drug|arm)|test (?:product|drug)|"
    r"active (?:drug|treatment)|treatment|therapy|injection|drug|biological|combination|monotherapy|regimen)$", re.I)


def learn_names(trials: list[Trial], keys: set[str], patterns: list[list[str]], *, identified: bool,
                online: bool = True, table: CuratedTable | None = None,
                min_trials: int = 2) -> list[str]:
    """Other names that trials pair with this drug, in either direction.

    A trial listing "Telisotuzumab adizutecan" with other name "ABBV-400" teaches
    that the two are the same drug, whichever one was searched. Trials' other names
    are messy (partner drugs, company names, "study drug"), so a candidate must:
    - come from an intervention that names only this drug,
    - not be placebo / standard of care / a procedure / a generic phrase / the sponsor,
    - and either be confirmed by ChEMBL or the curated table as the same drug, or be
      seen with this drug in at least `min_trials` trials (3 if it has no digit).
    If this drug wasn't known to ChEMBL or the curated table (identified=False), a
    known drug is adopted as its identity when >= min_trials trials use the known drug
    as the intervention name with this drug among its other names.
    """
    table = table or default_table()
    seen_in: dict[str, set[str]] = {}
    as_main_name: dict[str, set[str]] = {}       # candidate was the intervention's main name
    sponsors = {name_key(t.sponsor) for t in trials if t.sponsor}
    for t in trials:
        for iv in t.interventions:
            if len(split_agents(iv.name)) != 1 or not intervention_has_drug(iv, patterns):
                continue
            for i, text in enumerate([iv.name, *iv.other_names]):
                sub = split_agents(text)
                if len(sub) != 1:
                    continue
                for n in candidate_names(sub[0]):
                    k = name_key(n)
                    if (k in keys or not _searchable(n) or role_of(n) != DRUG or GENERIC_NAME.match(n.strip())
                            or re.search(r"\b(?:or|and|plus|with)\b|[,/+]", n, re.I)
                            or k in sponsors or any(k and k in sp for sp in sponsors)):
                        continue
                    seen_in.setdefault(n, set()).add(t.nct_id)
                    if i == 0:
                        as_main_name.setdefault(n, set()).add(t.nct_id)

    learned: list[str] = []
    for n, ids in sorted(seen_in.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        k = name_key(n)
        if k in {name_key(x) for x in learned}:
            continue
        entry = table.find(n)
        hit = chembl.lookup(n) if online else None
        known_keys = ({name_key(x) for x in entry.all_names} if entry else set()) | \
                     ({name_key(hit.pref_name), *(name_key(x) for x in hit.synonyms)} if hit else set())
        if entry or hit:
            if known_keys & keys:
                learned.append(n)                  # confirmed: the same drug
            elif not identified and len(as_main_name.get(n, ())) >= min_trials:
                # Our unknown code is this known drug - but only if trials name the known
                # drug as the intervention and list our code as its other name. (A code
                # name with partner drugs in its "other names" must not become a partner.)
                learned.append(n)
            continue                               # otherwise: a different drug
        needed = min_trials if re.search(r"\d", n) else min_trials + 1
        if len(ids) >= needed:
            learned.append(n)
    return learned


# Kept for older callers.
def learn_code_names(trials: list[Trial], keys: set[str], patterns: list[list[str]],
                     *, online: bool = True, min_trials: int = 2) -> list[str]:
    return [n for n in learn_names(trials, keys, patterns, identified=True, online=online, min_trials=min_trials)
            if re.search(r"\d", n) and len(n.split()) <= 2]


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
    display, names, identified = identify(drug, online=online, table=table)
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

    def add_names(new: list[str]) -> None:
        for n in new:
            if name_key(n) and name_key(n) not in keys:
                keys.add(name_key(n))
                result.names.append(n)

    for n in [n for n in names if _searchable(n)][:MAX_SEARCH_NAMES]:
        search(n)

    # Learn other names from the trials found (e.g. "ABBV-400" listed with other name
    # "Telisotuzumab adizutecan", or the reverse), widen them with the curated table and
    # ChEMBL, and search those too. Two rounds at most.
    for _ in range(2):
        learned = learn_names(list(raw_by_id.values()), keys, name_patterns(result.names),
                              identified=identified, online=online, table=table)
        if not learned:
            break
        add_names(learned)
        for n in learned:
            d, more, ok = identify(n, online=online, table=table)
            if ok:
                add_names(more)
                if not identified:
                    result.display_name, identified = d, True
        for n in [n for n in result.names if _searchable(n) and n not in result.searched]:
            if len(result.searched) >= MAX_SEARCH_NAMES:
                break
            search(n)

    patterns = name_patterns(result.names)
    for t in raw_by_id.values():
        (result.trials if trial_has_drug(t, patterns) else result.dropped).append(t)
    if result.errors and not result.searched:
        raise CTGovError(result.errors[0])
    return result
