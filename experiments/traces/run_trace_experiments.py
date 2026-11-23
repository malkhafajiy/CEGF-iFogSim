"""Option 2 end to end: replay the real greenhouse trace in BOTH simulators and compare it with synthetic workloads.

Run from the repo root (JDK + experiments/ifogsim/build.ps1 done, trace built):
    python experiments/traces/run_trace_experiments.py
Writes CSVs, figures and a printed summary to experiments/traces/results/.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "farm"), os.path.join(HERE, "..", "ifogsim"), HERE]

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import farm_sim as F  # noqa: E402
import run_ifogsim as R  # noqa: E402
from trace_io import trace_workload  # noqa: E402

OUT = os.path.join(HERE, "results")
os.makedirs(OUT, exist_ok=True)
TRACE = "dataset/greenhouse_challenge_2019/trace/trace.csv"        # relative to the repo root (java cwd)
SEEDS = list(range(1, 21))
THETAS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
T = 2.093
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
KEYS = ["TUDR", "TUDR_read", "recall_read", "volume_sel_read", "useful_read_frac", "uplink_MB", "loss_useful_readings", "energy_J_per_sensor_h"]


def py_run(a):
    src, mode, cam, th, seed = a
    if src == "trace":
        r = F.run_df(seed, 1, mode, th, cam, workload=trace_workload(seed, n_cam=int(round(12 * cam))))
    else:
        r = F.run_df(seed, 1, mode, th, cam)
    return dict(sim="python", src=src, mode=mode, cam=cam, theta=th, seed=seed, **{k: float(r[k]) for k in KEYS})


def main():
    # ---------------- Python simulator
    pt = [(s_, m, c, 0.3, s) for s_ in ("trace", "synthetic") for m in ("UG", "SS", "CEGF") for c in (1.0, 1.5) for s in SEEDS]
    pt += [(s_, "CEGF", 1.0, th, s) for s_ in ("trace", "synthetic") for th in THETAS for s in SEEDS]
    with ThreadPoolExecutor(max_workers=8) as ex:
        py = pd.DataFrame(list(ex.map(py_run, pt)))
    print("python runs:", len(py), flush=True)
    # ---------------- iFogSim2
    jt = [dict(scenario="data", mode=m, cam=c, seed=s, trace=TRACE, src="trace") for m in ("UG", "SS", "CEGF") for c in (1.0, 1.5) for s in SEEDS]
    jt += [dict(scenario="data", mode="CEGF", theta=th, seed=s, trace=TRACE, src="trace") for th in THETAS for s in SEEDS]
    jt += [dict(scenario="data", mode="CEGF", theta=th, seed=s, src="synthetic") for th in THETAS for s in SEEDS]
    jt += [dict(scenario="data", mode=m, cam=c, seed=s, src="synthetic") for m in ("UG", "SS", "CEGF") for c in (1.0, 1.5) for s in SEEDS]

    def jrun(a):
        a = dict(a); src = a.pop("src")
        r = R.run(a)
        r["src"] = src; r["sim"] = "ifogsim"
        return r
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        ij = pd.DataFrame(list(ex.map(jrun, jt)))
    print("ifogsim runs:", len(ij), flush=True)
    for d in (py, ij):
        d["theta"] = d["theta"].fillna(0.3) if "theta" in d else 0.3
        d["cam"] = d["cam"].fillna(1.0) if "cam" in d else 1.0
    allr = pd.concat([py[["sim", "src", "mode", "cam", "theta", "seed"] + KEYS], ij[["sim", "src", "mode", "cam", "theta", "seed"] + KEYS]])
    allr.to_csv(os.path.join(OUT, "trace_vs_synthetic.csv"), index=False)

    def mc(d, col):
        return d[col].mean(), T * d[col].std() / np.sqrt(len(d))

    # ---------------- summary tables
    pd.set_option("display.width", 220); pd.set_option("display.max_columns", 20)
    nom = allr[(allr.cam == 1.0) & (allr.theta == 0.3)]
    print("\nDF1, theta=0.3, 12 cameras (mean over seeds):")
    print(nom.groupby(["sim", "src", "mode"])[["TUDR", "TUDR_read", "recall_read", "volume_sel_read", "uplink_MB", "energy_J_per_sensor_h"]].mean().round(3))
    print("\nreadings-only recall / forwarded vs theta (CEGF, 12 cameras):")
    th = allr[(allr["mode"] == "CEGF") & (allr.cam == 1.0)]
    print(th.groupby(["sim", "src", "theta"])[["recall_read", "volume_sel_read"]].mean().round(3).unstack("theta").round(2).to_string())

    # ---------------- figures
    plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(1, 3, figsize=(12.5, 3.6))
    for (sim, src, ls, mk, c) in [("ifogsim", "trace", "-", "o", BLUE), ("python", "trace", "--", "s", BLUE),
                                  ("ifogsim", "synthetic", "-", "o", ORANGE), ("python", "synthetic", "--", "s", ORANGE)]:
        d = th[(th.sim == sim) & (th.src == src)]
        g = d.groupby("theta")
        lab = f"{'real trace' if src == 'trace' else 'synthetic'} ({'iFogSim2' if sim == 'ifogsim' else 'Python'})"
        ax[0].plot(g.recall_read.mean().index, 100 * g.recall_read.mean(), ls=ls, marker=mk, ms=4, color=c, label=lab)
        ax[1].plot(g.volume_sel_read.mean().index, 100 * g.volume_sel_read.mean(), ls=ls, marker=mk, ms=4, color=c, label=lab)
        ax[2].plot(100 * g.volume_sel_read.mean(), 100 * g.recall_read.mean(), ls=ls, marker=mk, ms=4, color=c, label=lab)
    ax[0].set_ylabel("recall of useful readings (%)"); ax[0].set_xlabel("entropy threshold theta")
    ax[1].set_ylabel("readings forwarded (%)"); ax[1].set_xlabel("entropy threshold theta")
    ax[2].set_xlabel("readings forwarded (%)"); ax[2].set_ylabel("recall of useful readings (%)")
    ax[0].legend(fontsize=7, frameon=False)
    ax[0].set_title("(a) recall", loc="left", fontsize=10); ax[1].set_title("(b) volume", loc="left", fontsize=10); ax[2].set_title("(c) trade-off", loc="left", fontsize=10)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_trace_theta.png"), dpi=160); fig.savefig(os.path.join(OUT, "fig_trace_theta.pdf")); plt.close(fig)

    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    modes = [("UG", "Ungoverned", ORANGE), ("SS", "All-HTTPS", YELLOW), ("CEGF", "CEGF", BLUE)]
    for k, (sim, title) in enumerate([("ifogsim", "iFogSim2"), ("python", "Python simulator")]):
        a = ax[k]
        for j, cam in enumerate((1.0, 1.5)):
            for i, (m, lab, c) in enumerate(modes):
                for h, src in enumerate(("synthetic", "trace")):
                    d = allr[(allr.sim == sim) & (allr.src == src) & (allr["mode"] == m) & (allr.cam == cam) & (allr.theta == 0.3)]
                    mean, e = mc(d, "TUDR")
                    x = j * 8 + i * 2.3 + h * 0.9
                    a.bar(x, 100 * mean, 0.85, color=c, alpha=1.0 if src == "trace" else 0.45, hatch="" if src == "trace" else "//", edgecolor="white",
                          label=f"{lab}" if (j == 0 and h == 1) else None)
        a.set_xticks([3.2, 11.2]); a.set_xticklabels(["12 cameras", "18 cameras"]); a.set_ylabel("useful items on time (%)")
        a.set_title(f"{title}  (solid = real trace, hatched = synthetic)", loc="left", fontsize=9); a.grid(axis="x", visible=False)
    ax[0].legend(fontsize=8, frameon=False, loc="lower left")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_trace_modes.png"), dpi=160); fig.savefig(os.path.join(OUT, "fig_trace_modes.pdf")); plt.close(fig)
    print("figures written to", OUT)


if __name__ == "__main__":
    main()
