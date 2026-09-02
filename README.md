# PromiseProof

[![Google ADK](https://img.shields.io/badge/Framework-Google%20ADK-4285F4?logo=google&logoColor=white)](https://github.com/google/adk)
[![Model](https://img.shields.io/badge/LLM-NVIDIA%20Nemotron-76B900?logo=nvidia&logoColor=white)](https://build.nvidia.com/)
[![Inference](https://img.shields.io/badge/Inference-Nebius%20Token%20Factory-6C4CE0)](https://studio.nebius.com/)
[![MCP](https://img.shields.io/badge/Protocol-Model%20Context%20Protocol-blueviolet)](https://modelcontextprotocol.io/)
[![Cloud](https://img.shields.io/badge/Deployment-Google%20Cloud%20Run-FBBC05?logo=google-cloud&logoColor=white)](https://cloud.google.com/run)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> Built for the **Nebius x NVIDIA Global AI Hackathon**. A significantly
> updated fork of [The Promise Ledger](https://github.com/yobanrg6-coder/the-promise-ledger)
> (built for a different, earlier hackathon): the entire inference stack was
> migrated off Google's Gemini/Gemma to two open-source **NVIDIA Nemotron**
> models served through **Nebius Token Factory**, plus the hardening and
> documentation that migration required. The zero-LLM verification core —
> this project's actual differentiator — is unchanged and untouched.

**A machine-verifiable record of public product promises.** Companies announce
dated commitments constantly ("open weights by end of year", "GA next quarter",
"available later this month"). Nobody keeps an honest, checkable score of which
ones actually shipped, on time. PromiseProof does, and — its whole point —
**no LLM decides an outcome**. A promise's status is set by deterministic code
that fetches the official page and checks it.

---

## What it does

1. **Extract** a falsifiable promise from an announcement — an agent
   (NVIDIA Nemotron Super, via Nebius) proposes a structured promise: verbatim
   source quote, normalized deadline, an observable outcome, and
   machine-checkable keywords.
2. **Audit** it adversarially on a second, smaller NVIDIA model (Nemotron
   Nano) — an independent read on "is this actually checkable?". Rejections
   trigger up to two re-extractions.
3. **Gate** it with pure Python — a real deadline, not absurd, ≥2 distinct
   specific keywords, a substantive outcome. The gate admits, not the model.
4. **Verify** it with **zero LLM**, point-in-time. Two probes: the official
   page **as archived by the Wayback Machine on or before the deadline** —
   the CDX API's *last* capture at/before that date, never one from after it
   (if the check keywords are in that capture, the promise was kept on time
   and the capture date is the dated proof — no prose-date guessing, no third
   party but a neutral public archive) — then the page **now** (which,
   combined with probe 1, gives late vs delayed vs abandoned). A fixed
   decision table turns the two readings into one status, and every verdict
   records how it was reached (`wayback@deadline`, `live-page`, …).
5. **Score** it — a per-company and overall scorecard: kept on time / undated /
   late / delayed / abandoned / unverifiable, and an on-time rate that is a
   count, not a claim.
6. **Chain** it — every admission is appended to a SHA-256 hash chain over the
   immutable claim (verbatim quote, company, deadline, observable outcome).
   Editing a stored quote or nudging a deadline after the fact breaks that
   row's hash and every row after it; `GET /api/health`'s sibling
   `GET /api/chain` (and the MCP `verify_ledger_chain` tool) recompute it from
   genesis. Deployed, the 6-hourly cycle commits the refreshed ledger back to
   git, so the whole history is a public, tamper-evident log.

### The seven statuses

`PENDING` · `FULFILLED` · `FULFILLED_LATE` · `PARTIALLY_FULFILLED` · `DELAYED` ·
`ABANDONED` · `UNVERIFIABLE`

The decision table lives in `ledger/README.md` and `ledger/verifier.py`. It is
deliberately fixed and public, so "delayed vs abandoned" is never a judgement
call made after the fact.

---

## Architecture

![PromiseProof architecture](docs/architecture.png)

```
announcement text ──▶ PromiseExtractorAgent  (Nemotron Super, ADK, structured)  [1]
                        │
                        ▼
                     PromiseAuditorAgent     (Nemotron Nano, ADK, adversarial)  [2]
                        │  reject ─▶ re-extract (max 2)
                        ▼
                     falsifiability gate      (pure Python, no LLM)             [3]
                        │
                        ▼
                     admit_promise ──▶ ledger  (JSON file / Firestore)          [4]

ledger  ◀──▶  FastMCP server        get_scorecard · list_promises · get_promise ·
                                    admit_promise · run_verification_cycle
   │
   ▼
run_cycle  (Cloud Run Job on       for each promise: the official page as
Cloud Scheduler, every 6h,         archived on/before the deadline (Wayback),
zero LLM)                          then the page now → fixed decision table
```

Both agents run through **Nebius Token Factory** (an OpenAI-compatible
endpoint) via ADK's LiteLLM integration — see `agents/promise_extractor.py`
and `agents/promise_auditor.py`. Steps 1–3 stream live in the web app
(`/api/extract-stream`). The verification cycle and every MCP tool are
LLM-free.

| Component | Tech |
|---|---|
| `agents/promise_extractor.py` | `google.adk` `LlmAgent` + `LiteLlm`, NVIDIA Nemotron Super (via Nebius), Pydantic `PromiseExtraction` output schema |
| `agents/promise_auditor.py` | `google.adk` `LlmAgent` + `LiteLlm`, NVIDIA Nemotron Nano — a genuinely different-sized model |
| `agents/promise_orchestrator.py` | the extract → audit → re-extract → gate → admit pipeline, as an async event stream |
| `agents/falsifiability_gate.py` | deterministic admission check, no LLM |
| `ledger/evidence.py` | HTTP fetch + HTML→text (+ Wayback toolbar strip, entity decode) + whole-token keyword match, no JS |
| `ledger/archive.py` | Wayback lookup — CDX "last capture ≤ deadline" for probe 1, availability API for "roughly now" |
| `ledger/verifier.py` | the zero-LLM, two-probe (archived-at-deadline / now) decision table |
| `ledger/promises.py` | store + scorecard + append-only SHA-256 hash chain; backend = JSON file / Firestore / in-memory |
| `mcp_server/server.py` | FastMCP server exposing the ledger over the Model Context Protocol |
| `web_app/` | FastAPI + a single static page: scorecard + live pipeline stream |

---

## Quick start

Python 3.11+.

```bash
git clone https://github.com/yobanrg6-coder/promiseproof.git
cd promiseproof
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # add NEBIUS_API_KEY for the live extraction demo
```

**Seed the ledger** with the curated demo promises (hand-typed real
announcements; the machine verifies them live — no LLM, no key needed):

```bash
python -m ledger.seed --fresh
```

This writes `data/ledger.json` (a copy is committed, so you can skip this and
still have data).

**Run the app:**

```bash
python run.py           # FastMCP server + web app
# open http://127.0.0.1:8000
```

**Run a verification cycle** (re-checks promises against their live evidence
page, zero LLM):

```bash
python -m ledger.run_cycle          # only promises still due
python -m ledger.run_cycle --all    # every promise (this is what the
                                    # scheduled Cloud Run Job runs)
```

**Tests:**

```bash
pip install -r requirements-dev.txt
pytest tests/            # no network, no LLM
```

---

## Deploy to Cloud Run

Uses a **new** GCP project — this fork does not touch the original Promise
Ledger project or its running submission.

```bash
# Cloud Run builds the container from the Dockerfile - no local Docker needed.
# Store the Nebius key in Secret Manager, never as a plain env var.
echo -n "your_nebius_api_key" | gcloud secrets create nebius-api-key --data-file=-

gcloud run deploy promiseproof --source . --region=us-central1 \
    --allow-unauthenticated --min-instances=1 --max-instances=1 \
    --set-env-vars MODEL=nvidia/nemotron-3-super-120b-a12b,AUDITOR_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B,LEDGER_BACKEND=firestore,GCP_PROJECT=<your-new-project-id> \
    --set-secrets NEBIUS_API_KEY=nebius-api-key:latest
```

`data/ledger.json` ships in the image as a zero-config baseline
(`LEDGER_BACKEND=json`). The live deployment runs `LEDGER_BACKEND=firestore` so
writes survive Cloud Run's ephemeral disk, and a **Cloud Run Job** re-runs the
zero-LLM cycle on a schedule against that same store:

```bash
gcloud run jobs deploy ledger-cycle --image <same image> --region=us-central1 \
    --command python --args=-m,ledger.run_cycle,--all \
    --set-env-vars LEDGER_BACKEND=firestore,GCP_PROJECT=<your-new-project-id>
gcloud scheduler jobs create http ledger-cycle-scheduler --schedule "0 */6 * * *" \
    --uri ".../jobs/ledger-cycle:run" --http-method POST --oauth-service-account-email <sa>
```

Cloud Run exposes one port (the web app). The FastMCP server also runs in the
container but on an internal port — connect an MCP client to it by running the
stack locally (`python run.py`, then point the client at
`http://127.0.0.1:8081/mcp`). The web app talks to the same ledger module
directly, so the public demo is fully functional without it.

---

## What changed from The Promise Ledger

This is a from-scratch-history fork built specifically for the Nebius x
NVIDIA Global AI Hackathon, which requires either a brand-new project or an
existing one **"significantly updated after the start of the Hackathon
Submission Period."** What changed:

- **Full inference migration**: `google.adk.models.Gemini` → `google.adk.models.lite_llm.LiteLlm`
  routed through Nebius Token Factory, on both agents. `GEMINI_API_KEY` /
  `GEMMA_MODEL` → `NEBIUS_API_KEY` / `MODEL` / `AUDITOR_MODEL` throughout the
  code, tests, docs, and deploy config.
- **Model choice is now load-bearing for eligibility**: two *different-sized*
  NVIDIA open-source Nemotron models (Super for extraction, Nano for the
  adversarial audit) — not a cosmetic rename, the same "independent second
  opinion" integrity design as before, now on NVIDIA's own model family.
  Satisfies the hackathon's "at least one NVIDIA open source model"
  requirement twice over.
- **New, isolated GCP project** (`GCP_PROJECT`, no longer hardcoded) — this
  fork never touches the original project, which keeps running unmodified for
  its own, already-judged hackathon.
- **Reasoning-model hardening**: both system prompts request `detailed
  thinking off`; `LiteLlm(..., drop_params=True)` lets LiteLLM drop any
  request field Nebius won't accept for a given model instead of erroring;
  and the orchestrator's output parser strips `<think>…</think>` traces and
  code fences and, as a last resort, slices the outer JSON object before
  validating — so a Nemotron reasoning trace can't break the pipeline.
- **Post-audit hardening** (see `git log`): SSRF guard on the verifier's
  fetch path (`is_public_http_url` — an `evidence_url` that resolves to a
  private/loopback/link-local/metadata address is refused, redirects
  re-checked per hop); a version keyword no longer matches its own point
  release (`iOS 18.1` ≠ `iOS 18.1.1`); JSON-file store takes its lock on
  reads too (Windows `WinError 32`); `PARTIALLY_FULFILLED` promises stay in
  the re-verification cycle; the MCP `admit_promise` tool validates URLs like
  the web path already did; the MCP port default moved off `8080` so it can't
  collide with `PORT`; the API rejects impossible calendar dates and
  over-long announcements instead of truncating silently.
- Full rebrand (package identifiers, service names, docs, submission
  materials) and a fresh git history, per the hackathon's project-page rules.

The zero-LLM half of the system — the falsifiability gate, the Wayback
point-in-time verifier, the ledger store, the MCP surface — is byte-for-byte
the same design, because that is the part that makes this an accountability
tool rather than another chatbot demo.

---

## Honest limitations

- **The archive doesn't always have a capture near the deadline.** When there
  is no Wayback snapshot on/before the deadline, the verifier falls back to
  reading a date off the *current* page — a weaker signal, biased toward
  `FULFILLED` over `FULFILLED_LATE` because it takes the earliest date near the
  first keyword. Several seed rows verify this way; their `verification_method`
  says `live-page+date`, so the record shows which verdicts rest on the weaker
  path.
- **A few seed rows point at Wikipedia, not the vendor page.** `xAI` (Grok-2),
  `Apple` (ChatGPT-in-iOS) and `Google` (Gemini Advanced) vendor pages render
  as an empty JS shell to a non-browser client, so their `evidence_url` is the
  relevant Wikipedia article — neutral, dated, archived. `Anthropic`'s Claude
  3.5 Haiku row leans on a dated third-party write-up
  (`simonwillison.net/.../haiku/`) because Anthropic's own changelog rolled
  over. Each such choice is flagged with a comment in `ledger/seed_data.py`,
  and every verdict is still the zero-LLM rule's.
- **Keyword brittleness.** If a page describes a shipped feature in words that
  don't contain the check keywords, the verifier under-reports it. The seed set
  shows this: `Stability AI` resolves `FULFILLED` but neither its page nor any
  capture pins a date, so it stays `FULFILLED (undated)` — kept out of the
  on-time rate rather than assumed on time.
- **`UNVERIFIABLE` still fires** when the live page is unreachable *and* the
  archive has nothing usable (or the stored record has a broken date).
  `OpenAI`'s bot-blocked ChatGPT-for-Windows page hits this on any pass where
  the archived-capture fallback doesn't answer in time, and clears on the next
  cycle — the status is live in the decision table, not theoretical.
- The seed is 14 curated promises across 7 companies (Anthropic, Apple, Google,
  Meta, OpenAI, Stability AI, xAI) — enough to show the mechanism, not a
  census. Treat the headline percentage as illustrative: the re-verification
  cycle re-runs it every 6 hours and it moves as pages and archives change.
- **NVIDIA Nemotron model ids on Nebius change over time.** `.env.example`
  pins specific ids as of this submission; check the Nebius Token Factory
  console if a deploy fails on an unknown model.

---

## Author

Jose (Yoban) Rodríguez · [Google Cloud profile](https://www.skills.google/public_profiles/6bac5b41-ee95-4a9a-b9ee-d871c4e31106) · MIT License
