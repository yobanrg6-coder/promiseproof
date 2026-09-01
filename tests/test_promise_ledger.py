"""Backbone tests for PromiseProof: gate + verifier + store + scorecard.
No network, no LLM (evidence fetch is monkeypatched)."""

import datetime as dt

from agents.falsifiability_gate import run_gate
from agents.promise_schemas import PromiseExtraction, PromiseStatus
from ledger import evidence as evidence_mod
from ledger import promises, verifier
from ledger.promises import InMemoryBackend

ANNOUNCED = "2024-10-22"


def _ext(**kw):
    base = {
        "is_falsifiable": True,
        "company": "Anthropic",
        "promise_text": "Claude 3.5 Haiku will be released later this month",
        "source_quote": "The new Claude 3.5 Haiku will be released later this month.",
        "observable_outcome": "Claude 3.5 Haiku is available via the Anthropic API and Bedrock",
        "check_keywords": ["claude-3-5-haiku", "Claude 3.5 Haiku", "Amazon Bedrock"],
        "deadline_raw": "later this month",
        "deadline_date_iso": "2024-10-31",
        "evidence_url_hint": "https://docs.claude.com/",
        "rejection_reason": "",
    }
    base.update(kw)
    return PromiseExtraction(**base)


# ----------------------------- gate --------------------------------------- #
def test_gate_accepts_well_formed_promise():
    assert run_gate(_ext(), ANNOUNCED).accepted


def test_gate_rejects_non_falsifiable():
    r = run_gate(_ext(is_falsifiable=False, rejection_reason="aspirational"), ANNOUNCED)
    assert not r.accepted and "aspirational" in r.reason


def test_gate_rejects_missing_deadline():
    assert not run_gate(_ext(deadline_date_iso=""), ANNOUNCED).accepted


def test_gate_rejects_deadline_before_announcement():
    assert not run_gate(_ext(deadline_date_iso="2024-01-01"), ANNOUNCED).accepted


def test_gate_rejects_single_generic_keywords():
    assert not run_gate(_ext(check_keywords=["API", "beta"]), ANNOUNCED).accepted


# --------------------------- verifier ----------------------------------- #
def _fake_evidence(text, ok=True, shell=False):
    def _fetch(url, timeout=25.0):
        return evidence_mod.Evidence(url=url, ok=ok, text=text, looks_like_spa_shell=shell)
    return _fetch


def _promise(**kw):
    d = {
        "id": "p1", "company": "Anthropic",
        "promise_text": "x", "source_quote": "x", "source_url": "https://a.co",
        "announced_date": ANNOUNCED, "deadline_raw": "later this month", "deadline_date": "2024-10-31",
        "observable_outcome": "x", "check_keywords": ["claude-3-5-haiku", "Claude 3.5 Haiku", "Amazon Bedrock"],
        "evidence_url": "https://docs.claude.com/models",
    }
    d.update(kw)
    from agents.promise_schemas import LedgerPromise
    return LedgerPromise(**d)


def test_verifier_fulfilled_on_time(monkeypatch):
    page = "Model claude-3-5-haiku (Claude 3.5 Haiku) is available on Amazon Bedrock. Released October 28, 2024."
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence(page))
    r = verifier.verify_promise(_promise(), check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.FULFILLED


def test_verifier_fulfilled_late(monkeypatch):
    page = "claude-3-5-haiku (Claude 3.5 Haiku) on Amazon Bedrock. Shipped November 15, 2024."
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence(page))
    r = verifier.verify_promise(_promise(), check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.FULFILLED_LATE


def test_verifier_delayed_when_absent_and_past_deadline(monkeypatch):
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("Totally unrelated release notes page."))
    r = verifier.verify_promise(_promise(deadline_date="2026-06-30"), check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.DELAYED


def test_verifier_abandoned_when_absent_long_past_deadline(monkeypatch):
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("Unrelated page."))
    r = verifier.verify_promise(_promise(deadline_date="2024-10-31"), check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.ABANDONED


def test_verifier_pending_before_deadline(monkeypatch):
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("Nothing here yet."))
    r = verifier.verify_promise(_promise(deadline_date="2027-01-01"), check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.PENDING


def test_verifier_unverifiable_on_spa_shell(monkeypatch):
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("nav only", shell=True))
    r = verifier.verify_promise(_promise(), check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.UNVERIFIABLE


def test_verifier_unverifiable_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("", ok=False))
    r = verifier.verify_promise(_promise(), check_date=dt.date(2026, 8, 27))
    assert r.status == PromiseStatus.UNVERIFIABLE


# ---------------------- store + scorecard ------------------------------ #
def test_store_admit_verify_and_scorecard(monkeypatch):
    be = InMemoryBackend()
    pid = promises.admit_promise(
        company="Anthropic", promise_text="Haiku ships", source_quote="q",
        source_url="https://a.co", announced_date=ANNOUNCED,
        deadline_raw="later this month", deadline_date="2024-10-31",
        observable_outcome="haiku available in api",
        check_keywords=["claude-3-5-haiku", "Claude 3.5 Haiku", "Amazon Bedrock"],
        evidence_url="https://docs.claude.com/models", backend=be,
    )
    assert promises.get_promise(pid, backend=be)["status"] == "PENDING"

    page = "claude-3-5-haiku (Claude 3.5 Haiku) available on Amazon Bedrock since October 28, 2024."
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence(page))
    result = verifier.verify_promise(
        verifier.LedgerPromise(**promises.get_promise(pid, backend=be)), check_date=dt.date(2026, 8, 27)
    )
    promises.apply_verification(pid, result, backend=be)

    card = promises.get_scorecard(backend=be)
    assert card["overall"]["resolved"] == 1
    assert card["overall"]["kept_on_time"] == 1
    assert card["overall"]["on_time_rate_pct"] == 100.0
    assert card["companies"][0]["company"] == "Anthropic"


def test_due_for_check_respects_deadline():
    be = InMemoryBackend()
    promises.admit_promise(
        company="X", promise_text="p", source_quote="q", source_url="u",
        announced_date="2024-01-01", deadline_raw="Q1 2024", deadline_date="2024-03-31",
        observable_outcome="a b c", check_keywords=["foo bar", "baz qux"],
        evidence_url="u", backend=be,
    )
    promises.admit_promise(
        company="Y", promise_text="p", source_quote="q", source_url="u",
        announced_date="2024-01-01", deadline_raw="2099", deadline_date="2099-12-31",
        observable_outcome="a b c", check_keywords=["foo bar", "baz qux"],
        evidence_url="u", backend=be,
    )
    due = promises.due_for_check(check_date=dt.date(2026, 8, 27), backend=be)
    assert [d["company"] for d in due] == ["X"]
