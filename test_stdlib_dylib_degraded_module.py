#!/usr/bin/env python3
"""Regression: a module whose generic-struct elaboration failed must not be
silently linked into the stdlib dylib (build_stdlib_dylib._compile_module_job /
_compile_one_object must report it as the job's error so the caller skips it).

The live case (`std/simd.mojo`) no longer degrades, so this forces a degraded
compile through the job with a stubbed elaboration result, the same way
compile_stdlib.py's verdict test does.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_stdlib_dylib as bsd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))


real_compile = bsd.compile_module_to_c
reason = "forced: generic struct elaboration failed (stubbed for the dylib job)"


def _degraded(src, path, module_name, linkable=True):
    # Produce C the compiler could object-compile, but record a degradation for
    # THIS compile so the dylib path must refuse to publish/link it.
    bsd._LAST_DEGRADED[:] = [reason]
    return "void __stub__(void) {}\n"


with tempfile.TemporaryDirectory() as wd:
    src_path = os.path.join(wd, "degraded_mod.mojo")
    open(src_path, "w").write("def f() -> Int:\n    return 1\n")

    bsd.compile_module_to_c = _degraded
    try:
        bsd._stdlib_compile_cache.clear()
        path, name, ofile, exports, error, hit = bsd._compile_module_job(
            src_path, wd, use_cache=False)
        check("degraded module is refused, not linked",
              error is not None and ofile is None,
              f"error={error!r} ofile={ofile!r}")
        check("refusal reports the elaboration failure",
              error is not None and "elaboration" in error and "not the program" in error,
              f"error={error!r}")
        check("refusal carries the degradation reason",
              error is not None and "forced" in error,
              f"error={error!r}")

        # The cached build path must also refuse, and must not publish the
        # degraded object into the shared CAS.
        bsd._stdlib_compile_cache.clear()
        path2, name2, ofile2, exports2, error2, hit2 = bsd._compile_module_job(
            src_path, wd, use_cache=True)
        check("degraded module is refused on the cached build path",
              error2 is not None and ofile2 is None,
              f"error={error2!r} ofile={ofile2!r} hit={hit2!r}")
    finally:
        bsd.compile_module_to_c = real_compile
        bsd._LAST_DEGRADED[:] = []

print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
