#!/usr/bin/env python3
"""Self-host compile guard.

fire.py must compile *itself* to a fully linked binary with zero GCC errors,
zero internal compiler errors (ICEs), and no undefined symbols. This is the
`./fire.py --jit fire.py` path.

It must then also COMPILE: the produced binary is run over a two-line program
and the generated `.ci` is checked for real output. The second half is not
redundant with the first. A self-hosted compiler whose own analysis helper was
emitted as the `weak` "unavailable in compiled mode" stub links perfectly,
exits 0, and emits a `.ci` containing nothing but that diagnostic — so the
compile+link check above is structurally blind to the whole class, and a green
`selfhost` step coexisted with a `mojoc` that could compile nothing at all.
`run_produced_binary`'s docstring has the real instance.

build_executable() performs the same compile_to_gimple -> gcc -fgimple -> link
sequence the JIT uses and returns True only if every step exited 0.

There are two halves, and they fail for unrelated reasons. The static one
(`closure_coroutines_are_lowerable`) is a parse plus one AST transform over
every module of the self-host closure, and asks whether each generator in it
is a shape the compiled path can lower IN PLACE — because a module of this
closure that lowers its generators into a separate companion translation unit
compiles to an object whose coroutine symbols nothing defines, which is a
LINK failure in the self-host executable and nothing else. It runs first
because it costs milliseconds and the build it guards costs minutes. The
build half is the historical one.
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.abspath(__file__))

# The smallest input that exercises the whole self-hosted compile path: a
# module's worth of statements, a function, a call and a print. Two lines is
# enough and is deliberately the smallest thing that used to crash — see
# `run_produced_binary` below.
TWO_LINE = "x = 1\nprint(x)\n"


def build(td: str) -> str:
    """Self-compile fire.py into `td`, returning the binary path.

    build_executable writes mojo.{ci,o} + fire_runtime.o into the CWD, so the
    caller chdirs into a temp dir to keep the repo clean.
    """
    sys.path.insert(0, REPO)
    import fire
    main_src = os.path.join(REPO, "fire.py")
    src = open(main_src).read()
    out = os.path.join(td, "mojo_selfhost")
    ok = fire.build_executable(main_src, src, output=out)
    if not ok or not os.path.exists(out):
        return ""
    return out


# The AST attributes a node's children can hang off. A fixed list, walked
# explicitly, because there is no generic `__dict__` to iterate: every
# attribute name here is a source-level spelling the parser actually produces.
_CHILD_ATTRS = ('body', 'args', 'value', 'func', 'iterable', 'obj', 'left',
                'right', 'operand', 'target', 'elt', 'key', 'results',
                'statements', 'expr', 'handlers', 'finalbody', 'orelse',
                'ifs', 'decorator_list', 'defaults')


def _unlowered_coroutines(stmts: list) -> list:
    """Every generator / `async def` in `stmts`, by bare name.

    An explicit-stack walk, and deliberately NOT a generator: the thing this
    file exists to look for is a generator in the self-host closure, so a
    generator function here would be one more instance of it (see
    `mojo/middle/coro.py::_walk`'s own note for the same conversion, and
    `run_produced_binary`'s for the class). The depth cap is a backstop, not a
    shape anyone expects to hit: the deepest node in a parsed module body is a
    handful of levels down.
    """
    import fire_compiler as N
    found = []
    stack = [(s, 0) for s in reversed(stmts)]
    while stack:
        node, depth = stack.pop()
        if node is None or depth > 80:
            continue
        if isinstance(node, N.FunctionDef) and (node.is_generator
                                                or getattr(node, 'is_async', False)):
            found.append(node.name)
        for attr in _CHILD_ATTRS:
            sub = getattr(node, attr, None)
            if sub is None or isinstance(sub, (str, int, float, bool, bytes)):
                continue
            if isinstance(sub, list):
                for item in reversed(sub):
                    if not isinstance(item, (str, int, float, bool, bytes)):
                        stack.append((item, depth + 1))
            else:
                stack.append((sub, depth + 1))
    return found


def closure_coroutines_are_lowerable() -> bool:
    """No module of the self-host closure may contain a generator the
    compiled path cannot lower in place.

    Two backends lower a generator, and only one of them puts the definitions
    where a link can find them:

      * the A3 stack-switch lowering (`mojo/middle/coro.py`, the default)
        rewrites the generator into a plain function plus four tiny
        `_start`/`_resume`/`_value`/`_destroy` trampolines emitted into the
        module's OWN `.c`, so nothing else has to be compiled or linked;
      * the C++20 coroutine emitter puts them in a SEPARATE companion
        translation unit, `GimpleGen.generated_cpp`, which a build path has to
        compile and put on its link line.

    `build_stdlib_dylib.compile_module_to_c` — the per-module compile every
    dylib build, and therefore every self-host build, goes through — returns
    the `.c` and discards `generated_cpp`. So a module in this closure that
    the A3 lowering REFUSES compiles into an object referencing coroutine
    symbols nothing defines, and the self-host executable fails to LINK:

        Undefined symbols for architecture arm64:
          "__mojogen_build_stdlib_dylib__output_lock_start",
          "__mojogen_build_stdlib_dylib__output_lock_resume"

    which is how `mojoc`, `selfhost` and `bootstrap-stage2-cc` went red over
    one `@contextlib.contextmanager` (the A3 eligibility check refuses a
    DECORATED generator outright — `coro._eligible` returns
    `(False, 'decorated')` for it — measured).

    So the invariant to enforce is not "no `yield` anywhere" — this closure has
    generators on purpose and they lower fine — but "every one of them is a
    shape the A3 pass claims". That is exactly what running the pass and
    looking at what is left measures, and it is why this is a parse plus one
    AST transform rather than a grep: a grep cannot tell a generator the
    compiler can lower from one it cannot.

    Deliberately FIRST in `run()`, before the several-minute self-compile: this
    half is a pure static check, so a violation should be reported in
    milliseconds rather than after a build that is going to fail at link.
    """
    sys.path.insert(0, REPO)
    import cas
    import mojo.middle.coro as coro
    from fire_compiler import Parser, py_tokenize

    checked = 0
    offenders = []
    for name in cas.selfhost_inputs():
        if not name.endswith('.py'):
            continue
        path = os.path.join(cas.HERE, name)
        if not os.path.isfile(path):
            continue
        checked += 1
        with open(path, encoding='utf-8', errors='replace') as f:
            src = f.read()
        stmts = Parser(py_tokenize(src)).with_filename(path).parse_module()
        lowered, _meta = coro.lower(stmts)
        left = _unlowered_coroutines(lowered)
        if left:
            offenders.append((name, left))
    print(f"  self-host closure: {checked} modules, every generator/async "
          f"lowered in place: {not offenders}")
    for name, left in offenders:
        print(f"  ✗ {name}: the stack-switch lowering left "
              f"{', '.join(sorted(set(left)))} — its coroutine symbols would "
              f"be referenced but never defined (see "
              f"bugs/CODEGEN_dylib_module_path_drops_generated_cpp.md)")
    return not offenders


def run_produced_binary(exe: str, td: str) -> tuple:
    """Compile a two-line program with the freshly built self-hosted compiler
    and report `(exit_status, ci_bytes, unsupported_stub_hits)`.

    This is the end-to-end regression for the class of bug where the
    self-hosted binary *builds and links cleanly* — so `run()` above is
    green — and then cannot compile anything, because one of its own
    analysis helpers was emitted as the `weak` "unavailable in compiled
    mode" stub. A stub returns nothing, so every `for node in <stub>(...)`
    in the compiled compiler iterated zero times and the whole
    self-hosted codegen pass became a no-op. The result was a `.ci` file
    containing nothing but that diagnostic, repeated once per call, with
    exit status 0 — a silent wrong answer that no exit code reports and
    that the compile+link check is structurally blind to.

    The real instance: `mojo/middle/lambdareduce.py`'s `_walk` /
    `_walk_body` were `yield`/`yield from` generators, which do not
    survive self-compilation, so `./mojoc --dump-full` on a TWO-LINE
    program produced a 164-byte `.ci` that was entirely
    `"_walk: unavailable in compiled mode"`. `mojo/middle/coro.py`'s
    identically-named `_walk` had already been converted to an accumulator
    function for the same class of reason (see its docstring); this makes
    the two agree.

    Asserted on the CONTENT, not the exit status, for that reason.
    """
    prog = os.path.join(td, "probe.mojo")
    with open(prog, "w") as f:
        f.write(TWO_LINE)
    r = subprocess.run([exe, "--dump-full", prog], cwd=td,
                       capture_output=True, text=True, timeout=300)
    ci = os.path.join(td, "probe.ci")
    text = ""
    if os.path.exists(ci):
        with open(ci) as f:
            text = f.read()
    return (r.returncode, len(text),
            text.count("unavailable in compiled mode"))


def run() -> tuple:
    """(static_ok, build_ok). The static half first and separately, so its
    verdict is a line of its own in the tally rather than a `False` that
    reads like a build failure."""
    static_ok = closure_coroutines_are_lowerable()
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            exe = build(td)
            if not exe:
                return static_ok, False
            rc, nbytes, stubs = run_produced_binary(exe, td)
            print(f"  self-hosted compiler on a two-line program: "
                  f"exit={rc} ci_bytes={nbytes} stub_hits={stubs}")
            if rc != 0:
                print("  ✗ the self-hosted binary did not exit 0")
                return static_ok, False
            if stubs:
                print(f"  ✗ {stubs} of the self-hosted compiler's own "
                      "functions were emitted as 'unavailable in compiled "
                      "mode' stubs — its analysis passes are no-ops")
                return static_ok, False
            if nbytes < 200:
                print(f"  ✗ the self-hosted binary produced a {nbytes}-byte "
                      ".ci for a two-line program; expected real output")
                return static_ok, False
            return static_ok, True
        finally:
            os.chdir(cwd)


def main() -> int:
    try:
        static_ok, build_ok = run()
    except Exception as e:
        print(f"Results: 0 passed, 2 failed")
        print(f"✗ self-host build raised: {e}")
        return 1
    passed = (1 if static_ok else 0) + (1 if build_ok else 0)
    failed = 2 - passed
    print(f"Results: {passed} passed, {failed} failed")
    if not static_ok:
        print("✗ a module of the self-host closure holds a generator the "
              "compiled path cannot lower in place — its coroutine symbols "
              "would be referenced and never defined")
    if not build_ok:
        print("✗ self-host compile/link regressed (GCC error, ICE, undefined "
              "symbol, or the produced binary cannot compile)")
    if not build_ok:
        return 1
    print("✓ every generator in the self-host closure lowers in place, the "
          "self-host compiles + links clean, and the produced binary compiles "
          "a two-line program to real output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
