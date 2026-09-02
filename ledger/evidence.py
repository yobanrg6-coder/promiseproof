"""
Evidence fetching for PromiseProof - pure HTTP + text normalization,
NO LLM. The verifier's job is only as trustworthy as the page it reads, so
this module deliberately:

  - fetches raw HTML and strips it to visible text (no JS execution)
  - flags when a fetch looks like an empty SPA shell (so the verifier can
    return UNVERIFIABLE instead of a false "not shipped")
  - is meant to be pointed at STATIC, DATED, machine-checkable sources
    (changelogs, release-notes, pricing pages, docs) - not JS marketing
    landing pages, which the probe (27-ago-2026) showed produce false
    negatives.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

_UA = "Mozilla/5.0 (compatible; PromiseProofBot/1.0; +https://github.com/yobanrg6-coder/promiseproof)"

# Hosts that must never be fetched even if DNS would resolve them publicly.
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata"}

# Characters that have no business in a URL and would let a stored value break
# out of an href attribute when the scorecard renders it as a link.
_URL_INJECTION_CHARS = re.compile(r"""["'<>`\s]""")


def looks_like_safe_url(url: str) -> bool:
    """Cheap syntactic check (no DNS) for a value we will STORE and later
    render as a link: an http(s) URL with no attribute-breakout characters.
    An empty string is allowed (the field is optional)."""
    if not url:
        return True
    return bool(re.match(r"^https?://", url, re.IGNORECASE)) and not _URL_INJECTION_CHARS.search(url)


def is_public_http_url(url: str) -> bool:
    """True only if `url` is an http(s) URL whose host resolves entirely to
    public IP addresses.

    This is an SSRF guard for the verifier's fetch path: `evidence_url` on a
    promise can originate from an LLM's `evidence_url_hint` (influenced by an
    attacker-supplied announcement) or from an MCP client, and it is later
    fetched server-side by the zero-LLM cycle. Without this, a crafted URL
    could make a Cloud Run instance probe link-local metadata endpoints or
    internal services. Fails closed: any parse/DNS error returns False.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        host = parts.hostname.lower()
        if host in _BLOCKED_HOSTNAMES:
            return False
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
        if not infos:
            return False
        for *_, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                    or ip.is_multicast or ip.is_unspecified):
                return False
        return True
    except Exception:  # noqa: BLE001 - any failure means "don't fetch it"
        return False
_TAG_RE = re.compile(r"(?s)<[^>]+>")
# Drop executable / non-visible blocks. The `(?:</\1>|\Z)` tail means an
# unclosed <script> (broken markup) still gets stripped to end-of-document
# instead of leaking its JS source into evidence.text as fake "content".
_DROP_RE = re.compile(r"(?is)<(script|style|noscript|template|svg)\b.*?(?:</\1>|\Z)")
# The Wayback Machine injects a navigation toolbar into every archived page,
# fenced by these comments. Its visible text ("377 captures  Nov DEC Jan  2023
# 2024 2025 ...") carries calendar dates that would poison the ship-date read,
# so strip the whole fenced block before anything else.
_WAYBACK_TOOLBAR_RE = re.compile(
    r"(?is)<!--\s*BEGIN WAYBACK TOOLBAR INSERT\s*-->.*?<!--\s*END WAYBACK TOOLBAR INSERT\s*-->"
)
_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
_WS_RE = re.compile(r"\s+")

# Below this many characters of extracted text, a 200 response is almost
# certainly a JS shell / nav chrome only - not real content to judge against.
_SHELL_TEXT_THRESHOLD = 600


@dataclass
class Evidence:
    url: str
    ok: bool
    text: str = ""
    looks_like_spa_shell: bool = False
    error: str = ""

    def excerpt_around(self, needle: str, radius: int = 180) -> str:
        i = self.text.lower().find(needle.lower())
        if i < 0:
            return self.text[:2 * radius].strip()
        return self.text[max(0, i - radius): i + radius].strip()


def html_to_text(raw: str) -> str:
    """Raw HTML -> visible text: drop executable/non-visible blocks, strip
    tags, decode HTML entities, collapse whitespace.

    Entities are decoded AFTER tags are gone, so a date written
    "November&nbsp;4,&nbsp;2024" or a keyword containing "&"/"'" is matched
    against real text, not entity noise. Whitespace collapse comes last so a
    decoded &nbsp; (U+00A0) folds into a normal space.
    """
    without_toolbar = _WAYBACK_TOOLBAR_RE.sub(" ", raw)
    stripped = _TAG_RE.sub(" ", _COMMENT_RE.sub(" ", _DROP_RE.sub(" ", without_toolbar)))
    return _WS_RE.sub(" ", html.unescape(stripped)).strip()


def fetch_evidence(url: str, timeout: float = 25.0) -> Evidence:
    if not url:
        return Evidence(url=url, ok=False, error="no evidence url")
    if not is_public_http_url(url):
        return Evidence(url=url, ok=False, error="refused: not a public http(s) URL")
    try:
        # Redirects are followed (http->https and canonical-host 301s are
        # ubiquitous), capped low. Every hop and the final URL are re-checked
        # against is_public_http_url: if a public page 3xx-redirects to a
        # private/metadata address the response is discarded, so an attacker
        # never sees an internal response body. (httpx has still issued that
        # one GET; a blind timing probe via a redirect the attacker also
        # controls is not fully prevented - the direct case, evidence_url
        # pointing straight at an internal address, is, by the check above.)
        # max_redirects is a client-level setting, not a param of httpx.get() -
        # passing it to the top-level helper raises TypeError and fails every
        # fetch, so build a Client explicitly.
        with httpx.Client(follow_redirects=True, timeout=timeout,
                          headers={"User-Agent": _UA}, max_redirects=3) as client:
            r = client.get(url)
    except Exception as e:  # noqa: BLE001 - any transport error is just "couldn't fetch"
        return Evidence(url=url, ok=False, error=f"{type(e).__name__}: {e}")

    for hop in (*r.history, r):
        if not is_public_http_url(str(hop.url)):
            return Evidence(url=str(hop.url), ok=False, error="refused: redirect to a non-public address")

    if r.status_code != 200:
        return Evidence(url=str(r.url), ok=False, error=f"HTTP {r.status_code}")

    text = html_to_text(r.text)
    return Evidence(
        url=str(r.url),
        ok=True,
        text=text,
        looks_like_spa_shell=len(text) < _SHELL_TEXT_THRESHOLD,
    )


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    """Keywords that appear in `text` as whole tokens.

    Uses non-word-char lookarounds instead of a raw substring test so short
    tokens ("GA", "Pro", "iOS", "v2") don't get false hits inside ordinary
    prose ("navigation", "improving", "studios", "revamp"). A keyword whose
    own edge is a non-word char (e.g. ".NET", "C++") falls back to a plain
    substring check, since a lookaround there would never anchor.
    """
    hits: list[str] = []
    for k in keywords:
        needle = k.strip()
        if not needle:
            continue
        left = r"(?<!\w)" if needle[0].isalnum() or needle[0] == "_" else ""
        # `(?!\w)` stops "GA" matching inside "navigation"; the extra `(?!\.\d)`
        # stops a version keyword matching its own point release - "iOS 18.1"
        # must not hit "iOS 18.1.1", "GPT-4" must not hit "GPT-4.5" - while a
        # trailing sentence period ("Feature X.") still counts as a boundary.
        right = r"(?!\w)(?!\.\d)" if needle[-1].isalnum() or needle[-1] == "_" else ""
        if re.search(left + re.escape(needle) + right, text, re.IGNORECASE):
            hits.append(k)
    return hits
