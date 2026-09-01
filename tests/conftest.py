"""Shared test setup: never let a test touch the real ledger file or the network."""

import pytest

from ledger import promises


@pytest.fixture(autouse=True)
def _isolate_ledger_backend(monkeypatch, tmp_path):
    """Force the process-wide default backend to a throwaway in-memory one for
    every test, so a call that omits `backend=` can't read or write the repo's
    committed ledger file."""
    monkeypatch.setenv("LEDGER_BACKEND", "memory")
    monkeypatch.setenv("LEDGER_JSON_PATH", str(tmp_path / "ledger.json"))
    promises.reset_default_backend()
    yield
    promises.reset_default_backend()


@pytest.fixture(autouse=True)
def _no_wayback(monkeypatch):
    """The verifier consults the Wayback Machine for a point-in-time capture.
    Default every test to "no snapshot" so the suite stays offline; tests that
    exercise the archive path patch ledger.verifier.snapshot_near explicitly."""
    monkeypatch.setattr("ledger.verifier.snapshot_near", lambda *a, **k: None)
