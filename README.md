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


## How to run

**Requirements:** JDK 21, Python 3.12, git, and `pip install numpy pandas matplotlib py7zr rdflib pyshacl requests python-dateutil jinja2`. Run everything from the repository root.

**Full pipeline (one command, about 30 minutes with 20 seeds):**

```
python experiments/run_pipeline.py
```

It compiles the code, downloads the real greenhouse data (8 MB, CC0) and builds the workload trace, validates the ODRL policies against OVAL (fetch it once with `python -P experiments/odrl_engine/fetch_oval.py`), runs the iFogSim2 experiments, and writes figures, tables and `results/RUN_SUMMARY.md` to `results/`.

Useful options: `--stages workload,policies,simulation,figures,summary` (run only some stages), `--seeds 3` (quick test), `--parts e1,e2,e3` (re-run only some experiments), `--paper-figures DIR` (title-free figures for a paper).

**A single simulation** (after the pipeline has compiled the code):

```
java -cp "jars/*;jars/commons-math3-3.5/*;experiments/ifogsim/build" org.fog.cegf.FarmExperiment scenario=jobs policy=cegf load=0.9 seed=1
```

Options: `scenario=data|jobs`, `mode=UG|SS|CEGF` and `trace=<trace.csv>` (data flow), `policy=cegf|greedy|random|static|cloud` and `load=` (jobs), `theta`, `alpha`, `tau`, `cam`, `seed`. It prints one `RESULT` line.


## ODRL policy validation (OVAL)

The two policies are also written as standard ODRL in Turtle (`experiments/odrl_engine/job_recipient_policy.ttl`, `entropy_policy.ttl`) and checked against an independent evaluator, the [OVAL evaluator of the ODRL Engine](https://github.com/DIPS-Tools/ODRL-Engine) (DIPS, University of Southampton, MIT licence):

* **SHACL validation:** both policies are valid ODRL, with no errors or warnings.
* **Decision cross-check:** OVAL and the simulator's own evaluator (`OdrlEval`) give identical decisions on 451 test cases, including boundary values.

```
python -P experiments/odrl_engine/fetch_oval.py          # fetch OVAL at a pinned commit (git-ignored vendor/ folder)
python -I experiments/odrl_engine/crosscheck_oval.py     # needs: pip install rdflib pyshacl requests python-dateutil pandas jinja2
```

OVAL runs outside the simulation (about 71 ms per decision), so it serves as an offline validator and conformance oracle, not as the in-simulation evaluator.


## About iFogSim2

iFogSim2 is a toolkit for modeling and simulating resource management in IoT, edge and fog computing, with mobility support and migration management, microservice orchestration and dynamic distributed clustering, compatible with [CloudSim](https://github.com/Cloudslab/cloudsim/releases) and the [previous iFogSim](https://github.com/Cloudslab/iFogSim1). Upstream: https://github.com/Cloudslab/iFogSim. To run the upstream examples, open the project in Eclipse or IntelliJ IDEA, add the JARs from `jars/`, and run e.g. `TranslationServiceFog_Clustering.java`.