# northbridge-diligence — working context

A Delivery Engineer take-home by **Chidrupa Mamunooru**. Two deliverables, one repo:
an **MCP server** wrapping SEC EDGAR, and an **Agent Skill** (`company-screen`) that
uses it to produce a screening memo for a lower-middle-market PE deal team.

This file exists so a fresh session has the design context without re-deriving it.
Read it before changing anything in `src/`.

## The one idea the whole design turns on

**Code computes, the model narrates.**

Every number, every ratio, every judgment about whether a ratio is *meaningful*, and
every red flag is decided in Python — in `src/edgar_client.py`. The skill is forbidden
from doing arithmetic, from inventing a flag, and from suppressing one. This is not a
style preference; it is the falsifiability property the deliverable is built to
demonstrate: two analysts running the same screen get byte-identical flags, which a
prompt can never guarantee.

The concrete test case is Beyond Meat. Its equity is negative, so `debt_to_equity`
evaluates to −417.0 — arithmetically correct, substantively nonsense. The client
returns it as `meaningful: false` with a written caveat, and the skill is required to
print the caveat *instead of* the number. If you ever find yourself moving judgment
back into the prompt, you are undoing the point of the submission.

## Layout

```
src/edgar_client.py    ~1400 lines. ALL logic lives here. Fetch, parse, normalize,
                       source-attribute, compute, judge, flag.
src/server.py          Thin FastMCP shim. 8 tools, each a docstring + one call into
                       the client, wrapped in _safe() for a uniform error envelope.
                       Keep it thin — no logic belongs here.
skill/SKILL.md         The company-screen skill. Frontmatter name/description are
                       within the 64/1024-char limits (currently 14/670) — re-check
                       if you edit them, the skill silently fails to load otherwise.
tests/                 65 unit tests + 2 golden-set cases. Offline, ~0.2s.
samples/               One worked BYND memo, in .md and self-contained .html.
README.md              The reviewer-facing document. Design decisions and seams.
PRD_*.md               Product framing: problem, requirements, architecture, roadmap.
architecture_flow.*    Mermaid source + rendered svg/png + standalone html viewer.
```

`pconf.json`, `mconf.json`, `package*.json` are Mermaid render tooling only. They are
excluded from the submission zip and are not part of the deliverable.

## MCP tool surface (8)

`resolve_company` · `get_company_profile` · `get_key_financials` ·
`compute_screening_metrics` · `list_filings` · `scan_disclosure_signals` ·
`get_risk_factors` · `get_financial_concept`

Scoping these was itself a graded decision — the brief said "Scope the tools."
The rule applied: one tool per *analyst intention*, not one per API endpoint. Adding
tools that split an intention across two calls makes the model's job harder, not
easier. Resist growing this list without a reason you'd defend out loud.

`scan_disclosure_signals` is the eighth, added deliberately. The defence: the XBRL
side answers "what are the numbers" and had no way to answer "what is the company
worried about". Going-concern doubt, a material weakness and customer concentration
are sentences, and for a distress screen they matter more than any ratio. It is one
tool, not two, because "sweep the disclosures" is one intention -- `extra_phrases`
extends it rather than a second search tool splitting it.

`compute_screening_metrics` is the centrepiece. It returns `metrics` (each with
`value` / `unit` / `meaningful` / `caveat` / `inputs`), `flags`, `data_quality`,
`thresholds`, and `as_of_fiscal_year`.

## Invariants — break these and the submission loses its argument

1. **Every value carries its source.** A `SourcedValue` knows its accession number,
   filing date and URL. No source, no memo line. `inputs` on each metric is what the
   `[S#]` citations in the memo resolve to.
2. **One HTTP call per filer for facts.** We fetch `companyfacts` once — all tags,
   one response — rather than `companyconcept` per tag. A full screen is **two**
   HTTP calls. Do not reintroduce per-tag fetching; it was the main perf finding.
3. **Fallback tags merge per fiscal year, not per tag.** Filers switch US-GAAP tags
   mid-history. Taking the first tag that returns anything truncates the series at
   the switch. `merged_series()` fills year by year and records `mixed_tag_basis`.
4. **Fiscal years are labelled, not inferred from `end.year`.** Target's fiscal 2009
   ended 2010-01-30. `_fy_label()` handles the carry-over; there is a regression test.
5. **Meaningfulness is computed.** `_guarded_ratio()` catches negative and near-zero
   denominators. Never let an uninterpretable ratio reach the memo as a bare number.
6. **`flags` is complete and authoritative.** 13 codes:
   `NEGATIVE_EQUITY` `EARNINGS_QUALITY` `LIQUIDITY` `LEVERAGE` `COVERAGE`
   `NEGATIVE_EBITDA` `REVENUE_DECLINE` `CASH_BURN` `STALE_DATA` `MISSING_DATA`
   `TAG_DISCONTINUED` `MIXED_TAG_BASIS` `RESTATED`.
   Severities: `high` / `medium` → Risk signals; `info` → Data gaps.
7. **Missing data is reported, never estimated.** BYND does not tag `Liabilities`;
   the memo says so rather than backing into a number.
8. **SEC fair access.** Descriptive `User-Agent` (403 without it), ~10 req/s throttle,
   retry on 429/5xx only — never on a 4xx, which would hammer EDGAR over a bug.
9. **Disclosure signals are evidence, not flags.** `scan_disclosure_signals` never
   feeds `flags`. A phrase hit cannot be verified by code, and `flags` is the set
   the deal team is told is arithmetically reproducible. Keeping them apart is what
   lets both claims stay true. The skill reports disclosure signals in their own
   subsection with a verification status.
10. **A false `absent` is the worst output this system can produce.** An "absent"
    verdict is written into the memo as a finding, so an over-specific phrase that
    silently misses becomes a false statement to the deal team. Disclosure phrases
    are therefore tuned for **recall**, and precision is recovered downstream by the
    boilerplate classification plus reading the filing. If you add a pack, measure
    it against at least one filer where the condition is genuinely true — a phrase
    that never fires is worse than no phrase. `test_curated_phrases_stay_short_
    enough_to_match_real_filings` is the cheap guard.
11. **Section extraction anchors on the last heading before the real end marker.**
    Not the first match (lands in the table of contents) and not the last match
    (lands on a cross-reference *after* the section — this returned 2,958 chars of
    the wrong section on Dollar General and reported success). See
    `_find_section_span`.

## Tuning knobs

`THRESHOLDS` and `RESTATEMENT_POLICY` at the top of `edgar_client.py`. Thresholds are
deliberately one global set — a real deployment would want them per sector, and that
is called out as a known seam rather than hidden. `RESTATEMENT_POLICY` is
`as_last_reported`, which is why FY2021 figures are sourced to the FY2023 10-K where
they appear as prior-year comparatives.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 67 pass, offline, ~0.2s
```

Fully offline against recorded fixtures — `conftest.py` monkeypatches `ec._get` and
freezes `_today()` to 2026-07-29 so date-sensitive flags don't rot. BYND and TGT are
in the fixture set because each pins specific failure modes (distress signals;
January FYE plus a mid-history tag switch plus an abandoned `GrossProfit` tag).

`tests/test_golden.py` diffs whole screen outputs field by field and reports
*"metric disappeared"*, *"flags lost"*, *"flags added"* rather than a wall of JSON.
Regenerate deliberately with `UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py`
and read the diff before committing — that file is the behavioural contract.

Refresh fixtures only when EDGAR's shape changes:
`EDGAR_USER_AGENT="Name email@example.com" python tests/record_fixtures.py`

`prune_submissions` keeps every annual report on top of the recent window, not just
the most recent 60 filings. That is load-bearing, not tidiness: the disclosure
classifier compares matched filings against annual reports on file, and a naive
prune left exactly one 10-K per company, so the comparison could never reach its
threshold and the test passed without exercising the logic.

Tests are named after the failure mode they prevent, not the function they cover.
Keep that convention.

## Gotchas already paid for

- **Stale bytecode.** A restored threshold kept failing the golden suite until
  `find . -name __pycache__ -type d -prune -exec rm -rf {} +`. If a change "doesn't
  take", check this before debugging logic.
- **`list_filings` kwarg is `form_types`** (a list), not `forms` or `form_type`.
- **Mermaid ignores `direction LR` inside subgraphs** unless nodes are chained with
  invisible links (`~~~`). That's what those chains in the `.mmd` are for — don't
  "clean them up". Render server-side; the CDN is blocked here. Working command:
  `npx -y @mermaid-js/mermaid-cli@latest -i architecture_flow.mmd -o architecture_flow.svg -b white`
  (add `-s 2` for the png). `architecture_flow.html` embeds the SVG inline — swap
  the `<svg>...</svg>` block when you re-render, or the viewer goes stale silently.
- **EDGAR full-text search counts DOCUMENTS, not filings.** `hits.total` counts
  matching files, and one 10-K is dozens of them, so comparing that total against a
  count of filings produced "20 of 11 annual reports". Use `_distinct_filings()`
  whenever the number meets a filing count.
- **efts.sec.gov 500s intermittently** under bursts. The existing retry handles it;
  don't add a second retry layer on top.

## Before submitting

`EDGAR_USER_AGENT` is set to `chidrupa.mamunooru@example.com` in `README.md`,
`src/server.py` and `tests/record_fixtures.py`. **Swap in a real reachable address** —
EDGAR returns 403 without a valid one, and a reviewer may actually run this.

## What's deliberately not built

Documented in README "What I'd build next" and PRD §10: peer comparables, a wider
golden set, sector-relative thresholds, segment-level revenue, and a disk-backed
cache with an EDGAR freshness check. EBITDA is an operating-income + D&A proxy, and
total debt is approximated from long-term + current debt tags — both are stated as
caveats in the output rather than quietly smoothed over. That honesty is the point;
don't paper over it to make the numbers look cleaner.
