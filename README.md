# CEGF-iFogSim

**Evaluating a Cloud-Edge Governance Framework (CEGF) on iFogSim2.**
CEGF regulates *what to do* in cloud-edge service provisioning with [ODRL](https://www.w3.org/TR/odrl-model/) policies, for two concerns: **data flow** (which data is worth sending, over which protocol) and **job distribution** (which node may receive a job). This repository extends [iFogSim2](https://github.com/Cloudslab/iFogSim) with a governed precision-farming scenario and the experiments that evaluate it. It accompanies the CEGF paper (in preparation).

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

## Headline results (iFogSim2, 20 seeds)

* Zero policy violations at every load; the strongest baseline (greedy placement) violates the policy on 3-20% of jobs.
* Uplink traffic −57% vs all-HTTPS and −34% vs ungoverned, with 98.8% of useful data on time (synthetic workload).
* A policy change at run time costs 1.1% critical misses, against 6.7% for a policy needing a (assumed) 30 s redeploy.
* **Cost:** at the highest load CEGF misses more critical deadlines than greedy (16.3% vs 2.6%).
* **On real greenhouse data** the entropy filter keeps only 49% of useful readings at θ = 0.3 (synthetic data suggested 98.8%), so θ needs calibration.

## Repository layout

| Path | Contents |
|---|---|
| `src/org/fog/` | iFogSim2 (upstream) |
| `src/org/fog/cegf/` | The CEGF port: `GovernedSensor` (entropy policy, protocol model, trace replay), `GovernedFogDevice` (job-recipient policy and baselines), `OdrlEval` (ODRL evaluator), `FarmExperiment` (entry point), `OdrlCheck` |
| `experiments/ifogsim/` | Build script, experiment driver `run_ifogsim.py`, figures (`make_figures.py`) and results |
| `experiments/traces/` | Real-data trace pipeline (Autonomous Greenhouse Challenge 2019, CC0): download, build, replay. See its README |
| `experiments/odrl_engine/` | Valid ODRL (Turtle) versions of the policies and a cross-check against the independent [OVAL evaluator](https://github.com/DIPS-Tools/ODRL-Engine) |
| `experiments/farm/` | A standalone Python cross-check simulator, results and the paper section `precision_farming_experiments.tex` |
| `experiments/CEGF_precision_farming_results.pptx` | Results presentation |
| `dataset/greenhouse_challenge_2019/` | Downloaded data (git-ignored) and the derived `trace/` |
| `jars/` | Libraries |

## Getting started

Requirements: JDK 21 (older versions may work), Python 3.12 with `numpy pandas matplotlib`; for the optional steps `py7zr rdflib pyshacl requests python-dateutil jinja2`. Run everything from the repository root (Windows PowerShell shown).

```powershell
# 1. Build iFogSim2 + the CEGF code into experiments/ifogsim/build
powershell -File experiments/ifogsim/build.ps1

# 2. One simulation (one JVM per run). Data flow, governed, synthetic workload:
java -cp "jars/*;jars/commons-math3-3.5/*;experiments/ifogsim/build" org.fog.cegf.FarmExperiment scenario=data mode=CEGF seed=1
#    Job distribution: scenario=jobs policy=cegf|greedy|random|static|cloud load=0.9

# 3. All experiments (about 1,500 runs, 15-30 min) and the figures
python experiments/ifogsim/run_ifogsim.py
python experiments/ifogsim/make_figures.py
```

`FarmExperiment` options: `scenario` (data|jobs), `mode` (UG|SS|CEGF), `policy`, `seed`, `theta`, `alpha`, `tau`, `load`, `cam`, `trace`, and `change_t`/`alpha2`/`tau2`/`outage_s` for the policy-change test. It prints one `RESULT k=v,...` line.

**Real-data workload** (optional):

```powershell
python -P experiments/traces/fetch_greenhouse.py      # download dataset (8.4 MB, CC0)
python -P experiments/traces/build_trace.py           # build trace.csv
# then add trace=dataset/greenhouse_challenge_2019/trace/trace.csv to a FarmExperiment run
```

**Check the policies against an independent ODRL evaluator** (optional):

```powershell
python -P experiments/odrl_engine/fetch_oval.py
python -I experiments/odrl_engine/crosscheck_oval.py  # validates the policies and compares 147 decisions
```

## Limitations

Workloads, trust and availability values, loss rates and the 30 s redeploy outage are assumptions, not measurements. The iFogSim2 port has one cloud node, no edge failures and does not use iFogSim2's mobility or microservice features. Camera frames are synthetic. Data flows DF4 and DF5 are described in the scenario but have no policies yet. This fork removed the upstream mobility datasets, topology files and result spreadsheets; the legacy mobility examples that read them need those files restored from the git history.

## About iFogSim2

iFogSim2 is a toolkit for modeling and simulating resource management in IoT, edge and fog computing, with mobility support and migration management, microservice orchestration and dynamic distributed clustering, compatible with [CloudSim](https://github.com/Cloudslab/cloudsim/releases) and the [previous iFogSim](https://github.com/Cloudslab/iFogSim1). Upstream: https://github.com/Cloudslab/iFogSim. To run the upstream examples, open the project in Eclipse or IntelliJ IDEA, add the JARs from `jars/`, and run e.g. `TranslationServiceFog_Clustering.java`.

## License

MIT, see `LICENSE.txt` (Copyright (c) 2025 CLOUDS Laboratory, as inherited from iFogSim2).

## References

 * Redowan Mahmud, Samodha Pallewatta, Mohammad Goudarzi, and Rajkumar Buyya, [iFogSim2: An Extended iFogSim Simulator for Mobility, Clustering, and Microservice Management in Edge and Fog Computing Environments](https://arxiv.org/abs/2109.05636), Journal of Systems and Software (JSS), Volume 190, Pages: 1-17, ISSN:0164-1212, Elsevier Press, Amsterdam, The Netherlands, August 2022.
 * Harshit Gupta, Amir Vahid Dastjerdi, Soumya K. Ghosh, and Rajkumar Buyya, [iFogSim: A Toolkit for Modeling and Simulation of Resource Management Techniques in Internet of Things, Edge and Fog Computing Environments](http://www.buyya.com/papers/iFogSim.pdf), Software: Practice and Experience (SPE), Volume 47, Issue 9, Pages: 1275-1296, ISSN: 0038-0644, Wiley Press, New York, USA, September 2017.
 * Redowan Mahmud and Rajkumar Buyya, [Modelling and Simulation of Fog and Edge Computing Environments using iFogSim Toolkit](http://www.buyya.com/papers/iFogSim-Tut.pdf), Fog and Edge Computing: Principles and Paradigms, R. Buyya and S. Srirama (eds), 433-466pp, ISBN: 978-111-95-2498-4, Wiley Press, New York, USA, January 2019.
 * Greenhouse data: Hemming et al., Autonomous Greenhouse Challenge, Second Edition (2019), 4TU.ResearchData, [doi:10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7](https://doi.org/10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7), CC0.
