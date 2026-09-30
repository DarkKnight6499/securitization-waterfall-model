"""Inputs for the securitization waterfall model. Every number here is a stated assumption.

The pool is SYNTHETIC. The forward curve is an assumed curve, not market data.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

# ============================== CONFIG ==============================
PACKAGE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PACKAGE_DIR.parent / "outputs"
CHART_DIR = OUTPUT_DIR / "charts"
EXCEL_PATH = PACKAGE_DIR.parent.parent / "excel" / "securitization_waterfall.xlsx"
SOFFICE_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "soffice",
)

HORIZON_MONTHS = 96  # longest rep-line term (84) plus the longest recovery lag (12)

# Synthetic rep lines: (name, balance USD, WAC, remaining term months)
POOL_REP_LINES = (
    ("RL01", 60_000_000.0, 0.0650, 60),
    ("RL02", 55_000_000.0, 0.0725, 72),
    ("RL03", 50_000_000.0, 0.0800, 48),
    ("RL04", 48_000_000.0, 0.0875, 66),
    ("RL05", 45_000_000.0, 0.0950, 60),
    ("RL06", 40_000_000.0, 0.1025, 84),
    ("RL07", 35_000_000.0, 0.1100, 54),
    ("RL08", 30_000_000.0, 0.1175, 72),
    ("RL09", 22_000_000.0, 0.1250, 36),
    ("RL10", 15_000_000.0, 0.1350, 48),
)

# Assumed forward index (SOFR-like): start + (end - start) * (1 - exp(-t / tau))
FWD_START = 0.0430
FWD_END = 0.0325
FWD_TAU_MONTHS = 24.0

# Notes: name, original balance USD, coupon type, margin (floating) or fixed rate
NOTE_A_BALANCE = 300_000_000.0
NOTE_B_BALANCE = 40_000_000.0
NOTE_C_BALANCE = 30_000_000.0
MARGIN_A = 0.0110
MARGIN_B = 0.0225
FIXED_RATE_C = 0.0750

SERVICING_FEE = 0.0060  # annual, on beginning pool balance
TRUSTEE_FEE = 0.0003
RESERVE_INITIAL = 3_000_000.0  # funded at closing by the residual holder
RESERVE_TARGET = 3_000_000.0

# Principal paydown: "sequential" or "pro_rata" (pro rata reverts to sequential after any breach)
PRINCIPAL_MODE = "sequential"

# Credit enhancement triggers
OC_TRIGGER_A = 1.25
OC_TRIGGER_B = 1.12
OC_TRIGGER_C = 1.045
IC_TRIGGER_A = 1.50
IC_TRIGGER_B = 1.30
IC_TRIGGER_C = 1.15

# Assumed market discount margins over the forward curve, used only for retention fair values
FV_MARGIN_A = 0.0110
FV_MARGIN_B = 0.0275
FV_MARGIN_C = 0.0450
FV_MARGIN_R = 0.1200

# Risk retention
RETENTION_PCT = 0.05
LSHAPE_VERTICAL_PCT = 0.025  # vertical share of the 5% combined requirement
EU_SOLD_TRANCHES = ("A", "B", "C", "R")  # tranches treated as sold to investors for the EU vertical option

# Financing of the retained interest (illustrative)
ADVANCE_RATE_A = 0.85
ADVANCE_RATE_B = 0.70
ADVANCE_RATE_C = 0.55
ADVANCE_RATE_R = 0.30
FINANCING_SPREAD = 0.0275

# Numerical tolerances
LOSS_THRESHOLD_USD = 1.0
RETIRED_TOLERANCE_USD = 0.005
BREAKEVEN_CDR_MAX = 0.95


@dataclass(frozen=True)
class Scenario:
    name: str
    cpr: float
    cdr: float
    severity: float
    lag: int
    rate_shift_bps: float = 0.0


BASE_SCENARIO = Scenario("Base", 0.10, 0.03, 0.40, 6)
SCENARIOS = (
    BASE_SCENARIO,
    Scenario("Mild stress", 0.10, 0.06, 0.50, 6),
    Scenario("Stress", 0.06, 0.12, 0.60, 9),
    Scenario("Severe stress", 0.04, 0.20, 0.70, 12),
    Scenario("Fast prepay", 0.30, 0.03, 0.40, 6),
    Scenario("Rate shock +300bp", 0.10, 0.06, 0.50, 6, 300.0),
)
STRESS_SCENARIO = SCENARIOS[2]

GRID_CDRS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
GRID_SEVERITIES = (0.30, 0.50, 0.70)
BREAKEVEN_SEVERITIES = (0.40, 0.60)
# ============================ END CONFIG ============================

TRANCHES = ("A", "B", "C", "R")
NOTES = ("A", "B", "C")


@dataclass(frozen=True)
class Deal:
    rep_lines: Tuple[tuple, ...] = POOL_REP_LINES
    horizon: int = HORIZON_MONTHS
    fwd_start: float = FWD_START
    fwd_end: float = FWD_END
    fwd_tau: float = FWD_TAU_MONTHS
    bal_a: float = NOTE_A_BALANCE
    bal_b: float = NOTE_B_BALANCE
    bal_c: float = NOTE_C_BALANCE
    margin_a: float = MARGIN_A
    margin_b: float = MARGIN_B
    fixed_c: float = FIXED_RATE_C
    servicing_fee: float = SERVICING_FEE
    trustee_fee: float = TRUSTEE_FEE
    reserve_initial: float = RESERVE_INITIAL
    reserve_target: float = RESERVE_TARGET
    principal_mode: str = PRINCIPAL_MODE
    oc_trig: Tuple[float, float, float] = (OC_TRIGGER_A, OC_TRIGGER_B, OC_TRIGGER_C)
    ic_trig: Tuple[float, float, float] = (IC_TRIGGER_A, IC_TRIGGER_B, IC_TRIGGER_C)
    fv_margins: Tuple[float, float, float, float] = (FV_MARGIN_A, FV_MARGIN_B, FV_MARGIN_C, FV_MARGIN_R)
    retention_pct: float = RETENTION_PCT
    lshape_vertical: float = LSHAPE_VERTICAL_PCT
    eu_sold: Tuple[str, ...] = EU_SOLD_TRANCHES
    advance_rates: Tuple[float, float, float, float] = (
        ADVANCE_RATE_A, ADVANCE_RATE_B, ADVANCE_RATE_C, ADVANCE_RATE_R)
    financing_spread: float = FINANCING_SPREAD

    @property
    def pool_balance(self) -> float:
        return sum(line[1] for line in self.rep_lines)

    @property
    def bal_r(self) -> float:
        return self.pool_balance + self.reserve_initial - self.bal_a - self.bal_b - self.bal_c

    def par(self, tranche: str) -> float:
        return {"A": self.bal_a, "B": self.bal_b, "C": self.bal_c, "R": self.bal_r}[tranche]
