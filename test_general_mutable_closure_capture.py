"""REAL behavioral tests for mutable (by-reference) closure capture in
ORDINARY (non-async) nested `def`s — the high-priority, foundational bug
found while scoping test_locks.mojo's remaining gaps: a `{mut}`-capture-spec
closure (`def inc() {mut}: counter += 1`) did not actually propagate its
mutation back to the caller in EITHER execution path, even though this
project's own async mutable-capture mechanism (test_mutable_async_capture.py,
commit dcf9bf3) already worked for the async-coroutine flavor of the same
idiom. See bugs/CODEGEN_comptime_bracket_parametrized_function_calls_
silently_wrong.md's "investigated (not fixed) the transitive-closure-
capture gap" section for the corrected, real-Mojo-verified repro this test
mirrors.

Root causes fixed:
  - myinterpreter.py: `_assign_target` always called `Scope.define` (always
    writes the INNERMOST scope's own dict), even for `execute_AugAssignStmt`
    -- so `counter += 1` inside `inc()` silently created a new LOCAL
    `counter` shadowing the captured one, instead of mutating the enclosing
    scope's binding. Fixed by routing ONLY the AugAssignStmt case through
    `Scope.set` (walks up to the nearest existing binding) -- a plain `x =
    ...` assignment is deliberately left untouched (still always local,
    correct Python-like default nested-function-scoping).
  - gimple_codegen.py: the ordinary (non-async) closure-lifting mechanism
    (_gen_lifted_closure/_scan_for_closures) only ever captured free
    variables BY VALUE (copied into the closure's env struct once, at
    definition time) -- so a write inside the closure body only ever
    mutated the closure's own private copy. Fixed by detecting reassigned
    captures (GimpleGen._mutated_free_names, reused from the async
    mechanism) and threading them through as heap-boxed pointers instead
    (ClosureInfo.mut_names) -- see gimple_codegen.py's
    _seed_mut_captured_local_types docstring for why a HEAP-boxed pointer,
    not just `&stack_local`, is required (a real `-fgimple` restriction
    surfaced by std/memory/span.mojo's own `Span.count` during this fix's
    stdlib-dylib regression check).

This file compiles + links + RUNS each repro (interpreter via `mojo.py run`
AND the compiled path via a real gcc -fgimple build+link) and asserts on
real output, not just that the pieces compile/parse.
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


def _build_and_run_compiled(mojo_src: str, filename: str = 'prog.mojo') -> str:
    """Real compile+link+run through the same driver.compile_program path
    `python3 mojo.py <file.mojo>` (build mode) itself uses -- mirrors
    test_comptime_bracket_params.py's identical harness."""
    wd = tempfile.mkdtemp(prefix='mojo_general_mut_capture_')
    src_path = os.path.join(wd, filename)
    with open(src_path, 'w') as f:
        f.write(mojo_src)
    exe = os.path.join(wd, 'prog.exe')
    rc = driver.compile_program(src_path, mojo_src, output=exe, run=False)
    if rc is None:
        raise RuntimeError("driver.compile_program failed to build (returned None)")
    r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def _run_interpreted(mojo_src: str, filename: str = 'prog.mojo') -> str:
    """Real interpretation through `mojo.py run` (myinterpreter.py's own
    evaluator), captured via a subprocess so this test genuinely exercises
    the same code path a user's `python3 mojo.py <file.mojo> run` would."""
    wd = tempfile.mkdtemp(prefix='mojo_general_mut_capture_interp_')
    src_path = os.path.join(wd, filename)
    with open(src_path, 'w') as f:
        f.write(mojo_src)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'mojo.py'), 'run', src_path],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"interpreter run exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


_ORDINARY_MUT_SRC = """\
def test_ordinary_mut() raises:
    var counter = 0
    def inc() {mut}:
        counter += 1
    inc(); inc(); inc()
    print(counter)


def main() raises:
    test_ordinary_mut()
"""


def test_ordinary_mut_capture_interpreted():
    """The bug doc's exact, real-Mojo-verified repro, via the interpreter.
    Real Mojo (tools/mojo): prints 3. Before this fix, mojo.py run printed
    0 (each call silently rebound a fresh local `counter` inside `inc`)."""
    out = _run_interpreted(_ORDINARY_MUT_SRC)
    check("interpreter: {mut} closure capture propagates across 3 calls -> 3",
          out == "3\n", detail=repr(out))


def test_ordinary_mut_capture_compiled():
    """Same repro, via the compiled (gimple) path. Before this fix, `mojo.py
    build` + running the binary also printed 0 (by-value-only capture)."""
    out = _build_and_run_compiled(_ORDINARY_MUT_SRC)
    check("compiled: {mut} closure capture propagates across 3 calls -> 3",
          out == "3\n", detail=repr(out))


def test_read_only_capture_still_works_interpreted():
    """Regression guard: an ORDINARY (non-`{mut}`) closure that only READS
    a captured free variable must be completely unaffected by this fix --
    still a plain by-value/read-only capture, no accidental promotion to
    by-reference."""
    src = """\
def test_read_only() raises:
    var base = 10
    def add_base(x: Int) -> Int:
        return base + x
    print(add_base(1))
    print(add_base(2))


def main() raises:
    test_read_only()
"""
    out = _run_interpreted(src)
    check("interpreter: read-only capture unaffected -> 11 / 12",
          out == "11\n12\n", detail=repr(out))


def test_read_only_capture_still_works_compiled():
    src = """\
def test_read_only() raises:
    var base = 10
    def add_base(x: Int) -> Int:
        return base + x
    print(add_base(1))
    print(add_base(2))


def main() raises:
    test_read_only()
"""
    out = _build_and_run_compiled(src)
    check("compiled: read-only capture unaffected -> 11 / 12",
          out == "11\n12\n", detail=repr(out))


def test_plain_reassignment_still_shadows_locally_interpreted():
    """Regression guard: a captured free variable REASSIGNED with plain
    `=` (not `+=`) inside a nested `def`, WITHOUT `{mut}`, must still shadow
    locally (real Python/Mojo's own default nested-function-scoping) --
    this fix deliberately only special-cases AugAssignStmt (`counter +=
    1`-shaped mutation), never a plain `=` assignment."""
    src = """\
def test_local_shadow() raises:
    var x = 1
    def shadow():
        x = 99
        print(x)
    shadow()
    print(x)


def main() raises:
    test_local_shadow()
"""
    out = _run_interpreted(src)
    check("interpreter: plain `=` in a nested def still shadows locally -> 99 / 1",
          out == "99\n1\n", detail=repr(out))


def test_captured_local_returned_after_mutation_compiled():
    """Mirrors the REAL stdlib shape that surfaced the heap-boxing
    requirement during this fix's own stdlib-dylib regression check
    (std/memory/span.mojo's `Span.count`, a `{mut count, read ...}`-spec
    nested `def` whose enclosing function `return`s the captured local
    afterward): once a local's address is taken anywhere in a `-fgimple`
    function, that SAME local can no longer be the direct operand of a
    `return` statement or a cast-assignment elsewhere in that function
    ("non-register as LHS of unary operation" / "invalid operand in
    return statement" -- confirmed via a hand-reduced repro). Heap-boxing
    the captured local (see gimple_codegen.py's _seed_mut_captured_local_
    types docstring) sidesteps this by never taking `&stack_local` at
    all."""
    src = """\
def accumulate(values: Int) raises -> Int:
    var total = 0
    def add(v: Int) {mut total}:
        total += v
    var i = 0
    while i < 3:
        add(values)
        i += 1
    return total


def main() raises:
    print(accumulate(5))
"""
    out = _build_and_run_compiled(src)
    check("compiled: {mut}-captured local safely returned afterward -> 15",
          out == "15\n", detail=repr(out))


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
