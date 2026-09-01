"""
PromiseAuditorAgent - adversarial critic on an extracted promise, before it
reaches the deterministic gate. Adversarial by default: assume the extraction
is too loose until it proves otherwise. If it rejects, it must hand back ONE
exact re-extraction instruction so the self-correction loop produces a
genuinely different, crisper promise (not a rephrase).

Runs on a different-sized NVIDIA Nemotron model than the extractor (Nano vs.
Super), both served through Nebius Token Factory - an independent second
read, on a genuinely different model, on "is this actually falsifiable",
which is the ledger's whole integrity claim.
"""

import os

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from agents.promise_schemas import PromiseAudit

DEFAULT_AUDITOR_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"

SYSTEM_INSTRUCTION = """You audit a proposed ledger entry - an extracted "falsifiable promise" - and decide,
adversarially, whether it is crisp enough to be checked TRUE or FALSE later with no AI. Assume it is too
loose until proven otherwise; a lenient audit makes the whole ledger untrustworthy.

Reject (agrees_falsifiable=false) if ANY of these are true:
  - observable_outcome is vague, subjective, or not visible on a public page ("better performance", "improved UX")
  - the deadline is soft or missing, or deadline_date_iso does not correspond to deadline_raw
  - check_keywords are generic single words that would match unrelated pages ("API", "AI", "beta", "launch")
  - promise_text adds spin or claims more than source_quote actually says
  - source_quote does not actually contain a commitment (it's a description, an intention, or marketing)

When you reject, tighter_instruction must be a single concrete order the extractor can act on, e.g.
"Use the exact API model identifier as a check keyword, not the marketing name" or
"The source quote is an intention, not a dated commitment - reject this statement as non-falsifiable."

When you accept, issues may still list minor concerns, but agrees_falsifiable=true.
Output strictly conforms to the schema.

detailed thinking off
Respond with ONLY the JSON object. Do not emit any reasoning, preamble, <think> block, or code fence."""


def create_promise_auditor_agent(model_name: str | None = None, api_key: str | None = None) -> LlmAgent:
    # Accept a bare NVIDIA model id or one already carrying LiteLLM's "nebius/"
    # provider prefix - normalize so we never double-prefix.
    model = (model_name or os.getenv("AUDITOR_MODEL", DEFAULT_AUDITOR_MODEL)).removeprefix("nebius/")
    # drop_params: let LiteLLM drop request fields Nebius rejects for this
    # model rather than erroring (see promise_extractor.py for the rationale).
    lite_llm_kwargs: dict = {"drop_params": True}
    if api_key:
        lite_llm_kwargs["api_key"] = api_key
    if api_base := os.getenv("NEBIUS_API_BASE"):
        lite_llm_kwargs["api_base"] = api_base
    return LlmAgent(
        name="promise_auditor_agent",
        description="Adversarially audits whether an extracted promise is truly falsifiable and well-formed.",
        model=LiteLlm(model=f"nebius/{model}", **lite_llm_kwargs),
        instruction=SYSTEM_INSTRUCTION,
        output_schema=PromiseAudit,
    )
