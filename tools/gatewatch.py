#!/usr/bin/env python3
"""Peek at the integrator's gate: elapsed time, verdict, live processes, last suite output.

    gatewatch.py [TREE]        # default ../work-integ

A full `make gate` takes ~30 minutes. Reading: <=35 min on track, 35-60 slow
(check the processes), >60 stuck and needs help. Elapsed time comes from the
oldest `suite.py`/`make` process whose cwd is TREE, else from gate.log's mtime span.
"""
import os, re, subprocess, sys, time

tree = os.path.realpath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "work-integ"))
ps = subprocess.run(["ps", "-axo", "pid=,etime=,rss=,pcpu=,command="], capture_output=True, text=True).stdout


def secs(et):
    d, _, r = et.partition("-") if "-" in et else ("0", "", et)
    p = [int(x) for x in r.split(":")]
    while len(p) < 3: p.insert(0, 0)
    return int(d) * 86400 + p[0] * 3600 + p[1] * 60 + p[2]


def cwd(pid):
    r = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
    m = re.search(r"^n(.*)$", r, re.M)
    return os.path.realpath(m.group(1)) if m else ""


rows = []
for line in ps.splitlines():
    f = line.split(None, 4)
    if len(f) < 5 or "gatewatch" in f[4]: continue
    if re.search(r"suite\.py|make (gate|check)|mojoc|stage[123]|gcc|cc1|memcap|lean|python3", f[4]) and cwd(int(f[0])).startswith(tree):
        rows.append((int(f[0]), secs(f[1]), int(f[2]) / 1048576, float(f[3]), f[4][:110]))
if not rows:
    print("no gate processes under %s" % tree)
else:
    top = max(r[1] for r in rows)
    m = top / 60
    print("gate running %.0f min: %s" % (m, "on track" if m <= 35 else "SLOW, look at the jobs" if m <= 60 else "STUCK (>60 min) — needs help"))
    for pid, e, gb, cpu, cmd in sorted(rows, key=lambda r: -r[2])[:8]:
        print("  %6d %5.1fm %5.1fGB %5.1f%%  %s" % (pid, e / 60, gb, cpu, cmd))
gl = os.path.join(tree, "gate.log")
if os.path.exists(gl):
    prog = re.findall(r"\.\.\. (\d+)/(\d+) jobs done, (\d+) running, (\d+)s elapsed", open(gl, errors="replace").read())
    if prog:
        d, n, run, el = map(int, prog[-1])
        # progress in the last ~10 heartbeats (30 s each) tells slow-because-loaded from stuck
        d0 = int(prog[-10][0]) if len(prog) >= 10 else 0
        print("progress: %d/%d jobs, %d running, %ds elapsed; +%d jobs in the last ~5 min; load %s" % (
            d, n, run, el, d - d0, " ".join("%.0f" % x for x in os.getloadavg())))
for fn in ("build/suite.log", "gate.log"):
    p = os.path.join(tree, fn)
    if os.path.exists(p):
        age = time.time() - os.path.getmtime(p)
        print("--- %s (updated %.0fs ago)" % (fn, age))
        print("".join(open(p, errors="replace").readlines()[-6:]).rstrip())
