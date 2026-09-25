#!/usr/bin/env python3
"""Sweep every *.py under the repo through `build --formal` (arm64 Mach-O).

Mojo is a Python superset, so .py files are valid inputs. Prints one
FAIL: line per failure; PASS lines are counted but not printed.
Summary (1-3 lines) at the end. Exit 1 if any FAIL.

Usage:
  python3 tools/formal_sweep.py [-j N] [paths...]
"""
import argparse
import concurrent.futures
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE = os.path.join(REPO, "fire.py")

SKIP_DIRS = {
    ".git", ".pixi", "output", "build", "__pycache__", ".mypy_cache",
    ".pytest_cache", "node_modules", "stdlib",  # external stdlib tree
}
DEFAULT_JOBS = max(4, min(os.cpu_count() or 8, 20))
TIMEOUT = 30


def find_py_files(roots):
    if roots:
        files = []
        for root in roots:
            root = os.path.abspath(root)
            if os.path.isfile(root) and root.endswith(".py"):
                files.append(root)
            elif os.path.isdir(root):
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [
                        d for d in dirnames
                        if d not in SKIP_DIRS and not d.startswith(".")
                    ]
                    for fn in filenames:
                        if fn.endswith(".py"):
                            files.append(os.path.join(dirpath, fn))
        return sorted(set(files))

    files = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(os.path.join(dirpath, fn))
    return sorted(files)


def rel(path):
    return os.path.relpath(path, REPO)


def run_one(path):
    """Return (ok, detail). detail empty on success."""
    try:
        # -o into a temp dir so we don't scatter .aout across the tree
        with tempfile.TemporaryDirectory(prefix="formal_sweep_") as td:
            out = os.path.join(td, "a.out")
            proc = subprocess.run(
                [sys.executable, FIRE, "build", "--formal", "-o", out, path],
                capture_output=True, text=True, timeout=TIMEOUT, cwd=REPO,
            )
        if proc.returncode == 0:
            return True, ""
        err = (proc.stderr or proc.stdout or "").strip()
        # keep the last non-empty line — that's the formal build's actual message
        lines = [ln for ln in err.splitlines() if ln.strip()]
        detail = lines[-1] if lines else f"exit {proc.returncode}"
        return False, detail
    except subprocess.TimeoutExpired:
        return False, f"timeout (> {TIMEOUT}s)"
    except Exception as e:
        return False, str(e)[:200]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-j", "--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"parallel workers (default {DEFAULT_JOBS})")
    ap.add_argument("paths", nargs="*",
                    help="files or dirs (default: all *.py under repo)")
    args = ap.parse_args()

    files = find_py_files(args.paths or None)
    if not files:
        print("no .py files found", file=sys.stderr)
        sys.exit(2)

    jobs = max(1, args.jobs)
    print(f"Sweeping {len(files)} .py files through build --formal "
          f"({jobs} workers)...", file=sys.stderr)

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(run_one, p): p for p in files}
        for fut in concurrent.futures.as_completed(futs):
            path = futs[fut]
            results[path] = fut.result()

    passed = failed = 0
    fails = []
    for path in files:  # deterministic order
        ok, detail = results[path]
        if ok:
            passed += 1
        else:
            failed += 1
            fails.append((rel(path), detail))

    # FAIL lines only (PASS counted, not printed)
    for r, detail in fails:
        print(f"FAIL: {r}  ({detail})")

    total = passed + failed
    pct = (100.0 * passed / total) if total else 0.0
    print(f"PASS={passed} FAIL={failed} total={total} ({pct:.1f}% pass)")
    if failed:
        print(f"first failure: {fails[0][0]}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
