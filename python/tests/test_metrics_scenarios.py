from dataclasses import replace

import numpy as np
import pytest

from waterfall import columns as C
from waterfall.config import BASE_SCENARIO, BREAKEVEN_SEVERITIES, LOSS_THRESHOLD_USD, TRANCHES
from waterfall.metrics import (discount_margin, first_loss_tranche, irr_annual, most_senior_impaired,
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
    assert most_senior_impaired(s) == "none" and first_loss_tranche(s) == "none"


def test_scenario_grid_identifies_most_senior_impaired(deal):
    rows = {r["scenario"].name: r for r in run_scenarios(deal)}
    assert rows["Base"]["most_senior_impaired"] == "none"
    assert rows["Severe stress"]["most_senior_impaired"] in ("A", "B")
    assert first_loss_tranche(rows["Stress"]["summary"]) == "R"


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
            vals = [r[f"loss_pct_{x}"] for r in seq]
            assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:]))


def test_more_prepayment_shortens_wal(deal):
    from waterfall.waterfall import run_waterfall
    slow = tranche_summary(run_waterfall(deal, replace(BASE_SCENARIO, cpr=0.02)))
    fast = tranche_summary(run_waterfall(deal, replace(BASE_SCENARIO, cpr=0.30)))
    assert fast["A"]["wal_years"] < slow["A"]["wal_years"]
