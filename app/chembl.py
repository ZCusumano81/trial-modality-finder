"""Look up a drug in ChEMBL (EMBL-EBI), free and with no API key.

ChEMBL knows most named drugs and their code/brand names (AZD9291 -> osimertinib)
and gives a broad molecule type ("Antibody", "Small molecule", "Antibody drug
conjugate", "Cell", "Gene", ...). Answers are cached on disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app import cache
from app import taxonomy as T

BASE = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"
FIELDS = "molecule_chembl_id,pref_name,molecule_type,max_phase,molecule_synonyms"
TIMEOUT = 20.0

# ChEMBL molecule_type -> (our modality, is_broad). Broad answers may be refined
# by a more specific name rule or web lookup.
TYPE_MAP = {
    "Small molecule": (T.SMALL_MOLECULE, False),
    "Antibody": (T.MAB, True),
    "Antibody drug conjugate": (T.ADC, False),
    "Protein": (T.FUSION_PROTEIN, True),
    "Enzyme": (T.ENZYME, False),
    "Oligonucleotide": (T.OLIGONUCLEOTIDE, False),
    "Cell": (T.CELL_THERAPY, False),
    "Gene": (T.GENE_THERAPY, False),
}


@dataclass
class ChemblHit:
    chembl_id: str
    pref_name: str
    molecule_type: str
    synonyms: list[str] = field(default_factory=list)

    @property
    def modality(self) -> str | None:
        return TYPE_MAP.get(self.molecule_type, (None, False))[0]

    @property
    def is_broad(self) -> bool:
        return TYPE_MAP.get(self.molecule_type, (None, True))[1]

    @property
    def url(self) -> str:
        return f"https://www.ebi.ac.uk/chembl/explore/compound/{self.chembl_id}"


def _fetch(name: str, client: httpx.Client | None) -> dict | None:
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "trial-modality-finder/0.1"})
    try:
        for param in ("molecule_synonyms__molecule_synonym__iexact", "pref_name__iexact"):
            r = c.get(BASE, params={param: name, "only": FIELDS, "limit": 5})
            r.raise_for_status()
            molecules = r.json().get("molecules") or []
            if molecules:
                # Prefer the most advanced record (e.g. the parent drug over a salt or research form).
                best = max(molecules, key=lambda m: float(m.get("max_phase") or 0))
                return {
                    "chembl_id": best.get("molecule_chembl_id", ""),
                    "pref_name": best.get("pref_name") or "",
                    "molecule_type": best.get("molecule_type") or "",
                    "synonyms": sorted({s.get("molecule_synonym", "") for s in best.get("molecule_synonyms") or []
                                        if s.get("molecule_synonym")}),
                }
        return None
    finally:
        if own:
            c.close()


def lookup(name: str, client: httpx.Client | None = None) -> ChemblHit | None:
    """Find a drug by name or synonym. Returns None if not found or ChEMBL is unreachable."""
    name = name.strip()
    if len(name) < 3:
        return None
    try:
        data = cache.cached("chembl", name, lambda: _fetch(name, client))
    except (httpx.HTTPError, ValueError):
        return None
    return ChemblHit(**data) if data else None
