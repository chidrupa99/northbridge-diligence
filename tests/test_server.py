"""Tests for the MCP shim itself.

These exist because of a real break: `requirements.txt` asked for `mcp>=1.2.0`,
the SDK renamed `FastMCP` to `MCPServer` in 2.0, and the documented setup
(`pip install -e . && edgar-mcp`) therefore raised
ImportError before reaching a single tool. Nothing caught it, because every other
test imports `edgar_client` directly and never loads the server.

So the point of this file is narrow and deliberate: import the module the reviewer
actually runs, and assert the surface is what the README and the skill promise.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from northbridge_diligence import edgar_client as ec
from northbridge_diligence import server


def _tools():
    listed = server.mcp.list_tools()
    if asyncio.iscoroutine(listed):
        listed = asyncio.run(listed)
    return {tool.name: tool for tool in listed}


EXPECTED = {
    "resolve_company",
    "get_company_profile",
    "get_key_financials",
    "compute_screening_metrics",
    "list_filings",
    "scan_disclosure_signals",
    "get_risk_factors",
    "get_financial_concept",
}


def test_server_module_imports_against_the_installed_sdk():
    # The regression itself: this line failing is the whole bug.
    assert server.mcp is not None


def test_the_documented_tool_surface_is_what_registers():
    assert set(_tools()) == EXPECTED


def test_no_tool_ships_without_a_model_facing_description():
    # Docstrings are the model's only spec for when to call a tool, so an empty
    # one is a silent capability loss rather than a cosmetic problem.
    for name, tool in _tools().items():
        assert (tool.description or "").strip(), f"{name} has no description"


def test_disclosure_tool_warns_that_a_hit_is_not_a_finding():
    # The single most important instruction in that tool's contract.
    description = _tools()["scan_disclosure_signals"].description.lower()
    assert "not that the condition applies" in description
    assert "absent" in description


def test_metrics_tool_tells_the_model_not_to_quote_unmeaningful_numbers():
    description = _tools()["compute_screening_metrics"].description.lower()
    assert "meaningful" in description
    assert "do not quote" in description


class TestErrorEnvelope:
    """`_safe` is what keeps a bad ticker from crashing the model's turn."""

    def test_domain_errors_become_recoverable_payloads(self):
        def boom():
            raise server.ec.EdgarError("no such filer")

        result = server._safe(boom)
        assert result["recoverable"] is True
        assert "no such filer" in result["error"]

    def test_ambiguity_keeps_its_candidates(self):
        payload = {"ambiguous": True, "candidates": [{"ticker": "BAC"}]}

        def boom():
            raise server.ec.AmbiguousCompany(payload)

        result = server._safe(boom)
        assert result["ambiguous"] is True
        assert result["candidates"]
        assert result["recoverable"] is True

    def test_unexpected_errors_surface_rather_than_being_swallowed(self):
        def boom():
            raise ValueError("something nobody planned for")

        result = server._safe(boom)
        assert result["recoverable"] is False
        assert "something nobody planned for" in result["error"]


# --------------------------------------------------------------------------- #
# Error taxonomy
#
# The envelope used to be {"error": str, "recoverable": True} for every
# EdgarError, so a 404 on a bad ticker and a 429 rate limit were indistinguishable
# to the model. It could not tell "this will never work" from "try again in a
# moment". These tests pin the two axes apart.
# --------------------------------------------------------------------------- #

TAXONOMY = [
    # exception,                      code,                 category,         retryable
    (ec.InvalidArgument,              "INVALID_ARGUMENT",   "client_error",   False),
    (ec.CompanyNotFound,              "COMPANY_NOT_FOUND",  "client_error",   False),
    (ec.InvalidTag,                   "INVALID_TAG",        "client_error",   False),
    (ec.NoXBRLData,                   "NO_XBRL_DATA",       "data_gap",       False),
    (ec.SectionNotFound,              "SECTION_NOT_FOUND",  "data_gap",       False),
    (ec.RateLimited,                  "RATE_LIMITED",       "upstream_error", True),
    (ec.UpstreamUnavailable,          "UPSTREAM_UNAVAILABLE", "upstream_error", True),
]


@pytest.mark.parametrize("exc_type,code,category,retryable", TAXONOMY)
def test_each_error_type_maps_to_its_own_code(exc_type, code, category, retryable):
    envelope = server._safe(lambda: (_ for _ in ()).throw(exc_type("boom")))
    assert envelope["code"] == code
    assert envelope["category"] == category
    assert envelope["retryable"] is retryable


def test_transient_and_permanent_failures_are_distinguishable():
    """The whole point. A rate limit and a bad ticker must not look alike."""
    transient = server._safe(lambda: (_ for _ in ()).throw(ec.RateLimited("429")))
    permanent = server._safe(lambda: (_ for _ in ()).throw(ec.CompanyNotFound("404")))
    assert transient["retryable"] is True
    assert permanent["retryable"] is False
    assert transient["category"] != permanent["category"]


def test_recoverable_and_retryable_are_independent_axes():
    """A bad ticker is recoverable but not retryable; that pairing must survive.

    `recoverable` means the model can continue its turn. `retryable` means the
    same call may succeed later. Collapsing them was the original defect.
    """
    envelope = server._safe(lambda: (_ for _ in ()).throw(ec.CompanyNotFound("nope")))
    assert envelope["recoverable"] is True
    assert envelope["retryable"] is False


def test_internal_faults_are_the_only_non_recoverable_case():
    # An unexpected exception means we do not know what happened. Narrating
    # around that is how an invented figure reaches a memo.
    envelope = server._safe(lambda: (_ for _ in ()).throw(ValueError("unplanned")))
    assert envelope["recoverable"] is False
    assert envelope["code"] == "INTERNAL"
    assert envelope["category"] == "internal"


def test_retry_after_is_surfaced_when_edgar_sends_one():
    # _get() honoured Retry-After internally and then discarded it, so a caller
    # that exhausted retries had to guess how long to wait.
    envelope = server._safe(
        lambda: (_ for _ in ()).throw(ec.RateLimited("429", retry_after_seconds=30.0))
    )
    assert envelope["retry_after_seconds"] == 30.0


def test_retry_after_is_absent_rather_than_null_when_not_sent():
    envelope = server._safe(lambda: (_ for _ in ()).throw(ec.RateLimited("429")))
    assert "retry_after_seconds" not in envelope


class TestBackwardCompatibility:
    """SKILL.md documents the old shape and the goldens snapshot it."""

    def test_error_and_recoverable_keys_are_unchanged(self):
        envelope = server._safe(lambda: (_ for _ in ()).throw(ec.CompanyNotFound("x")))
        assert envelope["error"] == "x"
        assert isinstance(envelope["recoverable"], bool)

    def test_ambiguity_still_carries_its_candidate_payload(self):
        payload = {"ambiguous": True, "candidates": [{"ticker": "BAC"}], "note": "pick one"}
        envelope = server._safe(
            lambda: (_ for _ in ()).throw(ec.AmbiguousCompany(payload))
        )
        assert envelope["ambiguous"] is True
        assert envelope["candidates"] == [{"ticker": "BAC"}]
        # ...and now also carries the taxonomy.
        assert envelope["code"] == "AMBIGUOUS_COMPANY"
        assert envelope["retryable"] is False


class TestVersionHandshake:
    def test_server_reports_a_non_empty_version(self):
        # The stdio initialize handshake returned version "" before this was
        # wired, so a client could not tell which build it was talking to.
        from northbridge_diligence import __version__
        assert __version__
        assert server.mcp.version == __version__


class TestToolAnnotations:
    """All eight tools are read-only; none said so.

    Clients use these hints to decide what needs a confirmation prompt. Without
    them a cautious client may gate a public-filings lookup behind a dialog, or
    a careless one may treat a mutating tool as safe — the hints exist so
    neither has to guess.
    """

    def test_every_tool_declares_itself_read_only(self):
        for name, tool in _tools().items():
            assert tool.annotations is not None, f"{name} has no annotations"
            assert tool.annotations.read_only_hint is True, name

    def test_every_tool_declares_itself_idempotent(self):
        # EDGAR is an append-only archive: the same arguments give the same
        # answer until the filer files something new.
        for name, tool in _tools().items():
            assert tool.annotations.idempotent_hint is True, name

    def test_every_tool_declares_that_it_reaches_outside(self):
        # Results depend on sec.gov being up, which a client may want to know.
        for name, tool in _tools().items():
            assert tool.annotations.open_world_hint is True, name

    def test_no_tool_claims_to_be_destructive(self):
        for name, tool in _tools().items():
            assert tool.annotations.destructive_hint is False, name


# --------------------------------------------------------------------------- #
# Resources
#
# The reference data that shaped every returned number was invisible: a model
# asking "why is this LEVERAGE" had to infer the threshold from the response.
#
# The risk in exposing it is a hand-maintained copy that drifts from the code and
# then lies confidently — the exact failure this codebase is organised against. So
# every resource is serialised from the live constant, and these tests assert that
# rather than trusting it.
# --------------------------------------------------------------------------- #

def _resources():
    listed = server.mcp.list_resources()
    if asyncio.iscoroutine(listed):
        listed = asyncio.run(listed)
    return {str(r.uri): r for r in listed}


def _read(uri: str) -> dict:
    body = server.mcp.read_resource(uri)
    if asyncio.iscoroutine(body):
        body = asyncio.run(body)
    if isinstance(body, list):
        body = body[0].content
    return json.loads(str(body))


EXPECTED_RESOURCES = {
    "northbridge://reference/concept-map",
    "northbridge://reference/thresholds",
    "northbridge://reference/flag-catalogue",
    "northbridge://reference/disclosure-packs",
    "northbridge://reference/absence-codes",
    "northbridge://diagnostics/stats",
}


def test_the_documented_resources_are_registered():
    assert set(_resources()) == EXPECTED_RESOURCES


def test_every_resource_declares_json_and_a_description():
    for uri, res in _resources().items():
        assert res.mime_type == "application/json", uri
        assert res.description and len(res.description) > 40, uri
        assert res.name, uri


class TestResourcesMatchLiveConstants:
    """A copy is a thing that drifts. These fail the moment one does."""

    def test_concept_map_is_the_live_concept_map(self):
        assert _read("northbridge://reference/concept-map")["concepts"] == ec.CONCEPT_MAP

    def test_thresholds_are_the_live_thresholds(self):
        payload = _read("northbridge://reference/thresholds")
        assert payload["thresholds"] == ec.THRESHOLDS
        assert payload["restatement_policy"] == ec.RESTATEMENT_POLICY

    def test_flag_catalogue_is_the_live_catalogue(self):
        assert _read("northbridge://reference/flag-catalogue")["flags"] == ec.FLAG_CATALOGUE

    def test_disclosure_packs_are_the_live_packs(self):
        assert _read("northbridge://reference/disclosure-packs")["packs"] == ec.DISCLOSURE_PACKS

    def test_absence_codes_are_the_live_codes(self):
        assert _read("northbridge://reference/absence-codes")["codes"] == ec.ABSENCE_CODES

    def test_stats_resource_reflects_the_live_counters(self):
        payload = _read("northbridge://diagnostics/stats")
        assert set(payload["stats"]) == set(ec.STATS)


class TestFlagCatalogueIsTheSingleSourceOfTruth:
    """Severity is written down once, in the catalogue.

    Before this, each of the 13 `add(...)` call sites carried its own severity
    string, so a catalogue resource would have been a second copy of the same
    fact — free to disagree with the behaviour it documented.
    """

    def test_catalogue_covers_every_code_the_engine_can_raise(self):
        import pathlib
        import re
        source = (pathlib.Path(ec.__file__)).read_text()
        raised = set(re.findall(r'add\("([A-Z_]+)"', source))
        assert raised, "no flag call sites found — did add() get renamed?"
        assert raised == set(ec.FLAG_CATALOGUE)

    def test_every_catalogued_flag_has_severity_trigger_and_rationale(self):
        for code, spec in ec.FLAG_CATALOGUE.items():
            assert spec["severity"] in {"high", "medium", "info"}, code
            assert spec["fires_when"], code
            assert spec["why"], code

    def test_the_thirteen_codes_the_docs_promise(self):
        # DEVELOPING.md invariant 6 names exactly these.
        assert len(ec.FLAG_CATALOGUE) == 13
