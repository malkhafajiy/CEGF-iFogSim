package org.fog.cegf;

import java.util.*;

/** Static collectors for one simulation run (one JVM per run). */
public class Metrics {
    public static class Rec {
        public String type;          // READING, FRAME, IRRIGATION, DISEASE, FERTIGATION, STORAGE
        public double emit, done = Double.NaN, deadline;
        public boolean useful, selected = true, lost, placed, violation, fallback, rejected;
        public String node = ""; public double tauUsed;
        public double bytes;
    }

    public static final Map<Integer, Rec> recs = new HashMap<>();       // cloudletId -> record
    public static final List<Rec> all = new ArrayList<>();               // every generated item / job
    public static double uplinkBytes = 0;
    public static double sensorEnergyJ = 0;
    public static double edgeBusyMs = 0;

    public static Rec newRec(String type, double emit, double deadline) {
        Rec r = new Rec(); r.type = type; r.emit = emit; r.deadline = deadline; all.add(r); return r;
    }

    public static double pct(double a, double b) { return b <= 0 ? Double.NaN : 100.0 * a / b; }

    public static double percentile(List<Double> xs, double p) {
        if (xs.isEmpty()) return Double.NaN;
        Collections.sort(xs);
        double idx = p / 100.0 * (xs.size() - 1);
        int lo = (int) Math.floor(idx), hi = (int) Math.ceil(idx);
        return xs.get(lo) + (xs.get(hi) - xs.get(lo)) * (idx - lo);
    }
}
