package org.fog.cegf;

import java.util.*;

import org.cloudbus.cloudsim.Log;
import org.cloudbus.cloudsim.core.CloudSim;
import org.fog.application.AppEdge;
import org.fog.application.Application;
import org.fog.application.selectivity.FractionalSelectivity;
import org.fog.entities.Actuator;
import org.fog.entities.FogBroker;
import org.fog.entities.FogDevice;
import org.fog.entities.Sensor;
import org.fog.entities.Tuple;
import org.fog.placement.Controller;
import org.fog.placement.ModuleMapping;
import org.fog.placement.ModulePlacementMapping;
import org.fog.utils.Config;
import org.fog.utils.FogLinearPowerModel;
import org.fog.utils.TimeKeeper;

/**
 * Precision-farming experiment on iFogSim2: one simulation per JVM.
 * Usage: FarmExperiment key=value ...   (scenario, mode, policy, seed, theta, alpha, tau, load, cam, policies)
 * Prints one line "RESULT k=v,k=v,..." on exit.
 */
public class FarmExperiment {
    static List<FogDevice> fogDevices = new ArrayList<>();
    static List<Sensor> sensors = new ArrayList<>();
    static List<Actuator> actuators = new ArrayList<>();
    static double endMs;

    public static void main(String[] args) throws Exception {
        Map<String, String> a = new HashMap<>();
        for (String s : args) { String[] kv = s.split("=", 2); a.put(kv[0], kv[1]); }
        Cfg.scenario = a.getOrDefault("scenario", "data");
        Cfg.mode = a.getOrDefault("mode", "CEGF");
        Cfg.policy = a.getOrDefault("policy", "cegf");
        Cfg.seed = Long.parseLong(a.getOrDefault("seed", "1"));
        Cfg.theta = Double.parseDouble(a.getOrDefault("theta", "0.3"));
        Cfg.alpha = Double.parseDouble(a.getOrDefault("alpha", "0.25"));
        Cfg.tau = Double.parseDouble(a.getOrDefault("tau", "0.7"));
        Cfg.load = Double.parseDouble(a.getOrDefault("load", "0.9"));
        Cfg.camScale = Double.parseDouble(a.getOrDefault("cam", "1.0"));
        Cfg.tracePath = a.get("trace");
        if (Cfg.tracePath != null) {
            org.json.simple.JSONObject tm = OdrlEval.load(new java.io.File(Cfg.tracePath).getParent() + "/trace_meta.json");
            org.json.simple.JSONObject pr = (org.json.simple.JSONObject) tm.get("params");
            Cfg.speedup = ((Number) pr.get("speedup")).doubleValue();
            Cfg.realStartH = ((Number) tm.get("real_start_hour")).doubleValue();
            Cfg.sunriseH = ((Number) tm.get("sunrise_hour")).doubleValue();
        }
        Cfg.policies = OdrlEval.load(a.getOrDefault("policies", "experiments/odrl_engine/policies.json"));
        Cfg.params.put("theta", Cfg.theta); Cfg.params.put("alpha", Cfg.alpha); Cfg.params.put("tau", Cfg.tau);
        Cfg.rnd = new Random(Cfg.seed + 77);
        Cfg.changeT = Double.parseDouble(a.getOrDefault("change_t", "-1")) * 1000;
        Cfg.alpha2 = Double.parseDouble(a.getOrDefault("alpha2", "0.5")); Cfg.tau2 = Double.parseDouble(a.getOrDefault("tau2", "0.9"));
        Cfg.outageMs = Double.parseDouble(a.getOrDefault("outage_s", "0")) * 1000;
        Cfg.params2.put("theta", Cfg.theta); Cfg.params2.put("alpha", Cfg.alpha2); Cfg.params2.put("tau", Cfg.tau2);
        boolean data = Cfg.scenario.equals("data");
        endMs = data ? Cfg.WINDOW_MS + 30e3 : Cfg.HORIZON_MS + 130e3;
        Config.MAX_SIMULATION_TIME = (int) endMs;

        Log.disable();
        CloudSim.init(1, Calendar.getInstance(), false);
        FogBroker broker = new FogBroker("broker");
        Application app = Application.createApplication("farm", broker.getId());
        app.setUserId(broker.getId());
        app.setLoops(new ArrayList<>());

        // ---- topology: cloud <- uplink proxy (shared 2 Mbit/s link) <- 3 edge gateways (+ peer links)
        GovernedFogDevice cloud = dev("cloud", "cloud", 0.95, 8, (long) Cfg.CLOUD_MIPS, 0, -1, 0, 100);
        GovernedFogDevice proxy = dev("uplink", "proxy", 1.0, 0, 1000, 1, cloud.getId(), Cfg.UP_LAT, Cfg.UP_BW);
        double[] trust = {0.90, 0.85, 0.55};
        List<GovernedFogDevice> edges = new ArrayList<>();
        for (int i = 0; i < Cfg.N_GW; i++) edges.add(dev("e" + (i + 1), "edge", trust[i], 2, (long) Cfg.EDGE_MIPS, 2, proxy.getId(), 1, 5000));
        for (GovernedFogDevice e : edges) e.configureCluster(edges, 2.0, 5000);

        ModuleMapping mm = ModuleMapping.createModuleMapping();
        if (data) {
            app.addAppModule("ctrl", 10); app.addAppModule("archive", 10);
            app.addAppEdge("READING", "ctrl", 0, 0, "READING", Tuple.UP, AppEdge.SENSOR);
            app.addAppEdge("FRAME", "ctrl", 0, 0, "FRAME", Tuple.UP, AppEdge.SENSOR);
            double ohUp = Cfg.pUp()[0];
            app.addAppEdge("ctrl", "archive", 5e4, 120 + ohUp, "SUMMARY_R", Tuple.UP, AppEdge.MODULE);
            app.addAppEdge("ctrl", "archive", 5e4, 2000 + ohUp, "SUMMARY_F", Tuple.UP, AppEdge.MODULE);
            app.addTupleMapping("ctrl", "READING", "SUMMARY_R", new FractionalSelectivity(1.0));
            app.addTupleMapping("ctrl", "FRAME", "SUMMARY_F", new FractionalSelectivity(1.0));
            for (GovernedFogDevice e : edges) mm.addModuleToDevice("ctrl", e.getName());
            mm.addModuleToDevice("archive", "cloud");
            if (Cfg.tracePath == null) {
                for (int i = 0; i < Cfg.N_SENS; i++)
                    addSensor("s" + i, "READING", edges.get(i % 3), new Dists.Periodic(Cfg.SENS_PERIOD_MS, Cfg.seed * 1000 + i), Cfg.seed * 7 + i, false, broker);
            } else {
                Map<Integer, List<double[]>> byStream = new TreeMap<>();
                try (java.io.BufferedReader br = new java.io.BufferedReader(new java.io.FileReader(Cfg.tracePath))) {
                    br.readLine();                                          // header: t_ms,stream_id,comp,channel,zone,kind,value,entropy,useful
                    for (String ln; (ln = br.readLine()) != null; ) {
                        String[] f = ln.split(",");
                        byStream.computeIfAbsent(Integer.parseInt(f[1]), k -> new ArrayList<>())
                                .add(new double[]{Double.parseDouble(f[0]), Double.parseDouble(f[7]), Double.parseDouble(f[8])});
                    }
                }
                for (Map.Entry<Integer, List<double[]>> e : byStream.entrySet()) {
                    List<double[]> rows = e.getValue();
                    rows.sort((x, y) -> Double.compare(x[0], y[0]));
                    double[] ts = new double[rows.size()];
                    for (int k = 0; k < ts.length; k++) ts[k] = rows.get(k)[0];
                    GovernedSensor gs = addSensor("s" + e.getKey(), "READING", edges.get(e.getKey() % 3), new Dists.Replay(ts), Cfg.seed * 7 + e.getKey(), false, broker);
                    gs.setTrace(rows); gs.setTransmissionStartDelay(0);
                }
            }
            int nCam = (int) Math.round(Cfg.N_CAM * Cfg.camScale);
            for (int i = 0; i < nCam; i++)
                addSensor("c" + i, "FRAME", edges.get(i % 3), new Dists.Periodic(Cfg.CAM_PERIOD_MS, Cfg.seed * 1000 + 500 + i), Cfg.seed * 13 + i, false, broker);
        } else {
            app.addAppModule("worker", 10);
            for (Cfg.JT j : Cfg.JTYPES) app.addAppEdge(j.name, "worker", 0, 0, j.name, Tuple.UP, AppEdge.SENSOR);
            for (GovernedFogDevice e : edges) mm.addModuleToDevice("worker", e.getName());
            mm.addModuleToDevice("worker", "cloud");
            double edgeWork = 0; for (Cfg.JT j : Cfg.JTYPES) if (!j.name.equals("STORAGE")) edgeWork += j.mix * j.workS;
            double lambda = Cfg.load * (3 * 2) / edgeWork;                  // jobs / s
            int k = 0;
            for (Cfg.JT j : Cfg.JTYPES)
                for (int g = 0; g < 3; g++) {
                    double meanMs = 1000.0 / (lambda * j.mix / 3);
                    addSensor("j" + (k++), j.name, edges.get(g), new Dists.Poisson(meanMs, Cfg.seed * 31 + k), Cfg.seed * 17 + k, true, broker);
                }
        }

        Controller controller = new Controller("master-controller", fogDevices, sensors, actuators);
        controller.submitApplication(app, 0, new ModulePlacementMapping(fogDevices, app, mm));
        TimeKeeper.getInstance().setSimulationStartTime(Calendar.getInstance().getTimeInMillis());
        Runtime.getRuntime().addShutdownHook(new Thread(() -> System.out.println(data ? reportData() : reportJobs())));
        CloudSim.startSimulation();
        CloudSim.stopSimulation();
    }

    static GovernedFogDevice dev(String name, String role, double trust, double slots, long mips, int level, int parent, double upLat, double upBw) throws Exception {
        List<org.cloudbus.cloudsim.Pe> peList = new ArrayList<>();
        peList.add(new org.cloudbus.cloudsim.Pe(0, new org.cloudbus.cloudsim.sdn.overbooking.PeProvisionerOverbooking(mips)));
        org.cloudbus.cloudsim.power.PowerHost host = new org.cloudbus.cloudsim.power.PowerHost(
                org.fog.utils.FogUtils.generateEntityId(), new org.cloudbus.cloudsim.provisioners.RamProvisionerSimple(4000),
                new org.cloudbus.cloudsim.sdn.overbooking.BwProvisionerOverbooking(10000), 1000000, peList,
                new org.fog.scheduler.StreamOperatorScheduler(peList), new FogLinearPowerModel(107.339, 83.4333));
        List<org.cloudbus.cloudsim.Host> hostList = new ArrayList<>(); hostList.add(host);
        org.fog.entities.FogDeviceCharacteristics ch = new org.fog.entities.FogDeviceCharacteristics(
                "x86", "Linux", "Xen", host, 10.0, 3.0, 0.05, 0.001, 0.0);
        GovernedFogDevice d = new GovernedFogDevice(name, role, trust, slots, mips, ch,
                new org.fog.policy.AppModuleAllocationPolicy(hostList), new LinkedList<org.cloudbus.cloudsim.Storage>(), upBw, 10000, 0.0);
        d.setLevel(level); d.setParentId(parent); d.setUplinkLatency(upLat);
        fogDevices.add(d);
        return d;
    }

    static GovernedSensor addSensor(String name, String type, GovernedFogDevice gw, org.fog.utils.distribution.Distribution dist, long seed, boolean job, FogBroker broker) {
        GovernedSensor s = new GovernedSensor(name, type, broker.getId(), "farm", dist, seed, job);
        s.setGatewayDeviceId(gw.getId()); s.setLatency(5.0);
        sensors.add(s);
        return s;
    }

    // ------------------------------------------------------------------ reports
    static String kv(String k, double v) { return k + "=" + String.format(Locale.ROOT, "%.6f", v); }

    static String reportData() {
        int total = 0, usefulN = 0, usefulSel = 0, timely = 0, sel = 0, readUseful = 0, readUsefulLost = 0, readN = 0, readSel = 0, readUsefulSel = 0, readTimely = 0;
        List<Double> tta = new ArrayList<>(); double latSum = 0; int latN = 0;
        for (Metrics.Rec r : Metrics.all) {
            total++;
            if (r.selected) sel++;
            if (r.type.equals("READING")) { readN++; if (r.selected) readSel++; }
            if (r.useful) {
                usefulN++;
                if (r.selected) usefulSel++;
                if (r.type.equals("READING")) { readUseful++; if (r.lost) readUsefulLost++; if (r.selected) readUsefulSel++; }
            }
            if (r.selected && !r.lost && !Double.isNaN(r.done)) {
                double lat = r.done - r.emit; latSum += lat; latN++;
                if (r.useful) { tta.add(lat / 1000); if (lat <= r.deadline) { timely++; if (r.type.equals("READING")) readTimely++; } }
            }
        }
        double unenc = Cfg.encrypted() ? 0 : 100;
        return "RESULT " + String.join(",", kv("TUDR", (double) timely / usefulN), kv("recall", (double) usefulSel / usefulN),
                kv("volume_sel", (double) sel / total), kv("uplink_MB", Metrics.uplinkBytes / 1e6),
                kv("tta_p95", Metrics.percentile(tta, 95)), kv("edge_lat_mean_s", latN == 0 ? Double.NaN : latSum / latN / 1000),
                kv("loss_useful_readings", (double) readUsefulLost / Math.max(1, readUseful)),
                kv("energy_J_per_sensor_h", Metrics.sensorEnergyJ / Cfg.N_SENS), kv("unencrypted_pct", unenc),
                kv("recall_read", (double) readUsefulSel / Math.max(1, readUseful)), kv("TUDR_read", (double) readTimely / Math.max(1, readUseful)), kv("volume_sel_read", (double) readSel / Math.max(1, readN)), kv("useful_read_frac", (double) readUseful / Math.max(1, readN)), kv("items", total));
    }

    static String reportJobs() {
        Map<String, Double> trustOf = new HashMap<>();
        for (GovernedFogDevice e : GovernedFogDevice.EDGES) trustOf.put(e.getName(), e.trust);
        trustOf.put("cloud", GovernedFogDevice.CLOUD.trust);
        int critPre = 0, critPreMiss = 0, critPost = 0, critPostMiss = 0;
        int n = 0, crit = 0, critMiss = 0, dis = 0, disMiss = 0, miss = 0, conf = 0, confViol = 0, viol = 0, fb = 0, rej = 0, nonSt = 0, nonStCloud = 0;
        List<Double> irrLat = new ArrayList<>();
        for (Metrics.Rec r : Metrics.all) {
            if (r.deadline > endMs) continue;                                  // outcome not observable within the run
            Cfg.JT j = Cfg.jt(r.type);
            boolean missed = r.rejected || Double.isNaN(r.done) || r.done > r.deadline;
            n++; if (missed) miss++;
            if (j.crit) { crit++; if (missed) critMiss++; if (Cfg.changeT >= 0) { if (r.emit < Cfg.changeT) { critPre++; if (missed) critPreMiss++; } else { critPost++; if (missed) critPostMiss++; } } }
            if (j.name.equals("DISEASE")) { dis++; if (missed) disMiss++; }
            if (j.conf) { conf++; if (r.placed && trustOf.get(r.node) < r.tauUsed) confViol++; }
            if (r.violation) viol++;
            if (r.fallback) fb++;
            if (r.rejected) rej++;
            if (!j.name.equals("STORAGE")) { nonSt++; if (r.node.equals("cloud")) nonStCloud++; }
            if (j.name.equals("IRRIGATION") && !Double.isNaN(r.done)) irrLat.add((r.done - r.emit) / 1000);
        }
        return "RESULT " + String.join(",", kv("miss_all", Metrics.pct(miss, n)), kv("miss_critical", Metrics.pct(critMiss, crit)),
                kv("miss_disease", Metrics.pct(disMiss, dis)), kv("conf_viol_pct", Metrics.pct(confViol, conf)),
                kv("violations_pct", Metrics.pct(viol, n)), kv("lat_p95_irrig", Metrics.percentile(irrLat, 95)),
                kv("offload_cloud_pct", Metrics.pct(nonStCloud, nonSt)), kv("fallback_pct", Metrics.pct(fb, n)),
                kv("rejected_pct", Metrics.pct(rej, n)), kv("miss_crit_pre", Metrics.pct(critPreMiss, critPre)), kv("miss_crit_post", Metrics.pct(critPostMiss, critPost)), kv("jobs", n));
    }
}
