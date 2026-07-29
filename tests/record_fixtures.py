"""
record_fixtures.py — snapshot the EDGAR responses the test suite runs against.

Run this deliberately, not in CI:

    EDGAR_USER_AGENT="Chidrupa Mamunooru chidrupa.mamunooru@example.com" \
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
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import edgar_client as ec  # noqa: E402

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


def prune_submissions(blob: dict, keep: int = 60) -> dict:
    recent = blob.get("filings", {}).get("recent", {})
    blob["filings"] = {
        "recent": {k: v[:keep] if isinstance(v, list) else v
                   for k, v in recent.items()}
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


if __name__ == "__main__":
    main()
