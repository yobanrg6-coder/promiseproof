"""
Adversarial tests for the FastAPI request models.
No network, no LLM calls.

The web app is the one unauthenticated path that persists caller-supplied
strings onto a promise (which are later rendered as links), so its input
validation is a security boundary.
"""

import pytest
from pydantic import ValidationError

from web_app.app import ExtractRequest


def test_extract_request_accepts_a_plain_https_source_url():
    req = ExtractRequest(
        announcement_text="Acme will ship Feature X by Q4 2024.",
        source_url="https://acme.com/news/feature-x",
        announced_date="2024-01-15",
    )
    assert req.source_url == "https://acme.com/news/feature-x"


def test_extract_request_allows_an_empty_source_url():
    req = ExtractRequest(
        announcement_text="Acme will ship Feature X by Q4 2024.",
        source_url="",
        announced_date="2024-01-15",
    )
    assert req.source_url == ""


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(document.domain)",
        'https://acme.com" onmouseover="alert(1)',
        "data:text/html,<script>alert(1)</script>",
        "ftp://acme.com/x",
        "  javascript:alert(1)  ",
    ],
)
def test_extract_request_rejects_non_http_source_urls(bad_url):
    """A pasted announcement must not be able to smuggle a javascript:/data:
    URI - or an attribute break-out - into a value that ends up in an href."""
    with pytest.raises(ValidationError):
        ExtractRequest(
            announcement_text="Acme will ship Feature X by Q4 2024.",
            source_url=bad_url,
            announced_date="2024-01-15",
        )


def test_extract_request_still_rejects_a_malformed_announced_date():
    with pytest.raises(ValidationError):
        ExtractRequest(
            announcement_text="Acme will ship Feature X by Q4 2024.",
            source_url="https://acme.com",
            announced_date="Q4 2024",
        )
