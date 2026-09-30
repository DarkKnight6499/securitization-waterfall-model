"""Tranche waterfall, credit enhancement tests, turbo, reserve account and write-downs.

Per payment date the order of calculation is:
  1. Collateral cash and interest/principal available funds.
  2. Regular principal to A, B, C (sequential, or pro rata until the first breach, then sequential for good).
  3. OC and IC tests on pro forma balances (after regular principal, before turbo).
  4. Interest priority of payments (see run_waterfall docstring).
  5. Write-downs of any remaining principal deficiency, most junior note first.
"""
import numpy as np

from . import columns as C
from .collateral import simulate_pool
from .config import NOTES, RETIRED_TOLERANCE_USD, Deal, Scenario

BIG_RATIO = 999.0  # ratio shown when a test has no notes to cover


def _ratio(num: float, den: float) -> float:
    return BIG_RATIO if den <= 0.005 else num / den


def run_waterfall(deal: Deal, scen: Scenario) -> dict:
    """Run the full deal. Interest priority of payments:

    1 senior fees; 2 Class A interest; 3 turbo to senior principal if Class A test breached;
    4 Class B interest; 5 turbo if Class B test breached; 6 Class C interest; 7 turbo if Class C
    test breached; 8 turbo to cure principal deficiency (realized losses); 9 reserve top-up to
    target; 10 residual. Unpaid fees and interest carry forward without interest on interest.
    Steps 1 to 10 run on interest collections only. The reserve then draws exactly the fees, Class A
    interest and Class B interest still unpaid and pays those items directly, so a draw is never
    swept into turbo or principal. Principal priority: regular principal collections to A, B, C,
    then any excess to the residual, except that once the notes are retired that excess and the reserve
    release first pay carried fees and A, B, C interest (EHRI condition 2: shortfalls hit the residual
    before any other interest). The pro rata mode is a latching switch: after the first
    breach every later period is sequential, even if the tests cure. The index for period t is
    fwd[t], the curve value at the end of month t (the payment date), applied to the beginning
    balance with a 30/360 monthly convention (rate / 12).
    """
    n = deal.horizon
    pool = simulate_pool(deal, scen)
    res = {k: v for k, v in pool.items() if k != "lines"}
    res["pool_lines"] = pool["lines"]
    fwd = pool[C.FWD]
    z = lambda: np.zeros(n + 1)  # noqa: E731

    for tranche in NOTES:
        for f in (C.BEG, C.INT_ACC, C.INT_DUE, C.INT_PAID, C.INT_SHORT, C.ARR, C.CPN, C.REG, C.PF,
                  C.PRIN, C.WD, C.END, C.X, C.OC, C.IC, C.BREACH):
            res[C.tr(tranche, f)] = z()
    for k in (C.FEE_DUE, C.FEE_PAID, C.FEE_SHORT, C.INT_COLL, C.RES_BEG, C.RES_DRAW, C.RES_DRAW_FEE,
              C.RES_DRAW_A, C.RES_DRAW_B, C.RES_TOPUP,
              C.RES_RELEASE, C.RES_RELEASE_R, C.ARR_FEE, C.RES_END, C.AIF, C.APF, C.SEQ_FLAG, C.TURBO_TOTAL, C.TURBO_A,
              C.TURBO_B, C.TURBO_C, C.PDL_PRE, C.DEFICIENCY, C.RESID_INT, C.RESID_PRIN,
              C.RESID_CASH, C.RETIRED, C.EXCESS_SPREAD, C.EXCESS_SPREAD_BPS, C.BREACH_ANY,
              C.CASH_CHECK, C.NOTES_PAID_TOTAL, *C.TURBO_STEPS):
        res[k] = z()

    bal0 = {"A": deal.bal_a, "B": deal.bal_b, "C": deal.bal_c}
    for tranche in NOTES:
        res[C.tr(tranche, C.END)][0] = bal0[tranche]
    res[C.RES_END][0] = deal.reserve_initial
    fee_rate = (deal.servicing_fee + deal.trustee_fee) / 12.0
    seq_mode = deal.principal_mode == "sequential"

    for t in range(1, n + 1):
        beg = {x: res[C.tr(x, C.END)][t - 1] for x in NOTES}
        cpn = {"A": max(0.0, fwd[t] + deal.margin_a), "B": max(0.0, fwd[t] + deal.margin_b), "C": deal.fixed_c}
        acc = {x: beg[x] * cpn[x] / 12.0 for x in NOTES}
        due = {x: acc[x] + res[C.tr(x, C.INT_SHORT)][t - 1] for x in NOTES}
        fee_acc = fee_rate * pool[C.POOL_BEG][t]
        fee_due = fee_acc + res[C.FEE_SHORT][t - 1]
        int_coll = pool[C.POOL_INT][t]
        res_beg = res[C.RES_END][t - 1]
        apf = pool[C.POOL_SCH][t] + pool[C.POOL_PRE][t] + pool[C.POOL_REC][t]

        # regular principal
        latched = res[C.BREACH_ANY][t - 1] == 1.0 or res[C.SEQ_FLAG][t - 1] == 1.0  # one-way switch
        seq = 1.0 if (seq_mode or latched) else 0.0
        sum_beg = sum(beg.values())
        reg = {}
        if seq == 1.0:
            left = apf
            for x in NOTES:
                reg[x] = min(beg[x], left)
                left -= reg[x]
        else:
            to_notes = min(apf, sum_beg)
            for x in NOTES:
                reg[x] = 0.0 if sum_beg <= 0 else to_notes * beg[x] / sum_beg
        r_prin = apf - sum(reg.values())
        pf = {x: beg[x] - reg[x] for x in NOTES}
        pf_tot = sum(pf.values())
        val = pool[C.POOL_VAL][t]

        # tests
        num_ic = max(0.0, int_coll - fee_acc)
        cum_pf, cum_acc = 0.0, 0.0
        breach = {}
        for i, x in enumerate(NOTES):
            cum_pf += pf[x]
            cum_acc += acc[x]
            oc = _ratio(val, cum_pf)
            ic = _ratio(num_ic, cum_acc)
            res[C.tr(x, C.OC)][t] = oc
            res[C.tr(x, C.IC)][t] = ic
            breach[x] = 1.0 if (oc < deal.oc_trig[i] or ic < deal.ic_trig[i]) else 0.0
            res[C.tr(x, C.BREACH)][t] = breach[x]
        any_breach = 1.0 if max(breach.values()) > 0 else 0.0

        # interest waterfall on collections only; the reserve covers what is left unpaid afterwards
        fees_c = min(fee_due, int_coll)
        rem = int_coll - fees_c
        paid_c = {}
        paid_c["A"] = min(due["A"], rem)
        rem -= paid_c["A"]
        used = 0.0
        t1 = min(rem, pf_tot - used) if breach["A"] else 0.0
        rem -= t1
        used += t1
        paid_c["B"] = min(due["B"], rem)
        rem -= paid_c["B"]
        t2 = min(rem, pf_tot - used) if breach["B"] else 0.0
        rem -= t2
        used += t2
        paid_c["C"] = min(due["C"], rem)
        rem -= paid_c["C"]
        t3 = min(rem, pf_tot - used) if breach["C"] else 0.0
        rem -= t3
        used += t3
        short_fee, short_a, short_b = fee_due - fees_c, due["A"] - paid_c["A"], due["B"] - paid_c["B"]
        draw = min(res_beg, short_fee + short_a + short_b)
        d_fee = min(draw, short_fee)
        d_a = min(draw - d_fee, short_a)
        d_b = min(short_b, draw - d_fee - d_a)
        fees_paid = fees_c + d_fee
        paid = {"A": paid_c["A"] + d_a, "B": paid_c["B"] + d_b, "C": paid_c["C"]}
        aif = int_coll + draw
        def_pre = max(0.0, pf_tot - used - val)
        t4 = min(rem, def_pre)
        rem -= t4
        used += t4
        turbo_tot = used
        turbo = {}
        left = turbo_tot
        for x in NOTES:
            turbo[x] = min(pf[x], left)
            left -= turbo[x]
        post = {x: pf[x] - turbo[x] for x in NOTES}
        deficiency = max(0.0, sum(post.values()) - val)
        wd, left = {}, deficiency
        for x in reversed(NOTES):
            wd[x] = min(post[x], left)
            left -= wd[x]
        end = {x: post[x] - wd[x] for x in NOTES}
        retired = 1.0 if sum(end.values()) < RETIRED_TOLERANCE_USD else 0.0

        res_after = res_beg - draw
        topup = 0.0 if retired else min(rem, max(0.0, deal.reserve_target - res_after))
        release = res_after if retired else 0.0
        rem -= topup
        # once the notes retire, principal collections and the reserve release settle carried fees and
        # note interest (A, B, C) before the residual gets anything
        sweep_left = r_prin + release if retired else 0.0
        arr_fee = min(sweep_left, fee_due - fees_paid)
        sweep_left -= arr_fee
        arr = {}
        for x in NOTES:
            arr[x] = min(sweep_left, due[x] - paid[x])
            sweep_left -= arr[x]
        fees_paid += arr_fee
        paid = {x: paid[x] + arr[x] for x in NOTES}
        sweep = arr_fee + sum(arr.values())
        take_prin = min(r_prin, sweep)
        r_prin -= take_prin
        release_r = release - (sweep - take_prin)
        resid_cash = rem + r_prin + release_r

        # store
        for x in NOTES:
            res[C.tr(x, C.BEG)][t] = beg[x]
            res[C.tr(x, C.CPN)][t] = cpn[x]
            res[C.tr(x, C.INT_ACC)][t] = acc[x]
            res[C.tr(x, C.INT_DUE)][t] = due[x]
            res[C.tr(x, C.INT_PAID)][t] = paid[x]
            res[C.tr(x, C.INT_SHORT)][t] = due[x] - paid[x]
            res[C.tr(x, C.ARR)][t] = arr[x]
            res[C.tr(x, C.REG)][t] = reg[x]
            res[C.tr(x, C.PF)][t] = pf[x]
            res[C.tr(x, C.PRIN)][t] = reg[x] + turbo[x]
            res[C.tr(x, C.WD)][t] = wd[x]
            res[C.tr(x, C.X)][t] = post[x]
            res[C.tr(x, C.END)][t] = end[x]
        res[C.FEE_DUE][t] = fee_due
        res[C.FEE_PAID][t] = fees_paid
        res[C.FEE_SHORT][t] = fee_due - fees_paid
        res[C.INT_COLL][t] = int_coll
        res[C.RES_BEG][t] = res_beg
        res[C.RES_DRAW][t] = draw
        res[C.RES_DRAW_FEE][t], res[C.RES_DRAW_A][t], res[C.RES_DRAW_B][t] = d_fee, d_a, d_b
        res[C.RES_TOPUP][t] = topup
        res[C.RES_RELEASE][t] = release
        res[C.RES_RELEASE_R][t] = release_r
        res[C.ARR_FEE][t] = arr_fee
        res[C.RES_END][t] = res_after + topup - release
        res[C.AIF][t] = aif
        res[C.APF][t] = apf
        res[C.SEQ_FLAG][t] = seq
        res[C.TURBO_TOTAL][t] = turbo_tot
        res[C.TURBO_A][t], res[C.TURBO_B][t], res[C.TURBO_C][t] = turbo["A"], turbo["B"], turbo["C"]
        for key, val_ in zip(C.TURBO_STEPS, (t1, t2, t3, t4)):
            res[key][t] = val_
        res[C.PDL_PRE][t] = def_pre
        res[C.DEFICIENCY][t] = deficiency
        res[C.RESID_INT][t] = rem
        res[C.RESID_PRIN][t] = r_prin
        res[C.RESID_CASH][t] = resid_cash
        res[C.RETIRED][t] = retired
        es = int_coll - fee_acc - sum(acc.values())
        res[C.EXCESS_SPREAD][t] = es
        res[C.EXCESS_SPREAD_BPS][t] = 0.0 if pool[C.POOL_BEG][t] <= 0 else es * 12.0 / pool[C.POOL_BEG][t] * 1e4
        res[C.BREACH_ANY][t] = any_breach
        notes_paid = sum(paid.values()) + sum(reg.values()) + turbo_tot
        res[C.NOTES_PAID_TOTAL][t] = notes_paid
        payouts = fees_paid + notes_paid + resid_cash
        res[C.CASH_CHECK][t] = payouts + (res[C.RES_END][t] - res_beg) - pool[C.POOL_CASH][t]

    res["deal"] = deal
    res["scenario"] = scen
    return res
