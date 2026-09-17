"""REAL behavioral tests for monomorphize.py's dual C/C++ output support --
test_tracing.mojo's own real shape: a comptime-bracket-parametrized generic
function (elaborated via elaborate.py/monomorphize.py's textual
monomorphizer, e.g. `test_tracing[level, enabled]()`) containing a NESTED
`async def` that itself has its OWN comptime bracket parameters (`test_
tracing_add[enabled, lhs](rhs)`), composed via `create_task(...)`/`await`.

Before this fix, `monomorphize.instantiate()`'s `build()` only ever asked
for the elaborated fragment's ordinary GIMPLE `.c` output --
`GimpleGen.generated_cpp` (the real C++20 coroutine translation unit a
nested async def needs) was silently discarded entirely, and
`monomorphize_source`'s textual substitution had no notion of a nested
function's own re-declared (shadowing) bracket-parameter name -- both
real, hand-verified silent-miscompile/corruption risks `_elaborate_
generic_call` used to refuse outright rather than risk (see bugs/CODEGEN_
comptime_bracket_parametrized_function_calls_silently_wrong.md).

This file compiles + links + RUNS each repro (via driver.compile_program,
the real `fire.py build`/`run` module-cache pipeline -- not compile-only)
and asserts on real stdout, plus a couple of pure unit tests for the
substitution-safety helper itself.
"""
import os
import subprocess
import sys
import tempfile

import monomorphize as mm
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


def _build_and_run(mojo_src: str, timeout: int = 30) -> str:
    """Real compile+link+run through driver.compile_program -- the actual
    pipeline `python3 fire.py build`/`run` uses (module-cache/link mode,
    the ONLY path that supports generic elaboration's own recorded link
    objects at all)."""
    wd = tempfile.mkdtemp(prefix='mojo_dual_cpp_elab_')
    src_path = os.path.join(wd, 'prog.mojo')
    with open(src_path, 'w') as f:
        f.write(mojo_src)
    exe = os.path.join(wd, 'prog.exe')
    rc = driver.compile_program(src_path, mojo_src, output=exe, run=False)
    if rc is None:
        raise RuntimeError("driver.compile_program failed to build (returned None)")
    r = subprocess.run([exe], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"program exited {r.returncode}, stderr={r.stderr}")
    return r.stdout


def test_shadowed_spans_protects_nested_bracket_declaration():
    """Pure unit test for `monomorphize_source`'s own substitution safety:
    test_tracing.mojo's real shape -- an outer `enabled` bracket param,
    re-declared independently by TWO levels of nested async defs. The
    outer substitution must not corrupt either nested declaration (or
    their own bodies, where `enabled` refers to the NESTED binding, not
    the outer one) into invalid syntax (`[True: Bool, ...]`), while a
    genuinely non-shadowed name (`level`) still substitutes everywhere,
    including inside those same nested bodies."""
    tmpl = (
        "def test_tracing[level: Int, enabled: Bool]() raises:\n"
        "    @parameter\n"
        "    async def test_tracing_add[enabled: Bool, lhs: Int](rhs: Int) -> Int:\n"
        "        if enabled:\n"
        "            return lhs + rhs + level\n"
        "        return rhs\n"
        "\n"
        "    @parameter\n"
        "    async def test_tracing_add_two_of_them[enabled: Bool](a: Int, b: Int) -> Int:\n"
        "        var t0 = create_task(test_tracing_add[enabled, 1](a))\n"
        "        var t1 = create_task(test_tracing_add[enabled, 2](b))\n"
        "        return await t0 + await t1\n"
        "\n"
        "    print(1)\n"
    )
    _mangled, concrete = mm.monomorphize_source(tmpl, {'level': 100, 'enabled': 'True'})
    check("nested bracket declarations (both levels) stay syntactically "
          "valid -- 'enabled' text untouched",
          "test_tracing_add[enabled: Bool, lhs: Int]" in concrete
          and "test_tracing_add_two_of_them[enabled: Bool]" in concrete,
          detail=concrete)
    check("nested call sites using the shadowed name are ALSO untouched "
          "(test_tracing_add[enabled, 1](a), not [True, 1](a))",
          "test_tracing_add[enabled, 1](a)" in concrete
          and "test_tracing_add[enabled, 2](b)" in concrete,
          detail=concrete)
    check("a NON-shadowed outer param (level) still substitutes everywhere, "
          "including inside a nested (shadowed-for-`enabled`) function body",
          "return lhs + rhs + 100" in concrete, detail=concrete)


def test_nested_generic_bracket_async_compiles_links_runs():
    """Simplest real shape: a local generic top-level function containing
    a nested async def, called via create_task(...)/.wait() -- exercises
    the dual C/C++ artifact build+cache end to end (not just parsing)."""
    src = """\
def outer[level: Int]() raises:
    @parameter
    async def inc() -> Int:
        return level + 1

    var t = create_task(inc())
    print(t.wait())


def main() raises:
    outer[10]()
"""
    out = _build_and_run(src)
    check("local generic containing a nested async def -> 11",
          out == "11\n", detail=repr(out))


def test_doubly_nested_bracket_async_composition_correct_argument_order():
    """test_tracing.mojo's own real shape, minus Trace/TraceLevel (covered
    separately below): a nested async def with its OWN comptime bracket
    params (`test_tracing_add[enabled, lhs](rhs)`), called via create_task
    (...)/await from a SIBLING nested async def which is itself bracket-
    parametrized and called via create_task(...)/.wait() from the
    (elaborated) generic's own top-level body.

    Deliberately NON-commutative and 3-parameter (unlike test_asyncrt.
    mojo's own `lhs + rhs`-summing tests, which happen to produce the same
    result whether `lhs`/`rhs` are swapped) -- this is the exact shape that
    caught a real argument-ORDER bug (comptime bracket args were being
    emitted BEFORE the call's own ordinary arguments at three separate
    composition call sites, but the callee's actual compiled signature
    places ordinary params first) at three independent call sites. Expects
    (1+10) + (2+20) = 33 -- the swapped-order bug produced 32 (confirmed
    via a hand-verified repro before the fix)."""
    src = """\
def test_tracing[level: Int, enabled: Bool]() raises:
    @parameter
    async def test_tracing_add[enabled: Bool, lhs: Int](rhs: Int) -> Int:
        return lhs + rhs

    @parameter
    async def test_tracing_add_two_of_them[enabled: Bool](a: Int, b: Int) -> Int:
        var t0 = create_task(test_tracing_add[enabled, 1](a))
        var t1 = create_task(test_tracing_add[enabled, 2](b))
        return await t0 + await t1

    var task = create_task(test_tracing_add_two_of_them[enabled](10, 20))
    print(task.wait())


def main() raises:
    test_tracing[1, True]()
"""
    out = _build_and_run(src)
    check("doubly-nested bracket-parametrized async composition, correct "
          "argument order -> 33 (not 32)", out == "33\n", detail=repr(out))


def test_trace_and_comptime_and_abort_inside_nested_async():
    """test_tracing.mojo's FULL real shape (modulo real Trace/TraceLevel
    stdlib imports, which pull in unrelated GPU/DeviceContext machinery
    out of scope here): `with Trace[level](s1, s2):` guarding the return
    (elided as a no-op, like BlockingScopedLock -- see gimple_codegen.py's
    `_ASYNC_NOOP_LOCK_GUARD_TYPES`), preceded by `comptime s1 = ...`/
    `comptime s2 = ...` declarations feeding it (a no-op fold -- see
    `_cpp_stmt`'s ComptimeVarStmt case), inside a try/except whose handler
    calls `abort(...)` (a bare CallExpr statement `_cpp_stmt` didn't
    recognize before this fix either)."""
    src = """\
def test_tracing[level: Int, enabled: Bool]() raises:
    @parameter
    async def test_tracing_add[enabled: Bool, lhs: Int](rhs: Int) -> Int:
        comptime s1 = "ENABLED: trace event 2" if enabled else "DISABLED: trace event 2"
        comptime s2 = "ENABLED: detail event 2" if enabled else "DISABLED: detail event 2"
        try:
            with Trace[level](s1, s2):
                return lhs + rhs
        except e:
            abort(String(e))

    @parameter
    async def test_tracing_add_two_of_them[enabled: Bool](a: Int, b: Int) -> Int:
        var t0 = create_task(test_tracing_add[enabled, 1](a))
        var t1 = create_task(test_tracing_add[enabled, 2](b))
        return await t0 + await t1

    with Trace[level]("c", "d"):
        var task = create_task(test_tracing_add_two_of_them[enabled](10, 20))
        print(task.wait())


def main() raises:
    test_tracing[1, True]()
"""
    out = _build_and_run(src)
    check("full test_tracing.mojo-shaped repro (Trace elision + comptime "
          "no-op + abort() + doubly-nested bracket async) -> 33",
          out == "33\n", detail=repr(out))


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
