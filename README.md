# Securitization Waterfall and Risk Retention Model

A generic structured-finance model: an amortizing collateral pool feeding a four-class capital structure through an explicit priority of payments, with overcollateralization (OC) and interest coverage (IC) tests, turbo cure, a reserve account, tranche write-downs, scenario and break-even analysis, and a module that sizes the 5% risk retention interest under US Regulation RR and EU Securitisation Regulation Article 6.

It is built twice from the same specification: a **Python package** (tested with pytest) and an **Excel workbook with live formulas**. A script recalculates the workbook headlessly in LibreOffice and reconciles it to the Python results.

**The collateral is synthetic.** The ten rep lines, the forward curve, the fees, the trigger levels, the fair value discount margins and the advance rates are all invented inputs chosen for illustration. Nothing here is market data or a real transaction.

## Contents

```
python/      waterfall/ package, tests/, outputs/ (CSV, JSON, charts), requirements.txt
excel/       build_workbook.py and securitization_waterfall.xlsx (about 21,000 live formulas)
docs/sources/  plain-text extracts of the regulations read for the retention module (see Sources)
```

Quick start (Windows shown; use `python` where `py -3` is not needed):

```
cd python
py -3 -m pip install -r requirements.txt
py -3 -m waterfall.cli               # regenerates every table, CSV and chart in python/outputs
py -3 -m pytest -q                   # 90 tests, about 45 seconds (the Excel reconciliation dominates)
cd ../excel
py -3 build_workbook.py              # rebuilds the workbook (embeds calculated values if LibreOffice is present)
cd ../python
py -3 -m waterfall.reconcile_excel   # recalculates the workbook in LibreOffice and compares to Python
```

## The deal

Pool (synthetic, 10 rep lines): USD 400.0 million, weighted average coupon 9.15%, weighted average remaining term 61.9 months, terms from 36 to 84 months. Monthly payment dates, 30/360 (rate divided by 12), interest accrues on beginning balances.

| Class | Original balance | Coupon | Subordination below it |
|-|-|-|-|
| A | 300.0m | index + 1.10% (floating) | 25.75% of pool |
| B | 40.0m | index + 2.25% (floating) | 15.75% |
| C | 30.0m | 7.50% fixed | 8.25% |
| R (residual) | 33.0m | none, receives all remaining cash | none |

The residual par equals pool balance plus the initial reserve account (3.0m, funded by the residual holder) less A, B and C. Senior fees are 0.60% servicing plus 0.03% trustee, annual, on beginning pool balance. The floating index is an assumed curve, `4.30% + (3.25% - 4.30%) * (1 - exp(-t/24))`, not market data. Notes are unhedged, so a rise in the index compresses excess spread (see the rate shock scenario).

### Collateral mechanics (per rep line, per month)

1. Defaults = beginning balance x MDR. MDR and SMM come from CDR and CPR by `1 - (1 - annual)^(1/12)`.
2. Interest = performing balance (beginning less defaults) x WAC / 12.
3. Scheduled principal = level-payment principal on the performing balance over the remaining term.
4. Prepayment = (performing balance less scheduled principal) x SMM.
5. Ending balance = beginning - defaults - scheduled - prepayment (reconciled every period, per rep line and in total).
6. Recoveries arrive `lag` months after default at (1 - severity) x defaulted balance. Net loss is recognized at default. Collateral value for the tests is ending balance plus recoveries still pending.

Collateral cash in = interest + scheduled principal + prepayments + recoveries.

### Priority of payments

Regular principal (available principal funds = scheduled + prepaid + recovered principal):

1. Class A, B, C principal, **sequential** (A, then B, then C) or **pro rata** by beginning balance. In pro rata mode the deal reverts to sequential from the period after any test breach.
2. Any excess after A, B and C are retired goes to the residual.

Tests are computed on pro forma balances (after regular principal, before turbo), so timing is consistent between collateral value and note balances:

* OC ratio for class k = (collateral value) / (balance of classes A through k). Triggers: A 1.25, B 1.12, C 1.045. Initial ratios are 1.333, 1.176 and 1.081.
* IC ratio for class k = (interest collections less senior fees accrued) / (interest accrued on classes A through k). Triggers: A 1.50, B 1.30, C 1.15.
* A class is in breach if either its OC or its IC ratio is below trigger.

Interest priority of payments (available interest funds = interest collections plus any reserve draw):

1. Senior fees.
2. Class A interest.
3. If the Class A tests are breached, all remaining interest is diverted to principal (turbo), A first, then B, then C.
4. Class B interest.
5. Turbo if the Class B tests are breached.
6. Class C interest.
7. Turbo if the Class C tests are breached.
8. Turbo to cure any principal deficiency (collateral value below note balances), up to the deficiency.
9. Reserve account top-up to target.
10. Remaining interest to the residual.

Unpaid fees and interest carry forward without interest on interest. The reserve account covers shortfalls in fees, A interest and B interest (not C), and is released to the residual when A, B and C are retired. After turbo, any remaining principal deficiency is written down against C, then B, then A. Write-downs are permanent (no reinstatement).

Excess spread = interest collections - senior fees - interest accrued on A, B, C. It is tracked per period in dollars and annualized basis points of pool balance.

### Tranche analytics

* WAL: sum of (month x principal paid) / 12 / total principal paid. For R, principal paid means principal distributions plus the reserve release.
* Yield at par: annualized (monthly IRR x 12) of the cash flows against a purchase at par at closing. This is the same basis as the coupons.
* Discount margin: spread over the forward curve that prices the cash flows at par with monthly compounding (Python only).
* Principal window: first and last month with principal paid.
* Loss: cumulative write-down for A, B, C. For R, par less total cash received (capital not returned).
* Break-even CDR: highest CDR (bisection, base CPR and lag) at which the tranche has no loss above USD 1.

## Results

Every figure below was produced by the code in this repository (`py -3 -m waterfall.cli`) and is stored in `python/outputs/`.

### Base case (CPR 10%, CDR 3%, severity 40%, recovery lag 6 months)

| Class | WAL (yrs) | Yield at par | Discount margin | Principal window (months) | Interest paid | Loss |
|-|-|-|-|-|-|-|
| A | 1.62 | 4.996% | 1.100% | 1 to 42 | 24.21m | none |
| B | 3.84 | 5.973% | 2.250% | 42 to 51 | 9.16m | none |
| C | 4.61 | 7.500% | 3.824% | 51 to 60 | 10.38m | none |
| R | 5.58 | 16.83% | 13.12% | 60 to 90 | 32.08m | none |

No test is breached in the base case. Cumulative net loss at the horizon is 2.73% of the original pool. Excess spread is about 327 basis points annualized in month 1.

### Scenario grid

Loss is a percentage of original class balance (R: capital not returned). "First loss" is the most junior class that takes any loss; "Most senior hit" is the most senior class with a loss.

| Scenario | CPR | CDR | Severity | Lag | Index shift | A | B | C | R | First loss | Most senior hit |
|-|-|-|-|-|-|-|-|-|-|-|-|
| Base | 10% | 3% | 40% | 6 | 0 | 0 | 0 | 0 | 0 | none | none |
| Mild stress | 10% | 6% | 50% | 6 | 0 | 0 | 0 | 0 | 0 | none | none |
| Stress | 6% | 12% | 60% | 9 | 0 | 0 | 0 | 52.9% | 73.2% | R | C |
| Severe stress | 4% | 20% | 70% | 12 | 0 | 0 | 80.3% | 100% | 90.2% | R | B |
| Fast prepay | 30% | 3% | 40% | 6 | 0 | 0 | 0 | 0 | 0 | none | none |
| Rate shock | 10% | 6% | 50% | 6 | +300bp | 0 | 0 | 0 | 46.0% | R | R |

The rate shock scenario shows unhedged basis risk: the credit assumptions equal Mild stress, yet the floating notes reprice up against fixed-rate collateral and the residual loses 46% of its capital. A denser CDR by severity grid (CDR 0% to 40%, severity 30%, 50%, 70%) is in `python/outputs/loss_grid_cdr_severity.csv`.

### Break-even CDR (annual, base CPR 10%, lag 6 months)

| Severity | Class A | Class B | Class C | Residual |
|-|-|-|-|-|
| 40% | 52.3% | 26.4% | 12.6% | 7.5% |
| 60% | 30.3% | 16.9% | 8.6% | 5.1% |

Higher severity cuts every break-even sharply, and the ordering (A above B above C above R) holds at both severities.

### Charts

![Tranche balance paydown, base and stress](python/outputs/charts/tranche_balance_paydown.png)

![Cumulative net loss versus subordination](python/outputs/charts/cumulative_loss_vs_subordination.png)

![Break-even CDR by tranche](python/outputs/charts/breakeven_cdr_by_tranche.png)

In the loss chart, a scenario curve above a class subordination line means collateral net losses exceed the notional credit enhancement below that class. Cumulative net loss at the horizon is 2.7% (Base), 6.6% (Mild stress), 15.7% (Stress) and 28.6% (Severe stress) of the original pool. Excess spread and turbo divert cash to principal, so write-downs are smaller than the gap to subordination suggests: Severe stress ends above the Class A line (25.75%) and Class A is still repaid in full.

## Risk retention

Retained amounts are computed from base-case tranche fair values. Fair value here is the present value of each class's base-case cash flows at the forward curve plus an assumed margin (A +1.10%, B +2.75%, C +4.50%, R +12.00%). This is an illustrative discounted cash flow, not a GAAP fair value measurement. Base fair values: A 300.00m, B 39.32m, C 29.22m, R 33.97m; total 402.51m against 403.00m of par across all four ABS interests.

| Option | What is retained | Par retained | Fair value retained |
|-|-|-|-|
| US Reg RR vertical, 17 CFR 246.4(a)(1) | 5% of every class | 20.150m | 20.126m |
| US Reg RR horizontal, 246.4(a)(2) | 59.25% of the residual, sized to 5% of fair value of all ABS interests | 19.553m | 20.126m |
| US Reg RR L-shaped, 246.4(a)(3) | 2.5% vertical plus a horizontal slice worth 2.5% of total fair value (2.5% of A, B, C and 32.13% of R) | 19.852m | 20.126m |
| EU Art 6(3)(a) vertical | 5% of the nominal of each tranche (all four treated as sold to investors) | 20.150m | not applicable |
| EU Art 6(3)(d) first loss | the whole residual (8.25% of the pool, above the 5% needed) | 33.000m | 33.966m |

Other amounts: the eligible horizontal cash reserve account alternative under 246.4(b) is funded at the required horizontal fair value, 20.126m. EU 6(3)(c) (randomly selected exposures) and 6(3)(e) (first loss exposure of 5% of every exposure) each equal 5% of the pool nominal, 20.000m; they are sized but not cash-flow modelled, and 6(3)(c) needs at least 100 potentially securitised exposures at origination, which a 10 rep line pool cannot show.

### Retained-position return (cost basis is par)

| Option | Base yield | Stress yield | Base cash received | Stress cash received |
|-|-|-|-|-|
| RR vertical (same as EU vertical) | 7.07% | 0.71% | 23.40m | 20.46m |
| RR horizontal | 16.83% | -27.87% | 32.10m | 5.23m |
| RR L-shaped | 12.86% | -15.92% | 27.75m | 12.85m |
| EU first loss | 16.83% | -27.87% | 54.18m | 8.83m |

Stress is CPR 6%, CDR 12%, severity 60%, lag 9. Sizing is fixed at closing on base fair values and is not re-run under stress. The vertical strip keeps a positive return under stress because it holds 5% of the senior classes that do not lose; horizontal and first-loss positions concentrate the loss.

### Financing view (illustrative)

Advance rates by class: A 85%, B 70%, C 55%, R 30%, at forward index + 2.75%. All retained cash flows sweep to the lender until repaid. Coverage is the present value of retained cash flows at the financing rate divided by the advance.

| Option | Advance | Advance / cost | Coverage base | Coverage stress | Repaid (base / stress) |
|-|-|-|-|-|-|
| RR vertical | 15.47m | 76.8% | 1.32x | 1.15x | month 37 / month 46 |
| RR horizontal | 5.87m | 30.0% | 4.46x | 0.76x | month 11 / not repaid, 2.27m unpaid |
| RR L-shaped | 10.67m | 53.7% | 2.18x | 1.05x | month 22 / month 93 |
| EU first loss | 9.90m | 30.0% | 4.46x | 0.76x | month 11 / not repaid, 3.84m unpaid |

17 CFR 246.12(e) prohibits a retaining sponsor from pledging a required retained ABS interest unless the obligation is with full recourse to the sponsor. So any "unpaid" balance above is a claim against the sponsor, not a loss the lender could absorb by seizing the retained interest. This view is an economic coverage illustration, not a compliant financing structure.

## Excel workbook

`excel/securitization_waterfall.xlsx`, sheets: Inputs, Pool, Waterfall, Tests, CashFlows, Retention_CF, Retention, Scenario_Summary. Only Inputs holds typed numbers (a test checks that the calculation sheets contain formulas or zero seeds only). Change the scenario number on Inputs (row "Selected scenario number") and every sheet recalculates. Pool has ten rep line blocks with beginning balance, defaults, interest, scheduled principal, prepayment and ending balance; Waterfall has the priority of payments step by step; Tests has OC and IC ratios, breach flags and excess spread; Retention sizes all five options and runs the financing sweep; Scenario_Summary shows the tranche metrics and integrity checks for the selected scenario.

Retention sizing in Excel follows the selected scenario's fair values unless the optional "Locked fair value" cells on Inputs are filled (paste base-case values there to fix sizing at closing while viewing stress). Break-even CDR and discount margin are not in Excel (no live solver); they are Python outputs, and the reconciliation probes the break-even point through the workbook.

### Reconciliation of Excel to Python

`py -3 -m waterfall.reconcile_excel` opens the workbook, sets the scenario selector, recalculates in headless LibreOffice, reads the results back and compares them to the Python model. It covers the six scenarios, two extra runs in pro rata mode (Base and Stress), and a break-even probe. Compared: every tranche cash flow in every period, interest and principal totals, write-downs, WAL, yields, live fair values, the retention fractions, retained amounts, retained yields, financing figures, breach month counts and the workbook's own check cells.

Stated tolerances: USD 0.01 for dollar amounts and each cash flow cell; 1e-6 for WAL (years) and annualized yields; 1e-5 for levered IRR; 1e-9 for retention fractions. Result of the last run (8 workbook recalculations): all passed, with worst absolute differences of 4.7e-8 USD on cash flows, 1.2e-7 USD on totals, 7.1e-15 years on WAL and 2.9e-12 on yields. Break-even probe on Class C: Python break-even CDR 12.5676%. Set in Excel at 0.995 times that CDR the Class C loss is USD 0; at 1.005 times it is USD 255,905.95 in Excel and USD 255,905.95 in Python. The full report is `python/outputs/excel_reconciliation.json`.

Honest caveats: recalculation was verified in LibreOffice only, not in Microsoft Excel. Two functions (`MINIFS`, `MAXIFS`, used for the principal window) need Excel 2019 or later. The committed workbook was round-tripped through LibreOffice so it carries calculated values; the creator property is set to the author name.

## Integrity checks (run for every scenario)

* Pool balance reconciliation each period and per rep line (max absolute difference 1.2e-7 USD).
* Lifetime pool identity: original balance = scheduled + prepaid + defaulted + ending balance.
* Cash conservation each period: fees + note interest + note principal + residual cash + change in reserve = collateral cash in (max 3.7e-9 USD).
* Fees plus note principal and interest paid never exceed collateral cash plus reserve draws.
* Per class: principal paid + write-downs + ending balance = original balance (max 1.2e-7 USD).
* No negative balances, payments or reserve.

## Sources

Regulatory text was read from primary sources on 2026-09-30 and saved as plain-text extracts in `docs/sources/` (each file starts with its source URL and retrieval date).

* **US, 17 CFR Part 246 (Regulation RR)**: eCFR API text of sections 246.2 (definitions of ABS interest, eligible vertical interest, eligible horizontal residual interest), 246.3 (base requirement), 246.4 (standard risk retention: (a)(1) vertical not less than 5 percent; (a)(2) horizontal at least 5 percent of the fair value of all ABS interests under a GAAP fair value framework; (a)(3) combination whose percentages equal at least five; (a)(4) determined at closing; (b) cash reserve account; (c) disclosures, including discount rates, loss given default, prepayment rates, default rates, lag between default and recovery, and the basis of forward rates) and 246.12 ((a) transfer, (b) hedging, (e) full-recourse financing). The eCFR API needs compressed transfer enabled on the request (curl's compressed option); without it the API answers HTTP 406.
* **EU, Regulation (EU) 2017/2402, Article 6**: the Publications Office consolidated text dated 09.04.2021 (`https://publications.europa.eu/resource/celex/02017R2402-20210409`, requested with an `Accept: application/xhtml+xml` header). Article 6(1): not less than 5%, measured at origination, not subject to credit risk mitigation or hedging. Article 6(3)(a) to (e): 5% of the nominal of each tranche sold or transferred to investors; revolving exposures; randomly selected exposures (at least 100 at origination); first loss tranche (plus other tranches if needed to reach 5% of the nominal of the securitised exposures); first loss exposure of at least 5% of every securitised exposure. The EUR-Lex website pages returned a bot-challenge response (HTTP 202, empty body), which is why the Publications Office endpoint was used.

Not verified: amendments to the EU Regulation after 9 April 2021 were not read, so Article 6 as currently in force should be checked before relying on this. The UK securitisation retention regime (a separate onshored rule set) was not fetched or modelled; the EU sizing here must not be read as a UK compliance calculation. Reg RR exemptions and other retention options (sections 246.5 to 246.11, for example qualified residential mortgages and revolving pool structures) are not modelled. The same joint rule also appears in banking agency codifications (for example 12 CFR Part 244), which were not read.

## Limitations

* The collateral is synthetic: ten rep lines with constant CPR and CDR, not loan-level data, and no seasoning curves.
* Delinquencies and servicer advances are not modelled; defaults go straight to a lagged recovery.
* Fees and coupons use a simplified 30/360 monthly convention with no payment lag between collection and payment dates.
* Notes are unhedged, and the discount margins, advance rates, triggers and forward curve are illustrative assumptions.
* Fair values for retention sizing are a discounted cash flow at assumed margins, not a GAAP fair value measurement, and no disclosure package is produced.
* Retention logic covers the standard options only, at the level of whole classes and pro rata slices, and does not test who the retainer is, majority-owned affiliate rules, or the hedging and transfer restrictions beyond describing them.
* No tax, accounting, or legal analysis. Nothing here is investment advice or a compliance opinion.
