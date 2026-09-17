#!/usr/bin/env python3
"""Driver for fault_tolerance.py: discover the current fire.py-build-PASS
population of the Python-3.14.6 stdlib corpus, run each file through the
two-version (CPython vs mojo) fault-tolerance check, and write a summary
report (JSON + markdown) alongside the per-file artifacts that
fault_tolerance.py already persists under artifacts/fault_tolerance/.

Two phases:

  1. Discovery — which files currently PASS `fire.py build` at all. This is
     the natural starting population (a file mojo can't even compile isn't a
     candidate for a *runtime* behavior comparison). We don't trust any
     stale bugs/PY314_FULL_SCAN_SUMMARY.json list on disk (it only records
     counts, not filenames, and several compiler fixes have landed since any
     full scan last ran) — we re-derive it here via py314_harness.run_build,
     which is itself cached (py314_cache.py, keyed by compiler fingerprint +
     file content) so re-running this driver after an unrelated compiler
     change only re-pays the cost for files whose build outcome could have
     changed.

  2. Fault-tolerance run — for a sample of that PASS population (bounded by
     --sample), actually run both CPython and mojo and compare, via
     fault_tolerance.run_fault_tolerant().

Safety: discovery only ever *compiles* (fire.py build), never executes.
Only phase 2 executes code, and only after fault_tolerance.is_unsafe() has
had a chance to veto a candidate; phase 2 also runs each side in its own
throwaway scratch cwd/HOME with a timeout (see fault_tolerance.py).
"""
import argparse
import concurrent.futures
import json
import os
import time

import fault_tolerance
import py314_cache
from py314_harness import run_build
from test_py314_full import ROOT, EXCLUDE_DIR_NAMES, safe_name_for

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_JSON = os.path.join(HERE, "artifacts", "ft_summary.json")
REPORT_MD = os.path.join(HERE, "artifacts", "ft_summary.md")

# Discovery walks Lib/ only (the real library modules) and skips the same
# unsafe-ish trees fault_tolerance.py would refuse to execute anyway, so we
# don't waste build attempts on candidates phase 2 will just skip.
LIB_ROOT = os.path.join(ROOT, "Lib")
DISCOVERY_SKIP_DIRS = EXCLUDE_DIR_NAMES | {
    "test", "tests", "idle_test", "idlelib", "turtledemo", "ensurepip",
}


def find_candidates(max_candidates):
    files = []
    for dirpath, dirnames, filenames in os.walk(LIB_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in DISCOVERY_SKIP_DIRS)
        for fn in sorted(filenames):
            if fn.endswith(".py") and not fn.startswith("test_"):
                files.append(os.path.join(dirpath, fn))
    files.sort()
    if max_candidates:
        files = files[:max_candidates]
    return files


def discover_pass_population(max_candidates, workers, build_timeout):
    candidates = find_candidates(max_candidates)
    print(f"[discovery] {len(candidates)} candidate files under {LIB_ROOT}", flush=True)
    pass_files = []
    t0 = time.time()
    done = 0

    def work(fp):
        cat, stderr, stdout, rc, elapsed, hit = run_build(fp, timeout=build_timeout)
        return fp, cat

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for fp, cat in ex.map(work, candidates):
            done += 1
            if cat == "PASS":
                pass_files.append(fp)
            if done % 50 == 0 or done == len(candidates):
                print(f"[discovery] {done}/{len(candidates)} checked, "
                      f"{len(pass_files)} PASS so far, {time.time()-t0:.0f}s elapsed", flush=True)
    py314_cache.save()
    return pass_files


def run_sample(pass_files, sample_size, ft_timeout, workers):
    sample = pass_files[:sample_size]
    print(f"[fault-tolerance] running {len(sample)} files "
          f"(of {len(pass_files)} discovered PASS)", flush=True)

    results = []

    def work(fp):
        safe_name = safe_name_for(fp)
        return fault_tolerance.run_fault_tolerant(fp, timeout=ft_timeout, safe_name=safe_name)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, fp): fp for fp in sample}
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            fp = futs[fut]
            done += 1
            try:
                r = fut.result()
            except Exception as e:
                r = fault_tolerance.FaultTolerantResult(
                    filepath=fp, verdict="ERROR", divergence=str(e),
                    trusted_output=None, mojo_output=None, artifacts_path=None,
                )
            results.append(r)
            if done % 10 == 0 or done == len(sample):
                print(f"[fault-tolerance] {done}/{len(sample)} done", flush=True)
    return results


def write_report(results, pass_population_size, candidates_checked):
    counts = {}
    fails = []
    skips = []
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
        if r.verdict == "FAIL":
            fails.append((os.path.relpath(r.filepath, ROOT), r.divergence, r.artifacts_path))
        elif r.verdict == "SKIPPED":
            skips.append((os.path.relpath(r.filepath, ROOT), r.divergence))

    os.makedirs(os.path.dirname(REPORT_JSON), exist_ok=True)
    summary = {
        "candidates_checked_for_build_pass": candidates_checked,
        "build_pass_population_discovered": pass_population_size,
        "fault_tolerance_sample_size": len(results),
        "counts": counts,
        "fails": [{"file": f, "divergence": d, "artifact": a} for f, d, a in fails],
        "skipped": [{"file": f, "reason": d} for f, d in skips],
    }
    with open(REPORT_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    lines = []
    lines.append("# Fault-tolerance run report\n")
    lines.append(f"Build-PASS population discovered: {pass_population_size} "
                 f"(out of {candidates_checked} candidates checked)\n")
    lines.append(f"Fault-tolerance sample size: {len(results)}\n")
    lines.append("## Verdict counts\n")
    for k, v in sorted(counts.items()):
        lines.append(f"- {k}: {v}\n")
    lines.append("\n## FAIL files\n")
    if not fails:
        lines.append("(none)\n")
    for f, d, a in fails:
        lines.append(f"- `{f}` — {d}  (artifact: `{os.path.relpath(a, HERE) if a else '?'}`)\n")
    lines.append("\n## SKIPPED files\n")
    if not skips:
        lines.append("(none)\n")
    for f, d in skips:
        lines.append(f"- `{f}` — {d}\n")

    with open(REPORT_MD, "w") as f:
        f.writelines(lines)

    print("\n" + "".join(lines))
    print(f"\nJSON summary: {REPORT_JSON}")
    print(f"Markdown summary: {REPORT_MD}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=int, default=200,
                    help="how many Lib/ files to check for build-PASS during discovery")
    ap.add_argument("--sample", type=int, default=40,
                    help="how many of the discovered build-PASS files to actually run+compare")
    ap.add_argument("--discovery-workers", type=int, default=6)
    ap.add_argument("--ft-workers", type=int, default=4)
    ap.add_argument("--build-timeout", type=int, default=60)
    ap.add_argument("--ft-timeout", type=int, default=20)
    ap.add_argument("--pass-list", default=None,
                    help="skip discovery; load a JSON list of file paths instead")
    args = ap.parse_args()

    if args.pass_list:
        with open(args.pass_list) as f:
            pass_files = json.load(f)
        candidates_checked = len(pass_files)
    else:
        pass_files = discover_pass_population(args.candidates, args.discovery_workers,
                                               args.build_timeout)
        candidates_checked = args.candidates

    results = run_sample(pass_files, args.sample, args.ft_timeout, args.ft_workers)
    write_report(results, len(pass_files), candidates_checked)


if __name__ == "__main__":
    main()
