#!/usr/bin/env python3
"""
Bootstrap Validation - Verify deterministic compilation across three stages.

Checks .ci, .tok, .ast, and .pyi outputs for every *.mojo and *.py source file,
comparing stage1 vs stage2 vs stage3 for byte identity.

Stage 1: Python-driven compilation  (ground truth)
Stage 2: stage2/mojo binary output  (must match stage1)
Stage 3: stage2/mojo idempotency    (must match stage2)
"""

import os
import sys
import glob

EXTENSIONS = [".ci", ".tok", ".ast", ".pyi"]

def stem(path):
    """Return filename stem without extension, e.g. 'foo/bar.mojo' -> 'bar'."""
    return os.path.splitext(os.path.basename(path))[0]

def compare_stages(base, extensions, verbose=False):
    """Compare a single stem across all stages and extensions. Returns (ok, failures)."""
    failures = []
    for ext in extensions:
        s1 = os.path.join("stage1", base + ext)
        s2 = os.path.join("stage2", base + ext)
        s3 = os.path.join("stage3", base + ext)

        if not os.path.isfile(s1):
            # Stage 1 must always exist
            failures.append("MISSING stage1/" + base + ext)
            continue

        s1_bytes = open(s1, "rb").read()
        s1_len   = len(s1_bytes)

        if os.path.isfile(s2):
            s2_bytes = open(s2, "rb").read()
            if s1_bytes != s2_bytes:
                failures.append("DIFFER stage1 vs stage2: " + base + ext +
                                 " (" + str(s1_len) + " vs " + str(len(s2_bytes)) + " bytes)")
        else:
            failures.append("MISSING stage2/" + base + ext)

        if os.path.isfile(s3):
            s3_bytes = open(s3, "rb").read()
            if s1_bytes != s3_bytes:
                failures.append("DIFFER stage1 vs stage3: " + base + ext +
                                 " (" + str(s1_len) + " vs " + str(len(s3_bytes)) + " bytes)")
        else:
            failures.append("MISSING stage3/" + base + ext)

        if verbose and not failures:
            print("  OK " + base + ext + " (" + str(s1_len) + " bytes)")
    return failures

def collect_sources():
    """Return list of (path, stem) for all .mojo and key .py files."""
    sources = []
    for pattern in ("*.mojo", "mojo/*.mojo"):
        for p in sorted(glob.glob(pattern)):
            sources.append((p, stem(p)))
    # The core .py sources the bootstrap stages dump — this must be exactly
    # tools/suite.py's PY_FILES, which is what the stage drivers enumerate
    # (BOOTSTRAP_INPUTS = MOJO_FILES + PY_FILES). This list is a second copy
    # only because this script is itself part of the bootstrap corpus the
    # compiled binary dumps, so it may not grow new imports to share the
    # constant; test_bootstrap_validate_source_list_regress.py keeps the two in
    # step and proves each name is really checked. It DID go stale at the
    # mojo.py -> fire.py rename (2026-09-26): it named mojo.py,
    # mojo_compiler.py and mojo_main.py (all gone, so os.path.isfile skipped
    # them silently) and omitted fire.py, fire_compiler.py and fire_main.py,
    # so half the compiler's own artefacts were never required in any stage.
    for p in sorted([
        "fire.py", "fire_compiler.py", "fire_main.py",
        "myinterpreter.py", "module_loader.py", "generated_dispatch.py",
    ]):
        if os.path.isfile(p):
            sources.append((p, stem(p)))
    return sources

def main():
    print("Bootstrap Validation")
    print("=" * 72)
    print("")

    # Verify stage directories exist
    for stage in ("stage1", "stage2", "stage3"):
        if not os.path.isdir(stage):
            print("ERROR: " + stage + " directory not found - run make bootstrap first")
            sys.exit(1)

    sources = collect_sources()
    if not sources:
        print("ERROR: no .mojo source files found")
        sys.exit(1)

    print("Checking " + str(len(sources)) + " source files x " +
          str(len(EXTENSIONS)) + " output types across 3 stages")
    print("")

    all_failures = []
    ok_count     = 0

    for path, base in sources:
        failures = compare_stages(base, EXTENSIONS, verbose=False)
        if failures:
            print("FAIL  " + path)
            for msg in failures:
                print("        " + msg)
            all_failures.extend(failures)
        else:
            print("  OK  " + path)
            ok_count += len(EXTENSIONS)

    print("")
    print("=" * 72)

    total = len(sources) * len(EXTENSIONS)
    if not all_failures:
        print("PASSED: all " + str(total) + " output files match across 3 stages")
        print("")
        sys.exit(0)
    else:
        print("FAILED: " + str(len(all_failures)) + " mismatch(es) / " + str(total) + " checked")
        print("")
        sys.exit(1)

main()
