"""Search trials by drug modality (e.g. every ADC trial in breast cancer).

ClinicalTrials.gov doesn't know modalities, so we:
1. search for known drugs of that modality by name (curated table + ChEMBL's
   list of clinical-stage drugs of that type), many names per request;
2. search intervention text for modality keywords ("antibody-drug conjugate",
   "bispecific", "CAR-T"...) to catch new and code-named drugs;
3. classify every trial found, and keep those where an agent really has the
   modality ("confirmed"). Keyword hits whose drugs are still pending review
   are kept as "possible" so they can be checked.
Very broad modalities (antibodies, small molecules) need a narrowing search
term; for those we run the plain search and filter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import httpx

from app import cache
from app import taxonomy as T
from app.combos import TrialModalities
from app.ctgov import CTGovError, SearchQuery, search_studies
from app.curated import CuratedTable, default_table
from app.names import name_key
from app.pipeline import analyze_all
from app.trial import Trial, parse_study

CHEMBL_LIST = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"
BATCH_CHARS = 900               # keep each OR-query to a sensible URL length


@dataclass(frozen=True)
class ModalityTarget:
    label: str                  # shown in the menu
    modality: str
    sub_modality: str = ""      # "" = any sub-type
    keywords: tuple[str, ...] = ()
    chembl_type: str = ""       # ChEMBL molecule_type listing known drugs of this kind
    broad: bool = False         # needs a narrowing search term

    def matches(self, modality: str, sub: str) -> bool:
        if modality != self.modality:
            return False
        return not self.sub_modality or self.sub_modality.lower() in sub.lower()


TARGETS: list[ModalityTarget] = [
    ModalityTarget("Antibody-drug conjugate (ADC)", T.ADC,
                   keywords=('"antibody-drug conjugate"', '"antibody drug conjugate"', "ADC"),
                   chembl_type="Antibody drug conjugate"),
    ModalityTarget("Antibody-oligonucleotide conjugate (AOC)", T.AOC,
                   keywords=('"antibody-oligonucleotide conjugate"', '"antibody oligonucleotide conjugate"',
                             '"antibody-siRNA"', "AOC")),
    ModalityTarget("Bispecific/multispecific antibody", T.BISPECIFIC,
                   keywords=("bispecific", '"bi-specific"', "trispecific", "multispecific", '"T-cell engager"',
                             "BiTE")),
    ModalityTarget("Cell therapy (all)", T.CELL_THERAPY,
                   keywords=('"CAR-T"', '"CAR T"', '"chimeric antigen receptor"', '"CAR-NK"', '"TCR-T"',
                             '"tumor infiltrating lymphocytes"', '"cell therapy"'), chembl_type="Cell"),
    ModalityTarget("Cell therapy: CAR-T", T.CELL_THERAPY, "CAR-T",
                   keywords=('"CAR-T"', '"CAR T"', '"chimeric antigen receptor"'), chembl_type="Cell"),
    ModalityTarget("Gene therapy", T.GENE_THERAPY,
                   keywords=('"gene therapy"', "AAV", '"adeno-associated"', "lentiviral"), chembl_type="Gene"),
    ModalityTarget("Gene editing", T.GENE_EDITING,
                   keywords=("CRISPR", '"gene editing"', '"gene-edited"', '"base editing"')),
    ModalityTarget("Oncolytic virus", T.ONCOLYTIC_VIRUS, keywords=("oncolytic",)),
    ModalityTarget("Radiopharmaceutical", T.RADIOPHARMACEUTICAL,
                   keywords=("radioligand", "radiopharmaceutical", "177Lu", "lutetium", "actinium", "225Ac",
                             '"radium-223"')),
    ModalityTarget("Oligonucleotide (all)", T.OLIGONUCLEOTIDE,
                   keywords=("siRNA", "antisense", "oligonucleotide", "aptamer"), chembl_type="Oligonucleotide"),
    ModalityTarget("Oligonucleotide: siRNA", T.OLIGONUCLEOTIDE, "siRNA",
                   keywords=("siRNA", '"small interfering RNA"'), chembl_type="Oligonucleotide"),
    ModalityTarget("Oligonucleotide: ASO", T.OLIGONUCLEOTIDE, "ASO",
                   keywords=("antisense", "ASO"), chembl_type="Oligonucleotide"),
    ModalityTarget("mRNA/RNA therapeutic", T.MRNA, keywords=("mRNA",)),
    ModalityTarget("Fusion protein / other recombinant protein", T.FUSION_PROTEIN,
                   keywords=('"fusion protein"', '"Fc fusion"')),
    ModalityTarget("Enzyme", T.ENZYME, keywords=('"enzyme replacement"',), chembl_type="Enzyme"),
    ModalityTarget("Peptide", T.PEPTIDE, keywords=("peptide",)),
    ModalityTarget("Small molecule: degrader/PROTAC", T.SMALL_MOLECULE, "degrader",
                   keywords=("PROTAC", "degrader", '"protein degrader"')),
    ModalityTarget("Vaccine", T.VACCINE, keywords=("vaccine",), broad=True),
    ModalityTarget("Monoclonal antibody", T.MAB, broad=True),
    ModalityTarget("Small molecule (all)", T.SMALL_MOLECULE, broad=True),
]
TARGETS_BY_LABEL = {t.label: t for t in TARGETS}


@dataclass
class ModalitySearchResult:
    target: ModalityTarget
    confirmed: list[TrialModalities] = field(default_factory=list)
    possible: list[TrialModalities] = field(default_factory=list)
    known_drugs: int = 0                                     # drug names searched
    searches: dict[str, int] = field(default_factory=dict)  # search description -> trials returned
    candidates: int = 0                                      # trials classified
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


def _clean_chembl_name(name: str) -> str:
    """"MIPOMERSEN SODIUM" -> "mipomersen"; keep codes ("SHR-A1811") as they are."""
    name = re.sub(r"\s+(SODIUM|HYDROCHLORIDE|ACETATE|MESYLATE|POTASSIUM|TRIFLUOROACETATE)$", "", name.strip(), flags=re.I)
    name = re.sub(r"\s*\(.*\)$", "", name)
    return name if re.search(r"\d", name) else name.lower()


def chembl_drugs(molecule_type: str) -> list[str]:
    """Clinical-stage drug names of one ChEMBL type (cached)."""
    def fetch() -> list[str]:
        r = httpx.get(CHEMBL_LIST, params={"molecule_type": molecule_type, "max_phase__gte": 1,
                                           "only": "pref_name", "limit": 1000}, timeout=60)
        r.raise_for_status()
        return sorted({_clean_chembl_name(m["pref_name"]) for m in r.json().get("molecules", []) if m.get("pref_name")})
    try:
        return cache.cached("chembl_list", molecule_type, fetch)
    except (httpx.HTTPError, ValueError):
        return []


def known_drug_names(target: ModalityTarget, *, online: bool = True,
                     table: CuratedTable | None = None) -> list[str]:
    table = table or default_table()
    names: list[str] = []
    for e in table.entries:
        if target.matches(e.modality, e.sub_modality):
            names += [e.agent, *[s for s in e.synonyms if len(name_key(s)) >= 4 and len(s.split()) <= 3]]
    if online and target.chembl_type:
        names += chembl_drugs(target.chembl_type)
    seen, out = set(), []
    for n in names:
        k = name_key(n)
        if len(k) >= 4 and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def or_batches(terms: list[str], limit: int = BATCH_CHARS) -> list[str]:
    """Group terms into "a" OR "b" OR ... queries of limited length."""
    batches, current = [], []
    for t in terms:
        quoted = t if t.startswith('"') or " " not in t and "-" not in t else f'"{t}"'
        if current and len(" OR ".join([*current, quoted])) > limit:
            batches.append(" OR ".join(current))
            current = []
        current.append(quoted)
    if current:
        batches.append(" OR ".join(current))
    return batches


def keyword_pattern(target: ModalityTarget) -> re.Pattern | None:
    words = [k.strip('"') for k in target.keywords]
    if not words:
        return None
    return re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(w) for w in words) + r")(?![\w-])", re.I)


def _described_as(tm: TrialModalities, intervention_name: str, pattern: re.Pattern) -> bool:
    """Does this intervention's own name / other names / description use the modality keyword?"""
    for iv in tm.trial.interventions:
        if iv.name == intervention_name:
            return bool(pattern.search(" ".join([iv.name, *iv.other_names, iv.description])))
    return False


def _has_narrowing(q: SearchQuery) -> bool:
    return any(v.strip() for v in (q.text, q.condition, q.sponsor, q.location)) or bool(q.nct_ids)


def search_modality(
    target: ModalityTarget,
    base_query: SearchQuery | None = None,
    *,
    any_arm: bool = False,
    max_results: int = 200,
    online: bool = True,
    table: CuratedTable | None = None,
    search_fn: Callable[[SearchQuery, int], tuple[list[dict], int]] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ModalitySearchResult:
    """Find trials with this modality. any_arm=False looks only at experimental arms."""
    base = base_query or SearchQuery()
    run = search_fn or (lambda q, n: search_studies(q, max_results=n))
    result = ModalitySearchResult(target=target)
    raw_by_id: dict[str, Trial] = {}
    from_keywords: set[str] = set()
    per_search = max(max_results, 100)

    def search(label: str, q: SearchQuery, keyword: bool = False) -> None:
        try:
            studies, _ = run(q, per_search)
        except CTGovError as e:
            result.warnings.append(f"{label}: {e}")
            return
        result.searches[label] = len(studies)
        for s in studies:
            t = parse_study(s)
            raw_by_id.setdefault(t.nct_id, t)
            if keyword:
                from_keywords.add(t.nct_id)

    if target.broad:
        if not _has_narrowing(base):
            raise CTGovError(f'"{target.label}" covers too many trials on its own. Add a condition, sponsor, '
                             "location or free-text term to narrow the search.")
        search("Your search terms (then filtered by modality)", base)
    else:
        names = known_drug_names(target, online=online, table=table)
        result.known_drugs = len(names)
        for i, batch in enumerate(or_batches(names), 1):
            search(f"Known drug names, batch {i}", SearchQuery(**{**base.__dict__, "intervention": batch}))
        if target.keywords:
            search("Keywords: " + ", ".join(k.strip('"') for k in target.keywords),
                   SearchQuery(**{**base.__dict__, "intervention": " OR ".join(target.keywords)}), keyword=True)

    trials = list(raw_by_id.values())
    limit = max_results * 3
    if len(trials) > limit:
        result.truncated = True
        trials = trials[:limit]
    result.candidates = len(trials)
    keyword_re = keyword_pattern(target)
    for tm in analyze_all(trials, progress, online=online):
        drugs = tm.drugs if any_arm else tm.experimental_drugs
        if any(target.matches(a.modality, a.sub_modality) for a in drugs):
            result.confirmed.append(tm)
        elif (tm.trial.nct_id in from_keywords and keyword_re
              and any(a.pending and _described_as(tm, a.original, keyword_re) for a in drugs)):
            result.possible.append(tm)
    if len(result.confirmed) > max_results:
        result.truncated = True
        result.confirmed = result.confirmed[:max_results]
    return result
