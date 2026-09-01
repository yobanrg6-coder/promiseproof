"""
Adversarial tests for agents.promise_orchestrator - hunting pipeline loops, timeouts, and edge cases.
Uses mocked agent runners (no Nebius/NVIDIA API calls).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agents.promise_orchestrator import (
    AgentExecutionError,
    PromiseLedgerOrchestrator,
    _strip_model_scaffolding,
)
from agents.promise_schemas import PromiseAudit, PromiseExtraction
from ledger.promises import InMemoryBackend


def _valid_extraction(is_falsifiable=True, reason=""):
    return PromiseExtraction(
        is_falsifiable=is_falsifiable,
        company="Acme Corp",
        promise_text="Acme launches Feature X",
        source_quote="We will launch Feature X by Q4 2024.",
        observable_outcome="Feature X is available in Acme dashboard",
        check_keywords=["Feature X", "Acme Dashboard"],
        deadline_raw="end of Q4 2024",
        deadline_date_iso="2024-12-31",
        evidence_url_hint="https://acme.com/docs",
        rejection_reason=reason,
    )


# =========================================================================== #
# 1. Auditor rejection loop exhaustion (decision_stop at stage 2)
# =========================================================================== #
@pytest.mark.asyncio
async def test_orchestrator_stops_when_auditor_rejects_max_times():
    """
    If auditor rejects 3 consecutive extractions, orchestrator halts with decision_stop.
    """
    orch = PromiseLedgerOrchestrator(api_key="fake-key")
    be = InMemoryBackend()

    audit_reject = PromiseAudit(
        agrees_falsifiable=False,
        issues=["Too vague"],
        tighter_instruction="Specify concrete API identifier",
    )

    with patch.object(orch, "_run_agent", new_callable=AsyncMock) as mock_run:
        # Extractor always returns valid extraction; Auditor always rejects
        async def fake_run_agent(agent, prompt, output_model, label):
            if output_model is PromiseExtraction:
                return _valid_extraction()
            elif output_model is PromiseAudit:
                return audit_reject
            raise ValueError("Unexpected model")

        mock_run.side_effect = fake_run_agent

        events = []
        async for ev in orch.process_announcement_stream(
            announcement_text="We promise X",
            source_url="https://example.com",
            announced_date="2024-01-01",
            backend=be,
        ):
            events.append(ev)

        stops = [ev for ev in events if ev["type"] == "decision_stop"]
        assert len(stops) == 1
        assert stops[0]["stage"] == 2
        assert "Auditor still rejects after 2 re-extractions" in stops[0]["message"]
        # No promise admitted
        assert len(be.all()) == 0


# =========================================================================== #
# 2. Auditor fails on pass 2 after rejecting pass 1 -> proceeds to gate
# =========================================================================== #
@pytest.mark.asyncio
async def test_orchestrator_proceeds_when_auditor_fails_on_second_pass():
    """
    Pass 1: Auditor rejects.
    Pass 2: Auditor times out / returns None.
    Orchestrator should proceed to gate with pass 2 extraction and admit if accepted.
    """
    orch = PromiseLedgerOrchestrator(api_key="fake-key")
    be = InMemoryBackend()

    audit_reject = PromiseAudit(
        agrees_falsifiable=False,
        issues=["Too vague"],
        tighter_instruction="Specify concrete API identifier",
    )

    audit_calls = 0

    with patch.object(orch, "_run_agent", new_callable=AsyncMock) as mock_run:
        async def fake_run_agent(agent, prompt, output_model, label):
            nonlocal audit_calls
            if output_model is PromiseExtraction:
                return _valid_extraction()
            elif output_model is PromiseAudit:
                audit_calls += 1
                if audit_calls == 1:
                    return audit_reject
                raise AgentExecutionError("Auditor timed out")
            raise ValueError("Unexpected model")

        mock_run.side_effect = fake_run_agent

        events = []
        async for ev in orch.process_announcement_stream(
            announcement_text="We promise X",
            source_url="https://example.com",
            announced_date="2024-01-01",
            backend=be,
        ):
            events.append(ev)

        completes = [ev for ev in events if ev["type"] == "complete"]
        assert len(completes) == 1
        assert len(be.all()) == 1
        # auditor_agreed is None because auditor was unavailable on final pass
        assert be.all()[0]["auditor_agreed"] is None


# =========================================================================== #
# 3. Extractor yields is_falsifiable=False on pass 2
# =========================================================================== #
@pytest.mark.asyncio
async def test_orchestrator_stops_when_extractor_revises_to_not_falsifiable():
    """
    If extractor realizes in pass 2 that the promise is not falsifiable,
    orchestrator halts at stage 1 without invoking the gate or store.
    """
    orch = PromiseLedgerOrchestrator(api_key="fake-key")
    be = InMemoryBackend()

    audit_reject = PromiseAudit(
        agrees_falsifiable=False,
        issues=["Not a hard deadline"],
        tighter_instruction="Reject if deadline is relative",
    )

    extractor_calls = 0

    with patch.object(orch, "_run_agent", new_callable=AsyncMock) as mock_run:
        async def fake_run_agent(agent, prompt, output_model, label):
            nonlocal extractor_calls
            if output_model is PromiseExtraction:
                extractor_calls += 1
                if extractor_calls == 1:
                    return _valid_extraction()
                return _valid_extraction(is_falsifiable=False, reason="Relative deadline")
            elif output_model is PromiseAudit:
                return audit_reject
            raise ValueError("Unexpected model")

        mock_run.side_effect = fake_run_agent

        events = []
        async for ev in orch.process_announcement_stream(
            announcement_text="We promise X",
            source_url="https://example.com",
            announced_date="2024-01-01",
            backend=be,
        ):
            events.append(ev)

        stops = [ev for ev in events if ev["type"] == "decision_stop"]
        assert len(stops) == 1
        assert stops[0]["stage"] == 1
        assert "Not a falsifiable promise: Relative deadline" in stops[0]["message"]
        assert len(be.all()) == 0


# =========================================================================== #
# 4. _audit_or_skip timeout handling
# =========================================================================== #
@pytest.mark.asyncio
async def test_audit_or_skip_catches_timeout_and_returns_none():
    """
    _audit_or_skip catches TimeoutError and returns None.
    """
    orch = PromiseLedgerOrchestrator(api_key="fake-key")
    
    with patch.object(orch, "_run_agent", new_callable=AsyncMock) as mock_run:
        async def sleep_forever(*args, **kwargs):
            await asyncio.sleep(100)
        mock_run.side_effect = sleep_forever

        with patch("agents.promise_orchestrator.AUDITOR_TIMEOUT_SECONDS", 0.05):
            res = await orch._audit_or_skip(_valid_extraction(), auditor=object())
            assert res is None


# =========================================================================== #
# 5. _strip_model_scaffolding - reasoning-model output cleanup
# =========================================================================== #
_PAYLOAD = '{"agrees_falsifiable": true, "issues": [], "tighter_instruction": ""}'


@pytest.mark.parametrize(
    "raw",
    [
        _PAYLOAD,
        f"```json\n{_PAYLOAD}\n```",
        f"<think>\nThe deadline is concrete and the keywords are specific, so this passes.\n</think>\n{_PAYLOAD}",
        f"<think>reasoning...</think>\n\n```json\n{_PAYLOAD}\n```",
        f"Here is the audit result:\n{_PAYLOAD}\nLet me know if you need more.",
        f"<THINK>upper-case tag</THINK>{_PAYLOAD}",
    ],
)
def test_strip_model_scaffolding_recovers_json(raw):
    cleaned = _strip_model_scaffolding(raw)
    parsed = PromiseAudit.model_validate_json(cleaned)
    assert parsed.agrees_falsifiable is True


def test_strip_model_scaffolding_handles_unclosed_think():
    # A truncated trace that never closed its <think> tag, then the JSON.
    raw = f"<think>I am still reasoning and never stopped</think> some words {_PAYLOAD}"
    cleaned = _strip_model_scaffolding(raw)
    assert PromiseAudit.model_validate_json(cleaned).agrees_falsifiable is True


def test_strip_model_scaffolding_handles_whitespace_in_closing_think_tag():
    # Some models emit "</think >" (with a space) - the close must still match.
    raw = f"<think>\nreasoning here\n</think >\n{_PAYLOAD}"
    assert PromiseAudit.model_validate_json(_strip_model_scaffolding(raw)).agrees_falsifiable is True
    raw2 = f"<think>reasoning</think\n>{_PAYLOAD}"
    assert PromiseAudit.model_validate_json(_strip_model_scaffolding(raw2)).agrees_falsifiable is True


def test_strip_model_scaffolding_leaves_plain_json_untouched():
    assert _strip_model_scaffolding(_PAYLOAD) == _PAYLOAD
