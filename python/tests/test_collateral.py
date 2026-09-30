from dataclasses import replace

import numpy as np
import pytest

from waterfall import columns as C
from waterfall.collateral import annual_to_monthly, simulate_pool
from waterfall.config import BASE_SCENARIO, SCENARIOS, Deal


def test_annual_to_monthly_compounds_back():
    for rate in (0.0, 0.03, 0.12, 0.5):
        assert (1 - annual_to_monthly(rate)) ** 12 == pytest.approx(1 - rate)


@pytest.mark.parametrize("scen", SCENARIOS, ids=lambda s: s.name)
def test_balance_reconciles_every_period_pool_and_lines(deal, scen):
    pool = simulate_pool(deal, scen)
    recon = pool[C.POOL_BEG] - pool[C.POOL_DEF] - pool[C.POOL_SCH] - pool[C.POOL_PRE] - pool[C.POOL_END]
    assert np.abs(recon[1:]).max() < 1e-6
    assert np.abs(pool[C.POOL_RECON]).max() < 1e-6
    for lines in pool["lines"].values():
        d = lines[C.POOL_BEG] - lines[C.POOL_DEF] - lines[C.POOL_SCH] - lines[C.POOL_PRE] - lines[C.POOL_END]
        assert np.abs(d[1:]).max() < 1e-6
        assert (lines[C.POOL_END] >= -1e-6).all()


def test_beginning_balance_is_prior_ending(deal):
    pool = simulate_pool(deal, BASE_SCENARIO)
    assert np.allclose(pool[C.POOL_BEG][1:], pool[C.POOL_END][:-1])


def test_no_prepay_no_default_fully_amortizes_at_maturity(deal):
    scen = replace(BASE_SCENARIO, cpr=0.0, cdr=0.0)
    pool = simulate_pool(deal, scen)
    for (name, bal, _wac, wam) in deal.rep_lines:
        end = pool["lines"][name][C.POOL_END]
        assert end[wam] == pytest.approx(0.0, abs=1e-4)
        assert pool["lines"][name][C.POOL_SCH].sum() == pytest.approx(bal)
    assert pool[C.POOL_DEF].sum() == 0


def test_lifetime_principal_identity(deal):
    for scen in SCENARIOS:
        p = simulate_pool(deal, scen)
        total = p[C.POOL_SCH].sum() + p[C.POOL_PRE].sum() + p[C.POOL_DEF].sum() + p[C.POOL_END][-1]
        assert total == pytest.approx(deal.pool_balance, abs=1e-4)


def test_recoveries_follow_lag_and_severity(deal):
    scen = replace(BASE_SCENARIO, lag=6, severity=0.35)
    p = simulate_pool(deal, scen)
    assert p[C.POOL_REC][:7].sum() == 0
    assert p[C.POOL_REC][7] == pytest.approx(p[C.POOL_DEF][1] * 0.65)
    assert p[C.POOL_CUM_REC][-1] == pytest.approx(p[C.POOL_CUM_DEF][-1] * 0.65, rel=1e-9)
    assert abs(p[C.POOL_PEND][-1]) < 1e-4


def test_zero_lag_recovers_same_period(deal):
    p = simulate_pool(deal, replace(BASE_SCENARIO, lag=0))
    assert p[C.POOL_REC][1] == pytest.approx(p[C.POOL_DEF][1] * (1 - BASE_SCENARIO.severity))


def test_collateral_cash_definition(deal):
    p = simulate_pool(deal, BASE_SCENARIO)
    assert np.allclose(p[C.POOL_CASH], p[C.POOL_INT] + p[C.POOL_SCH] + p[C.POOL_PRE] + p[C.POOL_REC])


def test_rate_shift_moves_forward_curve(deal):
    a = simulate_pool(deal, BASE_SCENARIO)[C.FWD]
    b = simulate_pool(deal, replace(BASE_SCENARIO, rate_shift_bps=300))[C.FWD]
    assert np.allclose(b - a, 0.03)


def test_pool_balance_matches_rep_lines():
    assert Deal().pool_balance == 400_000_000
