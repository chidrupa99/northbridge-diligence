"""
Unit tests for the data layer.

The tests are organised around the ways EDGAR actually hurts you, not around the
functions: tag switches, fiscal calendars, abandoned tags, restatements, and
ratios that are arithmetically fine and analytically worthless.
"""
from __future__ import annotations

import pytest

from northbridge_diligence import edgar_client as ec


# --------------------------------------------------------------------------- #
# Company resolution
# --------------------------------------------------------------------------- #

def test_ticker_resolves_exactly():
    assert ec.resolve_company("BYND")["resolved"]["cik"] == 1655210


def test_ticker_match_is_case_insensitive():
    assert ec.resolve_company("bynd")["resolved"]["ticker"] == "BYND"


def test_ambiguous_name_returns_candidates_not_a_guess():
    res = ec.resolve_company("Bank of")
    assert res["ambiguous"] is True
    assert len(res["candidates"]) > 1


def test_unknown_company_raises_a_useful_message():
    with pytest.raises(ec.EdgarError, match="No SEC-registered company"):
        ec.resolve_company("Definitely Not A Filer Inc")


def test_data_tools_surface_ambiguity_the_same_way_resolve_does():
    """The regression this guards: a data tool that quietly picks the first
    candidate while resolve_company politely asks. One shape, one behaviour."""
    with pytest.raises(ec.AmbiguousCompany) as exc:
        ec.get_key_financials("Bank of")
    assert exc.value.payload["ambiguous"] is True
    assert exc.value.payload["candidates"]


def test_empty_query_rejected():
    with pytest.raises(ec.EdgarError):
        ec.resolve_company("   ")


# --------------------------------------------------------------------------- #
# Fetch strategy
# --------------------------------------------------------------------------- #

def test_a_full_screen_costs_two_http_calls(http_calls):
    """companyfacts, not 17 companyconcept calls. The ticker map is the second."""
    ec.compute_screening_metrics("BYND")
    facts_calls = [u for u in http_calls if "companyfacts" in u]
    assert len(facts_calls) == 1
    assert not [u for u in http_calls if "companyconcept" in u]


def test_second_call_for_the_same_company_is_served_from_cache(http_calls):
    ec.get_key_financials("BYND")
    before = len(http_calls)
    ec.compute_screening_metrics("BYND")
    assert len(http_calls) == before, "companyfacts should not be re-fetched"
    assert ec.STATS["cache_hits"] > 0


# --------------------------------------------------------------------------- #
# The tag-merge bug this refactor exists to fix
# --------------------------------------------------------------------------- #

def _facts(ticker):
    comp = ec._resolve_cik(ticker)
    return comp, ec.get_company_facts(comp["cik10"])


def test_merging_candidate_tags_beats_first_tag_wins():
    """Target reported revenue under SalesRevenueNet, then Revenues, then
    RevenueFromContractWithCustomer...; taking the first tag with any data drops
    everything the filer tagged before the switch."""
    comp, facts = _facts("TGT")
    tags = ec.CONCEPT_MAP["revenue"]

    merged, used = ec.merged_series(facts, comp["cik"], tags)
    first_tag_wins = next(
        (s for s in (ec.annual_series(facts, comp["cik"], t) for t in tags) if s), [])

    assert len(used) > 1, "fixture should exercise a mid-history tag switch"
    assert len(merged) > len(first_tag_wins)


def test_merge_respects_tag_priority_for_overlapping_years():
    comp, facts = _facts("TGT")
    tags = ec.CONCEPT_MAP["revenue"]
    merged, _ = ec.merged_series(facts, comp["cik"], tags)
    preferred = {sv.fiscal_year: sv.value
                 for sv in ec.annual_series(facts, comp["cik"], tags[0])}
    for sv in merged:
        if sv.fiscal_year in preferred:
            assert sv.value == preferred[sv.fiscal_year]


def test_merged_series_has_one_entry_per_fiscal_year():
    comp, facts = _facts("TGT")
    merged, _ = ec.merged_series(facts, comp["cik"], ec.CONCEPT_MAP["interest_expense"])
    years = [sv.fiscal_year for sv in merged]
    assert len(years) == len(set(years))
    assert years == sorted(years)


# --------------------------------------------------------------------------- #
# Fiscal calendars
# --------------------------------------------------------------------------- #

def test_january_year_end_uses_the_filers_own_label_not_the_calendar_year():
    """Target's fiscal 2009 ended 2010-01-30. Labelling by end.year would call it
    2009 as well as calling 2009-01-31 'fiscal 2009' — and one year would vanish."""
    comp, facts = _facts("TGT")
    series = {sv.period_end: sv.fiscal_year
              for sv in ec.annual_series(facts, comp["cik"], "InterestExpense")}
    assert series["2010-01-30"] == 2009
    assert series["2009-01-31"] == 2008


def test_calendar_year_end_filer_labels_normally():
    comp, facts = _facts("BYND")
    series = {sv.period_end: sv.fiscal_year
              for sv in ec.annual_series(facts, comp["cik"], "NetIncomeLoss")}
    assert series["2025-12-31"] == 2025


def test_prior_year_comparatives_extend_history_beyond_filings_on_hand():
    """One 10-K carries two prior years as comparatives; we mine them."""
    comp, facts = _facts("BYND")
    series = ec.annual_series(facts, comp["cik"], "NetIncomeLoss")
    assert len(series) >= 6


# --------------------------------------------------------------------------- #
# Period alignment — the stale-line-item trap
# --------------------------------------------------------------------------- #

GROWTH_METRICS = {"revenue_cagr", "revenue_yoy"}


def test_point_in_time_metrics_use_only_the_reference_year():
    """Margins and leverage must not mix a FY2017 numerator with FY2025 revenue.
    Growth metrics are the deliberate exception — they span the window."""
    res = ec.compute_screening_metrics("TGT")
    ref = res["as_of_fiscal_year"]
    for name, metric in res["metrics"].items():
        if name in GROWTH_METRICS:
            continue
        years = {i["fiscal_year"] for i in metric["inputs"]
                 if i["fiscal_year"] is not None}
        assert years <= {ref}, f"{name} mixed fiscal years {years}"


def test_growth_metrics_stay_inside_the_requested_window():
    res = ec.compute_screening_metrics("TGT", years=5)
    ref = res["as_of_fiscal_year"]
    for name in GROWTH_METRICS:
        for i in res["metrics"][name]["inputs"]:
            assert ref - 4 <= i["fiscal_year"] <= ref


def test_abandoned_tag_becomes_a_gap_not_a_stale_number():
    """Target stopped tagging GrossProfit after FY2017. A positional slice would
    pair FY2017 gross profit with FY2025 revenue and call it a margin."""
    res = ec.compute_screening_metrics("TGT")
    stale = res["data_quality"]["last_reported_before_reference_year"]
    assert stale.get("gross_profit") == 2017
    assert any(f["code"] == "TAG_DISCONTINUED" for f in res["flags"])


def test_gross_margin_is_derived_when_gross_profit_is_untagged():
    res = ec.compute_screening_metrics("TGT")
    gm = res["metrics"]["gross_margin"]
    assert gm["meaningful"] and 0.2 < gm["value"] < 0.4


def test_key_financials_windows_by_fiscal_year():
    res = ec.get_key_financials("TGT", years=3)
    ref = res["reference_fiscal_year"]
    for series in res["line_items"].values():
        for sv in series:
            assert ref - 2 <= sv["fiscal_year"] <= ref


# --------------------------------------------------------------------------- #
# Attribution — the product promise
# --------------------------------------------------------------------------- #

def test_every_returned_value_carries_a_resolvable_source():
    res = ec.get_key_financials("BYND")
    values = [sv for series in res["line_items"].values() for sv in series]
    assert values
    for sv in values:
        assert sv["accession"]
        assert sv["source_url"].startswith("https://www.sec.gov/Archives/")
        assert sv["period_end"] and sv["form"] and sv["xbrl_tag"]


def test_metric_inputs_are_sourced_values_not_bare_numbers():
    res = ec.compute_screening_metrics("BYND")
    for name, metric in res["metrics"].items():
        assert metric["inputs"], f"{name} has no attributable inputs"
        for sourced in metric["inputs"]:
            assert sourced["source_url"]


def test_restatement_policy_is_declared_not_implied():
    res = ec.get_key_financials("BYND")
    assert res["restatement_policy"] in ("as_last_reported", "as_originally_reported")


# --------------------------------------------------------------------------- #
# Ratio meaningfulness — decided in code, not in a prompt
# --------------------------------------------------------------------------- #

def test_negative_denominator_is_marked_unquotable():
    value, ok, caveat = ec._guarded_ratio(100.0, -2.0)
    assert value == -50.0 and ok is False and "negative" in caveat


def test_near_zero_denominator_is_marked_unquotable():
    value, ok, caveat = ec._guarded_ratio(1_000_000.0, 500.0)
    assert ok is False and "unstable" in caveat


def test_zero_denominator_returns_no_value():
    value, ok, _ = ec._guarded_ratio(100.0, 0.0)
    assert value is None and ok is False


def test_healthy_ratio_is_meaningful():
    value, ok, caveat = ec._guarded_ratio(10.0, 5.0)
    assert value == 2.0 and ok is True and caveat is None


def test_debt_to_equity_on_negative_equity_is_flagged_not_quoted():
    """The -417x case. The number exists; the guarantee is that the caller is
    told not to print it. That guarantee lives here, in code."""
    res = ec.compute_screening_metrics("BYND")
    de = res["metrics"]["debt_to_equity"]
    assert de["meaningful"] is False
    assert "negative" in de["caveat"]


def test_interest_coverage_on_operating_losses_is_not_meaningful():
    res = ec.compute_screening_metrics("BYND")
    assert res["metrics"]["interest_coverage"]["meaningful"] is False


def test_debt_to_ebitda_on_negative_ebitda_is_not_meaningful():
    res = ec.compute_screening_metrics("BYND")
    assert res["metrics"]["debt_to_ebitda"]["meaningful"] is False


# --------------------------------------------------------------------------- #
# Red flags — deterministic, so a re-run gives the same answer
# --------------------------------------------------------------------------- #

def _codes(ticker):
    return {f["code"] for f in ec.compute_screening_metrics(ticker)["flags"]}


def test_distressed_filer_raises_the_expected_flags():
    codes = _codes("BYND")
    assert {"NEGATIVE_EQUITY", "EARNINGS_QUALITY", "NEGATIVE_EBITDA",
            "REVENUE_DECLINE", "CASH_BURN"} <= codes


def test_earnings_quality_flag_catches_profit_from_outside_the_business():
    """The finding that makes this screen worth reading: FY2025 net income is
    +$219m while the operating business lost $334m."""
    flags = {f["code"]: f for f in ec.compute_screening_metrics("BYND")["flags"]}
    eq = flags["EARNINGS_QUALITY"]
    assert eq["severity"] == "high"
    assert len(eq["evidence"]) == 2
    assert all(e["source_url"] for e in eq["evidence"])


def test_healthy_filer_does_not_raise_solvency_flags():
    codes = _codes("TGT")
    assert not ({"NEGATIVE_EQUITY", "EARNINGS_QUALITY", "NEGATIVE_EBITDA"} & codes)


def test_liquidity_flag_fires_on_a_current_ratio_below_one():
    res = ec.compute_screening_metrics("TGT")
    assert res["metrics"]["current_ratio"]["value"] < 1
    assert "LIQUIDITY" in {f["code"] for f in res["flags"]}


def test_flags_are_deterministic():
    a = ec.compute_screening_metrics("BYND")["flags"]
    b = ec.compute_screening_metrics("BYND")["flags"]
    assert a == b


def test_every_flag_has_the_full_contract():
    for f in ec.compute_screening_metrics("BYND")["flags"]:
        assert f["severity"] in ("high", "medium", "info")
        assert f["code"] and f["message"]
        assert isinstance(f["evidence"], list)


def test_stale_data_flag_is_time_relative(monkeypatch):
    from datetime import date
    monkeypatch.setattr(ec, "_today", lambda: date(2028, 1, 1))
    assert "STALE_DATA" in _codes("BYND")


def test_fresh_data_raises_no_staleness_flag():
    assert "STALE_DATA" not in _codes("BYND")


# --------------------------------------------------------------------------- #
# Escape hatch + input validation
# --------------------------------------------------------------------------- #

def test_raw_tag_lookup_works():
    res = ec.get_financial_concept("BYND", "NetIncomeLoss", years=3)
    assert res["series"] and res["xbrl_tags_used"] == ["NetIncomeLoss"]


def test_friendly_metric_name_maps_to_the_tag_chain():
    res = ec.get_financial_concept("BYND", "revenue")
    assert res["tags_tried"] == ec.CONCEPT_MAP["revenue"]


def test_path_traversal_in_a_tag_is_rejected_before_it_reaches_a_url():
    with pytest.raises(ec.EdgarError, match="valid US-GAAP tag"):
        ec.get_financial_concept("BYND", "../../../etc/passwd")


def test_unknown_but_well_formed_tag_returns_an_empty_series_not_an_error():
    res = ec.get_financial_concept("BYND", "SomeTagNobodyReports")
    assert res["series"] == [] and "No annual data" in res["note"]


# --------------------------------------------------------------------------- #
# Item 1A extraction (pure text, no filing download)
# --------------------------------------------------------------------------- #

TENK = """
Table of Contents
Item 1A. Risk Factors 14
Item 1B. Unresolved Staff Comments 40
PART I
Item 1A. Risk Factors
Our business faces substantial competition and our margins may decline.
Item 1B. Unresolved Staff Comments
None.
"""


def test_item_1a_extraction_skips_the_table_of_contents():
    section = ec.extract_item_1a(TENK)
    assert "substantial competition" in section
    assert "Unresolved Staff Comments\nNone" not in section


def test_item_1a_extraction_fails_soft():
    assert ec.extract_item_1a("A filing with no risk factors heading at all.") is None


# A 10-K that cross-references Item 1A *after* the section itself — the shape of
# Dollar General's FY2025 filing, where Item 1C points back at the risk factors.
# Taking the last heading match landed on that cross-reference and returned 2,958
# characters of audit-committee text, reported as a successful extraction.
TENK_LATE_CROSSREF = """
Table of Contents
Item 1A. Risk Factors 14
Item 1B. Unresolved Staff Comments 40
Item 1C. Cybersecurity 41
PART I
Item 1A. Risk Factors
Our business faces substantial competition and our margins may decline.
""" + ("Risk narrative continues at length. " * 60) + """
Item 1B. Unresolved Staff Comments
None.
Item 1C. Cybersecurity
See Item 1A. Risk Factors for additional information regarding cybersecurity
risks that could impact our business. The Audit Committee oversees this process
and receives quarterly reports from management on cyber risk posture.
"""


def test_item_1a_extraction_ignores_a_cross_reference_after_the_section():
    section = ec.extract_item_1a(TENK_LATE_CROSSREF)
    assert section is not None
    assert section.startswith("Item 1A. Risk Factors")
    assert "substantial competition" in section
    # The tell for the old bug: the returned text began inside Item 1C.
    assert "Audit Committee oversees" not in section


def test_item_1a_extraction_returns_the_whole_section_not_a_fragment():
    section = ec.extract_item_1a(TENK_LATE_CROSSREF)
    assert len(section) > 1000


def test_mdna_extraction_is_bounded_by_item_7a():
    text = """
    Table of Contents
    Item 7. Management's Discussion and Analysis 25
    Item 7A. Quantitative and Qualitative Disclosures 40
    Investors should read Item 7. Management's Discussion and Analysis together
    with the risk factors described elsewhere in this report.
    Item 7. Management's Discussion and Analysis
    Net sales increased twelve percent driven by new store openings.
    """ + ("Discussion continues. " * 60) + """
    Item 7A. Quantitative and Qualitative Disclosures
    Interest rate risk is managed centrally.
    """
    section = ec.extract_section(text, "mdna")
    assert "Net sales increased" in section
    # Anchoring on the forward-looking cross-reference would pull in the line
    # above the heading; over-running would pull in Item 7A.
    assert "Investors should read" not in section
    assert "Interest rate risk" not in section


def test_short_cross_reference_section_is_still_extracted():
    # Dollar General satisfies Item 3 with one sentence pointing into the notes.
    # That is a real section, not a failed match.
    text = """
    Item 3. Legal Proceedings 20
    Item 4. Mine Safety Disclosures 21
    Item 3. Legal Proceedings
    The information contained in Note 7 to the consolidated financial statements
    under the heading "Legal proceedings" contained in Part II, Item 8 of this
    report is incorporated herein by this reference.
    Item 4. Mine Safety Disclosures
    Not applicable.
    """
    section = ec.extract_section(text, "legal_proceedings")
    assert section is not None
    assert "incorporated herein by this reference" in section
    assert "Not applicable" not in section


def test_unknown_section_name_is_rejected():
    with pytest.raises(ec.EdgarError):
        ec.extract_section("some text", "item_99_nonexistent")


# --------------------------------------------------------------------------- #
# Disclosure signals (EDGAR full-text search)
#
# The failure this whole area guards against: reporting "absent" when the
# language is actually there. Absence is written into the memo as a finding, so a
# false negative is a false statement to the deal team -- worse than a noisy hit,
# which the verification step catches.
# --------------------------------------------------------------------------- #

def test_going_concern_absent_for_a_company_that_has_none():
    res = ec.scan_disclosure_signals("BYND")
    signal = next(s for s in res["signals"] if s["signal"] == "going_concern")
    assert signal["assessment"] == "absent"
    assert signal["documents_matched"] == 0


def test_language_in_every_annual_report_is_called_boilerplate():
    # Beyond Meat matches "material weakness" in all seven of its 10-Ks, yet its
    # Item 9A concludes controls were effective -- every hit is the auditor
    # describing its own testing methodology. Reporting that as a control failure
    # is exactly the mistake this classification exists to prevent.
    res = ec.scan_disclosure_signals("BYND")
    signal = next(s for s in res["signals"] if s["signal"] == "material_weakness")
    assert signal["annual_reports_matched"] == signal["annual_reports_on_file"]
    assert signal["assessment"] == "likely_boilerplate"


def test_language_present_in_only_some_years_is_flagged_for_reading():
    # Concentration language that comes and goes is the higher-signal case.
    res = ec.scan_disclosure_signals("BYND")
    signal = next(s for s in res["signals"]
                  if s["signal"] == "customer_concentration")
    assert 0 < signal["annual_reports_matched"] < signal["annual_reports_on_file"]
    assert signal["assessment"] == "changed_over_time"


def test_annual_match_count_is_filings_not_documents():
    # EDGAR's `total` counts matching documents; a 10-K plus two matching
    # exhibits is three. Compared against a count of filings that produced
    # "20 of 11 annual reports" before the units were reconciled.
    res = ec.scan_disclosure_signals("TGT")
    for signal in res["signals"]:
        assert signal["annual_reports_matched"] <= signal["annual_reports_on_file"]


def test_healthy_retailer_shows_no_distress_language():
    res = ec.scan_disclosure_signals("TGT")
    assert "going_concern" in res["summary"]["absent"]
    assert "customer_concentration" in res["summary"]["absent"]


def test_every_signal_carries_severity_and_rationale():
    # The model narrates these; it is not asked to decide which matter.
    for signal in ec.scan_disclosure_signals("BYND")["signals"]:
        assert signal["severity"]
        assert signal["why_it_matters"]
        assert signal["assessment_note"]


def test_present_signals_link_to_the_filings_to_read():
    res = ec.scan_disclosure_signals("BYND")
    present = [s for s in res["signals"] if s["present"]]
    assert present
    for signal in present:
        assert signal["examples"]
        assert all(e["url"] and e["accession"] for e in signal["examples"])


def test_result_tells_the_model_a_hit_is_not_a_finding():
    res = ec.scan_disclosure_signals("BYND")
    assert "not that the condition applies" in res["how_to_use"]
    # Disclosure signals stay out of `flags`, which is reserved for red flags
    # code can verify arithmetically.
    assert "flags" in res["how_to_use"]


def test_curated_phrases_stay_short_enough_to_match_real_filings():
    # The first version used the full formal wording -- "material weakness in our
    # internal control over financial reporting" -- which matched 0 Target
    # filings while "material weakness" matched 23. Length is the tell.
    for name, spec in ec.DISCLOSURE_PACKS.items():
        assert len(spec["phrase"].split()) <= 5, f"{name} phrase is over-specific"
