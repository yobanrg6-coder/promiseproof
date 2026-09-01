"""
Point-in-time evidence via the Wayback Machine - NO LLM.

The verifier's hard problem: a promise asks "did this ship BY date D?", but an
official page only ever shows its state *today*. A changelog is a rolling
window; a pricing page shows this week's prices. So "was it true by D" often
cannot be answered from the live page at all.

This module answers it with the Internet Archive: fetch the official page *as
it was captured near D*. The capture timestamp itself is then the dated
evidence - "the official page said X on 2024-06-30" - with no prose-date
parsing and no third party to trust beyond a neutral public archive.

Uses only the availability API (`archive.org/wayback/available`), which is
fast and reliable; it returns the single closest capture to a timestamp.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import httpx

_AVAILABILITY = "https://archive.org/wayback/available"
_UA = "Mozilla/5.0 (compatible; PromiseProofBot/1.0; +https://github.com/yobanrg6-coder/promiseproof)"


@dataclass
class ArchiveSnapshot:
    original_url: str
    archive_url: str
    captured: dt.date
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.archive_url) and not self.error


def _parse_ts(ts: str) -> dt.date | None:
    # Wayback timestamps are YYYYMMDDhhmmss.
    try:
        return dt.date(int(ts[0:4]), int(ts[4:6]), int(ts[6:8]))
    except (ValueError, IndexError):
        return None


def snapshot_near(url: str, target: dt.date, timeout: float = 12.0) -> ArchiveSnapshot | None:
    """The archived capture of `url` closest to `target` (either direction).
    Returns None if the archive has nothing for this URL, or on a fetch error.
    The caller decides whether `captured` is close enough to trust.
    """
    if not url:
        return None
    query_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
    try:
        r = httpx.get(
            _AVAILABILITY,
            params={"url": query_url, "timestamp": target.strftime("%Y%m%d")},
            headers={"User-Agent": _UA},
            timeout=timeout,
            follow_redirects=True,
        )
        r.raise_for_status()
        closest = r.json().get("archived_snapshots", {}).get("closest")
    except Exception as e:  # noqa: BLE001 - any failure is just "no snapshot"
        return ArchiveSnapshot(url, "", dt.date.min, error=f"{type(e).__name__}: {e}")

    if not closest or not closest.get("available") or str(closest.get("status")) != "200":
        return None
    captured = _parse_ts(closest.get("timestamp", ""))
    if captured is None:
        return None
    return ArchiveSnapshot(original_url=url, archive_url=closest["url"], captured=captured)
