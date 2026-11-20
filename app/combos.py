"""Put a trial's agents together arm by arm and build combination labels.

For each arm (from armGroups) we list the agents given together, tag placebo
and standard of care, and build a label sorted by modality, e.g.
"PD-1/VEGF bispecific + Nectin-4 ADC". The trial's main label comes from its
experimental arms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app import taxonomy as T
from app.curated import CuratedTable
from app.modality import AgentCall, classify_intervention
from app.names import NON_DRUG, PLACEBO, STANDARD_OF_CARE, name_key
from app.trial import Intervention, Trial

EXPERIMENTAL_TYPES = {"EXPERIMENTAL", "OTHER", ""}
COMPARATOR_TYPES = {"ACTIVE_COMPARATOR", "PLACEBO_COMPARATOR", "SHAM_COMPARATOR", "NO_INTERVENTION"}


@dataclass
class Arm:
    label: str
    type: str
    agents: list[AgentCall] = field(default_factory=list)   # all agents, incl. placebo etc.

    @property
    def drugs(self) -> list[AgentCall]:
        """Real drugs only, one per drug, sorted by modality then name."""
        seen, out = set(), []
        for a in self.agents:
            if a.is_drug and name_key(a.name) not in seen:
                seen.add(name_key(a.name))
                out.append(a)
        return sorted(out, key=lambda a: (T.order(a.modality) if not a.pending else 99, a.name.lower()))

    @property
    def tags(self) -> list[str]:
        roles = {a.role for a in self.agents if not a.is_drug}
        return [r for r in (PLACEBO, STANDARD_OF_CARE, NON_DRUG) if r in roles]

    @property
    def is_experimental(self) -> bool:
        return self.type.upper() in EXPERIMENTAL_TYPES

    @property
    def combination_label(self) -> str:
        """e.g. "PD-1 mAb + small molecule (+ placebo)". Repeated labels are shown once."""
        parts: list[str] = []
        for a in self.drugs:
            if a.short_label not in parts:
                parts.append(a.short_label)
        label = " + ".join(parts)
        extras = [t for t in self.tags if t != NON_DRUG]
        if not label:
            return " + ".join(extras) or ("non-drug" if NON_DRUG in self.tags else "no agents listed")
        if PLACEBO in extras:
            label += " (+ placebo)"
        return label

    @property
    def is_combination(self) -> bool:
        return len(self.drugs) > 1


@dataclass
class TrialModalities:
    trial: Trial
    interventions: dict[str, list[AgentCall]]       # intervention name -> its agents
    arms: list[Arm]

    @property
    def all_agents(self) -> list[AgentCall]:
        return [a for calls in self.interventions.values() for a in calls]

    @property
    def drugs(self) -> list[AgentCall]:
        """Every real drug in the trial, once each."""
        seen, out = set(), []
        for a in self.all_agents:
            if a.is_drug and name_key(a.name) not in seen:
                seen.add(name_key(a.name))
                out.append(a)
        return sorted(out, key=lambda a: (T.order(a.modality) if not a.pending else 99, a.name.lower()))

    @property
    def experimental_arms(self) -> list[Arm]:
        exp = [a for a in self.arms if a.is_experimental and a.drugs]
        return exp or [a for a in self.arms if a.drugs][:1]

    @property
    def experimental_drugs(self) -> list[AgentCall]:
        seen, out = set(), []
        for arm in self.experimental_arms:
            for a in arm.drugs:
                if name_key(a.name) not in seen:
                    seen.add(name_key(a.name))
                    out.append(a)
        return out

    @property
    def combination_label(self) -> str:
        """The experimental arms' labels; several distinct ones are joined with " | "."""
        labels: list[str] = []
        for arm in self.experimental_arms:
            if arm.combination_label not in labels:
                labels.append(arm.combination_label)
        return " | ".join(labels) or "no drugs listed"

    @property
    def modalities(self) -> list[str]:
        """Every modality in the trial (all arms), in taxonomy order."""
        found = {a.modality for a in self.drugs}
        return [m for m in [*T.MODALITIES, T.PENDING] if m in found]

    @property
    def experimental_modalities(self) -> list[str]:
        found = {a.modality for a in self.experimental_drugs}
        return [m for m in [*T.MODALITIES, T.PENDING] if m in found]

    @property
    def has_pending(self) -> bool:
        return any(a.pending for a in self.drugs)


def _strip_type_prefix(text: str) -> str:
    """Arm groups list interventions as "Drug: Pembrolizumab" - drop the "Drug: " part."""
    return re.sub(r"^\s*[A-Za-z ]+?:\s*", "", text, count=1).strip()


def analyze_trial(trial: Trial, *, online: bool = True, table: CuratedTable | None = None) -> TrialModalities:
    calls: dict[str, list[AgentCall]] = {}
    by_key: dict[str, list[AgentCall]] = {}
    for iv in trial.interventions:
        if iv.name in calls:
            continue
        calls[iv.name] = classify_intervention(iv, online=online, table=table)
        by_key[name_key(iv.name)] = calls[iv.name]

    arms: list[Arm] = []
    for g in trial.arm_groups:
        agents: list[AgentCall] = []
        for ref in g.intervention_names:
            found = calls.get(_strip_type_prefix(ref)) or by_key.get(name_key(_strip_type_prefix(ref)))
            if found:
                agents += found
        # Some records link interventions to arms only from the intervention side.
        for iv in trial.interventions:
            if g.label and g.label in iv.arm_group_labels:
                agents += [a for a in calls[iv.name] if a not in agents]
        arms.append(Arm(label=g.label, type=g.type, agents=agents))

    if not arms or not any(a.agents for a in arms):
        # No usable arm information: treat everything as one arm.
        arms = [Arm(label="All interventions", type="", agents=[a for c in calls.values() for a in c])]
    return TrialModalities(trial=trial, interventions=calls, arms=arms)
