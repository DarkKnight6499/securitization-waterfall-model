"""Risk retention sizing, retained-position cash flows and a simple financing view.

Sources (text read from primary sources, see README):
  US: 17 CFR 246.2 (definitions of eligible vertical / horizontal residual interest),
      246.3 (base requirement), 246.4(a)(1)-(4) (5 percent options, fair value basis for horizontal),
      246.4(b) (eligible horizontal cash reserve account), 246.12(a),(b),(e) (transfer, hedging, full-recourse financing).
  EU: Regulation (EU) 2017/2402 Article 6(1) (5 percent net economic interest, measured at origination)
      and Article 6(3)(a) to (e) (permitted retention forms), consolidated text of 09.04.2021.
Horizontal options: 246.2 makes shortfalls reduce an eligible horizontal residual interest before any
other ABS interest, so the retained piece is the separate first-loss residual subclass R1 and the sold
remainder of the residual is R2 (paid ahead of R1). Same-class pro rata holdings would not qualify.
"""
from dataclasses import replace

import numpy as np

from . import columns as C
from .config import NOTES, TRANCHES, Deal
from .metrics import irr_annual, pv_at_margin, tranche_cash_flows

RR_VERTICAL = "RR_VERTICAL"
RR_HORIZONTAL = "RR_HORIZONTAL"
RR_LSHAPED = "RR_LSHAPED"
EU_VERTICAL = "EU_VERTICAL"
EU_FIRST_LOSS = "EU_FIRST_LOSS"
RET_CLASSES = (*NOTES, "R1", "R2")  # R1 retained first-loss residual subclass, R2 sold residual subclass
OPTIONS = (RR_VERTICAL, RR_HORIZONTAL, RR_LSHAPED, EU_VERTICAL, EU_FIRST_LOSS)
OPTION_LABELS = {
    RR_VERTICAL: "US Reg RR vertical, 246.4(a)(1)",
    RR_HORIZONTAL: "US Reg RR horizontal, 246.4(a)(2)",
    RR_LSHAPED: "US Reg RR L-shaped, 246.4(a)(3)",
    EU_VERTICAL: "EU Art 6(3)(a) vertical slice",
    EU_FIRST_LOSS: "EU Art 6(3)(d) first loss tranche",
}


def fair_values(res: dict) -> dict:
    """Present value of base-case tranche cash flows at forward curve plus an assumed margin."""
    deal = res["deal"]
    out = {}
    for x, margin in zip(TRANCHES, deal.fv_margins):
        cf = tranche_cash_flows(res, x)["total"]
        out[x] = pv_at_margin(cf, res[C.FWD], margin)
    return out


def _whole_class_flags(fv: dict, required: float) -> dict:
    """Whole junior notes added from the bottom (C, then B, then A) while the residual alone falls short.

    Only whole classes qualify for a horizontal position: a partial holding of a class shares losses
    pro rata with third-party holders, so it would not reduce before "any other ABS interest".
    """
    flags, remaining = {}, max(0.0, required - fv["R"])
    for x in reversed(NOTES):
        flags[x] = 1.0 if remaining > 0 else 0.0
        remaining -= flags[x] * fv[x]
    return flags


def residual_carve_out(fv: dict, required: float) -> float:
    """Par of the sold residual subclass R2: everything above the retained first-loss subclass R1.

    R2 is sold at par (it accrues at forward + the residual FV margin and is discounted at the same
    rate), so FV(R1) = FV(R) - par(R2) is at least the required horizontal fair value.
    """
    return max(0.0, fv["R"] - required)


def retention_structure(deal: Deal, fv: dict) -> dict:
    """Per option: fractions held of A, B, C, R1, R2 and the par of the sold subclass R2.

    R1 is the whole residual R unless the option carves out R2 (the horizontal and L-shaped options).
    """
    par = {x: deal.par(x) for x in TRANCHES}
    p, v = deal.retention_pct, deal.lshape_vertical
    total_fv = sum(fv.values())
    zero = {x: 0.0 for x in RET_CLASSES}
    out = {RR_VERTICAL: {"fractions": {**zero, **{x: p for x in (*NOTES, "R1")}}, "r2_par": 0.0}}
    req_h = p * total_fv
    flags = _whole_class_flags(fv, req_h)
    out[RR_HORIZONTAL] = {"fractions": {**zero, **flags, "R1": 1.0 if req_h > 0 else 0.0},
                          "r2_par": residual_carve_out(fv, req_h)}
    req_l = (p - v) * total_fv
    flags_l = _whole_class_flags(fv, req_l)
    out[RR_LSHAPED] = {"fractions": {**{x: max(v, flags_l[x]) for x in NOTES}, "R1": 1.0 if req_l > 0 else 0.0,
                                     "R2": v},
                       "r2_par": residual_carve_out(fv, req_l)}
    out[EU_VERTICAL] = {"fractions": {**zero, **{x: (p if x in deal.eu_sold else 0.0) for x in NOTES},
                                      "R1": p if "R" in deal.eu_sold else 0.0}, "r2_par": 0.0}
    first_loss, cum, need = {}, 0.0, p * deal.pool_balance
    for x in reversed(TRANCHES):
        first_loss[x] = 1.0 if cum < need else 0.0
        cum += first_loss[x] * par[x]
    out[EU_FIRST_LOSS] = {"fractions": {**zero, **{x: first_loss[x] for x in NOTES}, "R1": first_loss["R"]},
                          "r2_par": 0.0}
    return out


def retention_fractions(deal: Deal, fv: dict) -> dict:
    return {o: s["fractions"] for o, s in retention_structure(deal, fv).items()}


def class_par(deal: Deal, r2_par: float) -> dict:
    return {**{x: deal.par(x) for x in NOTES}, "R1": deal.par("R") - r2_par, "R2": r2_par}


def retention_amounts(deal: Deal, fv: dict) -> dict:
    structure = retention_structure(deal, fv)
    total_fv = sum(fv.values())
    total_par = sum(deal.par(x) for x in TRANCHES)
    rows = {}
    for opt in OPTIONS:
        f, r2 = structure[opt]["fractions"], structure[opt]["r2_par"]
        par = class_par(deal, r2)
        class_fv = {**{x: fv[x] for x in NOTES}, "R1": fv["R"] - r2, "R2": r2}
        rows[opt] = {
            "fractions": f,
            "r2_par": r2,
            "retained_par": sum(f[x] * par[x] for x in RET_CLASSES),
            "retained_fair_value": sum(f[x] * class_fv[x] for x in RET_CLASSES),
            "horizontal_fair_value": f["R1"] * class_fv["R1"] if opt in (RR_HORIZONTAL, RR_LSHAPED) else 0.0,
        }
        rows[opt]["par_pct_of_all_interests"] = rows[opt]["retained_par"] / total_par
        rows[opt]["fv_pct_of_all_interests"] = rows[opt]["retained_fair_value"] / total_fv
        rows[opt]["par_pct_of_pool"] = rows[opt]["retained_par"] / deal.pool_balance
    rows[RR_VERTICAL]["regulatory_measure"] = deal.retention_pct
    rows[RR_HORIZONTAL]["regulatory_measure"] = rows[RR_HORIZONTAL]["horizontal_fair_value"] / total_fv
    rows[RR_LSHAPED]["regulatory_measure"] = deal.lshape_vertical + rows[RR_LSHAPED]["horizontal_fair_value"] / total_fv
    extra = {
        "us_min_horizontal_fair_value": deal.retention_pct * total_fv,
        "us_cash_reserve_alternative_amount": deal.retention_pct * total_fv,
        "eu_required_nominal_of_pool": deal.retention_pct * deal.pool_balance,
        "eu_random_selection_exposures_6_3_c": deal.retention_pct * deal.pool_balance,
        "eu_first_loss_exposure_6_3_e": deal.retention_pct * deal.pool_balance,
        "total_fair_value": total_fv,
        "total_par": total_par,
    }
    return {"options": rows, "extra": extra}


def split_residual(res: dict, r2_par: float) -> dict:
    """Split residual cash into the sold priority subclass R2 and the retained first-loss subclass R1.

    R2 accrues at forward + the residual FV margin on its unpaid claim and is paid first, so any
    shortfall of residual cash reduces R1 before R2. Index 0 holds the purchase at par.
    """
    deal = res["deal"]
    cash = tranche_cash_flows(res, "R")["total"]
    rate = res[C.FWD] + deal.fv_margins[-1]
    n = len(cash)
    bal, pay = np.zeros(n), np.zeros(n)
    bal[0] = r2_par
    for t in range(1, n):
        due = bal[t - 1] * (1.0 + rate[t] / 12.0)
        pay[t] = min(cash[t], due)
        bal[t] = due - pay[t]
    cf2 = pay.copy()
    cf2[0] = -r2_par
    cf1 = cash - pay
    cf1[0] = -(deal.par("R") - r2_par)
    return {"R1": cf1, "R2": cf2, "r2_balance": bal}


def retained_cash_flows(res: dict, fractions: dict, r2_par: float = 0.0) -> np.ndarray:
    cf = np.zeros(len(res[C.PERIOD]))
    for x in NOTES:
        cf += fractions[x] * tranche_cash_flows(res, x)["cf"]
    split = split_residual(res, r2_par)
    cf += fractions["R1"] * split["R1"] + fractions["R2"] * split["R2"]
    return cf


def financing_view(res: dict, fractions: dict, r2_par: float = 0.0) -> dict:
    """Advance against the retained interest, repaid by sweeping all retained cash flows.

    17 CFR 246.12(e) allows pledging a retained ABS interest only under an obligation with full
    recourse to the sponsor, so any unpaid balance at the horizon is a recourse claim, not a loss to the lender.
    """
    deal = res["deal"]
    cf = retained_cash_flows(res, fractions, r2_par)
    cost = -cf[0]
    par = class_par(deal, r2_par)
    rates = dict(zip(TRANCHES, deal.advance_rates))
    rates.update({"R1": rates["R"], "R2": rates["R"]})  # both residual subclasses use the residual advance rate
    advance = sum(fractions[x] * par[x] * rates[x] for x in RET_CLASSES)
    rate = res[C.FWD] + deal.financing_spread
    n = len(cf)
    bal, pay, interest = np.zeros(n), np.zeros(n), np.zeros(n)
    bal[0] = advance
    for t in range(1, n):
        interest[t] = bal[t - 1] * rate[t] / 12.0
        pay[t] = min(cf[t], bal[t - 1] + interest[t])
        bal[t] = bal[t - 1] + interest[t] - pay[t]
    eq = cf - pay
    eq[0] = -(cost - advance)
    repaid = np.where((bal[1:] <= 0.005) & (np.arange(1, n) >= 1))[0]
    pv = pv_at_margin(cf, res[C.FWD], deal.financing_spread)
    return {
        "advance": advance,
        "advance_rate_effective": advance / cost if cost > 0 else float("nan"),
        "loan_balance": bal, "loan_payment": pay, "loan_interest": interest,
        "repaid_month": int(repaid[0] + 1) if len(repaid) else None,
        "unpaid_at_horizon": float(bal[-1]),
        "pv_coverage": pv / advance if advance > 0 else float("nan"),
        "levered_irr": irr_annual(eq),
    }


def retention_report(res: dict, structure: dict) -> dict:
    """structure: option -> {"fractions": ..., "r2_par": ...} as built by retention_structure."""
    out = {}
    for opt in OPTIONS:
        f, r2 = structure[opt]["fractions"], structure[opt]["r2_par"]
        cf = retained_cash_flows(res, f, r2)
        out[opt] = {
            "cost": float(-cf[0]),
            "total_cash": float(cf[1:].sum()),
            "yield_at_cost": irr_annual(cf),
            "cf": cf,
            "financing": financing_view(res, f, r2),
        }
    return out


def with_lshape(deal: Deal, vertical: float) -> Deal:
    return replace(deal, lshape_vertical=vertical)
