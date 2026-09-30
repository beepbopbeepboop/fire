"""REAL behavioral tests for heap-boxed ({mut}/nonlocal) closure captures
whose FIRST BINDING is a PLAIN assignment statement — the Python-source
shape (`next_opcode = 1` before a nested `def` that reassigns it), as
opposed to the Mojo-source shape (`var counter = 0`) every earlier test in
test_general_mutable_closure_capture.py exercises.

Root cause fixed (bugs/COMPILE_FAIL_Tools_cases_generator_analyzer.md's
exit-time/mid-run segfault residual, analyzer.py:1066): the box for a
by-reference-captured local used to be allocated by _gen_stmt_VarDecl at
the local's `var x = ...` statement. Real Python source's first binding is
a PLAIN AssignStmt that never reaches that handler, so the `{ctype} * name`
pointer (pre-declared by _seed_mut_captured_local_types) was NEVER
allocated, while every read/write still dereferenced it — a write through
an uninitialized pointer local. Observed as a deterministic NULL-deref
segfault mid-assign_opcodes under lldb on one machine and (the same UB)
as an apparently-working run with a crash "at exit" on another, depending
on what garbage the uninitialized local happened to hold.

Fix: _emit_mut_local_box_allocs allocates every boxed local's cell ONCE in
the function prologue (exactly-once, call-scoped — Python's own per-call
cell model), so first bindings via AssignStmt, VarDecl, or a rebinding
after the nested def all share the same single cell, and the lifted
closure's env field (which stores the POINTER) stays valid across later
rebindings (`next_opcode = min_internal` after the env was captured).

This file compiles + links + RUNS each repro through the real compiled
path (driver.compile_program, link mode) and asserts on real output.
"""
import os
import subprocess
import sys
import tempfile

import driver

HERE = os.path.dirname(os.path.abspath(__file__))

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def _build_and_run_compiled(src: str, filename: str = 'prog.py') -> str:
    wd = tempfile.mkdtemp(prefix='mojo_plain_assign_mut_capture_')
    src_path = os.path.join(wd, filename)
    with open(src_path, 'w') as f:
        f.write(src)
    exe = os.path.join(wd, 'prog.exe')
    rc = driver.compile_program(src_path, src, output=exe, run=False)
    if rc is None:
        raise RuntimeError("driver.compile_program failed to build (returned None)")
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


# The exact analyzer.py:1066 shape: plain-assignment first binding, then a
# nested def whose body AugAssigns the free name (analyzer.py's
# `next_opcode += 1`), with further plain rebindings of the same outer
# local AFTER the closure was created — the env must keep pointing at the
# ONE prologue-allocated cell so the closure sees every rebinding (real
# `nonlocal` semantics; expectations verified against real CPython 3.14).
_PLAIN_ASSIGN_FIRST_BINDING_SRC = """\
def assign_opcodes_like():
    total = 0

    def bump(limit):
        while total < limit:
            total += 1

    bump(3)
    total = 100
    bump(103)
    return total


def main():
    print(assign_opcodes_like())


main()
"""


def test_plain_assign_first_binding_no_segfault_compiled():
    """Before the fix this segfaulted (write through the never-allocated
    box pointer at the `total = 0` first binding) or silently corrupted
    memory depending on stack garbage; with the prologue allocation it
    computes the CPython-verified 103."""
    out = _build_and_run_compiled(_PLAIN_ASSIGN_FIRST_BINDING_SRC)
    check("compiled: plain-AssignStmt-first-binding boxed capture -> 103",
          out == "103\n", detail=repr(out))


# Cell-identity across mid-stream outer rebindings: every write (closure
# AugAssign AND outer plain rebinding) must land on the same single cell.
# Also covers a VarDecl-free shape where ALL bindings are plain AssignStmts.
# Expectation verified against real CPython 3.14 (17).
_MIDSTREAM_REBINDING_SRC = """\
def counter_factory():
    total = 0

    def inc():
        total += 1

    i = 0
    while i < 5:
        inc()
        i += 1
    total = total + 10
    inc()
    inc()
    return total


def main():
    print(counter_factory())


main()
"""


def test_single_cell_identity_across_calls_compiled():
    """The old VarDecl-time allocation scheme allocated per-statement
    execution and missed plain-AssignStmt bindings entirely; the prologue
    scheme gives exactly-once, call-scoped cells, so the closure and the
    outer rebinding stay in lockstep -> 17 (CPython-verified)."""
    out = _build_and_run_compiled(_MIDSTREAM_REBINDING_SRC)
    check("compiled: closure + outer rebinding share one cell -> 17",
          out == "17\n", detail=repr(out))


# Regression guard for intended semantics (mirrors test_general_mutable_
# closure_capture.py's interpreter-side shadowing guard, here on the
# COMPILED path): an inner def's PLAIN `x = ...` to a free name is still a
# LOCAL shadow (real Python without a working `nonlocal` statement — which
# this parser treats as no-op ExprStmts), NOT a by-reference capture. Only
# AugAssign-shaped mutation promotes the capture. CPython-verified: 1.
_INNER_PLAIN_ASSIGN_SHADOWS_SRC = """\
def shadow_like():
    x = 1

    def set_local():
        x = 99

    set_local()
    return x


def main():
    print(shadow_like())


main()
"""


def test_inner_plain_assign_still_shadows_locally_compiled():
    out = _build_and_run_compiled(_INNER_PLAIN_ASSIGN_SHADOWS_SRC)
    check("compiled: inner plain `=` still shadows locally -> 1",
          out == "1\n", detail=repr(out))


def run_all():
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
            except Exception as e:
                check(name, False, detail=f"exception: {e}")
    print(f"\nResults: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    sys.exit(0 if run_all() else 1)
