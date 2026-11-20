"""Print the 30-drug accuracy check as a table.

    uv run python scripts/accuracy_report.py              # with the curated table (should be 30/30)
    uv run python scripts/accuracy_report.py --automatic  # ChEMBL + name rules + web only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.accuracy import run  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--automatic", action="store_true", help="ignore the curated table")
    args = p.parse_args()
    checks = run(use_curated=not args.automatic)
    mode = "automatic lookups only (no curated table)" if args.automatic else "with the curated table"
    print(f"30-drug accuracy check, {mode}\n")
    print(f"{'':2} {'drug':38} {'expected':34} {'got':34} {'source'}")
    for c in checks:
        got = c.call.modality + (f" / {c.call.sub_modality}" if c.call.sub_modality else "")
        exp = c.expected_modality + (f" / {c.expected_sub}" if c.expected_sub else "")
        mark = "✓ " if c.ok else ("~ " if c.modality_ok else "✗ ")
        print(f"{mark}{c.drug[:38]:38} {exp[:34]:34} {got[:34]:34} {c.call.source}")
    right = sum(c.modality_ok for c in checks)
    exact = sum(c.ok for c in checks)
    print(f"\nModality correct: {right}/{len(checks)}   (including sub-type: {exact}/{len(checks)})")
    print("✓ = right   ~ = right modality, sub-type missing or different   ✗ = wrong or pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
