"""
The zero-LLM verifier. Given a promise and the date it's checked on, decide a
PromiseStatus from keyword presence + point-in-time evidence + deadline
arithmetic. No model call anywhere in this file - "we said X shipped and it
did" must never be an inferred claim.

Two probes, both LLM-free:

  1. The official page **as archived on or before the deadline** (Wayback
     Machine). If the check keywords are present in that capture, the promise
     was kept ON TIME and the capture timestamp is the dated proof - no
     prose-date parsing, no third party beyond a neutral public archive. If
     that capture exists and the keywords are ABSENT, that is hard proof it
     had not shipped by the deadline.

  2. The page now (live, or a recent archive capture if the live page is
     bot-blocked / JS-only). Combined with probe 1 this yields FULFILLED_LATE
     vs DELAYED vs ABANDONED.

Decision table (deadline D, check date T):
  keywords present in the on/before-D archive capture ...... FULFILLED (on time)
  absent at D, present now ................................. FULFILLED_LATE
  no archive capture at D; present now:
      a page date <= D ...................................... FULFILLED (on time)
      a page date >  D ...................................... FULFILLED_LATE
      no readable date ..................................... FULFILLED (undated - kept
                                                             out of the on-time rate)
  some (>=1) but not a majority present, T > D ............. PARTIALLY_FULFILLED
  none present:  T <= D .................................... PENDING
                 D < T <= D + 180d ....................... DELAYED
                 T >  D + 180d ........................... ABANDONED
  live page and archive both unusable ..................... UNVERIFIABLE
"""

from __future__ import annotations

import datetime as dt
import re

from agents.promise_schemas import LedgerPromise, PromiseStatus, VerificationResult
from ledger.archive import snapshot_near
from ledger.evidence import fetch_evidence, keyword_hits

ABANDON_GRACE_DAYS = 180

_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
_MONTHS = {m.lower(): i for i, m in enumerate(_MONTH_NAMES, start=1)}
# Accept the standard 3-letter abbreviations too ("Oct", "sep", ...).
_MONTHS.update({m[:3].lower(): i for i, m in enumerate(_MONTH_NAMES, start=1)})

# re.IGNORECASE on the month patterns so "oct 28, 2024" / "OCTOBER 28, 2024"
# are read as well as Titlecase; the _MONTHS lookup still gates what counts.
# The `(?:st|nd|rd|th)?` makes the day ordinal optional, so "4th November 2024"
# / "November 4th, 2024" is read as well as "4 November 2024".
_DATE_PATTERNS = [
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{4})/(\d{2})/(\d{2})\b"),
    re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\s+(\d{4})\b", re.IGNORECASE),
]


def _majority(n_hits: int, n_total: int) -> bool:
    """A strict majority: more than half of the check_keywords, min 2.

    For an even keyword count this requires > 50% (3 of 4), not exactly half.
    The min-2 floor keeps a lone repeated/whitelisted token from ever
    resolving a promise on its own.
    """
    return n_total > 0 and n_hits >= max(2, n_total // 2 + 1)


def _dates_near(text: str, anchor: str, radius: int = 400) -> list[dt.date]:
    """Pull candidate dates from the window around the first keyword hit."""
    low = text.lower()
    i = low.find(anchor.lower()) if anchor else -1
    window = text if i < 0 else text[max(0, i - radius): i + radius]
    out: list[dt.date] = []
    for rx in _DATE_PATTERNS:
        for m in rx.finditer(window):
            try:
                if rx in (_DATE_PATTERNS[0], _DATE_PATTERNS[1]):  # YYYY-MM-DD / YYYY/MM/DD
                    y, mo, d = int(m[1]), int(m[2]), int(m[3])
                elif rx is _DATE_PATTERNS[2]:  # Month D, YYYY
                    mo = _MONTHS.get(m[1].lower())
                    d, y = int(m[2]), int(m[3])
                else:  # D Month YYYY
                    d = int(m[1])
                    mo = _MONTHS.get(m[2].lower())
                    y = int(m[3])
                if mo and 1 <= mo <= 12 and 1 <= d <= 31 and 2015 <= y <= 2100:
                    out.append(dt.date(y, mo, d))
            except (ValueError, TypeError):
                continue
    return out


def _result(status, reason, *, url, now_iso, hits=None, excerpt="",
            ship_date_confirmed=None, method="", captured="") -> VerificationResult:
    return VerificationResult(
        status=status,
        reason=reason,
        evidence_url=url,
        evidence_excerpt=excerpt,
        keyword_hits=hits or [],
        checked_at=now_iso,
        ship_date_confirmed=ship_date_confirmed,
        verification_method=method,
        evidence_captured_at=captured,
    )


def verify_promise(promise: LedgerPromise, check_date: dt.date | None = None) -> VerificationResult:
    today = check_date or dt.datetime.now(dt.timezone.utc).date()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    url = promise.evidence_url
    keywords = promise.check_keywords
    total = len(keywords)

    # A malformed date on the stored record is a data problem, not a delivery
    # signal - report it as UNVERIFIABLE instead of raising out of the cycle.
    try:
        deadline = dt.date.fromisoformat(promise.deadline_date)
        announced = dt.date.fromisoformat(promise.announced_date)
    except (ValueError, TypeError) as exc:
        return _result(PromiseStatus.UNVERIFIABLE,
                       f"promise record has an unparseable date ({exc})",
                       url=url, now_iso=now_iso, method="unverifiable")

    # ---- Probe 1: the official page as archived on or before the deadline ----
    absent_by_deadline = ""
    snap = snapshot_near(url, deadline)
    if snap and snap.ok and announced <= snap.captured <= deadline:
        ev_d = fetch_evidence(snap.archive_url, timeout=15.0)
        if ev_d.ok and not ev_d.looks_like_spa_shell:
            hits_d = keyword_hits(ev_d.text, keywords)
            if _majority(len(hits_d), total):
                return _result(
                    PromiseStatus.FULFILLED,
                    f"{len(hits_d)}/{total} check keywords present on {url} as archived "
                    f"{snap.captured.isoformat()} (on or before deadline {deadline.isoformat()})",
                    url=url, now_iso=now_iso, hits=hits_d,
                    excerpt=ev_d.excerpt_around(hits_d[0]),
                    ship_date_confirmed=True, method="wayback@deadline",
                    captured=snap.captured.isoformat(),
                )
            absent_by_deadline = f"absent from {url} as archived {snap.captured.isoformat()}"

    # ---- Probe 2: the page now (live, or a recent archive capture) ----
    ev = fetch_evidence(url)
    method = "live-page"
    captured_now = ""
    if not ev.ok or ev.looks_like_spa_shell:
        snap_now = snapshot_near(url, today)
        if snap_now and snap_now.ok:
            ev = fetch_evidence(snap_now.archive_url, timeout=15.0)
            method, captured_now = "wayback@now", snap_now.captured.isoformat()

    if not ev.ok or ev.looks_like_spa_shell:
        why = ev.error or "page returned only a JS shell / navigation, no checkable content"
        return _result(PromiseStatus.UNVERIFIABLE,
                       f"could not verify against {url or '(no url)'}: {why}",
                       url=url, now_iso=now_iso, method="unverifiable")

    hits = keyword_hits(ev.text, keywords)
    n = len(hits)
    excerpt = ev.excerpt_around(hits[0]) if hits else ev.text[:300]
    seen = f" (archived {captured_now})" if captured_now else ""

    if _majority(n, total):
        if absent_by_deadline:
            return _result(PromiseStatus.FULFILLED_LATE,
                           f"{absent_by_deadline}; {n}/{total} keywords present now{seen} "
                           f"- shipped after deadline {deadline.isoformat()}",
                           url=url, now_iso=now_iso, hits=hits, excerpt=excerpt,
                           ship_date_confirmed=True, method=f"{method}+archive-gap",
                           captured=captured_now)
        # No point-in-time capture pins the timing - fall back to a date on the page.
        page_dates = [d for d in _dates_near(ev.text, hits[0]) if d >= announced]
        earliest = min(page_dates) if page_dates else None
        if earliest and earliest <= deadline:
            return _result(PromiseStatus.FULFILLED,
                           f"{n}/{total} keywords present on {url}{seen}; page dates it "
                           f"{earliest.isoformat()}, on or before deadline {deadline.isoformat()}",
                           url=url, now_iso=now_iso, hits=hits, excerpt=excerpt,
                           ship_date_confirmed=True, method=f"{method}+date", captured=captured_now)
        if earliest and earliest > deadline:
            return _result(PromiseStatus.FULFILLED_LATE,
                           f"{n}/{total} keywords present{seen}; page dates it {earliest.isoformat()}, "
                           f"{(earliest - deadline).days}d after deadline {deadline.isoformat()}",
                           url=url, now_iso=now_iso, hits=hits, excerpt=excerpt,
                           ship_date_confirmed=True, method=f"{method}+date", captured=captured_now)
        return _result(PromiseStatus.FULFILLED,
                       f"{n}/{total} keywords present on {url}{seen}: {hits}; delivery proven but no "
                       "point-in-time capture or page date establishes timing",
                       url=url, now_iso=now_iso, hits=hits, excerpt=excerpt,
                       ship_date_confirmed=False, method=method, captured=captured_now)

    if n >= 1:
        if today <= deadline:
            return _result(PromiseStatus.PENDING,
                           f"only {n}/{total} keywords present and deadline {deadline.isoformat()} "
                           "not yet reached",
                           url=url, now_iso=now_iso, hits=hits, excerpt=excerpt, method=method)
        return _result(PromiseStatus.PARTIALLY_FULFILLED,
                       f"deadline {deadline.isoformat()} passed; partial evidence only "
                       f"({n}/{total} keywords: {hits})",
                       url=url, now_iso=now_iso, hits=hits, excerpt=excerpt, method=method)

    if today <= deadline:
        return _result(PromiseStatus.PENDING,
                       f"deadline {deadline.isoformat()} not yet reached; no delivery evidence on {url}",
                       url=url, now_iso=now_iso, excerpt=excerpt, method=method)
    if today <= deadline + dt.timedelta(days=ABANDON_GRACE_DAYS):
        return _result(PromiseStatus.DELAYED,
                       f"deadline {deadline.isoformat()} passed {(today - deadline).days}d ago; "
                       f"no delivery evidence on {url} (0/{total} keywords)",
                       url=url, now_iso=now_iso, excerpt=excerpt, method=method)
    return _result(PromiseStatus.ABANDONED,
                   f"deadline {deadline.isoformat()} passed {(today - deadline).days}d ago "
                   f"(> {ABANDON_GRACE_DAYS}d grace); still no delivery evidence on {url}",
                   url=url, now_iso=now_iso, excerpt=excerpt, method=method)
