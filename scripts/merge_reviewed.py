"""Move reviewed rows from data/proposed_modalities.csv into data/modalities.csv.

Only rows whose "reviewed" column says yes are moved; everything else stays in
the proposed file for later. A row for a drug already in the table (matched by
name or any synonym) updates that row and keeps all synonyms from both.

Usage:
    uv run python scripts/merge_reviewed.py --dry-run   # show what would change
    uv run python scripts/merge_reviewed.py             # do it
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import taxonomy as T  # noqa: E402
from app.curated import COLUMNS, split_synonyms  # noqa: E402
from app.names import name_key  # noqa: E402

TABLE = ROOT / "data" / "modalities.csv"
PROPOSED = ROOT / "data" / "proposed_modalities.csv"
VALID_MODALITIES = set(T.MODALITIES) | {T.NOT_CLASSIFIED}
YES = {"yes", "y", "true", "1", "reviewed"}


def iso_date(text: str) -> str:
    """Excel rewrites 2026-11-21 as 11/21/26 or 11/21/2026; put it back."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", text.strip())
    if not m:
        return text.strip()
    month, day, year = m.groups()
    year = f"20{year}" if len(year) == 2 else year
    return f"{year}-{int(month):02d}-{int(day):02d}"


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [{c: (r.get(c) or "").strip() for c in COLUMNS} for r in csv.DictReader(f) if (r.get("agent") or "").strip()]
    for r in rows:
        r["date"] = iso_date(r["date"])
        r["synonyms"] = "; ".join(split_synonyms(r["synonyms"]))
    return rows


def write(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def keys(row: dict) -> set[str]:
    return {name_key(n) for n in [row["agent"], *split_synonyms(row["synonyms"])] if name_key(n)}


def merge(table: list[dict], proposed: list[dict]) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Returns (new table, rows left in proposed, log lines, problems)."""
    table = [dict(r) for r in table]
    left, log, problems = [], [], []
    for row in proposed:
        if row["reviewed"].lower() not in YES:
            left.append(row)
            continue
        if row["modality"] not in VALID_MODALITIES:
            problems.append(f'{row["agent"]}: modality "{row["modality"]}" is not in the taxonomy - left in proposed')
            left.append(row)
            continue
        row = {**row, "reviewed": "yes", "date": row["date"] or date.today().isoformat()}
        match = next((t for t in table if keys(t) & keys(row)), None)
        if match:
            syns = [s for s in [*split_synonyms(match["synonyms"]), *split_synonyms(row["synonyms"])]
                    if name_key(s) != name_key(match["agent"])]
            unique = list(dict.fromkeys(syns))
            changes = [c for c in ("modality", "sub_modality", "target") if row[c] != match[c]]
            match.update({**row, "agent": match["agent"], "synonyms": "; ".join(unique)})
            log.append(f'updated {match["agent"]}' + (f' ({", ".join(changes)} changed)' if changes else ""))
        else:
            table.append(row)
            log.append(f'added {row["agent"]}: {row["modality"]}')
    return table, left, log, problems


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    table, proposed = read(TABLE), read(PROPOSED)
    if not proposed:
        print(f"Nothing to merge: {PROPOSED.relative_to(ROOT)} is empty or missing.")
        return 0
    new_table, left, log, problems = merge(table, proposed)
    for line in log:
        print("  " + line)
    for line in problems:
        print("  PROBLEM: " + line)
    print(f"{len(log)} reviewed rows merged; {len(left)} rows left in proposed_modalities.csv.")
    if args.dry_run:
        print("(dry run - nothing was changed)")
        return 0
    write(TABLE, new_table)
    write(PROPOSED, left)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
