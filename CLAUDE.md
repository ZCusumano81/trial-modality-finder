# Clinical Trial Modality Finder

## Goal
Free web app to search ClinicalTrials.gov and show, for each trial: NCT ID, title,
sponsor, status, phase, indication(s), site countries and number of sites, a
China-only flag, and the drug modality of every agent, including each agent in
combination trials.

## Hard rule: no paid services
- The deployed app makes NO Claude/LLM API calls and needs no API keys.
- AI classification of drugs happens only in curation sessions I run in Claude
  Code. Results are saved to data/modalities.csv, which the app reads.

## Stack
- Python 3.11, Streamlit UI, httpx, pandas, pytest
- Hosting: Streamlit Community Cloud from a GitHub repo
- Keep it simple: no database; the curated table is a CSV in the repo

## Data rules
- Source: https://clinicaltrials.gov/api/v2/studies (free, no key). Page with
  pageToken.
- Search inputs: free text, condition, intervention/drug, sponsor, location,
  status, phase, NCT ID.
- Phase: protocolSection.designModule.phases
- Conditions: protocolSection.conditionsModule.conditions
- Interventions and arms: protocolSection.armsInterventionsModule
  (interventions[].type/name/description/otherNames, and armGroups)
- Sites: protocolSection.contactsLocationsModule.locations[].country
- Site flags: "China-only" = every site country is "China". Whether Hong Kong,
  Macau and Taiwan count as China is a setting (default: they don't). Also label
  "China + other countries" and "No sites listed". Added in Stage 3: "No China
  sites" (sites listed, none in China) and "Country not stated" (sites listed
  without countries). Sites missing a country are ignored for the flag.
  Code: app/sites.py.

## Modality taxonomy
Small molecule (sub-types: degrader/PROTAC, radioligand); Monoclonal antibody;
Bispecific/multispecific antibody; Antibody-drug conjugate (ADC);
Antibody-oligonucleotide conjugate (AOC); Fusion protein / other recombinant
protein; Peptide; Enzyme; Oligonucleotide (ASO, siRNA, aptamer); mRNA/RNA
therapeutic; Cell therapy (CAR-T, CAR-NK, TCR-T, TIL, stem cell, other); Gene
therapy (AAV, lentiviral, other); Gene editing; Oncolytic virus; Vaccine;
Radiopharmaceutical; Placebo/standard of care/non-drug (labeled, not
classified); Unknown.

## Modality lookup order (in the app)
1. data/modalities.csv (curated; always wins). Columns: agent, synonyms,
   modality, sub_modality, target, confidence, evidence, source, reviewed, date.
   Match on name and synonyms, case-insensitive.
2. ChEMBL REST API (https://www.ebi.ac.uk/chembl/api/data), molecule_type
   looked up by name or synonym. Cache responses on disk.
3. INN name-stem rules: -mab -> antibody; vedotin/deruxtecan/govitecan/
   emtansine/mafodotin/tesirine -> ADC; -cel -> cell therapy; -vec -> gene
   therapy; -rsen -> ASO; -siran -> siRNA; -cept -> fusion protein; -tide ->
   peptide; -ase -> enzyme; -tinib/-ciclib/-parib/-lisib -> small molecule.
4. Free web lookup (no API key): Wikidata (instance of / subclass of, e.g.
   "monoclonal antibody", "antibody-drug conjugate") and the Wikipedia page
   summary (keyword match such as "is a bispecific antibody", "is a CAR-T").
   Search by name and each synonym. Used when steps 1-3 find nothing, or only
   a broad answer that the web result makes more specific. Save confidence
   "low", source "wikidata" or "wikipedia", and the matched sentence or
   property as evidence. Cache responses on disk. Never use paid or keyed
   search engines (Google, Bing) and never scrape search-results pages.
5. Otherwise show "Pending review."
- Precedence tweak (agreed in planning): when a name-stem rule gives a more
  specific answer than ChEMBL's broad molecule_type (e.g. "deruxtecan" -> ADC
  vs ChEMBL "Antibody"), the name rule wins. The curated CSV still always wins.
- Seed modalities.csv with the 30 test drugs (reviewed) in Stage 4, so cases
  the rules can't tell apart (e.g. ivonescimab is bispecific, not a plain mAb)
  are right from the start.
- Combination trials: classify each experimental intervention separately; use
  armGroups to show which agents are given together; tag placebo and standard of
  care; build a combination label sorted by modality, e.g. "ADC + PD-1 mAb".

## Drug names and synonym-merged search (added before Stage 4)
Why: ClinicalTrials.gov merges synonyms only for established drugs. Tested
2026-11-20: osimertinib/AZD9291/Tagrisso all return 394 trials, but
"ivonescimab" alone misses 54 of 193 trials listed only as "AK112", and the
full name "trastuzumab deruxtecan" misses trials listed as T-DXd/DS-8201a.
Short nicknames also over-match ("T-DXd" returns Dato-DXd, patritumab
deruxtecan and ifinatamab deruxtecan trials, and trials that only mention it).
- Name cleanup: strip doses, units, routes and dose labels from intervention
  names ("Pembrolizumab 200 mg", "Ivonescimab Dose 1", "Ivonescimab RP3D",
  "AZD9291 80 mg/40 mg + placebo") before matching; keep the original text.
- Synonym list per drug, from: modalities.csv synonyms (curated), the
  otherNames trials list for an intervention, and ChEMBL synonyms (cached).
- Drug search: search each name separately with query.intr, then merge and
  de-duplicate by NCT ID (one OR query lost trials in testing).
- Verify: keep a trial only if one of its interventions (name or otherNames,
  after cleanup) matches one of the drug's names exactly, case-insensitive.
  Drop trials that only mention the drug in text.
- Display one canonical name per drug everywhere (e.g. AK112, SMT112 ->
  ivonescimab), with the original wording in the trial detail view, so counts
  and modality add up per drug, not per spelling.

## UI
- Search box plus filters: phase, status, site flag (China-only etc.),
  modality, and "contains modality X" (e.g., any trial with an ADC)
- Results table plus CSV and Excel export
- Trial detail view showing each agent's modality, source and evidence
- "Pending review" badge and a "Suggest a correction" mailto link
- Footer: data sources (ClinicalTrials.gov, ChEMBL, Wikidata/Wikipedia attribution) and a note
  that modality calls are curated with AI help and may contain errors

## Curation workflow (run by me in Claude Code, never by the app)
- scripts/find_unknowns.py runs the saved searches in data/saved_searches.csv
  and writes agents that the table, ChEMBL and rules can't resolve to
  data/unknown_agents.csv (with name, other names, description, type, NCT IDs,
  trial count).
- When I ask, classify unknown agents from their trial descriptions, other names
  and a web search. Write data/proposed_modalities.csv using the table columns.
  Use confidence "low" when the evidence is thin; never guess.
- After I review, merge reviewed rows into modalities.csv, run the tests, and
  commit and push.

## Quality
- pytest tests, including a set of 30 well-known drugs with expected
  modalities across the taxonomy (e.g., pembrolizumab, trastuzumab deruxtecan,
  osimertinib, ivonescimab, inclisiran, tisagenlecleucel)
- Handle API errors, rate limits and missing fields gracefully
- Commit to git after each working stage

## Build stages
1. Project setup, README, git
2. ClinicalTrials.gov client and parsing, with tests on real NCT IDs
3. Site-country summary and China-only flags
4. Drug-name cleanup and synonym-merged search; modality lookup (CSV,
   ChEMBL, name rules, Wikidata/Wikipedia); seeded CSV; combination handling
5. Streamlit UI and export
6. find_unknowns.py and the 30-drug accuracy test
7. Deploy: GitHub repo + Streamlit Community Cloud

## Commands
- Python and libraries are managed by `uv` (Python 3.11 in .python-version).
- Run tests: `uv run pytest`
- Run the app: `uv run streamlit run streamlit_app.py`
- Add a library: `uv add <name>`
- Layout: streamlit_app.py (entry), app/ (code), scripts/ (curation tools),
  data/ (CSVs), tests/, cache/ (ChEMBL cache, not committed)

## Working style
- The owner is not a software developer: explain in plain language, keep things
  simple, and stop after each stage so they can test it.
