"""Free web lookup of a drug's modality: Wikidata + Wikipedia. No API key.

1. Wikidata finds the drug by name or alias (it knows code names like AK112)
   and gives the matching English Wikipedia page plus "instance of" labels.
2. The Wikipedia page summary's first sentence usually says what the drug is
   ("Ivonescimab is a humanized bispecific monoclonal antibody ...").

Results are low confidence, always come with the sentence or label they were
based on, and are cached on disk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app import cache
from app import taxonomy as T
from app.names import name_key

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
HEADERS = {"User-Agent": "trial-modality-finder/0.1 (open-source research tool)"}
TIMEOUT = 20.0

# Phrases in a Wikipedia first sentence, most specific first.
SENTENCE_RULES: list[tuple[str, str, str]] = [
    (r"antibody[- ](?:oligonucleotide|sirna) conjugate", T.AOC, ""),
    (r"antibody[- ]drug conjugate|\bADC\b", T.ADC, ""),
    (r"radio(?:ligand|pharmaceutical|conjugate)|radiolabel(?:l)?ed", T.RADIOPHARMACEUTICAL, ""),
    (r"\b(?:bi|tri|multi)[- ]?specific\b|T[- ]cell engager|\bBiTE\b", T.BISPECIFIC, ""),
    (r"chimeric antigen receptor|\bCAR[- ]?T\b", T.CELL_THERAPY, "CAR-T"),
    (r"\bCAR[- ]?NK\b", T.CELL_THERAPY, "CAR-NK"),
    (r"T[- ]cell receptor[- ]engineered|\bTCR[- ]T\b", T.CELL_THERAPY, "TCR-T"),
    (r"tumou?r[- ]infiltrating lymphocyte", T.CELL_THERAPY, "TIL"),
    (r"\bcell(?:ular)? therapy|stem cell", T.CELL_THERAPY, ""),
    (r"\bCRISPR\b|gene[- ]edit|base edit|zinc[- ]finger nuclease", T.GENE_EDITING, ""),
    (r"oncolytic", T.ONCOLYTIC_VIRUS, ""),
    (r"adeno[- ]associated vir|\bAAV\b", T.GENE_THERAPY, "AAV"),
    (r"lentivir", T.GENE_THERAPY, "lentiviral"),
    (r"gene therapy", T.GENE_THERAPY, ""),
    (r"\bmRNA[- ]?(?:based )?vaccine|\bvaccine\b", T.VACCINE, ""),
    (r"small interfering RNA|\bsiRNA\b", T.OLIGONUCLEOTIDE, "siRNA"),
    (r"antisense oligonucleotide|\bASO\b", T.OLIGONUCLEOTIDE, "ASO"),
    (r"\baptamer\b", T.OLIGONUCLEOTIDE, "aptamer"),
    (r"oligonucleotide", T.OLIGONUCLEOTIDE, ""),
    (r"messenger RNA|\bmRNA\b", T.MRNA, ""),
    (r"\bPROTAC\b|proteolysis[- ]targeting chimera|targeted protein degrader|\bdegrader\b",
     T.SMALL_MOLECULE, "degrader/PROTAC"),
    (r"monoclonal antibody|\bantibody\b", T.MAB, ""),
    (r"fusion protein|\bFc[- ]fusion|immunoadhesin|immunocytokine", T.FUSION_PROTEIN, ""),
    (r"enzyme replacement|recombinant (?:human )?enzyme|\benzyme\b", T.ENZYME, ""),
    (r"\bpeptide\b", T.PEPTIDE, ""),
    (r"small[- ]molecule|kinase inhibitor|\binhibitor\b", T.SMALL_MOLECULE, ""),
]
# Wikidata "instance of" labels -> modality.
WIKIDATA_LABELS: list[tuple[str, str, str]] = [
    ("antibody-drug conjugate", T.ADC, ""),
    ("bispecific antibody", T.BISPECIFIC, ""),
    ("monoclonal antibody", T.MAB, ""),
    ("chimeric antigen receptor t cell therapy", T.CELL_THERAPY, "CAR-T"),
    ("gene therapy", T.GENE_THERAPY, ""),
    ("vaccine", T.VACCINE, ""),
    ("small interfering rna", T.OLIGONUCLEOTIDE, "siRNA"),
    ("antisense oligonucleotide", T.OLIGONUCLEOTIDE, "ASO"),
    ("fusion protein", T.FUSION_PROTEIN, ""),
    ("peptide", T.PEPTIDE, ""),
    ("enzyme", T.ENZYME, ""),
]


@dataclass
class WebHit:
    modality: str
    sub_modality: str
    source: str        # "wikipedia" or "wikidata"
    evidence: str      # the sentence or label it was based on
    url: str
    page_title: str = ""


def first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(?:\s|$)", text.strip(), re.S)
    return (m.group(1) if m else text).strip()


def classify_sentence(sentence: str) -> tuple[str, str] | None:
    hit = _classify_with_rank(sentence)
    return (hit[1], hit[2]) if hit else None


def _classify_with_rank(sentence: str) -> tuple[int, str, str] | None:
    for rank, (pattern, modality, sub) in enumerate(SENTENCE_RULES):
        if re.search(pattern, sentence, re.I):
            return rank, modality, sub
    return None


def sentences_about(extract: str, names: list[str], limit: int = 4) -> list[str]:
    """The first sentence, plus later ones that describe the drug itself
    ("It is a bispecific T-cell engager ...", "Zanidatamab is ...")."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", extract.strip())[:limit]
    if not parts or not parts[0]:
        return []
    subject = "|".join(re.escape(n) for n in names if n)
    starts = re.compile(rf"^(?:It|This (?:drug|medication|antibody|agent|molecule)|"
                        rf"The (?:drug|medication|antibody|agent|molecule)|{subject})\b", re.I)
    return [parts[0], *[p for p in parts[1:] if starts.match(p)]]


def classify_extract(extract: str, names: list[str]) -> tuple[str, str, str] | None:
    """Most specific answer across the sentences about the drug: (modality, sub, sentence)."""
    best = None
    for s in sentences_about(extract, names):
        hit = _classify_with_rank(s)
        if hit and (best is None or hit[0] < best[0]):
            best = (hit[0], hit[1], hit[2], s)
    return (best[1], best[2], best[3]) if best else None


def _get_json(client: httpx.Client, url: str, params: dict | None = None) -> dict | None:
    r = client.get(url, params=params)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _fetch(name: str, client: httpx.Client) -> dict | None:
    """Return {"wikidata_id", "labels", "wiki_title", "extract"} or None."""
    found = _get_json(client, WIKIDATA_API, {
        "action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": 3})
    candidates = (found or {}).get("search") or []
    # Only accept an entity whose label or alias really is this name.
    match = next((c for c in candidates
                  if name_key(name) in {name_key(c.get("label", "")), name_key((c.get("match") or {}).get("text", ""))}),
                 None)
    labels: list[str] = []
    title = ""
    qid = ""
    if match:
        qid = match["id"]
        ent = _get_json(client, WIKIDATA_API, {
            "action": "wbgetentities", "ids": qid, "props": "claims|sitelinks", "sitefilter": "enwiki",
            "format": "json"})
        entity = ((ent or {}).get("entities") or {}).get(qid, {})
        title = ((entity.get("sitelinks") or {}).get("enwiki") or {}).get("title", "")
        ids = [c["mainsnak"]["datavalue"]["value"]["id"]
               for p in ("P31", "P279") for c in (entity.get("claims") or {}).get(p, [])
               if "datavalue" in c.get("mainsnak", {})]
        if ids:
            lab = _get_json(client, WIKIDATA_API, {
                "action": "wbgetentities", "ids": "|".join(ids[:20]), "props": "labels", "languages": "en",
                "format": "json"})
            labels = [v.get("labels", {}).get("en", {}).get("value", "")
                      for v in ((lab or {}).get("entities") or {}).values()]
    summary = _get_json(client, WIKIPEDIA_SUMMARY + quote((title or name).replace(" ", "_"), safe=""))
    extract = ""
    if summary and summary.get("type") != "disambiguation":
        extract = summary.get("extract") or ""
        title = summary.get("title") or title
    if not (labels or extract):
        return None
    return {"wikidata_id": qid, "labels": [l for l in labels if l], "wiki_title": title, "extract": extract}


def lookup(name: str, client: httpx.Client | None = None) -> WebHit | None:
    """Classify a drug from Wikipedia (preferred) or Wikidata. None if nothing usable."""
    name = name.strip()
    if len(name) < 3:
        return None
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True)
    try:
        data = cache.cached("web", name, lambda: _fetch(name, c))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    finally:
        if own:
            c.close()
    if not data:
        return None

    extract = data.get("extract", "")
    sentence = first_sentence(extract)
    # Only trust the page if its first sentence is about this drug (its title or name appears in it).
    title = data.get("wiki_title", "")
    if sentence and (name_key(name) in name_key(sentence) or (title and name_key(title) in name_key(sentence))):
        hit = classify_extract(extract, [name, title])
        if hit:
            return WebHit(hit[0], hit[1], "wikipedia", hit[2],
                          f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}", title)
    for label in data.get("labels", []):
        for key, modality, sub in WIKIDATA_LABELS:
            if key in label.lower():
                return WebHit(modality, sub, "wikidata", f'Wikidata "instance of": {label}',
                              f"https://www.wikidata.org/wiki/{data.get('wikidata_id', '')}", title)
    return None
