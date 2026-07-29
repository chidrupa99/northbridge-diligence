"""
record_fixtures.py — snapshot the EDGAR responses the test suite runs against.

Run this deliberately, not in CI:

    EDGAR_USER_AGENT="Your Name you@example.com" \
        python tests/record_fixtures.py

Why record instead of mocking by hand: the failure modes worth testing (a filer
switching XBRL tags mid-history, a January fiscal year end, a company that
stopped tagging GrossProfit) are things real filings do and hand-written mocks
never think to do. Recording keeps the tests honest; pruning keeps them small.

Refresh when EDGAR's shape changes or a new edge case is worth pinning.
"""
from __future__ import annotations

import json
import pathlib

from northbridge_diligence import edgar_client as ec

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# Each company is here because it exercises a specific edge case.
COMPANIES = {
    "BYND": "distressed: negative equity, negative EBITDA, positive net income "
            "on a loss-making operating business",
    "TGT": "January fiscal year end, tags switched mid-history, GrossProfit "
           "abandoned after FY2017",
}

# Keep the ticker map small but keep enough 'BANK OF ...' rows to exercise
# ambiguous-name resolution.
KEEP_TICKERS = {"BYND", "TGT", "AAPL", "MSFT", "BAC", "RY", "BMO", "BNY", "CM"}

EXTRA_TAGS = ["ResearchAndDevelopmentExpense"]


def prune_facts(blob: dict) -> dict:
    wanted = {t for tags in ec.CONCEPT_MAP.values() for t in tags} | set(EXTRA_TAGS)
    us_gaap = blob.get("facts", {}).get("us-gaap", {})
    blob["facts"] = {"us-gaap": {k: v for k, v in us_gaap.items() if k in wanted}}
    return blob


def prune_efts(blob: dict, keep: int = 60) -> dict:
    """Keep the hit metadata we classify on; drop the aggregation blocks.

    A raw full-text response is ~50 KB of facet counts we never read. Only the
    accession, form and date drive the boilerplate test.
    """
    hits = blob.get("hits", {})
    return {
        "hits": {
            "total": hits.get("total", {}),
            "hits": [
                {"_id": h.get("_id"),
                 "_source": {k: h.get("_source", {}).get(k)
                             for k in ("adsh", "form", "file_date", "ciks")}}
                for h in hits.get("hits", [])[:keep]
            ],
        }
    }


def prune_submissions(blob: dict, keep: int = 60) -> dict:
    """Keep a recent window PLUS every annual report.

    Annual reports are kept unconditionally because the disclosure-signal
    classifier compares "filings that matched" against "annual reports on file".
    A naive most-recent-60 prune left exactly one 10-K per company, so that
    comparison could never reach its threshold and the test passed without
    exercising the logic it was meant to cover.
    """
    recent = blob.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    keep_idx = sorted(
        set(range(min(keep, len(forms))))
        | {i for i, f in enumerate(forms) if f in ec._ANNUAL_FORMS}
    )
    blob["filings"] = {
        "recent": {
            k: ([v[i] for i in keep_idx] if isinstance(v, list) else v)
            for k, v in recent.items()
        }
    }
    return blob


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    tickers = ec._get("https://www.sec.gov/files/company_tickers.json").json()
    pruned = {k: v for k, v in tickers.items()
              if v["ticker"].upper() in KEEP_TICKERS}
    (FIXTURES / "company_tickers.json").write_text(json.dumps(pruned, indent=1))
    print(f"tickers: {len(pruned)} rows")

    for ticker in COMPANIES:
        comp = ec._resolve_cik(ticker)
        cik10 = comp["cik10"]

        facts = ec._get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json").json()
        path = FIXTURES / f"companyfacts_CIK{cik10}.json"
        path.write_text(json.dumps(prune_facts(facts)))
        print(f"{ticker} facts: {path.stat().st_size / 1024:.0f} KB")

        subs = ec._get(f"https://data.sec.gov/submissions/CIK{cik10}.json").json()
        path = FIXTURES / f"submissions_CIK{cik10}.json"
        path.write_text(json.dumps(prune_submissions(subs)))
        print(f"{ticker} submissions: {path.stat().st_size / 1024:.0f} KB")

        # Full-text search, one response per curated phrase. These are what make
        # the boilerplate-vs-signal classification testable offline: BYND matches
        # "material weakness" in every 10-K (template text) and matches
        # going-concern language in none.
        for name, spec in ec.DISCLOSURE_PACKS.items():
            for suffix, forms in (("", None), ("_10K", ["10-K"])):
                payload = ec._efts_search(spec["phrase"], cik10, forms=forms)
                path = FIXTURES / f"efts_{cik10}_{name}{suffix}.json"
                path.write_text(json.dumps(prune_efts(payload)))
        print(f"{ticker} full-text: {len(ec.DISCLOSURE_PACKS) * 2} phrase responses")


if __name__ == "__main__":
    main()
