"""Fetch trials from the free ClinicalTrials.gov API (v2). No API key needed.

Two main functions:
- get_study("NCT01234567")  -> one trial's raw data
- search_studies(SearchQuery(...), max_results=200) -> raw data for many trials,
  following the API's "pageToken" to load page after page.

Errors (bad ID, trial not found, site down, too many requests) become a
CTGovError with a plain-language message the app can show.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Iterator

import httpx

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
TIMEOUT = 30.0
MAX_RETRIES = 3          # extra tries after rate limits / server hiccups
PAGE_SIZE = 100          # trials per request (API allows up to 1000)
NCT_PATTERN = re.compile(r"^NCT\d{8}$")

# Values the API accepts for status and phase filters.
STATUSES = [
    "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION",
    "COMPLETED", "SUSPENDED", "TERMINATED", "WITHDRAWN", "UNKNOWN",
]
PHASES = ["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA"]


class CTGovError(Exception):
    """A problem talking to ClinicalTrials.gov, with a message fit to show users."""


@dataclass
class SearchQuery:
    """What the user is searching for. Every field is optional."""
    text: str = ""            # free text, anywhere in the record
    condition: str = ""
    intervention: str = ""    # drug / intervention name
    sponsor: str = ""
    location: str = ""        # e.g. "China", "Boston"
    statuses: list[str] = field(default_factory=list)   # from STATUSES
    phases: list[str] = field(default_factory=list)     # from PHASES
    nct_ids: list[str] = field(default_factory=list)

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        for key, value in [
            ("query.term", self.text),
            ("query.cond", self.condition),
            ("query.intr", self.intervention),
            ("query.spons", self.sponsor),
            ("query.locn", self.location),
        ]:
            if value.strip():
                params[key] = value.strip()
        if self.statuses:
            params["filter.overallStatus"] = "|".join(self.statuses)
        if self.phases:
            params["filter.advanced"] = " OR ".join(f"AREA[Phase]{p}" for p in self.phases)
        if self.nct_ids:
            ids = [normalize_nct_id(i) for i in self.nct_ids]
            params["filter.ids"] = "|".join(ids)
        return params

    def is_empty(self) -> bool:
        return not self.to_params()


def normalize_nct_id(nct_id: str) -> str:
    """Tidy an NCT ID (" nct02578680 " -> "NCT02578680") or raise CTGovError."""
    cleaned = nct_id.strip().upper()
    if not NCT_PATTERN.match(cleaned):
        raise CTGovError(f'"{nct_id.strip()}" is not a valid NCT ID (it should look like NCT01234567).')
    return cleaned


def _request(
    client: httpx.Client,
    url: str,
    params: dict[str, str],
    bad_request_message: str = "ClinicalTrials.gov didn't accept this search. Try simpler search terms.",
) -> dict:
    """GET with polite retries on rate limits (429) and server errors (5xx)."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.get(url, params=params, timeout=TIMEOUT)
        except httpx.TransportError as exc:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise CTGovError("Couldn't reach ClinicalTrials.gov. Check your internet connection and try again.") from exc

        if response.status_code == 200:
            return response.json()
        if response.status_code == 404:
            raise CTGovError("No trial with that ID was found on ClinicalTrials.gov.")
        if response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
            wait = float(response.headers.get("Retry-After", 2 ** attempt))
            time.sleep(min(wait, 30))
            continue
        if response.status_code == 429:
            raise CTGovError("ClinicalTrials.gov is busy (too many requests). Please wait a minute and try again.")
        if response.status_code == 400:
            raise CTGovError(bad_request_message)
        raise CTGovError(f"ClinicalTrials.gov returned an error (code {response.status_code}). Please try again later.")
    raise CTGovError("ClinicalTrials.gov didn't respond. Please try again later.")  # pragma: no cover


def get_study(nct_id: str, client: httpx.Client | None = None) -> dict:
    """Fetch one trial's raw record."""
    nct_id = normalize_nct_id(nct_id)
    with _client(client) as c:
        return _request(
            c, f"{BASE_URL}/{nct_id}", {"fields": "protocolSection"},
            bad_request_message=f"ClinicalTrials.gov says {nct_id} is not a valid trial ID.",
        )


def search_studies(
    query: SearchQuery,
    max_results: int = 200,
    client: httpx.Client | None = None,
) -> tuple[list[dict], int]:
    """Run a search. Returns (raw trial records, total number of matches on the site).

    Stops after max_results trials so a very broad search doesn't take forever.
    """
    if query.is_empty():
        raise CTGovError("Please enter at least one search term or filter.")
    studies: list[dict] = []
    total = 0
    with _client(client) as c:
        for page in _pages(c, query, max_results):
            total = page.get("totalCount", total)
            studies.extend(page.get("studies", []))
            if len(studies) >= max_results:
                break
    return studies[:max_results], total


def _pages(client: httpx.Client, query: SearchQuery, max_results: int) -> Iterator[dict]:
    params = query.to_params()
    params.update({
        "fields": "protocolSection",
        "pageSize": str(min(PAGE_SIZE, max_results)),
        "countTotal": "true",
    })
    while True:
        page = _request(client, BASE_URL, params)
        yield page
        token = page.get("nextPageToken")
        if not token:
            return
        params = {k: v for k, v in params.items() if k != "countTotal"}
        params["pageToken"] = token


class _client:
    """Use the caller's httpx.Client if given (tests do this), else make a short-lived one."""

    def __init__(self, client: httpx.Client | None):
        self._given = client
        self._own: httpx.Client | None = None

    def __enter__(self) -> httpx.Client:
        if self._given is not None:
            return self._given
        self._own = httpx.Client(headers={"User-Agent": "trial-modality-finder/0.1"})
        return self._own

    def __exit__(self, *exc) -> None:
        if self._own is not None:
            self._own.close()
