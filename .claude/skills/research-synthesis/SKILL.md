---
name: research-synthesis
description: >-
  Ask E.V a research question and get an answer synthesised from the brain (Wikipedia, Kiwix books, past cases) and, with approval, the public web - every claim numbered [n] to its source and checked automatically, so the user no longer verifies an AI's research by hand. Use when the user asks 'what do you know about…', 'explain…', 'research… for me', or 'what's the latest on…'. Verifies that citations map to real retrieved passages, that web searches wait for approval, and that the Quality check flags any unsupported sentence.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# research-synthesis

Ask E.V a research question and get an answer synthesised from the brain (Wikipedia, Kiwix books, past cases) and, with approval, the public web - every claim numbered [n] to its source and checked automatically, so the user no longer verifies an AI's research by hand. Use when the user asks 'what do you know about…', 'explain…', 'research… for me', or 'what's the latest on…'. Verifies that citations map to real retrieved passages, that web searches wait for approval, and that the Quality check flags any unsupported sentence.

## When to trigger

- What do you know about black holes?
- Research the history of the Snowy Mountains Scheme for me.
- What's the latest on solid-state batteries? You can search the web.
- Explain how CRISPR works, with sources.

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Ask the question in the chat; E.V calls search_brain (and read_article for detail).
2. For current events she proposes web_search - approve the card if you want the public web used.
3. Read the answer; click [n] to open a source; open the Quality check card to see each claim's verdict.

```bash
openatlas ev chat
openatlas kb search "black holes"
openatlas kb eval --fixture
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill research-synthesis
python -m openatlas.utils.forge doctor
```

1. Every [n] in the answer points to a passage E.V actually retrieved (the source list in the message footer).
2. web_search never runs without an approved card.
3. The Quality check shows zero unsupported claims, or E.V says what she couldn't verify.
4. openatlas kb eval --fixture passes, so retrieval is on-topic.

## Tools this skill needs

- openatlas/ev/skills/research.py - search_brain, read_article, web_search (approval)
- openatlas/kb/retrieve.py - on-topic ranking with why each hit matched
- openatlas/ev/skills/qa.py - automatic claim check

## Definition of done

- `python -m openatlas.utils.forge verify-skill research-synthesis` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
