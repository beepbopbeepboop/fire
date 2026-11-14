#!/usr/bin/env python3
"""For each CHECKFAIL case, capture our compiler output and the expected CHECK
lines, writing a JSON candidate file for canonicalization review."""
import json, os, subprocess, sys, time

FIRE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(FIRE, "build", "modular_suite_results.txt")
OUT = os.path.join(FIRE, "build", "checkfail_candidates.json")
TIMEOUT = 300

cases = []
with open(RESULTS) as fh:
    for line in fh:
        parts = line.strip().split("\t")
        if len(parts) >= 2 and parts[0] == "CHECKFAIL":
            cases.append(parts[1])

print(f"Processing {len(cases)} CHECKFAIL cases")

out = []
for i, f in enumerate(cases):
    checks = []
    try:
        with open(f) as fh:
            for line in fh:
                import re
                m = re.match(r"\s*(?://|#)\s*CHECK(?:-NEXT|-NOT|-SAME)?:\s*(.*)", line)
                if m:
                    checks.append(m.group(1).strip())
    except Exception:
        pass
    try:
        r = subprocess.run(["python3", "fire.py", "build", f], cwd=FIRE,
                           capture_output=True, text=True, timeout=TIMEOUT)
        our_out = (r.stdout or "") + "\n" + (r.stderr or "")
        rc = r.returncode
    except subprocess.TimeoutExpired:
        our_out = "TIMEOUT"
        rc = -1
    out.append({"file": f, "rc": rc, "checks": checks, "our_output": our_out[:4000]})
    print(f"[{i+1}/{len(cases)}] {os.path.basename(f)}")

with open(OUT, "w") as fh:
    json.dump(out, fh, indent=1)
print(f"Written {OUT}")
