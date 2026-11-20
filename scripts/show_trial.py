"""Print a trial's details, or a quick search, in the terminal. For testing.

Examples:
    uv run python scripts/show_trial.py NCT03529110
    uv run python scripts/show_trial.py --drug ivonescimab --phase PHASE3 --brief
    uv run python scripts/show_trial.py --drug ivonescimab --exact-name     (old one-name search)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.combos import analyze_trial  # noqa: E402
from app.ctgov import CTGovError, SearchQuery, get_study, search_studies  # noqa: E402
from app.drugsearch import search_drug  # noqa: E402
from app.sites import SITE_FLAGS, summarize_trial_sites  # noqa: E402
from app.trial import Trial, parse_study  # noqa: E402


def print_trial(t: Trial, count_greater_china: bool = False) -> None:
    tm = analyze_trial(t)
    print(f"\n{t.nct_id}  {t.title}")
    print(f"  Link:        {t.url}")
    print(f"  Sponsor:     {t.sponsor or '-'}")
    print(f"  Status:      {t.status_label}")
    print(f"  Phase:       {t.phase_label}")
    print(f"  Conditions:  {'; '.join(t.conditions) or '-'}")
    print(f"  Combination: {tm.combination_label}" + ("   [has drugs pending review]" if tm.has_pending else ""))
    print(f"  Modalities:  {', '.join(tm.modalities) or '-'}")
    print(f"  Interventions ({len(t.interventions)}):")
    for i in t.interventions:
        extra = f"  [other names: {', '.join(i.other_names)}]" if i.other_names else ""
        print(f"    - {i.type}: {i.name}{extra}")
        for c in tm.interventions.get(i.name, []):
            if not c.is_drug:
                print(f"        -> {c.name}: {c.role} (not classified)")
                continue
            sub = f" / {c.sub_modality}" if c.sub_modality else ""
            tgt = f", target {c.target}" if c.target else ""
            how = f"  [{c.source}, {c.confidence} confidence]" if c.source else ""
            print(f"        -> {c.name}: {c.modality}{sub}{tgt}{how}")
            if c.evidence:
                print(f"           evidence: {c.evidence[:150]}")
    print(f"  Arms ({len(tm.arms)}):")
    for a in tm.arms:
        names = " + ".join(d.name for d in a.drugs) or "-"
        tags = f"  [{', '.join(a.tags)}]" if a.tags else ""
        print(f"    - {a.label} ({a.type or 'type not given'}): {a.combination_label}")
        print(f"        agents: {names}{tags}")
    s = summarize_trial_sites(t, count_greater_china)
    print(f"  Sites:       {s.site_count} in {s.country_count} countries: {s.countries_label or '-'}")
    print(f"  Site flag:   {s.flag}")


def print_brief(t: Trial, gc: bool) -> None:
    s = summarize_trial_sites(t, gc)
    tm = analyze_trial(t)
    print(f"{t.nct_id}  {s.flag:<24} {s.site_count:>4} sites  {tm.combination_label[:45]:<45}  {t.title[:60]}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("nct_ids", nargs="*", help="one or more NCT IDs")
    p.add_argument("--text", default="", help="free-text search")
    p.add_argument("--condition", default="")
    p.add_argument("--drug", default="", help="drug name (searches all its synonyms)")
    p.add_argument("--exact-name", action="store_true", help="search the drug under this one name only")
    p.add_argument("--sponsor", default="")
    p.add_argument("--location", default="")
    p.add_argument("--status", action="append", default=[], help="e.g. RECRUITING (repeatable)")
    p.add_argument("--phase", action="append", default=[], help="e.g. PHASE3 (repeatable)")
    p.add_argument("--max", type=int, default=10, help="max trials to show")
    p.add_argument("--greater-china", action="store_true",
                   help="count Hong Kong, Macau and Taiwan as China")
    p.add_argument("--flag", choices=SITE_FLAGS, help='only show trials with this site flag, e.g. "China-only"')
    p.add_argument("--brief", action="store_true", help="one line per trial")
    args = p.parse_args()
    gc = args.greater_china

    try:
        if args.nct_ids and not any([args.text, args.condition, args.drug, args.sponsor, args.location]):
            for nct_id in args.nct_ids:
                print_trial(parse_study(get_study(nct_id)), gc)
            return 0
        query = SearchQuery(
            text=args.text, condition=args.condition, intervention=args.drug,
            sponsor=args.sponsor, location=args.location,
            statuses=[s.upper() for s in args.status], phases=[s.upper() for s in args.phase],
            nct_ids=args.nct_ids,
        )
        if args.drug and not args.exact_name:
            print(f'Searching every known name for "{args.drug}" ...')
            r = search_drug(args.drug, query)
            print(f"Drug: {r.display_name}")
            print("Names searched (trials returned): "
                  + ", ".join(f"{n} ({c})" for n, c in r.searched.items()))
            print(f"{len(r.trials)} trials really list this drug; "
                  f"{len(r.dropped)} other search hits were dropped (a different drug, or only mentioned in text).")
            for e in r.errors:
                print(f"  Warning: {e}")
            trials = r.trials
            header = f"{len(trials)} trials"
        else:
            studies, total = search_studies(query, max_results=max(args.max, 200 if args.flag else args.max))
            trials = [parse_study(raw) for raw in studies]
            header = f"{total} trials match on ClinicalTrials.gov; fetched {len(studies)}"
        if args.flag:
            trials = [t for t in trials if summarize_trial_sites(t, gc).flag == args.flag]
            header += f', {len(trials)} of them "{args.flag}"'
        print(f"{header}; showing {min(len(trials), args.max)}.\n")
        for t in trials[: args.max]:
            print_brief(t, gc) if args.brief else print_trial(t, gc)
        return 0
    except CTGovError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
