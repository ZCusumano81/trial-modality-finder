"""The curated table, data/modalities.csv. Its answers always win."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.names import name_key

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "modalities.csv"
COLUMNS = ["agent", "synonyms", "modality", "sub_modality", "target",
           "confidence", "evidence", "source", "reviewed", "date"]


@dataclass(frozen=True)
class CuratedEntry:
    agent: str
    synonyms: tuple[str, ...]
    modality: str
    sub_modality: str
    target: str
    confidence: str
    evidence: str
    source: str
    reviewed: str
    date: str

    @property
    def all_names(self) -> list[str]:
        return [self.agent, *self.synonyms]


def split_synonyms(text: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in text.replace("|", ";").split(";") if s.strip())


class CuratedTable:
    def __init__(self, entries: list[CuratedEntry]):
        self.entries = entries
        self._by_key: dict[str, CuratedEntry] = {}
        for e in entries:
            for n in e.all_names:
                self._by_key.setdefault(name_key(n), e)

    @classmethod
    def load(cls, path: Path = CSV_PATH) -> "CuratedTable":
        entries = []
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if not (row.get("agent") or "").strip():
                        continue
                    entries.append(CuratedEntry(
                        agent=row["agent"].strip(),
                        synonyms=split_synonyms(row.get("synonyms") or ""),
                        **{c: (row.get(c) or "").strip() for c in COLUMNS if c not in ("agent", "synonyms")},
                    ))
        except FileNotFoundError:
            pass
        return cls(entries)

    def find(self, name: str) -> CuratedEntry | None:
        return self._by_key.get(name_key(name))


@lru_cache(maxsize=1)
def default_table() -> CuratedTable:
    return CuratedTable.load()
