"""Build a replayable sensor trace from the Autonomous Greenhouse Challenge 2019 data (option 2).

Input : dataset/greenhouse_challenge_2019/raw/extracted/   (run fetch_greenhouse.py first)
Output: dataset/greenhouse_challenge_2019/trace/trace.csv, trace_meta.json, trace_overview.png

What it does
  1. Picks N sensor streams: substrate-slab sensors (water content WC, EC, temperature) of all six
     compartments (= the "soil-moisture / soil-temperature" sensors of the scenario), topped up with
     greenhouse-climate channels (Tair, Rhair, CO2air, HumDef).
  2. Cuts a real-time window (default 2020-03-15 04:00, 10 h, covers sunrise) and replays it
     `speedup` times faster (5-min samples -> 30 s sim samples), with a random phase per stream.
  3. Computes, per reading
       entropy : normalised self-information (-log2 p) of the value under a kernel density estimate of the
                 stream's previous W samples; the kernel width is the sensor's noise scale. In [0, 1].
       useful  : ground truth, report-by-exception dead-band: the value differs from the last *useful*
                 value by more than eps (eps = k * robust noise scale). Independent of the entropy measure.
  4. Writes trace.csv + metadata + a quality report (how well entropy predicts `useful`, theta sweep).

Run from the repo root:  python -P experiments/traces/build_trace.py [--help]
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(ROOT, "dataset", "greenhouse_challenge_2019", "raw", "extracted")
OUT = os.path.join(ROOT, "dataset", "greenhouse_challenge_2019", "trace")
COMPS = ["AICU", "Automatoes", "Digilog", "IUACAAS", "Reference", "TheAutomators"]
SLAB = ["WC_slab1", "WC_slab2", "EC_slab1", "EC_slab2", "t_slab1", "t_slab2"]
CLIM = ["Tair", "Rhair", "CO2air", "HumDef"]


def load_series(comp, fname, col):
    d = pd.read_csv(os.path.join(RAW, comp, fname), usecols=["%time", col], low_memory=False)
    t = pd.to_datetime(pd.to_numeric(d["%time"], errors="coerce"), unit="D", origin="1899-12-30").dt.round("min")
    s = pd.Series(pd.to_numeric(d[col], errors="coerce").values, index=t)
    s = s[~s.index.isna()]
    return s[~s.index.duplicated()].sort_index().ffill(limit=3)


def noise_scale(x, k):
    """Robust noise scale of a stream from its first differences; eps = k * scale (>= 1.5 x quantisation step)."""
    d = np.diff(x[np.isfinite(x)])
    mad = 1.4826 * np.median(np.abs(d - np.median(d)))
    nz = np.abs(d[d != 0])
    q = nz.min() if len(nz) else 1e-9
    return max(k * mad, 1.5 * q, 1e-9)


def self_information(x_full, idx, eps, hist):
    """Normalised self-information of x_full[i] (i in idx) under a Gaussian-kernel density of the previous `hist` samples."""
    out = np.empty(len(idx))
    alpha = 0.5
    for j, i in enumerate(idx):
        past = x_full[max(0, i - hist):i]
        past = past[np.isfinite(past)]
        n = len(past)
        if n < 4:
            out[j] = 1.0
            continue
        w = np.exp(-0.5 * ((x_full[i] - past) / eps) ** 2).sum()
        p = (w + alpha) / (n + alpha)
        out[j] = np.log2(1 / p) / np.log2((n + alpha) / alpha)
    return np.clip(out, 0.0, 1.0)


def deadband_useful(x, eps):
    useful = np.zeros(len(x), bool)
    ref = None
    for i, v in enumerate(x):
        if ref is None or abs(v - ref) >= eps:
            useful[i] = True
            ref = v
    return useful


def auc(score, label):
    r = pd.Series(score).rank().values
    n1 = label.sum(); n0 = len(label) - n1
    return float((r[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else float("nan")


def sunrise_hour(day):
    """Sunrise proxy: first hour of the day with outdoor global radiation (Weather.csv, Iglob) above 5 W/m2.
    (The inside PAR in GreenhouseClimate.csv includes assimilation lighting and is therefore not usable.)"""
    try:
        d = pd.read_csv(os.path.join(RAW, "Weather", "Weather.csv"), usecols=["%time", "Iglob"], low_memory=False)
        t = pd.to_datetime(pd.to_numeric(d["%time"], errors="coerce"), unit="D", origin="1899-12-30").dt.round("min")
        x = pd.Series(pd.to_numeric(d["Iglob"], errors="coerce").values, index=t)
        x = x[(x.index >= day) & (x.index < day + pd.Timedelta(days=1))]
        t0 = x[x > 5].index[0]
        return t0.hour + t0.minute / 60
    except Exception:
        return 6.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-start", default="2020-03-15 04:00")
    ap.add_argument("--real-hours", type=float, default=10)
    ap.add_argument("--speedup", type=float, default=10, help="real seconds per simulated second (5-min samples -> 30 s)")
    ap.add_argument("--streams", type=int, default=40)
    ap.add_argument("--k", type=float, default=3.0, help="dead-band = k x robust noise scale")
    ap.add_argument("--history", type=int, default=24, help="samples of history for the entropy estimate (24 = 2 h real)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if not os.path.isdir(RAW):
        raise SystemExit("raw data missing: run experiments/traces/fetch_greenhouse.py first")
    rng = np.random.default_rng(a.seed)
    start = pd.Timestamp(a.real_start); end = start + pd.Timedelta(hours=a.real_hours)

    cands = [(c, "GrodanSens.csv", col) for c in COMPS for col in SLAB]
    cands += [("Reference", "GreenhouseClimate.csv", col) for col in CLIM]
    cands += [(c, "GreenhouseClimate.csv", col) for c in COMPS if c != "Reference" for col in CLIM]
    rows, streams, dropped = [], [], []
    period_sim = 300.0 / a.speedup                                   # s between samples in simulation time
    horizon_s = a.real_hours * 3600 / a.speedup
    for comp, fname, col in cands:
        if len(streams) == a.streams:
            break
        s = load_series(comp, fname, col)
        win = s[(s.index >= start) & (s.index < end)]
        if len(win) < 0.95 * a.real_hours * 12 or win.isna().mean() > 0.05 or win.nunique() < 4:
            dropped.append(f"{comp}/{col}")
            continue
        x_full = s.values.astype(float)
        pos = np.where((s.index >= start) & (s.index < end))[0]
        eps = noise_scale(x_full, a.k)
        H = self_information(x_full, pos, eps, a.history)
        vals = x_full[pos]
        ok = np.isfinite(vals)
        useful = deadband_useful(np.where(ok, vals, np.nanmedian(vals)), eps)
        phase = rng.uniform(0, period_sim)
        t_sim = (s.index[pos] - start).total_seconds().values / a.speedup + phase
        sid = len(streams)
        streams.append(dict(stream_id=sid, comp=comp, file=fname, channel=col, eps=float(eps)))
        for k_, (ts, v, h, u) in enumerate(zip(t_sim, vals, H, useful)):
            if ts < horizon_s and np.isfinite(v):
                rows.append((round(ts * 1000, 1), sid, comp, col, sid % 3, "READING", float(v), round(float(h), 5), int(u)))
    tr = pd.DataFrame(rows, columns=["t_ms", "stream_id", "comp", "channel", "zone", "kind", "value", "entropy", "useful"])
    tr = tr.sort_values("t_ms").reset_index(drop=True)
    os.makedirs(OUT, exist_ok=True)
    tr.to_csv(os.path.join(OUT, "trace.csv"), index=False)

    # ---------------- quality report
    u = tr.useful.values.astype(bool)
    sweep = {f"{th:.1f}": dict(forwarded=float((tr.entropy >= th).mean()), recall=float(((tr.entropy >= th) & u).sum() / max(1, u.sum())))
             for th in np.arange(0, 0.9, 0.1)}
    thirds = pd.cut(tr.t_ms / 1000 / horizon_s, [0, 1 / 3, 2 / 3, 1.0], include_lowest=True, labels=["first", "middle", "last"])
    meta = dict(
        source="Autonomous Greenhouse Challenge 2nd edition (2019), 4TU.ResearchData, DOI 10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7, CC0",
        params=dict(real_start=a.real_start, real_hours=a.real_hours, speedup=a.speedup, k=a.k, history=a.history, seed=a.seed),
        sim_horizon_s=horizon_s, sample_period_sim_s=period_sim,
        real_start_hour=start.hour + start.minute / 60, sunrise_hour=sunrise_hour(start.normalize()),
        n_streams=len(streams), n_readings=int(len(tr)), dropped_streams=dropped, streams=streams,
        useful_fraction=float(u.mean()), useful_fraction_by_third={k: float(tr.useful[thirds == k].mean()) for k in ["first", "middle", "last"]},
        mean_entropy_useful=float(tr.entropy[u].mean()), mean_entropy_other=float(tr.entropy[~u].mean()),
        auc_entropy_vs_useful=auc(tr.entropy.values, u), theta_sweep=sweep)
    json.dump(meta, open(os.path.join(OUT, "trace_meta.json"), "w"), indent=1)
    print(f"{len(streams)} streams, {len(tr)} readings, dropped {len(dropped)} candidates")
    print(f"useful fraction {meta['useful_fraction']:.2f} by third {meta['useful_fraction_by_third']}")
    print(f"entropy mean: useful {meta['mean_entropy_useful']:.2f} vs other {meta['mean_entropy_other']:.2f}; AUC {meta['auc_entropy_vs_useful']:.3f}")
    print("theta sweep (forwarded / recall):", {k: (round(v['forwarded'], 2), round(v['recall'], 2)) for k, v in sweep.items()})
    plot(tr, meta, os.path.join(OUT, "trace_overview.png"))


def plot(tr, meta, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
    for sid in (0, 6, 12, 36):
        d = tr[tr.stream_id == sid]
        if d.empty:
            continue
        z = (d.value - d.value.mean()) / (d.value.std() + 1e-9)
        ax[0].plot(d.t_ms / 60000, z, lw=1, label=f"{d.comp.iloc[0]} {d.channel.iloc[0]}")
        ax[0].scatter(d.t_ms[d.useful == 1] / 60000, z[d.useful == 1], s=10, zorder=3)
    ax[0].set_xlabel("simulated minutes"); ax[0].set_ylabel("z-scored value (dots = useful)"); ax[0].legend(fontsize=7)
    bins = (tr.t_ms // 300000).astype(int)
    g = tr.groupby(bins).agg(useful=("useful", "mean"), entropy=("entropy", "mean"))
    ax[1].plot(g.index * 5, g.useful, marker="o", label="useful fraction"); ax[1].plot(g.index * 5, g.entropy, marker="s", label="mean entropy")
    ax[1].set_xlabel("simulated minutes"); ax[1].legend(fontsize=8)
    th = sorted(meta["theta_sweep"]); ax[2].plot([float(t) for t in th], [meta["theta_sweep"][t]["recall"] for t in th], marker="o", label="recall of useful")
    ax[2].plot([float(t) for t in th], [meta["theta_sweep"][t]["forwarded"] for t in th], marker="s", label="forwarded")
    ax[2].set_xlabel("entropy threshold theta"); ax[2].legend(fontsize=8)
    for a_ in ax:
        a_.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


if __name__ == "__main__":
    main()
