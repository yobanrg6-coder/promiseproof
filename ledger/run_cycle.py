"""
Verification passes for PromiseProof.

`run_cycle` re-checks every promise whose deadline has passed and that is not
yet in a final state. `reverify_all` re-checks every promise regardless of
state (used by the web app's "re-verify now" action). Both re-fetch the
evidence page and re-decide the status with the zero-LLM verifier
(ledger/verifier.py). No API key, no LLM call - safe to run unattended.

Usage:
  python -m ledger.run_cycle          # re-check only promises still due
  python -m ledger.run_cycle --all    # re-check every promise (self-healing:
                                      # a transient network blip that left a
                                      # promise UNVERIFIABLE gets another pass)
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from agents.promise_schemas import LedgerPromise
from ledger import promises as ledger
from ledger.verifier import verify_promise

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("promise_ledger.cycle")


def _verify_rows(rows: list[dict], today: dt.date, backend) -> dict:
    """Re-verify each row, persist the result, and summarize what changed."""
    changed: list[dict] = []
    errors = 0
    for row in rows:
        try:
            before = row.get("status")
            result = verify_promise(LedgerPromise(**row), check_date=today)
            ledger.apply_verification(row["id"], result, backend=backend)
            if result.status.value != before:
                changed.append({"id": row["id"], "company": row.get("company"),
                                "from": before, "to": result.status.value})
                logger.info("  %s (%s): %s -> %s  [%s]", row["id"][:8], row.get("company"),
                            before, result.status.value, result.reason)
        except Exception:
            errors += 1
            logger.exception("  verification failed for %s", row.get("id"))

    card = ledger.get_scorecard(backend=backend)
    ov = card["overall"]
    logger.info(
        "Pass complete. checked=%d changed=%d errors=%d | ledger: %d total, %d resolved, on-time rate %s",
        len(rows), len(changed), errors, ov["total"], ov["resolved"],
        f'{ov["on_time_rate_pct"]}%' if ov["on_time_rate_pct"] is not None else "n/a",
    )
    return {"checked": len(rows), "changed": changed, "errors": errors, "scorecard": card}


def run_cycle(check_date: dt.date | None = None, backend=None) -> dict:
    """Verify every due promise once (deadline passed, not yet final)."""
    today = check_date or dt.datetime.now(dt.timezone.utc).date()
    due = ledger.due_for_check(check_date=today, backend=backend)
    logger.info("Verification cycle starting %s - %d promise(s) due", today.isoformat(), len(due))
    return _verify_rows(due, today, backend)


def reverify_all(check_date: dt.date | None = None, backend=None) -> dict:
    """Re-verify every promise in the ledger against its live evidence page,
    whatever its current status. Zero LLM. Used by the web app so a viewer can
    watch the deterministic verifier run on the whole seeded ledger on demand."""
    today = check_date or dt.datetime.now(dt.timezone.utc).date()
    rows = ledger.list_promises(backend=backend)
    logger.info("Full re-verification starting %s - %d promise(s)", today.isoformat(), len(rows))
    return _verify_rows(rows, today, backend)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Zero-LLM re-verification pass.")
    ap.add_argument("--all", action="store_true",
                    help="re-check every promise, not just the ones still due")
    (reverify_all if ap.parse_args().all else run_cycle)()
