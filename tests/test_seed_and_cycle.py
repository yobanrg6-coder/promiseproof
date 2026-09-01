"""
Seed data + JsonFileBackend + run_cycle. No network, no LLM (evidence fetch
is monkeypatched).
"""

import datetime as dt

from agents.falsifiability_gate import run_gate
from agents.promise_schemas import PromiseStatus
from ledger import evidence as evidence_mod
from ledger import promises, verifier
from ledger.promises import JsonFileBackend
from ledger.run_cycle import reverify_all, run_cycle
from ledger.seed import _extraction_from_seed, seed
from ledger.seed_data import SEED_PROMISES


# --------------------------- seed data shape --------------------------- #
def test_every_seed_promise_passes_the_falsifiability_gate():
    assert SEED_PROMISES, "seed list is empty"
    for entry in SEED_PROMISES:
        ext = _extraction_from_seed(entry)
        result = run_gate(ext, entry["announced_date"])
        assert result.accepted, f"{entry['company']}: {result.reason}"


def test_seed_promise_dates_are_sane():
    for entry in SEED_PROMISES:
        announced = dt.date.fromisoformat(entry["announced_date"])
        deadline = dt.date.fromisoformat(entry["deadline_date_iso"])
        assert announced <= deadline
        assert entry["evidence_url"].startswith("http")
        assert len(entry["check_keywords"]) >= 2


# --------------------------- JsonFileBackend --------------------------- #
def test_jsonfilebackend_round_trip(tmp_path):
    be = JsonFileBackend(tmp_path / "ledger.json")
    pid = promises.admit_promise(
        company="Acme", promise_text="p", source_quote="q", source_url="u",
        announced_date="2024-01-01", deadline_raw="Q1", deadline_date="2024-03-31",
        observable_outcome="a b c", check_keywords=["foo bar", "baz qux"],
        evidence_url="https://e.co", backend=be,
    )
    assert promises.get_promise(pid, backend=be)["status"] == "PENDING"

    # a fresh handle on the same file sees the persisted row
    be2 = JsonFileBackend(tmp_path / "ledger.json")
    assert be2.get(pid)["company"] == "Acme"
    assert len(be2.all()) == 1


# --------------------------- run_cycle -------------------------------- #
def _fake_evidence(text):
    def _fetch(url, timeout=25.0):
        return evidence_mod.Evidence(url=url, ok=True, text=text, looks_like_spa_shell=False)
    return _fetch


def test_run_cycle_resolves_due_promise(monkeypatch, tmp_path):
    be = JsonFileBackend(tmp_path / "ledger.json")
    pid = promises.admit_promise(
        company="Acme", promise_text="ship X", source_quote="q", source_url="u",
        announced_date="2024-01-01", deadline_raw="Q2 2024", deadline_date="2024-06-30",
        observable_outcome="Feature X on the dashboard", check_keywords=["Feature X", "Acme Dashboard"],
        evidence_url="https://e.co/docs", backend=be,
    )
    monkeypatch.setattr(verifier, "fetch_evidence",
                        _fake_evidence("Feature X is live on the Acme Dashboard. Shipped 2024-05-01."))

    summary = run_cycle(check_date=dt.date(2026, 8, 28), backend=be)
    assert summary["checked"] == 1
    assert summary["errors"] == 0
    assert promises.get_promise(pid, backend=be)["status"] == PromiseStatus.FULFILLED.value

    # nothing due on the second pass (already resolved)
    assert run_cycle(check_date=dt.date(2026, 8, 28), backend=be)["checked"] == 0


def test_seed_runs_end_to_end_with_fake_evidence(monkeypatch, tmp_path):
    be = JsonFileBackend(tmp_path / "ledger.json")
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("nothing relevant on this page"))
    out = seed(fresh=True, verify=True, backend=be)
    assert out["admitted"] == len(SEED_PROMISES)
    card = out["scorecard"]["overall"]
    assert card["total"] == len(SEED_PROMISES)


def test_reverify_all_rechecks_every_promise_even_when_none_are_due(monkeypatch, tmp_path):
    """reverify_all re-runs the zero-LLM verifier over the WHOLE ledger; run_cycle
    only touches promises still in a trackable state. After seeding with an empty
    page every promise resolves ABANDONED, so run_cycle has nothing to do but
    reverify_all still re-checks all of them."""
    be = JsonFileBackend(tmp_path / "ledger.json")
    monkeypatch.setattr(verifier, "fetch_evidence", _fake_evidence("nothing relevant on this page"))
    seed(fresh=True, verify=True, backend=be)
    check = dt.date(2026, 8, 28)

    assert run_cycle(check_date=check, backend=be)["checked"] == 0
    assert reverify_all(check_date=check, backend=be)["checked"] == len(SEED_PROMISES)
