"""Tests for the memo auditor.

This exists because the repo's central claim had a hole in it. Ratios,
meaningfulness and flags are all decided in code — and then the deliverable that
carries them was assembled by a model, with nothing in code checking that every
figure kept its source marker, that the Sources table resolved, or that a metric
marked meaningful=false was not quoted as a number anyway.

The auditor earned its place immediately: run against the two sample memos already
committed as exemplars, it found three real defects. BYND's HTML declared S2 and
never cited it (the Markdown did), and both TGT renderings declared an S4 row for
a 10-Q that no figure in the memo came from. Those are precisely the failures it
is built to catch, and they were sitting in the documents held up as correct.
"""
from __future__ import annotations

import pathlib

import pytest

from northbridge_diligence import edgar_client as ec
from northbridge_diligence.memo_audit import audit_memo

SAMPLES = pathlib.Path(__file__).resolve().parents[1] / "samples"


@pytest.mark.parametrize("ticker", ["BYND", "TGT"])
@pytest.mark.parametrize("suffix", [".md", ".html"])
def test_committed_samples_satisfy_their_own_invariants(ticker, suffix):
    """The samples are the argument. They must survive the check they advertise."""
    screen = ec.compute_screening_metrics(ticker, years=5)
    memo = (SAMPLES / f"{ticker}_screening_memo{suffix}").read_text()
    result = audit_memo(memo, screen)
    assert result["ok"], f"{ticker}{suffix}: {result['problems']}"


def test_markdown_and_html_cite_the_same_sources():
    """Two renderings of one memo drifting apart is how BYND lost its [S2].

    A reader given the HTML and a reader given the Markdown must be looking at
    the same provenance.
    """
    from northbridge_diligence.memo_audit import _markers_used, _sources_declared
    for ticker in ("BYND", "TGT"):
        md = (SAMPLES / f"{ticker}_screening_memo.md").read_text()
        html = (SAMPLES / f"{ticker}_screening_memo.html").read_text()
        assert _markers_used(md) == _markers_used(html), f"{ticker}: citations differ"
        assert _sources_declared(md) == _sources_declared(html), f"{ticker}: sources differ"


class TestCatchesWhatItClaimsTo:
    """An auditor that cannot fail is decoration. Each check is provoked."""

    @pytest.fixture
    def screen(self):
        return ec.compute_screening_metrics("BYND", years=5)

    def test_catches_a_citation_pointing_nowhere(self, screen):
        memo = "Revenue was $275.5M [S9].\n\n| Ref | Filing |\n|---|---|\n| S1 | 10-K |\n"
        codes = {p["code"] for p in audit_memo(memo, screen)["problems"]}
        assert "DANGLING_CITATION" in codes

    def test_catches_a_stale_unused_source_row(self, screen):
        memo = "Revenue was $275.5M [S1].\n\n| Ref |\n|---|\n| S1 |\n| S7 |\n"
        codes = {p["code"] for p in audit_memo(memo, screen)["problems"]}
        assert "UNUSED_SOURCE" in codes

    def test_catches_a_memo_with_no_citations_at_all(self, screen):
        # The signature of the skill not being used: prose with no provenance.
        codes = {p["code"] for p in audit_memo("Beyond Meat looks risky.", screen)["problems"]}
        assert "NO_CITATIONS" in codes

    def test_catches_an_unmeaningful_metric_quoted_as_a_number(self, screen):
        """The canonical case: debt/equity of -417.0 must never be quoted.

        It is arithmetically correct and substantively nonsense, and the memo is
        required to print the caveat instead.
        """
        unmeaningful = {n: m for n, m in screen["metrics"].items()
                        if m.get("meaningful") is False and isinstance(m.get("value"), (int, float))}
        assert unmeaningful, "BYND fixture should have an unmeaningful metric"
        name, metric = next(iter(unmeaningful.items()))
        memo = (f"Leverage sits at {metric['value']:.1f}x [S1].\n\n"
                f"| Ref |\n|---|\n| S1 |\n")
        problems = audit_memo(memo, screen)["problems"]
        assert any(p["code"] == "UNMEANINGFUL_METRIC_QUOTED" for p in problems), name

    def test_catches_a_dropped_high_severity_flag(self, screen):
        memo = "All fine here [S1].\n\n| Ref |\n|---|\n| S1 |\n"
        problems = audit_memo(memo, screen)["problems"]
        omitted = [p for p in problems if p["code"] == "FLAG_OMITTED"]
        assert omitted, "dropping every flag should be caught"

    def test_reports_what_it_does_not_check(self, screen):
        # Honesty about scope: it checks invariants, not whether the prose is good.
        result = audit_memo("x [S1]\n\n| Ref |\n|---|\n| S1 |\n", screen)
        assert "judgment" in result["not_checked"]


def test_compound_markers_are_understood():
    # The memos use [S1, S3] as well as [S1]; both halves must resolve.
    from northbridge_diligence.memo_audit import _markers_used
    assert _markers_used("a [S1, S3] b [S2]") == {"S1", "S2", "S3"}
