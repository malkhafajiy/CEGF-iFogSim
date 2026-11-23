"""Precision-farming simulator for CEGF (data flow + job distribution).

Self-contained discrete simulation (numpy). All parameters are assumptions documented in PARAMS /
the constants below; they are NOT measurements. Seeds make every run reproducible.
"""
import heapq
import time
from collections import deque

import numpy as np

from odrl_eval import ENTROPY_POLICY, RECIPIENT_POLICY, permitted

# ----------------------------------------------------------------------------------------------
# E1: data-flow experiments
# ----------------------------------------------------------------------------------------------
T0, T1 = 3 * 3600, 9 * 3600          # simulated window 03:00-09:00 (night -> sunrise at 06:00)
N_SENS, SENS_PERIOD = 40, 30.0        # 40 soil sensors, one reading / 30 s, 60 B payload
N_CAM, CAM_PERIOD = 12, 5.0           # 12 canopy cameras, one 150 kB frame / 5 s
N_GW, GW_SERVERS = 3, 2               # 3 greenhouse gateways, 2 inference slots each
SVC_READ, SVC_FRAME = 0.02, 1.8       # edge service time [s] (frame: lognormal, cv 0.3)
STALE_CAP = 20.0                      # edge drops items that waited longer than this [s]
DEADLINE = {0: 2.0, 1: 8.0}           # freshness requirement [s]: readings / frames
UP_CAP, UP_BASE = 250e3, 0.05         # farm uplink 2 Mbit/s, one-way delay to cloud 50 ms
LINK_LOSS, LINK_BW = 0.02, 5e6        # greenhouse wireless: 2 % loss, 5 MB/s
PROTO = {  # enc: encrypted, qos: delivery confirmed, oh: per-message overhead [B], newconn: P(new TLS session)
    "MQTT": dict(enc=False, qos=0, oh=20, newconn=0.0),
    "MQTTS": dict(enc=True, qos=1, oh=45, newconn=0.0),
    "HTTPS": dict(enc=True, qos=1, oh=700, newconn=0.5),
}
MODES = {"UG": ("MQTT", "MQTT"), "SS": ("HTTPS", "HTTPS"), "CEGF": ("MQTTS", "HTTPS")}  # (to-edge, to-cloud)
E_BYTE, E_HS = 2e-6, 0.02             # sensor energy: J / byte, J / new TLS session


def gen_workload(rng, n_cam=N_CAM):
    t_r = np.concatenate([T0 + rng.uniform(0, SENS_PERIOD) + np.arange(0, T1 - T0, SENS_PERIOD)
                          for _ in range(N_SENS)])
    s_r = np.repeat(np.arange(N_SENS), len(t_r) // N_SENS)
    t_f = np.concatenate([T0 + rng.uniform(0, CAM_PERIOD) + np.arange(0, T1 - T0, CAM_PERIOD)
                          for _ in range(n_cam)])
    s_f = np.repeat(np.arange(n_cam), len(t_f) // n_cam)
    t = np.concatenate([t_r, t_f]); kind = np.concatenate([np.zeros(len(t_r), int), np.ones(len(t_f), int)])
    src = np.concatenate([s_r, s_f])
    o = np.argsort(t); t, kind, src = t[o], kind[o], src[o]
    ramp = 1 / (1 + np.exp(-(t - 6 * 3600) / 1200.0))            # sunrise ramp
    p_useful = np.where(kind == 0, 0.10 + 0.60 * ramp, 0.08 + 0.55 * ramp)
    useful = rng.random(len(t)) < p_useful                       # ground truth: informs irrigation/vision
    H = np.where(useful, rng.beta(5, 2, len(t)), rng.beta(1.5, 8, len(t)))   # entropy = noisy proxy
    size = np.where(kind == 0, 60.0, 150e3)
    zone = src % N_GW
    return dict(t=t, kind=kind, zone=zone, useful=useful, H=H, size=size)


def uplink(send_t, nbytes, rng):
    """Fluid shared-uplink model: 10 s bins; delay grows as 1/(1-rho); tail-drop beyond 95 % load."""
    b = ((send_t - T0) // 10).astype(int)
    load = np.bincount(b, weights=nbytes, minlength=b.max() + 2) / (UP_CAP * 10)
    rho = load[b]
    tx = nbytes / UP_CAP
    q = np.where(rho < 0.95, tx / (1 - np.minimum(rho, 0.94)), np.minimum(8 + 40 * (rho - 0.95), 60))
    drop = rng.random(len(send_t)) < np.maximum(0, 1 - 0.95 / np.maximum(rho, 1e-9))
    return UP_BASE + tx + q + rng.lognormal(-4, 0.5, len(send_t)), drop


def edge_queue(arr, svc, zone, rng_unused=None):
    """FIFO, GW_SERVERS slots per gateway, drop if wait > STALE_CAP. Returns finish, wait, dropped."""
    n = len(arr); fin = np.full(n, np.nan); wait = np.full(n, np.nan); dropped = np.zeros(n, bool)
    for z in range(N_GW):
        idx = np.where(zone == z)[0]; idx = idx[np.argsort(arr[idx])]
        free = [0.0] * GW_SERVERS
        for i in idx:
            k = free.index(min(free)); st = max(arr[i], free[k]); w = st - arr[i]
            if w > STALE_CAP:
                dropped[i] = True; continue
            free[k] = st + svc[i]; fin[i] = free[k]; wait[i] = w
    return fin, wait, dropped


def run_df(seed, flow, mode, theta=0.3, cam_scale=1.0):
    rng = np.random.default_rng(seed)
    W = gen_workload(rng, int(round(N_CAM * cam_scale)))
    p_edge, p_up = (PROTO[x] for x in MODES[mode])
    n_all = len(W["t"]); kind = W["kind"]
    if mode == "CEGF":   # the entropy policy (Listing "freshness") selects the data; vectorised check below
        sel = W["H"] >= theta
    else:
        sel = np.ones(n_all, bool)
    idx = np.where(sel)[0]
    t, k, zone, size, useful = (W[x][idx] for x in ("t", "kind", "zone", "size", "useful"))
    n = len(idx); useful_total = W["useful"].sum()
    tta = np.full(n, np.inf); lost_transit = np.zeros(n, bool); edge_wait = []
    cloud_delay = np.full(n, np.nan); up_bytes = 0.0; stale_drop = 0

    to_edge = flow in (1, 2, 3); to_cloud_raw = flow in (2, 4)
    if to_edge:
        extra = rng.random(n) < LINK_LOSS
        r2 = extra & (rng.random(n) < LINK_LOSS)
        lost = extra & (p_edge["qos"] == 0)                            # QoS0 loses the message
        lat = (0.005 + rng.exponential(0.01, n) + size / LINK_BW
               + (rng.random(n) < p_edge["newconn"]) * 0.03 + 0.2 * extra * (p_edge["qos"] > 0) + 0.2 * r2 * (p_edge["qos"] > 0))
        arr = t + lat
        svc = np.where(k == 0, SVC_READ, rng.lognormal(np.log(SVC_FRAME) - 0.045, 0.3, n))
        ok = ~lost
        fin = np.full(n, np.nan); wait = np.full(n, np.nan); dr = np.zeros(n, bool)
        sub = np.where(ok)[0]
        f_, w_, d_ = edge_queue(arr[sub], svc[sub], zone[sub])
        fin[sub], wait[sub], dr[sub] = f_, w_, d_
        lost_transit |= lost; stale_drop = int(dr.sum()); edge_wait = wait[~np.isnan(wait)]
        tta = np.where(np.isnan(fin), np.inf, fin - t)
    # uplink traffic: derived results (flows 1,2) and/or raw copies (flows 2,4)
    send_t, nbytes, owner, is_raw = [], [], [], []
    if flow in (1, 2):
        m = ~np.isnan(fin)
        j = np.where(m)[0]
        send_t.append(fin[j]); nbytes.append(np.where(k[j] == 0, 120.0, 2000.0) + p_up["oh"])
        owner.append(j); is_raw.append(np.zeros(len(j), bool))
    if to_cloud_raw:
        send_t.append(t.copy()); nbytes.append(size + p_up["oh"]); owner.append(np.arange(n)); is_raw.append(np.ones(n, bool))
    if send_t:
        st_, nb_, ow_, rw_ = map(np.concatenate, (send_t, nbytes, owner, is_raw))
        d_up, drop_up = uplink(st_, nb_, rng)
        if p_up["qos"] == 0:      # QoS0 over a saturated uplink: dropped messages are lost
            pass
        else:                     # confirmed delivery: retransmit after 1 s instead of losing
            d_up = d_up + drop_up * 1.0; drop_up = np.zeros_like(drop_up)
        up_bytes = nb_.sum()
        arr_cloud = st_ + d_up
        if flow == 4:             # raw data processed in cloud, result returned to the greenhouse
            tta = np.where(drop_up, np.inf, arr_cloud - t[ow_] + 0.2 + 0.04)
            cloud_delay[ow_] = np.where(drop_up, np.nan, arr_cloud - t[ow_])
            lost_transit |= np.isin(np.arange(n), ow_[drop_up])
        else:
            use = rw_ if flow == 2 else ~rw_
            cloud_delay[ow_[use]] = np.where(drop_up[use], np.nan, arr_cloud[use] - t[ow_[use]])
            if flow == 2:
                pass
    dl = np.where(k == 0, DEADLINE[0], DEADLINE[1])
    timely_useful = (useful & (tta <= dl)).sum()
    read_useful = useful & (k == 0)
    n_msgs_read = (k == 0).sum()
    nc_edge = (rng.random(n) < p_edge["newconn"])
    sens_bytes = size[k == 0] + p_edge["oh"]
    energy_edge = (sens_bytes.sum() * E_BYTE + nc_edge[k == 0].sum() * E_HS) if to_edge else 0.0
    energy_cloud = (((size[k == 0] + p_up["oh"]).sum() * E_BYTE + (rng.random(n)[k == 0] < p_up["newconn"]).sum() * E_HS)
                    if to_cloud_raw else 0.0)
    hours = (T1 - T0) / 3600
    unenc = 0.0
    if to_edge and not p_edge["enc"]: unenc = 1.0
    if to_cloud_raw and not p_up["enc"]: unenc = 1.0
    if flow in (1, 2) and not p_up["enc"]: unenc = 1.0
    return dict(
        TUDR=timely_useful / useful_total,
        recall=(sel & W["useful"]).sum() / useful_total,
        volume_sel=sel.mean(),
        uplink_MB=up_bytes / 1e6,
        tta_p95=np.percentile(tta[np.isfinite(tta) & useful], 95) if (np.isfinite(tta) & useful).any() else np.nan,
        edge_wait_mean=float(np.mean(edge_wait)) if len(edge_wait) else 0.0,
        stale_drops=stale_drop,
        cloud_delay_p95=np.nanpercentile(cloud_delay, 95) if np.isfinite(cloud_delay).any() else np.nan,
        loss_useful_readings=(lost_transit & read_useful).sum() / max(1, (W["useful"] & (kind == 0)).sum()),
        energy_J_per_sensor_h=(energy_edge + energy_cloud) / N_SENS / hours,
        unencrypted_pct=100 * unenc,
    )


def entropy_policy_check(seed, n=3000, theta=0.3):
    """Correctness: the ODRL evaluator and the vectorised filter select exactly the same items."""
    rng = np.random.default_rng(seed); H = rng.random(n)
    ev = np.array([permitted(ENTROPY_POLICY, {"entropy": h}, {"theta": theta}) for h in H])
    return bool((ev == (H >= theta)).all())


# ----------------------------------------------------------------------------------------------
# E2/E4: job-distribution experiments
# ----------------------------------------------------------------------------------------------
JTYPES = {  # name: (mix, critical, confidential, edge work [s], size [B], deadline [s])
    "irrigation": (0.45, True, False, 0.4, 2e3, 2.0),
    "disease":    (0.25, False, True, 3.0, 150e3, 15.0),
    "fertigation": (0.10, True, True, 1.2, 20e3, 10.0),
    "storage":    (0.20, False, False, 0.5, 50e3, 120.0),
}
NODES = [  # name, layer, servers, speed, trust, one-way latency [s]
    ("e1", "edge", 2, 1.0, 0.90, 0.005), ("e2", "edge", 2, 1.0, 0.85, 0.005), ("e3", "edge", 2, 1.0, 0.55, 0.005),
    ("c1", "cloud", 8, 4.0, 0.95, 0.05), ("c2", "cloud", 8, 4.0, 0.50, 0.07)]
MTBF, MTTR = 1200.0, 60.0
HORIZON = 1800.0


class Node:
    def __init__(self, spec, windows):
        self.name, self.layer, self.servers, self.speed, self.trust, self.lat = spec
        self.free = [0.0] * self.servers; self.fin = deque(); self.down = windows   # list of (start,end)

    def down_until(self, now):
        for a, b in self.down:
            if a <= now < b: return b
        return 0.0

    def avail(self, now):
        if self.down_until(now) > now: return 0.0
        while self.fin and self.fin[0] <= now: self.fin.popleft()
        return max(0.0, 1 - len(self.fin) / self.servers)

    def start_time(self, arrive):
        return max(arrive, min(self.free), self.down_until(arrive))


class Uplink:
    def __init__(self): self.free = 0.0


def make_jobs(rng, load, horizon=HORIZON):
    edge_work = sum(m * w for n, (m, c, f, w, s, d) in JTYPES.items() if n != "storage")
    lam = load * (3 * 2) / edge_work
    n = rng.poisson(lam * horizon); t = np.sort(rng.uniform(0, horizon, n))
    names = list(JTYPES); p = [JTYPES[x][0] for x in names]
    ty = rng.choice(len(names), n, p=p)
    return t, ty, rng.integers(0, 3, n), names


def make_nodes(rng, horizon=HORIZON):
    nodes = []
    for spec in NODES:
        w = []
        if spec[1] == "edge":
            t = rng.exponential(MTBF)
            while t < horizon:
                d = rng.exponential(MTTR); w.append((t, t + d)); t += d + rng.exponential(MTBF)
        nodes.append(Node(spec, w))
    return nodes


def est_completion(node, now, work, size, up):
    if node.layer == "edge":
        arrive = now + node.lat + size / LINK_BW
        st = node.start_time(arrive)
        return st + work / node.speed + node.lat
    send = max(now, up.free) + size / UP_CAP
    arrive = send + node.lat
    st = node.start_time(arrive)
    return st + work / node.speed + node.lat


def commit(node, now, work, size, up):
    if node.layer == "edge":
        arrive = now + node.lat + size / LINK_BW
    else:
        up.free = max(now, up.free) + size / UP_CAP; arrive = up.free + node.lat
    st = node.start_time(arrive); k = node.free.index(min(node.free))
    st = max(st, node.free[k]); node.free[k] = st + work / node.speed
    fin = node.free[k] + node.lat; node.fin.append(node.free[k]); return fin


def run_jobs(seed, policy, load=0.8, alpha=0.25, tau=0.7, change=None, redeploy_outage=0.0, horizon=HORIZON):
    """policy: random | cloud | static | greedy | cegf.  change=(t, alpha2, tau2) swaps the ODRL parameters."""
    rng = np.random.default_rng(seed)
    arr_t, ty, home, names = make_jobs(rng, load, horizon)
    nodes = make_nodes(rng, horizon); up = Uplink(); prm = {"alpha": alpha, "tau": tau}
    rng2 = np.random.default_rng(seed + 10_000)
    events = [(float(t_), i) for i, t_ in enumerate(arr_t)]; heapq.heapify(events)
    n = len(arr_t); done = np.full(n, np.nan); where = np.full(n, -1); dl_abs = np.zeros(n)
    fallback = np.zeros(n, bool); viol = np.zeros(n, bool); conf_viol = np.zeros(n, bool); placed_at = np.full(n, np.nan)
    swapped = False; swap_us = 0.0; eval_calls = 0; eval_time = 0.0
    outage = (change[0], change[0] + redeploy_outage) if (change and redeploy_outage) else None

    def ok_for(job_i, nd, now):
        nonlocal eval_calls, eval_time
        _, c, f, *_ = JTYPES[names[ty[job_i]]]
        ctx = {"job.critical": c, "job.confidential": f, "recipient.availability": nd.avail(now), "recipient.trust": nd.trust}
        t0 = time.perf_counter(); r = permitted(RECIPIENT_POLICY, ctx, prm); eval_time += time.perf_counter() - t0; eval_calls += 1
        return r

    while events:
        now, i = heapq.heappop(events)
        if change and not swapped and now >= change[0]:
            t0 = time.perf_counter(); prm = {"alpha": change[1], "tau": change[2]}; swap_us = (time.perf_counter() - t0) * 1e6; swapped = True
        if outage and outage[0] <= now < outage[1]:           # hard-coded policy: decisions blocked during redeploy
            heapq.heappush(events, (outage[1], i)); continue
        nm = names[ty[i]]; mix, crit, conf, work, size, dl = JTYPES[nm]; dl_abs[i] = arr_t[i] + dl
        h = home[i]; edges = nodes[:3]; clouds = nodes[3:]; choice = None
        if policy == "random": choice = nodes[rng2.integers(0, 5)]
        elif policy == "cloud": choice = clouds[rng2.integers(0, 2)]
        elif policy == "static": choice = clouds[0] if nm == "storage" else edges[h]
        elif policy == "greedy": choice = min(nodes, key=lambda x: est_completion(x, now, work, size, up))
        else:
            pref = clouds if nm == "storage" else edges
            other = [x for x in nodes if x not in pref]
            E = [x for x in pref if ok_for(i, x, now)]
            best = min((est_completion(x, now, work, size, up) for x in E), default=float("inf"))
            if best > dl_abs[i] and nm != "storage":            # overloaded: offload to peers/cloud that satisfy the policy
                E = E + [x for x in other if ok_for(i, x, now)]
            if E: choice = min(E, key=lambda x: est_completion(x, now, work, size, up))
            elif conf:                                          # fallback: hold at initiator, retry until deadline
                if now + 0.5 < dl_abs[i]: heapq.heappush(events, (now + 0.5, i))
                fallback[i] = True; continue
            else: choice = edges[h]; fallback[i] = True         # fallback: execute at initiator
        av = choice.avail(now)                                   # audit against the policy in force right now
        viol[i] = (not permitted(RECIPIENT_POLICY, {"job.critical": crit, "job.confidential": conf,
                                                    "recipient.availability": av, "recipient.trust": choice.trust}, prm)) and not fallback[i]
        fin = commit(choice, now, work, size, up); done[i] = fin; where[i] = nodes.index(choice); placed_at[i] = now
        if conf and choice.trust < prm["tau"]: conf_viol[i] = True
    return dict(viol=viol,arr=arr_t, ty=ty, names=names, done=done, where=where, dl=dl_abs, fallback=fallback, conf_viol=conf_viol,
                swap_us=swap_us, eval_us=(eval_time / max(1, eval_calls)) * 1e6, placed=placed_at, nodes=nodes)


def summarize_jobs(R):
    names, ty, done, dl, arr = R["names"], R["ty"], R["done"], R["dl"], R["arr"]
    ok = ~np.isnan(done) & (done <= dl)
    crit = np.array([JTYPES[names[t]][1] for t in ty]); conf = np.array([JTYPES[names[t]][2] for t in ty])
    lat = done - arr
    on_edge = (R["where"] < 3) & (R["where"] >= 0); on_cloud = R["where"] >= 3
    out = dict(
        miss_all=100 * (1 - ok.mean()),
        miss_critical=100 * (1 - ok[crit].mean()) if crit.any() else np.nan,
        miss_disease=100 * (1 - ok[ty == names.index("disease")].mean()),
        miss_irrigation=100 * (1 - ok[ty == names.index("irrigation")].mean()),
        conf_viol_pct=100 * R["conf_viol"][conf].mean() if conf.any() else 0.0,
        rejected_pct=100 * np.isnan(done).mean(),
        lat_mean_irrig=np.nanmean(lat[ty == names.index("irrigation")]),
        lat_p95_irrig=np.nanpercentile(lat[ty == names.index("irrigation")], 95),
        offload_cloud_pct=100 * (on_cloud & (np.array([names[t] for t in ty]) != "storage")).sum() / max(1, (np.array([names[t] for t in ty]) != "storage").sum()),
        fallback_pct=100 * R["fallback"].mean(),
        eval_us=R["eval_us"],
        violations_pct=100 * R["viol"].mean(),
    )
    return out
