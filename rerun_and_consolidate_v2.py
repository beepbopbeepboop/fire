#!/usr/bin/env python3
"""Re-run the newly-discovered failing files from PY314_FULL_SCAN_SUMMARY.json
through mojo.py build, capturing FULL stderr (the first pass's per-file .md
reports truncated to 50 lines, which mis-signatured files whose real error
was preceded by many warnings). Group by accurate root-cause signature and
write consolidated reports directly (no intermediate per-file .md files).

categorize_error/run_build now live in py314_harness.py (shared with
test_py314_full.py - this file used to carry its own copy that had drifted).
Builds are cached via py314_cache.py: re-running this after a compiler fix
only re-executes files whose (compiler+file) cache key actually changed.
"""

import concurrent.futures
import json
import os
import re
import time

import py314_cache
from py314_harness import run_build

HERE = os.path.dirname(os.path.abspath(__file__))
BUGS_DIR = os.path.join(HERE, "bugs")
ROOT = os.path.expanduser("~/net/Python-3.14.6")
CONS_DIR = os.path.join(BUGS_DIR, "consolidated")
os.makedirs(CONS_DIR, exist_ok=True)


def normalize_signature(cat, stderr_text):
    lines = [l for l in stderr_text.splitlines() if l.strip() and "_mojo_reflect.c" not in l]
    if not lines:
        return "NO_ERROR_TEXT", ""

    if cat == "PARSE_FAIL":
        for l in lines:
            m = re.search(r"(Expected \S+ got \S+\(?[^)]*\)?|Unexpected \S+\(?[^)]*\)?|SyntaxError:.*)", l)
            if m:
                sig = re.sub(r"line \d+", "line N", m.group(1))
                sig = re.sub(r"'[^']*'\)", "X')", sig)
                return sig.strip(), l
        return lines[0][:120], lines[0]

    if cat == "COMPILE_FAIL":
        # Highest priority: real compiler errors (never masked by warnings/notes).
        for l in lines:
            m = re.search(r"error:\s*(.*)", l)
            if m and ("_mojo_reflect.c" not in l):
                sig = re.sub(r"'[^']+'", "'X'", m.group(1))
                sig = re.sub(r"\d+", "N", sig)
                return "CC ERROR: " + sig.strip()[:140], l
        for l in lines:
            if "Linking failed" in l or "Undefined symbols" in l or "referenced from" in l:
                return "LINKER: undefined symbol (unresolved import/external call)", l
        for l in lines:
            if "Error building" in l:
                sig = re.sub(r"'[^']+'", "'X'", l)
                sig = re.sub(r"\d+", "N", sig)
                return sig.strip()[:140], l
        # Only pure notes/warnings, no actual error/linker failure -> genuine
        # toolchain-noise false positive (matches the pre-existing
        # COMPILE_FAIL_false_positive_g3_warning.md class).
        for l in lines:
            if "-g3" in l and "not supported" in l:
                return "FALSE_POSITIVE: -g3 debug-flag warning misreported as failure (no real error/linker failure present)", l
        return lines[0][:140], lines[0]

    if cat == "TIMEOUT":
        return "TIMEOUT (build exceeded 90s)", ""

    return (lines[0] if lines else cat)[:140], (lines[0] if lines else "")


def slugify(sig):
    s = sig.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")[:60]


def main():
    with open(os.path.join(BUGS_DIR, "PY314_FULL_SCAN_SUMMARY.json")) as f:
        summary = json.load(f)
    rels = summary["new_bugs_filed"]
    files = [os.path.join(ROOT, r) for r in rels]

    workers = int(os.environ.get("WORKERS", "20"))
    print(f"Re-running {len(files)} files with full stderr capture (workers={workers})", flush=True)

    groups = {}
    cache_hits = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_build, f): f for f in files}
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            f = futs[fut]
            rel = os.path.relpath(f, ROOT)
            done += 1
            cat, stderr, stdout, rc, elapsed, cache_hit = fut.result()
            if cache_hit:
                cache_hits += 1
            if cat == "PASS":
                pass  # became a pass on rerun (fixed upstream); skip
            else:
                sig, example_line = normalize_signature(cat, stderr)
                key = (cat, sig)
                g = groups.setdefault(key, {"files": [], "example": stderr})
                g["files"].append(rel)
            if done % 100 == 0 or done == len(files):
                print(f"[{done}/{len(files)}] elapsed={time.time()-t0:.0f}s "
                      f"groups={len(groups)} cache_hits={cache_hits}", flush=True)
            if done % 200 == 0:
                py314_cache.save()

    py314_cache.save()

    ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]["files"]))
    index_lines = [
        "# Consolidated root-cause bug index (Python-3.14.6 full tree scan)\n\n",
        f"{len(files)} newly-discovered failing files were grouped into {len(groups)} "
        f"distinct root causes (full-stderr accurate pass; supersedes the earlier "
        f"truncated-stderr grouping attempt).\n\n",
        "| Category | Root cause | Files affected | Report |\n",
        "|---|---|---|---|\n",
    ]

    for i, ((cat, sig), g) in enumerate(ordered):
        n = len(g["files"])
        slug = slugify(sig) or f"group{i}"
        fname = f"{cat}_{slug}.md"
        fpath = os.path.join(CONS_DIR, fname)
        suffix = 2
        while os.path.exists(fpath):
            fname = f"{cat}_{slug}_{suffix}.md"
            fpath = os.path.join(CONS_DIR, fname)
            suffix += 1
        with open(fpath, "w") as f:
            f.write(f"# {cat}: {sig}\n\n")
            f.write(f"**{n} files** affected in the Python-3.14.6 full source tree scan.\n\n")
            f.write("## Example error (full stderr from one affected file)\n\n```\n")
            f.write(g["example"][:4000])
            f.write("\n```\n\n## Affected files\n\n")
            for rel in sorted(g["files"]):
                f.write(f"- `{rel}`\n")
        index_lines.append(f"| {cat} | {sig[:80]} | {n} | consolidated/{fname} |\n")

    with open(os.path.join(BUGS_DIR, "PY314_CONSOLIDATED_INDEX.md"), "w") as f:
        f.writelines(index_lines)

    print(f"\nWrote {len(groups)} consolidated reports to {CONS_DIR}/")
    print(f"Cache hits: {cache_hits}/{len(files)}")


if __name__ == "__main__":
    main()
