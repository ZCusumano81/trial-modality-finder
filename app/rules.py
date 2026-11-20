"""Guess a modality from the drug's name (INN name stems). Fast, offline, rough.

Only applied to names that look like an INN (one to four plain words), so
phrases like "graft-versus-host disease prophylaxis" don't trip the "-ase" rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app import taxonomy as T


@dataclass
class RuleHit:
    modality: str
    sub_modality: str
    evidence: str


ADC_PAYLOADS = ("vedotin", "deruxtecan", "govitecan", "emtansine", "mafodotin", "tesirine",
                "ozogamicin", "soravtansine", "ravtansine", "mertansine", "duocarmazine", "tirumotecan",
                "rezetecan", "sudocetecan", "pelidotin", "bulumtecan")
RADIO = re.compile(r"\b(lutetium|lu[- ]?177|177[- ]?lu|actinium|ac[- ]?225|225[- ]?ac|radium|ra[- ]?223|"
                   r"yttrium[- ]?90|y[- ]?90|iodine[- ]?(?:i[- ]?)?131|i[- ]?131|131[- ]?i)\b", re.I)

# (pattern on the last word, modality, sub_modality, explanation)
STEM_RULES = [
    (r"mig$", T.BISPECIFIC, "", "-mig: multi-specific immunoglobulin"),
    (r"(?:mab|tug|bart)$", T.MAB, "", "-mab / -tug / -bart: monoclonal antibody"),
    (r"(?:cel|leucel|temcel)$", T.CELL_THERAPY, "", "-cel: cell therapy"),
    (r"(?:parvovec|repvec|vec)$", T.GENE_THERAPY, "", "-vec: gene therapy vector"),
    (r"rsen$", T.OLIGONUCLEOTIDE, "ASO", "-rsen: antisense oligonucleotide"),
    (r"siran$", T.OLIGONUCLEOTIDE, "siRNA", "-siran: small interfering RNA"),
    (r"cept$", T.FUSION_PROTEIN, "", "-cept: receptor fusion protein"),
    (r"tide$", T.PEPTIDE, "", "-tide: peptide"),
    (r"ase$", T.ENZYME, "", "-ase: enzyme"),
    (r"(?:tinib|ciclib|parib|lisib|rafenib|degib|zomib|platin|taxel|rubicin|tecan|sertib|metinib|"
     r"lutamide|trozole|fulvestrant|gliflozin|gliptin|statin|sartan|prazole)$",
     T.SMALL_MOLECULE, "", "small-molecule name stem"),
]
NON_PAYLOAD_SECOND_WORDS = {"pegol", "biosimilar", "injection", "infusion", "subcutaneous",
                            "intravenous", "monotherapy", "maintenance", "therapy", "treatment",
                            "hyaluronidase", "consolidation", "adjuvant", "neoadjuvant", "regimen",
                            "combination", "induction", "retreatment", "rechallenge"}
# Ordinary words that happen to end in a drug stem.
COMMON_WORDS = {"disease", "release", "increase", "decrease", "purchase", "database", "phase",
                "excel", "parcel", "peptide", "nucleotide", "oligonucleotide", "concept",
                "intercept", "accept", "except", "glucose", "lactase", "kinase", "protease"}
_INN_LIKE =re.compile(r"^[A-Za-z][A-Za-z\-]+(?: [A-Za-z][A-Za-z\-]+){0,3}$")
# Enzymes are usually "<name>ase alfa" etc.
_ENZYME_SUFFIX = re.compile(r"\b\w+ase (?:alfa|beta|gamma)\b", re.I)


# Chemotherapy regimens written as abbreviations: all small-molecule drugs.
REGIMENS = {
    "folfox": "fluorouracil + leucovorin + oxaliplatin", "mfolfox6": "fluorouracil + leucovorin + oxaliplatin",
    "folfiri": "fluorouracil + leucovorin + irinotecan", "folfirinox": "fluorouracil + leucovorin + irinotecan + oxaliplatin",
    "mfolfirinox": "fluorouracil + leucovorin + irinotecan + oxaliplatin",
    "capeox": "capecitabine + oxaliplatin", "capox": "capecitabine + oxaliplatin", "xelox": "capecitabine + oxaliplatin",
    "xeliri": "capecitabine + irinotecan", "gemox": "gemcitabine + oxaliplatin", "sox": "S-1 + oxaliplatin",
    "gp": "gemcitabine + cisplatin/carboplatin", "gc": "gemcitabine + cisplatin", "tp": "paclitaxel + cisplatin/carboplatin",
    "tc": "paclitaxel/docetaxel + carboplatin", "ec": "epirubicin + cyclophosphamide", "ac": "doxorubicin + cyclophosphamide",
    "flot": "fluorouracil + leucovorin + oxaliplatin + docetaxel", "ep": "etoposide + cisplatin",
    "s1": "tegafur + gimeracil + oteracil", "tas102": "trifluridine + tipiracil", "tegafur": "tegafur",
    "nabpaclitaxel": "albumin-bound paclitaxel",
}
# Phrases that name a drug class rather than a specific drug ("TROP2 ADC", "PD-1 inhibitors").
CLASS_PHRASES: list[tuple[str, str, str]] = [
    (r"\bADCs?\b|antibody[- ]drug conjugate", T.ADC, ""),
    (r"\bbispecific", T.BISPECIFIC, ""),
    (r"\bCAR[- ]?T\b", T.CELL_THERAPY, "CAR-T"),
    (r"\b(?:PD-?1|PD-?L1|CTLA-?4|LAG-?3|TIGIT)\b.*\b(?:inhibitors?|antibod(?:y|ies)|blockade|blockers?|mAbs?)\b",
     T.MAB, ""),
    (r"\b(?:TKIs?|tyrosine kinase inhibitors?|(?:PARP|CDK4/6|aromatase|mTOR|BTK|JAK|KRAS(?: G12[CD])?) inhibitors?|"
     r"AR antagonists?|anti-?androgens?|antiandrogens?|platinum|taxanes?|anthracyclines?|fluoropyrimidines?)\b",
     T.SMALL_MOLECULE, ""),
]


def classify_by_name(name: str) -> RuleHit | None:
    text = name.strip()
    low = text.lower()
    key = re.sub(r"[^0-9a-z]", "", low)

    if key in REGIMENS:
        return RuleHit(T.SMALL_MOLECULE, "", f"Chemotherapy regimen: {REGIMENS[key]}")
    for pattern, modality, sub in CLASS_PHRASES:
        if re.search(pattern, text, re.I):
            return RuleHit(modality, sub, f'Names a drug class ("{text}"), not a specific drug')

    if RADIO.search(low):
        return RuleHit(T.RADIOPHARMACEUTICAL, "", "Name contains a medical radioisotope")
    words = low.replace("-", " ").split()
    if any(w in ADC_PAYLOADS for w in words) and len(words) >= 2:
        return RuleHit(T.ADC, "", f"Name contains ADC payload stem \"{next(w for w in words if w in ADC_PAYLOADS)}\"")
    if any("cabtagene" in w for w in words):
        return RuleHit(T.CELL_THERAPY, "CAR-T", "-cabtagene: CAR-T cell therapy")
    # INN convention: an antibody name followed by a payload word is a conjugate
    # ("telisotuzumab adizutecan"), unless the second word is a PEG or protein suffix.
    if len(words) == 2 and words[0].endswith("mab") and len(words[1]) >= 6:
        if words[1] in NON_PAYLOAD_SECOND_WORDS:
            # e.g. "nivolumab hyaluronidase" (subcutaneous form): still the antibody.
            return RuleHit(T.MAB, "", f"Name stem rule: -mab: monoclonal antibody (\"{words[1]}\" is not a payload)")
        return RuleHit(T.ADC, "", f"Two-word antibody name (\"{words[0]} {words[1]}\") follows the "
                                  "INN pattern for antibody-drug conjugates")
    if _ENZYME_SUFFIX.search(low):
        return RuleHit(T.ENZYME, "", "-ase alfa/beta: recombinant enzyme")
    if not _INN_LIKE.match(text):
        return None
    last = words[-1] if words else ""
    if last in {"alfa", "beta", "gamma"} and len(words) >= 2:
        last = words[-2]
    if len(last) < 6 or last in COMMON_WORDS:
        return None
    for pattern, modality, sub, why in STEM_RULES:
        if re.search(pattern, last):
            return RuleHit(modality, sub, f"Name stem rule: {why}")
    return None
