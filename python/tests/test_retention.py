from dataclasses import replace

import numpy as np
import pytest

from waterfall import columns as C
from waterfall.config import BASE_SCENARIO, NOTES, STRESS_SCENARIO, TRANCHES
from waterfall.metrics import tranche_cash_flows
from waterfall.metrics import pv_at_margin
from waterfall.retention import (EU_FIRST_LOSS, EU_VERTICAL, OPTIONS, RET_CLASSES, RR_HORIZONTAL, RR_LSHAPED,
                                 RR_VERTICAL, fair_values, financing_view, retained_cash_flows, retention_amounts,
                                 retention_fractions, retention_report, retention_structure, split_residual)
from waterfall.waterfall import run_waterfall


@pytest.fixture(scope="module")
def fv(base):
    return fair_values(base)


def test_vertical_is_five_percent_of_every_class(deal, fv):
    f = retention_fractions(deal, fv)[RR_VERTICAL]
    assert all(f[x] == pytest.approx(0.05) for x in (*NOTES, "R1"))
    am = retention_amounts(deal, fv)["options"][RR_VERTICAL]
    assert am["retained_par"] == pytest.approx(0.05 * sum(deal.par(x) for x in TRANCHES))


def test_horizontal_retains_a_separate_first_loss_subclass_sized_to_five_percent_of_fair_value(deal, fv):
    am = retention_amounts(deal, fv)["options"][RR_HORIZONTAL]
    f = am["fractions"]
    assert (f["A"], f["B"], f["C"], f["R2"]) == (0, 0, 0, 0) and f["R1"] == 1
    assert am["retained_fair_value"] == pytest.approx(0.05 * sum(fv.values()))
    assert am["r2_par"] == pytest.approx(fv["R"] - 0.05 * sum(fv.values()))
    assert am["retained_par"] == pytest.approx(deal.par("R") - am["r2_par"])
    assert am["regulatory_measure"] == pytest.approx(0.05)


def test_horizontal_never_holds_a_partial_share_of_a_class_shared_with_third_parties(deal, fv):
    # 17 CFR 246.2: a shortfall must reduce the horizontal interest before any other ABS interest,
    # so every class is either held whole (R1) or not held at all
    f = retention_fractions(deal, fv)[RR_HORIZONTAL]
    assert all(v in (0.0, 1.0) for v in f.values())


def test_horizontal_reaches_into_whole_junior_notes_when_residual_is_small(deal):
    small = replace(deal, bal_c=55_000_000.0)  # residual par falls to 8m
    fvs = fair_values(run_waterfall(small, BASE_SCENARIO))
    st = retention_structure(small, fvs)[RR_HORIZONTAL]
    f = st["fractions"]
    assert f["R1"] == 1 and f["C"] == 1 and f["R2"] == 0 and st["r2_par"] == 0
    assert all(v in (0.0, 1.0) for v in f.values())
    am = retention_amounts(small, fvs)["options"][RR_HORIZONTAL]
    assert am["retained_fair_value"] >= 0.05 * sum(fvs.values())


def test_l_shape_vertical_plus_horizontal_totals_five_percent_on_the_regulatory_measure(deal, fv):
    opt = retention_amounts(deal, fv)["options"][RR_LSHAPED]
    assert opt["regulatory_measure"] == pytest.approx(0.05)  # 246.4(a)(3): vertical percentage plus horizontal FV percentage
    total = sum(fv.values())
    assert opt["retained_fair_value"] / total == pytest.approx(0.05)  # no double count of the R1 slice
    assert opt["horizontal_fair_value"] == pytest.approx(0.025 * total)
    assert opt["fractions"]["R1"] * (fv["R"] - opt["r2_par"]) == pytest.approx(0.025 / 0.975 * total)
    f = opt["fractions"]
    assert all(f[x] >= deal.lshape_vertical - 1e-12 for x in (*NOTES, "R2")) and f["R1"] == 1


def test_r2_is_paid_before_r1_so_shortfalls_hit_the_retained_subclass_first(deal, fv):
    st = retention_structure(deal, fv)[RR_HORIZONTAL]
    for scen in (BASE_SCENARIO, STRESS_SCENARIO):
        res = run_waterfall(deal, scen)
        split = split_residual(res, st["r2_par"])
        cash = tranche_cash_flows(res, "R")["total"]
        assert np.allclose(split["R1"][1:] + split["R2"][1:], cash[1:])
        assert (split["R1"][1:] >= -1e-9).all() and (split["R2"][1:] >= -1e-9).all()
        outstanding = split["r2_balance"][1:] > 0.005
        assert np.allclose(split["R1"][1:][outstanding], 0.0)  # R1 gets nothing while R2 is unpaid


def test_stress_loses_the_retained_first_loss_subclass_before_the_sold_subclass(deal, fv):
    st = retention_structure(deal, fv)[RR_HORIZONTAL]
    res = run_waterfall(deal, STRESS_SCENARIO)
    split = split_residual(res, st["r2_par"])
    loss_r1 = 1 - split["R1"][1:].sum() / -split["R1"][0]
    loss_r2 = 1 - split["R2"][1:].sum() / -split["R2"][0]
    assert loss_r1 > loss_r2 >= 0
    assert loss_r1 > 0.99  # the whole first-loss piece is gone in this scenario


def test_sold_subclass_is_worth_par_in_the_base_case_so_r1_fair_value_meets_the_requirement(deal, fv, base):
    st = retention_structure(deal, fv)[RR_HORIZONTAL]
    split = split_residual(base, st["r2_par"])
    margin = deal.fv_margins[-1]
    assert pv_at_margin(split["R2"], base[C.FWD], margin) == pytest.approx(st["r2_par"], rel=1e-9)
    fv_r1 = pv_at_margin(split["R1"], base[C.FWD], margin)
    assert fv_r1 == pytest.approx(fv["R"] - st["r2_par"], rel=1e-9)
    assert fv_r1 >= 0.05 * sum(fv.values()) - 1e-6


def test_eu_vertical_respects_sold_tranche_set(deal, fv):
    only_notes = replace(deal, eu_sold=("A", "B", "C"))
    f = retention_fractions(only_notes, fv)[EU_VERTICAL]
    assert f["R1"] == 0 and f["A"] == pytest.approx(0.05)


def test_eu_first_loss_retains_whole_residual_when_it_exceeds_five_percent(deal, fv):
    opt = retention_amounts(deal, fv)["options"][EU_FIRST_LOSS]
    assert opt["fractions"]["R1"] == 1 and opt["fractions"]["C"] == 0
    assert opt["retained_par"] >= 0.05 * deal.pool_balance


def test_eu_first_loss_adds_next_tranche_when_residual_is_under_five_percent(deal):
    small = replace(deal, bal_c=45_000_000.0)
    fvs = fair_values(run_waterfall(small, BASE_SCENARIO))
    opt = retention_amounts(small, fvs)["options"][EU_FIRST_LOSS]
    assert opt["fractions"]["R1"] == 1 and opt["fractions"]["C"] == 1
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
    expected = sum(0.05 * tranche_cash_flows(base, x)["cf"] for x in TRANCHES)  # R1 is the whole R here
    assert np.allclose(cf, expected)


def test_stress_lowers_retained_return_for_every_option(deal, fv, base):
    stress = run_waterfall(deal, STRESS_SCENARIO)
    st = retention_structure(deal, fv)
    rb, rs = retention_report(base, st), retention_report(stress, st)
    for o in OPTIONS:
        assert rs[o]["total_cash"] < rb[o]["total_cash"]
        assert np.isnan(rs[o]["yield_at_cost"]) or rs[o]["yield_at_cost"] < rb[o]["yield_at_cost"]  # nan: no cash back


def test_financing_loan_roll_forward(deal, fv, base):
    stress = run_waterfall(deal, STRESS_SCENARIO)
    for res in (base, stress):
        for o, s_ in retention_structure(deal, fv).items():
            fin = financing_view(res, s_["fractions"], s_["r2_par"])
            bal, pay, intr = fin["loan_balance"], fin["loan_payment"], fin["loan_interest"]
            assert (bal >= -1e-6).all()
            assert bal[-1] == pytest.approx(fin["advance"] + intr.sum() - pay.sum(), abs=1e-4)
            cf = retained_cash_flows(res, s_["fractions"], s_["r2_par"])
            assert (pay[1:] <= cf[1:] + 1e-9).all()


def test_financing_horizontal_not_repaid_under_stress_but_repaid_in_base(deal, fv, base):
    stress = run_waterfall(deal, STRESS_SCENARIO)
    s_ = retention_structure(deal, fv)[RR_HORIZONTAL]
    fb = financing_view(base, s_["fractions"], s_["r2_par"])
    fs = financing_view(stress, s_["fractions"], s_["r2_par"])
    assert fb["repaid_month"] is not None
    assert fs["unpaid_at_horizon"] > 0
    assert fs["pv_coverage"] < fb["pv_coverage"]


def test_advance_is_weighted_by_class_advance_rates(deal, fv):
    f = retention_fractions(deal, fv)[RR_VERTICAL]
    expected = sum(0.05 * deal.par(x) * a for x, a in zip(TRANCHES, deal.advance_rates))
    fin = financing_view(run_waterfall(deal, BASE_SCENARIO), f)
    assert fin["advance"] == pytest.approx(expected)


def test_retention_sizing_is_fixed_at_closing_not_rerun_under_stress(deal, base):
    # sizing depends on base-case fair values only; the carve-out would differ if it were re-run on stress values
    fv_base = fair_values(base)
    fv_stress = fair_values(run_waterfall(deal, STRESS_SCENARIO))
    assert fv_stress["R"] < fv_base["R"]
    assert (retention_structure(deal, fv_base)[RR_HORIZONTAL]["r2_par"]
            != retention_structure(deal, fv_stress)[RR_HORIZONTAL]["r2_par"])
    assert C.PERIOD in base


def test_every_option_has_a_fraction_for_every_retention_class(deal, fv):
    for s_ in retention_structure(deal, fv).values():
        assert set(s_["fractions"]) == set(RET_CLASSES)
