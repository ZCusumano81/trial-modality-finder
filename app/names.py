"""Clean up intervention names as trials write them, so they can be matched.

Trials write things like "Pembrolizumab 200 mg", "Ivonescimab Dose 1",
"Trastuzumab deruxtecan (T-DXd)" or "AZD9291 80 mg/40 mg + placebo".

- split_agents("AZD9291 80 mg/40 mg + placebo") -> ["AZD9291", "placebo"]
- candidate_names("Trastuzumab deruxtecan (T-DXd)") -> ["Trastuzumab deruxtecan", "T-DXd"]
- name_key("DS-8201a") -> "ds8201a"   (used to compare names)
- role_of(...) -> "drug", "placebo", "standard of care" or "non-drug"
"""
from __future__ import annotations

import re

# ---- roles ----
DRUG = "drug"
PLACEBO = "placebo"
STANDARD_OF_CARE = "standard of care"
NON_DRUG = "non-drug"

NON_DRUG_TYPES = {"PROCEDURE", "RADIATION", "DEVICE", "BEHAVIORAL", "DIAGNOSTIC_TEST", "DIETARY_SUPPLEMENT"}

PLACEBO_PATTERN = re.compile(r"\b(placebos?|matching placebo|saline|sham|vehicle)\b", re.I)
SOC_PATTERN = re.compile(
    r"\b(standard[- ]of[- ]care|SOC|best supportive care|BSC|supportive care|physician'?s choice|"
    r"investigator'?s choice|treatment of physician'?s choice|TPC|usual care|observation|"
    r"active surveillance|watchful waiting|no (?:intervention|treatment))\b",
    re.I,
)
# Things typed as a "drug" that are really procedures, radiotherapy or study activities.
NON_DRUG_PATTERN = re.compile(
    r"\b(?:radiotherapy|radiation|irradiation|SBRT|SABR|SCRT|IMRT|SRS|SRT|proton therapy|brachytherapy|"
    r"surgery|surgical|resection|operation|non[- ]operative|HAIC|TACE|RFA|ablation|transplant(?:ation)?|"
    r"(?:allo|auto)?[- ]?HS?CT|stem cell transplant\w*|"
    r"questionnaire|survey|interview|assessment|management|education|counsel+ing|exercise|physiotherapy|"
    r"manual therapy|"
    r"biopsy|blood (?:draw|sample)|sample collection|imaging|PET|MRI|CT scan|ultrasound|ctDNA|"
    r"data collection|follow[- ]up|observation)\b|\b(?:group|cohort)\s*$",
    re.I,
)
# Phrases that describe a step of a protocol, not a specific drug.
GENERIC_TREATMENT = re.compile(
    r"^(?:randomi[sz]ation|sample|samples|pharmacological study|non-intervention research|control arm|"
    r"rescue medications?|systemic therapy|other anti-?cancer therapy|targeted drugs?|chemotherapeutic drugs?|"
    r"chemotherapy drugs?|induction therapy|maintenance(?: therapy)?|neoadjuvant (?:therapy|chemotherapy)|"
    r"pre-?treatment|post-?CR (?:consolidation|treatment)|consolidation|intrathecal|intolerable toxicity|"
    r"standard|cervical spine|a dose of.*|\d+%|positive control|comparator)$", re.I)

# Generic regimen words with no specific drug ("platinum-based chemotherapy").
GENERIC_REGIMEN = re.compile(
    r"^(?:(?:platinum|platinum[- ]based|investigator'?s choice|standard|systemic|adjuvant|"
    r"neoadjuvant|combination|doublet|triplet|cytotoxic|conventional|induction|consolidation|"
    r"maintenance|first[- ]line|second[- ]line)\s+)*(?:chemotherapy|chemo|endocrine therapy|"
    r"hormone therapy|hormonal therapy|immunotherapy|targeted therapy|radiotherapy|chemoradiotherapy|"
    r"chemoradiation|surgery|radiation)$",
    re.I,
)

# ---- cleanup patterns ----
UNIT = r"(?:mg|g|µg|μg|ug|mcg|ng|ml|mL|l|IU|MIU|U|units?|cells?|vg|GBq|mCi|MBq|%)"
DOSE = re.compile(
    rf"\b\d+(?:[.,]\d+)?(?:\s*[-–/]\s*\d+(?:[.,]\d+)?)*\s*{UNIT}"
    rf"(?:\s*/\s*(?:kg|m2|m²|m\^2|day|d|week|wk|dose|ml|mL|L))*\b",
    re.I,
)
DOSE_WORDS = re.compile(
    r"\b(?:dose\s*(?:level\s*)?\d+|dose\s*[a-z]\b|high[- ]dose|low[- ]dose|mid[- ]dose|fixed[- ]dose|"
    r"RP[123]D|MTD|cohort\s*\w+|arm\s*\w+|part\s*\w+|level\s*\d+|regimen\s*\w+|q[1-9]w|q\d+d|"
    r"Q[1-9]W|BID|QD|TID|QW|Q2W|Q3W|Q4W|once daily|twice daily|weekly|daily|monthly|"
    r"(?:treatment |study |experimental |control |\w+-line )?(?:group|arm)$|regimen$|protocol$)\b",
    re.I,
)
FORM_WORDS = re.compile(
    r"\b(?:for injection|injection|infusion|tablets?|capsules?|oral solution|oral suspension|"
    r"solution|suspension|intravenous(?:ly)?|subcutaneous(?:ly)?|intramuscular|i\.?v\.?|s\.?c\.?|"
    r"p\.?o\.?|oral(?:ly)?|lyophili[sz]ed powder|powder|film[- ]coated|extended[- ]release|"
    r"sustained[- ]release|liposom(?:e|al)|albumin[- ]bound|protein[- ]bound|nanoparticle albumin[- ]bound|"
    r"polymeric micelles?|micelles?|nanoparticles?|-?albumin|for oral use)\b|\bnab-(?=[a-z])",
    re.I,
)
COMBO_SPLIT = re.compile(
    r"\s*(?:\bwith or without\b|\bwith/without\b|\bor\b|\+/-|±|\+|＋|\bplus\b|\bin combination with\b|\bcombined with\b|\bcombination with\b|"
    r"\bfollowed by\b|\bwith\b|\band\b|;|&|,(?!\d)|(?<=[a-z]{3})\s*/\s*(?=[A-Za-z]{3}))\s*",
    re.I,
)
PARENS = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")


FULLWIDTH = str.maketrans({"（": "(", "）": ")", "，": ",", "、": ",", "；": ";", "：": ":", "＋": "+",
                           "／": "/", "－": "-", "　": " "})


def normalize_punctuation(text: str) -> str:
    """Turn Chinese/Japanese full-width punctuation into the plain kind."""
    return text.translate(FULLWIDTH)


def name_key(name: str) -> str:
    """Comparison key: lower-case, letters and digits only. "DS-8201a" -> "ds8201a"."""
    return re.sub(r"[^0-9a-zα-ω]", "", name.lower())


SCI_DOSE = re.compile(
    rf"\b\d+(?:[.,]\d+)?\s*(?:[x×*]\s*)?10\s*\^?\s*\d+(?:\s*{UNIT})?(?:\s*/\s*(?:kg|m2|dose))?", re.I)
AUC_DOSE = re.compile(r"\bAUC\s*=?\s*\d+(?:[.,]\d+)?\b", re.I)


TYPE_PREFIX = re.compile(
    r"^\s*(?:drug|biological|biologic|genetic|combination product|other|dietary supplement|radiation|"
    r"procedure|device|behavioral|diagnostic test)\s*:\s*", re.I)


def _tidy(text: str) -> str:
    text = TYPE_PREFIX.sub("", text)
    text = SCI_DOSE.sub(" ", text)
    text = AUC_DOSE.sub(" ", text)
    text = DOSE.sub(" ", text)
    text = DOSE_WORDS.sub(" ", text)
    text = FORM_WORDS.sub(" ", text)
    # Trailing bare numbers after a space ("Erlotinib 150/100") - but keep code
    # names like "MK-3475" or "177Lu-PSMA-617", where the number follows a hyphen.
    text = re.sub(r"(?<=[a-z)])\s+\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)*\s*$", " ", text)
    text = re.sub(r"[,:/]+\s*$", " ", text)
    text = re.sub(r"^\s*[,:/-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -–,.;:/")
    return text


# Arm labels written before a drug: "A1: SHR-A1811", "investigational drug: HLX37".
ARM_PREFIX = re.compile(
    r"^\s*(?:[A-Z]\d{1,2}|arm\s*\w+|cohort\s*\w+|group\s*\w+|investigational (?:drug|product)|"
    r"experimental(?: drug)?|active comparator|control)\s*:\s*", re.I)
EMBEDDED_TYPE = re.compile(r"\s+(?:Drug|Biological|Other)\s*:\s*")
# Words trailing a drug name that describe how/when it's given.
TRAILING_NOISE = re.compile(
    r"\s+(?:monotherapy|combined|combination|(?:low|medium|high)[- ]dose|until disease progression.*|"
    r"via\b.*|for \d.*cycles?.*|should be.*|is injected.*|IN\s*≥.*|maintenance after.*|- \d+ cycles?)$", re.I)

# Regimens written as abbreviations, expanded into their drugs so each is classified.
REGIMEN_COMPONENTS = {
    name_key(k): v for k, v in {
        "FOLFOX": ["fluorouracil", "leucovorin", "oxaliplatin"],
        "mFOLFOX6": ["fluorouracil", "leucovorin", "oxaliplatin"],
        "FOLFIRI": ["fluorouracil", "leucovorin", "irinotecan"],
        "FOLFIRINOX": ["fluorouracil", "leucovorin", "irinotecan", "oxaliplatin"],
        "mFOLFIRINOX": ["fluorouracil", "leucovorin", "irinotecan", "oxaliplatin"],
        "mFOLFORINOX": ["fluorouracil", "leucovorin", "irinotecan", "oxaliplatin"],
        "FOLFOXIRI": ["fluorouracil", "leucovorin", "oxaliplatin", "irinotecan"],
        "mFOLFOXIRI": ["fluorouracil", "leucovorin", "oxaliplatin", "irinotecan"],
        "CAPOX": ["capecitabine", "oxaliplatin"], "CapeOX": ["capecitabine", "oxaliplatin"],
        "XELOX": ["capecitabine", "oxaliplatin"], "XELIRI": ["capecitabine", "irinotecan"],
        "GEMOX": ["gemcitabine", "oxaliplatin"], "GnP": ["gemcitabine", "paclitaxel"],
        "SOX": ["tegafur-gimeracil-oteracil", "oxaliplatin"],
        "SOX chemotherapy": ["tegafur-gimeracil-oteracil", "oxaliplatin"],
        "FLOT": ["fluorouracil", "leucovorin", "oxaliplatin", "docetaxel"],
        "EC": ["epirubicin", "cyclophosphamide"], "AC": ["doxorubicin", "cyclophosphamide"],
        "EP": ["etoposide", "cisplatin"],
        "CHOP": ["cyclophosphamide", "doxorubicin", "vincristine", "prednisone"],
        "R-CHOP": ["rituximab", "cyclophosphamide", "doxorubicin", "vincristine", "prednisone"],
        "R-mini-CHOP": ["rituximab", "cyclophosphamide", "doxorubicin", "vincristine", "prednisone"],
        "R-CVP": ["rituximab", "cyclophosphamide", "vincristine", "prednisone"],
        "BR": ["bendamustine", "rituximab"],
    }.items()
}
# Common misspellings in trial records -> correct name (tried as an extra candidate).
SPELLING_FIXES = {
    name_key(k): v for k, v in {
        "capcitabine": "capecitabine", "vincrisitne": "vincristine", "tioguanin": "tioguanine",
        "prenisolone": "prednisolone", "5- fluorouracil": "fluorouracil", "5-FU": "fluorouracil",
        "l-leucovorin": "levoleucovorin", "6-Mercaptopurine": "mercaptopurine",
        "tegafur-gimeracil-oteracil potassium": "tegafur", "tegafur-gimeracil-oteracil": "tegafur",
        "liposome-entrapped mitoxantrone": "mitoxantrone", "carbonilumab": "cadonilimab",
    }.items()
}


def _balance_parens(text: str) -> str:
    """Drop a stray ")" or "(" left over from a split ("prednisone)")."""
    if text.count("(") != text.count(")"):
        text = text.replace("(", " ").replace(")", " ")
    return re.sub(r"\s+", " ", text).strip()


def split_agents(raw_name: str) -> list[str]:
    """Split an intervention name that names several agents, and tidy each part.

    Parenthetical text is kept attached so candidate_names can use it as an alias.
    """
    raw_name = normalize_punctuation(raw_name)
    # Don't split inside parentheses: protect them first.
    protected: list[str] = []

    def _protect(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"\x00{len(protected) - 1}\x00"

    text = PARENS.sub(_protect, raw_name)
    text = ARM_PREFIX.sub("", text)
    text = EMBEDDED_TYPE.sub(" + ", text)               # "AK129 Drug: cadonilimab" -> two agents
    parts = [p for p in COMBO_SPLIT.split(text) if p and p.strip()]
    out = []
    for part in parts:
        part = re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], part)
        cleaned = TRAILING_NOISE.sub("", _tidy(part)).strip(" -–,.;:/")
        cleaned = _balance_parens(cleaned)
        if cleaned and not re.fullmatch(r"[\d\s.,/-]*", cleaned):
            out.extend(REGIMEN_COMPONENTS.get(name_key(cleaned), [cleaned]))
    return out or ([_tidy(raw_name)] if _tidy(raw_name) else [])


def candidate_names(agent_text: str) -> list[str]:
    """Names to try for one agent: the main text, then any aliases in parentheses.

    "Trastuzumab deruxtecan (T-DXd)" -> ["Trastuzumab deruxtecan", "T-DXd"]
    """
    agent_text = normalize_punctuation(agent_text)
    aliases = [_tidy(a) for inner in PARENS.findall(agent_text) for a in re.split(r",(?!\d)", inner)]
    main = _tidy(PARENS.sub(" ", agent_text))
    names = []
    for n in [main, *aliases]:
        if n and len(name_key(n)) >= 2 and name_key(n) not in {name_key(x) for x in names}:
            names.append(n)
    fixes = [SPELLING_FIXES[name_key(n)] for n in names if name_key(n) in SPELLING_FIXES]
    return names + [f for f in fixes if name_key(f) not in {name_key(x) for x in names}]


CODE_NAME = re.compile(r"^([A-Za-z]{2,6})[\s-]?(\d{2,7}[A-Za-z]?\d*)$")


def code_variants(name: str) -> list[str]:
    """"AMG 386" -> ["AMG-386", "AMG386", "AMG 386"] (registries write code names differently)."""
    m = CODE_NAME.match(name.strip())
    if not m:
        return []
    a, b = m.groups()
    return [v for v in (f"{a}-{b}", f"{a}{b}", f"{a} {b}") if v != name.strip()]


def role_of(agent_text: str, intervention_type: str = "") -> str:
    """Is this agent a real drug, a placebo, standard of care, or not a drug at all?"""
    if PLACEBO_PATTERN.search(agent_text):
        return PLACEBO
    if intervention_type.upper() in NON_DRUG_TYPES or NON_DRUG_PATTERN.search(agent_text):
        return NON_DRUG
    if (SOC_PATTERN.search(agent_text) or GENERIC_REGIMEN.match(agent_text.strip())
            or GENERIC_TREATMENT.match(agent_text.strip())):
        return STANDARD_OF_CARE
    return DRUG
