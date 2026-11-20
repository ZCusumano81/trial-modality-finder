"""Tests for name-stem rules and for reading Wikipedia sentences (offline)."""
import pytest

from app import taxonomy as T
from app.rules import classify_by_name
from app.weblookup import classify_extract, classify_sentence


@pytest.mark.parametrize("name, modality, sub", [
    ("pembrolizumab", T.MAB, ""),
    ("trastuzumab deruxtecan", T.ADC, ""),
    ("enfortumab vedotin", T.ADC, ""),
    ("telisotuzumab adizutecan", T.ADC, ""),          # two-word antibody name pattern
    ("volrustomig", T.BISPECIFIC, ""),
    ("tisagenlecleucel", T.CELL_THERAPY, ""),
    ("lisocabtagene maraleucel", T.CELL_THERAPY, "CAR-T"),
    ("beremagene geperpavec", T.GENE_THERAPY, ""),
    ("tofersen", T.OLIGONUCLEOTIDE, "ASO"),
    ("inclisiran", T.OLIGONUCLEOTIDE, "siRNA"),
    ("etanercept", T.FUSION_PROTEIN, ""),
    ("tirzepatide", T.PEPTIDE, ""),
    ("alglucosidase alfa", T.ENZYME, ""),
    ("osimertinib", T.SMALL_MOLECULE, ""),
    ("abemaciclib", T.SMALL_MOLECULE, ""),
    ("niraparib", T.SMALL_MOLECULE, ""),
    ("alpelisib", T.SMALL_MOLECULE, ""),
    ("lutetium Lu 177 dotatate", T.RADIOPHARMACEUTICAL, ""),
    ("177Lu-PSMA-617", T.RADIOPHARMACEUTICAL, ""),
])
def test_stem_rules(name, modality, sub):
    hit = classify_by_name(name)
    assert hit is not None, name
    assert (hit.modality, hit.sub_modality) == (modality, sub)


@pytest.mark.parametrize("name", [
    "graft versus host disease prophylaxis", "XYZ-99999", "AK112", "nivolumab hyaluronidase",
    "pembrolizumab subcutaneous", "treatment", "Vitamin B12",
])
def test_stem_rules_leave_alone(name):
    hit = classify_by_name(name)
    assert hit is None or hit.modality != T.ADC and hit.modality != T.ENZYME


@pytest.mark.parametrize("sentence, modality, sub", [
    ("Ivonescimab is a humanized bispecific monoclonal antibody.", T.BISPECIFIC, ""),
    ("Datopotamab deruxtecan is a Trop-2-directed antibody-drug conjugate.", T.ADC, ""),
    ("Tisagenlecleucel is a CAR T cells medication.", T.CELL_THERAPY, "CAR-T"),
    ("Inclisiran is a small interfering RNA (siRNA).", T.OLIGONUCLEOTIDE, "siRNA"),
    ("Osimertinib is a small-molecule kinase inhibitor.", T.SMALL_MOLECULE, ""),
    ("Vepdegestrant is a PROTAC estrogen receptor degrader.", T.SMALL_MOLECULE, "degrader/PROTAC"),
    ("Talimogene laherparepvec is an oncolytic virus therapy.", T.ONCOLYTIC_VIRUS, ""),
    ("Pembrolizumab is a humanized monoclonal antibody.", T.MAB, ""),
])
def test_wikipedia_sentences(sentence, modality, sub):
    assert classify_sentence(sentence) == (modality, sub)


def test_reads_follow_on_sentence_about_the_drug():
    extract = ("Tarlatamab, sold under the brand name Imdelltra, is an anti-cancer medication used for "
               "small cell lung cancer. It is a bispecific T-cell engager that binds DLL3 and CD3.")
    modality, sub, sentence = classify_extract(extract, ["tarlatamab"])
    assert modality == T.BISPECIFIC
    assert sentence.startswith("It is a bispecific")


def test_ignores_sentences_about_other_drugs():
    extract = ("Foo is a monoclonal antibody against X. "
               "Researchers combined it in trials with enfortumab vedotin, an antibody-drug conjugate.")
    modality, _, _ = classify_extract(extract, ["foo"])
    assert modality == T.MAB


def test_short_labels():
    assert T.short_label(T.MAB, "", "PD-1") == "PD-1 mAb"
    assert T.short_label(T.ADC) == "ADC"
    assert T.short_label(T.CELL_THERAPY, "CAR-T", "CD19") == "CD19 CAR-T"
    assert T.short_label(T.SMALL_MOLECULE, "degrader/PROTAC", "ER") == "ER degrader"
