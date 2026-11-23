package org.fog.cegf;

import java.io.FileReader;
import java.util.Map;

import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import org.json.simple.parser.JSONParser;

/**
 * Minimal ODRL evaluator for the CEGF listings (permission / prohibition, conflict=prohibit).
 * It evaluates the same JSON documents as the paper's listings (see experiments/odrl_engine/policies.json),
 * so decisions inside the iFogSim simulation are produced by the policy documents themselves.
 */
public class OdrlEval {

    public static JSONObject load(String file) throws Exception {
        try (FileReader r = new FileReader(file)) {
            return (JSONObject) new JSONParser().parse(r);
        }
    }

    private static Object value(Object v, Map<String, Double> params) {
        if (v instanceof JSONObject) v = ((JSONObject) v).get("@value");
        String s = String.valueOf(v);
        if (params.containsKey(s)) return params.get(s);
        if (s.equals("true")) return Boolean.TRUE;
        if (s.equals("false")) return Boolean.FALSE;
        return Double.parseDouble(s);
    }

    private static boolean cmp(String op, Object a, Object b) {
        if (a instanceof Boolean || b instanceof Boolean) {
            boolean eq = a.equals(b);
            return op.equals("odrl:eq") ? eq : !eq;
        }
        double x = ((Number) a).doubleValue(), y = ((Number) b).doubleValue();
        switch (op) {
            case "odrl:eq": return x == y;
            case "odrl:neq": return x != y;
            case "odrl:lt": return x < y;
            case "odrl:lteq": return x <= y;
            case "odrl:gt": return x > y;
            case "odrl:gteq": return x >= y;
            default: throw new IllegalArgumentException(op);
        }
    }

    private static String key(String leftOperand) {
        String k = leftOperand.substring(leftOperand.indexOf("/vocab/") + 7);
        switch (k) {
            case "job/critical": return "job.critical";
            case "job/confidential": return "job.confidential";
            case "recipient/availability": return "recipient.availability";
            case "recipient/trust": return "recipient.trust";
            default: return k;
        }
    }

    private static boolean refsOk(Object refs, Map<String, Object> ctx, Map<String, Double> params) {
        if (refs == null) return true;
        for (Object o : (JSONArray) refs) {
            JSONObject r = (JSONObject) o;
            Object left = ctx.get(key((String) r.get("leftOperand")));
            if (!cmp((String) r.get("operator"), left, value(r.get("rightOperand"), params))) return false;
        }
        return true;
    }

    private static boolean applies(JSONObject rule, Map<String, Object> ctx, Map<String, Double> params) {
        Object t = rule.get("target");
        if (t instanceof JSONObject && !refsOk(((JSONObject) t).get("refinement"), ctx, params)) return false;
        Object a = rule.get("action");
        if (a instanceof JSONArray)
            for (Object o : (JSONArray) a)
                if (!refsOk(((JSONObject) o).get("refinement"), ctx, params)) return false;
        return true;
    }

    /** True iff some permission applies and (conflict=prohibit) no prohibition applies. */
    public static boolean permitted(JSONObject policy, Map<String, Object> ctx, Map<String, Double> params) {
        boolean ok = false;
        JSONArray perm = (JSONArray) policy.get("permission");
        if (perm != null) for (Object p : perm) if (applies((JSONObject) p, ctx, params)) { ok = true; break; }
        if (ok && "odrl:prohibit".equals(policy.get("conflict"))) {
            JSONArray pro = (JSONArray) policy.get("prohibition");
            if (pro != null) for (Object p : pro) if (applies((JSONObject) p, ctx, params)) return false;
        }
        return ok;
    }
}
