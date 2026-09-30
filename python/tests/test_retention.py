from dataclasses import replace

import numpy as np
import pytest

from waterfall import columns as C
from waterfall.config import BASE_SCENARIO, STRESS_SCENARIO, TRANCHES
from waterfall.metrics import tranche_cash_flows
from waterfall.retention import (EU_FIRST_LOSS, EU_VERTICAL, OPTIONS, RR_HORIZONTAL, RR_LSHAPED, RR_VERTICAL,
                                 fair_values, financing_view, retained_cash_flows, retention_amounts,
                                 retention_fractions, retention_report)
from waterfall.waterfall import run_waterfall


@pytest.fixture(scope="module")
def fv(base):
    return fair_values(base)


def test_vertical_is_five_percent_of_every_class(deal, fv):
    f = retention_fractions(deal, fv)[RR_VERTICAL]
    assert all(f[x] == pytest.approx(0.05) for x in TRANCHES)
    am = retention_amounts(deal, fv)["options"][RR_VERTICAL]
    assert am["retained_par"] == pytest.approx(0.05 * sum(deal.par(x) for x in TRANCHES))


def test_horizontal_is_five_percent_of_fair_value_of_all_interests(deal, fv):
    am = retention_amounts(deal, fv)
    assert am["options"][RR_HORIZONTAL]["retained_fair_value"] == pytest.approx(0.05 * sum(fv.values()))
    f = am["options"][RR_HORIZONTAL]["fractions"]
    assert f["A"] == f["B"] == f["C"] == 0 and 0 < f["R"] <= 1


def test_horizontal_reaches_into_junior_notes_when_residual_is_small(deal):
    small = replace(deal, bal_c=55_000_000.0)  # residual par falls to 8m
    base = run_waterfall(small, BASE_SCENARIO)
    fvs = fair_values(base)
    f = retention_fractions(small, fvs)[RR_HORIZONTAL]
    assert f["R"] == pytest.approx(1.0) and f["C"] > 0
    assert retention_amounts(small, fvs)["options"][RR_HORIZONTAL]["retained_fair_value"] == pytest.approx(
        0.05 * sum(fvs.values()))


def test_l_shape_vertical_plus_horizontal_totals_five_percent(deal, fv):
    opt = retention_amounts(deal, fv)["options"][RR_LSHAPED]
    assert opt["fv_pct_of_all_interests"] == pytest.approx(0.05)
    assert all(opt["fractions"][x] >= deal.lshape_vertical - 1e-12 for x in TRANCHES)


def test_eu_vertical_respects_sold_tranche_set(deal, fv):
    only_notes = replace(deal, eu_sold=("A", "B", "C"))
    f = retention_fractions(only_notes, fv)[EU_VERTICAL]
    assert f["R"] == 0 and f["A"] == pytest.approx(0.05)


def test_eu_first_loss_retains_whole_residual_when_it_exceeds_five_percent(deal, fv):
    opt = retention_amounts(deal, fv)["options"][EU_FIRST_LOSS]
    assert opt["fractions"]["R"] == 1 and opt["fractions"]["C"] == 0
    assert opt["retained_par"] >= 0.05 * deal.pool_balance


def test_eu_first_loss_adds_next_tranche_when_residual_is_under_five_percent(deal):
    small = replace(deal, bal_c=45_000_000.0)
    fvs = fair_values(run_waterfall(small, BASE_SCENARIO))
    opt = retention_amounts(small, fvs)["options"][EU_FIRST_LOSS]
    assert opt["fractions"]["R"] == 1 and opt["fractions"]["C"] == 1
    assert opt["retained_par"] >= 0.05 * small.pool_balance


def test_us_horizontal_uses_fair_value_and_eu_uses_nominal(deal, fv):
    extra = retention_amounts(deal, fv)["extra"]
    assert extra["us_min_horizontal_fair_value"] == pytest.approx(0.05 * sum(fv.values()))
    assert extra["eu_required_nominal_of_pool"] == pytest.approx(0.05 * deal.pool_balance)


def test_fair_values_near_par_for_notes_priced_at_par_margin(fv, deal):
    assert fv["A"] == pytest.approx(deal.par("A"), rel=1e-6)
    assert fv["B"] < deal.par("B")  # assumed margin above coupon margin prices B below par


def test_vertical_retained_cash_is_five_percent_of_each_tranche(base, deal, fv):
    f = retention_fractions(deal, fv)[RR_VERTICAL]
    cf = retained_cash_flows(base, f)
    expected = sum(0.05 * tranche_cash_flows(base, x)["cf"] for x in TRANCHES)
    assert np.allclose(cf, expected)


def test_stress_lowers_retained_yield_for_every_option(deal, fv, base):
    stress = run_waterfall(deal, STRESS_SCENARIO)
    fracs = {o: f for o, f in retention_fractions(deal, fv).items()}
    rb, rs = retention_report(base, fracs), retention_report(stress, fracs)
    for o in OPTIONS:
        assert rs[o]["yield_at_cost"] < rb[o]["yield_at_cost"]


def test_financing_loan_roll_forward(deal, fv, base):
    stress = run_waterfall(deal, STRESS_SCENARIO)
    for res in (base, stress):
        for o, f in retention_fractions(deal, fv).items():
            fin = financing_view(res, f)
            bal, pay, intr = fin["loan_balance"], fin["loan_payment"], fin["loan_interest"]
            assert (bal >= -1e-6).all()
            assert bal[-1] == pytest.approx(fin["advance"] + intr.sum() - pay.sum(), abs=1e-4)
            cf = retained_cash_flows(res, f)
            assert (pay[1:] <= cf[1:] + 1e-9).all()


def test_financing_horizontal_not_repaid_under_stress_but_repaid_in_base(deal, fv, base):
    stress = run_waterfall(deal, STRESS_SCENARIO)
    f = retention_fractions(deal, fv)[RR_HORIZONTAL]
    assert financing_view(base, f)["repaid_month"] is not None
    assert financing_view(stress, f)["unpaid_at_horizon"] > 0
    assert financing_view(stress, f)["pv_coverage"] < financing_view(base, f)["pv_coverage"]


def test_advance_is_weighted_by_class_advance_rates(deal, fv):
    f = retention_fractions(deal, fv)[RR_VERTICAL]
    expected = sum(0.05 * deal.par(x) * a for x, a in zip(TRANCHES, deal.advance_rates))
    fin = financing_view(run_waterfall(deal, BASE_SCENARIO), f)
    assert fin["advance"] == pytest.approx(expected)


def test_retention_sizing_is_fixed_at_closing_not_rerun_under_stress(deal, base):
    # sizing depends on base-case fair values only; the stress run must not change fractions
    fv_base = fair_values(base)
    fv_stress = fair_values(run_waterfall(deal, STRESS_SCENARIO))
    assert fv_stress["R"] < fv_base["R"]
    assert retention_fractions(deal, fv_base)[RR_HORIZONTAL]["R"] != retention_fractions(deal, fv_stress)[RR_HORIZONTAL]["R"]
    assert C.PERIOD in base
