---
name: kb-curate
description: >-
  Grow and check OpenAtlas's local knowledge base (the brain) from the user's fields-of-study taxonomy and Wikipedia, with CC BY-SA attribution. Use when the user says 'teach the brain about topology', 'how big is the brain', 'add these fields to the knowledge base', 'pause learning', or asks a question that should be answered from the brain with citations. Verifies that every seed resolves to a real, non-disambiguation article, is retrievable in the top 5 for its own title, carries attribution, and is not duplicated.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# kb-curate

The brain is a local SQLite/FTS5 store on your PC or external HDD. It learns in tiers behind one progress bar: your ~1,800 fields of study, then Wikipedia Vital Articles level 4, then each field's category (depth 1) and relevant subcategories (depth 2). This skill queues topics, checks progress and proves that what was learned can be found again.

## When to trigger

- "Teach the brain about algebraic topology."
- "How far along is the knowledge base? How much disk does it use?"
- "Add the Engineering division to the brain first."
- "What does the brain know about Bayesian statistics?" (answer with citations)
- "Pause learning while I game."

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Check size, tiers and free disk space with `openatlas kb stats`.
2. Queue a topic ahead of the rest with `openatlas kb boost`, or the whole taxonomy with `openatlas kb plan`.
3. Ingest now (`openatlas kb ingest`) or leave the systemd unit / `openatlas kb daemon` to grow it politely in the background.
4. Answer from the brain with `openatlas kb ask`; every sentence cites a stored article and its licence.

```bash
openatlas kb stats
openatlas kb seeds
openatlas kb boost "Algebraic topology"
openatlas kb ingest --max 25
openatlas kb search "algebraic topology"
openatlas kb ask "What is a homotopy?"
openatlas kb pause
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill kb-curate
python -m openatlas.utils.forge doctor
```

1. Each ingested seed resolved to a real article: redirects are followed and disambiguation pages are skipped and logged (`openatlas.kb.wikipedia`).
2. Each seed title is retrievable in the top 5 of `openatlas kb search` for its own title (the doctor's 'Brain retrievability' check samples this automatically).
3. Every stored document keeps its source URL, revision id and the CC BY-SA 4.0 attribution.
4. No duplicates: documents are keyed by canonical title, so re-ingesting updates in place.
5. Ingestion refuses to run with less than 20 GB free and honours the pause flag.

## Tools this skill needs

- `openatlas/kb/taxonomy.py` - parses `data/taxonomy/fields_of_study.md` into seeds
- `openatlas/kb/wikipedia.py` - MediaWiki API client (maxlag, serial, Retry-After)
- `openatlas/kb/ingest.py` - tiered queue, relevance filter, disk guard
- `openatlas/kb/retrieve.py` - BM25 + optional vectors (RRF)
- Local Ollama (optional) - `nomic-embed-text` for vectors and a small model for cited answers

## Definition of done

- `python -m openatlas.utils.forge verify-skill kb-curate` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
