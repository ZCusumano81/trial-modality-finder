"""Turn a raw ClinicalTrials.gov record into a tidy Trial object.

Any field can be missing in real records, so every lookup has a safe default.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PHASE_LABELS = {
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE2": "Phase 2",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": "Not applicable",
}


@dataclass
class Intervention:
    type: str                 # e.g. DRUG, BIOLOGICAL, DEVICE, DIETARY_SUPPLEMENT
    name: str
    description: str = ""
    other_names: list[str] = field(default_factory=list)
    arm_group_labels: list[str] = field(default_factory=list)


@dataclass
class ArmGroup:
    label: str
    type: str = ""            # e.g. EXPERIMENTAL, ACTIVE_COMPARATOR, PLACEBO_COMPARATOR
    description: str = ""
    intervention_names: list[str] = field(default_factory=list)   # e.g. "Drug: Pembrolizumab"


@dataclass
class Site:
    facility: str = ""
    city: str = ""
    country: str = ""


@dataclass
class Trial:
    nct_id: str
    title: str
    sponsor: str = ""
    status: str = ""
    phases: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    interventions: list[Intervention] = field(default_factory=list)
    arm_groups: list[ArmGroup] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://clinicaltrials.gov/study/{self.nct_id}"

    @property
    def phase_label(self) -> str:
        """["PHASE2", "PHASE3"] -> "Phase 2/3"; [] -> "Not stated"."""
        if not self.phases:
            return "Not stated"
        labels = [PHASE_LABELS.get(p, p) for p in self.phases]
        if len(labels) == 2 and all(l.startswith("Phase ") for l in labels):
            return f"{labels[0]}/{labels[1].removeprefix('Phase ')}"
        return ", ".join(labels)

    @property
    def status_label(self) -> str:
        """"ACTIVE_NOT_RECRUITING" -> "Active, not recruiting"."""
        if not self.status:
            return "Unknown"
        words = self.status.replace("_", " ").lower().replace("active not", "active, not")
        return words[0].upper() + words[1:]


def _get(data: dict, *keys, default=None):
    """Safely walk nested dicts: _get(d, "a", "b") == d["a"]["b"] or default."""
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data


def parse_study(raw: dict) -> Trial:
    """Convert one raw API record (as returned by app.ctgov) into a Trial."""
    ps = raw.get("protocolSection", raw)
    arms_module = _get(ps, "armsInterventionsModule", default={}) or {}

    interventions = [
        Intervention(
            type=i.get("type", ""),
            name=(i.get("name") or "").strip(),
            description=(i.get("description") or "").strip(),
            other_names=[n.strip() for n in i.get("otherNames", []) if n and n.strip()],
            arm_group_labels=list(i.get("armGroupLabels", [])),
        )
        for i in arms_module.get("interventions", []) or []
        if (i.get("name") or "").strip()
    ]
    arm_groups = [
        ArmGroup(
            label=(a.get("label") or "").strip(),
            type=a.get("type", ""),
            description=(a.get("description") or "").strip(),
            intervention_names=list(a.get("interventionNames", [])),
        )
        for a in arms_module.get("armGroups", []) or []
    ]
    sites = [
        Site(
            facility=(loc.get("facility") or "").strip(),
            city=(loc.get("city") or "").strip(),
            country=(loc.get("country") or "").strip(),
        )
        for loc in _get(ps, "contactsLocationsModule", "locations", default=[]) or []
    ]

    return Trial(
        nct_id=_get(ps, "identificationModule", "nctId", default=""),
        title=_get(ps, "identificationModule", "briefTitle", default="")
        or _get(ps, "identificationModule", "officialTitle", default="(no title)"),
        sponsor=_get(ps, "sponsorCollaboratorsModule", "leadSponsor", "name", default=""),
        status=_get(ps, "statusModule", "overallStatus", default=""),
        phases=list(_get(ps, "designModule", "phases", default=[]) or []),
        conditions=list(_get(ps, "conditionsModule", "conditions", default=[]) or []),
        interventions=interventions,
        arm_groups=arm_groups,
        sites=sites,
    )
