# Apollo Theater shows, 1934–1969: a structured dataset

This repo turns Marv Goldberg's *Apollo Theater Shows* list (`uncamarvy.txt`, © 2019 Marv Goldberg) into tidy tables for visualization. The list covers 1,531 weekly bills. They are resolved to about 2,900 canonical performers, enriched with act type and genre. Wikidata/MusicBrainz links are chosen but not yet verified (see the end of this file).

## Outputs (`data/out/`)

| File | Grain | Notes |
|---|---|---|
| `shows.csv` | 1 row per dated bill | `show_type` is one of regular, dj_revue, gospel, closed, movie, play, legit, jewel_box. Also has `host` (DJ presenter, e.g. Dr. Jive), `package_title` (e.g. "Rhythm & Blues Show of 1955"), `revue_title` (1930s–40s house revues), `held_over`, `duration_days`, `week_end`, `date_suspect`, `raw_text`, `source_line`. |
| `performers.csv` | 1 row per canonical act | `act_type`, `genres` (pipe-separated), `real_name` and `goldberg_note` (from Goldberg's NOTES), `members` (for ensembles), `first_date`/`last_date`, `n_appearances`, `n_headlines`, `billed_as` (every spelling seen), `wikidata_qid`, `mbid`, `wikipedia_url`. Every enriched field has a `*_confidence` column. |
| `appearances.csv` | show × act | `billing_order`, `billed_as` (exactly as printed), `role_hint` (e.g. "tap dancer"), `is_headliner` (first-billed), `featured_of` (for "(with X)" billings), `correction_of` (for Goldberg's "s/b" fixes). |
| `aliases.csv` | spelling → performer | `source` is one of `billed`, `seed` (Goldberg's notes), `llm`, `manual`, `rule`. |
| `group_members.csv` | group → member | e.g. *Tim, George, & Vivian* → Tim Moore, George Wiltshire, Vivian Harris |
| `coappearances.csv` | weighted edge list | Pairs of acts on the same bill, with `n_shows`, `first_year`, `last_year`. For network views. |
| `apollo.json` | nested bundle | `{meta, shows: [{…, acts: [...]}], performers: {id: {...}}}`. Loads directly into D3/Observable. |

**Caveats**
- Coverage after 1960 is deliberately sparse. Goldberg: "the list is not in any sense complete from here on."
- Act types and genres are LLM-assisted. For one-off obscure acts they are often educated guesses, marked `low` confidence. Filter on confidence when it matters.
- Performer merges follow Goldberg's notes. For example, Spider Bruce *is* John Mason, Garbage is Marshall Rogers, and "Jackie" Mabley is Moms Mabley.

## Pipeline

```bash
python3 -m venv .venv && .venv/bin/pip install rapidfuzz numpy requests pyyaml pytest
.venv/bin/python pipeline/parse.py        # 1. text -> data/interim/shows.jsonl, raw_appearances.jsonl, parse_log.txt
.venv/bin/python pipeline/normalize.py    # 2. canonical performers, groups, alias_candidates.json
.venv/bin/python pipeline/enrich.py ...   # 3. act types / genres / external IDs (see module docstring)
.venv/bin/python pipeline/build.py        # 4. data/out/*
.venv/bin/python -m pytest pipeline/tests
```

**1. Parse** (deterministic) handles these source quirks:
- wrapped lines
- `;`-separated bills
- Oxford-comma trios (`Ford, Bowie, & Bennie`)
- leading `[labels]`, i.e. DJ hosts, gospel, closed, movie, held over, durations
- per-act parentheticals: roles, `(with X)`, `(s/b X)`, alias hints
- editorial `[inserts]`
- revue/production titles
- one source date typo (`05/01/58` corrected to 1959 and flagged)

Every dated line becomes exactly one show. Dropped lines (captions, asides) are listed in `parse_log.txt`.

**2. Normalize** does the following:
- builds deterministic keys (case and punctuation folding, band suffixes stripped, `3`/`Three`, `Bros.`)
- applies `pipeline/aliases_seed.yaml`, transcribed from Goldberg's NOTES
- applies the LLM decisions in `data/interim/alias_decisions/`
- applies hand fixes from `pipeline/aliases_manual.yaml`

Fuzzy near-duplicates that were never billed together are written to `alias_candidates.json` for review. If performer IDs change between runs, the enrichment results are re-keyed automatically.

**3. Enrich** keeps its results in `data/enrichment/*.json`, keyed by `performer_id`, so a re-run only processes new performers.
- **Act types:** Sonnet subagents classified every performer. An earlier Haiku pass failed `pipeline/check_types.py` and is kept in `batches/rejected_haiku/`.
- **Genres:** Sonnet tagged performers with 3+ shows, using a controlled vocabulary.
- **External IDs:** `enrich.py search-ids` queries the Wikidata and MusicBrainz search APIs for candidates. An LLM picks among those candidates only, and `verify-ids` re-fetches every chosen ID before it is kept. IDs never come from model memory.

## Test page

`viz/index.html` loads `apollo.json` from the same folder. It draws every bill as a year-by-week grid colored by show type, plus the 25 most-billed acts, with hover details and a per-year table. To view it locally, serve the two files together, e.g. copy `data/out/apollo.json` into `viz/` and run `python3 -m http.server`.

## Deferred: external IDs

The Wikidata/MusicBrainz links are searched and chosen but not yet verified. The candidates are in `data/enrichment/id_candidates.json` and the 594 picks are in `id_choices.json`. To finish, run `python pipeline/enrich.py verify-ids && python pipeline/build.py`. Verification resumes where it left off and follows Wikidata redirects.
