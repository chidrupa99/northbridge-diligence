"""
Test harness: run the real client code against recorded EDGAR responses.

Nothing here touches the network. `_get` is replaced with a fixture reader that
raises the same `EdgarError` an unknown URL would produce, so error paths are
exercised by the same code the server runs in production.
"""
from __future__ import annotations

import json
import pathlib
from datetime import date

import pytest

# The package is installed (`pip install -e ".[dev]"`), so this is a plain
# import — no sys.path manipulation. That is the main practical benefit of the
# src/ layout: tests exercise the package exactly as an installed consumer
# would, rather than a directory that happens to be adjacent.
from northbridge_diligence import edgar_client as ec

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# The date the fixtures were recorded. Freezing it keeps staleness assertions
# stable forever instead of decaying into a flaky test.
FROZEN_TODAY = date(2026, 7, 29)

CIK = {"BYND": "0001655210", "TGT": "0000027419"}


class _FakeResponse:
    def __init__(self, payload: str):
        self._payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}

    @property
    def text(self) -> str:
        return self._payload

    def json(self):
        return json.loads(self._payload)


def _efts_fixture(url: str) -> pathlib.Path | None:
    """Map a full-text search URL back to its recorded response.

    Keyed on CIK plus which curated phrase was asked for, rather than on the
    whole query string, so a reworded phrase does not silently fall through to a
    404 and turn a real assertion into a vacuous one.
    """
    from urllib.parse import parse_qs, urlparse

    params = parse_qs(urlparse(url).query)
    cik = (params.get("ciks") or [""])[0]
    phrase = (params.get("q") or [""])[0].strip('"')
    # The form-scoped query is a separate recording: its total is what the
    # boilerplate classification compares against.
    suffix = "_10K" if params.get("forms") else ""
    for name, spec in ec.DISCLOSURE_PACKS.items():
        if spec["phrase"] == phrase:
            return FIXTURES / f"efts_{cik}_{name}{suffix}.json"
    return None


def _fixture_for(url: str) -> pathlib.Path | None:
    if url.endswith("company_tickers.json"):
        return FIXTURES / "company_tickers.json"
    if "/api/xbrl/companyfacts/CIK" in url:
        return FIXTURES / f"companyfacts_CIK{url.split('CIK')[-1]}"
    if "/submissions/CIK" in url:
        return FIXTURES / f"submissions_CIK{url.split('CIK')[-1]}"
    if "efts.sec.gov" in url:
        return _efts_fixture(url)
    return None


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Serve every EDGAR call from disk, and freeze 'today'."""
    calls: list[str] = []

    def fake_get(url: str):
        calls.append(url)
        path = _fixture_for(url)
        if path is None or not path.exists():
            raise ec.EdgarError(f"EDGAR resource not found (404): {url}")
        return _FakeResponse(path.read_text())

    monkeypatch.setattr(ec, "_get", fake_get)
    monkeypatch.setattr(ec, "_today", lambda: FROZEN_TODAY)
    ec._cache.clear()
    ec.STATS.update(requests=0, cache_hits=0, retries=0)
    yield calls
    ec._cache.clear()


@pytest.fixture
def http_calls(offline):
    """The list of URLs the code under test asked for."""
    return offline
