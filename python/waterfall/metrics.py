"""Tranche analytics: WAL, yield at par, discount margin, principal window, losses."""
import math

import numpy as np

from . import columns as C
from .config import LOSS_THRESHOLD_USD, NOTES, TRANCHES

PRIN_EPS = 0.005  # dollars; below this a period counts as no principal


def tranche_cash_flows(res: dict, tranche: str) -> dict:
    """Interest, principal and total cash arrays (index 0 is closing, cash flow -par)."""
    deal = res["deal"]
    if tranche == "R":
        interest = res[C.RESID_INT]
        principal = res[C.RESID_PRIN] + res[C.RES_RELEASE]
    else:
        interest = res[C.tr(tranche, C.INT_PAID)]
        principal = res[C.tr(tranche, C.PRIN)]
    total = interest + principal
    cf = total.copy()
    cf[0] = -deal.par(tranche)
    return {"interest": interest, "principal": principal, "total": total, "cf": cf}


def wal_years(principal: np.ndarray, periods: np.ndarray) -> float:
    tot = principal[1:].sum()
    return float("nan") if tot <= PRIN_EPS else float((periods[1:] * principal[1:]).sum() / tot / 12.0)


def _npv(rate: float, cf: np.ndarray) -> float:
    t = np.arange(len(cf))
    return float(np.sum(cf / (1.0 + rate) ** t))


def irr_annual(cf: np.ndarray) -> float:
    """Monthly IRR by bisection, quoted as monthly rate x 12 (same basis as the coupons)."""
    cf = np.where(np.abs(cf) < 1e-4, 0.0, cf)  # float dust times a large discount factor flips the sign
    lo, hi = -0.5, 1.0
    f_lo, f_hi = _npv(lo, cf), _npv(hi, cf)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return float("nan")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = _npv(mid, cf)
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 12.0 * 0.5 * (lo + hi)


def _pv_over_forward(cf: np.ndarray, fwd: np.ndarray, margin: float) -> float:
    df = np.cumprod(1.0 / (1.0 + (fwd[1:] + margin) / 12.0))
    return float(np.sum(cf[1:] * df))


def pv_at_margin(cf: np.ndarray, fwd: np.ndarray, margin: float) -> float:
    return _pv_over_forward(cf, fwd, margin)


def discount_margin(cf: np.ndarray, fwd: np.ndarray) -> float:
    """Spread over the forward curve that prices the tranche at par (monthly compounding)."""
    par = -cf[0]
    lo, hi = -0.5, 5.0
    if (_pv_over_forward(cf, fwd, lo) - par) * (_pv_over_forward(cf, fwd, hi) - par) > 0:
        return float("nan")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _pv_over_forward(cf, fwd, mid) > par:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def principal_window(principal: np.ndarray):
    idx = np.where(principal[1:] > PRIN_EPS)[0]
    return (None, None) if len(idx) == 0 else (int(idx[0] + 1), int(idx[-1] + 1))


def tranche_loss(res: dict, tranche: str) -> float:
    """Note loss is the cumulative write-down; residual loss is capital not returned."""
    if tranche == "R":
        loss = max(0.0, res["deal"].par("R") - float(tranche_cash_flows(res, "R")["total"][1:].sum()))
    else:
        loss = float(res[C.tr(tranche, C.WD)].sum())
    return loss if loss > 1e-6 else 0.0  # float dust from the deficiency calculation


def tranche_summary(res: dict) -> dict:
    deal = res["deal"]
    out = {}
    for x in TRANCHES:
        cf = tranche_cash_flows(res, x)
        first, last = principal_window(cf["principal"])
        loss = tranche_loss(res, x)
        row = {
            "original_balance": deal.par(x),
            "interest_paid": float(cf["interest"][1:].sum()),
            "principal_paid": float(cf["principal"][1:].sum()),
            "writedown": loss,
            "ending_balance": float(res[C.tr(x, C.END)][-1]) if x != "R" else 0.0,
            "wal_years": wal_years(cf["principal"], res[C.PERIOD]),
            "yield_at_par": irr_annual(cf["cf"]),
            "discount_margin": discount_margin(cf["cf"], res[C.FWD]),
            "window_first": first,
            "window_last": last,
            "loss_pct": loss / deal.par(x),
            "takes_loss": loss > LOSS_THRESHOLD_USD,
        }
        if x in NOTES:
            short = res[C.tr(x, C.INT_SHORT)]  # float dust below a millionth of a dollar counts as zero
            row["unpaid_interest_end"] = float(short[-1]) if short[-1] > 1e-6 else 0.0
            row["unpaid_interest_peak"] = float(short.max()) if short.max() > 1e-6 else 0.0
        else:
            row["unpaid_interest_end"] = row["unpaid_interest_peak"] = 0.0  # residual has no interest claim
        row["any_shortfall"] = row["takes_loss"] or row["unpaid_interest_peak"] > LOSS_THRESHOLD_USD
        out[x] = row
    return out


def _most_senior(summary: dict, flag: str) -> str:
    for x in TRANCHES:
        if summary[x][flag]:
            return x
    return "none"


def _most_junior(summary: dict, flag: str) -> str:
    for x in reversed(TRANCHES):
        if summary[x][flag]:
            return x
    return "none"


def most_senior_writedown(summary: dict) -> str:
    """Most senior class with a principal write-down (interest deferrals are ignored)."""
    return _most_senior(summary, "takes_loss")


def most_junior_writedown(summary: dict) -> str:
    """Most junior class with a principal write-down, i.e. the first to absorb a loss."""
    return _most_junior(summary, "takes_loss")


def most_senior_shortfall(summary: dict) -> str:
    """Most senior class with a write-down or unpaid interest at any payment date."""
    return _most_senior(summary, "any_shortfall")


def first_shortfall_tranche(summary: dict) -> str:
    """Most junior class with any shortfall, the first in the order shortfalls are absorbed."""
    return _most_junior(summary, "any_shortfall")


def principal_subordination(deal) -> dict:
    """Share of the original pool below each note; the reserve cannot absorb principal, so it is excluded."""
    pool = deal.pool_balance
    return {"A": (pool - deal.bal_a) / pool, "B": (pool - deal.bal_a - deal.bal_b) / pool,
            "C": (pool - deal.bal_a - deal.bal_b - deal.bal_c) / pool}
