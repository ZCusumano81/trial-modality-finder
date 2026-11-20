"""Print a trial's details, or a quick search, in the terminal. For testing.

Examples:
    uv run python scripts/show_trial.py NCT03529110
    uv run python scripts/show_trial.py --drug ivonescimab --phase PHASE3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ctgov import CTGovError, SearchQuery, get_study, search_studies  # noqa: E402
from app.trial import Trial, parse_study  # noqa: E402


def print_trial(t: Trial) -> None:
    print(f"\n{t.nct_id}  {t.title}")
    print(f"  Link:        {t.url}")
    print(f"  Sponsor:     {t.sponsor or '-'}")
    print(f"  Status:      {t.status_label}")
    print(f"  Phase:       {t.phase_label}")
    print(f"  Conditions:  {'; '.join(t.conditions) or '-'}")
    print(f"  Interventions ({len(t.interventions)}):")
    for i in t.interventions:
        extra = f"  [other names: {', '.join(i.other_names)}]" if i.other_names else ""
        print(f"    - {i.type}: {i.name}{extra}")
    print(f"  Arms ({len(t.arm_groups)}):")
    for a in t.arm_groups:
        print(f"    - {a.label} ({a.type or 'type not given'}): {', '.join(a.intervention_names) or '-'}")
    countries = sorted({s.country for s in t.sites if s.country})
    print(f"  Sites:       {len(t.sites)} in {len(countries)} countries: {', '.join(countries) or '-'}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("nct_ids", nargs="*", help="one or more NCT IDs")
    p.add_argument("--text", default="", help="free-text search")
    p.add_argument("--condition", default="")
    p.add_argument("--drug", default="", help="intervention / drug name")
    p.add_argument("--sponsor", default="")
    p.add_argument("--location", default="")
    p.add_argument("--status", action="append", default=[], help="e.g. RECRUITING (repeatable)")
    p.add_argument("--phase", action="append", default=[], help="e.g. PHASE3 (repeatable)")
    p.add_argument("--max", type=int, default=10, help="max trials to show for a search")
    args = p.parse_args()

    try:
        if args.nct_ids and not any([args.text, args.condition, args.drug, args.sponsor, args.location]):
            for nct_id in args.nct_ids:
                print_trial(parse_study(get_study(nct_id)))
            return 0
        query = SearchQuery(
            text=args.text, condition=args.condition, intervention=args.drug,
            sponsor=args.sponsor, location=args.location,
            statuses=[s.upper() for s in args.status], phases=[s.upper() for s in args.phase],
            nct_ids=args.nct_ids,
        )
        studies, total = search_studies(query, max_results=args.max)
        print(f"{total} trials match on ClinicalTrials.gov; showing {len(studies)}.")
        for raw in studies:
            print_trial(parse_study(raw))
        return 0
    except CTGovError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
