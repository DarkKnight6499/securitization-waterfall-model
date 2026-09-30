"""Matplotlib charts saved as PNGs."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import columns as C  # noqa: E402
from .config import CHART_DIR, NOTES, TRANCHES  # noqa: E402

TRANCHE_COLORS = {"A": "#1b6ca8", "B": "#e08a1e", "C": "#7a3e9d", "R": "#4d4d4d"}


def _save(fig, name):
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = CHART_DIR / name
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return path


def chart_paydown(base: dict, stress: dict):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, res in zip(axes, (base, stress)):
        t = res[C.PERIOD]
        for x in NOTES:
            ax.plot(t, res[C.tr(x, C.END)] / 1e6, label=f"Class {x}", color=TRANCHE_COLORS[x])
        ax.plot(t, res[C.POOL_END] / 1e6, label="Collateral", color="#999999", linestyle="--")
        ax.set_title(f"{res['scenario'].name}")
        ax.set_xlabel("Month")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Ending balance (USD millions)")
    axes[0].legend()
    return _save(fig, "tranche_balance_paydown.png")


def chart_loss_vs_subordination(results: list):
    deal = results[0]["deal"]
    pool = deal.pool_balance
    sub = {"C": deal.par("R") / pool,
           "B": (deal.par("C") + deal.par("R")) / pool,
           "A": (deal.par("B") + deal.par("C") + deal.par("R")) / pool}
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for res in results:
        ax.plot(res[C.PERIOD], res[C.POOL_CUM_LOSS] / pool * 100, label=res["scenario"].name)
    for x, lvl in sub.items():
        ax.axhline(lvl * 100, color=TRANCHE_COLORS[x], linestyle=":")
        ax.text(res[C.PERIOD][-1], lvl * 100, f" Class {x} subordination {lvl:.1%}", va="bottom", ha="right",
                color=TRANCHE_COLORS[x], fontsize=8)
    ax.set_xlabel("Month")
    ax.set_ylabel("Cumulative net loss (% of original pool)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    return _save(fig, "cumulative_loss_vs_subordination.png")


def chart_breakeven(table: dict):
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    sevs = list(table)
    width = 0.8 / len(sevs)
    for i, sev in enumerate(sevs):
        vals = [table[sev][x] * 100 for x in TRANCHES]
        pos = [j + i * width for j in range(len(TRANCHES))]
        bars = ax.bar(pos, vals, width, label=f"Severity {sev:.0%}")
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks([j + width * (len(sevs) - 1) / 2 for j in range(len(TRANCHES))])
    ax.set_xticklabels([f"Class {x}" if x != "R" else "Residual" for x in TRANCHES])
    ax.set_ylabel("Break-even CDR (% annual)")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")
    return _save(fig, "breakeven_cdr_by_tranche.png")
