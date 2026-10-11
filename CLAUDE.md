# Apollo Theater viz: project notes and handoff

This file is the working notes for future sessions. `README.md` is the dataset documentation: output schema, pipeline commands, and caveats. Read both before changing anything.

## Goal
Turn Marv Goldberg's Apollo Theater show list (`uncamarvy.txt`, 1934–1969) into a clean, enriched dataset for D3/Observable visualizations: timelines, career arcs, co-billing networks, and genre trends. The approved plan was a 4-stage pipeline: parse → normalize → enrich → build.

## Status (as of 2026-10-10)

| Stage | State | Notes |
|---|---|---|
| 1. Parse (`pipeline/parse.py`) | ✅ done | 1,531 shows, 8,973 appearances. Every dated line becomes one show. 6 editorial lines dropped (see `data/interim/parse_log.txt`). |
| 2. Normalize (`pipeline/normalize.py`) | ✅ done | 2,915 performers and 84 groups with resolved members. Merges come from Goldberg's notes (`aliases_seed.yaml`), Sonnet decisions on 277 fuzzy clusters (`data/interim/alias_decisions/`), and 11 hand merges (`aliases_manual.yaml`). |
| 3a. Act types | ✅ done | All 2,915 performers, by Sonnet. Haiku was tried first and rejected (see Lessons). |
| 3b. Genres | ✅ done | The 778 performers with 3+ shows, by Sonnet, using a controlled vocabulary. |
| 3c. External IDs | ⏸ **deferred** | API candidates were searched for 778 performers, and Sonnet picked 594 (342 QIDs, 442 MBIDs). **Not verified yet**, so nothing is in the outputs. |
| 4. Build (`pipeline/build.py`) | ✅ done | `data/out/*` is current (without IDs). |
| Test page (`viz/index.html`) | ✅ done | Published privately at https://claude.ai/artifact/Hd4Hgi7cXJSK2t8oNktdRJ. To update it, republish `viz/index.html` with `files: {"apollo.json": "data/out/apollo.json"}`. |
| Tests | ✅ 8 passing | `.venv/bin/python -m pytest -q pipeline/tests` |

## To do next
1. **Verify IDs.** Run `.venv/bin/python pipeline/enrich.py verify-ids && .venv/bin/python pipeline/build.py`. It takes about 15–25 min because of rate limits, resumes where it left off, and follows Wikidata redirects. The first attempt was stopped by Claude Code during a machine-wide memory shortage, not by a bug; check free memory before starting it. Afterwards, spot-check a sample of `data/enrichment/ids.json` and republish the test page.
2. **Review borderline merges.** These were flagged as uncertain by the Sonnet adjudicators and are worth a human look. To undo a merge, add a `keep_separate` entry to `pipeline/aliases_manual.yaml` and re-run normalize → build.
   - John Henry → Juano Hernandez (based on a Goldberg parenthetical)
   - Rhythm Kings → 3 Rhythm Kings
   - Tramp Band + Cowans' Musical Madcaps (merged as one act)
   - Shorts Davis → Shorty Davis
   - Benny Green → Bennie Green
   - Hendricks & Ross → Lambert Hendricks & Ross
   - Bud Harris & Hank/Frank Radcliff
   - Henry Wells / Henry Wills
   - Red Garland Trio → Red Garland, and similar "X Trio" → "X" merges
3. **Optional: wider genre coverage.** Genres currently cover only acts with 3+ shows. Run `enrich.py prep-genres --min-shows 1` to cover the rest, then a Sonnet pass, then `collect genres`.
4. **Build the real visualizations.** Ideas the data already supports:
   - career swimlanes
   - a co-billing network from `coappearances.csv`
   - genre share by year (streamgraph)
   - the DJ-revue era (1955+)
   - the house comedians' tenure
5. ~~**Housekeeping.**~~ Done 2026-10-11: git repo at https://github.com/jdetmer04/apollo_theater_viz (branch `main`). `.gitignore` excludes `.venv/`, caches, and `data/enrichment/batches/`.

## Lessons and decisions (keep following these)
- **Use Sonnet, not Haiku, for classification.** Haiku at 370 performers per batch defaulted to blanket rules (Ruth Brown and Lavern Baker as MC/DJ, Lionel Hampton as a dancer). It failed `pipeline/check_types.py` on every batch. Sonnet at about 245 per batch passed. Gate any new LLM batch with a checker before collecting it.
- **IDs never come from model memory.** The LLM may only choose among API search candidates, and `verify-ids` re-fetches each one. Keep it that way.
- **Goldberg's notes win.** For example, Spider Bruce *is* John Mason, so they are one performer, `spider-bruce`. When in doubt, keep acts separate; a false merge is worse than a missed one.
- **Solo performers and duos/groups containing them are different acts.** Charlie Ray is not Charlie & Ray. Ensemble membership goes in `group_members.json`.
- **Performer IDs are slugs of display names** and can change when names or merges change. `normalize.py` re-keys `data/enrichment/*.json` automatically by comparing against the previous `data/interim/appearances_norm.jsonl`. **Don't delete that file**, and always run normalize before build.
- **Enrichment batch files share names across rounds** (`types_out_01.json` and so on). Run `enrich.py collect <kind>` and archive a round's batch files before starting the next round, or they will be overwritten.
- **API politeness.** MusicBrainz allows at most 1 request per second, and Wikidata returns 429s under load. Long runs need `run_in_background` with a 2-hour timeout; the default 30-minute limit killed one run.

## Known data quirks (documented, not bugs)
- `is_headliner` means first-billed, which in the 1930s isn't always the star.
- A few source bills list the same act twice (e.g. 1951-02-01 "Earles"), which produces duplicate appearance rows. `n_appearances` counts distinct shows, so it is unaffected.
- One source date typo: `05/01/58`, which sits among 1959 bills, is corrected to 1959-05-01 with `date_suspect=true`.
- From 6/2/50 to 3/15/51, shows opened on Thursday, not Friday (an editorial note dropped by the parser). Dates come from the source, so nothing is wrong, but `week_end` assumes a 7-day run.
- Bare first names inside comedy ensembles ("Tim", "George", "Vivian") resolve through `member_aliases` in the seed file, following Goldberg's note that a lone "Vivian" is Vivian Harris. Bare surnames ("Ford", "Ross") are deliberately left unlinked.
- About half the act types are `low` confidence, mostly one-off obscure acts. The visualizations should expose or filter by confidence.

## Layout
```
uncamarvy.txt              source (never edit)
pipeline/                  parse.py, normalize.py, enrich.py, build.py, check_types.py,
                           aliases_seed.yaml, aliases_manual.yaml, tests/
data/interim/              parser and normalizer outputs, alias_decisions/ (LLM merge decisions)
data/enrichment/           act_types.json, genres.json, id_candidates.json, id_choices.json,
                           batches/ (LLM inputs/outputs, rejected_haiku/, ids_round1-2/)
data/out/                  final CSVs + apollo.json
viz/index.html             test page (loads apollo.json from the same folder)
.venv/                     python deps: rapidfuzz numpy requests pyyaml pytest
```
