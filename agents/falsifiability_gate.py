"""
The falsifiability gate - the deterministic checkpoint every extracted promise
must pass before it can enter the ledger. Pure Python, no LLM: the extractor
agent PROPOSES that a statement is falsifiable; this code is what actually
decides, so "the ledger only holds checkable promises" is enforced, not
trusted.

A statement is admissible only if it has, verifiably in the extraction:
  - the extractor's own is_falsifiable flag set
  - a normalized deadline that parses as a real calendar date
  - a deadline that is not absurd (not before the announcement, not >5y out)
  - an observable_outcome with real content
  - >=2 usable, specific check_keywords (not one-word filler)
"""

from __future__ import annotations

import datetime as dt
import re

from agents.promise_schemas import GateResult, PromiseExtraction

MAX_DEADLINE_HORIZON_YEARS = 5
_GENERIC_KEYWORDS = {
    "api", "ai", "app", "beta", "cloud", "feature", "launch", "release",
    "update", "new", "available", "support", "model", "platform", "tool",
}


def _too_far_out(announced: dt.date, deadline: dt.date) -> bool:
    """True if `deadline` is more than MAX_DEADLINE_HORIZON_YEARS calendar
    years after `announced`. Compared by calendar date, not a fixed day
    count, so a legitimate exact-5-year promise spanning a leap day isn't
    rejected for being 1826 days instead of 1825."""
    horizon = announced.replace(year=announced.year + MAX_DEADLINE_HORIZON_YEARS) \
        if not (announced.month == 2 and announced.day == 29) \
        else announced.replace(year=announced.year + MAX_DEADLINE_HORIZON_YEARS, day=28)
    return deadline > horizon


def usable_keywords(keywords: list[str]) -> list[str]:
    """The check_keywords that actually carry verification weight: trimmed,
    >=3 chars, not a lone generic word, de-duplicated case-insensitively.

    The ledger stores exactly this set, so the verifier's "majority of the
    keywords present" is measured against the same list the gate admitted on -
    a promise can't be padded past the gate with filler and then be
    unverifiable because the verifier counts the filler too.
    """
    out: list[str] = []
    seen: set[str] = set()
    for k in keywords:
        k = k.strip()
        if len(k) < 3:
            continue
        if k.lower() in _GENERIC_KEYWORDS and " " not in k:
            continue  # single generic word matches everything -> useless as a check
        if k.lower() in seen:
            continue  # duplicates don't add checking power -> don't let them pad the count
        seen.add(k.lower())
        out.append(k)
    return out


def run_gate(extraction: PromiseExtraction, announced_date: str) -> GateResult:
    if not extraction.is_falsifiable:
        return GateResult(
            accepted=False,
            reason=f"extractor rejected: {extraction.rejection_reason or 'not falsifiable'}",
        )

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", extraction.deadline_date_iso or ""):
        return GateResult(accepted=False, reason=f"no normalized deadline (got {extraction.deadline_date_iso!r})")
    try:
        deadline = dt.date.fromisoformat(extraction.deadline_date_iso)
    except ValueError:
        return GateResult(accepted=False, reason=f"unparseable deadline {extraction.deadline_date_iso!r}")

    try:
        announced = dt.date.fromisoformat(announced_date)
    except ValueError:
        return GateResult(accepted=False, reason=f"unparseable announced_date {announced_date!r}")

    if deadline < announced:
        return GateResult(accepted=False, reason=f"deadline {deadline} is before the announcement {announced}")
    if _too_far_out(announced, deadline):
        return GateResult(
            accepted=False,
            reason=f"deadline {deadline} is more than {MAX_DEADLINE_HORIZON_YEARS} years past the announcement",
        )

    if len(extraction.observable_outcome.split()) < 3:
        return GateResult(accepted=False, reason="observable_outcome too thin to check")

    usable = usable_keywords(extraction.check_keywords)
    if len(usable) < 2:
        return GateResult(
            accepted=False,
            reason=f"need >=2 specific check_keywords, got {usable or 'none usable'}",
        )

    return GateResult(accepted=True, reason=f"accepted ({len(usable)} usable keywords, deadline {deadline})")
