"""The 30-drug accuracy check (data/accuracy_set.csv).

- Offline: with the curated table, every drug must come out right (30/30).
- Live: with the curated table switched off, the automatic steps (ChEMBL, name
  rules, web) must still get most of them right. Run
  `uv run python scripts/accuracy_report.py --automatic` to see which ones miss.
"""
from collections import Counter

import pytest

from app import accuracy
from app import taxonomy as T

AUTOMATIC_MINIMUM = 22          # out of 30; ChEMBL + name rules alone reached 24 on 2026-11-20


def test_set_has_30_drugs_across_the_taxonomy():
    rows = accuracy.load_set()
    assert len(rows) == 30
    covered = {m for _, m, _ in rows}
    assert covered == set(T.MODALITIES) - {T.UNKNOWN}
    assert len({d.lower() for d, _, _ in rows}) == 30
    assert set(Counter(m for _, m, _ in rows)) <= set(T.MODALITIES)


@pytest.mark.parametrize("check", accuracy.run(use_curated=True, online=False), ids=lambda c: c.drug)
def test_curated_accuracy(check):
    assert check.call.modality == check.expected_modality
    assert check.sub_ok, f"sub-type: expected {check.expected_sub}, got {check.call.sub_modality}"


@pytest.mark.live
def test_automatic_accuracy():
    checks = accuracy.run(use_curated=False, online=True)
    right = sum(c.modality_ok for c in checks)
    misses = [f"{c.drug}: got {c.call.modality}" for c in checks if not c.modality_ok]
    assert right >= AUTOMATIC_MINIMUM, f"only {right}/30 right. Misses: {misses}"
