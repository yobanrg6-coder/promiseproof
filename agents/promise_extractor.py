"""
PromiseExtractorAgent - turns one public company statement into a structured,
falsifiable promise (or an explicit rejection). Real ADK LlmAgent with a
strict Pydantic output schema; the deterministic falsifiability gate
(agents/falsifiability_gate.py) is what actually admits it to the ledger.

Model: an NVIDIA open-source model (Nemotron) served through Nebius Token
Factory, via ADK's LiteLLM integration - not a Google model. See
agents/promise_auditor.py for why the auditor deliberately runs a
different-sized Nemotron.
"""

import os

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from agents.promise_schemas import PromiseExtraction

DEFAULT_MODEL = "nvidia/Llama-3_3-Nemotron-Super-49B-v1"

SYSTEM_INSTRUCTION = """You extract FALSIFIABLE product promises from company announcements for a public
accountability ledger. The ledger only holds promises that can later be checked TRUE or FALSE against a
public page with no AI involved - so your bar is high and adversarial.

A statement qualifies as a falsifiable promise ONLY if ALL of these hold:
  1. It names a specific capability, product, feature, price, availability, limit, or downloadable artifact.
  2. It has a stated or clearly implied deadline: a date, a quarter, "by end of year", "next month",
     "in the coming weeks" (treat the last as ~6 weeks out).
  3. Its outcome is observable later from a public source: docs, changelog, release notes, pricing page,
     model card, a package/version, a downloadable file.

QUALIFIES (extract it):
  "The API will support a 1M-token context window in Q2 2026."
  "Open weights will be released by the end of 2025."
  "This feature will be generally available to all paid users next month."

DOES NOT QUALIFY (set is_falsifiable=false, give rejection_reason, invent NOTHING):
  "We're committed to making AI more accessible."      (aspirational, no outcome)
  "We believe agents are the future of work."          (opinion)
  "More is coming soon."                               (no observable outcome, no real deadline)

When it qualifies, fill every field:
  - source_quote: the verbatim sentence(s) stating the promise, copied exactly.
  - promise_text: one neutral line - what was promised, no spin.
  - observable_outcome: the concrete thing that must appear on a public page for this to be FULFILLED.
  - check_keywords: 2-6 short, machine-checkable tokens that would literally appear on that page once
    shipped. Strongly prefer exact identifiers: an API model id ("claude-3-5-haiku"), a feature name,
    a version string ("iOS 18.1"). Avoid single generic words ("API", "beta") - they match everything.
  - deadline_raw: exactly as stated. deadline_date_iso: normalize to the LAST day of that period (YYYY-MM-DD).
  - evidence_url_hint: your best guess at the official docs/changelog/pricing page where delivery shows up.

If a single announcement contains several promises, extract the ONE with the clearest, nearest,
most checkable deadline. Output strictly conforms to the schema.

detailed thinking off
Respond with ONLY the JSON object. Do not emit any reasoning, preamble, <think> block, or code fence.
"""


def create_promise_extractor_agent(model_name: str | None = None, api_key: str | None = None) -> LlmAgent:
    # Accept a bare NVIDIA model id ("nvidia/Llama-...") OR one that already
    # carries LiteLLM's "nebius/" provider prefix - normalize so we never
    # double-prefix into "nebius/nebius/...".
    model = (model_name or os.getenv("MODEL", DEFAULT_MODEL)).removeprefix("nebius/")
    # LiteLLM's "nebius/" provider prefix routes to Nebius Token Factory's
    # OpenAI-compatible endpoint; api_key/api_base are forwarded straight
    # through to litellm.completion(). NEBIUS_API_KEY in the environment is
    # picked up automatically if api_key is omitted. drop_params lets LiteLLM
    # silently drop any request field Nebius doesn't accept for this model
    # (e.g. an unsupported response_format flavor) instead of erroring - the
    # orchestrator still validates/repairs the JSON it gets back.
    lite_llm_kwargs: dict = {"drop_params": True}
    if api_key:
        lite_llm_kwargs["api_key"] = api_key
    if api_base := os.getenv("NEBIUS_API_BASE"):
        lite_llm_kwargs["api_base"] = api_base
    return LlmAgent(
        name="promise_extractor_agent",
        description="Extracts one falsifiable, dated, observable product promise from a company announcement.",
        model=LiteLlm(model=f"nebius/{model}", **lite_llm_kwargs),
        instruction=SYSTEM_INSTRUCTION,
        output_schema=PromiseExtraction,
    )
