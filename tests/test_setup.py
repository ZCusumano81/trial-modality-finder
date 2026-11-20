"""Stage 1 checks: the right Python, the libraries, and the data files are in place."""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODALITY_COLUMNS = [
    "agent", "synonyms", "modality", "sub_modality", "target",
    "confidence", "evidence", "source", "reviewed", "date",
]


def test_python_version_is_3_11():
    assert sys.version_info[:2] == (3, 11)


def test_libraries_import():
    import httpx, pandas, streamlit, openpyxl  # noqa: F401


def test_modalities_csv_has_spec_columns():
    with open(ROOT / "data" / "modalities.csv", newline="") as f:
        header = next(csv.reader(f))
    assert header == MODALITY_COLUMNS


def test_saved_searches_csv_exists():
    assert (ROOT / "data" / "saved_searches.csv").exists()
