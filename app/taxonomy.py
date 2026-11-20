"""The modality categories, their short labels, and their order in combination labels."""
from __future__ import annotations

SMALL_MOLECULE = "Small molecule"
MAB = "Monoclonal antibody"
BISPECIFIC = "Bispecific/multispecific antibody"
ADC = "Antibody-drug conjugate (ADC)"
AOC = "Antibody-oligonucleotide conjugate (AOC)"
FUSION_PROTEIN = "Fusion protein / other recombinant protein"
PEPTIDE = "Peptide"
ENZYME = "Enzyme"
OLIGONUCLEOTIDE = "Oligonucleotide"
MRNA = "mRNA/RNA therapeutic"
CELL_THERAPY = "Cell therapy"
GENE_THERAPY = "Gene therapy"
GENE_EDITING = "Gene editing"
ONCOLYTIC_VIRUS = "Oncolytic virus"
VACCINE = "Vaccine"
RADIOPHARMACEUTICAL = "Radiopharmaceutical"
NOT_CLASSIFIED = "Placebo/standard of care/non-drug"
UNKNOWN = "Unknown"
PENDING = "Pending review"

# Order = how combination labels are sorted: newer / more complex modalities first.
MODALITIES = [
    CELL_THERAPY, GENE_THERAPY, GENE_EDITING, ONCOLYTIC_VIRUS, ADC, AOC, RADIOPHARMACEUTICAL,
    BISPECIFIC, MAB, FUSION_PROTEIN, ENZYME, PEPTIDE, OLIGONUCLEOTIDE, MRNA, VACCINE,
    SMALL_MOLECULE, UNKNOWN,
]

SHORT = {
    SMALL_MOLECULE: "small molecule", MAB: "mAb", BISPECIFIC: "bispecific", ADC: "ADC", AOC: "AOC",
    FUSION_PROTEIN: "fusion protein", PEPTIDE: "peptide", ENZYME: "enzyme",
    OLIGONUCLEOTIDE: "oligonucleotide", MRNA: "mRNA", CELL_THERAPY: "cell therapy",
    GENE_THERAPY: "gene therapy", GENE_EDITING: "gene editing", ONCOLYTIC_VIRUS: "oncolytic virus",
    VACCINE: "vaccine", RADIOPHARMACEUTICAL: "radiopharmaceutical", UNKNOWN: "pending review",
}
# Sub-types that read better than the modality in a short label (e.g. "CD19 CAR-T").
SHORT_SUB = {"siRNA", "ASO", "aptamer", "CAR-T", "CAR-NK", "TCR-T", "TIL", "PROTAC", "degrader/PROTAC", "BiTE"}

# A broad answer that a more specific one may replace (e.g. ChEMBL "Antibody" -> bispecific).
REFINES = {
    MAB: {BISPECIFIC, ADC, AOC, RADIOPHARMACEUTICAL},
    FUSION_PROTEIN: {PEPTIDE, ENZYME, MAB, BISPECIFIC, ADC, AOC},
    SMALL_MOLECULE: {RADIOPHARMACEUTICAL},
    OLIGONUCLEOTIDE: {AOC},
    GENE_THERAPY: {CELL_THERAPY},     # ChEMBL files some CAR-Ts (gene-modified cells) as "Gene"
    UNKNOWN: set(MODALITIES),
}


def order(modality: str) -> int:
    return MODALITIES.index(modality) if modality in MODALITIES else len(MODALITIES)


def short_label(modality: str, sub_modality: str = "", target: str = "") -> str:
    """e.g. ("Monoclonal antibody", "", "PD-1") -> "PD-1 mAb"; ("Cell therapy", "CAR-T", "CD19") -> "CD19 CAR-T"."""
    core = sub_modality if sub_modality in SHORT_SUB else SHORT.get(modality, modality)
    if core == "degrader/PROTAC":
        core = "degrader"
    return f"{target} {core}".strip() if target else core
