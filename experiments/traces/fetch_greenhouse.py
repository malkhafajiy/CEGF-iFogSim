"""Download and extract the Autonomous Greenhouse Challenge, 2nd edition (2019) dataset.

Source : 4TU.ResearchData, DOI 10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7 (licence CC0)
Target : dataset/greenhouse_challenge_2019/raw/  (git-ignored; re-created by this script)
Needs  : pip install py7zr
Run from the repo root, away from the data:  python -P experiments/traces/fetch_greenhouse.py
"""
import hashlib
import json
import os
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(ROOT, "dataset", "greenhouse_challenge_2019", "raw")
API = "https://data.4tu.nl/v2/articles/12764777/versions/2"


def main():
    os.makedirs(RAW, exist_ok=True)
    meta = json.load(urllib.request.urlopen(API, timeout=60))
    f = meta["files"][0]
    dest = os.path.join(RAW, f["name"])
    if not os.path.exists(dest):
        print(f"downloading {f['name']} ({f['size'] / 1e6:.1f} MB) ...")
        urllib.request.urlretrieve(f["download_url"], dest)
    md5 = hashlib.md5(open(dest, "rb").read()).hexdigest()
    if md5 != f["computed_md5"]:
        sys.exit(f"MD5 mismatch: {md5} != {f['computed_md5']}")
    print("MD5 ok", md5)
    out = os.path.join(RAW, "extracted")
    if not os.path.isdir(out):
        import py7zr
        with py7zr.SevenZipFile(dest) as z:
            z.extractall(out)
    n = sum(len(fs) for _, _, fs in os.walk(out))
    print(f"extracted {n} files to {out}")


if __name__ == "__main__":
    main()
