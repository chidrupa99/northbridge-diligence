# Northbridge Diligence — SEC EDGAR MCP + Screening Skill

**Chidrupa Mamunooru** · Delivery Engineer take-home

A two-layer tool for Northbridge Capital Partners' deal team:

- **Data layer (MCP server)** — wraps the SEC EDGAR APIs into a focused set of tools a model can call to answer diligence questions, with every number traced to its source filing.
- **Intelligence layer (skill)** — sits on top and turns a company name into a **first-pass screening memo** an analyst would hand to a deal lead.

The goal is the one the client stated: *"get this data via Claude so our analysts save time, and the deal team can trust those numbers."*

Trust is enforced structurally, not by asking the model nicely. Three things are load-bearing:

1. **Every figure carries its filing** — accession number, form type, period end, XBRL tag, and a resolvable EDGAR URL.
2. **The code computes; the model narrates.** Ratios, the judgment of whether a ratio is *meaningful*, and the risk flags are all produced in Python against fixed thresholds. The skill is forbidden from doing arithmetic or inventing a flag.
3. **The behaviour is pinned by tests** — 67 offline tests plus a golden-set regression, so a tag-mapping tweak that would silently change a margin fails the build instead.

---

## Architecture

```
company name ──► [ company-screen skill ]         (intelligence layer)
                        │  selects tools, narrates the result, writes the memo
                        │  does NOT compute ratios or decide risk
                        ▼
             [ northbridge-diligence MCP server ]  (data layer, src/server.py)
                        │  thin MCP shim: decorators + uniform error envelope
                        ▼
             [ edgar_client.py ]                    (all logic: HTTP, XBRL, math, flags)
                        │
                        ▼
                 SEC EDGAR REST APIs
```

`edgar_client.py` holds **all** logic so it is unit-testable and reusable off-server; `server.py` is a thin registration layer. The sample memos were assembled following the skill's template from the tool functions' outputs — the same functions the MCP server exposes to a Claude client, without the intermediate protocol round-trip.

### One fetch, not eighteen

Financial data comes from `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` — **one request returns every XBRL fact the filer has ever reported**. An earlier design called `companyconcept` once per tag, which meant ~18 requests per screen, 18 chances to hit a rate limit, and 18 partial-failure modes.

A full screen is now **two HTTP calls**: the ticker→CIK map (cached) and one `companyfacts` blob (cached). A test asserts this and asserts no `companyconcept` URL is ever requested, so the property can't regress.

The same blob also hands us every prior-year comparative for free — a FY2025 10-K carries FY2023 and FY2024 columns — so a five-year history needs no extra requests.

---

## Setup

**Prerequisites:** Python 3.10+ (the MCP SDK requires it) and an MCP client — Claude Desktop or Claude Code.

```bash
# 1. Get the code onto the machine
unzip northbridge-diligence-submission.zip     # or: git clone <repo-url>
cd northbridge-diligence

# 2. Install dependencies into a private virtualenv
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Identify yourself to SEC (contact string, not a credential — EDGAR is public)
export EDGAR_USER_AGENT="Your Org you@example.com"

# 4. Verify — 9 checks; each failure prints its fix
python scripts/doctor.py

# 5. Install the skill
cp -r skill ~/.claude/skills/company-screen
```

`export` sets an **environment variable** — a value the terminal remembers for this session and passes to any program launched from it. SEC returns HTTP 403 without a contact header, so both `doctor.py` and the server need this value. Do step 4 before step 6, or a broken install first appears as a skill silently returning nothing inside a Claude conversation.

**6. Register the server with your Claude client.** This one is not a shell command — it edits a JSON file the client reads at launch. In Claude Desktop: **Settings → Developer → Edit Config**. **Add** to what is already there rather than replacing:

```jsonc
{
  "mcpServers": {
    "northbridge-diligence": {
      "command": "/absolute/path/to/northbridge-diligence/.venv/bin/python",
      "args":    ["/absolute/path/to/northbridge-diligence/src/server.py"],
      "env":     { "EDGAR_USER_AGENT": "Your Org you@example.com" }
    }
  }
}
```

Then **restart the client**. Full walkthrough — where the file lives on each platform, the merge case when other MCP servers are already registered, JSON validation and troubleshooting — in [DEPLOYMENT.md § 5](DEPLOYMENT.md).

Two things that catch people out here: **point `command` at the virtualenv's Python** by absolute path — the client does not inherit an activated venv — and **never run `src/server.py` yourself**. It speaks MCP over stdio, so it waits silently on standard input and looks hung when it is working correctly. The client starts it.

**To trigger the skill**, say: *"Screen Beyond Meat for the deal team"* — any ticker or company name. A correct result carries `[S1]`-style markers throughout and a Sources table; figures without source markers mean the skill is not being used.

- **Installing for a team?** → [DEPLOYMENT.md](DEPLOYMENT.md) — security posture, egress requirements, troubleshooting
- **Extending or maintaining it?** → [DEVELOPING.md](DEVELOPING.md) — test harness, fixtures, tuning knobs, invariants

---

## The tools — what each does and *why*

Scoping the toolset was the main judgment call. The principle: **one tool = one diligence question an analyst actually asks**, each returning source-attributed data, nothing that overlaps.

| Tool | What it does | Why it exists |
|---|---|---|
| `resolve_company` | ticker/name → CIK; flags ambiguous names | Everything keys off CIK. Ambiguity is surfaced (not guessed) because screening the wrong "Bank of X" is a silent, costly error. Every tool raises the *same* disambiguation payload, so the model never has to learn two shapes. |
| `get_company_profile` | identity, SIC industry, fiscal year-end, latest 10-K/10-Q | Orients a screen (who/what/where) and anchors the fiscal calendar before pulling numbers. |
| `get_key_financials` | curated multi-year IS/BS/CF, each value source-tagged | The financial-trajectory + capital-structure backbone. Returns `reference_fiscal_year`, `xbrl_tags_used` and `mixed_tag_basis` so the reader can see *how* the series was assembled. |
| `compute_screening_metrics` | growth, margins, leverage, liquidity — **computed in code** — plus `flags`, `data_quality`, and the `thresholds` used | The client must *trust the numbers*. LLM arithmetic isn't trustworthy, so ratios are calculated in Python, returned with the sourced inputs, and each marked `meaningful: true|false`. |
| `list_filings` | recent filings + direct EDGAR URLs | Source citation, latest annual/quarterly report, and recent 8-K events worth a second look. |
| `scan_disclosure_signals` | full-text sweep for going-concern doubt, material weaknesses, customer concentration and goodwill impairment — with a **computed** boilerplate-vs-signal verdict | The numbers cannot show what a company is *worried about*. Two things make this more than a search box: the phrasing is calibrated against real filings, and the judgment of whether a hit means anything is computed rather than narrated — language present in every annual report is template text, language that comes and goes is news. Deliberately kept **out** of `flags`, which stays reserved for red flags code can verify arithmetically. |
| `get_risk_factors` | Item 1A from the latest 10-K | The "risk section worth a second look," and the verification step for anything `scan_disclosure_signals` reports as present. Conservative extraction — returns the source URL and a note rather than a guess if it can't isolate the section. |
| `get_financial_concept` | any one metric/US-GAAP tag as a time series | Escape hatch for questions the curated set doesn't cover (R&D, capex). Keeps the curated tools focused while staying flexible. Tag names are validated against a strict pattern before they reach a URL. |

### The second scoping decision: ~500 concepts down to 17

Scoping happened twice — once at the tool surface above, and once at the data layer. The second is less visible and arguably more consequential.

Filers do not report a common set of concepts. Measured across seven filers in different industries: Beyond Meat reports 376 US-GAAP concepts, Apple 503, JPMorgan 917. Between them they use **2,220 distinct concepts, of which only 49 are common to all seven** — a shared core of roughly 2%, and mostly plumbing (share counts, tax line items). Almost nothing you would build a screen on.

So `CONCEPT_MAP` curates that down to **17 concepts a first-pass PE screen actually turns on**, each mapped to an *ordered* list of candidate US-GAAP tags:

| Statement | Concepts |
|---|---|
| Income | `revenue` · `cost_of_revenue` · `gross_profit` · `operating_income` · `interest_expense` · `net_income` |
| Balance sheet | `total_assets` · `total_liabilities` · `current_assets` · `current_liabilities` · `stockholders_equity` · `cash` · `long_term_debt` · `current_debt` |
| Cash flow | `operating_cash_flow` · `depreciation_amortization` · `capex` |

17 concepts, 33 candidate tags — 11 of the 17 need more than one spelling, because filers disagree:

```python
"revenue": [
    "RevenueFromContractWithCustomerExcludingAssessedTax",  # post-ASC 606: Apple, Target, Tesla
    "Revenues",                                             # JPMorgan, Pfizer, Realty Income
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",                                      # legacy, pre-2018
],
```

The order encodes preference, not just alternatives: the modern tag wins where both exist, and the legacy tag fills the years before the transition.

**No single revenue tag covers all seven filers above.** The two leading tags cover six each — but not the same six. The contract-revenue tag misses JPMorgan; `Revenues` misses Beyond Meat. That is why this is a list rather than a string, and why the merge happens per fiscal year rather than per tag.

Curation is not a ceiling. Anything outside the 17 stays reachable through `get_financial_concept`, by friendly name or raw tag — so the curated set keeps the common path focused without making the uncommon question impossible.

### Attribution model

Every financial datapoint is a `SourcedValue` carrying `period_end`, `fiscal_year`, `form`, `accession`, `xbrl_tag`, `filed`, a resolvable `source_url`, and — when the figure was later revised — `restated` plus `originally_reported`. The skill renders these as `[S#]` markers mapping to a Sources table. **If a number has no source, it does not go in the memo.**

---

## The design decision the whole thing turns on: code computes, the model narrates

The first version of this tool put the interesting judgment in the skill prompt: *"flag negative equity rather than quoting the exploded ratio," "call out current ratio below 1."* It produced good memos. It was also unfalsifiable — two runs could disagree, and nobody could point at the line that decided.

So the judgment moved into Python:

**Ratio meaningfulness.** `_guarded_ratio` returns `(value, meaningful, caveat)`. A negative denominator, a zero denominator, or a denominator near zero relative to the numerator all yield `meaningful: false` with an explanation. Beyond Meat's debt/equity is arithmetically −417.0; the tool returns that number marked unmeaningful with *"denominator is negative — the ratio is not interpretable; report the negative balance itself instead."* The skill is instructed never to quote an unmeaningful figure.

**Risk flags.** `_detect_flags` returns a structured list — `code`, `severity`, `message`, `evidence` (SourcedValues) — against the thresholds in one `THRESHOLDS` dict that is *returned with the response*, so the reader always sees the bar that fired:

`NEGATIVE_EQUITY` · `EARNINGS_QUALITY` · `LIQUIDITY` · `LEVERAGE` · `COVERAGE` · `NEGATIVE_EBITDA` · `REVENUE_DECLINE` · `CASH_BURN` · `STALE_DATA` · `MISSING_DATA` · `TAG_DISCONTINUED` · `MIXED_TAG_BASIS` · `RESTATED`

The payoff is that an analyst can re-run `compute_screening_metrics("BYND")` and get byte-identical flags. That is not a property a prompt can have. The skill's remaining job — deciding what leads the memo, what a deal lead actually needs to know — is exactly the part that *should* be a language model's.

---

## XBRL is messier than it looks — what the client handles

These are the cases that separate a working screen from a demo. Each is covered by a test named after the failure it prevents.

**Filers switch tags mid-history.** Given the tag ladders above, the naive implementation is first-tag-wins: try the modern tag, and if it returns anything, stop. That silently truncates history at the ASC 606 transition — Ford came back with 10 years instead of 19, Target 10 instead of 18. Fixed by merging candidates **per fiscal year** rather than per tag. Where a series spans more than one tag, `mixed_tag_basis` says so and an info flag fires.

**Fiscal years aren't calendar years.** Target's fiscal 2009 ended 2010-01-30. Taking `end[:4]` labels it 2010 and puts two "2009"s in the series. The fix reads the filer's own `fy` label out of the facts — within one accession, the fact with the latest period end *is* that report's own year — and carries the offset over to comparatives the index didn't cover directly. A test pins `2010-01-30 → FY2009`.

**Filers abandon tags.** Target stopped tagging `GrossProfit` after FY2017. A positional slice (`series[-5:]`) happily returned FY2013–2017 gross profit and set it beside FY2021–2025 revenue — which would have produced a gross margin dividing an eight-year-old numerator by a current denominator. Every series is now windowed **by fiscal year** against a `reference_fiscal_year` derived from anchor items, and each point-in-time metric reads its exact year or nothing. An abandoned tag becomes a visible gap plus a `TAG_DISCONTINUED` flag, never a stale number.

**Filers restate.** When the same period appears in multiple filings, `RESTATEMENT_POLICY` (default `as_last_reported`) picks one, and the value carries `restated: true` with `originally_reported` so the change is auditable rather than invisible.

**Currency.** Units are chosen preferring USD and never mixed; if line items span currencies, every metric is marked unmeaningful rather than quietly dividing dollars by euros.

### Other error & edge-case handling

- **Missing SEC header → 403:** detected and turned into an actionable message.
- **Bad ticker / private company:** clear "no SEC filer matched" (EDGAR only covers registered filers).
- **Ambiguous names:** returns candidates instead of guessing, from every tool.
- **Rate limits & transient failures:** self-throttled to ~8 req/s (under SEC's 10/s), with exponential-backoff retries on 429/5xx that honour `Retry-After`. 403/404 are *not* retried — they won't get better.
- **Caching:** a bounded, TTL'd, thread-safe cache (64 entries, 1h) so a deal sprint's repeat screens are instant and gentle on EDGAR. `STATS` exposes requests/cache hits/retries.
- **Messy 10-K HTML:** risk-factor extraction is conservative; failure returns the source URL for manual review.
- **Uniform error envelope** at the server layer (`{"error": ..., "recoverable": ...}`) so one bad call never crashes the model's turn.

---

## Tests

67 offline tests plus a golden-set regression, in about a second. Three things about them are deliberate:

**Recorded fixtures, not hand-written mocks.** Real EDGAR responses for two filers chosen for what they break. Beyond Meat gives negative equity, negative EBITDA and positive net income on a loss-making operating business; Target gives a January fiscal year end, a mid-history tag switch, and an abandoned `GrossProfit`. Hand-written mocks never invent a January-FYE retailer that stops tagging gross profit — real filings do, which is the point.

**Named after failure modes, not functions** — `test_january_year_end_uses_the_filers_own_label_not_the_calendar_year`, `test_abandoned_tag_becomes_a_gap_not_a_stale_number`, `test_a_full_screen_costs_two_http_calls`. EDGAR rarely crashes you; it hands you a plausible wrong number, so each test pins one specific way that happens.

**The golden set is the behavioural contract.** It snapshots entire screen outputs and, on failure, names the field — `flags lost: ['LIQUIDITY']` — rather than dumping a 200-line dict. I verified the harness actually bites by moving the current-ratio threshold from 1.0 to 0.5 and confirming it reported exactly that.

One limit worth stating: the suite is offline, so it verifies *logic*, not *installation* — it passes with EDGAR unreachable and no contact header set. `scripts/doctor.py` covers that gap. Running and extending the suite is documented in [DEVELOPING.md](DEVELOPING.md).

---

## Design decisions & seams

**What I deliberately left out** (scope discipline — each is a defensible *next* addition, not an oversight):

- **Public comps / peer benchmarking.** High value, but it needs a peer-selection method (SIC is too crude) and multiplies API load. It's the first thing I'd add (see below), built on `get_key_financials`.
- **Open-ended full-text search.** `scan_disclosure_signals` wraps EDGAR's FTS endpoint, but only behind curated phrases with a computed verdict. A general "search filings for X" tool was deliberately not exposed: an arbitrary phrase gives the model no way to tell boilerplate from news, which is the entire difficulty. `extra_phrases` is the escape hatch, and it carries the caveat.
- **Quarterly / TTM data.** The screen is annual-first for signal clarity. The plumbing (`annual_series`) generalizes to quarterly with a filter change.
- **Insider / ownership (Forms 3/4/5) and institutional holdings.** Useful for a deeper look, noise for a first pass.

**Where the seams are (known limitations):**

- **US-GAAP XBRL only.** Foreign private issuers (20-F / IFRS) and non-XBRL filers won't populate `get_key_financials`; the tool says so rather than returning partial nonsense.
- **"Total debt" is approximated** as long-term + current debt tags; finance-lease and other debt-like items aren't fully assembled. Flagged where it matters.
- **EBITDA is a proxy** — operating income plus D&A from the cash flow statement. It is not any filer's adjusted definition and shouldn't be compared to one.
- **Thresholds are one global set.** A 4.0x debt/EBITDA bar means different things in software and in distribution. Industry-relative bands are a real improvement, but they need a defensible peer set first — which is the comps tool.
- **Risk-factor extraction is heuristic** (heading match on messy HTML); it degrades to "here's the source, read it yourself" instead of fabricating. The heuristic has been through one real failure: anchoring on the *last* heading match returned 2,958 characters of the wrong section on Dollar General's 10-K — where Item 1C cross-references Item 1A — and reported it as a successful extraction. It now uses the widest start/end pairing to identify the real end marker, then takes the last heading before it, which excludes both contents rows and later cross-references. A filer with a stranger document structure could still defeat it.
- **Covenant compliance is not searchable.** A covenant pack was built and then removed: `"covenant violation"`, `"waiver from our lenders"` and `"not in compliance with the covenants"` each returned zero hits even against a genuinely distressed filer, while bare `"covenant"` returned 84 (Beyond Meat) and 274 (Target) of pure boilerplate. A pack that always reports "absent" is worse than no pack, because absence is written into the memo as a finding. Stated as a gap instead.
- **Disclosure phrases trade precision for recall, on purpose.** The first version used the full formal wording — `"material weakness in our internal control over financial reporting"` — which matched **0** Target filings while `"material weakness"` matched 23. An over-specific phrase produces a false `absent`, and that is the most damaging error this tool can make. Precision is recovered downstream by the boilerplate classification and the requirement to read the filing.

---

## Sample output

Two real screens, generated live from EDGAR, each as Markdown and a self-contained HTML one-pager. The brief asks for one; a second is included because a single company cannot show that the tool *discriminates*.

**[Beyond Meat](samples/BYND_screening_memo.md) — the distress case.** Five flags fire. It demonstrates the thing that separates a real screen from a naive one: FY2025 **net income is positive (+$219M) while the operating business lost −$334M**. A naive tool reports "profitable." This one raises an `EARNINGS_QUALITY` flag naming the ~$553M of profit that came from outside the operating business, marks debt/equity unmeaningful because equity is negative, and tells the deal lead to identify the non-operating item first — because that item is *not* isolable from XBRL, and saying so is more useful than guessing at it.

**[Target](samples/TGT_screening_memo.md) — the healthy case.** Every solvency flag stays silent, which is the harder thing to demonstrate. Revenue is flat over five years while operating income fell 43%, so the finding is a margin problem inside a sound balance sheet. The one flag that does fire — `LIQUIDITY`, current ratio 0.94 — is shown in the memo to be an artefact of applying one global threshold to a retailer, where payables structurally exceed receivables, rather than a finding. That is a seam this README already declares, caught working in public. Target also exercises the January fiscal year end, a mid-history tag switch across six series, and a gross margin derived because `GrossProfit` has been untagged since FY2017.

---

## What I'd build next (another week)

1. **Comps tool.** Assemble a peer set (SIC + size band, human-overridable) and return side-by-side growth, margin and leverage with the same attribution. A margin falling 240bp means one thing alone and another against five peers — and it's what would make industry-relative thresholds defensible instead of one global set.

2. **Linkbase-aware statements.** Statement structure lives in each filing's `_pre.xml` and `_cal.xml`, not in `companyfacts`. `_cal.xml` declares which lines sum to which subtotals, giving a free reconciliation check — JPMorgan's net interest income ($95.4bn) plus noninterest income ($87.0bn) ties exactly to $182.4bn of revenue. `_pre.xml` explains gaps: JPMorgan's income statement has no operating income line at all, which turns a bare `MISSING_DATA` flag into a structural answer. It would surface candidates for a human, never auto-substitute — mapping pretax income onto operating income would break the report-gaps-never-estimate invariant, and for a bank the difference is the loan loss provision.

3. **A covenant signal that actually works.** Exact-phrase search failed and was cut (see seams). The tractable version reads the debt footnote and Item 7 liquidity discussion directly instead of pattern-matching the filing — it targets the one capital-structure question this screen cannot answer.

4. **Year-over-year risk-factor diff.** A *newly added* risk factor is a far stronger signal than any standing one. The section extractor already spans Items 1A/3/7/9A, so the plumbing exists; the open problem is aligning risk factors across years in a way that survives rewording.

5. **Widen the golden set.** 15–20 filers covering a foreign issuer, a recent IPO, a restatement and a spin-off, run in CI. Trust needs tests, and the tests need coverage.
