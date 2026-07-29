# Screening Memo — Target Corporation (TGT)

*Prepared for the Northbridge deal team · Source: SEC EDGAR · FY2025 basis · July 29, 2026*

**Snapshot.** Target (NYSE: TGT) is a general-merchandise retailer (SIC: Retail–Variety Stores) at scale and at a plateau. Revenue is **flat over five years** — $106.0B in FY2021 to **$104.8B** in FY2025, a **−0.3% CAGR** [S1, S3] — while operating income fell **43%** over the same window, from $8,946M to **$5,117M** [S1, S3]. The balance sheet is not the issue: leverage is **1.75x** debt/EBITDA and interest coverage **11.5x** [S1]. This is a margin problem inside a stable, well-capitalised business, not a solvency one.

**Screen signal: Neutral, with one thing to understand.** Only one high-severity flag fired, and on inspection it is structural to retail rather than a distress signal (see below). The real question is whether the FY2021 margin was the anomaly or the FY2025 margin is.

> **Fiscal calendar.** Target's year ends on the Saturday closest to 31 January, so **FY2025 ended 2026-01-31** [S1] and FY2023 ended 2024-02-03. Comparing these to a December filer's like-numbered year introduces an eleven-month offset.

## Financial trajectory

| $M (FY ends late Jan) | FY2021 | FY2022 | FY2023 | FY2024 | FY2025 |
|---|---:|---:|---:|---:|---:|
| Revenue | 106,005 | 109,120 | 107,412 | 106,566 | 104,780 |
| Cost of revenue | 74,963 | 82,306 | 77,828 | 76,502 | 75,511 |
| Operating income | 8,946 | 3,848 | 5,707 | 5,566 | 5,117 |
| Net income | 6,946 | 2,780 | 4,138 | 4,091 | 3,705 |
| Cash from operations | 8,625 | 4,018 | 8,621 | 7,367 | 6,562 |
| Capital expenditures | 3,544 | 5,528 | 4,806 | 2,891 | 3,727 |
| Free cash flow | 5,081 | (1,510) | 3,815 | 4,476 | 2,835 |

| | FY2021 | FY2022 | FY2023 | FY2024 | FY2025 |
|---|---:|---:|---:|---:|---:|
| Gross margin | 29.3% | 24.6% | 27.5% | 28.2% | 27.9% |
| Operating margin | 8.4% | 3.5% | 5.3% | 5.2% | 4.9% |
| Net margin | 6.6% | 2.5% | 3.9% | 3.8% | 3.5% |

**Revenue CAGR FY2021–FY2025: −0.3%. Operating income: −43%.** [S1, S3]

The shape is a shock followed by an incomplete recovery. FY2022 was the break — gross margin fell 470bp to 24.6% and operating margin more than halved, with free cash flow going **negative (−$1,510M)** as capex peaked at $5,528M against collapsed operating cash flow [S1, S2]. Gross margin has since recovered to 27.9%, within 140bp of FY2021.

**Operating margin has not.** It sits at 4.9%, against 8.4% in FY2021, and has drifted *down* in each of the last three years (5.3% → 5.2% → 4.9%) even as gross margin held. That divergence — gross recovering, operating not — points at costs below the gross line rather than at pricing or mix. Worth isolating before forming a view.

## Capital structure

| $M | FY2023 | FY2024 | FY2025 |
|---|---:|---:|---:|
| Cash and equivalents | 3,805 | 4,762 | 5,488 |
| Long-term debt | 14,151 | 13,904 | 14,398 |
| Shareholders' equity | 13,432 | 14,666 | 16,165 |
| Total assets | 55,356 | 57,769 | 59,490 |

| | FY2023 | FY2024 | FY2025 |
|---|---:|---:|---:|
| Debt / EBITDA (proxy) | 1.66x | 1.63x | 1.75x |
| Debt / equity | 1.05x | 0.95x | 0.89x |
| Interest coverage | 11.4x | 13.5x | 11.5x |
| Current ratio | 0.91x | 0.94x | 0.94x |

Comfortable on every measure that matters for solvency. Leverage is stable around 1.7x against a 4.0x screening threshold, coverage is 11.5x against a 2.0x floor, equity has grown $2.7B in two years, and cash is up 44% since FY2023 [S1].

> **Total debt is understated here.** The filer does not tag a current-debt concept in this window, so `total_debt` reflects long-term debt only [S1]. Current maturities are therefore excluded. Reported as a gap rather than estimated — see Data gaps.

## Risk signals

*Computed by the screening tool against fixed thresholds. Every high- and medium-severity flag it raised appears here; none were added or removed by hand.*

- **LIQUIDITY** (high) — Current ratio is 0.94 (below the 1.0 floor); current liabilities exceed current assets. [S1]

**And that flag needs context to be useful.** A sub-1.0 current ratio is *normal* for a large-format retailer: inventory turns fast and suppliers are paid on terms, so payables structurally exceed receivables. Target's ratio has sat between 0.91x and 0.99x in every year of the window [S1] — this is its steady state, not a deterioration. Set against 11.5x interest coverage and $5.5B of cash, it is not a liquidity concern.

This is the clearest illustration of a stated limitation of the tool: **thresholds are one global set.** A 1.0x current-ratio floor is a reasonable bar for a manufacturer and the wrong bar for a retailer. The flag is correct — the rule fired as specified — but a deal lead should read it as an artefact of the threshold rather than a finding. Sector-relative bands are on the roadmap for exactly this.

**No other flag fired.** Specifically absent: `NEGATIVE_EQUITY`, `EARNINGS_QUALITY`, `NEGATIVE_EBITDA`, `LEVERAGE`, `COVERAGE`, `REVENUE_DECLINE`, `CASH_BURN`, `STALE_DATA`.

**Disclosure signals** *(full-text search across all Target filings since 2001; the boilerplate-vs-signal verdict is computed against the 11 annual reports on file).*

- **Going-concern language: absent.** *"Substantial doubt"* appears in **no** Target filing [S5]. Expected here, and confirmed rather than assumed.
- **Customer concentration: absent** [S5]. Expected for a retailer with no single material customer.
- **Material weakness: boilerplate.** Present in all 11 annual reports, which is the signature of the auditor's standard description of its own testing method — not a reported control failure [S5]. **Not a finding.**
- **Goodwill impairment: boilerplate.** Present in all 11 annual reports [S5]. Standing accounting-policy language, not an event.

## Data gaps & caveats

- **`gross_profit` is not tagged after FY2017** — a `TAG_DISCONTINUED` flag fired [S1]. Gross margin above is **derived** from revenue less cost of revenue, and cites both inputs, rather than pairing a stale FY2017 numerator with current revenue.
- **`current_debt` and `total_liabilities` are not tagged** in this window [S1]. Total debt is long-term only and understates the true figure; total liabilities is reported absent rather than estimated.
- **`MIXED_TAG_BASIS`** (info) — six series are stitched across more than one US-GAAP tag because the filer changed tagging mid-history: `interest_expense`, `long_term_debt`, `net_income`, `operating_cash_flow`, `revenue`, `stockholders_equity` [S1]. Comparability is generally fine, but worth a spot-check before quoting a long trend.
- **EBITDA is a proxy** — operating income plus D&A. Not Target's own or any credit-agreement definition.
- **Sources point at the filing each figure was read from**, under an `as_last_reported` restatement policy: FY2023–FY2025 from the FY2025 10-K [S1], FY2022 from the FY2024 10-K [S2], FY2021 from the FY2023 10-K [S3], where they appear as prior-year comparatives. No restatements were detected in this window.
- **Covenant compliance was not checked** — no exact search phrase proved reliable enough to ship. Low concern at 1.75x leverage, but stated rather than implied.
- This is a **first-pass screen from public filings only** — not investment advice, a valuation, or a full diligence review.

## Sources

| Ref | Filing | Filed | Accession | Used for | Link |
|---|---|---|---|---|---|
| S1 | 10-K (FY2025, period ended 2026-01-31) | 2026-03-11 | 0000027419-26-000016 | FY2023–FY2025 figures, flags | [link](https://www.sec.gov/Archives/edgar/data/27419/000002741926000016/tgt-20260131.htm) |
| S2 | 10-K (FY2024 report) | 2025-03-12 | 0000027419-25-000018 | FY2022 figures | [link](https://www.sec.gov/Archives/edgar/data/27419/000002741925000018/0000027419-25-000018-index.htm) |
| S3 | 10-K (FY2023 report) | 2024-03-13 | 0000027419-24-000032 | FY2021 figures (CAGR base) | [link](https://www.sec.gov/Archives/edgar/data/27419/000002741924000032/0000027419-24-000032-index.htm) |
| S4 | 10-Q (period ended 2026-05-02) | 2026-05-29 | 0000027419-26-000022 | Latest interim | [link](https://www.sec.gov/Archives/edgar/data/27419/000002741926000022/tgt-20260502.htm) |
| S5 | EDGAR full-text search (all Target filings, 2001–present) | — | — | Disclosure-signal presence / absence | [link](https://efts.sec.gov/LATEST/search-index?q=%22substantial+doubt%22&ciks=0000027419) |

*Generated by the `company-screen` skill over the northbridge-diligence MCP server. All figures pulled live from SEC EDGAR. Ratios, meaningfulness verdicts and risk flags are computed in Python — re-running the screen returns identical flags.*
