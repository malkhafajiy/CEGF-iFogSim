# Trace pipeline (option 2): real greenhouse data -> replayable sensor trace

Run from the repo root.

| Step | Command | Result |
|---|---|---|
| 1. Download (CC0, 8.4 MB, MD5-checked) | `python -P experiments/traces/fetch_greenhouse.py` | `dataset/greenhouse_challenge_2019/raw/` (git-ignored) |
| 2. Build the trace | `python -P experiments/traces/build_trace.py` | `dataset/greenhouse_challenge_2019/trace/trace.csv`, `trace_meta.json`, `trace_overview.png` |
| 3. Replay in the Python simulator | `python experiments/traces/smoke_replay.py` | DF1 on trace vs synthetic |

Needs `pip install py7zr pandas numpy matplotlib`.

Trace columns: `t_ms, stream_id, comp, channel, zone, kind, value, entropy, useful`.
`entropy` is the normalised self-information of the reading against the stream's last 24 samples (kernel width = sensor noise scale).
`useful` is a report-by-exception dead-band label (independent of `entropy`). `zone = stream_id % 3` (edge gateway).

Python use: `farm_sim.run_df(seed, 1, "CEGF", 0.3, workload=trace_io.trace_workload(seed))`.
iFogSim2 replay (Java reader for `trace.csv` in `GovernedSensor`) is not implemented yet.
