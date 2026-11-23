"""Figures for the CEGF precision-farming experiments -> results/visuals/.

Reads the Python-simulator CSVs (../farm/results) and the iFogSim2 CSVs (./results). Any iFogSim file that is
not there yet is skipped, so the script can be re-run while/after `run_ifogsim.py` finishes.
Palette: validated default categorical palette (slots 1-5), light surface.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "farm", "results")
IF = os.path.join(HERE, "results")
OUT = os.path.join(IF, "visuals")
os.makedirs(OUT, exist_ok=True)

BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e3e2de"
T = 2.093
plt.rcParams.update({"font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})


def load(path):
    return pd.read_csv(path) if os.path.exists(path) else None


def mc(df, by, col):
    g = df.groupby(by)[col]
    return g.mean(), T * g.std() / np.sqrt(g.count())


def save(fig, name):
    fig.savefig(os.path.join(OUT, name + ".png"), dpi=170, bbox_inches="tight")
    fig.savefig(os.path.join(OUT, name + ".pdf"), bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


# ---------------------------------------------------------------- data
py_df1, py_theta = load(f"{PY}/e1_df1.csv"), load(f"{PY}/e1_theta.csv")
if_df1, if_theta = load(f"{IF}/ifog_e1_df1.csv"), load(f"{IF}/ifog_e1_theta.csv")
py_jobs, py_thr, py_flex = load(f"{PY}/e2_jobs.csv"), load(f"{PY}/e2_thresholds.csv"), load(f"{PY}/e3_flex.csv")
if_jobs, if_thr, if_flex = load(f"{IF}/ifog_e2_jobs.csv"), load(f"{IF}/ifog_e2_thr.csv"), load(f"{IF}/ifog_e3_flex.csv")

# ================================================================ Fig 1: data flow (E1)
if if_df1 is not None:
    fig, ax = plt.subplots(1, 3, figsize=(12.2, 3.5), gridspec_kw={"width_ratios": [1.1, 1.1, 1.3]})
    modes = [("UG", "Ungoverned\n(plain MQTT)", ORANGE), ("SS", "All-HTTPS", YELLOW), ("CEGF", "CEGF", BLUE)]
    for k, (col, title, scale) in enumerate([("TUDR", "(a) Useful items delivered on time (%)", 100), ("uplink_MB", "(b) Uplink volume (MB per hour)", 1)]):
        a = ax[k]
        for j, cam in enumerate((1.0, 1.5)):
            for i, (m, lab, c) in enumerate(modes):
                d = if_df1[(if_df1["mode"] == m) & (if_df1.cam == cam)][col] * scale
                x = j * 4.2 + i
                a.bar(x, d.mean(), 0.78, color=c, label=lab.replace("\n", " ") if j == 0 else None)
                a.errorbar(x, d.mean(), T * d.std() / np.sqrt(len(d)), color=INK, lw=0.8, capsize=2)
                a.text(x, d.mean() + (2 if k == 0 else 0.6), f"{d.mean():.0f}" if k == 0 else f"{d.mean():.1f}", ha="center", fontsize=8, color=INK)
        a.set_xticks([1, 5.2]); a.set_xticklabels(["12 cameras\n(nominal)", "18 cameras\n(+50 % load)"]); a.set_title(title, loc="left", fontsize=10)
        a.grid(axis="x", visible=False)
    ax[0].set_ylim(0, 112); ax[0].legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3)
    a = ax[2]
    sims = [("iFogSim2", if_theta, "-", "o"), ("Python sim", py_theta, "--", "s")]
    for name, d, ls, mk in sims:
        if d is None: continue
        d = d[d["flow"] == 1] if "flow" in d else d
        sc = 100
        for col, c, lab in (("TUDR", BLUE, "on time (≈ recall)"), ("recall", AQUA, "recall"), ("volume_sel", ORANGE, "data forwarded")):
            m, e = mc(d, "theta", col)
            a.plot(m.index, m * sc, ls=ls, marker=mk, ms=4, lw=1.6, color=c, label=f"{lab}" if name == "iFogSim2" else None)
    a.annotate("data forwarded", (0.33, 50), fontsize=8, color=ORANGE)
    a.axvline(0.3, color=INK2, lw=0.8, ls=":"); a.text(0.31, 3, "θ = 0.3", fontsize=8, color=INK2)
    a.set_xlabel("entropy threshold θ"); a.set_ylabel("%"); a.set_ylim(0, 105)
    a.set_title("(c) Effect of θ  (solid: iFogSim2, dashed: Python sim)", loc="left", fontsize=10)
    a.legend(frameon=False, fontsize=8, loc="lower left")
    fig.tight_layout(); save(fig, "fig1_data_flow")

# ================================================================ Fig 2: job distribution vs load (E2)
POL = [("cegf", "CEGF", BLUE, "o"), ("greedy", "Greedy", ORANGE, "s"), ("random", "Random", AQUA, "^"), ("static", "Static", YELLOW, "D"), ("cloud", "Cloud-only", MAGENTA, "v")]
rows = [("Python simulator", py_jobs)] + ([("iFogSim2", if_jobs)] if if_jobs is not None else [])
rows = [r for r in rows if r[1] is not None]
if rows:
    fig, axs = plt.subplots(len(rows), 3, figsize=(12.2, 3.2 * len(rows)), squeeze=False)
    for r, (sim, d) in enumerate(rows):
        for k, (col, yl, log) in enumerate([("miss_critical", "critical deadline misses (%)", False),
                                            ("violations_pct", "policy violations (% of jobs)", False),
                                            ("lat_p95_irrig", "irrigation p95 latency (s)", True)]):
            a = axs[r][k]
            for key, lab, c, mk in POL:
                dd = d[d.policy == key]
                m, e = mc(dd, "load", col)
                a.errorbar(m.index, m, e, color=c, marker=mk, ms=4.5, lw=1.8 if key == "cegf" else 1.2, capsize=2,
                           label=lab, zorder=3 if key == "cegf" else 2)
            if log: a.set_yscale("log")
            a.set_xlabel("edge load (1.0 = edge capacity)"); a.set_ylabel(yl)
            if k == 0: a.set_title(f"{sim}", loc="left", fontsize=10, fontweight="bold")
            if r == 0 and k == 0: a.legend(frameon=False, fontsize=8)
    fig.tight_layout(); save(fig, "fig2_job_distribution")

# ================================================================ Fig 3: alpha x tau heatmaps (E2b)
rows = [("Python simulator", py_thr)] + ([("iFogSim2", if_thr)] if if_thr is not None else [])
rows = [r for r in rows if r[1] is not None]
if rows:
    fig, axs = plt.subplots(len(rows), 2, figsize=(8.2, 3.3 * len(rows)), squeeze=False)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seq", ["#eaf1fb", "#2a78d6", "#0d2f63"])
    for r, (sim, d) in enumerate(rows):
        for k, (col, title) in enumerate([("miss_critical", "critical misses (%)"), ("rejected_pct", "jobs rejected (%)")]):
            piv = d.groupby(["alpha", "tau"])[col].mean().unstack()
            a = axs[r][k]; im = a.imshow(piv.values, cmap=cmap, aspect="auto", vmin=0, vmax=max(20, np.nanmax(piv.values)))
            a.set_xticks(range(len(piv.columns))); a.set_xticklabels(piv.columns); a.set_yticks(range(len(piv.index))); a.set_yticklabels(piv.index)
            a.set_xlabel("trust threshold τ"); a.set_ylabel("availability threshold α"); a.grid(False)
            for i in range(piv.shape[0]):
                for j in range(piv.shape[1]):
                    v = piv.values[i, j]; a.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8, color="white" if v > 10 else INK)
            a.set_title(f"{sim}: {title}", loc="left", fontsize=10)
    fig.tight_layout(); save(fig, "fig3_threshold_sensitivity")

# ================================================================ Fig 4: flexibility (E3)
def flex_stats():
    out = []
    if py_flex is not None:
        d = py_flex.copy()
        d["pre"] = d[["w0_miss_crit", "w1_miss_crit"]].mean(axis=1); d["post"] = d[["w3_miss_crit", "w4_miss_crit", "w5_miss_crit"]].mean(axis=1)
        for v, lab in (("no change", "No change"), ("CEGF (runtime swap)", "Runtime swap"), ("hard-coded (30 s redeploy)", "Hard-coded,\n30 s redeploy")):
            x = d[d.policy == v]; out.append(("Python simulator", lab, x.pre, x.post))
    if if_flex is not None:
        for v, lab in (("no change", "No change"), ("runtime swap", "Runtime swap"), ("redeploy 30s", "Hard-coded,\n30 s redeploy")):
            x = if_flex[if_flex.variant == v]; out.append(("iFogSim2", lab, x.miss_crit_pre, x.miss_crit_post))
    return out


st = flex_stats()
if st:
    sims = list(dict.fromkeys(s[0] for s in st))
    fig, axs = plt.subplots(1, len(sims), figsize=(5.4 * len(sims), 3.4), squeeze=False)
    for a, sim in zip(axs[0], sims):
        items = [s for s in st if s[0] == sim]
        for i, (_, lab, pre, post) in enumerate(items):
            for j, (vals, c, nm) in enumerate(((pre, "#9fb9e0", "before change"), (post, BLUE, "after change"))):
                x = i * 3 + j
                a.bar(x, vals.mean(), 0.9, color=c, label=nm if i == 0 else None)
                a.errorbar(x, vals.mean(), T * vals.std() / np.sqrt(len(vals)), color=INK, lw=0.8, capsize=2)
                a.text(x, vals.mean() + T * vals.std() / np.sqrt(len(vals)) + 0.15, f"{vals.mean():.1f}", ha="center", fontsize=8)
        a.set_xticks([i * 3 + 0.5 for i in range(len(items))]); a.set_xticklabels([s[1] for s in items])
        a.set_ylabel("critical deadline misses (%)"); a.set_title(f"{sim}: policy tightened at t = 900 s", loc="left", fontsize=10)
        a.grid(axis="x", visible=False); a.legend(frameon=False, fontsize=8)
    fig.tight_layout(); save(fig, "fig4_flexibility")

# ================================================================ Fig 5: cross-simulator agreement on shared configs
if if_df1 is not None and py_df1 is not None:
    fig, a = plt.subplots(figsize=(6.4, 3.4))
    cfgs = [(m, cam) for cam in (1.0, 1.5) for m in ("UG", "SS", "CEGF")]
    names = {"UG": "Ungoverned", "SS": "All-HTTPS", "CEGF": "CEGF"}
    for y, (m, cam) in enumerate(cfgs[::-1]):
        p = py_df1[(py_df1["mode"] == m) & (py_df1.scale == cam) & (py_df1.flow == 1)]["TUDR"].mean() * 100
        i_ = if_df1[(if_df1["mode"] == m) & (if_df1.cam == cam)]["TUDR"].mean() * 100
        a.plot([p, i_], [y, y], color=GRID, lw=3, zorder=1)
        a.scatter(p, y, s=55, facecolor="#fcfcfb", edgecolor=BLUE, lw=1.8, zorder=3, label="Python simulator" if y == 0 else None)
        a.scatter(i_, y, s=55, color=ORANGE, zorder=3, label="iFogSim2" if y == 0 else None)
    a.set_yticks(range(len(cfgs))); a.set_yticklabels([f"{names[m]}, {int(12*cam)} cameras" for m, cam in cfgs[::-1]])
    a.set_xlabel("useful items delivered on time (%)"); a.set_xlim(-3, 105); a.grid(axis="y", visible=False)
    a.set_title("Same configurations, two simulators", loc="left", fontsize=10)
    a.legend(frameon=False, fontsize=8, loc="center right")
    fig.tight_layout(); save(fig, "fig5_simulator_agreement")
