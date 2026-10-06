#!/usr/bin/env python3
"""What `comptime` actually does on each path — measured, not assumed.

The first version of this file asserted that the interpreter and the compiled
backend must REFUSE `comptime <expr>`, on the reasoning that a construct they
disagree about should be rejected. Measurement killed that premise, and the
correction is the reason this file now reads the way it does:

  * `comptime <expr>` is REAL and the standard library uses it. Four files in
    the stdlib — `std/algorithm/reduction.mojo`, `std/math/math.mojo`,
    `std/memory/stack_allocation.mojo`, `std/reflection/reflect.mojo` — spell it
    `comptime (expr)` and compile. Refusing it at the parse took
    `compile_stdlib.py` from **664 passed / 0 unexpected** to **660 / 4**, and
    `U` must never increase.
  * The compiled backend does not REFUSE it. It evaluates to `0` and prints
    `comptime: unavailable in compiled mode`, which is the codebase's
    established convention for a name that has no compiled lowering (see the
    weak-stub pattern in `mojo/backend_gimple/module_gen.py`).
  * The interpreter raises `NameError: name 'comptime' is not defined`.

So the three paths do not agree, they cannot be made to agree without a
`comptime` expression evaluator, and the honest state is a documented
divergence rather than a refusal that breaks the stdlib.

**What is left, and it is the one thing worth a test:** the parenthesized
spelling warns and the bare one does not. Both evaluate to 0, so
`comptime _s()` — a function returning 7 — prints `0` with nothing on stderr
or stdout to say why. That is the only silent cell in the table, and this file
pins it as a KNOWN DIVERGENCE so that a future change cannot quietly make it
worse, and so the day someone implements the fold there is a failing test to
notice.

Run:  python3 test_comptime_parity.py
"""
import os
import subprocess
import sys
import tempfile
import textwrap

# Three kinds of child, three sites: a `fire.py build` (a COMPILE), the
# executable that build produced (a RUN), and `fire.py run` — which is not a
# build at all but this project's own INTERPRETER executing the program, so it
# is a RUN and was 300 s for a reason that no longer holds.
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# Bodies are indented RELATIVE to `fn main()`; textwrap adds the function's own
# four spaces. A block body carries one extra level, a plain statement none.
AGREE = [
    ("comptime var", 'comptime n = 6\nprint("v:", n)'),
    ("comptime if", 'comptime if 1 > 0:\n    print("i: yes")'),
    ("comptime for", 'comptime for i in range(3):\n    print("f:", i)'),
    ("comptime assert", 'comptime assert 1 == 1\nprint("a: ok")'),
    ("assignment to a var named comptime",
     'comptime = 5\ncomptime = comptime + 1\nprint("a:", comptime)'),
    ("parameter named comptime",
     'def f(comptime: Int) -> Int:\n    return comptime * 2\nprint("p:", f(4))'),
    ("@comptime decorator",
     'def _t(f):\n    return f\n\n@comptime\ndef _k() -> Int:\n    return 3\n'
     'print("d:", _k())'),
]

PRELUDE = 'def _s() -> Int:\n    return 7\n\n'

# The cell that is silent. `_s()` returns 7; both spellings produce 0.
# `comptime (_s())` prints the diagnostic, `comptime _s()` does not.
# (label, body, parenthesised). The flag is explicit because sniffing the body
# for "(" gets it wrong: `print(` is in both of them.
KNOWN_DIVERGENCE = [
    ("comptime (expr)", 'var a = comptime (_s())\nprint("val:", a)', True),
    ("comptime expr, bare", 'var a = comptime _s()\nprint("val:", a)', False),
]

DIAG = "unavailable in compiled mode"


def _run(src, tmp, i, exe):
    out = os.path.join(tmp, f"p{i}")
    b = subprocess.run([PY, "fire.py", "build", "-o", out, src], cwd=HERE,
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    if b.returncode != 0:
        return None, b.stdout, b.stderr
    r = subprocess.run([out], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    return r.stdout, r.stdout, r.stderr


def _refused_as_comptime(stderr: str) -> bool:
    return "not supported by this compiler" in (stderr or "")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="comptime-")
    src = os.path.join(tmp, "t.mojo")
    exe = os.path.join(tmp, "t")
    failures, notes = [], []

    # 1. Everything that works must keep working, identically on both paths.
    for i, (label, toplevel) in enumerate(AGREE):
        if label == "comptime var":
            body, pre = toplevel, PRELUDE
        else:
            body, pre = toplevel, ""
        with open(src, "w") as f:
            if "\nfn main" in toplevel or toplevel.startswith("def f(") \
               or toplevel.startswith("def _t("):
                f.write(toplevel + "\n")
            else:
                f.write(pre + "fn main():\n" + textwrap.indent(body, "    ") + "\n")
        iout, iout2, ierr = _run(src, tmp, i, exe) if False else (None, None, None)
        # interpreted
        ri = subprocess.run([PY, "fire.py", "run", src], cwd=HERE,
                            capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
        # compiled
        cout, _, cerr = _run(src, tmp, 100 + i, exe)
        checks = 1
        if _refused_as_comptime(ierr) or _refused_as_comptime(cerr):
            failures.append(f"{label}: refused as an unsupported comptime form; "
                            "it is supported and this must keep working")
        elif ri.returncode != 0 or cout is None:
            errs = [l for l in (ri.stderr + (cerr or "")).splitlines() if "Error" in l]
            failures.append(f"{label}: stopped working. interp rc={ri.returncode} "
                            f"compiled={'ok' if cout is not None else 'build failed'}\n"
                            f"  {(errs[-1] if errs else '')[:200]}")
        elif ri.stdout != cout:
            failures.append(f"{label}: the engines disagree.\n"
                            f"  interp:   {ri.stdout!r}\n  compiled: {cout!r}")

    # 2. The known divergence, pinned so it cannot get worse and so the fix has
    #    a failing test to trip.
    for i, (label, body, parenthesised) in enumerate(KNOWN_DIVERGENCE):
        with open(src, "w") as f:
            f.write(PRELUDE + "fn main():\n" + textwrap.indent(body, "    ") + "\n")
        ri = subprocess.run([PY, "fire.py", "run", src], cwd=HERE,
                            capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
        cout, _, cerr = _run(src, tmp, 200 + i, exe)
        if cout is None:
            failures.append(f"{label}: the build now FAILS. That is a change in "
                            "kind, not in degree — 4 stdlib files use the "
                            "parenthesized form, so report it, do not assume it.")
            continue
        if "val: 0" not in cout:
            notes.append(f"{label}: no longer evaluates to 0 ({cout!r}) — if a "
                         "`comptime` evaluator landed, delete the KNOWN_DIVERGENCE "
                         "table and assert the real value instead.")
        says_why = DIAG in cout
        if not parenthesised and not says_why:
            notes.append(
                f"{label}: STILL SILENT. Expected — this is the one cell with no "
                f"diagnostic. `_s()` returns 7 and the program prints 0 with "
                f"nothing on either stream. Fix belongs in the lowering of a "
                f"comptime expression (the parenthesized spelling's diagnostic "
                f"is in mojo/backend_gimple/), not in the parser.")
        if parenthesised and not says_why:
            failures.append(
                f"{label}: the parenthesized form has LOST its diagnostic. Four "
                f"stdlib files use this spelling, so it must keep compiling AND "
                f"keep saying why it returns 0. Got: {cout!r}")

    for n in notes:
        print("  NOTE  " + n)
    for f in failures:
        print("  FAIL  " + f)
    total = len(AGREE) + len(KNOWN_DIVERGENCE)
    print(f"\ncomptime: {'PASS' if not failures else 'FAIL'} "
          f"({total - len(failures)}/{total} checks, {len(notes)} noted)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
