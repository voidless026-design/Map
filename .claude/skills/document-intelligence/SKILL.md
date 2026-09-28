---
name: document-intelligence
description: >-
  Let E.V read the person's own PDFs, Word files, Markdown, text and saved web pages and answer questions about them with page-cited quotes, so they don't have to hunt through a document to check what an AI claimed. Use when the user says 'what does this contract say about…', 'summarise this PDF', 'find the budget in my report', 'which documents can you read', or drops a file into the chat. Verifies that every answer quotes a passage with its page number, that files outside the allowed folders are refused, and that the Quality Assurance check labels each claim against the quoted pages.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# document-intelligence

Let E.V read the person's own PDFs, Word files, Markdown, text and saved web pages and answer questions about them with page-cited quotes, so they don't have to hunt through a document to check what an AI claimed. Use when the user says 'what does this contract say about…', 'summarise this PDF', 'find the budget in my report', 'which documents can you read', or drops a file into the chat. Verifies that every answer quotes a passage with its page number, that files outside the allowed folders are refused, and that the Quality Assurance check labels each claim against the quoted pages.

## When to trigger

- Summarise the lease PDF I just dropped in and tell me the bond amount.
- What does my project report say about the budget?
- Which documents can you read?
- Find where my contract mentions termination.

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Drop the file into the chat (paperclip) or put it in ~/Documents, ~/Downloads or ~/Desktop (or OPENATLAS_EV_DOC_ROOTS).
2. Ask E.V a question about it; she calls read_document (auto-runs: reading is local).
3. Read the answer with its page-cited quotes and the Quality check badges underneath.

```bash
openatlas ev chat
openatlas doctor
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill document-intelligence
python -m openatlas.utils.forge doctor
```

1. Every factual sentence in the answer quotes or cites a passage with its page number.
2. A file outside the allowed folders is refused with the list of allowed folders.
3. The Quality check card shows each claim as supported / unsupported / unverified against the quoted pages.
4. The doctor's 'E.V document reader' check passes on its Word and Markdown fixtures.

## Tools this skill needs

- openatlas/ev/skills/documents.py - extract text per page (pypdf, python-docx, html), find passages, folder limits
- openatlas/ev/skills/qa.py - claim-by-claim check against the quoted pages
- openatlas doctor - 'E.V document reader' fixture check

## Definition of done

- `python -m openatlas.utils.forge verify-skill document-intelligence` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
