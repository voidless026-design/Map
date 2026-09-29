# OpenAtlas 🗺️

**A free, open-source, local OSINT toolkit. It is a key-free reimplementation of
[OAtlas](https://github.com/FauvidoTechnologies/open-atlas)'s AA (Aggregate & Analyze)
workflow, with an evidence-first investigation pipeline, a minimal web GUI and a
knowledge base (the "brain") that keeps growing on your own disk.**

- **Real investigations, not true/false.**
  - Give it a name, username, email, phone number, domain, IP address or image.
  - It queries up to 24 free public sources in parallel and reads the top result pages.
  - It cross-checks what it finds, then **re-checks every finding automatically**.
  - Each finding is labelled *confirmed*, *refuted* or *unverified*, with the source link and the reason.
- **Doesn't take over your PC.**
  - Only one local-AI request runs at a time, and models are unloaded when idle.
  - A memory guard refuses to load a model that won't fit, and ML models are loaded once.
  - Network requests are bounded, with a 2 MB cap on each response.
  - Resource profiles (lite / standard / gpu) are picked automatically from your hardware.
- **Buttons, not snake_case.**
  - Pick a filter (People, Username, Email, Phone, Domain & Web, IP & Network, Images, Breach, Code), then click actions.
  - The exact CLI command is **autofilled** for you to copy.
- **A brain on your PC or external HDD.**
  - It is seeded from your 13-division fields-of-study list, about 1,800 topics.
  - It then learns Wikipedia's Vital Articles and each field's categories, two levels deep.
  - All of that runs politely in the background behind **one progress bar**.
  - Ask it questions and get answers with citations.
- **Skills that generate *and* verify.** See [`skill-forge`](#skills) below.

> ⚖️ **Public data only. Respects robots.txt. No logins, CAPTCHA solving or paywall bypass.
> No paid API keys, ever.** Every investigation needs a stated purpose. Data-broker sites
> are never fetched. See [ETHICS.md](ETHICS.md): these rules are enforced in code.

---

## Quick start (Fedora)

```bash
sudo dnf install -y git python3 python3-pip
git clone https://github.com/voidless026-design/Map.git openatlas
cd openatlas                          # the repo root: the folder containing pyproject.toml
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                      # core: GUI, investigations, brain
pip install ddgs holehe               # web search + email account checks (both free, no key)

openatlas doctor                      # self-test every tool (should print "all tools verified")
openatlas doctor --live               # which public sources answer from YOUR network
openatlas serve                       # opens http://127.0.0.1:8600
```

> If `pip install -e .` says *"does not appear to be a Python project"*, you are one
> folder too deep. `cd ..` until `ls` shows `pyproject.toml`.

### Local AI (optional, free): Ollama on your GPU

Everything works without AI. It adds summaries, image geolocation and cited answers from the brain.

```bash
curl -fsSL https://ollama.com/install.sh | sh
# NVIDIA: install the RPM Fusion driver first (akmod-nvidia) so Ollama uses the GPU.
# AMD: Ollama uses ROCm; recent Fedora ships rocm packages (dnf install rocm-hip).
ollama pull llama3.1:8b        # text (gpu profile). Use llama3.2:3b on 8-16 GB RAM without a GPU
ollama pull llava:7b           # vision (gpu profile). moondream on the standard profile
ollama pull nomic-embed-text   # brain search vectors
```

The **System** view in the GUI (and `/api/health`) shows your profile and whether Ollama is really on the GPU.
Override the automatic choices with these variables:
- `OPENATLAS_PROFILE=lite|standard|gpu`
- `OPENATLAS_LLM_MODEL`, `OPENATLAS_VISION_MODEL` and `OPENATLAS_EMBED_MODEL`
- `OLLAMA_HOST`

If E.V says Ollama has **no chat model**, install one: `ollama pull llama3.1:8b`.
Before this fix, a missing model showed up as "HTTP 404". If the profile's model isn't installed, Atlas now picks the closest one you *do* have and says which.

## E.V - your local AI companion

E.V is the chat on the home page, and it runs only on this PC.
- **Memory:** everything she remembers stays in `OPENATLAS_DATA_DIR/ev/`.
- **Local model:** her model is your local Ollama.
- **Voice:** speech recognition and her Australian voice are local too.

```bash
openatlas serve                 # chat with E.V in the browser (home page)
openatlas ev chat               # ...or in the terminal
openatlas ev status             # local model, hearing, voice, mood
openatlas ev memory             # what she remembers (--forget "words" to remove)
openatlas ev approvals          # actions waiting for your OK;  openatlas ev approve 3
```

**Her eight skills** (each is a tool she calls; see `.claude/skills/`):

| Skill | What it does |
|---|---|
| Document Intelligence | Reads your PDFs, Word files and notes. Answers come with page-cited quotes. |
| Project Setup | Drafts a project layout, then creates it once you approve. Never overwrites anything. |
| Research Synthesis | Searches the brain, or the web with your approval. Every sentence cites a numbered source. |
| Workflow Automation | Runs named routines on a schedule: grow the brain, resume downloads, check quality, write digests. |
| Context Continuity | Remembers what you tell her across chats. You can list, edit or forget any of it. |
| Interactive Planning | Puts checklists in the chat that you tick, edit and reorder. She keeps open plans in view. |
| Quality Assurance | Checks every factual answer claim by claim: **supported / unsupported / unverified**. |
| Decision Support | Builds a weighted option matrix with a risk read-out and a sensitivity check. |

**Ask before acting.** She runs some things by herself and asks for others:
- **Automatic:** reading the brain, your allowed documents and her own memory.
- **Needs your approval:** anything touching the network, writing files or running an OpenAtlas command. It appears as an **Approve / Deny** card, with her risk read-out.

**Personality.** There are nine dials in **Settings**:
- humor, empathy, loyalty, mission commitment;
- risk & fear assessment, trust calibration, moral decision-making;
- emotional self-regulation, attachment & social preference.

Her mood and rapport are a *simulated* state, shown openly in the System panel. It shapes her tone; it isn't a feeling.

Some things are fixed and not dials: she is always honest that she's an AI, never guilt-trips you, and encourages your real-world relationships.

**Talk to her (hands-free, low latency).** She hears you with faster-whisper and answers with the MeloTTS **EN-AU** (Australian English) voice. Everything is local.
```bash
pip install -e '.[voice]'            # hearing: faster-whisper (+ WebRTC VAD up to Python 3.13)
sudo dnf install python3.11          # MeloTTS needs Python 3.11 beside Fedora's newer Python
openatlas ev voice-setup             # builds her voice in its own venv and saves a test phrase
```
Press the mic once and just talk:
- She replies when you pause (about 0.45 s).
- She starts speaking after her first sentence.
- If you talk over her, she stops and listens.

The System panel shows the hear / think / speak times for each turn.

Until the voice is set up, she speaks with your browser's own en-AU voice, if it has one.

### Better web search (optional): self-hosted SearXNG

DuckDuckGo may throttle heavy use. A local SearXNG is free and removes that limit:

```bash
podman run -d -p 8888:8080 -e SEARXNG_SETTINGS='{"search":{"formats":["html","json"]}}' docker.io/searxng/searxng
export OPENATLAS_SEARXNG_URL=http://127.0.0.1:8888
```

## Using it

### GUI

`openatlas serve` opens a light/dark single-page app (no CDN; it works offline). It has three parts:
- a left sidebar with your conversations and the sections;
- **E.V's chat** in the middle;
- a **System** panel on the right with the model, GPU, E.V's mood, the brain, downloads and voice latency.

The sections:

- **Chat.** E.V: see above.

- **Search.** Type a target; its type is detected automatically.
  - Pick a purpose, then a filter tab, then click the action tiles.
  - The command preview fills in as you click. **Run** streams evidence cards live.
  - Each card shows its badge, its "why", a confidence bar and its link.
  - "What was searched" lists every source, including the ones that failed.
  - **Auto-plan** lets the ATLAS loop propose which sources to run (local AI, or a heuristic
    when Ollama is off). It only selects the tiles; you review them and press Run.
  - When a case finishes, a **Check** row assesses it and offers one repair round: retry the
    sources that failed, or investigate a new identifier the case confirmed.
- **Cases.** History, a Markdown report and a graph view (the ATSMATRIX visualizer).
- **Brain.** One progress bar with start and pause, plus Ask, which answers with citations.
  - **3D brain ↗** opens your knowledge base as a 3D space you can fly through.
    - Every article is a neuron, clustered around its division.
    - **Click** a neuron to fly to it and inspect it (division, tier, when it was learned, licence, snippet, connections). From there: read the full text, ask E.V about it, find similar articles, isolate its neighbourhood, trace a path to another neuron, or pin it.
    - **Search** with `/`. A **growth timeline** replays the order things were learned.
  - The **Customize** panel changes:
    - the look: presets (Synapse, Nebula, Blueprint, Mono), colour by division / tier / links / age, size, link opacity / width / curvature, synapse firing, glow, background and labels;
    - the physics and quality: repulsion, link distance, freeze, auto-rotate, max neurons, and quality (auto keeps 60 fps).
  - Your settings are saved.
  - **Matrix view ↗** is the ATSMATRIX visualizer of the same brain.
- **Skills.** E.V's skills, the project skill cards and the doctor results.
- **Settings.** E.V's name for you, her standing mission, voice speed, personality dials, memory and routines.
- **System.** Hardware, profile, Ollama/GPU status and the data path.

The GUI only listens on `127.0.0.1`. Binding any other host requires `OPENATLAS_TOKEN`.

### CLI: every button is a command

```bash
openatlas catalog                                   # every action, grouped by filter
openatlas plan "jdoe_42" --purpose "self-audit"      # Auto-plan: which sources to run (ATLAS loop)
openatlas investigate "jdoe_42" --purpose "authorised background check" --filter username
openatlas investigate jane@example.com --purpose "verify applicant (consented)" --json
openatlas run rdap example.com                      # one action, exactly what a tile does
openatlas run keybase jdoe_42 --purpose "..."       # sources need a purpose too
openatlas cases                                     # history;  openatlas cases <ID> --md
openatlas doctor [--live]                           # verify the tools
```

The legacy OAtlas flags still work: `openatlas -f check_usernames`,
`--show-all-functions`, `--verify` and `--visualize`.

## The brain (knowledge base)

By default the brain and books live in `data/` inside your clone. To put them on another
drive, plug it in, open it once in Files (that mounts it), then let Atlas print the exact line:

```bash
openatlas kb where            # data folder, free space, and a ready-to-paste line per drive
```

Then start it:

```bash
openatlas kb seeds            # 1,787 unique topics across your 13 divisions
openatlas kb ingest --max 50  # learn a batch now
openatlas kb stats            # size, progress, tiers
openatlas kb graph            # see it in the visualizer (http://127.0.0.1:8765)
openatlas kb ask "What is a homotopy?"
```

Or let it grow 24/7 as a low-priority user service. The unit runs with nice 19, idle I/O,
a 50% CPU cap and 3 GB of RAM at most:

```bash
mkdir -p ~/.config/systemd/user
cp packaging/systemd/openatlas-brain.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now openatlas-brain
openatlas kb pause / openatlas kb resume     # e.g. while gaming
```

The brain learns in tiers:

| Tier | Contents |
|---|---|
| 0 | Your fields of study (about 1,800 articles) |
| 1 | Vital Articles level 4 (about 10,000) |
| 2 | Each field's category (up to 150 per field) |
| 3 | Relevant subcategories |

Whatever you search or ask about jumps the queue. **At full depth, expect roughly
8–15 GB and about two days** of polite, rate-limited downloading. Ingestion stops if
less than 20 GB is free. Text is Wikipedia's, under CC BY-SA 4.0, and each stored
article keeps its URL and attribution. Finished cases are added too, so "have we seen
this email before?" works.

### Search that stays on-topic

Brain search works like a search engine, not a keyword grep:
- `"exact phrases"` and `-exclusions` are supported, and question words like "what is the" are ignored.
- An article **titled** (or redirected from) your query beats one that only mentions it.
- The words you asked for have to be present, so "black hole" no longer brings up "Black Death".

Weak matches are dropped rather than padded out. Each hit says why it matched (`exact alias, 1/1 words`).

```bash
openatlas kb search "black hole event horizon"
openatlas kb eval --fixture   # P@1 / MRR@5 / nDCG@5 / off-topic rate on a look-alike corpus
openatlas kb eval             # the same, on queries sampled from your own brain
```

To add your own hard cases, put them in `data/eval/search_golden.jsonl`, one per line:
`{"q": "second world war", "expect": ["World War II"], "ok": []}`.

### Kiwix library: whole offline encyclopedias

The **Library** tab (or `openatlas kb library`) downloads [Kiwix](https://kiwix.org) books
from the official catalog: Wikipedia, Wiktionary, Stack Exchange, Gutenberg and more.
Each book is a single multi-gigabyte ZIM file, and Atlas feeds its articles into the brain.

```bash
pip install libzim                          # read ZIM files (free)
sudo dnf install kiwix-tools                # optional: read the books inside Atlas
openatlas kb library catalog wikipedia --lang eng   # words...
openatlas kb library catalog wikipedia_en_all       # ...or a name: maxi / nopic / mini
openatlas kb library get wikipedia_en_100           # 0.3 GB - a quick first test
openatlas kb library get wikipedia_en_all_nopic     # resumable, checksum-verified
openatlas kb library list                   # progress; each book has a number, e.g. [1]
openatlas kb library pause 1                # pause book 1 (no number: all downloads)
openatlas kb library resume                 # carry on after closing the terminal (all books)
openatlas kb library resume --background    # same, but keeps going when you close the terminal
openatlas kb library serve                  # Kiwix reader at http://127.0.0.1:8602/kiwix/
```

- **Downloads resume** after a restart, a dropped connection or a closed terminal, from the `.part` file.
  - Run `openatlas kb library resume`, run the same `get` again, or just open the app: the Library tab carries on by itself.
  - Progress shows the size done, the speed and an ETA.
  - Two windows can never write to the same file at once.
- **Checksums.** Each file is checked against the **SHA-256 that Kiwix publishes** before it is used. A corrupted file is deleted.
- **No duplicates.** A book already in the library is refused, whether it matches by id, file name, checksum, or an equal/newer version. A newer version of a book you already have counts as an update. The old file is removed only after the new one has verified and fed the brain.
- **Hand-copied files.** `.zim` files you copy into `$OPENATLAS_DATA_DIR/library/` are picked up too, and follow the same rules.
- **No double-counting with the brain.** Wikipedia articles from a ZIM **update** the ones the brain already learned; they aren't added a second time.
- **Disk check.** Downloads need the file size + 10% + 5 GB free. Feeding the brain is paused below the brain's 20 GB floor.

Sizes to expect:
- English Wikipedia *nopic* is about 50 GB; *maxi* (with pictures) is about 110 GB.
- Feeding it in adds roughly 20–30 GB of brain.
- That takes many hours in the background, at low priority.

## Skills

The manual task these skills remove is opening a browser to check each AI answer, and
checking by hand whether a new tool or skill actually works.

| Skill | What it does |
|---|---|
| **`skill-forge`** | Generates an engine (`forge new-engine`) or a skill (`forge new-skill`) and **verifies it straight away**. Engines go through 7 checks, including a mocked dry-run. For skills, the frontmatter spec, ≥3 triggers and the required sections are checked, and **every documented command is run**. `forge doctor` then verifies the verifying tools on known-good and known-bad fixtures. |
| **`osint-verify`** | Runs **automatically** after every case, re-checking findings against an independent source. Also usable by hand on pasted output. |
| **`osint-investigate`** | Runs an evidence-first case (generated by skill-forge). |
| **`kb-curate`** | Grows and checks the brain (generated by skill-forge). |
| **`search-quality`** | Measures whether brain search stays on-topic (`openatlas kb eval`) and drives fixes until it passes (generated by skill-forge). |
| **`kb-library`** | Finds, downloads, verifies and ingests Kiwix books without duplicates (generated by skill-forge). |
| **E.V's skills** | `document-intelligence`, `project-setup`, `research-synthesis`, `workflow-automation`, `context-continuity`, `interactive-planning`, `quality-assurance`, `decision-support` and `ev-voice`. All were generated and verified by skill-forge. |

```bash
python -m openatlas.utils.forge new-skill --name my-skill --description "..." \
  --trigger "..." --trigger "..." --trigger "..." --command "openatlas catalog"
python -m openatlas.utils.forge verify-skill --all
python -m openatlas.utils.forge doctor
```

## Free substitutes for OAtlas's paid services

| OAtlas needed (paid/key) | OpenAtlas uses instead (free) |
|---|---|
| OpenAI / VertexAI | **Ollama** (local) |
| Perplexity | **DuckDuckGo** (`ddgs`) or **SearXNG**, plus an optional local summary |
| Hunter.io | **Holehe**, email permutation and DNS/MX checks |
| HIBP (paid) / OathNet | **HIBP Pwned Passwords** (k-anonymity) and **XposedOrNot** |
| isgen.ai | A local Hugging Face model plus C2PA/EXIF |
| Picarta / IPinfo | EXIF GPS + **Nominatim**; **RDAP**, **ip-api** and **RIPEstat** |
| Username APIs | The **WhatsMyName** dataset (717 sites, bundled) |

## If `openatlas doctor` complains

- **Graphics for the 3D brain: … nouveau …** means Fedora's open NVIDIA driver is running your
  card at its slowest clock, which is common on older cards like the GTX 770. The 3D brain
  will be choppy. Raise the clock until the next reboot, then reload the page:
  `sudo cat /sys/kernel/debug/dri/0/pstate`, then `sudo sh -c 'echo 0f > /sys/kernel/debug/dri/0/pstate'`
  (use the highest level the first command lists). In Firefox, if `about:support` shows
  Compositing: "WebRender (Software)", set `gfx.webrender.all` to true in `about:config` and
  restart Firefox. The 3D brain shows the same advice, and its "auto" detail setting eases off
  sharpness and glow while the GPU can't keep up.
- **Installation: not installed …** means the code was updated (`git pull`) but its packages
  weren't. Run the command it prints, which uses your checkout's own folder.
- **Installation: pip install -e . will fail … links outside the project** (pip says
  "… is not in the subpath of …") means a folder inside `openatlas/`, usually an old copy with
  its own virtualenv, contains a link to your system Python. Move it out with the line the
  doctor prints, then run `pip install -e .` again.
- **Secret lint: skipped … inside the package folder** means an old copy of OpenAtlas (for
  example a `tests/` folder or another clone) sits *inside* `openatlas/`. It isn't used. Check
  it, then move it out with the `mv` line the doctor prints (nothing is deleted).
- **Skill linter: external skill(s)** are skills you added from elsewhere (for example
  Streamlit's). They are checked against the Agent Skills spec only. OpenAtlas's own skills
  (`metadata: project: OpenAtlas`) must also meet the house rules: triggers, Verification
  and Tools sections, and commands that run.
- **Brain retrievability** samples five of your articles, and each must come back for its own
  title. It names any that don't. `openatlas kb eval` gives the full picture.

## Honest limits

- **Results depend on the target's real public footprint.** "Nothing found" is a valid,
  reported outcome, and failed sources are listed with the reason.
- **Some sites block anonymous access.** LinkedIn and Instagram only appear through
  search snippets, and Reddit or GitHub (60 requests an hour) may rate-limit you. Run
  `openatlas doctor --live` to see what works from your network.
- **Some findings stay unverified.** Search snippets and Holehe results can't be
  independently re-checked without logging in, so they are labelled as unverified.
- **E.V's feelings are simulated.** Her mood, rapport and "attachment" are a small state
  that shapes her tone. It is shown openly in the UI. She is an AI and says so.
- **Voice speed depends on your hardware.** With a GPU, expect about 1 s from the end of
  your sentence to her first word. On CPU it's slower. MeloTTS is large (it uses torch), so
  it lives in its own Python 3.11 venv.

## Testing

```bash
make test     # pytest - all network/LLM mocked, never goes online
make lint     # ruff + secret/paid-key lint
make verify   # self-verifier over all 44 functions
make doctor   # verify the verification tools   (LIVE=1 to probe public sources)
make skills   # lint every SKILL.md and run its commands
```

## Credits & licences

Independent work inspired by OAtlas, PyBA, OpenJarvis (Apache-2.0) and ATLAS (AGPL-3.0).

Where the integrated projects live:

| Project | In OpenAtlas |
|---|---|
| ATSMATRIX Agent VisualizeR (MIT) | `openatlas/webserver/visualizer/` - case graphs and the **Brain graph** |
| OpenJarvis (Apache-2.0) | `openatlas/core/registry.py` - the tool registry every engine uses |
| ATLAS (AGPL-3.0) | `openatlas/reasoning/loop.py` - plan → execute → check → repair: the **Auto-plan** button / `openatlas plan`, and the **Check** row after each case |
| OpenJarvis (Apache-2.0) | Visual reference only for the GUI's look (layout, zinc/cyan palette). No code was copied. |
| three.js, 3d-force-graph (MIT) | `openatlas/web/static/vendor/` - the 3D brain (see `LICENSES.txt`, rebuilt by `tools/build_brain3d_vendor.sh`) |
| Chakra Petch, IBM Plex Mono (SIL OFL) | `openatlas/web/static/fonts/` |
| faster-whisper (MIT), MeloTTS (MIT) | E.V's hearing and her Australian voice (optional installs) |

It bundles a modified fork of the ATSMATRIX visualizer (MIT) and uses the WhatsMyName
dataset, and optionally Holehe. Wikipedia text is CC BY-SA 4.0. See [NOTICE](NOTICE).
OpenAtlas itself is MIT licensed.
