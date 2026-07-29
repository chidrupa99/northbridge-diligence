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

import pytest

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
