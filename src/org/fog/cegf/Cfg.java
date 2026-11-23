package org.fog.cegf;

import java.util.*;
import org.json.simple.JSONObject;

/** Run configuration (static: one simulation per JVM). Time unit of the simulation clock is ms. */
public class Cfg {
    public static String scenario = "data";        // data | jobs
    public static String mode = "CEGF";            // data scenario: UG | SS | CEGF
    public static String policy = "cegf";          // jobs scenario: random | cloud | static | greedy | cegf
    public static double theta = 0.3, alpha = 0.25, tau = 0.7, load = 0.9, camScale = 1.0;
    public static long seed = 1;
    public static JSONObject policies;
    public static Map<String, Double> params = new HashMap<>();
    public static Random rnd = new Random(1);
    // runtime policy change (E3): parameters switch at changeT; outageMs > 0 models a hard-coded policy that needs a redeploy
    public static double changeT = -1, alpha2 = 0.5, tau2 = 0.9, outageMs = 0;
    public static Map<String, Double> params2 = new HashMap<>();
    public static Map<String, Double> paramsAt(double nowMs) { return (changeT >= 0 && nowMs >= changeT) ? params2 : params; }

    // ---- data scenario (1 h window starting 05:30, sunrise at 06:00)
    public static final double T0_S = 5.5 * 3600, WINDOW_MS = 3600e3;
    public static final int N_SENS = 40, N_CAM = 12, N_GW = 3;
    public static final double SENS_PERIOD_MS = 30e3, CAM_PERIOD_MS = 5e3;
    public static final double[] DEADLINE_MS = {2000, 8000};     // reading, frame

    // protocol model: {overhead B, qos(0/1), newconn prob, cpu factor}, edge-link and cloud-link
    public static double[] pEdge() { return proto(mode.equals("UG") ? "MQTT" : mode.equals("SS") ? "HTTPS" : "MQTTS"); }
    public static double[] pUp()   { return proto(mode.equals("UG") ? "MQTT" : "HTTPS"); }
    public static double[] proto(String p) {
        switch (p) {
            case "MQTT":  return new double[]{20, 0, 0.0, 1.00};
            case "MQTTS": return new double[]{45, 1, 0.0, 1.02};
            default:      return new double[]{700, 1, 0.5, 1.15};   // HTTPS
        }
    }
    public static boolean encrypted() { return !mode.equals("UG"); }

    // ---- job scenario
    public static class JT {
        public final String name; public final double mix; public final boolean crit, conf;
        public final double workS, sizeB, deadlineMs;
        JT(String n, double mix, boolean c, boolean f, double w, double s, double d) { name = n; this.mix = mix; crit = c; conf = f; workS = w; sizeB = s; deadlineMs = d; }
    }
    public static final JT[] JTYPES = {
        new JT("IRRIGATION", 0.45, true, false, 0.4, 2e3, 2000),
        new JT("DISEASE", 0.25, false, true, 3.0, 150e3, 15000),
        new JT("FERTIGATION", 0.10, true, true, 1.2, 20e3, 10000),
        new JT("STORAGE", 0.20, false, false, 0.5, 50e3, 120000)};
    public static JT jt(String name) { for (JT j : JTYPES) if (j.name.equals(name)) return j; return null; }
    public static final double HORIZON_MS = 1800e3;
    public static final double MI_PER_WORK_S = 1e6;          // 1 s of work on one "slot" = 1e6 MI
    public static final double EDGE_MIPS = 2000, CLOUD_MIPS = 16000;   // MI/ms; PS capacity = 2 / 16 slots
    public static final double UP_BW = 250, UP_LAT = 50;      // shared uplink: 250 B/ms (2 Mbit/s), 50 ms
}
