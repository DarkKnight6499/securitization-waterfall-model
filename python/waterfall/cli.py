"""Reproduce every output: `py -3 -m waterfall.cli` from the python/ folder."""
import json

import pandas as pd

from . import columns as C
from .charts import chart_breakeven, chart_loss_vs_subordination, chart_paydown
from .checks import run_checks
from .config import BASE_SCENARIO, BREAKEVEN_SEVERITIES, OUTPUT_DIR, SCENARIOS, STRESS_SCENARIO, TRANCHES, Deal
from .metrics import first_loss_tranche, tranche_cash_flows
from .retention import (OPTIONS, fair_values, retention_amounts, retention_report)
from .scenarios import breakeven_table, loss_grid, run_scenarios

SCENARIO_COL, TRANCHE_COL, OPTION_COL = "scenario", "tranche", "option"


def cashflow_table(res: dict) -> pd.DataFrame:
    data = {C.PERIOD: res[C.PERIOD].astype(int), C.FWD: res[C.FWD],
            C.POOL_END: res[C.POOL_END], C.POOL_CASH: res[C.POOL_CASH],
            C.EXCESS_SPREAD: res[C.EXCESS_SPREAD], C.BREACH_ANY: res[C.BREACH_ANY],
            C.RES_END: res[C.RES_END], C.FEE_PAID: res[C.FEE_PAID]}
    for x in TRANCHES:
        cf = tranche_cash_flows(res, x)
        data[C.tr(x, C.INT_PAID)] = cf["interest"]
        data[C.tr(x, C.PRIN)] = cf["principal"]
        if x != "R":
            data[C.tr(x, C.WD)] = res[C.tr(x, C.WD)]
            data[C.tr(x, C.END)] = res[C.tr(x, C.END)]
    return pd.DataFrame(data)


def main() -> dict:
    deal = Deal()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    runs = run_scenarios(deal)
    by_name = {r["scenario"].name: r for r in runs}
    base, stress = by_name[BASE_SCENARIO.name]["result"], by_name[STRESS_SCENARIO.name]["result"]

    checks = {r["scenario"].name: run_checks(r["result"]) for r in runs}
    (OUTPUT_DIR / "checks.json").write_text(json.dumps(checks, indent=2))

    rows = []
    for r in runs:
        sc = r["scenario"]
        for x in TRANCHES:
            row = {SCENARIO_COL: sc.name, "cpr": sc.cpr, "cdr": sc.cdr, "severity": sc.severity,
                   "lag": sc.lag, "rate_shift_bps": sc.rate_shift_bps, TRANCHE_COL: x,
                   "first_loss_tranche": first_loss_tranche(r["summary"]),
                   "most_senior_impaired": r["most_senior_impaired"]}
            row.update(r["summary"][x])
            rows.append(row)
    pd.DataFrame(rows).to_csv(OUTPUT_DIR / "tranche_summary_by_scenario.csv", index=False)
    for name, res in (("base", base), ("stress", stress)):
        cashflow_table(res).to_csv(OUTPUT_DIR / f"cashflows_{name}.csv", index=False)

    be = breakeven_table(deal, BREAKEVEN_SEVERITIES)
    pd.DataFrame([{"severity": s, TRANCHE_COL: x, "breakeven_cdr": v}
                  for s, d in be.items() for x, v in d.items()]).to_csv(
        OUTPUT_DIR / "breakeven_cdr.csv", index=False)
    pd.DataFrame(loss_grid(deal)).to_csv(OUTPUT_DIR / "loss_grid_cdr_severity.csv", index=False)

    fv = fair_values(base)
    am = retention_amounts(deal, fv)
    fractions = {o: am["options"][o]["fractions"] for o in OPTIONS}
    ret_rows, fin_rows = [], []
    for name, res in (("base", base), ("stress", stress)):
        rep = retention_report(res, fractions)
        pd.DataFrame({C.PERIOD: res[C.PERIOD].astype(int), **{o: rep[o]["cf"] for o in OPTIONS}}).to_csv(
            OUTPUT_DIR / f"retained_cashflows_{name}.csv", index=False)
        for o in OPTIONS:
            a, f = am["options"][o], rep[o]["financing"]
            ret_rows.append({SCENARIO_COL: name, OPTION_COL: o, "retained_par": a["retained_par"],
                             "retained_fair_value": a["retained_fair_value"],
                             "par_pct_of_pool": a["par_pct_of_pool"],
                             "fv_pct_of_all_interests": a["fv_pct_of_all_interests"],
                             "total_cash_received": rep[o]["total_cash"],
                             "yield_at_cost": rep[o]["yield_at_cost"],
                             **{f"fraction_{x}": a["fractions"][x] for x in TRANCHES}})
            fin_rows.append({SCENARIO_COL: name, OPTION_COL: o, "advance": f["advance"],
                             "effective_advance_rate": f["advance_rate_effective"],
                             "pv_coverage": f["pv_coverage"], "repaid_month": f["repaid_month"],
                             "unpaid_at_horizon": f["unpaid_at_horizon"], "levered_irr": f["levered_irr"]})
    pd.DataFrame(ret_rows).to_csv(OUTPUT_DIR / "retention_summary.csv", index=False)
    pd.DataFrame(fin_rows).to_csv(OUTPUT_DIR / "financing_view.csv", index=False)
    pd.DataFrame([{"tranche": x, "fair_value": v, "par": deal.par(x), "fv_pct_of_par": v / deal.par(x)}
                  for x, v in fv.items()]).to_csv(OUTPUT_DIR / "fair_values.csv", index=False)

    paydown = chart_paydown(base, stress)
    loss_chart = chart_loss_vs_subordination(
        [by_name[n]["result"] for n in ("Base", "Mild stress", "Stress", "Severe stress")])
    be_chart = chart_breakeven(be)

    headline = {
        "pool_balance": deal.pool_balance, "residual_par": deal.bal_r,
        "base_summary": by_name["Base"]["summary"], "breakeven_cdr": {str(k): v for k, v in be.items()},
        "fair_values": fv, "retention": {o: {k: v for k, v in am["options"][o].items()} for o in OPTIONS},
        "retention_extra": am["extra"], "checks_all_passed": all(c["passed"] for c in checks.values()),
        "charts": [str(paydown), str(loss_chart), str(be_chart)],
    }
    (OUTPUT_DIR / "headline.json").write_text(json.dumps(headline, indent=2, default=float))
    print("checks passed in all scenarios:", headline["checks_all_passed"])
    print("outputs written to", OUTPUT_DIR)
    return headline


if __name__ == "__main__":
    main()
