"""
Seed PromiseProof with the curated promises in ledger/seed_data.py.

For each entry: run the deterministic falsifiability gate, admit it, then run
the zero-LLM verifier against its live evidence page and persist the result.
No LLM call anywhere - the seed set is hand-curated, the machine only
checks it.

Usage:
  python -m ledger.seed            # seed only if the ledger is empty
  python -m ledger.seed --fresh    # wipe the ledger first, then seed
  python -m ledger.seed --no-verify
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from agents.falsifiability_gate import run_gate
from agents.promise_schemas import LedgerPromise, PromiseExtraction
from ledger import promises as ledger
from ledger.promises import DEFAULT_JSON_PATH, JsonFileBackend
from ledger.seed_data import SEED_PROMISES
from ledger.verifier import verify_promise

_EXTRACTION_FIELDS = set(PromiseExtraction.model_fields)


def _extraction_from_seed(entry: dict) -> PromiseExtraction:
    payload = {k: v for k, v in entry.items() if k in _EXTRACTION_FIELDS}
    payload["is_falsifiable"] = True
    return PromiseExtraction(**payload)


def seed(*, fresh: bool = False, verify: bool = True, backend=None) -> dict:
    be = backend or ledger.get_backend()

    if fresh and isinstance(be, JsonFileBackend):
        path = getattr(be, "_path", None) or os.getenv("LEDGER_JSON_PATH") or DEFAULT_JSON_PATH
        try:
            os.remove(path)
            print(f"wiped {path}")
        except FileNotFoundError:
            pass
        if backend is None:
            ledger.reset_default_backend()
            be = ledger.get_backend()
    elif fresh and hasattr(be, "clear"):
        removed = be.clear()
        print(f"wiped {removed} existing promise(s) from {type(be).__name__}")

    existing = be.all()
    if existing and not fresh:
        print(f"ledger already has {len(existing)} promise(s); pass --fresh to rebuild. Nothing to do.")
        return {"admitted": 0, "skipped": len(SEED_PROMISES)}

    today = dt.datetime.now(dt.timezone.utc).date()
    admitted = 0
    rows: list[tuple[str, str, str]] = []

    for entry in SEED_PROMISES:
        ext = _extraction_from_seed(entry)
        gate = run_gate(ext, entry["announced_date"])
        if not gate.accepted:
            print(f"  GATE REJECTED  {entry['company']}: {gate.reason}")
            rows.append((entry["company"], "REJECTED", gate.reason))
            continue

        pid = ledger.admit_promise(
            company=ext.company,
            promise_text=ext.promise_text,
            source_quote=ext.source_quote,
            source_url=entry["source_url"],
            announced_date=entry["announced_date"],
            deadline_raw=ext.deadline_raw,
            deadline_date=ext.deadline_date_iso,
            observable_outcome=ext.observable_outcome,
            check_keywords=ext.check_keywords,
            evidence_url=entry["evidence_url"],
            extractor_model="(curated seed)",
            backend=be,
        )
        admitted += 1
        status = "PENDING"
        note = ""

        if verify:
            row = ledger.get_promise(pid, backend=be)
            result = verify_promise(LedgerPromise(**row), check_date=today)
            ledger.apply_verification(pid, result, backend=be)
            status = result.status.value
            note = result.reason

        claimed = entry.get("claimed_outcome", "")
        print(f"  {entry['company']:<14} -> {status:<20} {note[:90]}")
        if claimed:
            print(f"                    (human note: {claimed})")
        rows.append((entry["company"], status, note))

    card = ledger.get_scorecard(backend=be)
    print("\n=== SCORECARD ===")
    print(json.dumps(card, indent=2, ensure_ascii=False))
    return {"admitted": admitted, "rows": rows, "scorecard": card}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fresh", action="store_true", help="wipe the ledger before seeding")
    ap.add_argument("--no-verify", action="store_true", help="admit only, skip live verification")
    args = ap.parse_args()
    seed(fresh=args.fresh, verify=not args.no_verify)
