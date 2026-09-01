"""
Pydantic schemas for PromiseProof.

A "promise" is a public statement by a company that commits to a specific,
observable outcome by a stated or clearly implied deadline. The ledger only
ever accepts FALSIFIABLE promises - ones that can later be checked TRUE or
FALSE against a public source with no LLM in the loop.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PromiseStatus(str, Enum):
    # deadline not yet reached; nothing to conclude
    PENDING = "PENDING"
    # shipped, on or before the stated deadline
    FULFILLED = "FULFILLED"
    # shipped, but after the stated deadline
    FULFILLED_LATE = "FULFILLED_LATE"
    # part of the promise is observable, part is not
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    # deadline passed, positive evidence of non-delivery, still tracking
    DELAYED = "DELAYED"
    # deadline long passed, company stopped referencing it / superseded it
    ABANDONED = "ABANDONED"
    # deadline passed but the evidence check cannot decide either way
    UNVERIFIABLE = "UNVERIFIABLE"


# Statuses that count as a resolved, gradeable outcome for the scorecard.
RESOLVED_STATUSES = {
    PromiseStatus.FULFILLED,
    PromiseStatus.FULFILLED_LATE,
    PromiseStatus.PARTIALLY_FULFILLED,
    PromiseStatus.DELAYED,
    PromiseStatus.ABANDONED,
}
KEPT_ON_TIME_STATUSES = {PromiseStatus.FULFILLED}


class PromiseExtraction(BaseModel):
    """Output of the PromiseExtractorAgent for one candidate statement."""

    is_falsifiable: bool = Field(
        description="True ONLY if this is a specific, dated, publicly observable product promise"
    )
    company: str = Field(default="", description="Company or project making the promise")
    promise_text: str = Field(
        default="", description="One-line, neutral restatement of exactly what was promised"
    )
    source_quote: str = Field(
        default="", description="Verbatim sentence(s) from the announcement that state the promise"
    )
    observable_outcome: str = Field(
        default="",
        description="The concrete, checkable thing that must become true on a public page for this to be FULFILLED",
    )
    check_keywords: list[str] = Field(
        default_factory=list,
        description=(
            "2-6 short, machine-checkable tokens whose presence on the official docs/changelog/"
            "release-notes/pricing page confirms delivery - prefer exact identifiers "
            "(API model id, feature name, version string) over prose"
        ),
    )
    deadline_raw: str = Field(
        default="", description="Deadline exactly as stated ('Q2 2026', 'by end of 2025', 'in the coming weeks')"
    )
    deadline_date_iso: str = Field(
        default="",
        description="Deadline normalized to YYYY-MM-DD using the LAST day of the stated period",
    )
    evidence_url_hint: str = Field(
        default="",
        description="Best guess at the official page where delivery would be visible (docs / changelog / pricing)",
    )
    rejection_reason: str = Field(
        default="",
        description="If not falsifiable: why (vague / aspirational / no deadline / outcome not observable)",
    )


class PromiseAudit(BaseModel):
    """Adversarial second opinion on an extraction (a different model family)."""

    agrees_falsifiable: bool = Field(
        description="True only if the extraction is genuinely specific, dated and publicly checkable"
    )
    issues: list[str] = Field(
        default_factory=list, description="Concrete problems: vague outcome, wrong/soft deadline, weak keywords, spin"
    )
    tighter_instruction: str = Field(
        default="",
        description="If rejecting: one exact instruction telling the extractor how to re-extract a crisper promise",
    )


class GateResult(BaseModel):
    """Deterministic re-check of an extraction before it can enter the ledger."""

    accepted: bool
    reason: str


class VerificationResult(BaseModel):
    """Output of the zero-LLM verifier for one promise at resolution time."""

    status: PromiseStatus
    reason: str = Field(description="Plain-language explanation of how the status was decided")
    evidence_url: str = Field(default="", description="Page actually fetched and checked")
    evidence_excerpt: str = Field(default="", description="Snippet of the fetched page around the match, for the receipt")
    keyword_hits: list[str] = Field(default_factory=list)
    checked_at: str = Field(default="", description="UTC ISO timestamp of this check")
    ship_date_confirmed: bool | None = Field(
        default=None,
        description=(
            "For a FULFILLED / FULFILLED_LATE outcome: True if a ship date was actually established "
            "(from a point-in-time archive capture, or a date read off the page), False if delivery "
            "was proven but its timing could not be. None for every other status."
        ),
    )
    verification_method: str = Field(
        default="",
        description=(
            "How the verdict was reached: 'wayback@deadline' (official page as archived on/before the "
            "deadline), 'wayback@now' (recent archive capture), 'live-page' / 'live-page+date' (the "
            "current official page), or 'unverifiable'."
        ),
    )
    evidence_captured_at: str = Field(
        default="",
        description="YYYY-MM-DD the evidence was captured, when it came from a point-in-time archive.",
    )


class LedgerPromise(BaseModel):
    """A promise as persisted in the ledger."""

    id: str
    company: str
    promise_text: str
    source_quote: str
    source_url: str
    announced_date: str = Field(description="YYYY-MM-DD the promise was made")
    deadline_raw: str
    deadline_date: str = Field(description="YYYY-MM-DD, normalized")
    observable_outcome: str
    check_keywords: list[str]
    evidence_url: str = Field(default="", description="Official page the verifier checks against")
    status: PromiseStatus = PromiseStatus.PENDING
    status_reason: str = ""
    evidence_excerpt: str = ""
    created_at: str = ""
    resolved_at: str | None = None
    last_checked_at: str | None = None
    # True/False once a FULFILLED* verdict is reached (see VerificationResult); None while PENDING.
    ship_date_confirmed: bool | None = None
    verification_method: str = ""
    evidence_captured_at: str = ""
    # audit trail: independent second opinion on falsifiability (Nemotron Super vs. Nemotron Nano)
    extractor_model: str = ""
    auditor_agreed: bool | None = None
