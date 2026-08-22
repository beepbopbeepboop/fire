"""Byte-equivalence harness for the _run_pipeline consolidation (REF.html B3/A2).

Compiles a sample set through the pristine module (pre-consolidation, loaded
under a private name) and the refactored `gimple_codegen`, diffing every
output byte-for-byte across inline / cpp / link / compile_to_c modes.

Run from the repo (or worktree) root:  python3 tools/equiv_check.py
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gimple_codegen as new_mod  # noqa: E402


def _load_pristine():
    spec = importlib.util.spec_from_file_location(
        "_pristine_gimple_codegen", os.path.join(ROOT, "_pristine_gc.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


SAMPLES = ["hello.mojo", "t_func.mojo", "bootstrap_test_classes.mojo",
           "example_imports.mojo"]


def read(p):
    with open(os.path.join(ROOT, p)) as f:
        return f.read()


def main() -> int:
    old = _load_pristine()
    failures = 0
    checks = 0

    def cmp(label, a, b):
        nonlocal failures, checks
        checks += 1
        if a != b:
            failures += 1
            print(f"DIFF  {label} ({len(a)} vs {len(b)} chars)")
        else:
            print(f"ok    {label}")

    for s in SAMPLES:
        src = read(s)
        cmp(f"gimple      {s}",
            old.compile_to_gimple(src), new_mod.compile_to_gimple(src))
        cmp(f"gimple+fn   {s}",
            old.compile_to_gimple(src, False, s), new_mod.compile_to_gimple(src, False, s))
        c_old, cpp_old = old.compile_to_gimple_with_cpp(src)
        c_new, cpp_new = new_mod.compile_to_gimple_with_cpp(src)
        cmp(f"with_cpp.c  {s}", c_old, c_new)
        cmp(f"with_cpp.cpp {s}", cpp_old, cpp_new)
        l_old = old.compile_linked(src)
        l_new = new_mod.compile_linked(src)
        cmp(f"linked.code {s}", l_old[0], l_new[0])
        if l_old[1:] != l_new[1:]:
            failures += 1
            print(f"DIFF  linked.meta {s}: {l_old[1:]} vs {l_new[1:]}")
        else:
            checks += 1
            print(f"ok    linked.meta {s}")
        cmp(f"to_c        {s}", old.compile_to_c(src), new_mod.compile_to_c(src))

    # do_imports=True path on the helper that imports a sibling
    src = read("test_helper.mojo")
    cmp("gimple imports test_helper.mojo",
        old.compile_to_gimple(src, True, "test_helper.mojo"),
        new_mod.compile_to_gimple(src, True, "test_helper.mojo"))

    print(f"\n{checks} checks, {failures} diffs")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
