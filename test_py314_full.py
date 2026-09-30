#!/usr/bin/env python3
"""Comprehensive test of ~/net/Python-3.14.6's .py files against fire.py build.

Differences from test_py_stdlib.py / runner.py:
  - Scans the full Python-3.14.6 source tree (Lib/, Tools/, Doc/, PC/, etc.),
    not just a homebrew Lib/ copy limited to a 100-file sample.
  - Validates each file is syntactically valid Python (ast.parse) BEFORE
    running it through fire.py build. Test-suite fixtures that are
    *intentionally* invalid Python (e.g. Lib/test/badsyntax_*.py) are
    skipped and logged separately rather than filed as mojo bugs.
  - Dedups against bugs/ already on disk: if any category file already
    exists for a given relative path, no new bug report is written.
  - Caches every fire.py build outcome in py314_build_cache.json (keyed by
    compiler+toolchain fingerprint + file content, via py314_cache.py/cas.py)
    so re-running against an unchanged compiler is near-instant instead of
    repeating ~15 minutes of subprocess builds for files whose answer hasn't
    changed.
"""

import ast
import concurrent.futures
import json
import os
import sys
import threading
import time

import py314_cache
from py314_harness import run_build

HERE = os.path.dirname(os.path.abspath(__file__))
BUGS_DIR = os.path.join(HERE, "bugs")
ROOT = os.path.expanduser("~/net/Python-3.14.6")

EXCLUDE_DIR_NAMES = {".git", "__pycache__", "venv", ".venv"}

CATEGORIES = ["PASS", "LEX_FAIL", "PARSE_FAIL", "COMPILE_FAIL", "TIMEOUT", "ERROR"]

os.makedirs(BUGS_DIR, exist_ok=True)
write_lock = threading.Lock()


def find_py_files(root):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
        for f in filenames:
            if f.endswith(".py"):
                files.append(os.path.join(dirpath, f))
    files.sort()
    return files


def safe_name_for(filepath):
    rel = os.path.relpath(filepath, ROOT)
    if rel.startswith("Lib" + os.sep):
        rel = rel[len("Lib" + os.sep):]
    return rel.replace(os.sep, "_")[:-len(".py")]


def existing_bug_category(safe_name):
    for cat in CATEGORIES:
        if cat == "PASS":
            continue
        if os.path.exists(os.path.join(BUGS_DIR, f"{cat}_{safe_name}.md")):
            return cat
    return None


def check_valid_python(filepath):
    try:
        with open(filepath, "rb") as f:
            src = f.read()
    except OSError as e:
        return False, f"UNREADABLE: {e}"
    try:
        src.decode("utf-8")
    except UnicodeDecodeError as e:
        return False, f"UNDECODABLE: {e}"
    try:
        ast.parse(src)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"
    except (ValueError, RecursionError) as e:
        return False, f"{type(e).__name__}: {e}"
    return True, None


def write_bug_report(filepath, safe_name, cat, stderr, rc, elapsed):
    rel = os.path.relpath(filepath, ROOT)
    stderr_lines = [l for l in stderr.splitlines() if "_mojo_reflect.c" not in l]
    bugfile = os.path.join(BUGS_DIR, f"{cat}_{safe_name}.md")
    with write_lock:
        if os.path.exists(bugfile):
            return False
        with open(bugfile, "w") as f:
            f.write(f"# {cat}: {rel}\n\n")
            f.write(f"Source file: `{filepath}`\n\n")
            f.write(f"(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)\n\n")
            if stderr_lines:
                f.write("```\n")
                f.write("\n".join(stderr_lines[:50]))
                if len(stderr_lines) > 50:
                    f.write(f"\n... ({len(stderr_lines) - 50} more lines)")
                f.write("\n```\n\n")
            f.write(f"Exit code: {rc}\n")
            f.write(f"Elapsed: {elapsed:.2f}s\n")
    return True


def process_one(filepath):
    valid, reason = check_valid_python(filepath)
    safe_name = safe_name_for(filepath)
    if not valid:
        return {"file": filepath, "status": "INVALID_SOURCE", "reason": reason}

    already = existing_bug_category(safe_name)
    cat, stderr, stdout, rc, elapsed, cache_hit = run_build(filepath)

    filed = False
    if cat != "PASS" and already is None:
        filed = write_bug_report(filepath, safe_name, cat, stderr, rc, elapsed)

    return {
        "file": filepath,
        "status": cat,
        "already_known": already,
        "filed_new_bug": filed,
        "elapsed": elapsed,
        "cache_hit": cache_hit,
    }


def main():
    max_files = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    workers = int(os.environ.get("WORKERS", "8"))

    print(f"Scanning {ROOT} ...", flush=True)
    files = find_py_files(ROOT)
    if max_files:
        files = files[:max_files]
    print(f"Found {len(files)} .py files (workers={workers})", flush=True)

    results = []
    invalid = []
    counts = {c: 0 for c in CATEGORIES}
    new_bugs = []
    already_known_count = 0
    cache_hits = 0

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(process_one, f): f for f in files}
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            f = futs[fut]
            rel = os.path.relpath(f, ROOT)
            done += 1
            try:
                r = fut.result()
            except Exception as e:
                r = {"file": f, "status": "ERROR", "reason": str(e)}
            results.append(r)

            if r["status"] == "INVALID_SOURCE":
                invalid.append(r)
            else:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
                if r.get("cache_hit"):
                    cache_hits += 1
                if r.get("filed_new_bug"):
                    new_bugs.append(rel)
                elif r["status"] != "PASS" and r.get("already_known"):
                    already_known_count += 1

            if done % 25 == 0 or done == len(files):
                elapsed = time.time() - t0
                print(f"[{done}/{len(files)}] elapsed={elapsed:.0f}s "
                      f"pass={counts['PASS']} fail={sum(counts[c] for c in CATEGORIES if c!='PASS')} "
                      f"invalid_skipped={len(invalid)} new_bugs={len(new_bugs)} "
                      f"cache_hits={cache_hits}", flush=True)
            if done % 200 == 0:
                py314_cache.save()

    py314_cache.save()
    total_time = time.time() - t0
    summary = {
        "root": ROOT,
        "total_files": len(files),
        "total_time": round(total_time, 1),
        "counts": counts,
        "invalid_source_skipped": len(invalid),
        "invalid_source_examples": invalid[:50],
        "already_known_failures": already_known_count,
        "new_bugs_filed": new_bugs,
        "cache_hits": cache_hits,
    }
    with open(os.path.join(BUGS_DIR, "PY314_FULL_SCAN_SUMMARY.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Total .py files found:     {len(files)}")
    print(f"Invalid source (skipped):  {len(invalid)}")
    for cat in CATEGORIES:
        if counts[cat]:
            print(f"  {cat:15s} {counts[cat]}")
    print(f"Already-known failures (no new bug filed): {already_known_count}")
    print(f"New bug reports filed: {len(new_bugs)}")
    for b in new_bugs:
        print(f"  - {b}")
    print(f"\nCache hits: {cache_hits}/{len(files) - len(invalid)} "
          f"({os.path.basename(py314_cache.CACHE_PATH)})")
    print(f"Total time: {total_time:.0f}s")
    print(f"Summary written to {os.path.join(BUGS_DIR, 'PY314_FULL_SCAN_SUMMARY.json')}")


if __name__ == "__main__":
    main()
