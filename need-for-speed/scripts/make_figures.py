"""
Figures for "The Need for Speed" (PCCP/SaMD article), draft-v6.

All values are taken verbatim from the paper's published tables (draft-v5 / SSRN /
medRxiv) so the figures agree with the tables by construction:
  - Fig 1: cohort sizes  -> Table 1 header row
  - Fig 2: median review days by pathway x cohort -> Table 1
  - Fig 3: PCCP % of summaries by year -> Table 2A (+ text for AI 2023 & 2026)

Palette (Okabe-Ito, colorblind-safe, validated light-mode):
  AI = #0072B2 (blue) · Software+AI = #E69F00 (orange) · All = #009E73 (green)

Run:  uv run --with matplotlib --with numpy python figures/make_figures.py
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle

# ---- shared style -----------------------------------------------------------
C_AI = "#0072B2"
C_SWAI = "#E69F00"
C_ALL = "#009E73"
INK = "#222222"
MUTED = "#666666"
GRID = "#DDDDDD"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 10,
        "text.color": INK,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "svg.fonttype": "none",
    }
)


def despine(ax, keep=("left", "bottom")):
    for s in ("top", "right", "left", "bottom"):
        ax.spines[s].set_visible(s in keep)


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(
            f"figures/{name}.{ext}",
            dpi=200,
            bbox_inches="tight",
            facecolor="white",
        )
    plt.close(fig)
    print(f"wrote figures/{name}.pdf + .png")


# =============================================================================
# FIGURE 1 — Nested cohorts, area proportional to N (bottom-aligned nesting)
# =============================================================================
def fig1_nested():
    cohorts = [
        ("All devices", 24841, C_ALL),
        ("Software + AI", 1820, C_SWAI),
        ("AI devices", 1374, C_AI),
    ]
    fig, ax = plt.subplots(figsize=(5.4, 5.4))

    r = {name: np.sqrt(n) for name, n, _ in cohorts}
    rmax = r["All devices"]
    # normalize so the largest circle has radius 1.0
    scale = 1.0 / rmax
    baseline = 0.0  # all circles tangent to y = baseline

    for name, n, color in cohorts:
        rad = r[name] * scale
        cy = baseline + rad
        # concentric-at-bottom: shared vertical center line, tangent to baseline
        circ = Circle(
            (0.0, cy),
            rad,
            facecolor=color,
            edgecolor="white",
            linewidth=1.5,
            alpha=0.92,
            zorder=1,
        )
        ax.add_patch(circ)

    # labels with leader lines (small circles sit low, near the baseline)
    def label(name, n, color, xytext, ha):
        rad = r[name] * scale
        cy = baseline + rad
        # anchor point: top of each circle along the center line
        ax.annotate(
            f"{name}\nn = {n:,}",
            xy=(0.0, cy + rad * 0.0),
            xytext=xytext,
            ha=ha,
            va="center",
            fontsize=10,
            color=INK,
            fontweight="bold" if name == "AI devices" else "normal",
            arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8),
            zorder=3,
        )

    # All devices: label near top of big circle
    ax.annotate(
        "All devices\nn = 24,841",
        xy=(-0.72, 1.72),
        xytext=(-1.15, 1.72),
        ha="right",
        va="center",
        fontsize=10,
        color=INK,
        arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8),
    )
    # Software+AI and AI are the small nested pair near the baseline
    rad_sw = r["Software + AI"] * scale
    rad_ai = r["AI devices"] * scale
    ax.annotate(
        "Software + AI\nn = 1,820",
        xy=(rad_sw * 0.92, baseline + rad_sw * 1.15),
        xytext=(1.02, 0.92),
        ha="left",
        va="center",
        fontsize=10,
        color=INK,
        arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8),
    )
    ax.annotate(
        "AI devices\nn = 1,374",
        xy=(rad_ai * 0.55, baseline + rad_ai * 0.85),
        xytext=(1.02, 0.42),
        ha="left",
        va="center",
        fontsize=10,
        color=INK,
        fontweight="bold",
        arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8),
    )

    ax.text(
        0.0,
        2.28,
        "Nested device populations, 2018–2025\n(circle area proportional to number of submissions)",
        ha="center",
        va="bottom",
        fontsize=10.5,
        color=INK,
    )

    ax.set_xlim(-1.5, 1.7)
    ax.set_ylim(-0.15, 2.55)
    ax.set_aspect("equal")
    ax.axis("off")
    save(fig, "fig1_nested_cohorts")


# =============================================================================
# FIGURE 2 — Median review time by pathway x cohort (grouped horizontal bars)
# =============================================================================
def fig2_reviewtime():
    # Table 1 medians (days)
    pathways = ["De Novo", "Traditional 510(k)", "Special 510(k)"]
    data = {  # pathway -> (All, Software+AI, AI)
        "De Novo": (312, 299, 266),
        "Traditional 510(k)": (148, 149, 147),
        "Special 510(k)": (30, 29, 29),
    }
    series = [("All devices", C_ALL, 0), ("Software + AI", C_SWAI, 1), ("AI devices", C_AI, 2)]

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    y = np.arange(len(pathways))[::-1]  # De Novo on top
    h = 0.24

    for name, color, i in series:
        vals = [data[p][i] for p in pathways]
        offset = (i - 1) * h
        bars = ax.barh(
            y + offset,
            vals,
            height=h,
            color=color,
            edgecolor="white",
            linewidth=0.6,
            label=name,
            zorder=2,
        )
        for b, v in zip(bars, vals):
            ax.text(
                b.get_width() + 4,
                b.get_y() + b.get_height() / 2,
                f"{v}",
                va="center",
                ha="left",
                fontsize=8.5,
                color=INK,
            )

    ax.set_yticks(y)
    ax.set_yticklabels(pathways, fontsize=10, color=INK)
    ax.set_xlabel("Median review time, days (receipt to decision)", fontsize=10)
    ax.set_xlim(0, 360)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    despine(ax, keep=("left", "bottom"))
    ax.tick_params(length=0)

    # message annotation
    ax.text(
        0.5,
        1.06,
        "An AI device clears as fast or faster on every pathway —\nthe pathway sets the clock, not the presence of AI",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=10,
        color=INK,
    )
    ax.legend(
        loc="lower right",
        frameon=False,
        fontsize=9,
        handlelength=1.1,
        borderaxespad=0.6,
    )
    save(fig, "fig2_review_time_by_pathway")


# =============================================================================
# FIGURE 3 — PCCP adoption over time (AI vs All devices), multi-line
# =============================================================================
def fig3_pccp_time():
    # PCCP % of summaries by year, all pathways (510k + De Novo), canonical cohorts.
    years = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
    ai_vals = [0.0, 0.0, 1.7, 0.9, 0.0, 1.3, 6.9, 10.1, 10.5]
    swai_vals = [0.0, 0.0, 1.2, 0.7, 0.0, 1.0, 5.7, 9.1, 11.4]
    all_vals = [0.0, 0.0, 0.1, 0.0, 0.0, 0.2, 1.0, 2.1, 2.4]

    fig, ax = plt.subplots(figsize=(7.2, 4.6))

    # regulatory-timeline reference markers (staggered to avoid label collision)
    events = [
        (2022.99, "FDORA §3308\nDec 2022", "right", 13.6, "top"),
        (2023.30, "Draft guidance\nApr 2023", "left", 9.8, "top"),
        (2024.99, "Final guidance\nDec 2024", "center", 13.6, "top"),
    ]
    for xv, lbl, ha, yv, va in events:
        ax.axvline(xv, color=MUTED, linestyle=(0, (2, 3)), linewidth=0.8, zorder=1)
        ax.text(xv + (0.05 if ha == "left" else -0.05 if ha == "right" else 0),
                yv, lbl, ha=ha, va=va, fontsize=7.3, color=MUTED)

    ax.plot(years, all_vals, "-o", color=C_ALL, lw=2, ms=5.5, label="All devices", zorder=3)
    ax.plot(years, swai_vals, "-o", color=C_SWAI, lw=2, ms=5.5, label="Software + AI", zorder=4)
    ax.plot(years, ai_vals, "-o", color=C_AI, lw=2.2, ms=6, label="AI devices", zorder=5)

    # direct end labels
    ax.text(2026.08, 10.5, "10.5%", va="center", ha="left", fontsize=8.5, color=C_AI, fontweight="bold")
    ax.text(2026.08, 11.7, "11.4%", va="center", ha="left", fontsize=8.5, color=C_SWAI)
    ax.text(2026.08, 2.4, "2.4%", va="center", ha="left", fontsize=8.5, color=C_ALL)

    # annotate the Caption 2020 pilot (De Novo — the first PCCP, now on the AI line)
    ax.annotate(
        "Caption Guidance\n(first PCCP: De Novo AI, 2020)",
        xy=(2020, 1.7),
        xytext=(2018.1, 4.6),
        fontsize=7.3,
        color=INK,
        va="center",
        arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8),
    )

    ax.set_ylabel("Summaries disclosing a PCCP (%)", fontsize=10)
    ax.set_xlabel("Decision year", fontsize=10)
    ax.set_xlim(2017.6, 2027.0)
    ax.set_ylim(0, 14.2)
    ax.set_xticks(range(2018, 2027))
    ax.set_xticklabels([f"'{str(y)[2:]}" for y in range(2018, 2027)])
    ax.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    despine(ax, keep=("left", "bottom"))
    ax.tick_params(length=0)
    ax.legend(loc="upper left", frameon=False, fontsize=9.5, handlelength=1.4)

    ax.text(
        0.5,
        1.10,
        "AI adopts the PCCP at ~11× the rate of other devices, and the ramp tracks the statute",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=10,
        color=INK,
    )
    save(fig, "fig3_pccp_adoption_over_time")


if __name__ == "__main__":
    fig1_nested()
    fig2_reviewtime()
    fig3_pccp_time()
    print("done.")
