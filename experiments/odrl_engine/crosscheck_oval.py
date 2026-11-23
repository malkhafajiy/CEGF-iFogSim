"""Cross-check the simulator's ODRL evaluator (Java OdrlEval) against the independent OVAL evaluator.

1. Validates job_recipient_policy.ttl and entropy_policy.ttl with the DIPS SHACL validator.
2. Evaluates a grid of test cases (incl. boundary values) with both evaluators and compares the decisions.

Setup : python -P experiments/odrl_engine/fetch_oval.py ; powershell experiments/ifogsim/build.ps1
Run   : python -I experiments/odrl_engine/crosscheck_oval.py        (from the repo root)
"""
import itertools
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OVAL = os.environ.get("ODRL_ENGINE_PATH", os.path.join(HERE, "vendor", "ODRL-Engine"))
sys.path.insert(0, os.path.join(ROOT, "experiments", "ifogsim"))
import glob  # noqa: E402

JAVA = (glob.glob(r"C:\Program Files\Microsoft\jdk-*\bin\java.exe") or ["java"])[0]
CP = os.pathsep.join(glob.glob(os.path.join(ROOT, "jars", "**", "*.jar"), recursive=True) + [os.path.join(ROOT, "experiments", "ifogsim", "build")])
POLICIES = os.path.join(ROOT, "experiments", "farm", "results", "policies.json")
ALPHA, TAU, THETA = 0.25, 0.7, 0.3            # must equal the constants in the .ttl files
C = "https://example.org/cegf#"
ODRL = "http://www.w3.org/ns/odrl/2/"


def recipient_cases():
    return list(itertools.product([True, False], [True, False], [0.0, 0.1, 0.24, 0.25, 0.26, 0.5, 1.0], [0.3, 0.69, 0.7, 0.71, 0.95]))


def entropy_cases():
    return [0.0, 0.1, 0.29, 0.3, 0.31, 0.5, 1.0]


def java_decisions(recip, ent):
    lines = [f"R {str(c).lower()} {str(f).lower()} {a} {t}" for c, f, a, t in recip] + [f"E {h}" for h in ent]
    p = subprocess.run([JAVA, "-cp", CP, "org.fog.cegf.OdrlCheck", POLICIES, str(ALPHA), str(TAU), str(THETA)],
                       input="\n".join(lines), capture_output=True, text=True, cwd=ROOT)
    if p.returncode:
        sys.exit(p.stderr[-800:])
    return [x.strip() == "true" for x in p.stdout.split("\n") if x.strip()]


def main():
    if not os.path.isdir(OVAL):
        sys.exit("OVAL not found: run experiments/odrl_engine/fetch_oval.py first (or set ODRL_ENGINE_PATH)")
    os.chdir(OVAL)                                   # OVAL loads its ODRL/SHACL resources relative to its own folder
    sys.path.insert(0, OVAL)
    import ODRL_Evaluator as E
    import validate

    print("== 1. SHACL validation (DIPS validator)")
    for f in ("job_recipient_policy.ttl", "entropy_policy.ttl"):
        r = validate.validate_ODRL_from_file(os.path.join(HERE, f))
        print(f"  {f}: valid_ODRL={r['is_valid_ODRL']}  errors={len(r['errors'])}  warnings={len(r['warnings'])}")

    recip, ent = recipient_cases(), entropy_cases()
    jd = java_decisions(recip, ent)
    pol_r = open(os.path.join(HERE, "job_recipient_policy.ttl")).read() + "\ncegf:job1 odrl:partOf cegf:jobs .\n"
    pol_e = open(os.path.join(HERE, "entropy_policy.ttl")).read()
    bad = []
    for i, (c, f, a, t) in enumerate(recip):
        req = {ODRL + "Action": ODRL + "move", ODRL + "Asset": C + "job1", C + "critical": str(c).lower(),
               C + "confidential": str(f).lower(), C + "availability": str(a), C + "trust": str(t)}
        o = E.evaluate_ODRL_access_request_from_string(json.dumps(req), pol_r).get("accept_decision")
        if o != jd[i]:
            bad.append(("recipient", (c, f, a, t), "OVAL", o, "simulator", jd[i]))
    for j, h in enumerate(ent):
        req = {ODRL + "Action": ODRL + "select", ODRL + "Asset": C + "data", C + "entropy": str(h)}
        o = E.evaluate_ODRL_access_request_from_string(json.dumps(req), pol_e).get("accept_decision")
        if o != jd[len(recip) + j]:
            bad.append(("entropy", h, "OVAL", o, "simulator", jd[len(recip) + j]))
    n = len(recip) + len(ent)
    print(f"\n== 2. Decision agreement: {n - len(bad)}/{n} cases identical "
          f"({len(recip)} recipient cases incl. boundary values, {len(ent)} entropy cases)")
    for b in bad[:15]:
        print("  MISMATCH", b)
    print("  allowed by simulator:", sum(jd), "of", n)


if __name__ == "__main__":
    main()
