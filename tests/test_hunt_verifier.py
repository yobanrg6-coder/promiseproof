"""
Adversarial tests for ledger.verifier - hunting edge cases and bugs.
No network, no LLM calls.
"""

import datetime as dt

from agents.promise_schemas import LedgerPromise, PromiseStatus
from ledger import evidence as evidence_mod
from ledger import verifier
from ledger.archive import ArchiveSnapshot
from ledger.verifier import _dates_near, _majority, verify_promise


def _fake_evidence(text: str, ok: bool = True, shell: bool = False, url: str = "https://example.com/docs"):
    def _fetch(u, timeout=25.0):
        return evidence_mod.Evidence(url=url, ok=ok, text=text, looks_like_spa_shell=shell)
    return _fetch


def _fake_evidence_by_url(pages: dict[str, str], default: str = ""):
    """Route fetch_evidence by URL: keys are matched as substrings of the
    fetched URL, so an archive URL like 'web.archive.org/web/.../acme.com/docs'
    can be keyed on 'web.archive.org'."""
    def _fetch(u, timeout=25.0):
        for frag, text in pages.items():
            if frag in u:
                return evidence_mod.Evidence(url=u, ok=bool(text), text=text,
                                             looks_like_spa_shell=len(text) < 1)
        return evidence_mod.Evidence(url=u, ok=bool(default), text=default,
                                     looks_like_spa_shell=len(default) < 1)
    return _fetch


def _snap(captured: str, url: str = "http://web.archive.org/web/x/https://acme.com/docs"):
    return lambda *a, **k: ArchiveSnapshot(
        original_url="https://acme.com/docs", archive_url=url,
        captured=dt.date.fromisoformat(captured),
    )


def _make_promise(**kwargs):
    defaults = {
        "id": "test-p1",
        "company": "Acme Corp",
        "promise_text": "Acme launches Feature X",
        "source_quote": "We will launch Feature X by Q4 2024.",
        "source_url": "https://acme.com/news",
        "announced_date": "2024-01-15",
        "deadline_raw": "end of Q4 2024",
        "deadline_date": "2024-12-31",
        "observable_outcome": "Feature X is available in Acme dashboard",
        "check_keywords": ["Feature X", "Acme Dashboard"],
        "evidence_url": "https://acme.com/docs",
    }
    defaults.update(kwargs)
    return LedgerPromise(**defaults)


# =========================================================================== #
# 1. Substring collisions & false positives in keyword_hits
# =========================================================================== #
def test_keyword_hits_ignores_substring_collisions_in_prose():
    """
    keyword_hits must match whole tokens only. Common short technical tokens
    must NOT match unrelated English prose that merely contains them as
    substrings (regression guard for BUG-01).
    """
    text = "We are improving our available product navigation across our studios."
    keywords = ["AI", "Pro", "GA", "iOS"]
    hits = evidence_mod.keyword_hits(text, keywords)
    assert hits == []  # none present as standalone tokens

    # ...but a real standalone occurrence still registers, case-insensitively.
    assert evidence_mod.keyword_hits("Now in GA for all users.", ["GA"]) == ["GA"]
    assert evidence_mod.keyword_hits("Shipped on ios today.", ["iOS"]) == ["iOS"]


def test_verifier_no_false_fulfillment_from_substring_match(monkeypatch):
    """
    An unrelated page whose prose merely contains substrings of the keywords
    must not be marked FULFILLED (regression guard for BUG-01).
    """
    unrelated_page = "Our team is working on organization and navigation improvements across studios."
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence(unrelated_page))

    p = _make_promise(
        check_keywords=["GA", "iOS"],  # substrings of 'navigation' and 'studios'
        announced_date="2024-01-01",
        deadline_date="2024-12-31",
    )
    r = verify_promise(p, check_date=dt.date(2025, 1, 15))
    # 0 real hits, within the abandon grace window after the deadline.
    assert r.status == PromiseStatus.DELAYED


# =========================================================================== #
# 2. _majority boundary arithmetic
# =========================================================================== #
def test_majority_boundary_even_numbers_require_strict_majority():
    """
    A strict majority must be > 50% (regression guard for BUG-03).
    Exactly half of an even keyword count is NOT a majority.
    """
    assert _majority(2, 4) is False  # 50% is not a majority
    assert _majority(3, 6) is False
    assert _majority(4, 8) is False
    assert _majority(3, 4) is True   # > 50%
    assert _majority(4, 6) is True
    assert _majority(2, 3) is True   # odd count unchanged: 2/3


def test_majority_single_keyword_always_fails():
    """
    If a promise has 1 keyword and it matches (1/1 = 100%), _majority returns False
    because max(2, (1+1)//2) is 2, requiring >= 2 hits.
    """
    assert _majority(1, 1) is False  # 100% match fails majority check!


def test_majority_zero_total():
    """Empty keyword list should not cause division by zero and return False."""
    assert _majority(0, 0) is False
    assert _majority(1, 0) is False


# =========================================================================== #
# 3. _dates_near parsing limitations
# =========================================================================== #
def test_dates_near_handles_lowercase_or_uppercase_month():
    """Month case must not matter (regression guard for BUG-05)."""
    text_lower = "Feature X shipped on october 28, 2024 in general availability."
    assert dt.date(2024, 10, 28) in _dates_near(text_lower, "Feature X")

    text_upper = "FEATURE X SHIPPED ON OCTOBER 28, 2024 FOR ALL USERS."
    assert dt.date(2024, 10, 28) in _dates_near(text_upper, "FEATURE X")


def test_dates_near_handles_abbreviated_months():
    """3-letter month abbreviations must parse (regression guard for BUG-05)."""
    assert dt.date(2024, 10, 28) in _dates_near("Feature X released Oct 28, 2024.", "Feature X")
    assert dt.date(2024, 10, 28) in _dates_near("Feature X released 28 Oct 2024.", "Feature X")


def test_dates_near_handles_iso_slash_dates():
    """YYYY/MM/DD must parse (regression guard for BUG-05)."""
    text = "Feature X release date: 2024/10/28."
    assert dt.date(2024, 10, 28) in _dates_near(text, "Feature X")


def test_dates_near_handles_ordinal_day_suffixes():
    """'4th November 2024' / 'November 4th, 2024' must parse the same as the
    non-ordinal forms. Regression guard: the Anthropic seed's ship date is
    only ever written with an ordinal on its evidence page, and without this
    the verifier read that promise as on-time instead of FULFILLED_LATE."""
    assert dt.date(2024, 11, 4) in _dates_near("Claude 3.5 Haiku 4th November 2024 ...", "Claude 3.5 Haiku")
    assert dt.date(2025, 2, 25) in _dates_near("vision support was added on 25th February 2025.", "vision support")
    assert dt.date(2024, 11, 4) in _dates_near("shipped November 4th, 2024 to everyone", "shipped")


def test_verifier_reads_slash_date_as_late_when_after_deadline(monkeypatch):
    """
    A parseable ship date after the deadline must resolve to FULFILLED_LATE,
    not a default on-time FULFILLED (regression guard for BUG-05).
    """
    page = "Feature X and Acme Dashboard are live! Released 2025/06/01."
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence(page))

    p = _make_promise(deadline_date="2024-12-31")
    r = verify_promise(p, check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.FULFILLED_LATE


def test_verifier_defaults_to_fulfilled_when_truly_no_date(monkeypatch):
    """
    Majority of keywords present but genuinely no dateable ship signal ->
    FULFILLED with the reason noting the date could not be established.
    """
    page = "Feature X and Acme Dashboard are live now for everyone."
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence(page))

    p = _make_promise(deadline_date="2024-12-31")
    r = verify_promise(p, check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.FULFILLED
    assert "establishes timing" in r.reason  # neither an archive capture nor a page date
    # delivery proven but undated -> must be flagged so the scorecard keeps it
    # out of the on-time rate instead of counting it as on time.
    assert r.ship_date_confirmed is False


def test_verifier_marks_ship_date_confirmed_when_dated(monkeypatch):
    page = "Feature X and Acme Dashboard shipped on October 28, 2024."
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence(page))
    p = _make_promise(deadline_date="2024-12-31")
    r = verify_promise(p, check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.FULFILLED
    assert r.ship_date_confirmed is True


# =========================================================================== #
# 4. Temporal boundaries
# =========================================================================== #
def test_verifier_exact_deadline_date_with_zero_hits(monkeypatch):
    """On the exact deadline date with 0 hits, status is PENDING."""
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("Nothing relevant."))
    p = _make_promise(deadline_date="2026-08-27")
    r = verify_promise(p, check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.PENDING


def test_verifier_exact_abandon_grace_day_boundary(monkeypatch):
    """
    At deadline + 180 days (ABANDON_GRACE_DAYS), status is DELAYED.
    At deadline + 181 days, status is ABANDONED.
    """
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("Nothing relevant."))
    deadline = dt.date(2026, 1, 1)
    p = _make_promise(deadline_date=deadline.isoformat())
    
    # Exactly 180 days
    r_180 = verify_promise(p, check_date=deadline + dt.timedelta(days=180))
    assert r_180.status == PromiseStatus.DELAYED

    # 181 days
    r_181 = verify_promise(p, check_date=deadline + dt.timedelta(days=181))
    assert r_181.status == PromiseStatus.ABANDONED


def test_verifier_partial_evidence_on_deadline_vs_after(monkeypatch):
    """
    1 out of 2 keywords:
    - On or before deadline -> PENDING
    - 1 day after deadline -> PARTIALLY_FULFILLED
    """
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("Feature X is here without the dashboard."))
    deadline = dt.date(2026, 8, 27)
    p = _make_promise(deadline_date=deadline.isoformat(), check_keywords=["Feature X", "Acme Dashboard"])
    
    r_on = verify_promise(p, check_date=deadline)
    assert r_on.status == PromiseStatus.PENDING

    r_after = verify_promise(p, check_date=deadline + dt.timedelta(days=1))
    assert r_after.status == PromiseStatus.PARTIALLY_FULFILLED


def test_verifier_reports_unverifiable_on_corrupted_date_instead_of_crashing(monkeypatch):
    """
    A malformed date on the stored record is a data problem, not a delivery
    signal: verify_promise must return UNVERIFIABLE, not raise out of the cycle.
    """
    page = "Feature X and Acme Dashboard launched on October 28, 2024."
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence(page))

    r = verify_promise(_make_promise(announced_date="invalid-date"), check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.UNVERIFIABLE
    assert "unparseable date" in r.reason

    r2 = verify_promise(_make_promise(deadline_date="not-a-date"), check_date=dt.date(2026, 8, 27))
    assert r2.status == PromiseStatus.UNVERIFIABLE


# =========================================================================== #
# 5. Point-in-time verification via the Wayback Machine
# =========================================================================== #
def test_archive_capture_on_or_before_deadline_with_keywords_is_fulfilled_on_time(monkeypatch):
    """The strong path: the official page, as archived on/before the deadline,
    already carries the check keywords -> FULFILLED on time, and the capture
    date is the dated proof (no prose-date parsing needed)."""
    monkeypatch.setattr(verifier, "snapshot_near", _snap("2024-06-30"))
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence_by_url(
        {"web.archive.org": "Feature X is live in the Acme Dashboard.",
         "acme.com/docs": "unrelated current content"}))

    p = _make_promise(announced_date="2024-02-01", deadline_date="2024-06-30")
    r = verify_promise(p, check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.FULFILLED
    assert r.ship_date_confirmed is True
    assert r.verification_method == "wayback@deadline"
    assert r.evidence_captured_at == "2024-06-30"


def test_archive_absent_at_deadline_but_present_now_is_fulfilled_late(monkeypatch):
    """The archived page from on/before the deadline does NOT have the
    keywords, but the live page does -> it shipped, but late."""
    monkeypatch.setattr(verifier, "snapshot_near", _snap("2024-06-15"))
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence_by_url(
        {"web.archive.org": "Nothing has shipped yet. Coming soon.",
         "acme.com/docs": "Feature X is now live in the Acme Dashboard."}))

    p = _make_promise(announced_date="2024-02-01", deadline_date="2024-06-30")
    r = verify_promise(p, check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.FULFILLED_LATE
    assert r.ship_date_confirmed is True
    assert "archive-gap" in r.verification_method


def test_bot_blocked_live_page_is_verified_via_a_recent_archive_capture(monkeypatch):
    """The live page 403s to non-browser clients; a recent Wayback capture
    still lets the verifier resolve it instead of giving up as UNVERIFIABLE."""
    calls = {"n": 0}

    def snap(url, target, **k):
        # no capture near the deadline, but one near 'today'
        calls["n"] += 1
        return None if calls["n"] == 1 else ArchiveSnapshot(
            "https://acme.com/docs", "http://web.archive.org/web/2026/acme", dt.date(2026, 8, 1))

    monkeypatch.setattr(verifier, "snapshot_near", snap)
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence_by_url(
        {"web.archive.org": "Feature X shipped in the Acme Dashboard.",
         "acme.com/docs": ""}))  # live fetch returns empty/not-ok

    p = _make_promise(announced_date="2024-01-15", deadline_date="2024-12-31")
    r = verify_promise(p, check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.FULFILLED
    assert r.verification_method == "wayback@now"


def test_archive_snapshot_after_the_deadline_is_not_treated_as_on_time_proof(monkeypatch):
    """snapshot_near returns the closest capture in either direction; one from
    AFTER the deadline must not be used to claim on-time delivery."""
    monkeypatch.setattr(verifier, "snapshot_near", _snap("2025-03-01"))  # long after deadline
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence_by_url(
        {"web.archive.org": "Feature X and Acme Dashboard are live.",
         "acme.com/docs": "Feature X and Acme Dashboard are live now."}))

    p = _make_promise(announced_date="2024-02-01", deadline_date="2024-06-30")
    r = verify_promise(p, check_date=dt.date(2026, 8, 27))
    # no usable point-in-time capture, no page date -> FULFILLED but undated
    assert r.status == PromiseStatus.FULFILLED
    assert r.ship_date_confirmed is False
    assert r.verification_method == "live-page"
