#!/usr/bin/env python3
"""Run all stdlib benchmarks and test code through mojo.py --jit and run.

Usage:
  python3 run_stdlib_tests.py                          # run all benchmarks + tests
  python3 run_stdlib_tests.py --mode jit               # JIT only
  python3 run_stdlib_tests.py --mode run               # interpreter only
  python3 run_stdlib_tests.py --mode both              # both (default)
  python3 run_stdlib_tests.py --scope benchmarks        # benchmarks only
  python3 run_stdlib_tests.py --scope tests             # tests only
  python3 run_stdlib_tests.py --scope both              # both (default)
  python3 run_stdlib_tests.py --failed                  # re-run only files that previously failed
"""

import os
import sys
import subprocess
import argparse
import json
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = Path(__file__).parent.resolve()
MOJO_PY = HERE / "mojo.py"
RESULTS_FILE = HERE / ".stdlib_test_results.json"

from module_loader import STDLIB_PATH

STDLIB_ROOT = Path(STDLIB_PATH).resolve()
BENCHMARKS_DIR = STDLIB_ROOT / "benchmarks"
TEST_DIR = STDLIB_ROOT / "test"


def find_mojo_files(root):
    """Recursively find all .mojo files under root."""
    for f in sorted(root.rglob("*.mojo")):
        yield f


def skip_file(path):
    """Skip compile-fail, data, and other non-runnable files."""
    name = path.name
    rel = path.relative_to(STDLIB_ROOT)
    # Skip compile_fail directories entirely
    if "compile_fail" in rel.parts:
        return True
    # Skip data/include files
    if name.startswith("_"):
        return True
    if name.startswith("."):
        return True
    # Skip test_utils / helpers without main
    if "test_utils" in rel.parts and name != "test_utils.mojo":
        return True
    if name == "__init__.mojo":
        return True
    # Skip the python benchmark binding module (no main)
    if "python" in rel.parts and "bench_bindings" in rel.parts:
        return True
    return False


def run_with_mojo(mojo_file, mode, timeout=60):
    """Run a mojo file with the given mode ('jit' or 'run') and return results."""
    rel = mojo_file.relative_to(STDLIB_ROOT)
    short_name = str(rel)

    env = os.environ.copy()
    env["MOJO_STDLIB"] = str(STDLIB_ROOT)
    env["PYTHONPATH"] = str(HERE)

    if mode == "jit":
        cmd = [sys.executable, str(MOJO_PY), "--jit", str(mojo_file)]
    else:
        cmd = [sys.executable, str(MOJO_PY), "run", str(mojo_file)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(HERE),
        )
        rc = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
        if rc == 0:
            return {"file": short_name, "mode": mode, "status": "pass", "rc": rc}
        else:
            err = stderr[:500] if stderr else stdout[:500]
            return {
                "file": short_name,
                "mode": mode,
                "status": "fail",
                "rc": rc,
                "error": err,
                "stdout": stdout[:200],
                "stderr": stderr[:200],
            }
    except subprocess.TimeoutExpired:
        return {"file": short_name, "mode": mode, "status": "timeout", "error": "timeout > {}s".format(timeout)}
    except Exception as e:
        return {"file": short_name, "mode": mode, "status": "error", "error": str(e)[:200]}


def print_result(result, verbose=False):
    """Print a single test result."""
    status = result["status"]
    mode = result["mode"]
    f = result["file"]
    if status == "pass":
        print(f"  PASS  [{mode}] {f}")
    elif status == "timeout":
        print(f"  TIME  [{mode}] {f}")
        if verbose:
            print(f"         {result.get('error', '')}")
    else:
        print(f"  FAIL  [{mode}] {f}")
        if verbose:
            err = result.get("error", "")
            if err:
                for line in err.splitlines()[:3]:
                    print(f"         {line}")


def load_previous_results():
    """Load previous test results from JSON file."""
    if RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_results(results):
    """Save test results to JSON file."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "results": results,
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Run stdlib benchmarks and tests")
    parser.add_argument("--mode", choices=["jit", "run", "both"], default="both",
                        help="Execution mode(s) to test")
    parser.add_argument("--scope", choices=["benchmarks", "tests", "both"], default="both",
                        help="Which files to run")
    parser.add_argument("--failed", action="store_true",
                        help="Re-run only files that failed in the last run")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show error details for failures")
    parser.add_argument("--jobs", "-j", type=int, default=20,
                        help="Parallel workers (default: 20)")
    parser.add_argument("--timeout", type=int, default=60,
                        help="Per-file timeout in seconds (default: 60)")
    args = parser.parse_args()

    if not MOJO_PY.exists():
        print("ERROR: mojo.py not found at", MOJO_PY)
        sys.exit(1)

    # Collect files
    files_to_run = []
    if args.scope in ("benchmarks", "both"):
        for f in find_mojo_files(BENCHMARKS_DIR):
            if not skip_file(f):
                files_to_run.append(f)
    if args.scope in ("tests", "both"):
        for f in find_mojo_files(TEST_DIR):
            if not skip_file(f):
                files_to_run.append(f)

    print(f"Found {len(files_to_run)} runnable Mojo files")

    # Filter to previously failed if --failed
    if args.failed:
        prev = load_previous_results()
        prev_failed = {r["file"] for r in prev.get("results", []) if r["status"] != "pass"}
        if not prev_failed:
            print("No previously failed files to re-run")
            return
        files_to_run = [f for f in files_to_run if str(f.relative_to(STDLIB_ROOT)) in prev_failed]
        print(f"Re-running {len(files_to_run)} previously failed files")

    # Determine modes
    modes = []
    if args.mode in ("jit", "both"):
        modes.append("jit")
    if args.mode in ("run", "both"):
        modes.append("run")

    print(f"Modes: {', '.join(modes)}")
    print(f"Workers: {args.jobs}")
    print()

    all_results = []
    stats = {"pass": 0, "fail": 0, "timeout": 0, "error": 0}

    # Generate all (file, mode) pairs
    work_items = [(f, mode) for f in files_to_run for mode in modes]

    print(f"Total work items: {len(work_items)}")
    print()

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_with_mojo, f, mode, args.timeout): (f, mode)
                   for f, mode in work_items}

        for future in as_completed(futures):
            result = future.result()
            all_results.append(result)
            stats[result["status"]] += 1
            print_result(result, verbose=args.verbose)

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    total = len(all_results)
    print(f"  Total:  {total}")
    print(f"  Pass:   {stats['pass']}")
    print(f"  Fail:   {stats['fail']}")
    print(f"  Timeout:{stats['timeout']}")
    print(f"  Error:  {stats['error']}")
    print()

    # Save results
    save_results(all_results)

    # List all failures
    failures = [r for r in all_results if r["status"] != "pass"]
    if failures:
        print("-" * 70)
        print("FAILURES")
        print("-" * 70)
        for r in failures:
            print(f"  [{r['mode']}] {r['file']}")
            if r["status"] == "timeout":
                print(f"         Timeout")
            elif r.get("error"):
                for line in r["error"].splitlines()[:5]:
                    print(f"         {line}")
            print()

    # Save failure list to file
    if failures:
        fail_file = HERE / ".stdlib_test_failures.txt"
        with open(fail_file, "w") as f:
            for r in failures:
                f.write(f"[{r['mode']}] {r['file']}\n")
                if r.get("error"):
                    f.write(f"  {r['error']}\n")
        print(f"Failure list saved to {fail_file}")

    sys.exit(0 if stats["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
