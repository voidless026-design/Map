---
name: search-quality
description: >-
  Measure and fix how on-topic OpenAtlas's brain search is, so the user no longer has to check by hand whether the cited articles are really about the question. Use when the user says 'Atlas gave me unrelated results', 'why did she cite that', 'check search quality', 'did the ranking regress', or after any change to openatlas/kb/retrieve.py or store.py. Verifies with P@1, MRR@5, nDCG@5 and an off-topic rate on a look-alike fixture corpus (where the old pure-OR ranker must fail) and on queries sampled from the user's own brain; every hit explains why it matched.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# search-quality

Search-engine style retrieval: phrases, -exclusions, stopwords, a title/alias index, term coverage and a relevance gate that returns fewer results rather than off-topic ones. This skill measures it and drives fixes until the metrics pass.

## When to trigger

- Atlas answered my question about black holes with the Black Death - fix it.
- Check search quality after I changed the ranker.
- Why did she cite that article? It isn't about my question.
- Is the brain search still on-topic now that the Kiwix Wikipedia is ingested?

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Run the fixture evaluation (openatlas kb eval --fixture): known look-alike articles, known right answers.
2. Run the evaluation on the user's own brain (openatlas kb eval); add hard cases to data/eval/search_golden.jsonl as JSON lines {"q": ..., "expect": [titles], "ok": [acceptable titles]}.
3. For each failure, run openatlas kb search with the query and read each hit's why (exact title/alias, n/m words, phrase) to see which signal misfired.
4. Fix the parser, candidate sets, weights or gate in openatlas/kb/retrieve.py (or add an alias with store.add_aliases), then re-run both evaluations until they pass.

```bash
openatlas kb eval --fixture
openatlas kb eval
openatlas kb search "black hole event horizon"
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill search-quality
python -m openatlas.utils.forge doctor
```

1. openatlas kb eval --fixture exits 0: P@1 >= 0.85, MRR@5 >= 0.85, nDCG@5 >= 0.80, off-topic <= 0.15.
2. The doctor's 'Search relevance' check passes: the real ranker meets the thresholds AND the legacy pure-OR ranker fails them (proves the evaluator can catch the drift).
3. openatlas kb eval on the user's brain passes, or every failing query is listed with its hits.
4. Unknown topics return no hits (the gate says nothing instead of something unrelated), and openatlas kb ask then says the brain does not know yet.
5. pytest tests/test_search_quality.py passes offline.

## Tools this skill needs

- openatlas/kb/evaluate.py - relevance evaluator: fixture corpus, brain sampling, P@1/MRR/nDCG/off-topic, legacy ranker as a known-bad control
- openatlas/kb/retrieve.py - the ranker: query parser, title/alias index, coverage, phrase bonus, relevance gate, why
- openatlas/kb/store.py - titles + titles_fts index and add_aliases (redirects become aliases)
- openatlas doctor - 'Search relevance' check runs good vs known-bad rankers automatically

## Definition of done

- `python -m openatlas.utils.forge verify-skill search-quality` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
