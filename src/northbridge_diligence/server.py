"""
server.py — MCP server exposing the Northbridge diligence toolset.

This is intentionally a THIN layer. All logic lives in edgar_client.py so it is
testable and reusable; here we just register each function as an MCP tool with a
clear, model-facing docstring. Tool docstrings are the model's only spec for
*when* and *how* to call a tool, so they are written for that audience.

Run:  edgar-mcp                   (stdio transport, for MCP clients)
Env:  EDGAR_USER_AGENT="Your Name you@example.com"
      # SEC fair-access header — substitute a real, reachable contact.

You do not normally run this yourself: on stdio the process waits on standard
input, so it looks hung when it is working correctly. The MCP client starts it.
"""

from __future__ import annotations

# The MCP SDK renamed FastMCP to MCPServer in 2.0. Both expose the same .tool()
# decorator and .run(), so supporting each is a two-line import rather than a
# version pin -- and a pin would be the wrong fix: requirements.txt said
# `mcp>=1.2.0`, which resolves to 2.x today, so the documented setup raised
# ImportError before reaching a single tool. tests/test_server.py now imports this
# module so the break cannot recur silently.
try:                                          # SDK >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                           # SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from mcp.types import ToolAnnotations

from . import __version__
from . import edgar_client as ec

# Version is wired through so the stdio `initialize` handshake reports something.
# It returned an empty string before, which tells a client nothing about which
# build it is talking to — unhelpful the moment two versions exist in the wild.
mcp = _Server("northbridge-diligence", version=__version__)


# Every tool here reads public filings and mutates nothing, but nothing said so
# until now. Clients use these hints to decide what needs a confirmation prompt —
# without them a cautious client may gate a read-only lookup behind a dialog.
#
#   read_only_hint   — no side effects at all. True for all eight.
#   idempotent_hint  — same arguments give the same answer. True: EDGAR is an
#                      append-only archive, so a screen only changes when the
#                      filer files something new.
#   open_world_hint  — reaches outside this process. True: every tool talks to
#                      sec.gov, so results depend on an external system being up.
#   destructive_hint — explicitly False. Nothing here can delete or overwrite.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    idempotent_hint=True,
    open_world_hint=True,
    destructive_hint=False,
)


def _safe(fn, *args, **kwargs) -> dict:
    """Uniform error envelope so a bad ticker never crashes the model's turn.

    Deliberately thin. Which code, which category and whether the call is worth
    retrying are all decided by the exception classes in `edgar_client`, so the
    taxonomy is testable without a protocol harness and available to anything
    calling the client directly. This function only serialises what it is given.
    """
    try:
        return fn(*args, **kwargs)
    except ec.EdgarError as exc:
        # Covers AmbiguousCompany too — its envelope() merges the candidate list
        # in, so every tool disambiguates exactly as resolve_company does and the
        # model never sees two shapes for one situation.
        return exc.envelope()
    except Exception as exc:  # unexpected — surface, don't swallow silently
        # The one case where the model should NOT continue: an internal fault
        # means we do not know what happened, and narrating around that is how
        # an invented number reaches a memo.
        return {
            "error": f"Unexpected error: {exc}",
            "recoverable": False,
            "code": "INTERNAL",
            "category": "internal",
            "retryable": False,
        }


@mcp.tool(annotations=READ_ONLY)
def resolve_company(query: str) -> dict:
    """Resolve a ticker OR company name to its SEC CIK.

    Call this FIRST for any company. Accepts a ticker ("MSFT") or a name
    ("Microsoft"). Returns a single {"resolved": {...}} match, or when a name is
    ambiguous, {"ambiguous": true, "candidates": [...]} — in that case ask the
    user which company they mean instead of guessing. EDGAR only covers
    SEC-registered (public) filers.
    """
    return _safe(ec.resolve_company, query)


@mcp.tool(annotations=READ_ONLY)
def get_company_profile(query: str) -> dict:
    """Identity card for a company: legal name, tickers, exchange, SIC industry,
    fiscal year-end, state of incorporation, and links to its latest 10-K/10-Q.
    Use this to orient a screen (who/what/where) before pulling numbers.
    Accepts a ticker or name.
    """
    return _safe(ec.get_company_profile, query)


@mcp.tool(annotations=READ_ONLY)
def get_key_financials(query: str, years: int = 5) -> dict:
    """Curated multi-year financials (income statement, balance sheet, cash flow)
    from annual 10-K XBRL data. Returns each line item as a time series where
    every value carries its provenance: fiscal year, period end, form,
    accession number, and a source URL. Use this for the financial-trajectory
    and capital-structure parts of a screen. `years` = how many fiscal years
    back (default 5).
    """
    return _safe(ec.get_key_financials, query, years=years)


@mcp.tool(annotations=READ_ONLY)
def compute_screening_metrics(query: str, years: int = 5) -> dict:
    """The screen result, computed IN CODE (not by the model): revenue CAGR & YoY
    growth, gross/operating/net margins, total debt, debt/equity, debt/EBITDA,
    current ratio, interest coverage, EBITDA and latest operating cash flow —
    PLUS `flags` (code-detected red flags such as negative equity, weak
    liquidity, high leverage, cash burn, stale data, and net income that is
    positive while the operating business loses money) and `data_quality`.

    Read this carefully before writing anything:
      * Every metric has a `meaningful` boolean and a `caveat`. If
        meaningful=false, DO NOT quote the number — state the caveat instead
        (e.g. a debt/equity of -417x really just means equity is negative).
      * `flags` is the authoritative list of concerns. Report every high- and
        medium-severity flag. Do not invent flags that are not in the list, and
        do not suppress ones that are.
      * Do not recompute or round-trip any arithmetic yourself.
    """
    return _safe(ec.compute_screening_metrics, query, years=years)


@mcp.tool(annotations=READ_ONLY)
def list_filings(query: str, form_types: list[str] | None = None,
                 limit: int = 15) -> dict:
    """Recent SEC filings for a company, each with a direct EDGAR document URL.
    Optionally filter by form (e.g. ["10-K", "10-Q", "8-K"]). Use this to cite
    sources, find the latest annual/quarterly report, or spot recent 8-K events
    worth a second look. `limit` caps the count (default 15).
    """
    return _safe(ec.list_filings, query, form_types=form_types, limit=limit)


@mcp.tool(annotations=READ_ONLY)
def get_risk_factors(query: str) -> dict:
    """Extract the Item 1A "Risk Factors" section from the company's latest
    10-K, plus the source URL. Use this for the risk-signal part of a screen.
    Extraction is conservative: if the section can't be confidently isolated
    from the filing's HTML, it returns a note and the source URL rather than a
    guess — flag that to the user so they open the filing directly.
    """
    return _safe(ec.get_risk_factors, query)


@mcp.tool(annotations=READ_ONLY)
def scan_disclosure_signals(query: str,
                            extra_phrases: list[str] | None = None) -> dict:
    """Sweep a company's filings for the risk LANGUAGE that never appears in the
    numbers: going-concern doubt, material weaknesses, restatements, covenant
    breaches, customer concentration, goodwill impairment. Use this alongside
    compute_screening_metrics for the risk-signals part of a screen — the
    financial tools cannot see any of it.

    Each signal comes back with a computed `assessment`, and that is the field to
    read first:
      * "absent"             — the phrase appears in no filing since 2001. This is
                               a real negative finding; report it as one.
      * "likely_boilerplate" — present in EVERY annual report, so it is standing
                               risk-factor or audit-report template text. Do NOT
                               report it as a finding without reading the filing.
      * "changed_over_time"  — present in some years and not others. The highest-
                               signal case; read the years that differ.
      * "present_non_annual" — appears outside the 10-Ks, so likely a discrete
                               event. Read the filing.

    A hit means the words are in the document, NOT that the condition applies.
    Verify anything present via get_risk_factors or the linked filing before
    writing it up. These signals are deliberately separate from `flags` in
    compute_screening_metrics, which stays reserved for red flags code can verify
    arithmetically. `extra_phrases` appends your own exact phrases to the sweep.
    """
    return _safe(ec.scan_disclosure_signals, query, extra_phrases=extra_phrases)


@mcp.tool(annotations=READ_ONLY)
def get_financial_concept(query: str, metric_or_tag: str, years: int = 6) -> dict:
    """Flexible escape hatch: fetch the annual series for a single financial
    concept — either a friendly name from the curated map (e.g. "revenue",
    "operating_cash_flow", "capex") or a raw US-GAAP XBRL tag (e.g.
    "ResearchAndDevelopmentExpense"). Use when the curated `get_key_financials`
    set doesn't cover something the user asks about. Returns which tag matched.
    """
    return _safe(ec.get_financial_concept, query, metric_or_tag, years=years)


def main() -> None:
    """Entry point for the `edgar-mcp` console script.

    Exposed as a named command rather than a file path so an MCP client config
    can point at `edgar-mcp` on the virtualenv's PATH instead of hardcoding a
    path into the source tree.
    """
    mcp.run()


if __name__ == "__main__":
    main()
