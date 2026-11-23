"""Runs the CEGF precision-farming experiments on iFogSim2 (one JVM per run) and aggregates them.

Prereqs: JDK on PATH or in Program Files, and `build.ps1` run once (compiles src/ into ./build).
Policies come from ../farm/results/policies.json (written by ../farm/run_all.py).
"""
import glob
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "results")
SEEDS = range(1, 21)
T975 = 2.093


def find_java():
    for p in glob.glob(r"C:\Program Files\Microsoft\jdk-*\bin\java.exe"):
        return p
    return "java"


JAVA = find_java()
CP = os.pathsep.join(glob.glob(os.path.join(ROOT, "jars", "**", "*.jar"), recursive=True) + [os.path.join(HERE, "build")])


def run(args):
    cmd = [JAVA, "-cp", CP, "org.fog.cegf.FarmExperiment", f"policies={os.path.join(ROOT, 'experiments', 'farm', 'results', 'policies.json')}"] + [f"{k}={v}" for k, v in args.items()]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
    m = re.search(r"^RESULT (.*)$", p.stdout, re.M)
    if not m:
        raise RuntimeError(f"no result for {args}\n{p.stdout[-500:]}\n{p.stderr[-500:]}")
    return {**args, **{k: float(v) for k, v in (kv.split("=") for kv in m.group(1).split(","))}}


def batch(tasks, name):
    os.makedirs(OUT, exist_ok=True)
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
        rows = list(ex.map(run, tasks))
    df = pd.DataFrame(rows); df.to_csv(os.path.join(OUT, f"{name}.csv"), index=False)
    print(f"{name}: {len(df)} runs", flush=True)
    return df


def ci(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return x.mean(), (T975 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0)


def main():
    S = list(SEEDS)
    d1 = batch([dict(scenario="data", mode=m, cam=c, seed=s) for s in S for m in ("UG", "SS", "CEGF") for c in (1.0, 1.5)], "ifog_e1_df1")
    d1c = batch([dict(scenario="data", mode="CEGF", theta=t, seed=s) for s in S for t in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)], "ifog_e1_theta")
    d2 = batch([dict(scenario="jobs", policy=p, load=l, seed=s) for s in S for p in ("random", "cloud", "static", "greedy", "cegf") for l in (0.6, 0.9, 1.2, 1.5)], "ifog_e2_jobs")
    d2c = batch([dict(scenario="jobs", policy="cegf", load=1.2, alpha=a, tau=t, seed=s) for s in S for a in (0.0, 0.25, 0.5, 0.75) for t in (0.5, 0.7, 0.9, 0.96)], "ifog_e2_thr")
    ch = dict(scenario="jobs", policy="cegf", load=1.0, change_t=900, alpha2=0.5, tau2=0.9)
    d3 = batch([dict(scenario="jobs", policy="cegf", load=1.0, change_t=900, alpha2=0.25, tau2=0.7, seed=s, variant="no change") for s in S] +
               [dict(**ch, seed=s, variant="runtime swap") for s in S] +
               [dict(**ch, outage_s=30, seed=s, variant="redeploy 30s") for s in S], "ifog_e3_flex")

    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    def show(title, df, by, cols):
        g = df.groupby(by)
        t = pd.DataFrame({c: [f"{ci(grp[c])[0]:.2f}+-{ci(grp[c])[1]:.2f}" for _, grp in g] for c in cols}, index=[k for k, _ in g])
        print("\n" + title); print(t)
    c1 = ["TUDR", "recall", "volume_sel", "uplink_MB", "edge_lat_mean_s", "loss_useful_readings", "energy_J_per_sensor_h", "unencrypted_pct"]
    show("E1a DF1 (mode, cam)", d1, ["mode", "cam"], c1)
    show("E1c theta", d1c, ["theta"], ["TUDR", "recall", "volume_sel", "uplink_MB"])
    c2 = ["miss_critical", "miss_disease", "conf_viol_pct", "violations_pct", "lat_p95_irrig", "offload_cloud_pct", "fallback_pct", "rejected_pct"]
    for l in (0.9, 1.2):
        show(f"E2a load {l}", d2[d2.load == l], ["policy"], c2)
    show("E2b thresholds (alpha, tau)", d2c, ["alpha", "tau"], ["miss_critical", "miss_disease", "fallback_pct", "rejected_pct"])
    show("E3", d3, ["variant"], ["miss_crit_pre", "miss_crit_post", "violations_pct", "conf_viol_pct"])


if __name__ == "__main__":
    main()
