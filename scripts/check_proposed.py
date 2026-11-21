"""Cross-check data/proposed_modalities.csv against the sources the Drug Dossier app uses.

For every proposed drug (trying its name and each synonym) this asks:
- the NCI Drug Dictionary - its definition usually states the drug type
  ("An antibody-drug conjugate (ADC) composed of ..."),
- ChEMBL - molecule type ("Antibody", "Small molecule", ...),
- FDA GSRS - substance class (chemical, protein, nucleic acid, ...), only when
  NCI has no entry, because GSRS is slow.
It then marks each row: agrees / compatible / CONFLICT / no independent data,
and writes data/proposed_check.csv. Nothing in proposed_modalities.csv is changed.

    uv run python scripts/check_proposed.py
"""
from __future__ import annotations

import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import chembl  # noqa: E402
from app import taxonomy as T  # noqa: E402
from app.curated import split_synonyms  # noqa: E402
from app.names import name_key  # noqa: E402
from app.weblookup import _classify_with_rank, first_sentence  # noqa: E402

PROPOSED = ROOT / "data" / "proposed_modalities.csv"
OUT = ROOT / "data" / "proposed_check.csv"
NCI = "https://webapis.cancer.gov/drugdictionary/v1/Drugs/search"
GSRS = "https://gsrs.ncats.nih.gov/api/v1/substances/search"
HEADERS = {"User-Agent": "ClinicalTrialModalityFinder/0.1 (curation check)"}

# GSRS substance class -> modalities it is consistent with.
GSRS_FITS = {
    "chemical": {T.SMALL_MOLECULE, T.RADIOPHARMACEUTICAL, T.PEPTIDE},
    "protein": {T.MAB, T.BISPECIFIC, T.ADC, T.AOC, T.FUSION_PROTEIN, T.PEPTIDE, T.ENZYME, T.RADIOPHARMACEUTICAL},
    "nucleicAcid": {T.OLIGONUCLEOTIDE, T.MRNA, T.AOC, T.VACCINE, T.GENE_THERAPY},
    "structurallyDiverse": {T.CELL_THERAPY, T.GENE_THERAPY, T.ONCOLYTIC_VIRUS, T.VACCINE, T.GENE_EDITING},
    "polymer": {T.SMALL_MOLECULE, T.PEPTIDE},
    "mixture": set(T.MODALITIES),
}


def nci_lookup(client: httpx.Client, names: list[str]) -> dict | None:
    for n in names:
        try:
            r = client.get(NCI, params={"query": n, "matchType": "Begins", "size": 10}, timeout=30)
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        k = name_key(n)
        for res in r.json().get("results") or []:
            aliases = [a.get("name", "") for a in res.get("aliases") or []]
            if k in {name_key(res.get("name", "")), *(name_key(a) for a in aliases)}:
                definition = ((res.get("definition") or {}).get("text") or "").strip()
                return {"name": res.get("name", ""), "definition": definition, "matched": n}
    return None


def gsrs_lookup(client: httpx.Client, names: list[str]) -> str:
    for n in names[:2]:
        try:
            r = client.get(GSRS, params={"q": f'"{n}"', "top": 3}, timeout=45)
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        for s in r.json().get("content") or []:
            if name_key(s.get("_name", "")) == name_key(n):
                return s.get("substanceClass", "")
    return ""


def classify_text(*texts: str) -> tuple[str, str] | None:
    best = None
    for t in texts:
        if t and (hit := _classify_with_rank(t)) and (best is None or hit[0] < best[0]):
            best = hit
    return (best[1], best[2]) if best else None


def compatible(proposed: str, other: str) -> bool:
    """other is a broader answer that proposed refines (e.g. mAb -> bispecific)."""
    return proposed in T.REFINES.get(other, set())


def check(row: dict) -> dict:
    names = [row["agent"], *split_synonyms(row["synonyms"])]
    out = {"agent": row["agent"], "proposed": row["modality"], "proposed_sub": row["sub_modality"],
           "proposed_target": row["target"], "confidence": row["confidence"],
           "nci_name": "", "nci_says": "", "nci_definition": "", "chembl_says": "", "gsrs_class": "",
           "verdict": "", "note": ""}
    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        nci = nci_lookup(client, names)
        hit = None
        for n in names:
            if (hit := chembl.lookup(n)):
                break
        if nci:
            out["nci_name"] = nci["name"]
            out["nci_definition"] = first_sentence(nci["definition"])[:400]
            got = classify_text(nci["name"], first_sentence(nci["definition"]))
            out["nci_says"] = f"{got[0]}{' / ' + got[1] if got and got[1] else ''}" if got else ""
        if hit:
            out["chembl_says"] = f"{hit.molecule_type} ({hit.pref_name})"
        if not nci:
            out["gsrs_class"] = gsrs_lookup(client, names)

    p = row["modality"]
    nci_mod = out["nci_says"].split(" / ")[0] if out["nci_says"] else ""
    chembl_mod = hit.modality if hit else None
    if nci_mod:
        if nci_mod == p:
            out["verdict"] = "agrees"
        elif compatible(p, nci_mod):
            out["verdict"] = "compatible"
            out["note"] = f"NCI wording is broader ({nci_mod}); proposal is more specific"
        else:
            out["verdict"] = "CONFLICT"
            out["note"] = f"NCI suggests {nci_mod}"
    elif chembl_mod:
        if chembl_mod == p:
            out["verdict"] = "agrees"
        elif compatible(p, chembl_mod):
            out["verdict"] = "compatible"
            out["note"] = f"ChEMBL type is broader ({hit.molecule_type})"
        else:
            out["verdict"] = "CONFLICT"
            out["note"] = f"ChEMBL suggests {chembl_mod}"
    elif out["gsrs_class"]:
        fits = GSRS_FITS.get(out["gsrs_class"], set(T.MODALITIES))
        out["verdict"] = "compatible" if p in fits else "CONFLICT"
        out["note"] = f"GSRS substance class '{out['gsrs_class']}'" + ("" if p in fits else " doesn't fit")
    else:
        out["verdict"] = "no independent data"
    return out


def main() -> int:
    with open(PROPOSED, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("agent") or "").strip()]
    print(f"Checking {len(rows)} proposed drugs against NCI Drug Dictionary, ChEMBL and FDA GSRS ...")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, rows))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    print(f"Details in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
