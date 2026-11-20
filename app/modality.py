"""Decide the modality of every agent in a trial.

Lookup order (see CLAUDE.md):
1. Curated table (data/modalities.csv) - always wins.
2. ChEMBL molecule type.
3. Name-stem rules - win over ChEMBL when more specific (e.g. "deruxtecan" -> ADC).
4. Wikidata / Wikipedia - used when nothing was found, or only a broad answer
   ("antibody") that the web makes more specific ("bispecific antibody").
5. Otherwise "Pending review".
Placebo, standard of care and non-drug interventions are labelled, not classified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app import chembl, rules, weblookup
from app import taxonomy as T
from app.curated import CuratedEntry, CuratedTable, default_table
from app.names import DRUG, candidate_names, name_key, role_of, split_agents
from app.trial import Intervention

BROAD = {T.MAB, T.FUSION_PROTEIN}


@dataclass
class AgentCall:
    original: str                 # the intervention text as the trial wrote it
    name: str                     # one consistent display name (e.g. AK112 -> ivonescimab)
    role: str = DRUG              # drug / placebo / standard of care / non-drug
    modality: str = T.PENDING
    sub_modality: str = ""
    target: str = ""
    confidence: str = ""
    source: str = ""              # curated / chembl / name rule / wikipedia / wikidata
    evidence: str = ""
    url: str = ""
    synonyms: list[str] = field(default_factory=list)

    @property
    def pending(self) -> bool:
        return self.modality == T.PENDING

    @property
    def is_drug(self) -> bool:
        return self.role == DRUG

    @property
    def short_label(self) -> str:
        if not self.is_drug:
            return self.role
        if self.pending:
            return "pending review"
        return T.short_label(self.modality, self.sub_modality, self.target)


def _display_name(text: str) -> str:
    """ChEMBL names are upper-case: "OSIMERTINIB" -> "osimertinib", but keep code names like "SHR-A1811"."""
    return text if re.search(r"\d", text) else text.lower()


def _from_curated(original: str, e: CuratedEntry, extra_names: list[str]) -> AgentCall:
    return AgentCall(
        original=original, name=e.agent, modality=e.modality, sub_modality=e.sub_modality,
        target=e.target, confidence=e.confidence or "high", source="curated",
        evidence=e.evidence + ("" if e.reviewed.lower() in {"yes", "y", "true"} else " (not yet reviewed)"),
        synonyms=_unique([*e.all_names, *extra_names]),
    )


def _unique(names: list[str]) -> list[str]:
    seen, out = set(), []
    for n in names:
        k = name_key(n)
        if n and k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def classify_agent(original: str, names: list[str], *, online: bool = True,
                   table: CuratedTable | None = None) -> AgentCall:
    """Classify one drug, given every name we know for it (main name first)."""
    table = table or default_table()
    names = _unique(names)

    # 1. Curated table
    for n in names:
        if (e := table.find(n)):
            return _from_curated(original, e, names)

    # 2. ChEMBL
    hit = None
    if online:
        for n in names[:4]:
            if (hit := chembl.lookup(n)) and hit.modality:
                break
            hit = None
    if hit:
        # ChEMBL may know a synonym that is in the curated table.
        for n in [hit.pref_name, *hit.synonyms]:
            if (e := table.find(n)):
                return _from_curated(original, e, names)

    call = AgentCall(original=original, name=_display_name(hit.pref_name) if hit and hit.pref_name else names[0],
                     synonyms=_unique([*names, *(hit.synonyms if hit else [])]))
    if hit:
        call.modality, call.source, call.url = hit.modality, "chembl", hit.url
        call.confidence = "medium"
        call.evidence = f'ChEMBL {hit.chembl_id} molecule type: "{hit.molecule_type}"'

    # 3. Name rules (a more specific answer beats a broad ChEMBL one)
    rule = None
    for n in [*(([hit.pref_name]) if hit else []), *names]:
        if (rule := rules.classify_by_name(n)):
            break
    if rule:
        if not hit:
            call.modality, call.sub_modality, call.source = rule.modality, rule.sub_modality, "name rule"
            call.confidence, call.evidence = "low", rule.evidence
        elif rule.modality in T.REFINES.get(call.modality, set()):
            call.modality, call.sub_modality, call.source = rule.modality, rule.sub_modality, "chembl + name rule"
            call.evidence += f"; refined by {rule.evidence}"

    # 4. Web lookup when nothing found, or only a broad answer
    if online and (call.pending or (call.modality in BROAD and not call.sub_modality)):
        web_names = _unique([*(([hit.pref_name]) if hit else []), *names])[:3]
        for n in web_names:
            if (web := weblookup.lookup(n)):
                if call.pending:
                    call.modality, call.sub_modality = web.modality, web.sub_modality
                    call.source, call.confidence, call.evidence, call.url = web.source, "low", web.evidence, web.url
                    if web.page_title and call.name == names[0] and not hit:
                        call.name = _display_name(web.page_title)
                elif web.modality in T.REFINES.get(call.modality, set()):
                    call.modality, call.sub_modality = web.modality, web.sub_modality
                    call.source = f"{call.source} + {web.source}"
                    call.confidence = "low"
                    call.evidence += f'; refined by {web.source}: "{web.evidence}"'
                    call.url = web.url
                break
    return call


def classify_intervention(iv: Intervention, *, online: bool = True,
                          table: CuratedTable | None = None) -> list[AgentCall]:
    """One intervention may name several agents ("Nivolumab and Ipilimumab")."""
    parts = split_agents(iv.name) or [iv.name]
    calls = []
    for part in parts:
        role = role_of(part, iv.type)
        if role != DRUG:
            calls.append(AgentCall(original=iv.name, name=part, role=role, modality=T.NOT_CLASSIFIED,
                                   source="label", evidence=f"Recognized as {role}"))
            continue
        names = candidate_names(part)
        if len(parts) == 1:                      # other names describe the whole intervention
            names += [n for o in iv.other_names for n in candidate_names(o)]
        calls.append(classify_agent(iv.name, names or [part], online=online, table=table))
    return calls
