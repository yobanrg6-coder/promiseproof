# ledger/ - the verified store and the zero-LLM verifier

No model call anywhere in this package. A promise's status is only ever set by
deterministic code reading a public page.

## Files

| File | What it does |
|---|---|
| `promises.py` | The store. `admit_promise`, `apply_verification`, `get_promise`, `list_promises`, `due_for_check`, `get_scorecard`. Pluggable backend chosen by `LEDGER_BACKEND`: **`json`** (default, `data/ledger.json`), `firestore`, `memory`. |
| `evidence.py` | Pure HTTP + HTML-to-text. Fetches a page, strips scripts / markup / the Wayback toolbar, decodes HTML entities, flags an empty SPA shell, and does whole-token keyword matching. No JS execution. |
| `archive.py` | `snapshot_near(url, date)` -> the official page as captured by the Wayback Machine closest to a date (availability API, no key). |
| `verifier.py` | `verify_promise(promise, check_date)` -> a `PromiseStatus`. Two LLM-free probes: the official page **as archived on/before the deadline**, then the page **now**. This is the decision table. |
| `run_cycle.py` | One verification pass: for every promise past its deadline and not yet final, re-fetch and re-decide. `python -m ledger.run_cycle`. Safe to run unattended - no API key. |
| `seed.py` / `seed_data.py` | Load the hand-curated demo promises through the gate, admit them, and verify them live. `python -m ledger.seed --fresh`. |

## Status decision table (deadline D, check date T)

```
Probe 1 - the official page as archived by the Wayback Machine on/before D:
    check keywords present in that capture ......... FULFILLED (on time)   [capture date = dated proof]
    that capture exists but keywords absent ........ -> it had not shipped by D; go to Probe 2

Probe 2 - the page now (live, or a recent archive capture if the live page is bot-blocked / JS-only):
    keywords present, and Probe 1 proved absence-by-D ...... FULFILLED_LATE
    keywords present, no point-in-time proof:
        a date on the page <= D ........................... FULFILLED (on time)
        a date on the page >  D ........................... FULFILLED_LATE
        no readable date ................................. FULFILLED (undated - kept out of the rate)
    some (>=1) but not a majority present, T > D .......... PARTIALLY_FULFILLED
    none present:  T <= D ................................ PENDING
                   D < T <= D + 180d .................... DELAYED
                   T >  D + 180d ....................... ABANDONED

live page AND archive both unusable ...................... UNVERIFIABLE
```

"Majority" is a strict majority of the keyword count (min 2). Every result
carries a `verification_method` (`wayback@deadline` / `wayback@now` /
`live-page` / `live-page+date` / `unverifiable`) so the provenance of each
verdict is on the record. `UNVERIFIABLE` promises are re-checked each cycle
until 180 days past the deadline, then they stop being re-queued.

## Storage

`JsonFileBackend` writes the whole ledger to one JSON file under a lock. The
seeded demo ships as `data/ledger.json` in the repo, so the app and the cycle
have real data with no cloud credentials. Cloud Run's per-instance disk is
ephemeral, so live writes there don't survive a cold start - the committed
file is the baseline. Set `LEDGER_BACKEND=firestore` for durable writes.
