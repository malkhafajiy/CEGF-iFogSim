"""Complete experiment pipeline (iFogSim2 only; the Python simulator is not used).

  Stage 1  workload  : download the real greenhouse data, build the replayable trace, describe it
  Stage 2  policies  : validate the ODRL policies and cross-check the simulator's decisions with OVAL
  Stage 3  simulation: run the iFogSim2 experiments (real-trace workload) and draw the figures
  Summary            : results/RUN_SUMMARY.md

Everything is written under results/ (01_workload, 02_policy_validation, 03_simulation, RUN_SUMMARY.md).
Run from the repository root:   python experiments/run_pipeline.py [--stages all|workload,policies,simulation,summary] [--seeds 20]
Prerequisites: JDK, git, pip install numpy pandas matplotlib py7zr rdflib pyshacl requests python-dateutil jinja2
"""
import argparse
import datetime
import glob
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RES = os.path.join(ROOT, "results")
D1, D2, D3 = (os.path.join(RES, x) for x in ("01_workload", "02_policy_validation", "03_simulation"))
TRACE_DIR = os.path.join(ROOT, "dataset", "greenhouse_challenge_2019", "trace")
TRACE_REL = "dataset/greenhouse_challenge_2019/trace/trace.csv"          # relative to the repo root (the JVM's cwd)
POLICIES = os.path.join(HERE, "odrl_engine", "policies.json")
JAVA = (glob.glob(r"C:\Program Files\Microsoft\jdk-*\bin\java.exe") or ["java"])[0]
CP = os.pathsep.join(glob.glob(os.path.join(ROOT, "jars", "**", "*.jar"), recursive=True) + [os.path.join(HERE, "ifogsim", "build")])

# colours: validated default categorical palette (slots 1-5, light surface)
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e3e2de", "#fcfcfb"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": SURF, "axes.facecolor": SURF})
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 8: 2.31, 10: 2.26, 15: 2.14, 20: 2.09, 30: 2.05}


def tcrit(n):
    k = max([k for k in T95 if k <= max(1, n - 1)] or [1])
    return T95[k]


def mean_ci(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return (x.mean(), tcrit(len(x)) * x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else (x.mean() if len(x) else np.nan, 0.0)


def save(fig, folder, name):
    os.makedirs(folder, exist_ok=True)
    fig.savefig(os.path.join(folder, name + ".png"), dpi=170, bbox_inches="tight")
    fig.savefig(os.path.join(folder, name + ".pdf"), bbox_inches="tight")
    plt.close(fig)
    print("  figure:", os.path.relpath(os.path.join(folder, name + ".png"), ROOT), flush=True)


def sh(*cmd, **kw):
    return subprocess.run(cmd, check=True, cwd=kw.pop("cwd", ROOT), **kw)


# ======================================================================= build
def stage_build():
    print("[build] compiling iFogSim2 + CEGF code", flush=True)
    out = os.path.join(HERE, "ifogsim", "build")
    os.makedirs(out, exist_ok=True)
    files = [f for f in glob.glob(os.path.join(ROOT, "src", "**", "*.java"), recursive=True)]
    argfile = os.path.join(out, "files.txt")
    open(argfile, "w", encoding="utf-8").write(chr(10).join(chr(34) + f.replace(chr(92), "/") + chr(34) for f in files))
    javac = os.path.join(os.path.dirname(JAVA), "javac.exe") if JAVA != "java" else "javac"
    jars = os.pathsep.join(glob.glob(os.path.join(ROOT, "jars", "**", "*.jar"), recursive=True))
    p = subprocess.run([javac, "-nowarn", "-encoding", "UTF-8", "-cp", jars, "-d", out, "@" + argfile], capture_output=True, text=True, cwd=ROOT)
    if p.returncode:
        sys.exit("build failed: " + p.stderr[-2000:])
    print(f"  {len(glob.glob(os.path.join(out, '**', '*.class'), recursive=True))} classes", flush=True)


# ======================================================================= stage 1
def stage_workload():
    print("[1/3] workload: real greenhouse data -> trace", flush=True)
    sh(sys.executable, "-P", os.path.join(HERE, "traces", "fetch_greenhouse.py"))
    if os.path.isdir(TRACE_DIR):
        for f in os.listdir(TRACE_DIR):
            os.remove(os.path.join(TRACE_DIR, f))
    sh(sys.executable, "-P", os.path.join(HERE, "traces", "build_trace.py"))
    os.makedirs(D1, exist_ok=True)
    tr = pd.read_csv(os.path.join(TRACE_DIR, "trace.csv"))
    meta = json.load(open(os.path.join(TRACE_DIR, "trace_meta.json")))
    json.dump(meta, open(os.path.join(D1, "trace_meta.json"), "w"), indent=1)
    tr["kindch"] = tr.channel.map(lambda c: "substrate water content" if c.startswith("WC") else "substrate EC" if c.startswith("EC")
                                  else "substrate temperature" if c.startswith("t_slab") else "greenhouse climate")
    by_ch = tr.groupby("kindch").agg(streams=("stream_id", "nunique"), readings=("value", "size"), useful_fraction=("useful", "mean"), mean_entropy=("entropy", "mean")).reset_index()
    by_ch.to_csv(os.path.join(D1, "workload_by_channel_type.csv"), index=False)

    fig, ax = plt.subplots(2, 3, figsize=(14, 7))
    # (a) example streams
    a = ax[0][0]
    ex = [("WC_slab1", "substrate water content"), ("t_slab1", "substrate temperature"), ("EC_slab1", "substrate EC"), ("Tair", "air temperature")]
    for (ch, lab), col in zip(ex, (BLUE, ORANGE, AQUA, MAGENTA)):
        d = tr[tr.channel == ch]
        d = d[d.stream_id == d.stream_id.iloc[0]]
        z = (d.value - d.value.mean()) / (d.value.std() + 1e-9)
        a.plot(d.t_ms / 60000, z, color=col, lw=1.2, label=lab)
        a.scatter(d.t_ms[d.useful == 1] / 60000, z[d.useful == 1], s=16, color=col, edgecolor="white", zorder=3)
    a.set_xlabel("simulated minutes (1 min = 10 real minutes)"); a.set_ylabel("z-scored value; dots = useful readings")
    a.set_title("(a) Real sensor streams and their useful readings", loc="left", fontsize=10); a.legend(fontsize=7, frameon=False)
    # (b) over time
    a = ax[0][1]
    b = (tr.t_ms // 300000).astype(int)
    g = tr.groupby(b).agg(useful=("useful", "mean"), entropy=("entropy", "mean"))
    a.bar(g.index * 5 + 2.5, 100 * g.useful, 4.2, color=BLUE, label="useful readings (%)")
    a.plot(g.index * 5 + 2.5, 100 * g.entropy, color=ORANGE, marker="o", ms=4, label="mean entropy score x100")
    a.set_xlabel("simulated minutes"); a.set_title("(b) Useful share and entropy over the window", loc="left", fontsize=10); a.legend(fontsize=8, frameon=False)
    sunrise_sim = (meta["sunrise_hour"] - meta["real_start_hour"]) * 3600 / meta["params"]["speedup"] / 60
    if 0 < sunrise_sim < meta["sim_horizon_s"] / 60:
        a.axvline(sunrise_sim, color=INK2, ls=":", lw=1); a.text(sunrise_sim + 0.5, a.get_ylim()[1] * 0.92, "sunrise", fontsize=8, color=INK2)
    # (c) histogram
    a = ax[0][2]
    bins = np.linspace(0, 1, 26)
    a.hist(tr.entropy[tr.useful == 0], bins, color=ORANGE, alpha=0.75, label=f"not useful (n={int((tr.useful == 0).sum())})")
    a.hist(tr.entropy[tr.useful == 1], bins, color=BLUE, alpha=0.75, label=f"useful (n={int((tr.useful == 1).sum())})")
    a.set_yscale("log"); a.set_xlabel("entropy score"); a.set_ylabel("readings")
    a.set_title(f"(c) Entropy separates useful readings only partly (AUC {meta['auc_entropy_vs_useful']:.2f})", loc="left", fontsize=10); a.legend(fontsize=8, frameon=False)
    # (d) theta preview
    a = ax[1][0]
    th = sorted(meta["theta_sweep"], key=float)
    a.plot([float(t) for t in th], [100 * meta["theta_sweep"][t]["recall"] for t in th], color=BLUE, marker="o", label="recall of useful readings")
    a.plot([float(t) for t in th], [100 * meta["theta_sweep"][t]["forwarded"] for t in th], color=ORANGE, marker="s", label="readings forwarded")
    a.set_xlabel("entropy threshold θ"); a.set_ylabel("%"); a.set_title("(d) What the filter would keep (trace only, no network)", loc="left", fontsize=10); a.legend(fontsize=8, frameon=False)
    # (e) by channel type
    a = ax[1][1]
    order = by_ch.sort_values("useful_fraction")
    a.barh(order.kindch, 100 * order.useful_fraction, color=AQUA)
    for i, (v, s) in enumerate(zip(order.useful_fraction, order.streams)):
        a.text(100 * v + 0.3, i, f"{100 * v:.0f}%  ({s} streams)", va="center", fontsize=8)
    a.set_xlabel("useful readings (%)"); a.set_title("(e) Which sensors carry information", loc="left", fontsize=10); a.grid(axis="y", visible=False)
    a.set_xlim(0, max(100 * order.useful_fraction) * 1.5)
    # (f) facts
    a = ax[1][2]; a.axis("off")
    facts = [("Source", "Autonomous Greenhouse Challenge 2019\n(4TU.ResearchData, CC0)"), ("Crop", "cherry tomato, 6 compartments"),
             ("Window", f"{meta['params']['real_start']} + {meta['params']['real_hours']:.0f} h real time"),
             ("Replay", f"{meta['params']['speedup']:.0f}x faster: {meta['sim_horizon_s'] / 60:.0f} simulated minutes"),
             ("Streams / readings", f"{meta['n_streams']} / {meta['n_readings']}"), ("Useful readings", f"{100 * meta['useful_fraction']:.1f}%"),
             ("Entropy vs useful", f"AUC {meta['auc_entropy_vs_useful']:.2f}")]
    for i, (k, v) in enumerate(facts):
        a.text(0.0, 0.95 - i * 0.135, k, fontsize=10, fontweight="bold", va="top"); a.text(0.52, 0.95 - i * 0.135, v, fontsize=10, va="top")
    a.set_title("(f) The workload", loc="left", fontsize=10)
    fig.suptitle("Stage 1 - Real greenhouse workload", fontsize=13, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(); save(fig, D1, "workload_overview")
    return dict(meta=meta)


# ======================================================================= stage 2
def stage_policies():
    print("[2/3] policies: ODRL validation + OVAL cross-check", flush=True)
    spec = importlib.util.spec_from_file_location("crosscheck_oval", os.path.join(HERE, "odrl_engine", "crosscheck_oval.py"))
    cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)
    os.makedirs(D2, exist_ok=True)
    r = cc.run()
    json.dump(dict(validation=r["validation"], agree=r["agree"], total=r["total"], alpha=r["alpha"], tau=r["tau"], theta=r["theta"]),
              open(os.path.join(D2, "policy_validation.json"), "w"), indent=1)
    cases = pd.DataFrame(r["cases"]); cases.to_csv(os.path.join(D2, "oval_vs_simulator_decisions.csv"), index=False)
    print(f"  SHACL: {r['validation']}\n  decisions identical: {r['agree']}/{r['total']}", flush=True)

    fig = plt.figure(figsize=(14, 6.6))
    gs = fig.add_gridspec(2, 5, width_ratios=[1, 1, 1, 1, 1.5], hspace=0.55, wspace=0.55)
    rec = cases[cases.policy == "job_recipient"].copy()
    for c in ("critical", "confidential"):
        rec[c] = rec[c].astype(str).str.lower() == "true"
    av = sorted(rec.availability.astype(float).unique()); tr_ = sorted(rec.trust.astype(float).unique())
    combos = [(True, False, "critical job"), (False, True, "confidential job"), (True, True, "critical + confidential"), (False, False, "neither")]
    cmap = matplotlib.colors.ListedColormap([ORANGE, BLUE])
    for k, (cr, cf, title) in enumerate(combos):
        a = fig.add_subplot(gs[k // 2, (k % 2) * 2:(k % 2) * 2 + 2])
        d = rec[(rec.critical == cr) & (rec.confidential == cf)]
        M = np.zeros((len(av), len(tr_))); X = np.zeros_like(M)
        for _, row in d.iterrows():
            i, j = av.index(float(row.availability)), tr_.index(float(row.trust))
            M[i, j] = bool(row.oval); X[i, j] = row.oval != row.simulator
        a.imshow(M, cmap=cmap, vmin=0, vmax=1, aspect="auto", origin="lower")
        a.set_xticks(range(len(tr_))); a.set_xticklabels([f"{t:g}" for t in tr_], rotation=45, fontsize=7)
        a.set_yticks(range(len(av))); a.set_yticklabels([f"{x:g}" for x in av], fontsize=7)
        a.set_xlabel("recipient trust"); a.set_ylabel("recipient availability"); a.grid(False)
        a.axhline(av.index(0.25) - 0.5, color="white", lw=1.2); a.axvline(tr_.index(0.7) - 0.5, color="white", lw=1.2)
        for i, j in zip(*np.where(X > 0)):
            a.text(j, i, "x", ha="center", va="center", color="white", fontweight="bold")
        a.set_title(title, loc="left", fontsize=9)
    a = fig.add_subplot(gs[:, 4])
    en = cases[cases.policy == "entropy"].copy(); en["entropy"] = en.entropy.astype(float)
    a.step(en.entropy, en.oval.astype(int), where="post", color=BLUE, lw=2, label="OVAL")
    a.scatter(en.entropy, en.simulator.astype(int) * 0.96 + 0.02, color=ORANGE, marker="+", s=60, label="simulator (OdrlEval)", zorder=3)
    a.axvline(r["theta"], color=INK2, ls=":", lw=1); a.text(r["theta"] + 0.02, 0.55, f"θ = {r['theta']}", fontsize=8, color=INK2)
    a.set_xlabel("reading entropy"); a.set_yticks([0, 1]); a.set_yticklabels(["not selected", "selected"]); a.set_ylim(-0.1, 1.15)
    a.set_title("Data-selection policy", loc="left", fontsize=9); a.legend(fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.17))
    handles = [matplotlib.patches.Patch(color=BLUE, label="move permitted"), matplotlib.patches.Patch(color=ORANGE, label="move prohibited")]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.05, -0.01), ncol=2, frameon=False, fontsize=9)
    v = r["validation"]
    sub = f"SHACL validation: {sum(x['valid_ODRL'] for x in v.values())}/{len(v)} policies valid ODRL, {sum(x['errors'] for x in v.values())} errors | decisions identical in {r['agree']}/{r['total']} cases (white lines: α = {r['alpha']}, τ = {r['tau']})"
    fig.suptitle("Stage 2 - ODRL policies checked against the independent OVAL evaluator", fontsize=13, fontweight="bold", x=0.01, ha="left", y=1.0)
    fig.text(0.01, 0.94, sub, fontsize=9, color=INK2)
    save(fig, D2, "policy_validation")
    return dict(agree=r["agree"], total=r["total"], validation=r["validation"])


# ======================================================================= stage 3
def jrun(task):
    meta, args = task
    cmd = [JAVA, "-cp", CP, "org.fog.cegf.FarmExperiment", f"policies={POLICIES}"] + [f"{k}={v}" for k, v in args.items()]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1500)
    m = re.search(r"^RESULT (.*)$", p.stdout, re.M)
    if not m:
        raise RuntimeError(f"no result for {args}\n{p.stdout[-400:]}\n{p.stderr[-400:]}")
    return {**meta, **{k: v for k, v in args.items() if k not in ("trace",)}, **{k: float(v) for k, v in (kv.split("=") for kv in m.group(1).split(","))}}


def batch(tasks, name):
    os.makedirs(os.path.join(D3, "raw"), exist_ok=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        df = pd.DataFrame(list(ex.map(jrun, tasks)))
    df.to_csv(os.path.join(D3, "raw", name + ".csv"), index=False)
    print(f"  {name}: {len(df)} runs in {time.time() - t0:.0f} s", flush=True)
    return df


POLS = ["cegf", "greedy", "random", "static", "cloud"]
VARIANTS = [("UG", "Ungoverned (plain MQTT)", dict(mode="UG")), ("SS", "All-HTTPS", dict(mode="SS")),
            ("CEGF03", "CEGF θ=0.3", dict(mode="CEGF", theta=0.3)), ("CEGF01", "CEGF θ=0.1", dict(mode="CEGF", theta=0.1))]


def stage_figures():
    print("[figures] redrawing stage-3 figures from results/03_simulation/raw", flush=True)
    d = [pd.read_csv(os.path.join(D3, "raw", n + ".csv")) for n in ("e1_modes_real_trace", "e1_theta_sweep", "e2_jobs_vs_load", "e2_thresholds", "e3_policy_change")]
    figures_simulation(*d, VARIANTS, POLS)


def stage_simulation(seeds):
    print("[3/3] simulation: iFogSim2 experiments", flush=True)
    S = list(range(1, seeds + 1))
    TR = dict(trace=TRACE_REL)
    # ---- E1: data flow on the real trace
    variants = [("UG", "Ungoverned (plain MQTT)", dict(mode="UG")), ("SS", "All-HTTPS", dict(mode="SS")),
                ("CEGF03", "CEGF θ=0.3", dict(mode="CEGF", theta=0.3)), ("CEGF01", "CEGF θ=0.1", dict(mode="CEGF", theta=0.1))]
    e1 = batch([({"variant": v, "label": lab, "workload": "real trace"}, dict(scenario="data", cam=c, seed=s, **TR, **kw)) for s in S for v, lab, kw in variants for c in (1.0, 1.5)], "e1_modes_real_trace")
    th = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    e1t = batch([({"workload": w}, dict(scenario="data", mode="CEGF", theta=t, seed=s, **(TR if w == "real trace" else {}))) for s in S for t in th for w in ("real trace", "synthetic")], "e1_theta_sweep")
    # ---- E2: job distribution
    pols = ["cegf", "greedy", "random", "static", "cloud"]
    e2 = batch([({}, dict(scenario="jobs", policy=p, load=l, seed=s)) for s in S for p in pols for l in (0.6, 0.9, 1.2, 1.5)], "e2_jobs_vs_load")
    e2t = batch([({}, dict(scenario="jobs", policy="cegf", load=1.2, alpha=a, tau=t, seed=s)) for s in S for a in (0.0, 0.25, 0.5, 0.75) for t in (0.5, 0.7, 0.9, 0.96)], "e2_thresholds")
    # ---- E3: policy change at run time
    ch = dict(scenario="jobs", policy="cegf", load=1.0, change_t=900)
    e3 = batch([({"variant": "No change"}, dict(**ch, alpha2=0.25, tau2=0.7, seed=s)) for s in S] +
               [({"variant": "Runtime swap (CEGF)"}, dict(**ch, alpha2=0.5, tau2=0.9, seed=s)) for s in S] +
               [({"variant": "Hard-coded, 30 s redeploy"}, dict(**ch, alpha2=0.5, tau2=0.9, outage_s=30, seed=s)) for s in S], "e3_policy_change")
    figures_simulation(e1, e1t, e2, e2t, e3, variants, pols)
    return dict(e1=e1, e1t=e1t, e2=e2, e2t=e2t, e3=e3)


def figures_simulation(e1, e1t, e2, e2t, e3, variants, pols):
    cols = {"UG": ORANGE, "SS": YELLOW, "CEGF03": BLUE, "CEGF01": AQUA}
    # ---------------- Fig 1: data flow, real trace
    fig, ax = plt.subplots(1, 3, figsize=(14, 4.1))
    panels = [("TUDR", "Useful items delivered on time (%)", 100, "{:.0f}"), ("recall_read", "Useful sensor readings that were sent (%)", 100, "{:.0f}"),
              ("uplink_MB", "Uplink traffic (MB per hour)", 1, "{:.1f}")]
    for a, (col, title, mult, fmt) in zip(ax, panels):
        for j, cam in enumerate((1.0, 1.5)):
            for i, (v, lab, _) in enumerate(variants):
                d = e1[(e1.variant == v) & (e1.cam == cam)][col] * mult
                m, e = mean_ci(d)
                x = j * 5.2 + i * 1.1
                a.bar(x, m, 0.95, color=cols[v], label=lab if j == 0 else None)
                a.errorbar(x, m, e, color=INK, lw=0.8, capsize=2)
                a.text(x, m + (e if e == e else 0) + (2 if mult == 100 else 0.5), fmt.format(m), ha="center", fontsize=7.5)
        a.set_xticks([1.65, 6.85]); a.set_xticklabels(["12 cameras\n(nominal)", "18 cameras\n(+50 % load)"]); a.set_title(title, loc="left", fontsize=10); a.grid(axis="x", visible=False)
    ax[0].set_ylim(0, 115); ax[1].set_ylim(0, 115)
    fig.legend(*ax[0].get_legend_handles_labels(), loc="lower center", ncol=4, frameon=False, fontsize=9, bbox_to_anchor=(0.5, -0.08))
    fig.suptitle("E1 - Data flow on the real greenhouse workload (iFogSim2, mean ± 95 % CI)", fontsize=12, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(); save(fig, D3, "fig1_data_flow_real_trace")

    # ---------------- Fig 2: theta sweep, real vs synthetic
    fig, ax = plt.subplots(1, 3, figsize=(14, 4.0))
    for w, c, ls, mk in (("real trace", BLUE, "-", "o"), ("synthetic", ORANGE, "--", "s")):
        d = e1t[e1t.workload == w]; g = d.groupby("theta")
        ax[0].plot(g.recall_read.mean().index, 100 * g.recall_read.mean(), color=c, ls=ls, marker=mk, ms=4, label=w)
        ax[1].plot(g.volume_sel_read.mean().index, 100 * g.volume_sel_read.mean(), color=c, ls=ls, marker=mk, ms=4, label=w)
        ax[2].plot(100 * g.volume_sel_read.mean(), 100 * g.recall_read.mean(), color=c, ls=ls, marker=mk, ms=4, label=w)
    for a, (x, y, t) in zip(ax, [("entropy threshold θ", "useful readings sent (%)", "Recall"), ("entropy threshold θ", "readings sent (%)", "Volume"), ("readings sent (%)", "useful readings sent (%)", "Trade-off")]):
        a.set_xlabel(x); a.set_ylabel(y); a.set_title(t, loc="left", fontsize=10)
    ax[0].legend(fontsize=8, frameon=False)
    ax[2].plot([0, 100], [0, 100], color=INK2, ls=":", lw=1); ax[2].text(55, 47, "random selection", fontsize=7.5, color=INK2, rotation=33)
    fig.suptitle("E1 - How well does the entropy filter work? Real greenhouse data vs the synthetic assumption", fontsize=12, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(); save(fig, D3, "fig2_entropy_threshold")

    # ---------------- Fig 3: job distribution vs load
    PC = {"cegf": (BLUE, "o", "CEGF"), "greedy": (ORANGE, "s", "Greedy"), "random": (AQUA, "^", "Random"), "static": (YELLOW, "D", "Static"), "cloud": (MAGENTA, "v", "Cloud-only")}
    fig, ax = plt.subplots(2, 2, figsize=(11.5, 7.2))
    for a, (col, yl, log) in zip(ax.ravel(), [("violations_pct", "policy violations (% of jobs)", False), ("miss_critical", "critical deadline misses (%)", False),
                                              ("lat_p95_irrig", "irrigation p95 latency (s)", True), ("conf_viol_pct", "confidential jobs on an untrusted node (%)", False)]):
        for p in pols:
            c, mk, lab = PC[p]; g = e2[e2.policy == p].groupby("load")[col]
            a.errorbar(g.mean().index, g.mean(), g.std() * 2.09 / np.sqrt(g.count()), color=c, marker=mk, ms=4.5, lw=2.2 if p == "cegf" else 1.3, capsize=2, label=lab, zorder=3 if p == "cegf" else 2)
        a.set_xlabel("edge load (1.0 = edge capacity)"); a.set_ylabel(yl)
        if log: a.set_yscale("log")
    ax[0][0].legend(fontsize=8, frameon=False)
    fig.suptitle("E2 - Job distribution under the job-recipient policy (iFogSim2, mean ± 95 % CI)", fontsize=12, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(); save(fig, D3, "fig3_job_distribution")

    # ---------------- Fig 4: alpha x tau
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seq", ["#eaf1fb", "#2a78d6", "#0d2f63"])
    for a, (col, title) in zip(ax, [("miss_critical", "Critical deadline misses (%)"), ("rejected_pct", "Jobs rejected (%)")]):
        piv = e2t.groupby(["alpha", "tau"])[col].mean().unstack()
        a.imshow(piv.values, cmap=cmap, aspect="auto", vmin=0, vmax=max(20, np.nanmax(piv.values)), origin="lower")
        a.set_xticks(range(len(piv.columns))); a.set_xticklabels(piv.columns); a.set_yticks(range(len(piv.index))); a.set_yticklabels(piv.index)
        a.set_xlabel("trust threshold τ"); a.set_ylabel("availability threshold α"); a.grid(False); a.set_title(title, loc="left", fontsize=10)
        for i in range(piv.shape[0]):
            for j in range(piv.shape[1]):
                v = piv.values[i, j]; a.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8.5, color="white" if v > 9 else INK)
    fig.suptitle("E2 - Sensitivity to the policy thresholds (edge load 1.2)", fontsize=12, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(); save(fig, D3, "fig4_threshold_sensitivity")

    # ---------------- Fig 5: policy change
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    names = ["No change", "Runtime swap (CEGF)", "Hard-coded, 30 s redeploy"]
    for i, n in enumerate(names):
        d = e3[e3.variant == n]
        for j, (col, c, lab) in enumerate([("miss_crit_pre", "#9fb9e0", "before change"), ("miss_crit_post", BLUE, "after change")]):
            m, e = mean_ci(d[col]); x = i * 3 + j
            ax.bar(x, m, 0.9, color=c, label=lab if i == 0 else None); ax.errorbar(x, m, e, color=INK, lw=0.8, capsize=2)
            ax.text(x, m + e + 0.15, f"{m:.1f}", ha="center", fontsize=8.5)
    ax.set_xticks([i * 3 + 0.5 for i in range(3)]); ax.set_xticklabels([n.replace(", ", ",\n") for n in names]); ax.set_ylabel("critical deadline misses (%)")
    ax.grid(axis="x", visible=False); ax.legend(fontsize=8, frameon=False)
    ax.set_title("E3 - Policy tightened at t = 900 s (α 0.25→0.5, τ 0.7→0.9)", loc="left", fontsize=11, fontweight="bold")
    fig.tight_layout(); save(fig, D3, "fig5_policy_change")


# ======================================================================= summary
def md_table(df):
    return "\n".join(["| " + " | ".join(df.columns) + " |", "|" + "|".join("---" for _ in df.columns) + "|"] + ["| " + " | ".join(str(x) for x in r) + " |" for r in df.values])


def read_raw(name):
    p = os.path.join(D3, "raw", name + ".csv")
    return pd.read_csv(p) if os.path.exists(p) else None


def stage_summary(seeds):
    print("[summary] writing results/RUN_SUMMARY.md", flush=True)
    L = []
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    jv = subprocess.run([JAVA, "-version"], capture_output=True, text=True).stderr.splitlines()[0]
    L += ["# Run summary", "", f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M} | git {commit} | {jv} | Python {platform.python_version()} | {seeds} seeds per configuration | iFogSim2 only (the Python simulator was not used).", ""]
    # stage 1
    mp = os.path.join(D1, "trace_meta.json")
    if os.path.exists(mp):
        m = json.load(open(mp))
        L += ["## Stage 1 - Real workload", "", f"Autonomous Greenhouse Challenge 2019 (cherry tomato, 4TU.ResearchData, CC0). Window {m['params']['real_start']} + {m['params']['real_hours']:.0f} h replayed {m['params']['speedup']:.0f}x faster = {m['sim_horizon_s'] / 60:.0f} simulated minutes.",
              "", f"* {m['n_streams']} sensor streams, {m['n_readings']} readings; {100 * m['useful_fraction']:.1f}% of readings are useful (dead-band label).",
              f"* The entropy score separates useful from other readings only partly: AUC {m['auc_entropy_vs_useful']:.2f}, mean score {m['mean_entropy_useful']:.2f} (useful) vs {m['mean_entropy_other']:.2f} (other).",
              f"* At θ = 0.3 the filter would keep {100 * m['theta_sweep']['0.3']['recall']:.0f}% of the useful readings while forwarding {100 * m['theta_sweep']['0.3']['forwarded']:.0f}% of all readings.", "",
              "![workload](01_workload/workload_overview.png)", ""]
    # stage 2
    pj = os.path.join(D2, "policy_validation.json")
    if os.path.exists(pj):
        p = json.load(open(pj))
        L += ["## Stage 2 - Policy validation (OVAL)", "", f"* SHACL validation of the two ODRL policies: " + ", ".join(f"{k}: {'valid' if v['valid_ODRL'] else 'INVALID'} ({v['errors']} errors, {v['warnings']} warnings)" for k, v in p["validation"].items()) + ".",
              f"* The simulator's evaluator and OVAL give identical decisions on {p['agree']}/{p['total']} test cases (thresholds α={p['alpha']}, τ={p['tau']}, θ={p['theta']}; boundary values included).", "",
              "![policies](02_policy_validation/policy_validation.png)", ""]
    # stage 3
    e1, e1t, e2, e2t, e3 = (read_raw(n) for n in ("e1_modes_real_trace", "e1_theta_sweep", "e2_jobs_vs_load", "e2_thresholds", "e3_policy_change"))
    if e1 is not None:
        L += ["## Stage 3 - iFogSim2 experiments", "", "### E1 Data flow (real trace readings, synthetic camera frames)", ""]
        rows = []
        for cam in (1.0, 1.5):
            for v, lab in (("UG", "Ungoverned"), ("SS", "All-HTTPS"), ("CEGF03", "CEGF θ=0.3"), ("CEGF01", "CEGF θ=0.1")):
                d = e1[(e1.variant == v) & (e1.cam == cam)]
                rows.append([int(12 * cam), lab] + [f"{mean_ci(d[c] * k)[0]:.{n}f}" for c, k, n in (("TUDR", 100, 1), ("recall_read", 100, 1), ("volume_sel_read", 100, 1), ("uplink_MB", 1, 1), ("energy_J_per_sensor_h", 1, 3), ("loss_useful_readings", 100, 1))])
        L += [md_table(pd.DataFrame(rows, columns=["cameras", "setup", "useful on time %", "useful readings sent %", "readings sent %", "uplink MB/h", "sensor energy J/h", "useful readings lost %"])), "", "![E1](03_simulation/fig1_data_flow_real_trace.png)", ""]
        a = e1t.groupby(["workload", "theta"])[["recall_read", "volume_sel_read"]].mean()
        L += ["Entropy threshold on real vs synthetic data (useful readings sent / readings sent, %):", "", md_table(pd.DataFrame(
            [[w] + [f"{100 * a.loc[(w, t), 'recall_read']:.0f} / {100 * a.loc[(w, t), 'volume_sel_read']:.0f}" for t in (0.1, 0.2, 0.3, 0.4, 0.5)] for w in ("real trace", "synthetic")], columns=["workload", "θ=0.1", "θ=0.2", "θ=0.3", "θ=0.4", "θ=0.5"])), "", "![theta](03_simulation/fig2_entropy_threshold.png)", ""]
    if e2 is not None:
        L += ["### E2 Job distribution", ""]
        rows = []
        for l in (0.9, 1.2, 1.5):
            for p in ("cegf", "greedy"):
                d = e2[(e2.policy == p) & (e2.load == l)]
                rows.append([l, p] + [f"{mean_ci(d[c])[0]:.{n}f}" for c, n in (("miss_critical", 1), ("violations_pct", 1), ("conf_viol_pct", 1), ("fallback_pct", 1), ("lat_p95_irrig", 2))])
        L += [md_table(pd.DataFrame(rows, columns=["edge load", "strategy", "critical misses %", "policy violations %", "confidential on untrusted %", "fallback %", "irrigation p95 s"])), "", "![E2](03_simulation/fig3_job_distribution.png)", ""]
    if e2t is not None:
        L += ["![thr](03_simulation/fig4_threshold_sensitivity.png)", ""]
    if e3 is not None:
        L += ["### E3 Policy change at run time", "", md_table(pd.DataFrame([[v, f"{mean_ci(e3[e3.variant == v].miss_crit_pre)[0]:.1f}", f"{mean_ci(e3[e3.variant == v].miss_crit_post)[0]:.1f}", f"{mean_ci(e3[e3.variant == v].violations_pct)[0]:.1f}"]
                                                              for v in ("No change", "Runtime swap (CEGF)", "Hard-coded, 30 s redeploy")], columns=["setup", "critical misses before %", "after %", "policy violations %"])), "", "![E3](03_simulation/fig5_policy_change.png)", ""]
    L += ["## Notes and limitations", "",
          "* Camera frames, job arrivals, trust and availability values, loss rates and the 30 s redeploy outage are assumptions, not measurements.",
          "* The iFogSim2 port has one cloud node and no edge failures.",
          "* Raw per-run results are in `03_simulation/raw/`; every figure is also saved as PDF.", ""]
    open(os.path.join(RES, "RUN_SUMMARY.md"), "w", encoding="utf-8").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="all")
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args()
    st = ["workload", "policies", "simulation", "summary"] if a.stages == "all" else a.stages.split(",")
    os.makedirs(RES, exist_ok=True)
    t0 = time.time()
    stage_build()
    if "workload" in st:
        stage_workload()
    if "policies" in st:
        stage_policies()
    if "simulation" in st:
        stage_simulation(a.seeds)
    if "figures" in st:
        stage_figures()
    if "summary" in st:
        stage_summary(a.seeds)
    print(f"done in {(time.time() - t0) / 60:.1f} min -> {RES}")


if __name__ == "__main__":
    main()
