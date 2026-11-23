"""Fetch the OVAL evaluator (DIPS-Tools/ODRL-Engine, MIT licence) at a pinned commit into experiments/odrl_engine/vendor/.

The folder is git-ignored. Requirements: git, and `pip install rdflib pyshacl requests python-dateutil pandas jinja2`.
Run:  python -P experiments/odrl_engine/fetch_oval.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, "vendor", "ODRL-Engine")
URL = "https://github.com/DIPS-Tools/ODRL-Engine.git"
COMMIT = "35bcb56"          # 2026-11-17, "fixed mistake in test, and made test routine more resilient"


def run(*cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True)


if os.path.isdir(os.path.join(DEST, ".git")):
    print("already present:", DEST)
    sys.exit(0)
os.makedirs(os.path.dirname(DEST), exist_ok=True)
run("git", "clone", URL, DEST)
run("git", "checkout", "--quiet", COMMIT, cwd=DEST)
print("fetched OVAL at", COMMIT, "->", DEST)
