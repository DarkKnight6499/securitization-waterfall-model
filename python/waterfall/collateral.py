"""Rep-line collateral simulation: level-pay amortization with CPR/CDR, severity and recovery lag."""
import math

import numpy as np

from . import columns as C
from .config import Deal, Scenario


def annual_to_monthly(rate: float) -> float:
    """CPR->SMM and CDR->MDR share this conversion."""
    return 1.0 - (1.0 - rate) ** (1.0 / 12.0)


def forward_curve(deal: Deal, scen: Scenario) -> np.ndarray:
    t = np.arange(deal.horizon + 1, dtype=float)
    fwd = deal.fwd_start + (deal.fwd_end - deal.fwd_start) * (1.0 - np.exp(-t / deal.fwd_tau))
    return fwd + scen.rate_shift_bps / 10000.0


def simulate_pool(deal: Deal, scen: Scenario) -> dict:
    """Return pool arrays of length horizon+1 (index 0 is closing) plus per-line detail."""
    n = deal.horizon
    smm = annual_to_monthly(scen.cpr)
    mdr = annual_to_monthly(scen.cdr)
    sev = scen.severity
    z = lambda: np.zeros(n + 1)  # noqa: E731
    lines = {}
    for name, bal, wac, wam in deal.rep_lines:
        beg, dflt, intr, sch, pre, end = z(), z(), z(), z(), z(), z()
        end[0] = bal
        r = wac / 12.0
        for t in range(1, n + 1):
            beg[t] = end[t - 1]
            dflt[t] = beg[t] * mdr
            perf = beg[t] - dflt[t]
            intr[t] = perf * r
            rem = max(wam - (t - 1), 0)
            sch[t] = 0.0 if rem <= 0 else perf * (r / (1.0 - (1.0 + r) ** (-rem)) - r)
            pre[t] = (perf - sch[t]) * smm
            end[t] = perf - sch[t] - pre[t]
        lines[name] = {C.POOL_BEG: beg, C.POOL_DEF: dflt, C.POOL_INT: intr,
                       C.POOL_SCH: sch, C.POOL_PRE: pre, C.POOL_END: end}
    pool = {k: sum(v[k] for v in lines.values()) for k in
            (C.POOL_BEG, C.POOL_DEF, C.POOL_INT, C.POOL_SCH, C.POOL_PRE, C.POOL_END)}
    rec = z()
    for t in range(1, n + 1):
        src = t - scen.lag
        rec[t] = pool[C.POOL_DEF][src] * (1.0 - sev) if src >= 1 else 0.0
    cum_def = np.cumsum(pool[C.POOL_DEF])
    cum_rec = np.cumsum(rec)
    pool[C.POOL_REC] = rec
    pool[C.POOL_CUM_DEF] = cum_def
    pool[C.POOL_CUM_REC] = cum_rec
    pool[C.POOL_CUM_LOSS] = cum_def * sev
    pool[C.POOL_PEND] = cum_def * (1.0 - sev) - cum_rec
    pool[C.POOL_VAL] = pool[C.POOL_END] + pool[C.POOL_PEND]
    pool[C.POOL_CASH] = pool[C.POOL_INT] + pool[C.POOL_SCH] + pool[C.POOL_PRE] + rec
    recon = z()
    recon[1:] = (pool[C.POOL_BEG] - pool[C.POOL_DEF] - pool[C.POOL_SCH]
                 - pool[C.POOL_PRE] - pool[C.POOL_END])[1:]
    pool[C.POOL_RECON] = recon
    pool[C.PERIOD] = np.arange(n + 1, dtype=float)
    pool[C.FWD] = forward_curve(deal, scen)
    pool["lines"] = lines
    assert math.isfinite(float(pool[C.POOL_END][-1]))
    return pool
