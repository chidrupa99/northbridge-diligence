"""
memo_audit.py — check a finished memo against the screen it claims to describe.

The gap this closes
-------------------
This repo's argument is that whatever must be reproducible is decided in code,
not in a prompt. The deliverable format was the one place that argument did not
hold: the memo is assembled by the model, so nothing in code enforced that every
figure carries a source marker, that the Sources table is complete, or that a
metric marked `meaningful: false` is never quoted as a number. A model having an
off day could drop any of it and no test would notice.

Why this is an auditor and not a renderer
-----------------------------------------
A full renderer — screen dict in, finished HTML out — was the obvious move and is
the wrong one. The memo's value is not its table markup; it is the judgment about
what leads, which risk matters most, and what a deal lead should ask next. That
judgment is exactly the part a language model should own, and a renderer would
either strip it out (producing a rigid template nobody wants to read) or demand
the model hand over narrative strings to slot into fixed holes, which is a
renderer in name and a template in practice.

So: the model writes the memo, and code checks the invariants it must satisfy.
The division stays where the rest of the codebase puts it — code owns what must
be reproducible, the model owns what must be readable.

What it enforces
----------------
Three properties, chosen because each is robustly checkable and each corresponds
to a promise the README makes:

1. Every ``[S#]`` marker resolves to a row in the Sources table. A citation that
   points nowhere is worse than no citation: it looks like provenance.
2. No metric with ``meaningful: false`` appears as a bare number. Beyond Meat's
   debt/equity of −417.0 is the canonical case — arithmetically right,
   substantively nonsense, and the memo must print the caveat instead.
3. Every high- and medium-severity flag appears somewhere in the memo. ``flags``
   is authoritative; silently dropping one is how a screen misleads.

Deliberately not checked: whether the prose is any good, whether the right thing
leads, whether the analysis is sound. Those are judgment, and a regex asserting
them would be theatre.
"""

from __future__ import annotations

import re
from typing import Any

# `[S1]`, `[S12]`, and the compound `[S1,S3]` form the memos actually use.
_MARKER = re.compile(r"\[(S\d+(?:\s*,\s*S\d+)*)\]")
# A Sources table row opens with the ref, in Markdown (`| S1 |`) or HTML
# (`<td>S1</td>`). Matching the row start avoids counting body prose.
_SOURCE_ROW = re.compile(r"(?:^\|\s*|<td[^>]*>\s*)(S\d+)\s*(?:\||<)", re.M)


def _markers_used(memo: str) -> set[str]:
    found: set[str] = set()
    for group in _MARKER.findall(memo):
        found.update(part.strip() for part in group.split(","))
    return found


def _sources_declared(memo: str) -> set[str]:
    return set(_SOURCE_ROW.findall(memo))


def _number_forms(value: float) -> list[str]:
    """Renderings of a number a memo might plausibly use.

    Deliberately narrow. The point is to catch a model quoting −417.0 as
    "-417.0x" or "(417.0)", not to hunt every conceivable formatting — a broad
    net here produces false positives on unrelated figures, and an auditor that
    cries wolf gets switched off.
    """
    forms = []
    for text in (f"{value:.1f}", f"{value:.2f}", f"{abs(value):.1f}", f"{abs(value):.2f}"):
        forms.append(text)
        if text.endswith(".00") or text.endswith(".0"):
            forms.append(text.rstrip("0").rstrip("."))
    return list(dict.fromkeys(forms))


def audit_memo(memo: str, screen: dict[str, Any]) -> dict[str, Any]:
    """Check a memo against its screen. Returns findings; raises nothing.

    ``screen`` is a ``compute_screening_metrics`` result. Returning findings
    rather than raising keeps this usable as a soft check in a skill workflow as
    well as a hard assertion in a test.
    """
    problems: list[dict[str, str]] = []

    used, declared = _markers_used(memo), _sources_declared(memo)
    for dangling in sorted(used - declared):
        problems.append({
            "code": "DANGLING_CITATION",
            "detail": f"{dangling} is cited in the body but has no Sources row. A "
                      f"marker that resolves to nothing looks like provenance and "
                      f"is not.",
        })
    for unused in sorted(declared - used):
        problems.append({
            "code": "UNUSED_SOURCE",
            "detail": f"{unused} is listed in Sources but never cited. Either a "
                      f"figure lost its marker or the row is stale.",
        })
    if not used:
        problems.append({
            "code": "NO_CITATIONS",
            "detail": "The memo contains no source markers at all, which means the "
                      "tools were probably not used and the figures trace to nothing.",
        })

    for name, metric in (screen.get("metrics") or {}).items():
        if metric.get("meaningful") is not False:
            continue
        value = metric.get("value")
        if not isinstance(value, (int, float)):
            continue
        for form in _number_forms(float(value)):
            # Require a digit boundary so "417" does not match inside "1417".
            if re.search(rf"(?<![\d.]){re.escape(form)}(?![\d])", memo):
                problems.append({
                    "code": "UNMEANINGFUL_METRIC_QUOTED",
                    "detail": f"{name} is meaningful=false ({value}) but {form} "
                              f"appears in the memo. Print the caveat instead: "
                              f"{metric.get('caveat') or 'see the metric caveat'}",
                })
                break

    reportable = [f for f in (screen.get("flags") or [])
                  if f.get("severity") in ("high", "medium")]
    for flag in reportable:
        if flag["code"] not in memo:
            problems.append({
                "code": "FLAG_OMITTED",
                "detail": f"{flag['code']} ({flag['severity']}) is in `flags` but "
                          f"absent from the memo. flags is authoritative — every "
                          f"high and medium one belongs in Risk signals.",
            })

    return {
        "ok": not problems,
        "problems": problems,
        "checked": {
            "citations_used": len(used),
            "sources_declared": len(declared),
            "reportable_flags": len(reportable),
            "unmeaningful_metrics": sum(
                1 for m in (screen.get("metrics") or {}).values()
                if m.get("meaningful") is False
            ),
        },
        "not_checked": "Whether the prose is good, whether the right finding leads, "
                       "or whether the analysis is sound. Those are judgment, and a "
                       "regex asserting them would be theatre.",
    }
