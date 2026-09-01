"""
FastMCP server - PromiseProof.

The ledger's machine interface: any client (an ADK agent, the web UI, a CI
job) reads and writes the same verified ledger through these tools. Every
tool here is deterministic and LLM-free - promise EXTRACTION (the one
NVIDIA-Nemotron step) lives in the web app's streaming pipeline, not on this
port.
"""

import datetime as dt
import os
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP

# Windows consoles / subprocess pipes default to cp1252 and crash on any
# non-latin-1 output before the server binds a port; force UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from agents.falsifiability_gate import run_gate
from agents.promise_schemas import PromiseExtraction
from ledger import promises as ledger
from ledger.evidence import looks_like_safe_url
from ledger.run_cycle import run_cycle

load_dotenv()

mcp = FastMCP("PromiseProof")


@mcp.tool()
def get_scorecard() -> dict:
    """The accountability scorecard: per-company and overall counts of kept /
    kept-undated / late / delayed / abandoned / pending / unverifiable
    promises, plus an on-time rate = kept-on-time divided by the resolved
    promises whose ship date could be established (undated fulfillments are
    excluded from both sides). Computed from the ledger, never estimated."""
    return ledger.get_scorecard()


@mcp.tool()
def list_promises() -> list:
    """Every promise in the ledger with its current status, source quote,
    source URL, deadline and the evidence URL the verifier checks."""
    return ledger.list_promises()


@mcp.tool()
def get_promise(promise_id: str) -> dict:
    """One promise by id, including its verification fields (status_reason,
    evidence_excerpt, last_checked_at, resolved_at)."""
    row = ledger.get_promise(promise_id)
    return row or {"error": f"no promise {promise_id!r}"}


@mcp.tool()
def admit_promise(
    company: str,
    promise_text: str,
    source_quote: str,
    source_url: str,
    announced_date: str,
    deadline_date: str,
    observable_outcome: str,
    check_keywords: list[str],
    evidence_url: str = "",
    deadline_raw: str = "",
) -> dict:
    """Add a promise to the ledger. Dates are YYYY-MM-DD. The promise must pass
    the same deterministic falsifiability gate the web pipeline uses (real
    calendar deadline, not absurd, >=2 specific check keywords, a substantive
    observable outcome); if it doesn't, nothing is written and the gate's
    reason is returned. On success the ledger stores it as PENDING until a
    verification cycle resolves it."""
    # The web pipeline validates source_url via Pydantic; do the same here so
    # an MCP client can't persist a javascript:/file: scheme or an
    # href-breakout string into a ledger row that later renders as a link.
    for _field, _value in (("source_url", source_url), ("evidence_url", evidence_url)):
        if not looks_like_safe_url(_value):
            return {"error": f"{_field} must be an http(s) URL with no quote/space/angle characters"}

    extraction = PromiseExtraction(
        is_falsifiable=True,
        company=company,
        promise_text=promise_text,
        source_quote=source_quote,
        observable_outcome=observable_outcome,
        check_keywords=check_keywords,
        deadline_raw=deadline_raw or deadline_date,
        deadline_date_iso=deadline_date,
    )
    gate = run_gate(extraction, announced_date)
    if not gate.accepted:
        return {"error": "rejected by the falsifiability gate", "gate_reason": gate.reason}

    try:
        pid = ledger.admit_promise(
            company=company,
            promise_text=promise_text,
            source_quote=source_quote,
            source_url=source_url,
            announced_date=announced_date,
            deadline_raw=deadline_raw or deadline_date,
            deadline_date=deadline_date,
            observable_outcome=observable_outcome,
            check_keywords=check_keywords,
            evidence_url=evidence_url,
            extractor_model="(mcp admit_promise)",
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"promise_id": pid, "status": "PENDING"}


@mcp.tool()
def run_verification_cycle() -> dict:
    """Re-check every promise whose deadline has passed against its live
    evidence page (zero LLM) and persist any status change. Returns how many
    were checked, which changed, and the fresh scorecard."""
    result = run_cycle(check_date=dt.datetime.now(dt.timezone.utc).date())
    return {"checked": result["checked"], "changed": result["changed"],
            "errors": result["errors"], "scorecard": result["scorecard"]}


if __name__ == "__main__":
    host = os.getenv("MCP_SERVER_HOST", "127.0.0.1")
    # 8081, not 8080: 8080 is the conventional PORT value the web app takes.
    port = int(os.getenv("MCP_SERVER_PORT", "8081"))
    print(f"Starting PromiseProof FastMCP server on http://{host}:{port}/mcp ...")
    mcp.run(transport="streamable-http", host=host, port=port)
