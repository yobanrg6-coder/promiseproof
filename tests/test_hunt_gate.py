"""
Adversarial tests for agents.falsifiability_gate - hunting edge cases and bugs.
No network, no LLM calls.
"""

from agents.falsifiability_gate import run_gate, usable_keywords
from agents.promise_schemas import PromiseExtraction


def _ext(**kw):
    base = {
        "is_falsifiable": True,
        "company": "Acme Corp",
        "promise_text": "Acme launches Feature X",
        "source_quote": "We will launch Feature X by Q4 2024.",
        "observable_outcome": "Feature X is available in Acme dashboard",
        "check_keywords": ["Feature X", "Acme Dashboard"],
        "deadline_raw": "end of Q4 2024",
        "deadline_date_iso": "2024-12-31",
        "evidence_url_hint": "https://acme.com/docs",
        "rejection_reason": "",
    }
    base.update(kw)
    return PromiseExtraction(**base)


# =========================================================================== #
# 1. 5-year horizon calculation bug (leap year / 365 vs 366 days)
# =========================================================================== #
def test_gate_accepts_exact_five_year_deadline_across_leap_years():
    """
    An exactly-5-calendar-year deadline must be accepted even when the
    interval spans a leap day (regression guard for BUG-06).
    """
    announced = "2024-10-22"
    deadline_5y = "2029-10-22"  # exactly 5 calendar years (1826 days, spans Feb 29 2028)
    r = run_gate(_ext(deadline_date_iso=deadline_5y), announced)
    assert r.accepted

    # One day past the 5-year mark is still rejected.
    r_over = run_gate(_ext(deadline_date_iso="2029-10-23"), announced)
    assert not r_over.accepted
    assert "more than 5 years" in r_over.reason


# =========================================================================== #
# 2. Duplicate check_keywords bypass
# =========================================================================== #
def test_gate_rejects_duplicate_identical_keywords():
    """
    Duplicate keywords must not pad the >=2 distinct-keyword requirement
    (regression guard for BUG-07).
    """
    extraction = _ext(check_keywords=["Feature X", "Feature X"])
    r = run_gate(extraction, "2024-01-01")
    assert not r.accepted

    usable = usable_keywords(extraction.check_keywords)
    assert usable == ["Feature X"]

    # Case-insensitive: "feature x" is the same token as "Feature X".
    assert usable_keywords(["Feature X", "feature x", "  FEATURE X "]) == ["Feature X"]


# =========================================================================== #
# 3. Deadline ISO format robustness
# =========================================================================== #
def test_gate_rejects_whitespace_padded_deadline():
    """Whitespace padding ' 2024-12-31 ' should be rejected or stripped."""
    r = run_gate(_ext(deadline_date_iso=" 2024-12-31 "), "2024-01-01")
    assert not r.accepted


def test_gate_rejects_invalid_calendar_date_matching_regex():
    """'2026-13-40' matches regex \\d{4}-\\d{2}-\\d{2} but fails date parsing."""
    r = run_gate(_ext(deadline_date_iso="2026-13-40"), "2024-01-01")
    assert not r.accepted
    assert "unparseable deadline" in r.reason


def test_gate_rejects_slash_formatted_deadline():
    """'2024/12/31' fails regex."""
    r = run_gate(_ext(deadline_date_iso="2024/12/31"), "2024-01-01")
    assert not r.accepted


# =========================================================================== #
# 4. Announced date validation
# =========================================================================== #
def test_gate_rejects_malformed_announced_date():
    """Announced date not in YYYY-MM-DD should be rejected cleanly."""
    r = run_gate(_ext(), "October 22, 2024")
    assert not r.accepted
    assert "unparseable announced_date" in r.reason

    r2 = run_gate(_ext(), "")
    assert not r2.accepted
    assert "unparseable announced_date" in r2.reason


# =========================================================================== #
# 5. Observable outcome thinness
# =========================================================================== #
def test_gate_rejects_thin_observable_outcome():
    """Observable outcome with < 3 words is rejected."""
    r = run_gate(_ext(observable_outcome="it works"), "2024-01-01")
    assert not r.accepted
    assert "too thin" in r.reason


def test_gate_accepts_minimal_three_word_outcome():
    """Observable outcome with 3 words is accepted."""
    r = run_gate(_ext(observable_outcome="Feature is live"), "2024-01-01")
    assert r.accepted


# =========================================================================== #
# 6. Default / Empty extraction with is_falsifiable=True
# =========================================================================== #
def test_gate_handles_empty_extraction_gracefully():
    """An extraction with default fields and is_falsifiable=True does not crash."""
    empty_ext = PromiseExtraction(is_falsifiable=True)
    r = run_gate(empty_ext, "2024-01-01")
    assert not r.accepted


# =========================================================================== #
# 7. Usable keywords filtering
# =========================================================================== #
def test_usable_keywords_filters_short_and_generic_but_keeps_phrases():
    """Short (<3 chars) and single generic words are removed, multi-word phrases kept."""
    keywords = ["AI", "v2", "beta", "launch", "beta program", "cloud update", "Claude 3.5"]
    usable = usable_keywords(keywords)
    assert "AI" not in usable
    assert "v2" not in usable
    assert "beta" not in usable
    assert "launch" not in usable
    assert "beta program" in usable
    assert "cloud update" in usable
    assert "Claude 3.5" in usable
