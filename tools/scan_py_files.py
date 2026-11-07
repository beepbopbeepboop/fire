#!/usr/bin/env python3
"""Scan all .py files in the fire repo, compiling each with fire.py build."""
import os, subprocess, sys, time

FIRE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(FIRE, "build", "py_scan_results.txt")

files = []
for root, dirs, fs in os.walk(FIRE):
    # skip build dirs, stage dirs, .git, __pycache__
    dirs[:] = [d for d in dirs if d not in ("build","stage1","stage2",".git","__pycache__",".pytest_cache")]
    for f in fs:
        if f.endswith(".py"):
            files.append(os.path.join(root, f))

files = sorted(set(files))
print(f"total .py files: {len(files)}")

results = []
for i, f in enumerate(files):
    rel = os.path.relpath(f, FIRE)
    try:
        r = subprocess.run(["python3", "fire.py", "build", f], cwd=FIRE,
                           capture_output=True, text=True, timeout=300)
        ok = r.returncode == 0
        err = (r.stderr or r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        ok = False
        err = "TIMEOUT"
    status = "OK" if ok else "FAIL"
    results.append((status, f, err))
    el = ""
    for l in err.splitlines():
        if l.strip():
            el = l.strip()[:120]
            break
    print(f"[{i+1}/{len(files)}] {status}: {rel}  {el}")
    with open(OUT, "w") as fh:
        for s, p, e in results:
            fh.write(f"{s}\t{p}\t{e[:200]}\n")

fails = [r for r in results if r[0] == "FAIL"]
print(f"\nDone: {len(results)-len(fails)}/{len(results)} OK, {len(fails)} FAIL")
