"""Scenario grid and break-even CDR by tranche."""
from dataclasses import replace

from .config import (BASE_SCENARIO, BREAKEVEN_CDR_MAX, GRID_CDRS, GRID_SEVERITIES, LOSS_THRESHOLD_USD,
                     SCENARIOS, TRANCHES, Deal)
from . import columns as C
from .metrics import (first_shortfall_tranche, most_junior_writedown, most_senior_shortfall,
                      most_senior_writedown, tranche_loss, tranche_summary)
from .waterfall import run_waterfall


def class_labels(summ: dict) -> dict:
    """Write-down-only labels and the wider labels that also count unpaid interest."""
    return {C.WD_MOST_SENIOR: most_senior_writedown(summ), C.WD_MOST_JUNIOR: most_junior_writedown(summ),
            C.SHORT_MOST_SENIOR: most_senior_shortfall(summ), C.SHORT_FIRST: first_shortfall_tranche(summ)}


def run_scenarios(deal: Deal, scenarios=SCENARIOS) -> list:
    rows = []
    for sc in scenarios:
        res = run_waterfall(deal, sc)
        summ = tranche_summary(res)
        rows.append({"scenario": sc, "result": res, "summary": summ, "labels": class_labels(summ)})
    return rows


def loss_at_cdr(deal: Deal, base, tranche: str, cdr: float) -> float:
    return tranche_loss(run_waterfall(deal, replace(base, cdr=cdr)), tranche)


def breakeven_cdr(deal: Deal, tranche: str, base=BASE_SCENARIO, iterations: int = 40) -> float:
    """Highest CDR with no loss (above LOSS_THRESHOLD_USD) on the tranche; nan if none below the cap."""
    lo, hi = 0.0, BREAKEVEN_CDR_MAX
    if loss_at_cdr(deal, base, tranche, lo) > LOSS_THRESHOLD_USD:
        return 0.0
    if loss_at_cdr(deal, base, tranche, hi) <= LOSS_THRESHOLD_USD:
        return float("nan")
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        if loss_at_cdr(deal, base, tranche, mid) > LOSS_THRESHOLD_USD:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def breakeven_table(deal: Deal, severities, base=BASE_SCENARIO) -> dict:
    return {sev: {x: breakeven_cdr(deal, x, replace(base, severity=sev)) for x in TRANCHES}
            for sev in severities}


def loss_grid(deal: Deal, base=BASE_SCENARIO, cdrs=GRID_CDRS, severities=GRID_SEVERITIES) -> list:
    rows = []
    for sev in severities:
        for cdr in cdrs:
            res = run_waterfall(deal, replace(base, cdr=cdr, severity=sev, name=f"CDR {cdr:.0%} sev {sev:.0%}"))
            summ = tranche_summary(res)
            row = {"cdr": cdr, "severity": sev, **class_labels(summ)}
            for x in TRANCHES:
                row[f"loss_pct_{x}"] = summ[x]["loss_pct"]
                row[f"unpaid_interest_end_{x}"] = summ[x]["unpaid_interest_end"]
            rows.append(row)
    return rows
