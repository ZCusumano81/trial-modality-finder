"""The 30-drug accuracy check: known drugs with known modalities (data/accuracy_set.csv).

Two ways to run it:
- with the curated table (what the app really does) - should be 30/30;
- without it, so only ChEMBL + name rules + web lookup decide - shows how well
  the automatic steps do on their own, for drugs not yet curated.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from app.curated import CuratedTable, default_table
from app.modality import AgentCall, classify_agent

SET_PATH = Path(__file__).resolve().parent.parent / "data" / "accuracy_set.csv"


@dataclass
class Check:
    drug: str
    expected_modality: str
    expected_sub: str
    call: AgentCall

    @property
    def modality_ok(self) -> bool:
        return self.call.modality == self.expected_modality

    @property
    def sub_ok(self) -> bool:
        return not self.expected_sub or self.call.sub_modality == self.expected_sub

    @property
    def ok(self) -> bool:
        return self.modality_ok and self.sub_ok


def load_set(path: Path = SET_PATH) -> list[tuple[str, str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return [(r["drug"].strip(), r["expected_modality"].strip(), (r.get("expected_sub_modality") or "").strip())
                for r in csv.DictReader(f) if r.get("drug", "").strip()]


def run(use_curated: bool = True, online: bool = True) -> list[Check]:
    table = default_table() if use_curated else CuratedTable([])
    return [Check(d, m, s, classify_agent(d, [d], online=online, table=table)) for d, m, s in load_set()]
