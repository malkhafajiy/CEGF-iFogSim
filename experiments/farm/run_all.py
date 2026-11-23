"""Runs experiments E1-E4 and writes CSVs, LaTeX tables and figures to ./results."""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import farm_sim as F
from odrl_eval import ENTROPY_POLICY, RECIPIENT_POLICY

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
SEEDS = list(range(1, 21))
T975 = 2.093  # t(0.975, 19)


def _df(a):
    seed, flow, mode, theta, scale = a
    return dict(flow=flow, mode=mode, theta=theta, scale=scale, seed=seed, **F.run_df(seed, flow, mode, theta, scale))


def _jobs(a):
    seed, policy, load, alpha, tau, change, outage, label = a
    R = F.run_jobs(seed, policy, load, alpha, tau, change, outage)
    S = F.summarize_jobs(R); S.update(policy=label or policy, load=load, alpha=alpha, tau=tau, seed=seed)
    # 300 s windows for the timeline (E4)
    ok = ~np.isnan(R["done"]) & (R["done"] <= R["dl"])
    crit = np.array([F.JTYPES[R["names"][t]][1] for t in R["ty"]])
    for w in range(6):
        m = (R["arr"] >= w * 300) & (R["arr"] < (w + 1) * 300) & crit
        S[f"w{w}_miss_crit"] = 100 * (1 - ok[m].mean()) if m.any() else np.nan
        S[f"w{w}_done"] = int(((R["done"] >= w * 300) & (R["done"] < (w + 1) * 300)).sum())
    S["swap_us"] = R["swap_us"]
    return S


def ci(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return x.mean(), T975 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0


def fmt(x, d=1):
    m, c = ci(x); return f"{m:.{d}f}\\,$\\pm$\\,{c:.{d}f}"


def main():
    os.makedirs(OUT, exist_ok=True)
    json.dump({"entropy": ENTROPY_POLICY, "recipient": RECIPIENT_POLICY}, open(os.path.join(OUT, "policies.json"), "w"), indent=1)
    ex = ProcessPoolExecutor()
    # ------------------------------------------------------------------ E1
    t1 = [(s, 1, m, 0.3, sc) for s in SEEDS for m in ("UG", "SS", "CEGF") for sc in (1.0, 1.5)]
    t1b = [(s, f, "CEGF", 0.3, 1.0) for s in SEEDS for f in (1, 2, 3, 4)]
    t1c = [(s, 1, "CEGF", th, 1.0) for s in SEEDS for th in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)]
    t1d = [(s, 1, m, 0.3, sc) for s in SEEDS for m in ("UG", "CEGF") for sc in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)]
    d1 = pd.DataFrame(list(ex.map(_df, t1))); d1b = pd.DataFrame(list(ex.map(_df, t1b)))
    d1c = pd.DataFrame(list(ex.map(_df, t1c))); d1d = pd.DataFrame(list(ex.map(_df, t1d)))
    for n, d in (("e1_df1", d1), ("e1_flows", d1b), ("e1_theta", d1c), ("e1_load", d1d)):
        d.to_csv(f"{OUT}/{n}.csv", index=False)
    assert all(F.entropy_policy_check(s) for s in SEEDS), "ODRL evaluator disagrees with vectorised filter"
    # ------------------------------------------------------------------ E2
    pols = ["random", "cloud", "static", "greedy", "cegf"]
    t2 = [(s, p, ld, 0.25, 0.7, None, 0.0, None) for s in SEEDS for p in pols for ld in (0.6, 0.9, 1.2, 1.5)]
    d2 = pd.DataFrame(list(ex.map(_jobs, t2))); d2.to_csv(f"{OUT}/e2_jobs.csv", index=False)
    t2c = [(s, "cegf", 1.2, a, tau, None, 0.0, None) for s in SEEDS for a in (0.0, 0.25, 0.5, 0.75) for tau in (0.5, 0.7, 0.9, 0.96)]
    d2c = pd.DataFrame(list(ex.map(_jobs, t2c))); d2c.to_csv(f"{OUT}/e2_thresholds.csv", index=False)
    # ------------------------------------------------------------------ E4
    chg = (900.0, 0.5, 0.9)
    t4 = ([(s, "cegf", 1.0, 0.25, 0.7, None, 0.0, "no change") for s in SEEDS] +
          [(s, "cegf", 1.0, 0.25, 0.7, chg, 0.0, "CEGF (runtime swap)") for s in SEEDS] +
          [(s, "cegf", 1.0, 0.25, 0.7, chg, 30.0, "hard-coded (30 s redeploy)") for s in SEEDS])
    d4 = pd.DataFrame(list(ex.map(_jobs, t4))); d4.to_csv(f"{OUT}/e3_flex.csv", index=False)

    # ------------------------------------------------------------------ tables
    L = []
    def tab(name, header, rows, cols, caption, label):
        s = ["\\begin{table}[htbp]\\scriptsize\\centering", f"\\caption{{{caption}}}\\label{{{label}}}",
             "\\begin{tabular}{" + "l" * 1 + "r" * header.count(" & ") + "}", "\\toprule", header, "\\midrule"]
        s += rows; s += ["\\bottomrule", "\\end{tabular}", "\\end{table}"]
        open(f"{OUT}/{name}.tex", "w", encoding="utf-8").write("\n".join(s))

    M = [("TUDR", "Timely-useful (\\%)", 100, 1), ("uplink_MB", "Uplink (MB)", 1, 0), ("edge_wait_mean", "Edge wait (s)", 1, 2),
         ("stale_drops", "Stale drops", 1, 0), ("loss_useful_readings", "Useful-read.\\ loss (\\%)", 100, 1),
         ("energy_J_per_sensor_h", "Sensor energy (J/h)", 1, 2), ("unencrypted_pct", "Unenc.\\ (\\%)", 1, 0)]
    rows = []
    for sc in (1.0, 1.5):
        for m in ("UG", "SS", "CEGF"):
            d = d1[(d1["mode"] == m) & (d1.scale == sc)]
            rows.append(f"{m} (x{sc})" + "".join(" & " + fmt(d[c] * mult, dec) for c, _, mult, dec in M) + " \\\\")
    tab("tab_e1_df1", "Config. & " + " & ".join(h for _, h, _, _ in M) + " \\\\", rows, M,
        "E1a -- DF$_1$ under three configurations (mean $\\pm$ 95\\% CI, 20 seeds); x1.5 = 50\\% more cameras.", "tab:e1-df1")
    M2 = [("TUDR", "Timely-useful (\\%)", 100, 1), ("tta_p95", "p95 time-to-action (s)", 1, 1), ("cloud_delay_p95", "p95 cloud delay (s)", 1, 1),
          ("uplink_MB", "Uplink (MB)", 1, 0), ("energy_J_per_sensor_h", "Sensor energy (J/h)", 1, 2)]
    rows = [f"DF$_{f}$" + "".join(" & " + (fmt(d1b[d1b.flow == f][c] * mult, dec) if not d1b[d1b.flow == f][c].isna().all() else "n/a")
                                  for c, _, mult, dec in M2) + " \\\\" for f in (1, 2, 3, 4)]
    tab("tab_e1_flows", "Flow & " + " & ".join(h for _, h, _, _ in M2) + " \\\\", rows, M2,
        "E1b -- the four developed data flows under CEGF policies (mean $\\pm$ 95\\% CI, 20 seeds).", "tab:e1-flows")
    M3 = [("miss_critical", "Critical misses (\\%)", 1), ("miss_disease", "Disease-job misses (\\%)", 1), ("conf_viol_pct", "Conf.\\ violations (\\%)", 1),
          ("violations_pct", "Policy violations (\\%)", 1), ("lat_p95_irrig", "Irrig.\\ p95 lat.\\ (s)", 2), ("offload_cloud_pct", "Edge$\\to$cloud (\\%)", 1),
          ("fallback_pct", "Fallback (\\%)", 1)]
    for ld in (0.9, 1.2):
        rows = []
        for p in pols:
            d = d2[(d2.policy == p) & (d2.load == ld)]
            rows.append(p.upper() + "".join(" & " + fmt(d[c], dec) for c, _, dec in M3) + " \\\\")
        tab(f"tab_e2_load{str(ld).replace('.', '')}", "Policy & " + " & ".join(h for _, h, _ in M3) + " \\\\", rows, M3,
            f"E2a -- job distribution at edge load {ld} (mean $\\pm$ 95\\% CI, 20 seeds).", f"tab:e2-{ld}")
    rows = []
    for a in (0.0, 0.25, 0.5, 0.75):
        for tau in (0.5, 0.7, 0.9, 0.96):
            d = d2c[(d2c.alpha == a) & (d2c.tau == tau)]
            rows.append(f"{a} / {tau}" + "".join(" & " + fmt(d[c], 1) for c in ("miss_critical", "miss_disease", "fallback_pct", "rejected_pct")) + " \\\\")
    tab("tab_e2_thr", "$\\alpha$ / $\\tau$ & Critical misses (\\%) & Disease-job misses (\\%) & Fallback (\\%) & Rejected (\\%) \\\\", rows, None,
        "E2b -- sensitivity of CEGF to $\\alpha$ and $\\tau$ at load 1.2 (20 seeds).", "tab:e2-thr")
    rows = []
    for lab in ("no change", "CEGF (runtime swap)", "hard-coded (30 s redeploy)"):
        d = d4[d4.policy == lab]
        pre = d[[f"w{w}_miss_crit" for w in (0, 1)]].mean(axis=1); post = d[[f"w{w}_miss_crit" for w in (3, 4, 5)]].mean(axis=1)
        dip = d["w3_done"] / d["w2_done"]
        rows.append(f"{lab} & " + fmt(pre, 1) + " & " + fmt(post, 1) + " & " + fmt(d["violations_pct"], 1) + " & " + fmt(d["conf_viol_pct"], 1) + " \\\\")
    tab("tab_e3", "Setup & Crit.\\ miss pre (\\%) & Crit.\\ miss post (\\%) & Violations (\\%) & Conf.\\ viol.\\ (\\%) \\\\", rows, None,
        "E3 -- policy change at $t$=900\\,s ($\\alpha$: 0.25$\\to$0.5, $\\tau$: 0.7$\\to$0.9). Violations audited against the policy in force at decision time.", "tab:e3")

    # ------------------------------------------------------------------ figures
    plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.3})
    fig, ax = plt.subplots(1, 3, figsize=(11, 3.1))
    g = d1c.groupby("theta")
    ax[0].errorbar(g.TUDR.mean().index, 100 * g.TUDR.mean(), 100 * T975 * g.TUDR.std() / np.sqrt(20), marker="o", label="timely useful (%)")
    ax[0].errorbar(g.recall.mean().index, 100 * g.recall.mean(), marker="s", label="recall of useful (%)")
    ax[0].plot(g.volume_sel.mean().index, 100 * g.volume_sel.mean(), marker="^", label="data forwarded (%)")
    ax[0].set_xlabel(r"entropy threshold $\theta$"); ax[0].legend(fontsize=7); ax[0].set_title("(a) DF$_1$: effect of $\\theta$")
    for mname, st in (("UG", "--"), ("CEGF", "-")):
        gg = d1d[d1d["mode"] == mname].groupby("scale")
        ax[1].errorbar(gg.TUDR.mean().index, 100 * gg.TUDR.mean(), 100 * T975 * gg.TUDR.std() / np.sqrt(20), ls=st, marker="o", label=mname)
        ax[2].plot(gg.edge_wait_mean.mean().index, gg.edge_wait_mean.mean(), ls=st, marker="o", label=mname)
    ax[1].set_xlabel("camera scale (x12)"); ax[1].set_ylabel("timely useful (%)"); ax[1].legend(); ax[1].set_title("(b) workload scaling")
    ax[2].set_xlabel("camera scale (x12)"); ax[2].set_ylabel("mean edge wait (s)"); ax[2].legend(); ax[2].set_title("(c) edge queueing")
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_e1.pdf"); fig.savefig(f"{OUT}/fig_e1.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(1, 3, figsize=(11, 3.1))
    for p, mk in zip(pols, "osv^D"):
        gg = d2[d2.policy == p].groupby("load")
        ax[0].errorbar(gg.miss_critical.mean().index, gg.miss_critical.mean(), T975 * gg.miss_critical.std() / np.sqrt(20), marker=mk, label=p)
        ax[1].errorbar(gg.conf_viol_pct.mean().index, gg.conf_viol_pct.mean(), T975 * gg.conf_viol_pct.std() / np.sqrt(20), marker=mk, label=p)
        ax[2].errorbar(gg.lat_p95_irrig.mean().index, gg.lat_p95_irrig.mean(), marker=mk, label=p)
    ax[0].set_ylabel("critical deadline misses (%)"); ax[1].set_ylabel("confidential jobs on untrusted node (%)")
    ax[2].set_ylabel("irrigation p95 latency (s)"); ax[2].set_yscale("log")
    for a_ in ax: a_.set_xlabel("edge load")
    ax[0].legend(fontsize=7); fig.tight_layout(); fig.savefig(f"{OUT}/fig_e2.pdf"); fig.savefig(f"{OUT}/fig_e2.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(8, 3.1))
    for lab, st in (("no change", ":"), ("CEGF (runtime swap)", "-"), ("hard-coded (30 s redeploy)", "--")):
        d = d4[d4.policy == lab]
        x = [150 + 300 * w for w in range(6)]
        ax[0].plot(x, [d[f"w{w}_miss_crit"].mean() for w in range(6)], ls=st, marker="o", label=lab)
        ax[1].plot(x, [d[f"w{w}_done"].mean() for w in range(6)], ls=st, marker="o", label=lab)
    for a_ in ax: a_.axvline(900, color="k", lw=0.8); a_.set_xlabel("time (s); policy change at 900 s")
    ax[0].set_ylabel("critical misses (%)"); ax[1].set_ylabel("jobs completed / 300 s"); ax[0].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_e3.pdf"); fig.savefig(f"{OUT}/fig_e3.png", dpi=160); plt.close(fig)

    # console summary
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(d1.groupby(["scale", "mode"]).mean(numeric_only=True).round(3).drop(columns=["flow", "theta", "seed"]))
    print(d1b.groupby("flow").mean(numeric_only=True).round(3).drop(columns=["theta", "scale", "seed"]))
    for ld in (0.9, 1.2):
        print("load", ld); print(d2[d2.load == ld].groupby("policy").mean(numeric_only=True)[[c for c, _, _ in M3]].round(2))
    print(d2c.groupby(["alpha", "tau"]).mean(numeric_only=True)[["miss_critical", "miss_all", "fallback_pct", "rejected_pct"]].round(2))
    print(d4.groupby("policy").mean(numeric_only=True)[["violations_pct", "conf_viol_pct", "miss_critical", "swap_us"]].round(2))
    print("eval_us (CEGF):", d2[d2.policy == "cegf"].eval_us.mean())


if __name__ == "__main__":
    main()
