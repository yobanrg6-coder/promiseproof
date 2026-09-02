"""
FastAPI backend - PromiseProof.

Two things only:
  - read endpoints over the verified ledger (scorecard + promise list), and
  - one SSE endpoint that streams the extract -> audit -> gate -> admit
    pipeline for a pasted announcement (the single NVIDIA-Nemotron-powered path).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict, deque
from datetime import date as _date

import aiofiles
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("promiseproof")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from agents.promise_extractor import DEFAULT_MODEL
from agents.promise_orchestrator import PromiseLedgerOrchestrator
from ledger import promises as ledger

load_dotenv()

app = FastAPI(title="PromiseProof", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# In-memory per-IP rate limit for the one endpoint that spends Nebius quota.
# The Cloud Run deploy is --allow-unauthenticated (judges need a public URL),
# and this endpoint falls back to the server's own NEBIUS_API_KEY when the
# caller sends none - without a limiter that lets anyone script free calls
# against this project's quota. One instance is the realistic demo target, so
# per-process memory is an acceptable bound.
# --------------------------------------------------------------------------- #
RATE_LIMIT_MAX_REQUESTS = 8
RATE_LIMIT_WINDOW_SECONDS = 60
_request_log: dict[str, deque] = defaultdict(deque)

# The re-verify endpoint spends no Nebius quota but fetches every evidence page
# (currently 8 external requests) per call, so it gets a tighter, separate bound.
VERIFY_LIMIT_MAX_REQUESTS = 3
VERIFY_LIMIT_WINDOW_SECONDS = 300
_verify_log: dict[str, deque] = defaultdict(deque)


def _resolve_client_ip(request: Request) -> str:
    # Behind Cloud Run's front end, request.client.host is Google's internal
    # proxy, identical for everyone. The real client IP is the LAST entry of
    # X-Forwarded-For (the front end appends it and the client cannot forge
    # that position); earlier entries are client-supplied and spoofable.
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit(log_store: dict[str, deque], client_ip: str, max_requests: int, window_s: int) -> None:
    now = time.monotonic()
    # Evict fully-aged-out IPs so the map can't grow without bound on a
    # long-lived instance.
    for ip in [ip for ip, dq in log_store.items() if dq and now - dq[-1] > window_s]:
        del log_store[ip]
    log = log_store[client_ip]
    while log and now - log[0] > window_s:
        log.popleft()
    if len(log) >= max_requests:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {max_requests} requests per {window_s}s.",
        )
    log.append(now)


static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Must match the slice the orchestrator applies to the prompt
# (promise_orchestrator.process_announcement_stream) so the API rejects
# anything that would be silently truncated instead of accepting it.
MAX_ANNOUNCEMENT_CHARS = 14000
# Hard ceiling on one live pipeline run. The auditor step has its own internal
# timeout; this bounds the whole extract -> audit -> re-extract loop so a
# stalled Nebius call can't leave the SSE stream hanging with no events.
PIPELINE_TIMEOUT_SECONDS = 90
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ExtractRequest(BaseModel):
    announcement_text: str
    source_url: str = ""
    announced_date: str
    api_key: str | None = None

    @field_validator("announced_date")
    @classmethod
    def _check_date(cls, v: str) -> str:
        v = v.strip()
        if not _ISO_DATE.match(v):
            raise ValueError("announced_date must be YYYY-MM-DD")
        try:
            _date.fromisoformat(v)  # rejects a well-formatted but impossible date (2024-02-30)
        except ValueError as exc:
            raise ValueError(f"announced_date is not a real calendar date: {v}") from exc
        return v

    @field_validator("source_url")
    @classmethod
    def _check_source_url(cls, v: str) -> str:
        # This value is persisted verbatim on the promise and later rendered as
        # a link. Only ever accept a clean http(s) URL (or nothing) so a pasted
        # announcement can't smuggle a javascript:/data: URI - or an HTML
        # attribute break-out (quotes, angle brackets, whitespace) - into the
        # ledger.
        v = (v or "").strip()
        if not v:
            return v
        if not re.match(r"^https?://", v, re.IGNORECASE):
            raise ValueError("source_url must be an http(s) URL")
        if re.search(r"""["'<>`\s]""", v):
            raise ValueError("source_url contains characters not allowed in a URL")
        return v


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        async with aiofiles.open(index_file, "r", encoding="utf-8") as f:
            return await f.read()
    return "<h1>PromiseProof</h1>"


@app.get("/api/health")
async def health_check():
    return {
        "status": "online",
        "service": "PromiseProof",
        "model": os.getenv("MODEL", DEFAULT_MODEL),
        "backend": os.getenv("LEDGER_BACKEND", "json"),
    }


@app.get("/api/scorecard")
async def api_scorecard():
    return ledger.get_scorecard()


@app.get("/api/chain")
async def api_chain():
    """Append-only hash-chain integrity over the admitted claims (zero LLM):
    {length, intact, broken, head}. `intact` false means a stored quote or
    deadline was edited after admission."""
    return ledger.verify_chain()


@app.get("/api/promises")
async def api_promises():
    rows = ledger.list_promises()
    rows.sort(key=lambda r: (r.get("company", ""), r.get("deadline_date", "")))
    return {"promises": rows, "count": len(rows)}


@app.post("/api/verify-cycle")
async def api_verify_cycle(request: Request):
    """Re-run the zero-LLM verifier over every promise against its live evidence
    page and return the fresh scorecard. No LLM, no API key - this is the same
    deterministic check the scheduled cycle runs."""
    _rate_limit(_verify_log, _resolve_client_ip(request),
                VERIFY_LIMIT_MAX_REQUESTS, VERIFY_LIMIT_WINDOW_SECONDS)
    from ledger.run_cycle import reverify_all

    try:
        summary = await asyncio.to_thread(reverify_all)
    except Exception:
        logger.exception("verify-cycle failed")
        raise HTTPException(status_code=500, detail="Re-verification failed. See server logs.") from None
    return {
        "checked": summary["checked"],
        "changed": summary["changed"],
        "errors": summary["errors"],
        "scorecard": summary["scorecard"],
    }


@app.post("/api/extract-stream")
async def extract_stream(req: ExtractRequest, request: Request):
    """SSE: stream the real pipeline stages for a pasted announcement."""
    _rate_limit(_request_log, _resolve_client_ip(request),
                RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)
    resolved_key = req.api_key or os.getenv("NEBIUS_API_KEY")

    async def event_generator():
        if not resolved_key:
            yield _sse({"type": "error", "message": "No Nebius API key: set NEBIUS_API_KEY in .env or paste one."})
            return
        text = req.announcement_text.strip()
        if not text:
            yield _sse({"type": "error", "message": "The announcement text is empty."})
            return
        if len(text) > MAX_ANNOUNCEMENT_CHARS:
            yield _sse({"type": "error", "message": f"Announcement too long ({len(text)} chars, max {MAX_ANNOUNCEMENT_CHARS})."})
            return
        try:
            orch = PromiseLedgerOrchestrator(api_key=resolved_key)
        except Exception:
            logger.exception("orchestrator init failed")
            yield _sse({"type": "error", "message": "Could not initialize the pipeline. Check the Nebius API key."})
            return
        agen = orch.process_announcement_stream(
            announcement_text=text,
            source_url=req.source_url,
            announced_date=req.announced_date,
        )
        pipeline_deadline = time.monotonic() + PIPELINE_TIMEOUT_SECONDS
        try:
            while True:
                remaining = pipeline_deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    event = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                yield _sse(event)
                await asyncio.sleep(0.03)
        except asyncio.TimeoutError:
            logger.warning("pipeline exceeded %ss for source_url=%r", PIPELINE_TIMEOUT_SECONDS, req.source_url)
            yield _sse({"type": "error",
                        "message": f"The pipeline ran past {PIPELINE_TIMEOUT_SECONDS}s and was stopped. "
                                   "Try a shorter, more concrete announcement."})
        except Exception:
            logger.exception("pipeline failed for source_url=%r", req.source_url)
            yield _sse({"type": "error", "message": "The pipeline failed during execution. See server logs."})
        finally:
            await agen.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT") or os.getenv("WEB_APP_PORT", "8000"))
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=True)
