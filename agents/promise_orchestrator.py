"""
PromiseLedgerOrchestrator - the autonomous pipeline that turns a raw company
announcement into a ledger entry:

    announcement text
      -> PromiseExtractorAgent (NVIDIA Nemotron Super, via Nebius, structured) [1]
      -> PromiseAuditorAgent (NVIDIA Nemotron Nano, via Nebius, adversarial)  [2]  --reject--> re-extract (loop, max 2)
      -> falsifiability gate (pure Python, no LLM)          [3]
      -> admit_promise() into Firestore                     [4]

Verification of admitted promises is a separate, LLM-free path
(ledger/verifier.py, run by ledger/run_cycle.py on a schedule).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import uuid
from collections.abc import AsyncGenerator
from typing import Any, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

# Keep the project root importable when the orchestrator is loaded from a
# context that hasn't already put it on sys.path.
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.falsifiability_gate import run_gate
from agents.promise_auditor import create_promise_auditor_agent
from agents.promise_extractor import DEFAULT_MODEL, create_promise_extractor_agent
from agents.promise_schemas import PromiseAudit, PromiseExtraction
from ledger import promises as ledger

load_dotenv()
logger = logging.getLogger("promiseproof.orchestrator")

T = TypeVar("T", bound=BaseModel)

APP_NAME = "promiseproof"
MAX_AGENT_RETRIES = 3
MAX_REEXTRACTION_LOOPS = 2
AUDITOR_TIMEOUT_SECONDS = 35.0


class AgentExecutionError(RuntimeError):
    pass


_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think\s*>", re.IGNORECASE)
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _strip_model_scaffolding(text: str) -> str:
    """Best-effort removal of reasoning-model scaffolding around a JSON payload.

    Handles, in order: complete ``<think>...</think>`` blocks (closing tag may
    carry whitespace: ``</think >``); a leftover unclosed ``<think>`` (or
    trailing ``</think>``) from a truncated trace; a ```json ... ``` fence;
    finally, if what's left still isn't bare JSON, the slice from the first
    ``{`` / ``[`` to its matching last ``}`` / ``]``.
    """
    text = _THINK_BLOCK.sub("", text).strip()
    if _THINK_CLOSE.search(text):  # unclosed opener consumed the block above
        text = _THINK_CLOSE.split(text)[-1].strip()
    text = _FENCE.sub("", text.strip()).strip()
    if text[:1] not in ("{", "["):
        start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start != -1 and end > start:
            text = text[start : end + 1]
    return text


class PromiseLedgerOrchestrator:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("NEBIUS_API_KEY")
        self.model_name = model or os.getenv("MODEL", DEFAULT_MODEL)
        if not self.api_key:
            raise AgentExecutionError("NEBIUS_API_KEY is not set")

    # --------------------------- ADK runner ------------------------------- #
    async def _run_agent(self, agent, prompt: str, output_model: type[T], label: str) -> T:
        last_error: Exception | None = None
        for attempt in range(1, MAX_AGENT_RETRIES + 1):
            try:
                return await self._run_agent_once(agent, prompt, output_model, label)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("%s attempt %d/%d failed: %s", label, attempt, MAX_AGENT_RETRIES, exc)
                if attempt < MAX_AGENT_RETRIES:
                    await asyncio.sleep(1.0 * attempt)
        raise AgentExecutionError(f"{label} failed after {MAX_AGENT_RETRIES} attempts: {last_error}") from last_error

    async def _run_agent_once(self, agent, prompt: str, output_model: type[T], label: str) -> T:
        runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
        user_id = "promiseproof-user"
        session_id = f"{label}-{uuid.uuid4().hex[:10]}"
        await runner.session_service.create_session(
            app_name=runner.app_name, user_id=user_id, session_id=session_id
        )
        content = types.Content(role="user", parts=[types.Part(text=prompt)])
        final_event = None
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
            if event.is_final_response():
                final_event = event
        if final_event is None:
            raise AgentExecutionError(f"{label}: no final response")
        if getattr(final_event, "output", None) is not None:
            try:
                return output_model.model_validate(final_event.output)
            except ValidationError:
                pass
        # Join every non-"thought" text part (a reasoning model can emit its
        # trace as a separate part; ADK tags those thought=True). Taking only
        # parts[-1] would miss a split answer or grab a trailing reasoning part.
        text = ""
        if final_event.content and final_event.content.parts:
            text = "".join(
                p.text for p in final_event.content.parts
                if p.text and not getattr(p, "thought", False)
            )
        if not text.strip():
            raise AgentExecutionError(f"{label}: no parsable output")
        text = _strip_model_scaffolding(text)
        try:
            return output_model.model_validate_json(text)
        except ValidationError as exc:
            raise AgentExecutionError(f"{label}: bad {output_model.__name__}: {exc}") from exc

    # --------------------------- pipeline ------------------------------- #
    async def _audit_or_skip(self, extraction: PromiseExtraction, auditor) -> PromiseAudit | None:
        prompt = f"Audit this extracted promise:\n{extraction.model_dump_json(indent=2)}"
        try:
            return await asyncio.wait_for(
                self._run_agent(auditor, prompt, PromiseAudit, "PromiseAuditorAgent"),
                timeout=AUDITOR_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, AgentExecutionError) as exc:
            # asyncio.TimeoutError stringifies to "" on 3.11+, so name the type.
            detail = str(exc) or type(exc).__name__
            logger.warning("Auditor unavailable, continuing on extractor + gate alone: %s", detail)
            return None

    async def process_announcement_stream(
        self,
        *,
        announcement_text: str,
        source_url: str,
        announced_date: str,
        backend: Any = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        # Both agents are built once for the whole re-extraction loop, not per
        # iteration - construction is cheap but pointless to repeat.
        extractor = create_promise_extractor_agent(api_key=self.api_key, model_name=self.model_name)
        auditor = create_promise_auditor_agent(api_key=self.api_key)
        base_prompt = (
            f"--- SOURCE URL ---\n{source_url}\n"
            f"--- PUBLISHED ---\n{announced_date}\n"
            f"--- ANNOUNCEMENT TEXT ---\n{announcement_text[:14000]}\n"
        )

        extraction: PromiseExtraction | None = None
        audit: PromiseAudit | None = None
        for loop in range(1, MAX_REEXTRACTION_LOOPS + 2):
            yield {"type": "status", "stage": 1, "agent": "PromiseExtractorAgent",
                   "message": f"Extracting a falsifiable promise (pass {loop})..."}
            prompt = base_prompt
            if audit and not audit.agrees_falsifiable and audit.tighter_instruction:
                prompt += f"\n--- REVISION REQUIRED ---\n{audit.tighter_instruction}\n"
            extraction = await self._run_agent(extractor, prompt, PromiseExtraction, "PromiseExtractorAgent")
            yield {"type": "agent_result", "stage": 1, "agent": "PromiseExtractorAgent",
                   "data": extraction.model_dump()}

            if not extraction.is_falsifiable:
                yield {"type": "decision_stop", "stage": 1,
                       "message": f"Not a falsifiable promise: {extraction.rejection_reason}"}
                return

            yield {"type": "status", "stage": 2, "agent": "PromiseAuditorAgent",
                   "message": "Adversarially auditing the extraction on a second, smaller Nemotron model..."}
            audit = await self._audit_or_skip(extraction, auditor)
            if audit is None:
                yield {"type": "status", "stage": 2, "agent": "PromiseAuditorAgent",
                       "message": "Auditor unavailable this run - proceeding on extractor + gate alone."}
                break
            yield {"type": "agent_result", "stage": 2, "agent": "PromiseAuditorAgent", "data": audit.model_dump()}
            if audit.agrees_falsifiable:
                break
            if loop > MAX_REEXTRACTION_LOOPS:
                yield {"type": "decision_stop", "stage": 2,
                       "message": f"Auditor still rejects after {MAX_REEXTRACTION_LOOPS} re-extractions: {audit.issues}"}
                return
            yield {"type": "status", "stage": 2, "agent": "PromiseAuditorAgent",
                   "message": f"Rejected: {audit.tighter_instruction} - re-extracting..."}

        yield {"type": "status", "stage": 3, "agent": "falsifiability_gate",
               "message": "Deterministic falsifiability gate (no LLM)..."}
        gate = run_gate(extraction, announced_date)
        yield {"type": "agent_result", "stage": 3, "agent": "falsifiability_gate", "data": gate.model_dump()}
        if not gate.accepted:
            yield {"type": "decision_stop", "stage": 3, "message": f"Gate rejected: {gate.reason}"}
            return

        promise_id = ledger.admit_promise(
            company=extraction.company,
            promise_text=extraction.promise_text,
            source_quote=extraction.source_quote,
            source_url=source_url,
            announced_date=announced_date,
            deadline_raw=extraction.deadline_raw,
            deadline_date=extraction.deadline_date_iso,
            observable_outcome=extraction.observable_outcome,
            check_keywords=extraction.check_keywords,
            evidence_url=extraction.evidence_url_hint,
            extractor_model=self.model_name,
            auditor_agreed=(audit.agrees_falsifiable if audit else None),
            backend=backend,
        )
        yield {"type": "complete", "stage": 4, "promise_id": promise_id,
               "message": f"Admitted to the ledger as {promise_id}",
               "data": ledger.get_promise(promise_id, backend=backend)}
