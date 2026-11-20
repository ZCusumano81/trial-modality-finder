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
uv run pytest                            # run the tests
uv run streamlit run streamlit_app.py    # open the app in your browser
```

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
