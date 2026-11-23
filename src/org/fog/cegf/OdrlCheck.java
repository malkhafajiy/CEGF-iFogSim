package org.fog.cegf;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

import org.json.simple.JSONObject;

/**
 * Conformance helper: evaluates the simulator's ODRL policies on test cases read from stdin, so that the decisions
 * can be compared with an independent ODRL evaluator (see experiments/odrl_engine/crosscheck_oval.py).
 * Usage: OdrlCheck policies.json alpha tau theta   (stdin lines: "R crit conf availability trust" | "E entropy")
 */
public class OdrlCheck {
    public static void main(String[] a) throws Exception {
        JSONObject pol = OdrlEval.load(a[0]);
        Map<String, Double> params = new HashMap<>();
        params.put("alpha", Double.parseDouble(a[1]));
        params.put("tau", Double.parseDouble(a[2]));
        params.put("theta", Double.parseDouble(a[3]));
        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
        for (String ln; (ln = br.readLine()) != null; ) {
            String[] f = ln.trim().split("\\s+");
            Map<String, Object> ctx = new HashMap<>();
            boolean ok;
            if (f[0].equals("R")) {
                ctx.put("job.critical", Boolean.parseBoolean(f[1]));
                ctx.put("job.confidential", Boolean.parseBoolean(f[2]));
                ctx.put("recipient.availability", Double.parseDouble(f[3]));
                ctx.put("recipient.trust", Double.parseDouble(f[4]));
                ok = OdrlEval.permitted((JSONObject) pol.get("recipient"), ctx, params);
            } else {
                ctx.put("entropy", Double.parseDouble(f[1]));
                ok = OdrlEval.permitted((JSONObject) pol.get("entropy"), ctx, params);
            }
            System.out.println(String.format(Locale.ROOT, "%s", ok));
        }
    }
}
