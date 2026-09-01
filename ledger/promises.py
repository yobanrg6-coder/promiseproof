"""
Store for PromiseProof.

Every promise is persisted with its verbatim source quote and source URL the
moment it's admitted, and its status is only ever changed by the zero-LLM
verifier (ledger/verifier.py). Pluggable backend, picked by the LEDGER_BACKEND
env var (see get_backend):

  - "json" (default): a single JSON file (data/ledger.json). The seeded demo
    ledger ships in the repo this way, so the app and the verification cycle
    have real data to show with no cloud credentials. Cloud Run's disk is
    ephemeral, so live writes there don't survive a cold start - the committed
    file is always the baseline.
  - "firestore": real Firestore, for a deployment that needs durable writes.
  - "memory": network-free in-process fake, used by the tests.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Protocol

from agents.falsifiability_gate import usable_keywords
from agents.promise_schemas import (
    RESOLVED_STATUSES,
    LedgerPromise,
    PromiseStatus,
)

COLLECTION_NAME = "promises"
# This is a fresh fork (PromiseProof, for the Nebius x NVIDIA hackathon) - it
# must NOT reuse The Promise Ledger's original GCP project ("topicahead-hackathon"),
# which stays running unmodified for its own already-submitted hackathon.
# Create a new GCP project and either set GCP_PROJECT in the environment or
# edit this placeholder before deploying.
GCP_PROJECT = os.getenv("GCP_PROJECT", "promiseproof-hackathon")
DEFAULT_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "ledger.json"


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


# Typographic variants an LLM freely swaps in between runs - fold them so the
# dedup key is stable regardless of which the model emitted this time.
_QUOTE_FOLD = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "―": "-", " ": " ",
})


def _norm_key_text(s: str) -> str:
    """Normalize a string for use in the dedup key: NFKC, fold smart
    quotes/dashes, collapse whitespace, casefold. Two extractions of the same
    announcement that differ only in quote style or spacing must collide."""
    s = unicodedata.normalize("NFKC", s or "").translate(_QUOTE_FOLD)
    return re.sub(r"\s+", " ", s).strip().casefold()


class PromiseBackend(Protocol):
    def insert(self, doc: dict[str, Any]) -> None: ...
    def get(self, promise_id: str) -> dict[str, Any] | None: ...
    def update(self, promise_id: str, fields: dict[str, Any]) -> None: ...
    def all(self) -> list[dict[str, Any]]: ...
    def by_status(self, status: str) -> list[dict[str, Any]]: ...


class FirestoreBackend:
    def __init__(self, project: str | None = None):
        from google.cloud import firestore

        self._client = firestore.Client(project=project or GCP_PROJECT)
        self._col = self._client.collection(COLLECTION_NAME)

    def insert(self, doc: dict[str, Any]) -> None:
        self._col.document(doc["id"]).set(doc)

    def get(self, promise_id: str) -> dict[str, Any] | None:
        snap = self._col.document(promise_id).get()
        return snap.to_dict() if snap.exists else None

    def update(self, promise_id: str, fields: dict[str, Any]) -> None:
        self._col.document(promise_id).update(fields)

    def all(self) -> list[dict[str, Any]]:
        return [d.to_dict() for d in self._col.stream()]

    def by_status(self, status: str) -> list[dict[str, Any]]:
        return [d.to_dict() for d in self._col.where("status", "==", status).stream()]

    def clear(self) -> int:
        """Delete every promise document. Used by `python -m ledger.seed --fresh`
        so a re-seed replaces the ledger instead of stacking a second copy on
        top of it. Batched deletes, 400 at a time (Firestore's write-batch cap)."""
        n = 0
        batch = self._client.batch()
        pending = 0
        for snap in self._col.stream():
            batch.delete(snap.reference)
            n += 1
            pending += 1
            if pending == 400:
                batch.commit()
                batch = self._client.batch()
                pending = 0
        if pending:
            batch.commit()
        return n


class InMemoryBackend:
    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    def insert(self, doc: dict[str, Any]) -> None:
        self._docs[doc["id"]] = dict(doc)

    def get(self, promise_id: str) -> dict[str, Any] | None:
        d = self._docs.get(promise_id)
        return dict(d) if d else None

    def update(self, promise_id: str, fields: dict[str, Any]) -> None:
        self._docs[promise_id].update(fields)

    def all(self) -> list[dict[str, Any]]:
        return [dict(d) for d in self._docs.values()]

    def by_status(self, status: str) -> list[dict[str, Any]]:
        return [dict(d) for d in self._docs.values() if d.get("status") == status]


class JsonFileBackend:
    """File-backed store: the whole ledger is one JSON object on disk.

    Fine for a single-writer demo (the seed script, the hourly verification
    cycle, one web instance). Every mutation rewrites the file under a lock so
    a half-written file can't be observed by a concurrent reader in the same
    process.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._path = Path(path or DEFAULT_JSON_PATH)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return {d["id"]: d for d in raw.get("promises", [])} if isinstance(raw, dict) else {}

    def _dump(self, docs: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        payload = {"promises": list(docs.values())}
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    def insert(self, doc: dict[str, Any]) -> None:
        with self._lock:
            docs = self._load()
            docs[doc["id"]] = dict(doc)
            self._dump(docs)

    def get(self, promise_id: str) -> dict[str, Any] | None:
        # Reads take the lock too: on Windows, reading the file while another
        # thread is mid-`tmp.replace()` raises PermissionError (WinError 32).
        with self._lock:
            d = self._load().get(promise_id)
            return dict(d) if d else None

    def update(self, promise_id: str, fields: dict[str, Any]) -> None:
        with self._lock:
            docs = self._load()
            if promise_id not in docs:
                raise KeyError(promise_id)
            docs[promise_id].update(fields)
            self._dump(docs)

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(d) for d in self._load().values()]

    def by_status(self, status: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(d) for d in self._load().values() if d.get("status") == status]


_default_backend: PromiseBackend | None = None


def get_backend() -> PromiseBackend:
    """The process-wide default backend, chosen by LEDGER_BACKEND
    ("json" | "firestore" | "memory"; default "json")."""
    global _default_backend
    if _default_backend is None:
        kind = os.getenv("LEDGER_BACKEND", "json").strip().lower()
        if kind == "firestore":
            _default_backend = FirestoreBackend(project=GCP_PROJECT)
        elif kind == "memory":
            _default_backend = InMemoryBackend()
        else:
            _default_backend = JsonFileBackend(os.getenv("LEDGER_JSON_PATH") or None)
    return _default_backend


def reset_default_backend() -> None:
    """Drop the cached default backend (tests / after an env change)."""
    global _default_backend
    _default_backend = None


def _backend(backend: PromiseBackend | None) -> PromiseBackend:
    return backend if backend is not None else get_backend()


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def admit_promise(
    *,
    company: str,
    promise_text: str,
    source_quote: str,
    source_url: str,
    announced_date: str,
    deadline_raw: str,
    deadline_date: str,
    observable_outcome: str,
    check_keywords: list[str],
    evidence_url: str = "",
    extractor_model: str = "",
    auditor_agreed: bool | None = None,
    backend: PromiseBackend | None = None,
) -> str:
    # Store exactly the keywords the falsifiability gate admits on: trimmed,
    # de-duplicated, filler dropped. The verifier's "majority of the keywords
    # present" is then measured against the same list, so a promise can't be
    # padded past the gate and then be structurally unverifiable.
    vetted_keywords = usable_keywords(check_keywords)
    if len(vetted_keywords) < 2:
        raise ValueError(
            f"admit_promise needs >=2 specific check_keywords, got {vetted_keywords or 'none usable'}"
        )

    # Idempotent on (company, deadline, verbatim quote): re-running the same
    # announcement through the demo pipeline must not pile duplicate rows onto
    # the shared public scorecard. The quote/company are normalized (NFKC,
    # smart-quote and dash folding, whitespace collapse, casefold) so a model
    # that renders the same sentence with curly quotes on one run and straight
    # quotes on the next still collides.
    be = _backend(backend)
    key = (_norm_key_text(company), deadline_date.strip(), _norm_key_text(source_quote))
    for existing in be.all():
        if (
            _norm_key_text(existing.get("company", "")),
            existing.get("deadline_date", "").strip(),
            _norm_key_text(existing.get("source_quote", "")),
        ) == key:
            return existing["id"]

    promise = LedgerPromise(
        id=str(uuid.uuid4()),
        company=company,
        promise_text=promise_text,
        source_quote=source_quote,
        source_url=source_url,
        announced_date=announced_date,
        deadline_raw=deadline_raw,
        deadline_date=deadline_date,
        observable_outcome=observable_outcome,
        check_keywords=vetted_keywords,
        evidence_url=evidence_url,
        status=PromiseStatus.PENDING,
        created_at=utcnow_iso(),
        extractor_model=extractor_model,
        auditor_agreed=auditor_agreed,
    )
    be.insert(promise.model_dump(mode="json"))
    return promise.id


def apply_verification(promise_id: str, result, backend: PromiseBackend | None = None) -> None:
    """Persist a VerificationResult onto a promise."""
    be = _backend(backend)
    fields: dict[str, Any] = {
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "status_reason": result.reason,
        "evidence_url": result.evidence_url or "",
        "evidence_excerpt": result.evidence_excerpt or "",
        "last_checked_at": result.checked_at or utcnow_iso(),
        "ship_date_confirmed": result.ship_date_confirmed,
        "verification_method": getattr(result, "verification_method", "") or "",
        "evidence_captured_at": getattr(result, "evidence_captured_at", "") or "",
    }
    if fields["status"] in {s.value for s in RESOLVED_STATUSES}:
        # resolved_at records when the promise FIRST reached a gradeable
        # outcome. Periodic re-verification must not keep bumping it, or the
        # ledger loses the real resolution date.
        existing = be.get(promise_id) or {}
        if not existing.get("resolved_at"):
            fields["resolved_at"] = utcnow_iso()
    be.update(promise_id, fields)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def get_promise(promise_id: str, backend: PromiseBackend | None = None) -> dict[str, Any] | None:
    return _backend(backend).get(promise_id)


def list_promises(backend: PromiseBackend | None = None) -> list[dict[str, Any]]:
    return _backend(backend).all()


def due_for_check(check_date: dt.date | None = None, backend: PromiseBackend | None = None) -> list[dict[str, Any]]:
    """PENDING or still-tracking promises whose deadline has passed.

    DELAYED and PARTIALLY_FULFILLED are "resolved" for the scorecard but are
    still re-checked every cycle: the missing piece can ship later and flip
    them to FULFILLED_LATE / FULFILLED. FULFILLED* is genuinely terminal.

    UNVERIFIABLE promises are retried while there's still a reasonable chance
    the evidence page comes back, but they stop being re-queued once the
    deadline is more than ABANDON_GRACE_DAYS old - otherwise a permanently
    dead URL is re-fetched on every cycle forever and never leaves the queue.
    """
    from ledger.verifier import ABANDON_GRACE_DAYS

    today = check_date or dt.datetime.now(dt.timezone.utc).date()
    trackable = {
        PromiseStatus.PENDING.value,
        PromiseStatus.DELAYED.value,
        PromiseStatus.PARTIALLY_FULFILLED.value,
        PromiseStatus.UNVERIFIABLE.value,
    }
    out = []
    for d in _backend(backend).all():
        status = d.get("status")
        if status not in trackable:
            continue
        try:
            deadline = dt.date.fromisoformat(d["deadline_date"])
        except (KeyError, ValueError):
            continue
        if deadline > today:
            continue
        if status == PromiseStatus.UNVERIFIABLE.value and today > deadline + dt.timedelta(days=ABANDON_GRACE_DAYS):
            continue
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# Scorecard
# --------------------------------------------------------------------------- #
def get_scorecard(backend: PromiseBackend | None = None) -> dict[str, Any]:
    docs = _backend(backend).all()
    resolved_vals = {s.value for s in RESOLVED_STATUSES}
    fulfilled = PromiseStatus.FULFILLED.value

    def _zero() -> dict[str, int]:
        return {"resolved": 0, "kept_on_time": 0, "kept_undated": 0, "kept_late_or_partial": 0,
                "delayed": 0, "abandoned": 0, "pending": 0, "unverifiable": 0}

    by_company: dict[str, dict[str, int]] = {}
    overall = _zero()
    overall["total"] = len(docs)

    for d in docs:
        s = d.get("status", PromiseStatus.PENDING.value)
        c = d.get("company") or "(unknown)"
        cc = by_company.setdefault(c, _zero())
        if s in resolved_vals:
            overall["resolved"] += 1
            cc["resolved"] += 1

        if s == fulfilled and d.get("ship_date_confirmed") is False:
            # delivery proven, but the page carried no date - timeliness is
            # genuinely unknown, so it counts as neither on time nor late.
            bucket = "kept_undated"
        elif s == fulfilled:
            bucket = "kept_on_time"
        elif s in (PromiseStatus.FULFILLED_LATE.value, PromiseStatus.PARTIALLY_FULFILLED.value):
            bucket = "kept_late_or_partial"
        elif s == PromiseStatus.DELAYED.value:
            bucket = "delayed"
        elif s == PromiseStatus.ABANDONED.value:
            bucket = "abandoned"
        elif s == PromiseStatus.UNVERIFIABLE.value:
            bucket = "unverifiable"
        else:
            bucket = "pending"
        overall[bucket] += 1
        cc[bucket] += 1

    def _rate(kept_on_time: int, resolved: int, undated: int) -> float | None:
        # Denominator excludes the undated fulfillments: the rate is "of the
        # resolved promises whose timeliness could be established, the share
        # that were on time".
        datable = resolved - undated
        return round(100 * kept_on_time / datable, 1) if datable else None

    overall["on_time_rate_pct"] = _rate(overall["kept_on_time"], overall["resolved"], overall["kept_undated"])
    companies = []
    for c, cc in sorted(by_company.items()):
        cc = dict(cc)
        cc["company"] = c
        cc["on_time_rate_pct"] = _rate(cc["kept_on_time"], cc["resolved"], cc["kept_undated"])
        companies.append(cc)

    return {"overall": overall, "companies": companies}
