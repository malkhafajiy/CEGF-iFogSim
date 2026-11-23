package org.fog.cegf;

import java.util.HashMap;
import java.util.Map;
import java.util.Random;

import org.cloudbus.cloudsim.UtilizationModelFull;
import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.core.SimEvent;
import org.fog.application.AppEdge;
import org.fog.entities.Sensor;
import org.fog.entities.Tuple;
import org.fog.utils.FogEvents;
import org.fog.utils.FogUtils;
import org.fog.utils.distribution.Distribution;
import org.json.simple.JSONObject;

/**
 * Sensor that (i) applies the entropy-based data-selection policy before transmitting (CEGF mode),
 * (ii) models the communication protocol (overhead bytes, CPU cost, loss/retransmission),
 * and (iii) records per-item ground truth for the metrics. In the job scenario it just emits jobs.
 */
public class GovernedSensor extends Sensor {
    private final Random rnd;
    private final boolean jobSensor;

    public GovernedSensor(String name, String tupleType, int userId, String appId, Distribution d, long seed, boolean jobSensor) {
        super(name, tupleType, userId, appId, d);
        this.rnd = new Random(seed);
        this.jobSensor = jobSensor;
    }

    @Override
    public void processEvent(SimEvent ev) {
        if (ev.getTag() == FogEvents.EMIT_TUPLE) {
            if (jobSensor) emitJob(); else emitData();
            send(getId(), getTransmitDistribution().getNextValue(), FogEvents.EMIT_TUPLE);
        } else {
            super.processEvent(ev);
        }
    }

    private AppEdge edge() {
        for (AppEdge e : getApp().getEdges()) if (e.getSource().equals(getTupleType())) return e;
        throw new IllegalStateException("no edge for " + getTupleType());
    }

    private Tuple build(AppEdge e, double cpuMI, double nwBytes) {
        Tuple t = new Tuple(getAppId(), FogUtils.generateTupleId(), Tuple.UP, (long) cpuMI, 1, (long) nwBytes, 3,
                new UtilizationModelFull(), new UtilizationModelFull(), new UtilizationModelFull());
        t.setUserId(getUserId());
        t.setTupleType(getTupleType());
        t.setDestModuleName(e.getDestination());
        t.setSrcModuleName(getSensorName());
        t.setDestinationDeviceId(getGatewayDeviceId());
        return t;
    }

    // ------------------------------------------------------------------ data scenario
    private double gamma(double k) {
        if (k < 1) return gamma(k + 1) * Math.pow(rnd.nextDouble(), 1.0 / k);
        double d = k - 1.0 / 3, c = 1 / Math.sqrt(9 * d);
        while (true) {
            double x = rnd.nextGaussian(), v = 1 + c * x;
            if (v <= 0) continue;
            v = v * v * v;
            double u = rnd.nextDouble();
            if (Math.log(u) < 0.5 * x * x + d - d * v + d * Math.log(v)) return d * v;
        }
    }

    private double beta(double a, double b) { double x = gamma(a), y = gamma(b); return x / (x + y); }

    private void emitData() {
        double nowMs = CloudSim.clock();
        if (nowMs > Cfg.WINDOW_MS) return;
        boolean frame = getTupleType().equals("FRAME");
        double ramp = 1 / (1 + Math.exp(-((Cfg.T0_S + nowMs / 1000) - 6 * 3600) / 1200.0));
        double pu = frame ? 0.08 + 0.55 * ramp : 0.10 + 0.60 * ramp;
        boolean useful = rnd.nextDouble() < pu;
        double H = useful ? beta(5, 2) : beta(1.5, 8);
        Metrics.Rec r = Metrics.newRec(getTupleType(), nowMs, Cfg.DEADLINE_MS[frame ? 1 : 0]);
        r.useful = useful;
        if (Cfg.mode.equals("CEGF")) {
            Map<String, Object> ctx = new HashMap<>();
            ctx.put("entropy", H);
            if (!OdrlEval.permitted((JSONObject) Cfg.policies.get("entropy"), ctx, Cfg.params)) { r.selected = false; return; }
        }
        double[] p = Cfg.pEdge();
        double size = frame ? 150e3 : 60;
        if (!frame) Metrics.sensorEnergyJ += (size + p[0]) * 2e-6 + (rnd.nextDouble() < p[2] ? 0.02 : 0);
        boolean retx = rnd.nextDouble() < 0.02;
        if (retx && p[1] == 0) { r.lost = true; return; }              // QoS0: message silently lost
        double svcS = frame ? Math.exp(Math.log(1.8) - 0.045 + 0.3 * rnd.nextGaussian()) : 0.02;
        Tuple t = build(edge(), svcS * Cfg.MI_PER_WORK_S * p[3], size + p[0]);
        double delay = 5 + (-10 * Math.log(1 - rnd.nextDouble())) + size / 5000.0
                + (rnd.nextDouble() < p[2] ? 30 : 0) + (retx ? 200 + (rnd.nextDouble() < 0.02 ? 200 : 0) : 0);
        r.bytes = size + p[0];
        Metrics.recs.put(t.getCloudletId(), r);
        send(getGatewayDeviceId(), delay, FogEvents.TUPLE_ARRIVAL, t);
    }

    // ------------------------------------------------------------------ job scenario
    private void emitJob() {
        double nowMs = CloudSim.clock();
        if (nowMs > Cfg.HORIZON_MS) return;
        Cfg.JT j = Cfg.jt(getTupleType());
        Metrics.Rec r = Metrics.newRec(j.name, nowMs, nowMs + j.deadlineMs);   // deadline stored as absolute time
        Tuple t = build(edge(), j.workS * Cfg.MI_PER_WORK_S, j.sizeB);
        Metrics.recs.put(t.getCloudletId(), r);
        send(getGatewayDeviceId(), 5 + j.sizeB / 5000.0, FogEvents.TUPLE_ARRIVAL, t);
    }
}
