#!/usr/bin/env python3
"""Shared test harness for running Python-3.14.6 stdlib files through
mojo.py build. Single source of truth for categorization + caching, used by
test_py314_full.py and rerun_and_consolidate_v2.py (previously each had its
own copy-pasted, and slightly drifted, version of this logic).
"""
import os
import re
import subprocess
import sys
import tempfile
import time

import py314_cache
from build_config import find_gcc

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO_PY = os.path.join(HERE, "mojo.py")
GCC = find_gcc()


def categorize_error(stderr_text, stdout_text, returncode, out_path):
    combined = stderr_text + stdout_text

    # Ground truth: if the object file exists, the build genuinely succeeded,
    # regardless of any noisy warnings/notes in stderr.
    if os.path.exists(out_path):
        return "PASS"

    if re.search(r"Unexpected character", combined):
        if re.search(r"(Expected|but got).*NEWLINE", combined):
            return "PARSE_FAIL"
        return "LEX_FAIL"

    # Mojo's own parser errors always look like
    # "SyntaxError: <path>.py:<line>:<col>: <message>". Matching the bare
    # word "SyntaxError" is wrong: many stdlib files legitimately contain
    # that identifier (e.g. "except SyntaxError:") and reach the C-compile
    # stage successfully before hitting a real (unrelated) COMPILE_FAIL - a
    # bare substring match mis-labels those as PARSE_FAIL.
    if re.search(r"SyntaxError:\s*\S+\.py:\d+:\d+:", combined):
        return "PARSE_FAIL"

    py_errors = re.findall(r"[^:\s]+\.py:\d+:\d+: error:", combined)
    if py_errors:
        return "COMPILE_FAIL"

    if re.search(r"Linking failed|Undefined symbols|referenced from", combined):
        return "COMPILE_FAIL"

    if re.search(r"Error building", combined):
        return "COMPILE_FAIL"

    if returncode != 0:
        return "COMPILE_FAIL"

    return "PASS"


def _build_uncached(filepath, timeout=90):
    fd, out_path = tempfile.mkstemp(suffix=".o", prefix="pytest314_")
    os.close(fd)
    os.remove(out_path)
    cmd = [sys.executable, MOJO_PY, "build", "-o", out_path, filepath]
    start = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=HERE)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "(timeout after %ds)" % timeout, "", -1, time.time() - start
    except Exception as e:
        return "ERROR", str(e), "", -1, time.time() - start
    elapsed = time.time() - start
    cat = categorize_error(proc.stderr, proc.stdout, proc.returncode, out_path)
    if os.path.exists(out_path):
        os.remove(out_path)
    return cat, proc.stderr, proc.stdout, proc.returncode, elapsed


def run_build(filepath, timeout=90, use_cache=True):
    """Run mojo.py build on filepath, categorize the result, and cache it.

    Cache key folds in the compiler+toolchain fingerprint and the file's own
    bytes (see py314_cache.build_key), so a hit is only ever served for the
    exact same source against the exact same (possibly mid-fix, uncommitted)
    compiler - never a stale answer from before a bug got fixed.
    """
    key = None
    if use_cache:
        key = py314_cache.build_key(filepath, GCC)
        cached = py314_cache.get(key)
        if cached is not None:
            cat, stderr, stdout, rc = cached["cat"], cached["stderr"], cached["stdout"], cached["rc"]
            return cat, stderr, stdout, rc, 0.0, True  # elapsed=0, cache_hit=True

    cat, stderr, stdout, rc, elapsed = _build_uncached(filepath, timeout=timeout)

    # Timeouts/harness errors are not cached: a hang is a symptom of current
    # system load / a real bug that a subsequent fix should be re-measured
    # against, not something to freeze into the cache as a permanent verdict.
    if use_cache and cat not in ("TIMEOUT", "ERROR"):
        py314_cache.put(key, {"cat": cat, "stderr": stderr, "stdout": stdout, "rc": rc})

    return cat, stderr, stdout, rc, elapsed, False
