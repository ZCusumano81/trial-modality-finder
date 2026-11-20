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

PLACEBO_PATTERN = re.compile(r"\b(placebo|matching placebo|saline|sham|vehicle)\b", re.I)
SOC_PATTERN = re.compile(
    r"\b(standard[- ]of[- ]care|SOC|best supportive care|BSC|supportive care|physician'?s choice|"
    r"investigator'?s choice|treatment of physician'?s choice|TPC|usual care|observation|"
    r"active surveillance|watchful waiting|no (?:intervention|treatment))\b",
    re.I,
)
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
    r"Q[1-9]W|BID|QD|TID|QW|Q2W|Q3W|Q4W|once daily|twice daily|weekly|daily|monthly)\b",
    re.I,
)
FORM_WORDS = re.compile(
    r"\b(?:for injection|injection|infusion|tablets?|capsules?|oral solution|oral suspension|"
    r"solution|suspension|intravenous(?:ly)?|subcutaneous(?:ly)?|intramuscular|i\.?v\.?|s\.?c\.?|"
    r"p\.?o\.?|oral(?:ly)?|lyophili[sz]ed powder|powder|film[- ]coated|extended[- ]release|"
    r"sustained[- ]release)\b",
    re.I,
)
COMBO_SPLIT = re.compile(
    r"\s*(?:\+|＋|\bplus\b|\bin combination with\b|\bcombined with\b|\bcombination with\b|"
    r"\bfollowed by\b|\bwith\b|\band\b|;|&)\s*",
    re.I,
)
PARENS = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")


def name_key(name: str) -> str:
    """Comparison key: lower-case, letters and digits only. "DS-8201a" -> "ds8201a"."""
    return re.sub(r"[^0-9a-zα-ω]", "", name.lower())


SCI_DOSE = re.compile(
    rf"\b\d+(?:[.,]\d+)?\s*(?:[x×*]\s*)?10\s*\^?\s*\d+(?:\s*{UNIT})?(?:\s*/\s*(?:kg|m2|dose))?", re.I)
AUC_DOSE = re.compile(r"\bAUC\s*=?\s*\d+(?:[.,]\d+)?\b", re.I)


def _tidy(text: str) -> str:
    text = SCI_DOSE.sub(" ", text)
    text = AUC_DOSE.sub(" ", text)
    text = DOSE.sub(" ", text)
    text = DOSE_WORDS.sub(" ", text)
    text = FORM_WORDS.sub(" ", text)
    # Trailing bare numbers after a space ("Erlotinib 150/100") - but keep code
    # names like "MK-3475" or "177Lu-PSMA-617", where the number follows a hyphen.
    text = re.sub(r"(?<=[A-Za-z)])\s+\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)*\s*$", " ", text)
    text = re.sub(r"[,:/]+\s*$", " ", text)
    text = re.sub(r"^\s*[,:/-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -–,.;:/")
    return text


def split_agents(raw_name: str) -> list[str]:
    """Split an intervention name that names several agents, and tidy each part.

    Parenthetical text is kept attached so candidate_names can use it as an alias.
    """
    # Don't split inside parentheses: protect them first.
    protected: list[str] = []

    def _protect(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"\x00{len(protected) - 1}\x00"

    text = PARENS.sub(_protect, raw_name)
    parts = [p for p in COMBO_SPLIT.split(text) if p and p.strip()]
    out = []
    for part in parts:
        part = re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], part)
        cleaned = _tidy(part)
        if cleaned and not re.fullmatch(r"[\d\s.,/-]*", cleaned):
            out.append(cleaned)
    return out or ([_tidy(raw_name)] if _tidy(raw_name) else [])


def candidate_names(agent_text: str) -> list[str]:
    """Names to try for one agent: the main text, then any aliases in parentheses.

    "Trastuzumab deruxtecan (T-DXd)" -> ["Trastuzumab deruxtecan", "T-DXd"]
    """
    aliases = [_tidy(a) for a in PARENS.findall(agent_text)]
    main = _tidy(PARENS.sub(" ", agent_text))
    names = []
    for n in [main, *aliases]:
        if n and len(name_key(n)) >= 2 and name_key(n) not in {name_key(x) for x in names}:
            names.append(n)
    return names


def role_of(agent_text: str, intervention_type: str = "") -> str:
    """Is this agent a real drug, a placebo, standard of care, or not a drug at all?"""
    if PLACEBO_PATTERN.search(agent_text):
        return PLACEBO
    if intervention_type.upper() in NON_DRUG_TYPES:
        return NON_DRUG
    if SOC_PATTERN.search(agent_text) or GENERIC_REGIMEN.match(agent_text.strip()):
        return STANDARD_OF_CARE
    return DRUG
