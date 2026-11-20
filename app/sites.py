"""Summarize where a trial's sites are, and flag China-only trials.

Flags (one per trial):
- "China-only"               every site with a country is in China
- "China + other countries"  at least one China site and at least one elsewhere
- "No China sites"           sites listed, none in China
- "No sites listed"          the record lists no sites at all
- "Country not stated"       sites listed, but none says which country

Setting: count_greater_china. When False (the default), Hong Kong, Macau and
Taiwan are treated as separate from China, so a China + Hong Kong trial is
"China + other countries". When True, they count as China.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.trial import Site, Trial

CHINA_ONLY = "China-only"
CHINA_PLUS = "China + other countries"
NO_CHINA = "No China sites"
NO_SITES = "No sites listed"
NO_COUNTRY = "Country not stated"
SITE_FLAGS = [CHINA_ONLY, CHINA_PLUS, NO_CHINA, NO_SITES, NO_COUNTRY]

MAINLAND_CHINA = {"china", "people's republic of china", "peoples republic of china", "prc"}
GREATER_CHINA_EXTRAS = {
    "hong kong", "hong kong sar", "macau", "macao", "macau sar",
    "taiwan", "taiwan, province of china", "republic of china",
}


@dataclass
class SiteSummary:
    site_count: int
    country_counts: dict[str, int] = field(default_factory=dict)   # country -> number of sites
    flag: str = NO_SITES

    @property
    def countries(self) -> list[str]:
        """Countries sorted by number of sites (most first), then by name."""
        return sorted(self.country_counts, key=lambda c: (-self.country_counts[c], c))

    @property
    def country_count(self) -> int:
        return len(self.country_counts)

    @property
    def countries_label(self) -> str:
        """e.g. "China (12), United States (3)"."""
        return ", ".join(f"{c} ({self.country_counts[c]})" for c in self.countries)


def is_china(country: str, count_greater_china: bool = False) -> bool:
    name = country.strip().lower()
    if name in MAINLAND_CHINA:
        return True
    return count_greater_china and name in GREATER_CHINA_EXTRAS


def summarize_sites(sites: list[Site], count_greater_china: bool = False) -> SiteSummary:
    counts = Counter(s.country.strip() for s in sites if s.country and s.country.strip())
    summary = SiteSummary(site_count=len(sites), country_counts=dict(counts))

    if not sites:
        summary.flag = NO_SITES
    elif not counts:
        summary.flag = NO_COUNTRY
    else:
        china = [c for c in counts if is_china(c, count_greater_china)]
        if not china:
            summary.flag = NO_CHINA
        elif len(china) == len(counts):
            summary.flag = CHINA_ONLY
        else:
            summary.flag = CHINA_PLUS
    return summary


def summarize_trial_sites(trial: Trial, count_greater_china: bool = False) -> SiteSummary:
    return summarize_sites(trial.sites, count_greater_china)
