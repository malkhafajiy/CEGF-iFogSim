"""Smoke test: replay the greenhouse trace through the Python simulator (DF1, three modes) and compare with synthetic data.

Run from the repo root:  python experiments/traces/smoke_replay.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "farm"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

import farm_sim as F  # noqa: E402
from trace_io import trace_workload  # noqa: E402

COLS = ["TUDR", "recall", "volume_sel", "uplink_MB", "edge_wait_mean", "loss_useful_readings"]
for mode in ("UG", "SS", "CEGF"):
    rows = [F.run_df(s, 1, mode, 0.3, workload=trace_workload(s)) for s in range(1, 6)]
    print(f"{mode:5s} trace    " + "  ".join(f"{c}={np.mean([r[c] for r in rows]):.3f}" for c in COLS))
rows = [F.run_df(s, 1, "CEGF", 0.3) for s in range(1, 6)]
print(f"CEGF  synthetic " + "  ".join(f"{c}={np.mean([r[c] for r in rows]):.3f}" for c in COLS))
print("theta sweep on the trace (CEGF): theta -> recall / forwarded readings")
for th in (0.1, 0.2, 0.3, 0.4):
    W = trace_workload(1)
    r = F.run_df(1, 1, "CEGF", th, workload=W)
    rd = W["kind"] == 0
    print(f"  {th:.1f}: recall(all useful)={r['recall']:.3f}  readings forwarded={(W['H'][rd] >= th).mean():.2f}")
