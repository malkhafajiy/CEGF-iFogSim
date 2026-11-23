"""Minimal ODRL evaluator for the CEGF listings (permission / prohibition, conflict=prohibit).

It evaluates the *same JSON* as the paper's listings (entropy policy, job-recipient policy),
so the simulator's decisions are produced by the policy documents themselves and can be
swapped at run time (experiment E4).
"""
import operator

OPS = {"odrl:eq": operator.eq, "odrl:lt": operator.lt, "odrl:lteq": operator.le,
       "odrl:gt": operator.gt, "odrl:gteq": operator.ge, "odrl:neq": operator.ne}

# leftOperand IRI (suffix after ".../vocab/") -> key in the evaluation context
LEFT = {"entropy": "entropy", "job/critical": "job.critical", "job/confidential": "job.confidential",
        "recipient/availability": "recipient.availability", "recipient/trust": "recipient.trust"}


def _val(v, params):
    if isinstance(v, dict):
        v = v.get("@value")
    if v in params:
        return params[v]
    if v in ("true", "false"):
        return v == "true"
    return float(v)


def _refs_ok(refs, ctx, params):
    for r in refs or []:
        key = LEFT[r["leftOperand"].split("/vocab/")[-1]]
        if not OPS[r["operator"]](ctx[key], _val(r["rightOperand"], params)):
            return False
    return True


def _action_ok(action, ctx, params):
    if isinstance(action, str):
        return True
    return all(_refs_ok(a.get("refinement"), ctx, params) for a in action)


def _target_ok(target, ctx, params):
    if isinstance(target, dict):
        return _refs_ok(target.get("refinement"), ctx, params)
    return True


def _applies(rule, ctx, params):
    return _target_ok(rule.get("target"), ctx, params) and _action_ok(rule.get("action", []), ctx, params)


def permitted(policy, ctx, params):
    """True iff some permission applies and (conflict=prohibit) no prohibition applies."""
    ok = any(_applies(p, ctx, params) for p in policy.get("permission", []))
    if ok and policy.get("conflict") == "odrl:prohibit":
        ok = not any(_applies(p, ctx, params) for p in policy.get("prohibition", []))
    return ok


# ---- the two policies from the paper (Listings: entropy-based selection, job-recipient selection)
ENTROPY_POLICY = {
    "@context": "http://www.w3.org/ns/odrl/2/", "@type": "Set",
    "permission": [{
        "assignee": "role:DataOwner", "target": "http://.../data/",
        "action": [{"rdf:value": {"@id": "odrl:select"},
                    "refinement": [{"leftOperand": "http://.../vocab/entropy", "operator": "odrl:gteq",
                                    "rightOperand": {"@value": "theta", "@type": "xsd:double"}}]}]}]}

RECIPIENT_POLICY = {
    "@context": "http://www.w3.org/ns/odrl/2/", "@type": "Set", "conflict": "odrl:prohibit",
    "permission": [{"assignee": "http://.../role/Initiator", "target": "http://.../job/", "action": "odrl:move"}],
    "prohibition": [
        {"assignee": "http://.../role/Initiator",
         "target": {"@type": "AssetCollection", "source": "http://.../job/",
                    "refinement": [{"leftOperand": "http://.../vocab/job/critical", "operator": "odrl:eq",
                                    "rightOperand": {"@value": "true", "@type": "xsd:boolean"}}]},
         "action": [{"rdf:value": {"@id": "odrl:move"},
                     "refinement": [{"leftOperand": "http://.../vocab/recipient/availability",
                                     "operator": "odrl:lt", "rightOperand": {"@value": "alpha"}}]}]},
        {"assignee": "http://.../role/Initiator",
         "target": {"@type": "AssetCollection", "source": "http://.../job/",
                    "refinement": [{"leftOperand": "http://.../vocab/job/confidential", "operator": "odrl:eq",
                                    "rightOperand": {"@value": "true", "@type": "xsd:boolean"}}]},
         "action": [{"rdf:value": {"@id": "odrl:move"},
                     "refinement": [{"leftOperand": "http://.../vocab/recipient/trust",
                                     "operator": "odrl:lt", "rightOperand": {"@value": "tau"}}]}]}]}
