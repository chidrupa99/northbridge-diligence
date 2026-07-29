# Developing this

For an engineer picking this up to extend or maintain it. If you only need to
*deploy* it, the README's deployment section is all you need — this file is the
other half.

Read the next section before changing anything in `src/`. Everything else here
is reference.

---

## The one idea the whole design turns on

**Code computes, the model narrates.**

Every number, every ratio, every judgment about whether a ratio is *meaningful*,
and every red flag is decided in Python — in `src/edgar_client.py`. The skill is
forbidden from doing arithmetic, from inventing a flag, and from suppressing one.

This is not a style preference. It is the falsifiability property the whole tool
rests on: two analysts running the same screen get byte-identical flags, which a
prompt can never guarantee.

The concrete case is Beyond Meat. Its equity is negative, so `debt_to_equity`
evaluates to −417.0 — arithmetically correct, substantively nonsense. The client
returns it as `meaningful: false` with a written caveat, and the skill prints the
caveat *instead of* the number.

**If you find yourself moving judgment back into the prompt, stop.** That is the
one change that would undo the point of the tool.

---

## Layout

```
src/edgar_client.py    ~1,400 lines. ALL logic lives here. Fetch, parse,
                       normalise, source-attribute, compute, judge, flag.
src/server.py          Thin MCP shim. 8 tools, each a docstring plus one call
                       into the client, wrapped in _safe() for a uniform error
                       envelope. Keep it thin — no logic belongs here.
skill/SKILL.md         The company-screen skill. Frontmatter name/description
                       must stay within 64/1024 characters (currently 14/670)
                       or the skill silently fails to load.
scripts/doctor.py      Install verification. Live calls, not fixtures.
tests/                 65 unit tests + 2 golden-set cases. Offline, ~1s.
samples/               One worked BYND memo, in .md and self-contained .html.
README.md              Reviewer- and deployment-facing. Design decisions, seams.
PRD_*.md               Product framing: problem, requirements, roadmap.
architecture_flow.*    Mermaid source, plus rendered svg/png and an html viewer.
```

The split between `edgar_client.py` and `server.py` is deliberate and worth
preserving: all logic lives in the client so it is unit-testable and usable
off-server, and `server.py` only registers it as MCP tools.

---

## Developer setup

```bash
git clone <repo-url> northbridge-diligence         # or unzip the submission
cd northbridge-diligence
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt                # includes runtime deps
export EDGAR_USER_AGENT="Your Name you@example.com"

python -m pytest             # 67 tests, offline, ~1s
python scripts/doctor.py     # live checks against real EDGAR
```

`requirements-dev.txt` starts with `-r requirements.txt`, so it installs both.
`doctor.py` needs no dev dependencies, which is why the README's deployment path
uses it alone.

To test changes against a real Claude client rather than just pytest, register
the server in the client's config — see [DEPLOYMENT.md § 5](DEPLOYMENT.md) for
the full walkthrough. Two things worth calling out from there: **add** the
`mcpServers` block to whatever the config already contains rather than replacing
the file, and point `command` at the venv's Python by absolute path (the client
does not inherit an activated venv). Restart the client after saving; it only
reads the config at launch.

---

## MCP tool surface (8)

`resolve_company` · `get_company_profile` · `get_key_financials` ·
`compute_screening_metrics` · `list_filings` · `scan_disclosure_signals` ·
`get_risk_factors` · `get_financial_concept`

The scoping rule: **one tool per analyst intention, not one per API endpoint.**
Splitting an intention across two calls makes the model's job harder, not
easier. Resist growing this list without a reason you would defend out loud.

`scan_disclosure_signals` is the eighth and shows the bar. The XBRL side answers
"what are the numbers" and had no way to answer "what is the company worried
about" — going-concern doubt and customer concentration are sentences, and for a
distress screen they outrank any ratio. It is one tool rather than two because
sweeping the disclosures is one intention; `extra_phrases` extends it instead of
a second search tool splitting it.

`compute_screening_metrics` is the centrepiece. It returns `metrics` (each with
`value` / `unit` / `meaningful` / `caveat` / `inputs`), `flags`, `data_quality`,
`thresholds`, and `as_of_fiscal_year`.

---

## Invariants

Break these and the tool loses the argument it is built to make.

1. **Every value carries its source.** A `SourcedValue` knows its accession
   number, filing date and URL. No source, no memo line. `inputs` on each metric
   is what the `[S#]` citations resolve to.
2. **One HTTP call per filer for facts.** `companyfacts` once — all tags, one
   response — never `companyconcept` per tag. A full screen is two HTTP calls,
   and a test asserts no `companyconcept` URL is ever requested.
3. **Fallback tags merge per fiscal year, not per tag.** Filers switch US-GAAP
   tags mid-history; first-tag-wins truncates the series at the switch.
   `merged_series()` fills year by year and records `mixed_tag_basis`.
4. **Fiscal years are labelled, not inferred from `end.year`.** Target's fiscal
   2009 ended 2010-01-30. `_fy_label()` handles the carry-over.
5. **Meaningfulness is computed.** `_guarded_ratio()` catches negative and
   near-zero denominators. An uninterpretable ratio must never reach the memo as
   a bare number.
6. **`flags` is complete and authoritative.** 13 codes: `NEGATIVE_EQUITY`
   `EARNINGS_QUALITY` `LIQUIDITY` `LEVERAGE` `COVERAGE` `NEGATIVE_EBITDA`
   `REVENUE_DECLINE` `CASH_BURN` `STALE_DATA` `MISSING_DATA` `TAG_DISCONTINUED`
   `MIXED_TAG_BASIS` `RESTATED`. Severity `high`/`medium` → Risk signals;
   `info` → Data gaps.
7. **Missing data is reported, never estimated.** BYND does not tag
   `Liabilities`; the memo says so rather than backing into a number.
8. **SEC fair access.** Descriptive `User-Agent` (403 without it), ~8 req/s
   self-throttle, retry on 429/5xx only — never on a 4xx, which would hammer
   EDGAR over a bug in our own code.
9. **Disclosure signals are evidence, not flags.** `scan_disclosure_signals`
   never feeds `flags`. A phrase hit cannot be verified by code, and `flags` is
   the set the deal team is told is arithmetically reproducible. Keeping them
   apart is what lets both claims stay true.
10. **A false `absent` is the worst output this system can produce.** "Absent"
    is written into the memo as a finding, so an over-specific phrase that
    silently misses becomes a false statement to the deal team. Phrases are
    tuned for **recall**; precision is recovered by the boilerplate
    classification plus reading the filing. If you add a pack, measure it
    against at least one filer where the condition is genuinely true — a phrase
    that never fires is worse than no phrase.
11. **Section extraction anchors on the last heading before the real end
    marker.** Not the first match (lands in the table of contents) and not the
    last match (lands on a cross-reference *after* the section — that returned
    2,958 characters of the wrong section on Dollar General and reported
    success). See `_find_section_span`.

---

## Tuning knobs

`THRESHOLDS` and `RESTATEMENT_POLICY` at the top of `edgar_client.py`, and
`CONCEPT_MAP` below them.

- **`THRESHOLDS`** is deliberately one global set. A 4.0x debt/EBITDA bar means
  different things in software and in distribution; sector-relative bands are a
  real improvement but need a defensible peer set first. Stated as a seam in the
  README rather than hidden.
- **`RESTATEMENT_POLICY`** is `as_last_reported`, which is why FY2021 figures are
  sourced to the FY2023 10-K where they appear as prior-year comparatives.
- **`CONCEPT_MAP`** curates ~500 filed concepts down to the 17 a screen turns on,
  each mapped to an *ordered* list of candidate tags. Order encodes preference.
  Adding a concept means adding every spelling filers use for it — check against
  at least one bank and one REIT, which is where coverage breaks.

---

## Tests

```bash
python -m pytest -q          # 67 pass, offline, ~1s
```

Fully offline against recorded fixtures. `conftest.py` monkeypatches `ec._get`
and freezes `_today()` to 2026-07-29 so date-sensitive flags do not rot. BYND and
TGT are the fixture filers because each pins specific failure modes: distress
signals, and a January fiscal year end plus a mid-history tag switch plus an
abandoned `GrossProfit` tag.

**Tests are named after the failure mode they prevent, not the function they
cover.** Keep that convention — it is what makes a red build legible.

**The golden set is the behavioural contract.** `tests/test_golden.py` diffs
whole screen outputs field by field and reports *"metric disappeared"*, *"flags
lost"*, *"flags added"* rather than a wall of JSON. Regenerate deliberately:

```bash
UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py
```

Read the diff before committing. Regenerating without reading it is how a
regression gets blessed into the contract.

**Refresh fixtures only when EDGAR's shape changes:**

```bash
EDGAR_USER_AGENT="Name email@example.com" python tests/record_fixtures.py
```

`prune_submissions` keeps every annual report on top of the recent window, not
just the most recent 60 filings. That is load-bearing rather than tidiness: the
disclosure classifier compares matched filings against annual reports on file,
and a naive prune left exactly one 10-K per company — so the comparison could
never reach its threshold and the test passed without exercising the logic.

**What the tests do not cover.** They are offline, so they verify logic, not
installation — they pass with EDGAR unreachable and no contact header set. That
is `doctor.py`'s job. And they only see what the fixtures contain: two filers,
so anything BYND and TGT do not do, the suite does not see. Widening the golden
set is item 5 in the README roadmap for that reason.

---

## Gotchas already paid for

- **Stale bytecode.** A restored threshold kept failing the golden suite until
  `find . -name __pycache__ -type d -prune -exec rm -rf {} +`. If a change
  "doesn't take", check this before debugging logic.
- **`list_filings` kwarg is `form_types`** (a list), not `forms` or `form_type`.
- **EDGAR full-text search counts DOCUMENTS, not filings.** `hits.total` counts
  matching files, and one 10-K is dozens of them — comparing that total against
  a count of filings produced "20 of 11 annual reports". Use
  `_distinct_filings()` whenever the number will meet a filing count.
- **`efts.sec.gov` 500s intermittently** under bursts. The existing retry handles
  it; do not add a second retry layer on top.
- **The MCP SDK renamed `FastMCP` to `MCPServer` in 2.0.** `server.py` imports
  whichever is present, and `requirements.txt` carries a comment about it. Do not
  narrow that pin without updating the import — `tests/test_server.py` exists
  because this broke the documented setup once and nothing caught it.
- **Mermaid ignores `direction LR` inside subgraphs** unless nodes are chained
  with invisible links (`~~~`). That is what those chains in the `.mmd` are for —
  do not "clean them up". Render server-side:
  ```bash
  npx -y @mermaid-js/mermaid-cli@latest -i architecture_flow.mmd -o architecture_flow.svg -b white
  ```
  Add `-s 2` for the png. `architecture_flow.html` embeds the SVG inline — swap
  the `<svg>...</svg>` block when you re-render, or the viewer goes stale
  silently.

---

## What is deliberately not built

Peer comparables, a wider golden set, sector-relative thresholds, segment-level
revenue, linkbase-aware statements, and a covenant signal. Each is in the
README's roadmap with the reason.

Two approximations are load-bearing and stated as caveats in the output rather
than smoothed over: **EBITDA is an operating-income + D&A proxy**, and **total
debt is approximated** from long-term plus current debt tags. Both will differ
from a filer's own definitions.

That honesty is the point. Do not paper over it to make the numbers look
cleaner — the caveat is more useful to a deal lead than a tidier figure.
