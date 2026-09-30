"""Risk retention sizing, retained-position cash flows and a simple financing view.

Sources (text read from primary sources, see README):
  US: 17 CFR 246.2 (definitions of eligible vertical / horizontal residual interest),
      246.3 (base requirement), 246.4(a)(1)-(4) (5 percent options, fair value basis for horizontal),
      246.4(b) (eligible horizontal cash reserve account), 246.12 (hedging and transfer limits).
  EU: Regulation (EU) 2017/2402 Article 6(1) (5 percent net economic interest, measured at origination)
      and Article 6(3)(a) to (e) (permitted retention forms), consolidated text of 09.04.2021.
"""
from dataclasses import replace

import numpy as np

from . import columns as C
from .config import TRANCHES, Deal
from .metrics import irr_annual, pv_at_margin, tranche_cash_flows

RR_VERTICAL = "RR_VERTICAL"
RR_HORIZONTAL = "RR_HORIZONTAL"
RR_LSHAPED = "RR_LSHAPED"
EU_VERTICAL = "EU_VERTICAL"
EU_FIRST_LOSS = "EU_FIRST_LOSS"
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


def _stack_from_bottom(amounts: dict, required: float) -> dict:
    """Fraction of each class retained, filling from the most junior class upward."""
    frac, remaining = {}, required
    for x in reversed(TRANCHES):
        frac[x] = 0.0 if amounts[x] <= 0 else min(1.0, max(0.0, remaining) / amounts[x])
        remaining -= frac[x] * amounts[x]
    return frac


def retention_fractions(deal: Deal, fv: dict) -> dict:
    par = {x: deal.par(x) for x in TRANCHES}
    p = deal.retention_pct
    total_fv = sum(fv.values())
    out = {RR_VERTICAL: {x: p for x in TRANCHES}}
    out[RR_HORIZONTAL] = _stack_from_bottom(fv, p * total_fv)
    horiz = _stack_from_bottom(fv, (p - deal.lshape_vertical) * total_fv)
    out[RR_LSHAPED] = {x: min(1.0, deal.lshape_vertical + horiz[x]) for x in TRANCHES}
    out[EU_VERTICAL] = {x: (p if x in deal.eu_sold else 0.0) for x in TRANCHES}
    first_loss, cum, need = {}, 0.0, p * deal.pool_balance
    for x in reversed(TRANCHES):
        first_loss[x] = 1.0 if cum < need else 0.0
        cum += first_loss[x] * par[x]
    out[EU_FIRST_LOSS] = first_loss
    return out


def retention_amounts(deal: Deal, fv: dict) -> dict:
    fracs = retention_fractions(deal, fv)
    total_fv = sum(fv.values())
    total_par = sum(deal.par(x) for x in TRANCHES)
    rows = {}
    for opt in OPTIONS:
        f = fracs[opt]
        rows[opt] = {
            "fractions": f,
            "retained_par": sum(f[x] * deal.par(x) for x in TRANCHES),
            "retained_fair_value": sum(f[x] * fv[x] for x in TRANCHES),
        }
        rows[opt]["par_pct_of_all_interests"] = rows[opt]["retained_par"] / total_par
        rows[opt]["fv_pct_of_all_interests"] = rows[opt]["retained_fair_value"] / total_fv
        rows[opt]["par_pct_of_pool"] = rows[opt]["retained_par"] / deal.pool_balance
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


def retained_cash_flows(res: dict, fractions: dict) -> np.ndarray:
    cf = np.zeros(len(res[C.PERIOD]))
    for x in TRANCHES:
        cf += fractions[x] * tranche_cash_flows(res, x)["cf"]
    return cf


def financing_view(res: dict, fractions: dict) -> dict:
    """Advance against the retained interest, repaid by sweeping all retained cash flows."""
    deal = res["deal"]
    cf = retained_cash_flows(res, fractions)
    cost = -cf[0]
    advance = sum(fractions[x] * deal.par(x) * a for x, a in zip(TRANCHES, deal.advance_rates))
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


def retention_report(res: dict, fractions_by_option: dict) -> dict:
    out = {}
    for opt in OPTIONS:
        f = fractions_by_option[opt]
        cf = retained_cash_flows(res, f)
        out[opt] = {
            "cost": float(-cf[0]),
            "total_cash": float(cf[1:].sum()),
            "yield_at_cost": irr_annual(cf),
            "cf": cf,
            "financing": financing_view(res, f),
        }
    return out


def with_lshape(deal: Deal, vertical: float) -> Deal:
    return replace(deal, lshape_vertical=vertical)
