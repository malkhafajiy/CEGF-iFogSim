"""Trace-driven workloads for the Python simulator (option 2).

    from trace_io import load_trace, trace_workload
    W = trace_workload(seed)                 # readings from trace.csv + synthetic camera frames
    farm_sim.run_df(seed, flow=1, mode="CEGF", theta=0.3, workload=W)

The trace supplies the sensor readings (time, zone, entropy, useful). Camera frames are still synthetic
(a public greenhouse-camera trace is not part of this dataset); their "useful" probability follows the
same sunrise ramp, using the *real clock* implied by the trace metadata (real_start_hour, speedup).
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TRACE_DIR = os.path.join(ROOT, "dataset", "greenhouse_challenge_2019", "trace")
T0 = 3 * 3600          # same simulation origin as farm_sim.T0 (only used for bin alignment)


def load_trace(path=None):
    path = path or os.path.join(TRACE_DIR, "trace.csv")
    tr = pd.read_csv(path).sort_values("t_ms").reset_index(drop=True)
    meta = json.load(open(os.path.join(os.path.dirname(path), "trace_meta.json")))
    return tr, meta


def trace_workload(seed, path=None, n_cam=12, cam_period=5.0):
    tr, meta = load_trace(path)
    rng = np.random.default_rng(seed)
    horizon = meta["sim_horizon_s"]
    t_r = T0 + tr.t_ms.values / 1000.0
    # cameras: synthetic frames, usefulness follows sunrise measured in the data (real clock = start + t * speedup)
    p = meta["params"]
    t_f = np.concatenate([T0 + rng.uniform(0, cam_period) + np.arange(0, horizon, cam_period) for _ in range(n_cam)])
    s_f = np.repeat(np.arange(n_cam), len(t_f) // n_cam)
    clock_s = meta["real_start_hour"] * 3600 + (t_f - T0) * p["speedup"]
    ramp = 1 / (1 + np.exp(-(clock_s - meta["sunrise_hour"] * 3600) / 1200.0))
    u_f = rng.random(len(t_f)) < (0.08 + 0.55 * ramp)
    H_f = np.where(u_f, rng.beta(5, 2, len(t_f)), rng.beta(1.5, 8, len(t_f)))
    t = np.concatenate([t_r, t_f])
    kind = np.concatenate([np.zeros(len(t_r), int), np.ones(len(t_f), int)])
    zone = np.concatenate([tr.zone.values, s_f % 3])
    useful = np.concatenate([tr.useful.values.astype(bool), u_f])
    H = np.concatenate([tr.entropy.values, H_f])
    size = np.where(kind == 0, 60.0, 150e3)
    o = np.argsort(t, kind="stable")
    return dict(t=t[o], kind=kind[o], zone=zone[o], useful=useful[o], H=H[o], size=size[o], hours=horizon / 3600.0)
