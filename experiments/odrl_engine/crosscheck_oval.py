"""Cross-check the simulator's ODRL evaluator (Java OdrlEval) against the independent OVAL evaluator.

1. Validates job_recipient_policy.ttl and entropy_policy.ttl with the DIPS SHACL validator.
2. Evaluates a grid of test cases (incl. boundary values) with both evaluators and compares the decisions.

Setup : python -P experiments/odrl_engine/fetch_oval.py ; powershell experiments/ifogsim/build.ps1
Run   : python -I experiments/odrl_engine/crosscheck_oval.py        (from the repo root)
As a module: run() returns {"validation": ..., "cases": [...], "agree": n, "total": n} (used by experiments/run_pipeline.py).
"""
import glob
import itertools
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OVAL = os.environ.get("ODRL_ENGINE_PATH", os.path.join(HERE, "vendor", "ODRL-Engine"))
JAVA = (glob.glob(r"C:\Program Files\Microsoft\jdk-*\bin\java.exe") or ["java"])[0]
CP = os.pathsep.join(glob.glob(os.path.join(ROOT, "jars", "**", "*.jar"), recursive=True) + [os.path.join(ROOT, "experiments", "ifogsim", "build")])
POLICIES = os.path.join(HERE, "policies.json")
ALPHA, TAU, THETA = 0.25, 0.7, 0.3            # must equal the constants in the .ttl files
C = "https://example.org/cegf#"
ODRL = "http://www.w3.org/ns/odrl/2/"
AVAIL = [0.0, 0.1, 0.2, 0.24, 0.25, 0.26, 0.4, 0.5, 0.7, 0.9, 1.0]
TRUST = [0.3, 0.5, 0.6, 0.69, 0.7, 0.71, 0.8, 0.9, 0.95, 1.0]
ENTROPY = [0.0, 0.05, 0.1, 0.2, 0.29, 0.3, 0.31, 0.4, 0.5, 0.75, 1.0]


def java_decisions(recip, ent):
    lines = [f"R {str(c).lower()} {str(f).lower()} {a} {t}" for c, f, a, t in recip] + [f"E {h}" for h in ent]
    p = subprocess.run([JAVA, "-cp", CP, "org.fog.cegf.OdrlCheck", POLICIES, str(ALPHA), str(TAU), str(THETA)],
                       input="\n".join(lines), capture_output=True, text=True, cwd=ROOT)
    if p.returncode:
        sys.exit(p.stderr[-800:])
    return [x.strip() == "true" for x in p.stdout.split("\n") if x.strip()]


def run():
    if not os.path.isdir(OVAL):
        sys.exit("OVAL not found: run experiments/odrl_engine/fetch_oval.py first (or set ODRL_ENGINE_PATH)")
    cwd = os.getcwd()
    os.chdir(OVAL)                                   # OVAL loads its ODRL/SHACL resources relative to its own folder
    sys.path.insert(0, OVAL)
    try:
        import ODRL_Evaluator as E
        import validate

        validation = {}
        for f in ("job_recipient_policy.ttl", "entropy_policy.ttl"):
            r = validate.validate_ODRL_from_file(os.path.join(HERE, f))
            validation[f] = dict(valid_ODRL=bool(r["is_valid_ODRL"]), errors=len(r["errors"]), warnings=len(r["warnings"]), triples=r.get("ODRL_graph_size"))

        recip = list(itertools.product([True, False], [True, False], AVAIL, TRUST))
        jd = java_decisions(recip, ENTROPY)
        pol_r = open(os.path.join(HERE, "job_recipient_policy.ttl")).read() + "\ncegf:job1 odrl:partOf cegf:jobs .\n"
        pol_e = open(os.path.join(HERE, "entropy_policy.ttl")).read()
        cases = []
        for i, (c, f, a, t) in enumerate(recip):
            req = {ODRL + "Action": ODRL + "move", ODRL + "Asset": C + "job1", C + "critical": str(c).lower(),
                   C + "confidential": str(f).lower(), C + "availability": str(a), C + "trust": str(t)}
            o = E.evaluate_ODRL_access_request_from_string(json.dumps(req), pol_r).get("accept_decision")
            cases.append(dict(policy="job_recipient", critical=c, confidential=f, availability=a, trust=t, entropy="", oval=o, simulator=jd[i]))
        for j, h in enumerate(ENTROPY):
            req = {ODRL + "Action": ODRL + "select", ODRL + "Asset": C + "data", C + "entropy": str(h)}
            o = E.evaluate_ODRL_access_request_from_string(json.dumps(req), pol_e).get("accept_decision")
            cases.append(dict(policy="entropy", critical="", confidential="", availability="", trust="", entropy=h, oval=o, simulator=jd[len(recip) + j]))
    finally:
        os.chdir(cwd)
    agree = sum(1 for c in cases if c["oval"] == c["simulator"])
    return dict(validation=validation, cases=cases, agree=agree, total=len(cases), alpha=ALPHA, tau=TAU, theta=THETA)


def main():
    res = run()
    print("== 1. SHACL validation (DIPS validator)")
    for f, r in res["validation"].items():
        print(f"  {f}: valid_ODRL={r['valid_ODRL']}  errors={r['errors']}  warnings={r['warnings']}")
    print(f"\n== 2. Decision agreement: {res['agree']}/{res['total']} cases identical")
    for c in [c for c in res["cases"] if c["oval"] != c["simulator"]][:15]:
        print("  MISMATCH", c)


if __name__ == "__main__":
    main()
