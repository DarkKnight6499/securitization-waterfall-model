from dataclasses import replace

import numpy as np
import pytest

from waterfall import columns as C
from waterfall.checks import run_checks
from waterfall.config import BASE_SCENARIO, NOTES, SCENARIOS
from waterfall.waterfall import run_waterfall

SEVERE = [s for s in SCENARIOS if s.name == "Severe stress"][0]
STRESS = [s for s in SCENARIOS if s.name == "Stress"][0]
RATE_SHOCK = [s for s in SCENARIOS if s.name == "Rate shock +300bp"][0]


@pytest.mark.parametrize("scen", SCENARIOS, ids=lambda s: s.name)
def test_all_integrity_checks_pass(runs, scen):
    chk = run_checks(runs[scen.name])
    assert chk["passed"], chk


@pytest.mark.parametrize("scen", SCENARIOS, ids=lambda s: s.name)
def test_notes_never_paid_more_than_collateral_cash_plus_reserve_draw(runs, scen):
    r = runs[scen.name]
    paid = r[C.NOTES_PAID_TOTAL] + r[C.FEE_PAID]
    assert (paid <= r[C.POOL_CASH] + r[C.RES_DRAW] + 1e-6).all()


@pytest.mark.parametrize("scen", SCENARIOS, ids=lambda s: s.name)
def test_principal_paid_plus_losses_equals_original_balance(runs, deal, scen):
    r = runs[scen.name]
    for x in NOTES:
        total = r[C.tr(x, C.PRIN)].sum() + r[C.tr(x, C.WD)].sum() + r[C.tr(x, C.END)][-1]
        assert total == pytest.approx(deal.par(x), abs=1e-4)


@pytest.mark.parametrize("scen", SCENARIOS, ids=lambda s: s.name)
def test_cash_conservation_each_period(runs, scen):
    assert np.abs(runs[scen.name][C.CASH_CHECK]).max() < 1e-6


def test_no_negative_balances_or_payments(runs):
    for r in runs.values():
        for x in NOTES:
            assert (r[C.tr(x, C.END)] >= -1e-6).all()
            assert (r[C.tr(x, C.PRIN)] >= -1e-6).all()
            assert (r[C.tr(x, C.INT_PAID)] >= -1e-6).all()
        assert (r[C.RES_END] >= -1e-6).all()
        assert (r[C.RESID_CASH] >= -1e-6).all()


def test_base_has_no_breach_and_no_loss(base):
    assert base[C.BREACH_ANY].sum() == 0
    assert all(base[C.tr(x, C.WD)].sum() < 1e-6 for x in NOTES)


def test_sequential_mode_pays_b_only_after_a_retired(base):
    a_still_outstanding = base[C.tr("A", C.END)] > 0.005
    assert base[C.tr("B", C.REG)][a_still_outstanding].sum() == pytest.approx(0, abs=1e-6)


def test_pro_rata_pays_b_while_a_outstanding(deal):
    r = run_waterfall(replace(deal, principal_mode="pro_rata"), BASE_SCENARIO)
    a_out = r[C.tr("A", C.BEG)] > 0.005
    assert r[C.tr("B", C.REG)][a_out].sum() > 0
    assert run_checks(r)["passed"]


def test_pro_rata_reverts_to_sequential_after_breach(deal):
    r = run_waterfall(replace(deal, principal_mode="pro_rata"), STRESS)
    idx = np.where(r[C.BREACH_ANY] == 1)[0]
    assert len(idx) > 0
    assert r[C.SEQ_FLAG][idx[0] + 1] == 1
    assert run_checks(r)["passed"]


def test_pro_rata_switch_latches_after_breach_even_when_tests_cure(deal):
    r = run_waterfall(replace(deal, principal_mode="pro_rata"), RATE_SHOCK)
    breach = r[C.BREACH_ANY]
    first = int(np.where(breach == 1)[0][0])
    cured = [t for t in range(first + 1, len(breach)) if breach[t] == 0]
    assert cured, "scenario must breach and then cure for this test to mean anything"
    assert (r[C.SEQ_FLAG][first + 1:] == 1).all()
    assert (r[C.SEQ_FLAG][1:first + 1] == 0).all()
    assert (np.diff(r[C.SEQ_FLAG]) >= 0).all()


def test_reserve_draw_pays_b_interest_and_is_never_swept_into_turbo(deal):
    # regression: the draw sized for B interest used to be swept into Class A turbo principal
    r = run_waterfall(deal, RATE_SHOCK)
    months = [t for t in range(1, len(r[C.RES_DRAW])) if r[C.RES_DRAW][t] > 0]
    assert len(months) >= 5
    for t in months:
        assert r[C.tr("A", C.BREACH)][t] == 1
        assert r[C.tr("B", C.INT_PAID)][t] > 0
        assert r[C.tr("B", C.INT_SHORT)][t] == pytest.approx(0, abs=1e-6)
        assert r[C.RES_DRAW][t] == pytest.approx(r[C.tr("B", C.INT_PAID)][t])
        # turbo is funded by collections left after fees and Class A interest, nothing more
        assert r[C.TURBO_TOTAL][t] == pytest.approx(r[C.INT_COLL][t] - r[C.FEE_PAID][t] - r[C.tr("A", C.INT_PAID)][t], abs=1e-6)


def test_reserve_size_does_not_change_class_a_turbo(deal):
    # a draw is never swept into the Class A turbo, so removing the reserve leaves turbo step 1 untouched
    with_reserve = run_waterfall(deal, RATE_SHOCK)
    no_reserve = run_waterfall(replace(deal, reserve_initial=0.0, reserve_target=0.0), RATE_SHOCK)
    assert with_reserve[C.RES_DRAW].sum() > 0
    assert with_reserve[C.TURBO_STEPS[0]].sum() > 0
    assert np.allclose(with_reserve[C.TURBO_STEPS[0]], no_reserve[C.TURBO_STEPS[0]], atol=1e-6)


@pytest.mark.parametrize("scen", SCENARIOS, ids=lambda s: s.name)
def test_reserve_draw_is_fully_allocated_to_fees_and_a_b_interest(runs, scen):
    r = runs[scen.name]
    parts = r[C.RES_DRAW_FEE] + r[C.RES_DRAW_A] + r[C.RES_DRAW_B]
    assert np.allclose(r[C.RES_DRAW], parts, atol=1e-6)
    assert (r[C.RES_DRAW_A] <= r[C.tr("A", C.INT_PAID)] + 1e-6).all()
    assert (r[C.RES_DRAW_B] <= r[C.tr("B", C.INT_PAID)] + 1e-6).all()


def test_reserve_draw_never_exceeds_unpaid_fees_and_a_b_interest(deal):
    r = run_waterfall(replace(deal, servicing_fee=0.08), BASE_SCENARIO)
    due = r[C.FEE_DUE] + r[C.tr("A", C.INT_DUE)] + r[C.tr("B", C.INT_DUE)]
    assert (r[C.RES_DRAW] <= due + 1e-6).all()
    assert r[C.RES_DRAW].sum() > 0


def test_stress_breach_triggers_turbo(runs):
    r = runs["Stress"]
    assert r[C.BREACH_ANY].sum() > 0
    breach_months = r[C.BREACH_ANY] == 1
    assert r[C.TURBO_TOTAL][breach_months].sum() > 0
    assert (r[C.tr("A", C.PRIN)][1:] >= r[C.tr("A", C.REG)][1:] - 1e-9).all()


def test_turbo_beats_no_turbo_on_senior_paydown(deal):
    # a trigger that can never breach removes the diversion, so A must pay down no faster
    relaxed = replace(deal, oc_trig=(0.0, 0.0, 0.0), ic_trig=(0.0, 0.0, 0.0))
    with_turbo = run_waterfall(deal, STRESS)
    without = run_waterfall(relaxed, STRESS)
    assert with_turbo[C.tr("A", C.END)][30] <= without[C.tr("A", C.END)][30] + 1e-6


def test_turbo_step_one_only_when_a_test_breached(runs):
    r = runs["Severe stress"]
    fired = r[C.TURBO_STEPS[0]] > 0
    assert (r[C.tr("A", C.BREACH)][fired] == 1).all()


def test_losses_hit_junior_tranches_first(runs, deal):
    r = runs["Severe stress"]
    wd = {x: r[C.tr(x, C.WD)].sum() for x in NOTES}
    assert wd["C"] == pytest.approx(deal.par("C"), abs=1e-3)
    assert wd["B"] > 0
    assert wd["A"] == 0 or wd["B"] == pytest.approx(deal.par("B"), abs=1e-3)


def test_oc_ratio_matches_hand_calculation(base):
    t = 3
    assert base[C.tr("A", C.OC)][t] == pytest.approx(base[C.POOL_VAL][t] / base[C.tr("A", C.PF)][t])
    den_b = base[C.tr("A", C.PF)][t] + base[C.tr("B", C.PF)][t]
    assert base[C.tr("B", C.OC)][t] == pytest.approx(base[C.POOL_VAL][t] / den_b)


def test_ic_ratio_matches_hand_calculation(base):
    t = 5
    fee_acc = (0.0060 + 0.0003) / 12 * base[C.POOL_BEG][t]
    num = base[C.INT_COLL][t] - fee_acc
    assert base[C.tr("A", C.IC)][t] == pytest.approx(num / base[C.tr("A", C.INT_ACC)][t])


def test_excess_spread_definition(base):
    t = 10
    fee_acc = (0.0060 + 0.0003) / 12 * base[C.POOL_BEG][t]
    acc = sum(base[C.tr(x, C.INT_ACC)][t] for x in NOTES)
    assert base[C.EXCESS_SPREAD][t] == pytest.approx(base[C.INT_COLL][t] - fee_acc - acc)


def test_floating_coupons_move_with_rate_shift(runs):
    diff = runs["Rate shock +300bp"][C.tr("A", C.CPN)][5] - runs["Mild stress"][C.tr("A", C.CPN)][5]
    assert diff == pytest.approx(0.03)
    assert runs["Rate shock +300bp"][C.tr("C", C.CPN)][5] == runs["Mild stress"][C.tr("C", C.CPN)][5]


def test_reserve_draws_when_interest_is_short(deal):
    r = run_waterfall(replace(deal, servicing_fee=0.08), BASE_SCENARIO)
    assert r[C.RES_DRAW].sum() > 0
    assert (r[C.RES_END] >= -1e-6).all()
    assert run_checks(r)["passed"]


def test_reserve_released_when_notes_retire(base, deal):
    assert base[C.RES_END][1] == pytest.approx(deal.reserve_initial)
    retired = np.where(base[C.RETIRED] == 1)[0][0]
    assert base[C.RES_RELEASE][retired] == pytest.approx(deal.reserve_initial)
    assert base[C.RES_END][retired] == 0


def test_interest_shortfalls_carry_forward(deal):
    r = run_waterfall(replace(deal, servicing_fee=0.12), SEVERE)
    shortfall = sum(r[C.tr(x, C.INT_SHORT)] for x in NOTES).max() + r[C.FEE_SHORT].max()
    assert shortfall > 0
    assert run_checks(r)["passed"]


def test_residual_par_includes_reserve(deal):
    assert deal.bal_r == deal.pool_balance + deal.reserve_initial - deal.bal_a - deal.bal_b - deal.bal_c
