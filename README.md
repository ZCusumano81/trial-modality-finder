# Clinical Trial Modality Finder

A free web app that searches ClinicalTrials.gov and shows, for each trial, the
drug modality of every agent (small molecule, antibody, ADC, cell therapy, and
so on), plus where the trial's sites are, including a "China-only" flag.

The app uses only free data sources (ClinicalTrials.gov, ChEMBL, Wikidata and Wikipedia) and needs
no API keys. Drug classifications that can't be looked up automatically are
curated by hand, with AI help, and stored in `data/modalities.csv`.

## Running it on your computer

You need `uv`, a free tool that installs Python and this project's libraries.
On a Mac with Homebrew: `brew install uv`.

Then, in this folder:

```bash
uv sync                                  # install everything (first time only)
uv run pytest                            # run the tests (add -m "not live" if offline)
uv run python scripts/show_trial.py NCT03529110   # print one trial in the terminal
uv run streamlit run streamlit_app.py    # open the app in your browser
```

## Using the app

1. Type a drug (or condition, sponsor, NCT ID...) in the left panel and press **Search**.
   Drug searches include every known name (e.g. AK112 for ivonescimab).
2. Narrow the results with **Filter results**: site flag (e.g. China-only),
   modality in the experimental arms, or "contains modality" in any arm.
3. Click a row to see each agent's modality, where it came from, and the evidence.
4. Download the table as CSV, or as Excel with a second sheet listing every agent.

The "Suggest a correction" link appears once a corrections email address is set:
add `CORRECTIONS_EMAIL = "you@example.org"` to `.streamlit/secrets.toml` (locally)
or to the app's Secrets on Streamlit Community Cloud.

## Curating drugs the app can't classify

1. `uv run python scripts/find_unknowns.py` lists unclassified drugs from the
   searches in `data/saved_searches.csv` into `data/unknown_agents.csv`.
2. In Claude Code, ask: "classify the unknown agents" - Claude researches them
   and writes `data/proposed_modalities.csv`.
3. Open that file, check each row, and set `reviewed` to `yes` for the ones you accept.
4. Ask Claude to merge them (it runs `scripts/merge_reviewed.py`), run the tests, and publish.

`uv run python scripts/accuracy_report.py` checks 30 well-known drugs.

## What's in this folder

| Path | What it is |
| --- | --- |
| `streamlit_app.py` | The web app's starting point |
| `app/` | The app's code (fetching trials, site flags, modality lookup) |
| `data/modalities.csv` | The curated drug-to-modality table (always wins) |
| `data/saved_searches.csv` | Searches used to find drugs that still need review |
| `scripts/` | Curation tools, run by hand, never by the app |
| `tests/` | Automated checks |
| `CLAUDE.md` | The full spec and rules for Claude Code |

## Data sources

- [ClinicalTrials.gov](https://clinicaltrials.gov) API v2
- [ChEMBL](https://www.ebi.ac.uk/chembl/) (EMBL-EBI), CC BY-SA 3.0
- [Wikidata](https://www.wikidata.org) (CC0) and [Wikipedia](https://www.wikipedia.org) (CC BY-SA)

Modality calls are curated with AI help and may contain errors.
