#!/usr/bin/env python3
"""Run the modular Mojo test suite against our compiler (fire.py).

Usage:
    python3 tools/run_modular_suite.py [--timeout 600] [--filter PATTERN]

Writes per-test results to build/modular_suite_results.txt and a summary.
Each test gets its own 10-minute (default) timeout.
"""
import argparse, os, subprocess, sys, time

FIRE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULAR = "/Users/mrs/net/chatgpt/claude/modular"
RESULTS = os.path.join(FIRE, "build", "modular_suite_results.txt")
LOG = os.path.join(FIRE, "build", "modular_suite.log")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=600)
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
    print(f"Running {len(files)} tests, timeout={args.timeout}s each", flush=True)

    results = []
    t0 = time.time()
    with open(LOG, "w") as logf:
        for i, f in enumerate(files):
            try:
                r = subprocess.run(
                    ["python3", "fire.py", "build", f],
                    cwd=FIRE, capture_output=True, text=True, timeout=args.timeout)
                ok = r.returncode == 0
                err = (r.stderr or r.stdout or "").strip()
            except subprocess.TimeoutExpired:
                ok = False
                err = "TIMEOUT"
            status = "OK" if ok else "FAIL"
            results.append((status, f, err))
            line = f"[{i+1}/{len(files)}] {status}: {os.path.basename(f)}"
            print(line, flush=True)
            logf.write(line + "\n")
            if not ok:
                # first error line
                el = ""
                for l in err.splitlines():
                    if l.strip():
                        el = l.strip()[:150]
                        break
                if el:
                    print(f"    {el}", flush=True)
                    logf.write(f"    {el}\n")
            # incremental results
            with open(RESULTS, "w") as fh:
                for s, p, e in results:
                    fh.write(f"{s}\t{p}\n")
            logf.flush()

    fails = [r for r in results if r[0] == "FAIL"]
    summary = f"\nDone in {time.time()-t0:.0f}s: {len(results)-len(fails)}/{len(results)} passed, {len(fails)} failed.\n"
    print(summary, flush=True)
    logf.write(summary)
    # write failure detail
    detail = os.path.join(FIRE, "build", "modular_suite_failures.txt")
    with open(detail, "w") as fh:
        for s, p, e in results:
            if s == "FAIL":
                fh.write(f"FILE: {p}\n{e}\n===\n")
    print(f"Failures detail: {detail}")

if __name__ == "__main__":
    main()
EOF