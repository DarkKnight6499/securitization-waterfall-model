from dataclasses import replace

import numpy as np
import pytest

from waterfall import columns as C
from waterfall.config import BASE_SCENARIO, BREAKEVEN_SEVERITIES, LOSS_THRESHOLD_USD, TRANCHES
from waterfall.metrics import (discount_margin, first_shortfall_tranche, irr_annual, most_junior_writedown,
                               most_senior_shortfall, most_senior_writedown, principal_subordination,
                               principal_window, tranche_cash_flows, tranche_summary, wal_years)
from waterfall.scenarios import breakeven_cdr, breakeven_table, loss_at_cdr, loss_grid, run_scenarios


def test_irr_of_par_bond_equals_coupon():
    coupon = 0.06
    cf = np.array([-100.0] + [100 * coupon / 12] * 59 + [100 + 100 * coupon / 12])
    assert irr_annual(cf) == pytest.approx(coupon, abs=1e-9)


def test_irr_nan_when_no_sign_change():
    assert np.isnan(irr_annual(np.array([-100.0, 0.0, 0.0])))


def test_wal_of_bullet_is_its_maturity():
    prin = np.zeros(37)
    prin[24] = 100.0
    assert wal_years(prin, np.arange(37, dtype=float)) == pytest.approx(2.0)


def test_wal_of_two_equal_payments():
    prin = np.zeros(37)
    prin[12], prin[36] = 50.0, 50.0
    assert wal_years(prin, np.arange(37, dtype=float)) == pytest.approx(2.0)


def test_principal_window():
    prin = np.zeros(10)
    prin[3], prin[7] = 5.0, 5.0
    assert principal_window(prin) == (3, 7)
    assert principal_window(np.zeros(5)) == (None, None)


def test_discount_margin_of_unimpaired_floater_equals_its_margin(base, deal):
    cf = tranche_cash_flows(base, "A")["cf"]
    assert discount_margin(cf, base[C.FWD]) == pytest.approx(deal.margin_a, abs=1e-9)
    cf_b = tranche_cash_flows(base, "B")["cf"]
    assert discount_margin(cf_b, base[C.FWD]) == pytest.approx(deal.margin_b, abs=1e-9)


def test_fixed_tranche_yield_equals_coupon_when_unimpaired(base, deal):
    summ = tranche_summary(base)
    assert summ["C"]["yield_at_par"] == pytest.approx(deal.fixed_c, abs=1e-8)


def test_summary_base_is_clean_and_ordered(base):
    s = tranche_summary(base)
    assert all(not s[x]["takes_loss"] for x in TRANCHES)
    assert s["A"]["wal_years"] < s["B"]["wal_years"] < s["C"]["wal_years"]
    assert s["A"]["window_last"] <= s["B"]["window_first"]
    assert most_senior_writedown(s) == "none" and most_junior_writedown(s) == "none"
    assert most_senior_shortfall(s) == "none" and first_shortfall_tranche(s) == "none"


def test_scenario_grid_labels_writedown_only_and_shortfall(deal):
    rows = {r["scenario"].name: r for r in run_scenarios(deal)}
    assert rows["Base"]["labels"][C.WD_MOST_SENIOR] == "none"
    assert rows["Severe stress"]["labels"][C.WD_MOST_SENIOR] in ("A", "B")
    assert rows["Stress"]["labels"][C.WD_MOST_JUNIOR] == "R"
    assert rows["Stress"]["labels"][C.SHORT_FIRST] == "R"


def test_deferred_interest_is_visible_when_write_downs_are_not(deal):
    # Rate shock: the write-down-only label names R, but Class C also defers interest at some point
    row = {r["scenario"].name: r for r in run_scenarios(deal)}["Rate shock +300bp"]
    summ = row["summary"]
    assert most_senior_writedown(summ) == "R"
    assert summ["C"]["writedown"] == 0 and summ["C"]["unpaid_interest_peak"] > 1e6
    assert summ["C"]["any_shortfall"] and most_senior_shortfall(summ) == "C"
    assert first_shortfall_tranche(summ) == "R"


def test_ending_unpaid_interest_reported_for_notes(deal):
    row = {r["scenario"].name: r for r in run_scenarios(deal)}["Severe stress"]
    end = row["result"][C.tr("C", C.INT_SHORT)][-1]
    assert row["summary"]["C"]["unpaid_interest_end"] == pytest.approx(end) and end > 0
    assert row["summary"]["R"]["unpaid_interest_end"] == 0


def test_loss_grid_carries_unpaid_interest_columns(deal):
    rows = loss_grid(deal)
    assert all(f"unpaid_interest_end_{x}" in rows[0] for x in TRANCHES)
    assert C.SHORT_FIRST in rows[0] and C.WD_MOST_SENIOR in rows[0]


def test_principal_subordination_excludes_reserve(deal):
    sub = principal_subordination(deal)
    assert sub["A"] == pytest.approx(0.25) and sub["B"] == pytest.approx(0.15) and sub["C"] == pytest.approx(0.075)
    assert deal.par("R") / deal.pool_balance == pytest.approx(0.0825)  # includes the reserve, so not the credit enhancement


def test_breakeven_ordering_and_boundary(deal):
    be = {x: breakeven_cdr(deal, x) for x in TRANCHES}
    assert be["A"] > be["B"] > be["C"] > be["R"] > 0
    for x in TRANCHES:
        assert loss_at_cdr(deal, BASE_SCENARIO, x, be[x] * 0.999) <= LOSS_THRESHOLD_USD
        assert loss_at_cdr(deal, BASE_SCENARIO, x, be[x] * 1.01) > LOSS_THRESHOLD_USD


def test_higher_severity_lowers_breakeven(deal):
    table = breakeven_table(deal, BREAKEVEN_SEVERITIES)
    lo, hi = BREAKEVEN_SEVERITIES
    for x in TRANCHES:
        assert table[hi][x] < table[lo][x]


def test_loss_grid_monotone_in_cdr(deal):
    rows = loss_grid(deal)
    for sev in {r["severity"] for r in rows}:
        seq = [r for r in rows if r["severity"] == sev]
        for x in TRANCHES:
            # R is checked up to 30% CDR: beyond it write-downs retire the notes early and leftover reserve is released to R
            vals = [r[f"loss_pct_{x}"] for r in seq if x != "R" or r["cdr"] <= 0.30]
            assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:]))


def test_more_prepayment_shortens_wal(deal):
    from waterfall.waterfall import run_waterfall
    slow = tranche_summary(run_waterfall(deal, replace(BASE_SCENARIO, cpr=0.02)))
    fast = tranche_summary(run_waterfall(deal, replace(BASE_SCENARIO, cpr=0.30)))
    assert fast["A"]["wal_years"] < slow["A"]["wal_years"]
