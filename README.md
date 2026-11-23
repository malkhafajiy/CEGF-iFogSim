# CEGF-iFogSim

**Evaluating a Cloud-Edge Governance Framework (CEGF) on iFogSim2.**
CEGF regulates *what to do* in cloud-edge service provisioning with [ODRL](https://www.w3.org/TR/odrl-model/) policies, for two concerns: **data flow** (which data is worth sending, over which protocol) and **job distribution** (which node may receive a job). This repository extends [iFogSim2](https://github.com/Cloudslab/iFogSim) with a governed precision-farming scenario and the experiments that evaluate it. 


## What is evaluated

A smart greenhouse: 40 soil sensors and 12 cameras (data layer), three edge gateways of different trust, and one cloud node behind a shared 2 Mbit/s uplink. Four job types (irrigation, disease detection, fertigation planning, archiving) carry two labels, *critical* and *confidential*.

| Policy | Rule |
|---|---|
| Data selection | A reading is sent only if its entropy is at least θ |
| Job recipient | A critical job needs a recipient with availability at least α; a confidential job needs trust at least τ; prohibitions win over permissions |

| Experiment | Question |
|---|---|
| E1 Data flow | Does governed selection and protocol choice keep useful data on time while cutting traffic? |
| E2 Job distribution | Does the recipient policy keep placements compliant at what cost in deadlines? |
| E3 Flexibility | What does a policy change at run time cost, compared with a redeploy? |

Baselines: ungoverned, all-HTTPS (E1); random, cloud-only, static, greedy (E2).


## ODRL policy validation (OVAL)

The two policies are also written as standard ODRL in Turtle (`experiments/odrl_engine/job_recipient_policy.ttl`, `entropy_policy.ttl`) and checked against an independent evaluator, the [OVAL evaluator of the ODRL Engine](https://github.com/DIPS-Tools/ODRL-Engine) (DIPS, University of Southampton, MIT licence):

* **SHACL validation:** both policies are valid ODRL, with no errors or warnings.
* **Decision cross-check:** OVAL and the simulator's own evaluator (`OdrlEval`) give identical decisions on 147 test cases, including boundary values.

```
python -P experiments/odrl_engine/fetch_oval.py          # fetch OVAL at a pinned commit (git-ignored vendor/ folder)
python -I experiments/odrl_engine/crosscheck_oval.py     # needs: pip install rdflib pyshacl requests python-dateutil pandas jinja2
```

OVAL runs outside the simulation (about 71 ms per decision), so it serves as an offline validator and conformance oracle, not as the in-simulation evaluator.


## About iFogSim2

iFogSim2 is a toolkit for modeling and simulating resource management in IoT, edge and fog computing, with mobility support and migration management, microservice orchestration and dynamic distributed clustering, compatible with [CloudSim](https://github.com/Cloudslab/cloudsim/releases) and the [previous iFogSim](https://github.com/Cloudslab/iFogSim1). Upstream: https://github.com/Cloudslab/iFogSim. To run the upstream examples, open the project in Eclipse or IntelliJ IDEA, add the JARs from `jars/`, and run e.g. `TranslationServiceFog_Clustering.java`.