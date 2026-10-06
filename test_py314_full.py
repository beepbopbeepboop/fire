#!/usr/bin/env python3
"""Comprehensive test of ~/net/Python-3.14.6's .py files against fire.py build.

Differences from test_py_stdlib.py / runner.py:
  - Scans the full Python-3.14.6 source tree (Lib/, Tools/, Doc/, PC/, etc.),
    not just a homebrew Lib/ copy limited to a 100-file sample.
  - Validates each file is syntactically valid Python (ast.parse) BEFORE
    running it through fire.py build. Test-suite fixtures that are
    *intentionally* invalid Python (e.g. Lib/test/badsyntax_*.py) are
    skipped and logged separately rather than filed as mojo bugs.
  - Dedups against the report directory already on disk: if any category file
    already exists for a given relative path, no new report is written.
  - Caches every fire.py build outcome in py314_build_cache.json (keyed by
    compiler+toolchain fingerprint + file content, via py314_cache.py/cas.py)
    so re-running against an unchanged compiler is near-instant instead of
    repeating ~15 minutes of subprocess builds for files whose answer hasn't
    changed.

**It writes its reports to a directory you name, and that directory is a TEMP
one unless you ask otherwise.** It used to write `bugs/<CATEGORY>_<path>.md`
into this repository, which made it a process rather than a test: measured on
2026-10-01, 300 seconds of it produced **25 new files in `bugs/`** and a
`grammar_snippet_gen.cpp` at the repo root, and the failure mode is not who ran
it. `tools/suite.py` launches jobs in parallel from a common checkout, so two
runs racing on the same category file, or one killed half-way leaving a
truncated doc that the dedup then treats as complete, are both quiet.
`bugs/UNTESTED.md` §4.1 records the finding.

So: `--root` names the tree to scan (a missing one is a loud non-zero exit, not
a silent zero-file pass), `--out` names where reports go and defaults to a
fresh temp directory printed at the end, and `--write-to-bugs` restores the old
destination for the deliberate, manual, human-in-the-loop run. The
investigation is unchanged; only the write target moved, and the summary says
where it went.
"""

import argparse
import ast
import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import time

import py314_cache
from py314_harness import run_build

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_BUGS = os.path.join(HERE, "bugs")
DEFAULT_ROOT = os.path.expanduser("~/net/Python-3.14.6")

EXCLUDE_DIR_NAMES = {".git", "__pycache__", "venv", ".venv"}

CATEGORIES = ["PASS", "LEX_FAIL", "PARSE_FAIL", "COMPILE_FAIL", "TIMEOUT", "ERROR"]

# Set by main() from --out/--write-to-bugs, and read by the two writers. A
# module global because the report writers are called from worker threads and a
# path threaded through eight call signatures to say "and do not write into the
# repository" is a worse shape than one assignment.
OUT_DIR = None
write_lock = threading.Lock()


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=DEFAULT_ROOT,
                    help=f"tree of .py files to scan (default {DEFAULT_ROOT})")
    ap.add_argument("--out", default=None,
                    help="directory to write reports into; a fresh temp "
                         "directory if not given. The path is printed at the "
                         "end, so a run cannot write anywhere silently")
    ap.add_argument("--write-to-bugs", action="store_true",
                    help="write into this repository's bugs/ -- the ORIGINAL "
                         "behaviour, for a deliberate manual run. Off by "
                         "default because a test that writes into a shared "
                         "tree is a process, not a test (bugs/UNTESTED.md 4.1)")
    ap.add_argument("max_files", nargs="?", default=None,
                    help="stop after N files")
    return ap.parse_args(argv)


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


def existing_report(safe_name):
    for cat in CATEGORIES:
        if cat == "PASS":
            continue
        if os.path.exists(os.path.join(OUT_DIR, f"{cat}_{safe_name}.md")):
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
    bugfile = os.path.join(OUT_DIR, f"{cat}_{safe_name}.md")
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

    already = existing_report(safe_name)
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


def main(argv=None):
    global OUT_DIR, ROOT
    args = parse_args(sys.argv[1:] if argv is None else argv)
    ROOT = os.path.abspath(os.path.expanduser(args.root))
    max_files = int(args.max_files) if args.max_files and args.max_files.isdigit() else None
    workers = int(os.environ.get("WORKERS", "8"))

    # A missing tree is a loud non-zero exit, never a zero-file pass. A
    # registered test that skips silently when a path is absent is a gate that
    # measures nothing, which is worse than an unrun file.
    if not os.path.isdir(ROOT):
        print(f"test_py314_full: no such tree: {ROOT}\n"
              f"  pass --root <dir> to point at one "
              f"(default {DEFAULT_ROOT})", file=sys.stderr)
        return 2

    if args.write_to_bugs:
        OUT_DIR = REPO_BUGS
    elif args.out:
        OUT_DIR = os.path.abspath(os.path.expanduser(args.out))
    else:
        OUT_DIR = tempfile.mkdtemp(prefix="py314_full_")
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Scanning {ROOT} ... reports go to {OUT_DIR}", flush=True)
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
    with open(os.path.join(OUT_DIR, "PY314_FULL_SCAN_SUMMARY.json"), "w") as f:
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
    print(f"Reports and summary written to {OUT_DIR}")
    if OUT_DIR != REPO_BUGS and new_bugs:
        print(f"  {len(new_bugs)} report(s) written. To put them where the "
              f"queue lives, review them and copy, or re-run with "
              f"--write-to-bugs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
