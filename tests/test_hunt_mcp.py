"""
Adversarial tests for the MCP tool surface.
No network, no LLM calls.

The MCP admit_promise tool must enforce the SAME falsifiability gate as the
web pipeline - the ledger's integrity claim ("only holds checkable promises")
can't have a back door.
"""

from ledger import promises
from mcp_server import server


def _admit(**over):
    args = {
        "company": "Acme",
        "promise_text": "Acme ships a 1M-token context window",
        "source_quote": "The API will support a 1M-token context window in Q2 2026.",
        "source_url": "https://acme.com/news",
        "announced_date": "2026-01-10",
        "deadline_date": "2026-06-30",
        "observable_outcome": "The Acme API docs list a 1,000,000 token context window",
        "check_keywords": ["1M-token context", "Acme API"],
    }
    args.update(over)
    return server.admit_promise(**args)


def test_mcp_admit_rejects_a_non_falsifiable_promise_without_writing(monkeypatch):
    """A vague, dateless statement is turned away by the gate and nothing is
    persisted."""
    calls = []
    monkeypatch.setattr(promises, "admit_promise", lambda **kw: calls.append(kw))

    out = _admit(
        promise_text="We are committed to greatness",
        source_quote="We believe agents are the future of work.",
        deadline_date="not-a-date",
    )
    assert "error" in out and "gate_reason" in out
    assert calls == []  # never reached the store


def test_mcp_admit_rejects_filler_only_keywords(monkeypatch):
    calls = []
    monkeypatch.setattr(promises, "admit_promise", lambda **kw: calls.append(kw))
    out = _admit(check_keywords=["API", "beta", "launch"])
    assert "error" in out
    assert calls == []


def test_mcp_admit_accepts_a_well_formed_promise():
    # conftest's autouse fixture already pins the process-default backend to a
    # throwaway in-memory one for this test.
    out = _admit()
    assert out.get("status") == "PENDING"
    assert "promise_id" in out
    rows = promises.list_promises()
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme"
    assert rows[0]["status"] == "PENDING"
