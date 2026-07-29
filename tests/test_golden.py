"""
Golden-set regression: the whole screen output, byte for byte.

The unit tests check individual behaviours. This one checks the thing the deal
team actually consumes — if a tag-mapping tweak silently changes a margin or
drops a flag, this fails and names the field.

Regenerate deliberately after an intended change, and read the diff:

    UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

import edgar_client as ec

GOLDEN = pathlib.Path(__file__).parent / "golden"
CASES = ["BYND", "TGT"]


def _screen(ticker: str) -> dict:
    return {
        "financials": ec.get_key_financials(ticker, years=5),
        "screen": ec.compute_screening_metrics(ticker, years=5),
    }


@pytest.mark.parametrize("ticker", CASES)
def test_screen_matches_golden(ticker):
    GOLDEN.mkdir(exist_ok=True)
    path = GOLDEN / f"{ticker}_screen.json"
    actual = json.loads(json.dumps(_screen(ticker), sort_keys=True))

    if os.environ.get("UPDATE_GOLDEN") or not path.exists():
        path.write_text(json.dumps(actual, indent=1, sort_keys=True))
        pytest.skip(f"golden regenerated: {path.name}")

    expected = json.loads(path.read_text())
    if actual == expected:
        return

    # Point at the field, not at a 200-line dict.
    diffs = []
    for name, exp in expected["screen"]["metrics"].items():
        act = actual["screen"]["metrics"].get(name)
        if act is None:
            diffs.append(f"metric disappeared: {name}")
        elif act["value"] != exp["value"] or act["meaningful"] != exp["meaningful"]:
            diffs.append(f"{name}: {exp['value']} (ok={exp['meaningful']}) -> "
                         f"{act['value']} (ok={act['meaningful']})")
    exp_codes = {f["code"] for f in expected["screen"]["flags"]}
    act_codes = {f["code"] for f in actual["screen"]["flags"]}
    if exp_codes - act_codes:
        diffs.append(f"flags lost: {sorted(exp_codes - act_codes)}")
    if act_codes - exp_codes:
        diffs.append(f"flags added: {sorted(act_codes - exp_codes)}")
    pytest.fail(f"{ticker} screen drifted from golden:\n  " + "\n  ".join(
        diffs or ["structural change outside metrics/flags — diff the JSON"]))
