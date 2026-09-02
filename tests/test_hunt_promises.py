"""
Adversarial tests for ledger.promises - hunting store, scorecard, and persistence bugs.
No network, no LLM calls.
"""

import datetime as dt
import time

import pytest

from agents.promise_schemas import LedgerPromise, PromiseStatus, VerificationResult
from ledger import promises
from ledger.promises import InMemoryBackend


# =========================================================================== #
# 0. admit_promise stores exactly the gate-usable keyword set
# =========================================================================== #
def test_admit_promise_stores_only_the_vetted_keywords():
    """The gate admits on `usable_keywords(...)`; the verifier measures its
    majority against `len(check_keywords)`. If admit_promise kept filler the
    gate ignored, a promise could pass the gate on 2 strong keywords yet never
    reach FULFILLED because the verifier's denominator counts the filler too."""
    be = InMemoryBackend()
    pid = promises.admit_promise(
        company="Acme", promise_text="ship X", source_quote="q",
        source_url="https://example.com", announced_date="2024-01-01",
        deadline_raw="Q2 2024", deadline_date="2024-06-30",
        observable_outcome="Feature X on the dashboard",
        # "api" and "beta" are lone generic words; "x" is too short; "Feature X"
        # is duplicated. Only two tokens actually carry weight.
        check_keywords=["Feature X", "feature x", "api", "beta", "x", "Acme Console"],
        backend=be,
    )
    stored = promises.get_promise(pid, backend=be)["check_keywords"]
    assert stored == ["Feature X", "Acme Console"]


def test_admit_promise_rejects_when_fewer_than_two_usable_keywords():
    be = InMemoryBackend()
    with pytest.raises(ValueError):
        promises.admit_promise(
            company="Acme", promise_text="ship X", source_quote="q",
            source_url="https://example.com", announced_date="2024-01-01",
            deadline_raw="Q2 2024", deadline_date="2024-06-30",
            observable_outcome="Feature X on the dashboard",
            check_keywords=["api", "beta", "new"],  # all filler
            backend=be,
        )


def test_admit_promise_is_idempotent_on_company_deadline_and_quote():
    """Re-running the same announcement through the demo pipeline must not add
    a duplicate row to the shared public scorecard."""
    be = InMemoryBackend()
    kw = {
        "company": "Acme", "promise_text": "ship X",
        "source_quote": "We will ship X by Q2 2024.",
        "source_url": "https://example.com", "announced_date": "2024-01-01",
        "deadline_raw": "Q2 2024", "deadline_date": "2024-06-30",
        "observable_outcome": "Feature X on the dashboard",
        "check_keywords": ["Feature X", "Acme Console"], "backend": be,
    }
    first = promises.admit_promise(**kw)
    second = promises.admit_promise(**{**kw, "promise_text": "reworded", "check_keywords": ["Feature X", "Acme Console", "v2 API"]})
    assert first == second
    assert len(be.all()) == 1

    # a genuinely different deadline is a different promise
    third = promises.admit_promise(**{**kw, "deadline_date": "2024-12-31"})
    assert third != first
    assert len(be.all()) == 2


# =========================================================================== #
# 1. apply_verification overwrites resolved_at bug
# =========================================================================== #
def test_apply_verification_preserves_first_resolved_at():
    """
    When apply_verification is called repeatedly on an already-resolved promise
    (e.g. a daily cron re-evaluating DELAYED promises), `resolved_at` must keep
    the FIRST resolution timestamp, not be bumped every run
    (regression guard for BUG-02).
    """
    be = InMemoryBackend()
    pid = promises.admit_promise(
        company="Acme",
        promise_text="Launch X",
        source_quote="Quote",
        source_url="https://example.com",
        announced_date="2024-01-01",
        deadline_raw="2024-06-30",
        deadline_date="2024-06-30",
        observable_outcome="Feature is live",
        check_keywords=["Feature X", "Acme"],
        backend=be,
    )

    res1 = VerificationResult(
        status=PromiseStatus.DELAYED,
        reason="Deadline passed, not shipped",
        evidence_url="https://example.com/docs",
        checked_at="2024-07-01T00:00:00",
    )
    promises.apply_verification(pid, res1, backend=be)
    doc1 = promises.get_promise(pid, backend=be)
    initial_resolved_at = doc1["resolved_at"]
    assert initial_resolved_at is not None

    # Simulate subsequent check 30 days later
    time.sleep(0.01)
    res2 = VerificationResult(
        status=PromiseStatus.DELAYED,
        reason="Still not shipped",
        evidence_url="https://example.com/docs",
        checked_at="2024-08-01T00:00:00",
    )
    promises.apply_verification(pid, res2, backend=be)
    doc2 = promises.get_promise(pid, backend=be)

    # resolved_at is immutable once set.
    assert doc2["resolved_at"] == initial_resolved_at


# =========================================================================== #
# 2. Scorecard edge cases (0 promises, all pending, all unverifiable)
# =========================================================================== #
def test_scorecard_empty_backend():
    """Empty ledger should return total=0, on_time_rate_pct=None, no division by zero."""
    be = InMemoryBackend()
    card = promises.get_scorecard(backend=be)
    assert card["overall"]["total"] == 0
    assert card["overall"]["resolved"] == 0
    assert card["overall"]["on_time_rate_pct"] is None
    assert card["companies"] == []


def test_scorecard_all_pending():
    """Ledger with only PENDING promises."""
    be = InMemoryBackend()
    for i in range(3):
        promises.admit_promise(
            company="Acme",
            promise_text=f"Promise {i}",
            source_quote=f"Verbatim quote {i}",
            source_url="https://example.com",
            announced_date="2026-01-01",
            deadline_raw="2027-01-01",
            deadline_date="2027-01-01",
            observable_outcome="Outcome text here",
            check_keywords=["keyword one", "keyword two"],
            backend=be,
        )
    card = promises.get_scorecard(backend=be)
    assert card["overall"]["total"] == 3
    assert card["overall"]["pending"] == 3
    assert card["overall"]["resolved"] == 0
    assert card["overall"]["on_time_rate_pct"] is None
    assert card["companies"][0]["pending"] == 3
    assert card["companies"][0]["on_time_rate_pct"] is None


def test_scorecard_all_unverifiable():
    """Ledger with only UNVERIFIABLE promises."""
    be = InMemoryBackend()
    pid = promises.admit_promise(
        company="BetaCo",
        promise_text="Promise B",
        source_quote="Quote",
        source_url="https://example.com",
        announced_date="2024-01-01",
        deadline_raw="2024-06-30",
        deadline_date="2024-06-30",
        observable_outcome="Outcome text here",
        check_keywords=["keyword one", "keyword two"],
        backend=be,
    )
    res = VerificationResult(
        status=PromiseStatus.UNVERIFIABLE,
        reason="404 Not Found",
        evidence_url="https://example.com/broken",
    )
    promises.apply_verification(pid, res, backend=be)
    
    card = promises.get_scorecard(backend=be)
    assert card["overall"]["total"] == 1
    assert card["overall"]["unverifiable"] == 1
    assert card["overall"]["resolved"] == 0
    assert card["overall"]["on_time_rate_pct"] is None


# =========================================================================== #
# 3. Scorecard comprehensive status coverage
# =========================================================================== #
def test_scorecard_covers_all_seven_statuses_correctly():
    """
    Verify that get_scorecard correctly partitions all 7 PromiseStatus values
    without double counting or missing any status.
    """
    be = InMemoryBackend()
    statuses = [
        PromiseStatus.FULFILLED,
        PromiseStatus.FULFILLED_LATE,
        PromiseStatus.PARTIALLY_FULFILLED,
        PromiseStatus.DELAYED,
        PromiseStatus.ABANDONED,
        PromiseStatus.PENDING,
        PromiseStatus.UNVERIFIABLE,
    ]
    for st in statuses:
        pid = promises.admit_promise(
            company="MultiStatusCo",
            promise_text=f"Promise {st.value}",
            source_quote=f"Verbatim quote for {st.value}",
            source_url="https://example.com",
            announced_date="2024-01-01",
            deadline_raw="2024-06-30",
            deadline_date="2024-06-30",
            observable_outcome="Outcome text here",
            check_keywords=["keyword one", "keyword two"],
            backend=be,
        )
        res = VerificationResult(status=st, reason=f"Reason for {st.value}")
        promises.apply_verification(pid, res, backend=be)

    card = promises.get_scorecard(backend=be)
    ov = card["overall"]
    assert ov["total"] == 7
    assert ov["resolved"] == 5  # FULFILLED, FULFILLED_LATE, PARTIALLY_FULFILLED, DELAYED, ABANDONED
    assert ov["kept_on_time"] == 1  # FULFILLED only
    assert ov["kept_late_or_partial"] == 2  # FULFILLED_LATE, PARTIALLY_FULFILLED
    assert ov["delayed"] == 1
    assert ov["abandoned"] == 1
    assert ov["pending"] == 1
    assert ov["unverifiable"] == 1
    assert ov["on_time_rate_pct"] == 20.0  # 1 on time / 5 resolved = 20.0%


def test_scorecard_excludes_undated_fulfillments_from_on_time_rate():
    """A FULFILLED promise whose ship date could not be read (ship_date_confirmed
    False) lands in kept_undated and is removed from BOTH sides of the on-time
    rate - it is neither counted on time nor allowed to drag the rate down."""
    be = InMemoryBackend()
    specs = [
        ("dated-ontime", PromiseStatus.FULFILLED, True),
        ("dated-ontime-2", PromiseStatus.FULFILLED, True),
        ("undated", PromiseStatus.FULFILLED, False),
        ("late", PromiseStatus.FULFILLED_LATE, True),
    ]
    for name, st, confirmed in specs:
        pid = promises.admit_promise(
            company="Co", promise_text=name, source_quote=f"verbatim {name}", source_url="https://e.co",
            announced_date="2024-01-01", deadline_raw="Q1", deadline_date="2024-03-31",
            observable_outcome="a b c", check_keywords=["k one", "k two"], backend=be,
        )
        promises.apply_verification(
            pid, VerificationResult(status=st, reason=name, ship_date_confirmed=confirmed), backend=be
        )

    ov = promises.get_scorecard(backend=be)["overall"]
    assert ov["resolved"] == 4
    assert ov["kept_on_time"] == 2
    assert ov["kept_undated"] == 1
    assert ov["kept_late_or_partial"] == 1
    # denominator = resolved - undated = 3; on time = 2  ->  66.7%
    assert ov["on_time_rate_pct"] == 66.7


# =========================================================================== #
# 4. due_for_check infinite tracking of UNVERIFIABLE
# =========================================================================== #
def test_due_for_check_stops_retrying_stale_unverifiable():
    """
    An UNVERIFIABLE promise is retried only while there's a reasonable chance
    the page comes back; once the deadline is more than ABANDON_GRACE_DAYS old
    it stops being re-queued forever (regression guard for BUG-04).
    """
    from ledger.verifier import ABANDON_GRACE_DAYS

    be = InMemoryBackend()
    pid = promises.admit_promise(
        company="OldCo",
        promise_text="Promise from 2020",
        source_quote="Quote",
        source_url="https://example.com",
        announced_date="2020-01-01",
        deadline_raw="2020-06-30",
        deadline_date="2020-06-30",
        observable_outcome="Outcome text here",
        check_keywords=["keyword one", "keyword two"],
        backend=be,
    )
    res = VerificationResult(status=PromiseStatus.UNVERIFIABLE, reason="Page unavailable")
    promises.apply_verification(pid, res, backend=be)

    deadline = dt.date(2020, 6, 30)

    # Still inside the grace window -> retried.
    inside = promises.due_for_check(
        check_date=deadline + dt.timedelta(days=ABANDON_GRACE_DAYS), backend=be
    )
    assert [d["id"] for d in inside] == [pid]

    # One day past the grace window -> no longer re-queued.
    outside = promises.due_for_check(
        check_date=deadline + dt.timedelta(days=ABANDON_GRACE_DAYS + 1), backend=be
    )
    assert outside == []

    # Years later -> still not re-queued.
    assert promises.due_for_check(check_date=dt.date(2026, 8, 27), backend=be) == []


def test_admit_promise_dedups_across_smart_quote_and_whitespace_variants():
    """The same announcement re-run through the pipeline can come back with
    curly quotes one time and straight quotes the next, or with different
    spacing - it must still collide on the dedup key, not stack a second row."""
    be = InMemoryBackend()
    common = {
        "company": "Acme", "promise_text": "ship X", "source_url": "https://example.com",
        "announced_date": "2024-01-01", "deadline_raw": "Q2 2024", "deadline_date": "2024-06-30",
        "observable_outcome": "Feature X on the dashboard",
        "check_keywords": ["Feature X", "Acme Dashboard"], "backend": be,
    }
    id1 = promises.admit_promise(source_quote='We will ship "Feature X" by Q2 2024.', **common)
    id2 = promises.admit_promise(source_quote="We will ship “Feature X”  by Q2 2024.", **common)
    id3 = promises.admit_promise(source_quote='we will ship "feature x" by q2 2024.', **{**common, "company": " acme "})
    assert id1 == id2 == id3
    assert len(be.all()) == 1


def test_due_for_check_keeps_rechecking_partially_fulfilled():
    """A PARTIALLY_FULFILLED promise past its deadline stays in the cycle: the
    missing half can ship later and flip it to FULFILLED_LATE (BUG-08)."""
    be = InMemoryBackend()
    pid = promises.admit_promise(
        company="Acme", promise_text="ship X and Y", source_quote="q",
        source_url="https://example.com", announced_date="2024-01-01",
        deadline_raw="Q2 2024", deadline_date="2024-06-30",
        observable_outcome="X and Y both on the dashboard",
        check_keywords=["Feature X", "Feature Y"], backend=be,
    )
    promises.apply_verification(
        pid, VerificationResult(status=PromiseStatus.PARTIALLY_FULFILLED, reason="only X so far"),
        backend=be,
    )
    due = promises.due_for_check(check_date=dt.date(2025, 1, 1), backend=be)
    assert [d["id"] for d in due] == [pid]

    # FULFILLED, by contrast, is terminal and must NOT be re-queued.
    promises.apply_verification(
        pid, VerificationResult(status=PromiseStatus.FULFILLED, reason="both shipped"), backend=be,
    )
    assert promises.due_for_check(check_date=dt.date(2025, 1, 1), backend=be) == []


# =========================================================================== #
# 5. Pydantic round-trip integrity
# =========================================================================== #
def test_ledger_promise_pydantic_round_trip():
    """
    Verify that admit -> get -> LedgerPromise(**row) -> verify works without serialization loss.
    """
    be = InMemoryBackend()
    pid = promises.admit_promise(
        company="Anthropic",
        promise_text="Haiku Release",
        source_quote="Quote",
        source_url="https://anthropic.com",
        announced_date="2024-10-22",
        deadline_raw="October 2024",
        deadline_date="2024-10-31",
        observable_outcome="Haiku available",
        check_keywords=["claude-3-5-haiku", "Haiku"],
        evidence_url="https://docs.anthropic.com",
        backend=be,
    )
    row = promises.get_promise(pid, backend=be)
    assert isinstance(row["status"], str)
    assert row["status"] == "PENDING"

    model = LedgerPromise(**row)
    assert isinstance(model.status, PromiseStatus)
    assert model.status == PromiseStatus.PENDING


# =========================================================================== #
# 6. Append-only hash chain over the immutable claim
# =========================================================================== #
def _admit(be, **over):
    kw = {
        "company": "Acme", "promise_text": "ship X",
        "source_quote": "We will ship X by Q2 2024.",
        "source_url": "https://example.com", "announced_date": "2024-01-01",
        "deadline_raw": "Q2 2024", "deadline_date": "2024-06-30",
        "observable_outcome": "Feature X on the dashboard",
        "check_keywords": ["Feature X", "Acme Console"], "backend": be,
    }
    kw.update(over)
    return promises.admit_promise(**kw)


def test_chain_links_each_admission_to_the_previous_one():
    be = InMemoryBackend()
    id0 = _admit(be, source_quote="First promise, ship A by Q2 2024.")
    id1 = _admit(be, source_quote="Second promise, ship B by Q3 2024.", deadline_date="2024-09-30")

    r0 = promises.get_promise(id0, backend=be)
    r1 = promises.get_promise(id1, backend=be)
    assert r0["seq"] == 0 and r0["prev_hash"] == promises.GENESIS_HASH
    assert r1["seq"] == 1 and r1["prev_hash"] == r0["entry_hash"]
    assert r0["entry_hash"] and r1["entry_hash"] and r0["entry_hash"] != r1["entry_hash"]

    chain = promises.verify_chain(backend=be)
    assert chain["intact"] is True
    assert chain["length"] == 2
    assert chain["broken"] == []
    assert chain["head"] == r1["entry_hash"]


def test_chain_detects_an_edited_quote_after_the_fact():
    """Editing a stored source_quote must break that row's entry_hash AND show
    up as a prev_hash mismatch on every row admitted after it."""
    be = InMemoryBackend()
    _admit(be, source_quote="Original wording: ship A by Q2 2024.")
    id1 = _admit(be, source_quote="ship B by Q3 2024.", deadline_date="2024-09-30")
    _admit(be, source_quote="ship C by Q4 2024.", deadline_date="2024-12-31")
    assert promises.verify_chain(backend=be)["intact"] is True

    # tamper: someone rewrites the second promise's quote in storage
    be._docs[id1]["source_quote"] = "ship B by Q3 2024, but only maybe."

    chain = promises.verify_chain(backend=be)
    assert chain["intact"] is False
    seqs = {b["seq"] for b in chain["broken"]}
    assert 1 in seqs  # the edited row's own hash no longer matches
    assert 2 in seqs  # and the row after it no longer chains to a valid prev


def test_chain_survives_a_verification_status_update():
    """apply_verification changes status/verdict fields, which are deliberately
    NOT part of the chain - the chain must stay intact across a cycle."""
    be = InMemoryBackend()
    pid = _admit(be)
    promises.apply_verification(
        pid, VerificationResult(status=PromiseStatus.FULFILLED, reason="shipped"), backend=be
    )
    assert promises.get_promise(pid, backend=be)["status"] == "FULFILLED"
    assert promises.verify_chain(backend=be)["intact"] is True


def test_empty_ledger_chain_is_trivially_intact():
    chain = promises.verify_chain(backend=InMemoryBackend())
    assert chain == {"length": 0, "intact": True, "broken": [], "head": promises.GENESIS_HASH}
