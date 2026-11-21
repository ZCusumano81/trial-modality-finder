"""Find drugs the app can't classify, for a curation session. Never run by the app.

Runs every search in data/saved_searches.csv, classifies every agent (curated
table -> ChEMBL -> name rules -> Wikidata/Wikipedia) and writes the agents still
"Pending review" to data/unknown_agents.csv, most common first.

Usage:
    uv run python scripts/find_unknowns.py                 # pending agents only
    uv run python scripts/find_unknowns.py --include-low   # also low-confidence guesses
    uv run python scripts/find_unknowns.py --max 300       # trials per saved search

saved_searches.csv columns: name, query_term, condition, intervention, sponsor,
location, status, phase. Several statuses or phases are separated by ";".
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.combos import TrialModalities  # noqa: E402
from app.ctgov import CTGovError, SearchQuery  # noqa: E402
from app.curated import split_synonyms  # noqa: E402
from app.names import name_key  # noqa: E402
from app.pipeline import run_search  # noqa: E402

SAVED = ROOT / "data" / "saved_searches.csv"
OUT = ROOT / "data" / "unknown_agents.csv"
PROPOSED = ROOT / "data" / "proposed_modalities.csv"
COLUMNS = ["name", "status", "current_guess", "other_names", "description", "type",
           "intervention_text", "nct_ids", "trial_count", "found_by"]


@dataclass
class Unknown:
    name: str
    status: str                      # "pending" or "low confidence"
    current_guess: str = ""
    other_names: set[str] = field(default_factory=set)
    descriptions: list[str] = field(default_factory=list)
    types: set[str] = field(default_factory=set)
    texts: set[str] = field(default_factory=set)
    nct_ids: set[str] = field(default_factory=set)
    found_by: set[str] = field(default_factory=set)


def read_saved_searches(path: Path = SAVED) -> list[tuple[str, SearchQuery]]:
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            get = lambda k: (row.get(k) or "").strip()  # noqa: E731
            q = SearchQuery(
                text=get("query_term"), condition=get("condition"), intervention=get("intervention"),
                sponsor=get("sponsor"), location=get("location"),
                statuses=[s.upper() for s in split_synonyms(get("status"))],
                phases=[p.upper() for p in split_synonyms(get("phase"))],
            )
            if not q.is_empty():
                out.append((get("name") or f"search {len(out) + 1}", q))
    return out


def collect(analyses: list[TrialModalities], search_name: str, found: dict[str, Unknown],
            include_low: bool) -> None:
    for tm in analyses:
        ivs = {iv.name: iv for iv in tm.trial.interventions}
        for iv_name, calls in tm.interventions.items():
            iv = ivs.get(iv_name)
            for a in calls:
                if not a.is_drug:
                    continue
                if a.pending:
                    status, guess = "pending", ""
                elif include_low and a.confidence == "low":
                    status, guess = "low confidence", f"{a.modality} ({a.source}: {a.evidence[:120]})"
                else:
                    continue
                u = found.setdefault(name_key(a.name), Unknown(name=a.name, status=status, current_guess=guess))
                if iv:
                    u.other_names.update(iv.other_names)
                    if iv.description and iv.description not in u.descriptions:
                        u.descriptions.append(iv.description)
                    u.types.add(iv.type)
                u.texts.add(iv_name)
                u.nct_ids.add(tm.trial.nct_id)
                u.found_by.add(search_name)


def already_proposed() -> set[str]:
    if not PROPOSED.exists():
        return set()
    with open(PROPOSED, newline="", encoding="utf-8") as f:
        return {name_key(n) for r in csv.DictReader(f)
                for n in [r.get("agent") or "", *split_synonyms(r.get("synonyms") or "")] if name_key(n)}


def write(found: dict[str, Unknown], path: Path = OUT) -> int:
    rows = sorted(found.values(), key=lambda u: (u.status != "pending", -len(u.nct_ids), u.name.lower()))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for u in rows:
            w.writerow({
                "name": u.name, "status": u.status, "current_guess": u.current_guess,
                "other_names": "; ".join(sorted(u.other_names)),
                "description": " | ".join(d[:400] for d in u.descriptions[:3]),
                "type": "; ".join(sorted(t for t in u.types if t)),
                "intervention_text": " | ".join(sorted(u.texts)[:5]),
                "nct_ids": "; ".join(sorted(u.nct_ids)),
                "trial_count": len(u.nct_ids),
                "found_by": "; ".join(sorted(u.found_by)),
            })
    return len(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max", type=int, default=200, help="maximum trials per saved search (default 200)")
    p.add_argument("--include-low", action="store_true", help="also list low-confidence classifications")
    p.add_argument("--keep-proposed", action="store_true",
                   help="also list agents already in data/proposed_modalities.csv")
    args = p.parse_args()

    searches = read_saved_searches()
    if not searches:
        print(f"No searches found in {SAVED}.")
        return 1
    found: dict[str, Unknown] = {}
    for name, query in searches:
        print(f"Running: {name} ...", flush=True)
        try:
            outcome = run_search(query, max_results=args.max,
                                 progress=lambda d, n: print(f"\r  classified {d}/{n} trials", end="", flush=True))
            print()
        except CTGovError as e:
            print(f"\n  skipped: {e}")
            continue
        collect(outcome.analyses, name, found, args.include_low)
    if not args.keep_proposed:
        for k in already_proposed():
            found.pop(k, None)
    n = write(found)
    pending = sum(u.status == "pending" for u in found.values())
    print(f"\nWrote {n} agents to {OUT.relative_to(ROOT)} ({pending} pending review"
          + (f", {n - pending} low confidence" if args.include_low else "") + ").")
    return 0


if __name__ == "__main__":
    sys.exit(main())
