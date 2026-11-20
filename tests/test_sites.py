"""Tests for site-country summaries and China flags."""
import json
from pathlib import Path

import pytest

from app.sites import (
    CHINA_ONLY, CHINA_PLUS, NO_CHINA, NO_COUNTRY, NO_SITES,
    is_china, summarize_sites, summarize_trial_sites,
)
from app.trial import Site, parse_study

FIXTURES = Path(__file__).parent / "fixtures"


def sites(*countries):
    return [Site(country=c) for c in countries]


def load(nct_id):
    return parse_study(json.loads((FIXTURES / f"{nct_id}.json").read_text()))


# ---- flags, default setting (Hong Kong / Macau / Taiwan are NOT China) ----

@pytest.mark.parametrize("countries, flag", [
    (["China"], CHINA_ONLY),
    (["China", "China", "China"], CHINA_ONLY),
    (["China", "United States"], CHINA_PLUS),
    (["China", "Hong Kong"], CHINA_PLUS),
    (["China", "Taiwan"], CHINA_PLUS),
    (["China", "Macau"], CHINA_PLUS),
    (["Hong Kong"], NO_CHINA),
    (["Taiwan", "Japan"], NO_CHINA),
    (["United States"], NO_CHINA),
    ([], NO_SITES),
    (["", ""], NO_COUNTRY),
])
def test_flags_default(countries, flag):
    assert summarize_sites(sites(*countries)).flag == flag


# ---- flags with the setting on (they DO count as China) ----

@pytest.mark.parametrize("countries, flag", [
    (["China", "Hong Kong"], CHINA_ONLY),
    (["China", "Taiwan", "Macau"], CHINA_ONLY),
    (["Hong Kong"], CHINA_ONLY),
    (["Taiwan", "Japan"], CHINA_PLUS),
    (["United States"], NO_CHINA),
])
def test_flags_greater_china(countries, flag):
    assert summarize_sites(sites(*countries), count_greater_china=True).flag == flag


def test_sites_without_country_are_ignored_for_the_flag():
    s = summarize_sites(sites("China", "", "China"))
    assert s.flag == CHINA_ONLY
    assert s.site_count == 3                  # still counted as sites
    assert s.country_counts == {"China": 2}


def test_name_variants():
    assert is_china(" china ")
    assert is_china("People's Republic of China")
    assert not is_china("Macao")
    assert is_china("Macao", count_greater_china=True)
    assert is_china("Taiwan, Province of China", count_greater_china=True)


def test_country_counts_and_label():
    s = summarize_sites(sites("Japan", "China", "China", "United States", "China"))
    assert s.site_count == 5
    assert s.country_count == 3
    assert s.countries == ["China", "Japan", "United States"]       # most sites first, then A-Z
    assert s.countries_label == "China (3), Japan (1), United States (1)"


# ---- real trials ----

def test_real_trials():
    assert summarize_trial_sites(load("NCT05499390")).flag == CHINA_ONLY          # HARMONi-2
    assert summarize_trial_sites(load("NCT02578680")).flag == NO_SITES            # KEYNOTE-189
    db03 = summarize_trial_sites(load("NCT03529110"))                             # DESTINY-Breast03
    assert db03.flag == CHINA_PLUS
    assert db03.site_count == 164 and db03.country_count == 15
    assert db03.country_counts["China"] == 12
    assert summarize_trial_sites(load("NCT03529110"), count_greater_china=True).flag == CHINA_PLUS
