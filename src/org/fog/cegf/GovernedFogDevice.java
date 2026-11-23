package org.fog.cegf;

import java.util.*;

import org.cloudbus.cloudsim.Cloudlet;
import org.cloudbus.cloudsim.Host;
import org.cloudbus.cloudsim.Vm;
import org.cloudbus.cloudsim.core.CloudActionTags;
import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.core.SimEvent;
import org.cloudbus.cloudsim.power.models.PowerModel;
import org.fog.application.AppModule;
import org.fog.application.Application;
import org.fog.entities.FogDevice;
import org.fog.entities.Tuple;
import org.fog.utils.FogEvents;
import org.fog.utils.Logger;
import org.fog.utils.TimeKeeper;
import org.json.simple.JSONObject;

/**
 * Fog device that (a) in the job scenario applies the CEGF job-recipient policy (Listing "recipient")
 * or one of the baseline placement strategies when a job arrives at an edge gateway, and
 * (b) records completion times. Roles: "edge", "cloud", "proxy" (shared uplink, no compute).
 */
public class GovernedFogDevice extends FogDevice {
    public static final List<GovernedFogDevice> EDGES = new ArrayList<>();
    public static GovernedFogDevice CLOUD;
    public static GovernedFogDevice PROXY;

    public final String role;
    public final double trust;
    public final double slots;
    private final double mips;
    private double pendingWork = 0;          // MI accepted and not yet completed
    private int pendingCount = 0;
    private final Set<Integer> tracked = new HashSet<>();
    private static final Set<Integer> placed = new HashSet<>();

    public GovernedFogDevice(String name, String role, double trust, double slots, double mips,
                             org.fog.entities.FogDeviceCharacteristics ch, org.cloudbus.cloudsim.VmAllocationPolicy vmap,
                             List<org.cloudbus.cloudsim.Storage> storage, double upBw, double downBw, double ratePerMips) throws Exception {
        super(name, ch, vmap, storage, 10, upBw, downBw, 0, ratePerMips);
        this.role = role; this.trust = trust; this.slots = slots; this.mips = mips;
        if (role.equals("edge")) EDGES.add(this);
        if (role.equals("cloud")) CLOUD = this;
        if (role.equals("proxy")) PROXY = this;
    }

    /** Peer links between edge gateways (iFogSim2 cluster links). */
    public void configureCluster(List<GovernedFogDevice> peers, double latencyMs, double bwBytesPerMs) {
        Map<Integer, Double> lat = new HashMap<>();
        for (GovernedFogDevice p : peers) if (p != this) { addClusterMember(p.getId()); lat.put(p.getId(), latencyMs); }
        setClusterMembersToLatencyMap(lat);
        setClusterLinkBandwidth(bwBytesPerMs);
        setIsInCluster(true);
    }

    // ------------------------------------------------------------------ state seen by policies
    public double availability() { return Math.max(0.0, 1.0 - pendingCount / slots); }

    private double uplinkBacklogMs() {
        double b = 0;
        for (Tuple t : PROXY.getNorthTupleQueue()) b += t.getCloudletFileSize();
        return b / Cfg.UP_BW;
    }

    /** Estimated completion time of a job of {@code lenMI}/{@code size} if placed on this node now. */
    private double estCompletion(GovernedFogDevice home, double now, double lenMI, double size) {
        double net;
        if (this == home) net = 0;
        else if (role.equals("edge")) net = 2 + size / 5000.0;
        else net = (size + 1) / Cfg.UP_BW + uplinkBacklogMs() + Cfg.UP_LAT + 1;
        return now + net + (pendingWork + lenMI) / mips;
    }

    private boolean eligible(Cfg.JT j, GovernedFogDevice n) {
        Map<String, Object> ctx = new HashMap<>();
        ctx.put("job.critical", j.crit); ctx.put("job.confidential", j.conf);
        ctx.put("recipient.availability", n.availability()); ctx.put("recipient.trust", n.trust);
        return OdrlEval.permitted((JSONObject) Cfg.policies.get("recipient"), ctx, Cfg.paramsAt(CloudSim.clock()));
    }

    // ------------------------------------------------------------------ tuple handling
    @Override
    protected void processTupleArrival(SimEvent ev) {
        Tuple t = (Tuple) ev.getData();
        if (role.equals("proxy") && t.getDirection() == Tuple.UP) Metrics.uplinkBytes += t.getCloudletFileSize();
        if (Cfg.scenario.equals("jobs") && role.equals("edge") && t.getDirection() == Tuple.UP
                && Cfg.jt(t.getTupleType()) != null && !placed.contains(t.getCloudletId())) {
            route(ev, t);
            return;
        }
        if (hasModuleFor(t)) track(t);
        super.processTupleArrival(ev);
    }

    private boolean hasModuleFor(Tuple t) {
        return appToModulesMap.containsKey(t.getAppId()) && appToModulesMap.get(t.getAppId()).contains(t.getDestModuleName());
    }

    private void track(Tuple t) {
        if (tracked.add(t.getCloudletId())) { pendingWork += t.getCloudletLength(); pendingCount++; }
    }

    private void route(SimEvent ev, Tuple t) {
        Cfg.JT j = Cfg.jt(t.getTupleType());
        Metrics.Rec r = Metrics.recs.get(t.getCloudletId());
        double now = CloudSim.clock(), lenMI = t.getCloudletLength(), size = t.getCloudletFileSize();
        if (Cfg.outageMs > 0 && now >= Cfg.changeT && now < Cfg.changeT + Cfg.outageMs) {   // redeploy window: no decisions
            send(getId(), Cfg.changeT + Cfg.outageMs - now, FogEvents.TUPLE_ARRIVAL, t);
            return;
        }
        List<GovernedFogDevice> all = new ArrayList<>(EDGES); all.add(CLOUD);
        GovernedFogDevice target = null;
        switch (Cfg.policy) {
            case "random": target = all.get(Cfg.rnd.nextInt(all.size())); break;
            case "cloud": target = CLOUD; break;
            case "static": target = j.name.equals("STORAGE") ? CLOUD : this; break;
            case "greedy": {
                double best = Double.MAX_VALUE;
                for (GovernedFogDevice n : all) { double e = n.estCompletion(this, now, lenMI, size); if (e < best) { best = e; target = n; } }
                break;
            }
            default: { // cegf
                List<GovernedFogDevice> pref = j.name.equals("STORAGE") ? Collections.singletonList(CLOUD) : EDGES;
                List<GovernedFogDevice> cand = new ArrayList<>();
                double best = Double.MAX_VALUE;
                for (GovernedFogDevice n : pref) if (eligible(j, n)) { cand.add(n); best = Math.min(best, n.estCompletion(this, now, lenMI, size)); }
                if (best > r.deadline && !j.name.equals("STORAGE"))           // overloaded: offload to peers / cloud allowed by the policy
                    for (GovernedFogDevice n : all) if (!pref.contains(n) && eligible(j, n)) cand.add(n);
                if (!cand.isEmpty()) {
                    best = Double.MAX_VALUE;
                    for (GovernedFogDevice n : cand) { double e = n.estCompletion(this, now, lenMI, size); if (e < best) { best = e; target = n; } }
                } else if (j.conf) {                                           // fallback: hold at the initiator and retry
                    r.fallback = true;
                    if (now + 500 < r.deadline) send(getId(), 500, FogEvents.TUPLE_ARRIVAL, t);
                    else r.rejected = true;
                    return;
                } else { target = this; r.fallback = true; }                  // fallback: execute at the initiator
            }
        }
        // audit against the policy in force right now (declared fallbacks are not violations)
        r.violation = !eligible(j, target) && !r.fallback;
        placed.add(t.getCloudletId());
        r.placed = true; r.node = target.getName(); r.tauUsed = Cfg.paramsAt(now).get("tau");
        if (target == this) {
            track(t); super.processTupleArrival(ev);
        } else if (target.role.equals("edge")) {
            track0(target, t); sendToCluster(t, target.getId());
        } else {
            track0(target, t); sendUp(t);
        }
    }

    /** Reserve capacity on the target as soon as the decision is taken (the tuple is in flight). */
    private void track0(GovernedFogDevice target, Tuple t) { target.track(t); }

    @Override
    protected void checkCloudletCompletion() {
        boolean cloudletCompleted = false;
        List<? extends Host> list = getVmAllocationPolicy().getHostList();
        for (int i = 0; i < list.size(); i++) {
            Host host = list.get(i);
            for (Vm vm : host.getVmList()) {
                while (vm.getCloudletScheduler().isFinishedCloudlets()) {
                    Cloudlet cl = vm.getCloudletScheduler().getNextFinishedCloudlet();
                    if (cl != null) {
                        cloudletCompleted = true;
                        Tuple tuple = (Tuple) cl;
                        Metrics.Rec rec = Metrics.recs.get(tuple.getCloudletId());
                        if (rec != null) { rec.done = CloudSim.clock(); if (rec.node.isEmpty()) rec.node = getName(); }
                        if (tracked.remove(tuple.getCloudletId())) { pendingWork -= tuple.getCloudletLength(); pendingCount--; }
                        TimeKeeper.getInstance().tupleEndedExecution(tuple);
                        Application application = getApplicationMap().get(tuple.getAppId());
                        Logger.debug(getName(), "Completed execution of tuple " + tuple.getCloudletId());
                        List<Tuple> resultantTuples = application.getResultantTuples(tuple.getDestModuleName(), tuple, getId(), vm.getId());
                        for (Tuple resTuple : resultantTuples) {
                            resTuple.setModuleCopyMap(new HashMap<String, Integer>(tuple.getModuleCopyMap()));
                            resTuple.getModuleCopyMap().put(((AppModule) vm).getName(), vm.getId());
                            updateTimingsOnSending(resTuple);
                            sendToSelf(resTuple);
                        }
                        sendNow(cl.getUserId(), CloudActionTags.CLOUDLET_RETURN, cl);
                    }
                }
            }
        }
        if (cloudletCompleted) updateAllocatedMips(null);
    }
}
