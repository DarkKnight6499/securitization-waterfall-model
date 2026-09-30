"""Integrity checks run on every scenario."""
import numpy as np

from . import columns as C
from .config import NOTES

TOL_USD = 0.01


def run_checks(res: dict) -> dict:
    deal = res["deal"]
    out = {}
    out["pool_balance_recon_max_abs"] = float(np.abs(res[C.POOL_RECON]).max())
    line_recon = 0.0
    for lines in res["pool_lines"].values():
        d = lines[C.POOL_BEG] - lines[C.POOL_DEF] - lines[C.POOL_SCH] - lines[C.POOL_PRE] - lines[C.POOL_END]
        line_recon = max(line_recon, float(np.abs(d[1:]).max()))
    out["rep_line_recon_max_abs"] = line_recon
    out["cash_conservation_max_abs"] = float(np.abs(res[C.CASH_CHECK]).max())
    # notes plus fees paid cannot exceed collateral cash plus reserve draws and releases
    excess = res[C.NOTES_PAID_TOTAL] + res[C.FEE_PAID] - (res[C.POOL_CASH] + res[C.RES_DRAW] + res[C.RES_RELEASE])
    out["notes_paid_over_cash_max"] = float(excess.max())
    cons = 0.0
    for x in NOTES:
        orig = deal.par(x)
        total = res[C.tr(x, C.PRIN)].sum() + res[C.tr(x, C.WD)].sum() + res[C.tr(x, C.END)][-1]
        cons = max(cons, abs(orig - total))
        out[f"conservation_{x}"] = float(orig - total)
    out["tranche_conservation_max_abs"] = cons
    # every reserve draw must be applied to fees, Class A interest or Class B interest and nothing else
    out["reserve_draw_alloc_max_abs"] = float(np.abs(
        res[C.RES_DRAW] - res[C.RES_DRAW_FEE] - res[C.RES_DRAW_A] - res[C.RES_DRAW_B]).max())
    # 246.2 EHRI condition (2): the residual is never paid while fees or note interest are still owed
    owed = sum(res[C.tr(x, C.INT_SHORT)] for x in NOTES) + res[C.FEE_SHORT]
    out["residual_paid_while_owed_periods"] = int(((res[C.RESID_CASH] > TOL_USD) & (owed > TOL_USD)).sum())
    out["negative_balance_min"] = float(min(res[C.tr(x, C.END)].min() for x in NOTES))
    out["reserve_min"] = float(res[C.RES_END].min())
    out["pool_lifetime_recon_abs"] = float(abs(deal.pool_balance - (
        res[C.POOL_SCH].sum() + res[C.POOL_PRE].sum() + res[C.POOL_DEF].sum() + res[C.POOL_END][-1])))
    out["passed"] = bool(
        out["pool_balance_recon_max_abs"] < TOL_USD and out["rep_line_recon_max_abs"] < TOL_USD
        and out["cash_conservation_max_abs"] < TOL_USD and out["notes_paid_over_cash_max"] < TOL_USD
        and out["tranche_conservation_max_abs"] < TOL_USD and out["reserve_draw_alloc_max_abs"] < TOL_USD
        and out["pool_lifetime_recon_abs"] < TOL_USD and out["negative_balance_min"] > -TOL_USD
        and out["residual_paid_while_owed_periods"] == 0)
    return out
