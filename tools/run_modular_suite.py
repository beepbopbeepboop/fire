#!/usr/bin/env python3
"""Run the modular Mojo test suite against our compiler (fire.py).

Usage:
    python3 tools/run_modular_suite.py [--timeout 600] [-j 16] [--filter PATTERN]

Runs up to -j tests in parallel (default 16). Each test gets its own --timeout
(default 10 min). Writes per-test results to build/modular_suite_results.txt
and a failure detail file.
"""
import argparse, os, subprocess, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

FIRE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULAR = "/Users/mrs/net/chatgpt/claude/modular"
RESULTS = os.path.join(FIRE, "build", "modular_suite_results.txt")
LOG = os.path.join(FIRE, "build", "modular_suite.log")
DETAIL = os.path.join(FIRE, "build", "modular_suite_failures.txt")


def run_one(f, timeout):
    try:
        r = subprocess.run(
            ["python3", "fire.py", "build", f],
            cwd=FIRE, capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        err = (r.stderr or r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        ok = False
        err = "TIMEOUT"
    status = "OK" if ok else "FAIL"
    el = ""
    for l in err.splitlines():
        if l.strip():
            el = l.strip()[:150]
            break
    return status, f, el, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("-j", "--jobs", type=int, default=16)
    ap.add_argument("--filter", default=None)
    args = ap.parse_args()

    os.makedirs(os.path.join(FIRE, "build"), exist_ok=True)

    files = []
    for root, dirs, fs in os.walk(os.path.join(MODULAR, "mojo", "test")):
        for f in fs:
            if f.endswith(".mojo") and "inputs" not in root.lower():
                p = os.path.join(root, f)
                if args.filter and args.filter not in p:
                    continue
                files.append(p)
    files = sorted(set(files))
    print(f"Running {len(files)} tests, timeout={args.timeout}s, jobs={args.jobs}", flush=True)

    results = []
    lock = threading.Lock()
    t0 = time.time()
    with open(LOG, "w") as logf:
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            fut = {ex.submit(run_one, f, args.timeout): f for f in files}
            done = 0
            for future in as_completed(fut):
                status, f, el, err = future.result()
                with lock:
                    results.append((status, f, el, err))
                    done += 1
                    line = f"[{done}/{len(files)}] {status}: {os.path.basename(f)}"
                    print(line, flush=True)
                    logf.write(line + "\n")
                    if status == "FAIL" and el:
                        print(f"    {el}", flush=True)
                        logf.write(f"    {el}\n")
                    with open(RESULTS, "w") as fh:
                        for s, p, e, _ in results:
                            fh.write(f"{s}\t{p}\n")
                    logf.flush()

    fails = [r for r in results if r[0] == "FAIL"]
    summary = f"\nDone in {time.time()-t0:.0f}s: {len(results)-len(fails)}/{len(results)} passed, {len(fails)} failed.\n"
    print(summary, flush=True)
    with open(LOG, "a") as logf:
        logf.write(summary)
    with open(DETAIL, "w") as fh:
        for s, p, e, err in results:
            if s == "FAIL":
                fh.write(f"FILE: {p}\n{err}\n===\n")
    print(f"Failures detail: {DETAIL}")

if __name__ == "__main__":
    main()
EOF