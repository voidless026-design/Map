---
name: kb-library
description: >-
  Let the brain soak up whole offline encyclopedias (multi-gigabyte Kiwix ZIM files such as Wikipedia, Wiktionary, Stack Exchange, Gutenberg) inside Atlas, without ever downloading the same file twice. Use when the user says 'download Wikipedia for the brain', 'add a Kiwix book', 'is my download finished', 'pause the download', 'open the offline Wikipedia', or drops .zim files into the library folder. Verifies each file against the official SHA-256 checksum before it goes live, refuses duplicates, replaces an older version only after the new one verified, and confirms the articles are searchable afterwards.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# kb-library

The Library tab and openatlas kb library: the official Kiwix catalog, resumable checksum-verified downloads, feeding each book into the brain in resumable batches, and reading it with Kiwix's own reader (kiwix-serve) embedded in Atlas.

## When to trigger

- Download the English Wikipedia without pictures so Atlas knows more.
- How far along is my Kiwix download? Pause it while I game.
- I copied a .zim file into the library folder - add it to the brain.
- A newer Wikipedia is out; update mine without keeping two copies.

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Find the book: `openatlas kb library catalog wikipedia` (words) or `openatlas kb library catalog wikipedia_en_all` (a name - lists maxi / nopic / mini), or the Library tab's search. Rows already in the library show In library.
2. Download it by name, e.g. `openatlas kb library get wikipedia_en_all_nopic` (the newest version is picked; a name that fits several books lists them to choose from). A duplicate is refused with the reason; an older copy makes this an update. Never write placeholders like <id> in commands for the user - give the real name or number.
3. Watch progress with `openatlas kb library list` (each book has a number in brackets); `openatlas kb library pause 1` / `resume 1` for one book, or no number for all. Closed the terminal mid-download? `openatlas kb library resume` (or `resume --background` to survive closing it again), the same `get`, or opening the app all continue from the .part file - never from zero.
4. Once verified, the book feeds the brain in batches of 500 articles (openatlas kb library ingest runs it now); Wikipedia articles update the ones already learned instead of duplicating them.
5. Storage: `openatlas kb where` shows the data folder, free space and a ready-to-paste line for each mounted drive.
6. Read it inside Atlas: openatlas kb library serve (needs kiwix-serve: sudo dnf install kiwix-tools) or the Read button in the Library tab.

```bash
openatlas kb where
openatlas kb library catalog wikipedia
openatlas kb library catalog wikipedia_en_all
openatlas kb library get wikipedia_en_all_nopic
openatlas kb library list
openatlas kb library pause 1
openatlas kb library resume --background
openatlas kb library ingest
openatlas kb library verify
openatlas kb library serve
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill kb-library
python -m openatlas.utils.forge doctor
```

1. `openatlas kb library verify 1` (the book's number from `list`) recomputes the SHA-256 and matches the checksum published by Kiwix (meta4 or .sha256); a mismatch deletes the file and marks it failed.
2. Asking for the same book again (same uuid, file name, checksum, or an equal/newer version) is refused; only an older copy allows an update, and the old file is removed only after the new one verified and was ingested.
3. After ingest, openatlas kb search for a few article titles from the book returns them first (openatlas kb eval samples this).
4. The doctor's 'Kiwix library' check passes: a resumed download hashes identically to a straight one, duplicates are refused, an update is detected and a corrupted file is rejected.
5. A download interrupted by closing the terminal resumes from its .part file (HTTP Range) with `get`, `resume` or `resume 1`, and a second process is refused the same .part file.
6. A book name resolves to the newest file even when it is past the first catalog page, and an ambiguous name lists the choices instead of guessing.
7. pytest tests/test_library.py passes offline.

## Tools this skill needs

- openatlas/kb/library.py - catalog (OPDS, paged, search by name via `find_books` / `resolve`), meta4 checksums, Range-resume download, duplicate/update rules, libzim ingest, adopt hand-copied files
- openatlas/kb/kiwix.py - starts kiwix-serve on loopback and serves it under /kiwix inside Atlas
- libzim (pip install libzim) - reads ZIM files; kiwix-tools (dnf) - the reader
- openatlas doctor - 'Kiwix library' check runs the resume, duplicate, update and corruption fixtures

## Definition of done

- `python -m openatlas.utils.forge verify-skill kb-library` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
