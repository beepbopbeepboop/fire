"""REAL behavioral test for generator codegen: compiles a Mojo generator
function's C output directly (doc/COROUTINE.html §5.5 cutover: this now
goes through the A3 stack-switch backend by default, gimple_gen_coro.py,
rather than the old cpp-path C++20-coroutine emitter -- MOJO_CORO=cpp
still selects the old path for the shapes it still uniquely covers), links
it against the small, do_imports=False-friendly A3 runtime object set
(mirrors test_coro_nested_async_capture.py's own build helper -- these
fixtures are self-contained, no stdlib imports, so there's no need to pay
build_stdlib_dylib's ~664-module link cost per test the way a full `fire.py
build`/driver.compile_program invocation would), RUNS the resulting binary,
and asserts on its ACTUAL stdout. Falls back to the cpp companion-unit link
(g++, mojo_async_runtime.cpp) for the rarer shape not yet stack-switch-
eligible.
"""
import os
import platform
import subprocess
import sys
import tempfile

import gimple_codegen
from build_config import find_gcc, find_gxx

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
GCC = find_gcc()
GXX = find_gxx()

_CORO_CTX_SRC = (os.path.join(RUNTIME_DIR, 'fire_coro_ctx_aarch64.S')
                 if platform.machine().lower() in ('arm64', 'aarch64')
                 else os.path.join(RUNTIME_DIR, 'fire_coro_ctx_generic.c'))

# Runtime object set for a stack-switch (A3) program: compiled ONCE, reused
# by every test in this file (these never change across test cases).
_SS_RUNTIME_SRCS = [
    os.path.join(RUNTIME_DIR, 'fire_runtime.c'),
    os.path.join(RUNTIME_DIR, 'fire_coro.c'),
    os.path.join(RUNTIME_DIR, 'fire_coro_gen.c'),
    os.path.join(RUNTIME_DIR, 'fire_async_sched.c'),
    _CORO_CTX_SRC,
]
_ss_runtime_objs_cache = None


from exec_budget import (COMPILE_TIMEOUT_S as SHARED_COMPILE_TIMEOUT_S,
                      LINK_TIMEOUT_S as SHARED_LINK_TIMEOUT_S,
                      RUN_TIMEOUT_S as SHARED_RUN_TIMEOUT_S)

# Per-child budgets. These programs are snippets that run in milliseconds, so
# these numbers are not a claim about how long they SHOULD take -- they only stop
# a wedged child. They were far too tight to survive a loaded machine: the 10 s
# one failed FOUR cases of this suite in a full gate at -j18 ("list_consumes_
# counter_generator", "param_generator_counter_start_count",
# "param_generator_single_param_direct_yield",
# "param_generator_unannotated_string_via_cross_call" -- all "timed out after
# 10 seconds") while this file passed 155/155 standalone. So a red gate here was
# load, not a miscompile.
#
# The real hang detector is the SUITE's per-job timeout. `gimplegenerators`
# carries no explicit one, so it now inherits DEFAULT_JOB_TIMEOUT_S (3600 s) --
# which the runner enforces by killing the job and reporting it as a FAILURE
# tagged [TIMEOUT], ~6x the slowest healthy test measured. These budgets only
# have to sit far inside that, which they now do.
COMPILE_TIMEOUT_S = SHARED_COMPILE_TIMEOUT_S
LINK_TIMEOUT_S = SHARED_LINK_TIMEOUT_S
RUN_TIMEOUT_S = SHARED_RUN_TIMEOUT_S

def _ss_runtime_objs(wd):
    global _ss_runtime_objs_cache
    if _ss_runtime_objs_cache is None:
        objs = []
        for i, src in enumerate(_SS_RUNTIME_SRCS):
            o = os.path.join(wd, f'rt{i}.o')
            r = subprocess.run([GCC, f'-I{RUNTIME_DIR}', '-c', '-o', o, src],
                                capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
            if r.returncode != 0:
                raise RuntimeError(f"compile of {src} failed: {r.stderr}")
            objs.append(o)
        _ss_runtime_objs_cache = objs
    return _ss_runtime_objs_cache


_PASS = 0
_FAIL = 0


def _build_generator_program(mojo_src: str) -> str:
    """Compile mojo_src (which must contain a supported generator) directly
    and link it against the A3 stack-switch runtime (or the cpp path, for a
    shape not yet stack-switch-eligible). Returns the exe path."""
    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(mojo_src)
    return _build_generator_program_from_code(c_code, cpp_code)


def _build_generator_program_from_code(c_code: str, cpp_code: str) -> str:
    """The half of _build_generator_program that takes ALREADY-generated
    code. Split out so a test whose source needed extra scaffolding on disk
    (a package, for a cross-module fixture) can hand in the compile
    product it produced itself instead of re-generating from a single
    string — the compile and the link have always been separate concerns and
    only the single-source convenience had fused them."""
    wd = tempfile.mkdtemp(prefix='mojo_gen_runner_')
    c_path = os.path.join(wd, 'prog.c')
    with open(c_path, 'w') as f:
        f.write(c_code)
    exe = os.path.join(wd, 'prog.exe')

    # A module can legitimately contain generators the two backends lower
    # DIFFERENTLY, and BOTH kinds of body land in the generated .cpp:
    # the A3 stack-switch pass emits `__mgco_<X>_*` (its runtime entry
    # points, `runtime/fire_coro_gen.c`), the cpp C++20-coroutine pass
    # emits the `_mojogen_<X>_*` C++ class family. A first real case is
    # `yield_from_cls_generator_method_delegation`, where A3 lowers the
    # delegating `@classmethod` generator and the cpp path lowers the
    # sibling it delegates to.
    #
    # The original gate -- `'__mgco_' in c_code` -- sent that module down
    # the pure-A3 branch, which links `prog.o` + the A3 runtime objects
    # and never compiles `prog_gen.cpp` at all. The cpp backend's own body
    # was silently dropped and the link failed with undefined
    # `_mojogen_<X>_*` symbols.
    #
    # So the two body kinds are detected SEPARATELY and the link gets
    # exactly what each needs: the .cpp is compiled whenever EITHER kind
    # is present; the A3 runtime objects are linked for an A3 body and
    # `fire_runtime.c` otherwise; and the link driver is g++ whenever a
    # cpp body is present (a C++ translation unit needs a C++ driver).
    # One code path covers pure-A3, pure-cpp and mixed modules, and
    # cannot silently drop a backend's bodies again.
    _blob = f"{c_code}\n{cpp_code}"
    _has_a3_bodies = '__mgco_' in _blob
    _has_cpp_bodies = '_mojogen_' in _blob
    if not (_has_a3_bodies or _has_cpp_bodies):
        raise RuntimeError(
            "expected a non-empty generated .cpp — this source doesn't "
            "actually contain a supported generator (neither stack-switch "
            "nor cpp path lowered it)")

    r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-w', '-c', '-o',
                        os.path.join(wd, 'prog.o'), c_path],
                        capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple compile of .c failed: {r.stderr}\n---\n{c_code}")
    objs = [os.path.join(wd, 'prog.o')]
    if _has_a3_bodies:
        objs += _ss_runtime_objs(wd)
    else:
        runtime_o = os.path.join(wd, 'fire_runtime.o')
        r = subprocess.run([GCC, f'-I{RUNTIME_DIR}', '-c', '-o', runtime_o,
                            os.path.join(RUNTIME_DIR, 'fire_runtime.c')],
                           capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if r.returncode != 0:
            raise RuntimeError(f"gcc compile of fire_runtime.c failed: {r.stderr}")
        objs.append(runtime_o)
    if _has_cpp_bodies:
        cpp_path = os.path.join(wd, 'prog_gen.cpp')
        with open(cpp_path, 'w') as f:
            f.write(cpp_code)
        r = subprocess.run([GXX, '-std=c++20', f'-I{RUNTIME_DIR}', '-c', '-o',
                            os.path.join(wd, 'prog_gen.o'), cpp_path],
                           capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if r.returncode != 0:
            raise RuntimeError(f"g++ compile of .cpp failed: {r.stderr}")
        objs.append(os.path.join(wd, 'prog_gen.o'))
    if _has_cpp_bodies:
        import fire
        r = fire.link_executable(objs, exe, cxx=True)
    else:
        r = subprocess.run([GCC, '-o', exe, *objs], capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f"link failed: {r.stderr}")
    os.chmod(exe, 0o755)
    return exe


# ── A FOREIGN module's A3-lowered generator, consumed from a cpp-path ──────
#
# Two halves of one feature, neither observable without the other:
#
#   1. `mojo/middle/coro.py`'s `register` used to file a lowered generator
#      only into the per-bare-name `_generator_api`, never into the
#      whole-program `_generator_home_api` that
#      `_cpp_resolve_generator_call_api` searches for its
#      `<module>.<gen_fn>` shape. So a generator body of ONE module could
#      not construct a handle to a generator of ANOTHER at all, whenever
#      that generator happened to be A3-eligible (`publish_a3_generators`,
#      mojo/backend_gimple/emit_resolve.py). Both backends expose the SAME
#      four-symbol `{base}_start/_resume/_value/_destroy` ABI, so only the
#      registry entry was missing.
#   2. `next(<handle>)` was supported but `for x in <handle>:` was not: it
#      fell through to a generic C++ range-for over the bare handle text and
#      g++ rejected it with "'begin' was not declared in this scope"
#      (`MojoGenerator *` is an opaque runtime handle).
#
# Real: c_common/tables.py's `read_table` consuming
# `strutil._iter_significant_lines(infile)` — see
# bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md.

_FOREIGN_PKG_FILES = {
    '__init__.py': '',
    # A generator the A3 (stack-switch) backend lowers: no kwonly params, no
    # decorators, scalar yields. That it lowers via A3 rather than the cpp
    # path is the point of the fixture.
    'foreign.py': ("def counter(n):\n"
                   "    i = 0\n"
                   "    while i < n:\n"
                   "        yield i\n"
                   "        i = i + 1\n"),
}


def _build_foreign_package_run(entry_rel, entry_src, cwd):
    """Write the package, compile `entry_rel` with do_imports=True, build
    (C object + C++20 coroutine unit + the A3 runtime objects), run, and
    return (compiled_stdout, cpython_stdout)."""
    os.makedirs(os.path.join(cwd, 'fpp'), exist_ok=True)
    for rel, src in _FOREIGN_PKG_FILES.items():
        with open(os.path.join(cwd, 'fpp', rel), 'w') as f:
            f.write(src)
    entry = os.path.join(cwd, 'fpp', entry_rel)
    with open(entry, 'w') as f:
        f.write(entry_src)
    cp = subprocess.run([sys.executable, '-m', 'fpp.' + entry_rel[:-3]],
                        cwd=cwd, capture_output=True, text=True, timeout=60)
    cpython_stdout = cp.stdout
    c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(
        entry_src, do_imports=True, filename=entry)
    if not cpp_code:
        raise RuntimeError(
            "expected a non-empty generated .cpp — this source's own "
            "generator should NOT be A3-eligible (the kwonly parameter is "
            "what forces it down the cpp path)")
    exe = _build_generator_program_from_code(c_code, cpp_code)
    out = subprocess.run([exe], capture_output=True, timeout=10).stdout.decode()
    return out, cpython_stdout


def _test_foreign_a3_generator_handle(name, entry_src, want):
    """Compile+run the package fixture and compare against CPython on the
    very same files. `want` is asserted against CPython's own output first,
    so a fixture that drifted from its documented expectation fails as a
    FIXTURE bug and not as a compiler regression."""
    global _PASS, _FAIL
    try:
        wd = tempfile.mkdtemp(prefix='mojo_gen_fpp_')
        got, cpy = _build_foreign_package_run('main.py', entry_src, wd)
    except subprocess.TimeoutExpired as e:
        print(f"TIMEOUT {name}: {e}")
        _FAIL += 1
        return
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1
        return
    if cpy != want:
        print(f"FAIL  {name}: CPython baseline is not {want!r} (got {cpy!r}) "
              f"— fixture is wrong, not the compiler")
        _FAIL += 1
        return
    if got == cpy:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}: compiled stdout {got!r} != CPython {cpy!r}")
        _FAIL += 1


def _foreign_a3_generator_handle_next():
    # `next()` on a handle built from ANOTHER module's A3-lowered generator.
    # `consume` is itself a GENERATOR that consumes the foreign handle to
    # exhaustion.
    #
    # The consumer's own kwonly parameter is what keeps IT off the A3 path,
    # so it really is the cpp C++20-coroutine emitter doing the driving while
    # `foreign.counter` really is A3-lowered — the exact split in
    # c_common/tables.py's read_table/strutil pair. Before the fix the
    # module did not compile at all: `a call to unresolved callee
    # 'next(...)'`, because `_generator_home_api` held no entry for
    # `foreign.counter`.
    #
    # The default has to be one the A3 gate REJECTS. It used to be `start=0`,
    # which was enough while the gate refused any generator with a keyword-only
    # parameter at all; the gate now asks whether each omitted argument can be
    # filled with the right value (`coro._unrepresentable_kwonly`), and an
    # int literal can, so `consume` became A3-eligible and this fixture
    # silently stopped being the thing it says it is. A list literal is
    # deliberately not admitted (`_default_is_faithful_literal`), and it is
    # never read by the body.
    _test_foreign_a3_generator_handle(
        "foreign_a3_generator_handle_next",
        "from . import foreign\n"
        "\n"
        "def consume(n, *, start=[]):\n"
        "    g = foreign.counter(n)\n"
        "    yield next(g)\n"
        "\n"
        "def main():\n"
        "    print(sum(consume(4)))\n"
        "\n"
        "main()\n",
        "0\n")


def _foreign_a3_generator_handle_for_loop():
    # The `for` half of consuming one handle to exhaustion. `next(g)` and
    # `yield from g` already drove `{base}_resume`/`{base}_value`, but the
    # loop did not: it fell through to a generic C++ range-for over the bare
    # `MojoGenerator *` text and g++ rejected it with "'begin' was not
    # declared in this scope". Asserted on the binary's real output, so a
    # future regression cannot pass by merely compiling — and the `* 10`
    # plus the sum exercise the VALUE each resume produced, not just the
    # iteration count (a loop that ran zero times, or ran once, sums
    # differently).
    _test_foreign_a3_generator_handle(
        "foreign_a3_generator_handle_for_loop",
        "from . import foreign\n"
        "\n"
        "def consume(n, *, start=[]):\n"
        "    g = foreign.counter(n)\n"
        "    for rest in g:\n"
        "        yield rest * 10\n"
        "\n"
        "def main():\n"
        "    print(sum(consume(4)))\n"
        "\n"
        "main()\n",
        "60\n")


def test_generator_stdout(name: str, mojo_src: str, expected_stdout: str):
    global _PASS, _FAIL
    try:
        exe = _build_generator_program(mojo_src)
        out = subprocess.run([exe], capture_output=True, timeout=RUN_TIMEOUT_S).stdout.decode()
        if out == expected_stdout:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected {expected_stdout!r}, got {out!r}")
            _FAIL += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1


def test_generator_c_compiles(name: str, mojo_src: str):
    """Emit the generator module's C and assert it passes `gcc -fgimple
    -fsyntax-only` -- a regression guard for shapes that used to be
    A3-eligible but emitted BROKEN C (a miscompile), and are now honestly
    refused (falling through to the cpp path) instead."""
    global _PASS, _FAIL
    try:
        c_code, _cpp = gimple_codegen.compile_to_gimple_with_cpp(mojo_src)
        wd = tempfile.mkdtemp(prefix='mojo_gen_cc_')
        cp = os.path.join(wd, 'prog.c')
        with open(cp, 'w') as f:
            f.write(c_code)
        r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-w',
                            '-fsyntax-only', cp],
                           capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if r.returncode == 0:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: gcc -fgimple errors:\n{r.stderr}")
            _FAIL += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1


def test_generator_refused(name: str, mojo_src: str, expected_substr: str):
    """Assert this generator shape is honestly REFUSED at compile time
    (raises with a message containing `expected_substr`) rather than
    emitting C that links against a symbol that does not exist, miscompiles,
    or silently skips work."""
    global _PASS, _FAIL
    try:
        gimple_codegen.compile_to_gimple_with_cpp(mojo_src, do_imports=False)
        print(f"FAIL  {name}: expected a refusal, but it compiled")
        _FAIL += 1
    except Exception as e:
        if expected_substr in str(e):
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: refused with the wrong reason: {e}")
            _FAIL += 1


def _cpython_stdout(py_src: str) -> str:
    wd = tempfile.mkdtemp(prefix='mojo_gen_cpy_')
    p = os.path.join(wd, 'ref.py')
    with open(p, 'w') as f:
        f.write(py_src)
    r = subprocess.run(['python3', p], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"the CPython reference program itself failed: {r.stderr}")
    return r.stdout


def test_generator_matches_cpython(name: str, mojo_src: str, cpython_src: str):
    """Compile+link+RUN the Mojo program and require its stdout to equal
    the stdout CPython produces for the reference twin -- the oracle
    measured at test time rather than a constant, so a fixture that drifts
    cannot silently start asserting this compiler's own (wrong) answer.

    Used for the `async for` / async-generator shapes, where the failure
    mode this file most has to catch is a SILENT wrong value (a dropped
    loop body, or a wait-descriptor bound as the loop variable) that
    `test_generator_stdout`'s hand-written expected string would happily
    have been written to match after the fact."""
    global _PASS, _FAIL
    try:
        want = _cpython_stdout(cpython_src)
        exe = _build_generator_program(mojo_src)
        got = subprocess.run([exe], capture_output=True, timeout=10).stdout.decode()
        if got == want:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: CPython {want!r}, compiled {got!r}")
            _FAIL += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1


def _foreign_cpp_module_global_value():
    # A MODULE-LEVEL CONSTANT of one module, read as a VALUE in a cpp-path
    # coroutine body of another (`div = foreign.SEP`, `foreign.SEP.endswith`)
    # — real: scriptutil.py's `iter_marks` doing `div = os.linesep` beside
    # `end = f'{mark}{os.linesep}'`, and `track_progress_compact`'s
    # `last.endswith(os.linesep)`.
    #
    # Two independent failures hid behind this one shape, and the second is
    # why the test asserts the compiled BINARY's output rather than "it
    # compiles":
    #
    #   1. `_cpp_expr`'s member-read case stubbed any `<module marker>.<name>`
    #      read to a diagnosed `0` — a WRONG ANSWER, not an error, so
    #      `div` became `''` where CPython has `'|'`. Anywhere that did not
    #      also trip a type check, the generator compiled, ran, exited 0 and
    #      printed the wrong text.
    #   2. With the real value read, the module's OWN field triple types it
    #      `char *`, so `div` binds a `char *` local and the generator's
    #      yields now agree — before, `div` took the `int64_t` default that a
    #      `self`-less MemberExpr used to fall through to, disagreed with its
    #      sibling `end`, and the whole generator was refused outright with
    #      "every `yield` must ... agree on one scalar type". That refusal is
    #      what kept this shape off the compiled path entirely until now.
    #
    # The `*, start=[]` default is the A3 gate's rejection trigger (see
    # `_foreign_a3_generator_handle_next`), so the body really is compiled by
    # the cpp C++20-coroutine emitter rather than the A3 stack-switch pass.
    T_FOREIGN_CPP_PKG_FILES = {
        '__init__.py': '',
        # A STRING constant and an INT one, plus an EMPTY string, so the
        # comparison/`not`/length cases below can tell a real read from a
        # stubbed 0: `0 == '|'` is False, `len(0)` is not 1.
        'foreign.py': ("SEP = '|'\n"
                       "EMPTY = ''\n"
                       "WIDTH = 4\n"),
    }
    _saved_pkg_files = _FOREIGN_PKG_FILES
    try:
        globals()['_FOREIGN_PKG_FILES'] = T_FOREIGN_CPP_PKG_FILES
        # A local bound to the read, yielded beside a string sibling: the
        # mixed-kind refusal fires without the fix, and with only the value
        # read fixed it would print `''`.
        _test_foreign_a3_generator_handle(
            "cpp_coroutine_body_reads_foreign_module_constant",
            "from . import foreign\n"
            "\n"
            "def lines(prefix, *, start=[]):\n"
            "    div = foreign.SEP\n"
            "    end = f'{prefix}{foreign.SEP}'\n"
            "    yield end\n"
            "    yield div\n"
            "\n"
            "def main():\n"
            "    for s in lines('a'):\n"
            "        print(repr(s))\n"
            "\n"
            "main()\n",
            "'a|'\n'|'\n")
        # The truthiness/comparison/length/arithmetic half. Every yield is
        # wrapped in a one-or-zero ternary because this model gives a
        # generator ONE value-slot type: yielding the `==` result directly
        # would widen to `char *` and the four yields would disagree — a
        # genuine mixed-kind generator, not this test's subject.
        #
        # `_cpp_expr_static_ctype` answers the same question the value read
        # does, so `foreign.SEP` in a CONDITION must be decided on the
        # string's emptiness rather than on a null pointer. That is what
        # makes the first case discriminating: the stub's `0` is ALSO
        # falsy, but as a NULL it says `''` where the real `'|'` says true.
        _test_foreign_a3_generator_handle(
            "cpp_coroutine_body_compares_foreign_module_constant",
            "from . import foreign\n"
            "\n"
            "def probe(*, start=[]):\n"
            "    yield 1 if foreign.SEP else 0\n"
            "    yield 1 if foreign.SEP == '|' else 0\n"
            "    yield len(foreign.SEP)\n"
            "    yield foreign.WIDTH * 2\n"
            "\n"
            "def main():\n"
            "    for s in probe():\n"
            "        print(s)\n"
            "\n"
            "main()\n",
            "1\n1\n1\n8\n")
    finally:
        globals()['_FOREIGN_PKG_FILES'] = _saved_pkg_files


def _cpp_for_over_callable_local_is_named():
    # `for x in <call through a callable-valued local/parameter>` must name
    # the callee. The refusal it used to raise was a flat
    # "unsupported for-loop iterable type: CallExpr", which named neither
    # the call nor the reason — so the SAME blocker read as five unrelated
    # gaps (c_common/tables.py `read_table`, c_analyzer/__init__.py
    # `check_all`, c_common/fsutil.py `glob_tree`/`_walk_tree`,
    # bugs/CODEGEN_generator_function_Lib_glob.md's `_iglob`,
    # bugs/CODEGEN_generator_function_Lib_os.md's `walk`) and each doc had to
    # re-derive what to do about it. It stays a refusal — the callee's
    # return type genuinely is not knowable in this body model — but now says
    # which call and what would unblock it.
    #
    # The default `walk=os.walk` is the real shape: a kw-only parameter
    # defaulting to the function itself, which is also what keeps the
    # generator off the A3 path (see `_foreign_a3_generator_handle_next`).
    test_generator_refused(
        "cpp_for_over_callable_param_names_the_callee", """\
def walk_tree(root, *, walk=len, start=[]):
    for entry in walk(root):
        yield entry

def main():
    print(sum(walk_tree('a')))
""", "callable-valued local/parameter 'walk(...)'")
    # The negative half: an iterable this emitter DOES support must keep its
    # own path, and a call this emitter CAN resolve must never reach the new
    # branch — both would be silent behaviour changes if the gate were too
    # wide. `sum` is the resolved-callee case for the second.
    test_generator_stdout("cpp_for_over_callable_param_leaves_resolved_callees_alone", """\
def rows(xs, *, start=[]):
    for x in xs:
        yield x * 2

def main():
    print(sum(rows([1, 2, 3])))
""", "12\n")


def _cpp_coroutine_builtin_module_constant():
    # A constant read off a module MARKER that is NEVER INLINED — `os` and
    # `signal` bind to an opaque marker with no compiled body in this TU, so
    # there is no `_module_globals['os']` field to read and no emitted struct
    # to name. Real: scriptutil.py's `iter_marks` (`div = os.linesep` beside
    # `end = f'{mark}{os.linesep}'`), bugs/COMPILE_FAIL_Tools_c-analyzer_c_
    # common_scriptutil.md.
    #
    # Those few constants are known BY VALUE instead (fixed by the OS ABI
    # and by os.py's own literals). The table is SHARED with the ordinary
    # GIMPLE path, which already read them correctly — and that sharing is
    # the point of the test's shape: the generator body and the ORDINARY
    # function in the same program read the same constant, so the two
    # backends cannot answer differently without one of the two lines going
    # wrong. When the coroutine emitter had its own stub-to-0, the ordinary
    # line still printed '/' while the generator line printed ''.
    #
    # Asserted against CPython run on a reference twin AT TEST TIME, because
    # the failure mode is a silent wrong value on both halves.
    _mojo = (
        "import os\n"
        "import signal\n"
        "\n"
        "def strings(*, start=[]):\n"
        "    div = os.linesep\n"
        "    end = f'x{os.linesep}'\n"
        "    yield end\n"
        "    yield div\n"
        "\n"
        "def numbers(*, start=[]):\n"
        "    yield signal.SIGTERM + 0\n"
        "    yield signal.SIGKILL * 2\n"
        "    yield 1 if signal.SIGPIPE else 0\n"
        "    yield 1 if os.sep else 0\n"
        "    yield 1 if os.pathsep else 0\n"
        "\n"
        "def ordinary():\n"
        "    print(repr(os.linesep))\n"
        "    print(os.pathsep)\n"
        "    print(signal.SIGTERM)\n"
        "\n"
        "def main():\n"
        "    for s in strings():\n"
        "        print(repr(s))\n"
        "    for n in numbers():\n"
        "        print(n)\n"
        "    ordinary()\n"
        "\n"
        "main()\n")
    # The reference twin drops only the A3-gate triggers (`*, start=[]`);
    # everything the compiled program computes is identical source.
    _cpy = (_mojo.replace("def strings(*, start=[]):", "def strings():")
                .replace("def numbers(*, start=[]):", "def numbers():"))
    test_generator_matches_cpython(
        "cpp_coroutine_body_reads_marker_module_constant", _mojo, _cpy)


def _cpp_coroutine_exc_ctor_value():
    # `e = ValueError('boom')` then `raise e` — real: scriptutil.py's
    # `_iter_filenames` (`onempty = Exception('no filenames provided')` /
    # `raise onempty`), which refused the whole generator with "a call to
    # unresolved callee 'Exception(...)' is not supported in a compiled
    # generator/coroutine body".
    #
    # What the local HOLDS is unchanged by this: this model's one exception
    # representation is the message, which is what `_cpp_raise_stmt`'s own
    # `raise <handler variable>` case already throws and what the ordinary
    # (non-coroutine) GIMPLE path already produces for the same source
    # (`_lower_opaque_ctor` returns the lone string argument, so `e` there
    # is a `char *`). So the fix is an emission site plus the matching local
    # type, not a second representation. The type tag is consequently the
    # existing untagged(0) lenient match — the same one a
    # constructed-then-raised exception gets on the ordinary path, where the
    # tag set at construction is not carried onto the variable at all.
    #
    # Asserted against the BINARY's output, not just "it compiles": the
    # failure this shape had was a compile refusal, but a `int64_t`-typed
    # local would have compiled and thrown an integer as the message.
    test_generator_stdout("cpp_coroutine_exception_ctor_as_value", """\
def probe(*, start=[]):
    e = ValueError('boom')
    raise e
    yield 'never'

def main():
    try:
        for s in probe():
            print(s)
    except ValueError as err:
        print('caught', err)
""", "caught boom\n")
    # The no-argument form: `TypeError()` is legal Python and the message is
    # the empty string, which is what the emitted `char *` empty literal
    # carries. Kept because it is the shape whose typing needs no argument to
    # infer from — the one place a "just use args[0]" shortcut is wrong.
    test_generator_stdout("cpp_coroutine_exception_ctor_as_value_no_arg", """\
def probe(*, start=[]):
    e = TypeError()
    raise e
    yield 'never'

def main():
    try:
        for s in probe():
            print(s)
    except TypeError as err:
        print('caught', repr(str(err)))
""", "caught ''\n")


def run_next_method_tests():
    test_generator_stdout("generator_next_method_values_and_shared_cursor", """\
def counter():
    yield 10
    yield 20
    yield 30

def main():
    g = counter()
    print(g.__next__())
    print(next(g))
    print(g.__next__())
""", "10\n20\n30\n")

    test_generator_stdout("generator_next_method_string_values", """\
def words():
    yield "first"
    yield "second"

def main():
    g = words()
    print(g.__next__())
    print(g.__next__())
""", "first\nsecond\n")

    test_generator_stdout("generator_next_method_exhaustion", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(1)
    print(g.__next__())
    try:
        print(g.__next__())
    except StopIteration:
        print("done")
    try:
        print(g.__next__())
    except StopIteration:
        print("still done")
    empty = counter(0)
    try:
        print(empty.__next__())
    except StopIteration:
        print("empty")
""", "0\ndone\nstill done\nempty\n")

    test_generator_stdout("generator_next_method_exception_after_yield", """\
def broken():
    yield 7
    raise ValueError("boom")

def main():
    g = broken()
    print(g.__next__())
    try:
        print(g.__next__())
    except StopIteration:
        print("wrong exception")
    except ValueError as e:
        print(e)
    print("caught")
""", "7\nboom\ncaught\n")

    test_generator_stdout("generator_next_method_exception_before_yield", """\
def broken():
    raise KeyError("early")
    yield 1

def main():
    g = broken()
    try:
        print(g.__next__())
    except StopIteration:
        print("wrong exception")
    except KeyError as e:
        print(e)
    print("caught")
""", "early\ncaught\n")

    test_generator_stdout("generator_next_method_receiver_evaluated_once", """\
def argument():
    print("argument")
    return 42

def single(value):
    print("resumed")
    yield value

def main():
    print(single(argument()).__next__())
""", "argument\nresumed\n42\n")


def run_mixed_yield_kind_tests():
    # ── Mixed `yield` value kinds ──────────────────────────────────────
    # A generator whose yields disagree on the scalar type (int then str,
    # int then double, bool then int) has ONE value slot in the compiled
    # model, typed from the yields as a whole. The two type-inference passes
    # (the mojo-side walker and the C++ generator header builder) each
    # widened silently — one said int64_t, the other double/_Bool — and the
    # disagreement SEGFAULTED the compiler. Each pass now checks that all
    # yields agree, so the shape is REFUSED with a message naming the rule
    # and the module falls back to interpreting from source, which produces
    # the correct answer (see the note above these throw/close tests).
    test_generator_refused("generator_mixed_yield_kinds_int_str", """\
def gen():
    yield 1
    yield "a"
""", "all values must agree on one scalar type")

    # The same rule, in the other order and across the other two kinds: the
    # check is on the SET of kinds, not on a particular pair.
    test_generator_refused("generator_mixed_yield_kinds_str_int", """\
def gen():
    yield "a"
    yield 1
""", "all values must agree on one scalar type")

    test_generator_refused("generator_mixed_yield_kinds_int_double", """\
def gen():
    yield 1
    yield 2.5
""", "all values must agree on one scalar type")

    # `_Bool` and int64_t share one 64-bit slot, so this one is NOT a
    # disagreement and must keep compiling: the check is on genuinely
    # incompatible kinds, not on "more than one kind". (It prints `1` for the
    # `True` — a pre-existing repr nuance of the shared slot, and no crash;
    # not what this group is about.)
    test_generator_c_compiles("generator_yield_kinds_bool_int_share_slot", """\
def gen():
    yield True
    yield 7
""")

    # A single kind is untouched by the check — including all three kinds on
    # their own, so the refusal cannot be satisfied by refusing everything.
    test_generator_c_compiles("generator_single_yield_kind_int", """\
def gen():
    yield 1
    yield 2
""")
    test_generator_c_compiles("generator_single_yield_kind_str", """\
def gen():
    yield "a"
    yield "b"
""")
    test_generator_c_compiles("generator_single_yield_kind_double", """\
def gen():
    yield 1.5
    yield 2.5
""")
    test_generator_c_compiles("generator_single_yield_kind_bool", """\
def gen():
    yield True
    yield False
""")

    # ── A yield whose value kind could NOT BE RESOLVED ──────────────────
    # The checks above are on the SET of kinds, and every one of them
    # explicitly SKIPS an unresolved one (`kinds - {'d', None}`). So a yield
    # the static scan could not type, sitting beside one it could, sailed
    # through all of them and landed on the `int64_t` default — the identical
    # silent truncation the CALL-SITE half of the same one-slot contract was
    # fixed for (bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md).
    # Both of these compiled, ran, exit 0, and printed wrong values:
    #   `for i, x in enumerate(xs): yield i; yield "s"`  -> `(null)` then `s`
    #   `for k, v in d.items(): yield v; yield "s"`      -> nothing at all
    # The hole is a HOLE beside a slot that is NOT int64_t; see
    # `_generator_value_kind`'s own note for why `int64_t` is excluded from
    # the refusal (an unresolved expression is read as an `int64_t` anyway,
    # so refusing there would disqualify ordinary untyped generators).
    test_generator_refused("generator_unresolvable_yield_kind_beside_str", """\
def gen(xs):
    for i, x in enumerate(xs):
        yield i
        yield "s"
""", "all values must agree on one scalar type")

    test_generator_refused("generator_unresolvable_yield_kind_beside_double", """\
def gen(pairs):
    for a, b in pairs:
        yield a
        yield 2.5
""", "all values must agree on one scalar type")

    test_generator_refused("generator_unresolvable_yield_kind_beside_dict_value", """\
def gen(d):
    for k, v in d.items():
        yield v
        yield "s"
""", "all values must agree on one scalar type")

    # And the excluded half must keep compiling — an unresolvable yield
    # beside an int one is NOT a refusal, because the slot the hole would get
    # is the slot the int kind picks. Both of these are genuinely all-int
    # and both compiled and printed correctly before the check existed; a
    # blanket `None in kinds` refusal took them out of the compiled path.
    test_generator_c_compiles("generator_unresolvable_yield_kind_beside_int", """\
def gen():
    yield 1
    [x] = [42]
    yield x
""")

    test_generator_c_compiles("generator_unresolvable_yield_kind_beside_int_len", """\
def gen():
    var ba = bytearray()
    ba.append(5)
    yield ba[0]
    yield len(ba)
""")

    # Mixed kinds reached through `yield from` are caught by the same check.
    # A `yield from` re-yields everything the sub-generator yields, so the
    # sub-generator's kind lands in the OUTER generator's single value slot
    # exactly as if it had been written out. That kind is resolved per module
    # (`_register_generator_value_kinds`) and folded into the agreement check:
    # without it, `yield from <int sub>` + `yield "a"` SEGFAULTED and
    # `yield from <str sub>` + `yield 1` printed a raw address.
    test_generator_refused("generator_mixed_yield_kinds_yield_from_int_str", """\
def sub():
    yield 1

def gen():
    yield from sub()
    yield "a"
""", "all values must agree on one scalar type")

    test_generator_refused("generator_mixed_yield_kinds_yield_from_str_int", """\
def sub():
    yield "s"

def gen():
    yield from sub()
    yield 1
""", "all values must agree on one scalar type")

    # …and a delegation whose kind AGREES must still compile in both
    # directions, so the check cannot be satisfied by refusing every
    # `yield from`.
    test_generator_stdout("generator_yield_from_same_kind_int", """\
def sub():
    yield 1
    yield 2

def gen():
    yield from sub()
    yield 3

def main():
    g = gen()
    print(next(g))
    print(next(g))
    print(next(g))

main()
""", "1\n2\n3\n")

    # A string-delegating generator used to be typed 'i' (the delegation
    # contributed no kind, so the default won) and printed its values as raw
    # addresses; it now takes the sub-generator's kind.
    test_generator_stdout("generator_yield_from_same_kind_string", """\
def sub():
    yield "a"
    yield "b"

def gen():
    yield from sub()
    yield "c"

def main():
    g = gen()
    print(next(g))
    print(next(g))
    print(next(g))

main()
""", "a\nb\nc\n")


def run_lambda_capture_tests():
    # Lambdas that CLOSE over the enclosing function are exercised in
    # test_gimple_runner.py (gimple_lambda_capture_*): they need no generator,
    # so this suite's generator-only harness cannot build them. What matters
    # here is that the shapes WITHOUT an enclosing-local read are untouched by
    # the env-based capture work.
    #
    # A module global is not a capture — a lifted lambda reads those through
    # `_root_globals` — so it stays a bare function pointer.
    test_generator_c_compiles("lambda_reading_module_global", """\
d = {"a": 1}
f = lambda k: d[k]
print(f("a"))
""")

    # A lambda touching only its own parameters and locals.
    test_generator_c_compiles("lambda_without_capture", """\
def main():
    f = lambda v: v * 2
    print(f(3))

main()
""")


def test_generator_a3_ineligible(name: str, mojo_src: str, gen_name: str,
                                 expected_substr: str):
    """Assert the A3 stack-switch backend refuses `name` with a reason
    containing `expected_substr`, i.e. the generator is left untouched and
    falls through to the C++20-coroutine path.

    Asserting on the A3 DECISION rather than on a whole-module compile is
    deliberate: the two backends have different kwonly policies (the cpp
    path has never had a kwonly gate for a sync generator, so it accepts
    `*, extra=[1, 2]` and pads the omitted argument with `_default_
    expr_to_pair`'s typed-`0` fallback). A whole-module compile would
    therefore report the cpp backend's answer and never reach the gate
    under test.
    """
    global _PASS, _FAIL
    import fire_compiler
    import mojo.middle.coro as _coro
    try:
        stmts = fire_compiler.Parser(
            fire_compiler.py_tokenize(mojo_src)).parse_module()
        _coro.lower(stmts)      # populates the registries _eligible reads
        for s in stmts:
            if (isinstance(s, fire_compiler.FunctionDef) and s.name == gen_name):
                ok, why = _coro._eligible(s)
                if ok:
                    print(f"FAIL  {name}: A3 accepted it")
                    _FAIL += 1
                elif expected_substr in why:
                    print(f"PASS  {name}")
                    _PASS += 1
                else:
                    print(f"FAIL  {name}: refused for the wrong reason: {why}")
                    _FAIL += 1
                return
        print(f"FAIL  {name}: no such generator in the fixture")
        _FAIL += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1


def run_callable_param_tests():
    # Cluster: bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md --
    # "the real blocker is INVOKING a kw-only parameter as a callee", the
    # shape `Tools/c-analyzer/c_common/fsutil.py`'s `walk_tree(root, *,
    # walk=_walk_tree)` / `iter_files_by_suffix(..., *, _iter_files=
    # iter_files)` are built from. Each of these compiled-and-ran BEFORE the
    # fix only by accident of a different bug: the omitted `walk=` argument
    # was padded with `('int', '0')`, i.e. a NULL function pointer, so the
    # body called address 0 (SIGSEGV, exit 139, no diagnostic) -- the
    # minimal repro the bug doc quotes. So the FIRST assertion here is not
    # "it does not crash", it is that CPython's exact text comes out.
    test_generator_stdout("kwonly_callable_default_for_loop_over_result", """\
def leaf(root):
    yield root + "/a"
    yield root + "/b"

def consume(root, *, walk=leaf):
    for f in walk(root):
        yield f

def main():
    for x in consume("/r"):
        print(x)

main()
""", "/r/a\n/r/b\n")

    # The same shape consumed by `yield from` rather than a for-loop. The
    # value slot is what differs: a `yield from` through a callable-valued
    # parameter contributed an UNKNOWN kind to `_generator_value_kind`, so
    # the generator kept the `int64_t` default and every string came out as
    # its own pointer, printed in decimal (verified before the fix:
    # `4377024576\n4377024592`).
    test_generator_stdout("kwonly_callable_default_yield_from", """\
def leaf(root):
    yield root + "/a"
    yield root + "/b"

def consume(root, *, walk=leaf):
    yield from walk(root)

def main():
    for x in consume("/r"):
        print(x)

main()
""", "/r/a\n/r/b\n")

    # A caller that OVERRIDES the parameter. The compiled answer is typed
    # from the DECLARED DEFAULT (that is the only callee identity a
    # signature can carry), so this pins the behaviour rather than leaving
    # it undefined: both call sites run, each with its own generator's
    # values, in order.
    test_generator_stdout("kwonly_callable_default_overridden_at_call_site", """\
def leaf(root):
    yield root + "/a"

def other(root):
    yield root + "/X"

def consume(root, *, walk=leaf):
    for f in walk(root):
        yield f

def main():
    for x in consume("/r"):
        print(x)
    for x in consume("/r", walk=other):
        print(x)

main()
""", "/r/a\n/r/X\n")

    # Positional-with-default, not keyword-only: same callable-value
    # representation, and it was NULL there too.
    test_generator_stdout("positional_callable_default_iterated", """\
def leaf(root):
    yield root + "/a"

def consume(root, walk=leaf):
    for f in walk(root):
        yield f

def main():
    for x in consume("/r"):
        print(x)

main()
""", "/r/a\n")

    # The eligibility gate replaced a blanket `kwonly params (v0)` refusal
    # with "is every keyword-only default faithfully lowerable?". These two
    # are the answers it must still give NO on, because admitting either
    # would trade the whole-module fallback (gen_module interprets the
    # module from source, which is always right) for a compiled NULL
    # container pointer: `calls_shared._default_expr_to_pair` pads anything
    # it cannot represent with a typed `0`, which is not a list.
    test_generator_a3_ineligible("kwonly_default_container_literal_refused", """\
def leaf(root):
    yield root

def consume(root, *, extra=[1, 2]):
    for f in leaf(root):
        yield f
""", "consume", "kwonly params (v0): ['extra']")
    test_generator_a3_ineligible("kwonly_default_computed_refused", """\
def leaf(root):
    yield root

def consume(root, *, extra=len("ab")):
    for f in leaf(root):
        yield f
""", "consume", "kwonly params (v0): ['extra']")
    # ...and a faithful one IS accepted, so the gate is not simply always
    # saying no (the two refusals above are only meaningful next to this).
    test_generator_stdout("kwonly_default_literal_still_accepted", """\
def leaf(root):
    yield root + "/a"

def consume(root, *, extra=0, name=None):
    for f in leaf(root):
        yield f

def main():
    for x in consume("/r"):
        print(x)

main()
""", "/r/a\n")


def run_tests():
    run_callable_param_tests()
    run_lambda_capture_tests()
    run_mixed_yield_kind_tests()
    run_next_method_tests()
    # Cluster E (bugs/CODEGEN_generator_function_Lib_ipaddress.md): a
    # generator method that CALLS the result of a `@property` getter
    # (`self._address_class(x)` -- `_address_class` is a @property returning
    # a class object, then invoked). This used to be A3-eligible and lowered
    # `self._address_class(x)` as a direct method call `Net__address_class(
    # self, x)` (arity 2 vs the getter's 1) -- broken C. Now honestly
    # refused; the emitted .c must compile cleanly.
    test_generator_c_compiles("generator_calls_property_getter_result", """\
struct Addr:
    var v: Int
    fn __init__(out self, v: Int):
        self.v = v

struct Net:
    var lo: Int
    var hi: Int
    fn __init__(out self, lo: Int, hi: Int):
        self.lo = lo
        self.hi = hi
    @property
    fn _address_class(self) -> Addr:
        return Addr(0)
    fn hosts(self):
        var x = self.lo
        while x <= self.hi:
            yield self._address_class(x)
            x = x + 1

def main():
    n = Net(1, 3)
    for h in n.hosts():
        print(h.v)
""")


    # The exact target shape from the Milestone B writeup: a parameterless
    # generator with a plain while-loop/yield/increment body, consumed by an
    # ordinary `for x in counter(): print(x)` loop. Confirms the whole
    # pipeline: constructing the coroutine WITHOUT running the body
    # (`_start`), resuming to each `co_yield` (`_resume`/`_value`), and
    # cleanup (`_destroy`) after the loop's natural exhaustion.
    test_generator_stdout("for_loop_consumes_counter_generator", """\
def counter():
    i = 0
    while i < 5:
        yield i
        i = i + 1

def main():
    for x in counter():
        print(x)
""", "0\n1\n2\n3\n4\n")

    # A second, structurally different call-site/consumption shape —
    # list(...) — routes through _lower_ctor_from_iterable's synthetic
    # Comprehension -> _lower_comprehension -> _compr_generator_loop, a
    # DIFFERENT code path from _gen_for_iter's _gen_for_generator_iter
    # above, so this confirms more than one consumer was actually wired up
    # (not just the for-loop path happening to work).
    test_generator_stdout("list_consumes_counter_generator", """\
def counter():
    i = 0
    while i < 5:
        yield i
        i = i + 1

def main():
    xs = list(counter())
    n = 0
    for x in xs:
        n = n + x
    print(n)
""", "10\n")

    # An early exit (`break`) partway through — the generator's coroutine
    # frame must still be destroyed cleanly (no crash/hang) even though the
    # loop never reaches "resume reports done".
    test_generator_stdout("for_loop_breaks_early_out_of_generator", """\
def counter():
    i = 0
    while i < 100:
        yield i
        i = i + 1

def main():
    for x in counter():
        if x == 3:
            break
        print(x)
""", "0\n1\n2\n")

    # Parameter-support step: the exact target shape from that step's
    # writeup — `counter(start, count)`, two int64_t parameters threaded
    # from the call site (`counter(10, 3)`) through `<base>_start`'s real
    # arguments into the coroutine frame, and read back out via ordinary
    # local variables inside the body. Confirms the whole pipeline actually
    # produces the right VALUES (10, 11, 12), not just that it type-checks.
    test_generator_stdout("param_generator_counter_start_count", """\
def counter(start, count):
    i = start
    n = 0
    while n < count:
        yield i
        i = i + 1
        n = n + 1

def main():
    for x in counter(10, 3):
        print(x)
""", "10\n11\n12\n")

    # A generator call site whose arguments are ordinary expressions (not
    # bare literals) — confirms argument lowering reuses this codegen's
    # normal self.lower_expr(a)-per-arg machinery (the same as any other
    # function call), not just plain literal passthrough.
    test_generator_stdout("param_generator_expression_args", """\
def counter(start, count):
    i = start
    n = 0
    while n < count:
        yield i
        i = i + 1
        n = n + 1

def main():
    base = 5
    for x in counter(base + 1, 1 + 2):
        print(x)
""", "6\n7\n8\n")

    # A single-parameter generator that yields the parameter directly (no
    # intermediate local) — the simplest possible parameterized shape.
    test_generator_stdout("param_generator_single_param_direct_yield", """\
def repeat_twice(v):
    yield v
    yield v

def main():
    for x in repeat_twice(42):
        print(x)
""", "42\n42\n")

    # A Float64-typed parameter, yielded through a local that's mutated each
    # iteration (`v = start`, then `v = v + step`) — confirms the value-type
    # inference correctly resolves to double (not the int64_t default) both
    # for a directly-yielded param and for a local assigned straight from
    # one, per _generator_yield_ctype's `known`-map threading.
    test_generator_stdout("param_generator_float_step", """\
def stepper(start: Float64, step: Float64, count):
    v = start
    n = 0
    while n < count:
        yield v
        v = v + step
        n = n + 1

def main():
    for x in stepper(1.5, 0.5, 3):
        print(x)
""", "1.5\n2.0\n2.5\n")

    # An UNANNOTATED parameter that's provably `double` at every call site
    # (the cross-call scalar-contract mechanism, reused from the ordinary
    # non-generator compiled-function path per e387af9/8799ec4) now compiles
    # correctly end-to-end as `double`, not the naive int64_t default —
    # the positive counterpart to the honest-refusal fix in
    # bugs/CODEGEN_compiled_generator_unannotated_string_param_mistyped.md
    # (an unannotated param unanimously called with a NON-scalar argument,
    # e.g. a string, is refused instead; this one is unanimously called
    # with a scalar double argument, so it's positively confirmed safe to
    # compile). Before the fix, `x`'s compile attempt ran before the
    # cross-call inference existed for generators at all, so it would have
    # silently defaulted to int64_t and truncated/corrupted the double
    # value instead of round-tripping it correctly.
    test_generator_stdout("param_generator_unannotated_double_via_cross_call", """\
def g(x):
    yield x

def main():
    for v in g(3.5):
        print(v)
""", "3.5\n")

    # Same, string-typed: `def g(x): yield x` called only `g("...")` —
    # `x`'s kind resolves to 'p' from the unanimous call site, so the
    # generator's value slot / <base>_value return type is `char *` and
    # the string round-trips instead of printing raw pointer bits.
    test_generator_stdout("param_generator_unannotated_string_via_cross_call", """\
def g(x):
    yield x

def main():
    for v in g("hello"):
        print(v)
""", "hello\n")

    # And through a binary expression: `yield a * 2` with `a` resolved to
    # 'd' from the call site keeps the arithmetic in `double` (the arg ABI
    # bit-casts the double through its int64_t slot, __mojo_gen_arg_d reads
    # it back). The value is 5.0, and compiled `print` preserves that repr.
    test_generator_stdout("param_generator_unannotated_double_binexpr", """\
def h(a):
    yield a * 2
    yield a * 2

def main():
    for v in h(2.5):
        print(v)
""", "5.0\n5.0\n")

    # A generator METHOD with an unannotated param, called consistently
    # with a float argument: the cross-call contract feeds `v`'s kind into
    # the method-lowering path too (arg slot index 1, after `self`).
    test_generator_stdout("param_generator_method_unannotated_double", """\
struct Box:
    fn __init__(out self):
        pass
    def emit(self, v):
        yield v
        yield v

def main():
    b = Box()
    for x in b.emit(1.25):
        print(x)
""", "1.25\n1.25\n")

    # A generator that is never called anywhere must still compile (no
    # crash from an empty cross-call kind set).
    test_generator_c_compiles("param_generator_never_called_compiles", """\
def unused(z):
    yield z

def main():
    print(0)
""")

    # Milestone C step 2 (yield-from delegation): the exact target shape —
    # `outer` delegates its entire output to `inner` via a bare
    # `yield from inner()`. `inner` must be defined before `outer` (see
    # gimple_codegen.GimpleGen._cpp_yield_from's docstring). Confirms the
    # hand-rolled resume/yield/exhaust delegation loop actually produces the
    # right VALUES, in order, not just that it type-checks.
    test_generator_stdout("yield_from_delegates_to_another_generator", """\
def inner():
    yield 1
    yield 2
    yield 3

def outer():
    yield from inner()

def main():
    for x in outer():
        print(x)
""", "1\n2\n3\n")

    # `yield from` composed with other statements around it in the
    # delegating generator's own body — confirms the delegation loop is a
    # normal statement in the body (not required to be the only statement),
    # and that values yielded directly by `outer` and values relayed from
    # `inner` interleave in the right order.
    test_generator_stdout("yield_from_delegation_with_surrounding_yields", """\
def inner():
    yield 2
    yield 3

def outer():
    yield 1
    yield from inner()
    yield 4

def main():
    for x in outer():
        print(x)
""", "1\n2\n3\n4\n")

    # An EMPTY inner generator (yields nothing at all) — the delegation
    # loop's while-condition must be false on the very first `_resume`
    # call, so `yield from` contributes zero values and execution falls
    # through to whatever follows it in `outer`'s own body, cleanly (no
    # crash/hang on a sub-generator that never produces anything).
    test_generator_stdout("yield_from_delegates_to_empty_generator", """\
def inner():
    if False:
        yield 1

def outer():
    yield from inner()
    yield 99

def main():
    for x in outer():
        print(x)
""", "99\n")

    # Early exit (`break`) partway through consuming `outer()` from OUTSIDE
    # — this calls outer's own `_destroy` (coroutine_handle::destroy()) on
    # a coroutine suspended mid-`co_yield` INSIDE the yield-from delegation
    # loop's nested block, holding a live handle to `inner`. Per the C++20
    # coroutine-frame-destruction rules, all locals in scope at that
    # suspension point (the `_mojogen_sub_guard` RAII wrapper) get
    # destroyed as part of destroying outer's frame, which must in turn
    # call inner's own `_destroy` -- confirms delegation composes correctly
    # with early exit of the OUTER generator, not just normal exhaustion.
    # (No direct way to observe "inner's _destroy actually ran" from mojo
    # stdout alone, but a hang or crash here -- e.g. from a double-destroy,
    # a leaked/never-destroyed inner coroutine frame corrupting later
    # allocations, or an outright segfault destroying an in-flight frame --
    # would fail this test's subprocess run/timeout, which is the real
    # thing being checked.)
    test_generator_stdout("yield_from_delegation_early_break_cleans_up_both_generators", """\
def inner():
    i = 0
    while i < 100:
        yield i
        i = i + 1

def outer():
    yield from inner()

def main():
    for x in outer():
        if x == 3:
            break
        print(x)
""", "0\n1\n2\n")

    # TWO LEVELS of `yield from` (level2 -> level1 -> level0), each level
    # also yielding its own extra values around the delegation -- confirms
    # delegation composes/nests correctly (not just a single hop), each
    # generator's own extern "C" API calling into the next one down's,
    # entirely resolved via same-translation-unit definitions.
    test_generator_stdout("yield_from_delegation_two_levels_deep", """\
def level0():
    yield 1
    yield 2

def level1():
    yield from level0()
    yield 3

def level2():
    yield from level1()
    yield 4

def main():
    for x in level2():
        print(x)
""", "1\n2\n3\n4\n")

    # `yield from cls.<generator>(...)` -- a @classmethod generator
    # DELEGATING to a sibling generator method of the same class
    # (Lib/importlib/resources/readers.py's
    # `MultiplexedPath._candidate_paths` doing
    # `yield from cls._resolve_zip_path(path_str)`). This needs four
    # separate pieces, none of which existed:
    #   * `_cls_refs_supported` admitted a `cls.<generator method>(...)`
    #     call (it deliberately excluded every compiled generator method,
    #     because the ORDINARY-call lowering has no receiver convention
    #     for one);
    #   * `_cpp_yield_from` resolved the callee through
    #     `_generator_method_api` and passed the `cls` receiver positionally
    #     (the opaque, never-dereferenced placeholder), since a
    #     `@staticmethod` callee has no receiver parameter at all;
    #   * `_yield_from_delegate_ctype` resolved the same callee for TYPE
    #     inference -- without it the delegation contributed a `char *`
    #     and the enclosing generator's own `yield 1` tripped the
    #     conflicting-types refusal;
    #   * a FORWARD declaration of the callee's four `extern "C"`
    #     wrappers, because the callee is defined LATER in the class (the
    #     two-pass method retry makes it *registered* in time, but its
    #     .cpp unit is still emitted after the delegating one).
    #
    # The callee is deliberately defined AFTER the delegator -- the shape
    # that forced the forward declaration, and what `readers.py` does.
    # The expected stdout is CPython's answer for this program; the
    # interpreter cannot be the oracle here because it has no
    # `@classmethod` binding at all (it hands the classmethod generator's
    # first argument through as `cls`, so `cls.inner` is an int), which is
    # a separate, still-open interpreter gap.
    test_generator_stdout("yield_from_cls_generator_method_delegation", """\
class Paths:
    @classmethod
    def outer(cls, n):
        yield 1
        yield from cls.inner(n)

    @classmethod
    def inner(cls, n):
        yield n
        yield n + 1

def main():
    for v in Paths.outer(5):
        print(v)
""", "1\n5\n6\n")

    # A @staticmethod GENERATOR, called as `Class.gen(...)` and consumed
    # directly by the `for` loop. This shape did not compile on EITHER
    # backend before, for two independent reasons that both had to be fixed:
    #
    #   * the free-function generator loop's "is this a method?" filter was
    #     "does its first parameter look like `self`/`cls`", which a
    #     @staticmethod (first parameter a REAL argument) does not satisfy —
    #     so the method's coroutine unit was emitted under the free-function
    #     symbol `_mojogen_gen_*` and registered in the FREE-function api
    #     table. `Class.gen(...)` was then not a generator call at all: it
    #     lowered to an ordinary int64_t call, and the `for` loop raised
    #     `mojo_unsupported_iter` at run time. Real:
    #     `Lib/importlib/resources/readers.py`'s `_resolve_zip_path`.
    #   * the A3 stack-switch backend classified a @staticmethod as an
    #     INSTANCE method, so it declared a `{Struct} *` self the caller
    #     never passed AND dropped the method's first real parameter.
    #
    # Asserts the real values, not just that it linked: the first yield is a
    # literal, the second is the parameter, so a dropped parameter shows up
    # as a wrong number rather than as a compile error.
    test_generator_stdout("staticmethod_generator_method", """\
class Emitter:
    @staticmethod
    def gen(n: Int):
        yield 1
        yield n

def main():
    for v in Emitter.gen(5):
        print(v)
""", "1\n5\n")

    # A @staticmethod generator that takes MORE than one parameter, so a
    # receiver still wrongly prepended (the previous bug) shifts BOTH and
    # cannot accidentally produce the right answer.
    test_generator_stdout("staticmethod_generator_multi_param", """\
class Emitter:
    @staticmethod
    def gen(a: Int, b: Int):
        yield a
        yield b
        yield a + b

def main():
    for v in Emitter.gen(3, 4):
        print(v)
""", "3\n4\n7\n")

    # The exact `readers.py` shape: a @classmethod generator delegating with
    # `yield from cls.<@staticmethod generator>(...)`. Both the delegation
    # and the receiver-less callee have to be right for this to produce
    # CPython's output — the round-1 fix covered the `cls.`-receiver
    # delegation, this adds the receiver-less callee it delegates to.
    test_generator_stdout("classmethod_generator_yield_from_staticmethod_generator", """\
class MP:
    @staticmethod
    def resolve_zip_path(p: Int):
        yield p + 10
        yield p + 20

    @classmethod
    def candidate_paths(cls, p: Int):
        yield p
        yield from cls.resolve_zip_path(p)

def main():
    for v in MP.candidate_paths(1):
        print(v)
    for v in MP.resolve_zip_path(100):
        print(v)
""", "1\n11\n21\n110\n120\n")

    # delegated-to (`inner`) generator take parameters, and `outer` passes
    # an expression (not just a bare literal) built from its own parameter
    # as one of `inner`'s arguments -- confirms parameter support (from the
    # Milestone C step 1 parameter-support step) and yield-from delegation
    # (this step) compose correctly together, not just each in isolation.
    test_generator_stdout("yield_from_delegation_with_parameters_both_sides", """\
def inner(start, count):
    i = start
    n = 0
    while n < count:
        yield i
        i = i + 1
        n = n + 1

def outer(base):
    yield from inner(base + 5, 3)

def main():
    for x in outer(10):
        print(x)
""", "15\n16\n17\n")

    # Milestone C step 3 (generator METHODS on structs): the target shape
    # from that step's writeup -- a method reading a scalar `self` field,
    # constructed via an ordinary compiled struct constructor and consumed
    # by an inline `for x in obj.method(...):` loop (the same call-site
    # shape _lower_struct_method_call's new generator-method branch
    # handles; see that method's own comment for why an intermediate
    # `g = obj.method(...)` assignment isn't supported -- a PRE-EXISTING
    # gap shared with every other compiled generator, free-function or
    # method, not something specific to this step).
    test_generator_stdout("generator_method_reads_self_field", """\
class Counter:
    def __init__(self, start: Int):
        self.value = start

    def countdown(self, n: Int):
        i = 0
        while i < n:
            yield self.value - i
            i = i + 1

def main():
    c = Counter(10)
    for x in c.countdown(3):
        print(x)
""", "10\n9\n8\n")

    # Per-instance isolation: TWO different Counter instances, each with
    # its own `value`, each driving its own `countdown(...)` call -- the
    # real bug-finding candidate for this step (a `self` binding that was
    # accidentally shared/aliased across instances, e.g. a stray global/
    # static instead of a genuine per-coroutine-frame copy of the `self`
    # pointer argument, would make the second loop's output depend on the
    # first instance's state instead of its own). Confirms each instance's
    # generator produces independently-correct output.
    test_generator_stdout("generator_method_self_binding_is_per_instance", """\
class Counter:
    def __init__(self, start: Int):
        self.value = start

    def countdown(self, n: Int):
        i = 0
        while i < n:
            yield self.value - i
            i = i + 1

def main():
    a = Counter(10)
    b = Counter(100)
    for x in a.countdown(3):
        print(x)
    for x in b.countdown(2):
        print(x)
""", "10\n9\n8\n100\n99\n")

    # A generator method combining `self.<field>` reads with an ORDINARY
    # scalar parameter (`step`) alongside the implicit `self` -- confirms
    # this step's self-binding support composes naturally with the
    # parameter-support step's existing machinery (Milestone C step 1),
    # not just the self-only case.
    test_generator_stdout("generator_method_self_field_plus_scalar_param", """\
class Counter:
    def __init__(self, start: Int):
        self.value = start

    def countup(self, n: Int, step: Int):
        i = 0
        while i < n:
            yield self.value + i * step
            i = i + 1

def main():
    c = Counter(10)
    for x in c.countup(3, 2):
        print(x)
""", "10\n12\n14\n")

    # A `double`-typed self field, read directly (no intermediate local) --
    # confirms self-field type inference correctly resolves to `double`
    # (not the int64_t default), mirroring the free-function parameter
    # step's float coverage but for a struct field instead of a parameter.
    test_generator_stdout("generator_method_self_field_double", """\
class Sampler:
    def __init__(self, base: Float64):
        self.base = base

    def samples(self, n: Int):
        i = 0
        while i < n:
            yield self.base + i
            i = i + 1

def main():
    s = Sampler(1.5)
    for x in s.samples(3):
        print(x)
""", "1.5\n2.5\n3.5\n")

    # Milestone C step 4 (this step): compiled generators as first-class
    # values — bugs/CODEGEN_compiled_generator_not_first_class_value.md's
    # exact repro. Before this step `python3 fire.py build` failed with a
    # genuine gcc compile error ("invalid use of void expression") the
    # moment a generator call's result was assigned to a variable before
    # being consumed, rather than being consumed inline as the `for` loop's
    # own iterable expression. This is the single most load-bearing new
    # test in this step: real compile+link+run, asserting the exact correct
    # output.
    test_generator_stdout("assign_then_for_loop_consumes_generator", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(3)
    for x in g:
        print(x)
""", "0\n1\n2\n")

    # The bug report's SECOND failure: calling next() directly on an
    # assigned generator variable, rather than consuming it via `for`.
    # Previously failed at LINK time (undefined symbol '_next') since the
    # generic next() builtin had no case for MojoGenerator* at all.
    test_generator_stdout("next_on_assigned_generator_var", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(3)
    print(next(g))
    print(next(g))
    print(next(g))
""", "0\n1\n2\n")

    # Edge case beyond the bug report's exact repro: calling next() PAST
    # exhaustion must raise StopIteration (not crash, not silently return a
    # stale/garbage value) — confirms the mojo_exc_type_set()/mojo_raise()
    # StopIteration-signaling convention added for next() is actually
    # catchable by an ordinary `except StopIteration:` in the same function,
    # exactly like a real Python generator's exhausted next().
    test_generator_stdout("next_past_exhaustion_raises_stopiteration", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(2)
    print(next(g))
    print(next(g))
    try:
        print(next(g))
    except StopIteration:
        print("done")
""", "0\n1\ndone\n")

    # Edge case beyond the bug report's exact repro: a generator variable
    # consumed by TWO separate `for` loops in sequence (the second over an
    # already-exhausted generator, which real Python simply iterates zero
    # times). Found via independent verification during this step: the
    # `for`-loop lowering originally destroyed the underlying coroutine
    # unconditionally once drained (correct ONLY for Milestone B's inline-
    # call-as-iterable shape, where that loop is the value's one and only
    # reference) — the moment the SAME generator became reachable by name
    # after the loop (this step's whole point), that unconditional destroy
    # turned a second consumption attempt into a real use-after-free
    # (confirmed crashing with SIGBUS before the fix). The second `for`
    # loop below must print nothing (not crash) — see _gen_for_iter's
    # destroy_after=isinstance(node.iterable, CallExpr) fix.
    test_generator_stdout("generator_variable_survives_two_for_loops", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(3)
    for x in g:
        print(x)
    for x in g:
        print(x)
    print("end")
""", "0\n1\n2\nend\n")

    # ── Milestone C final: generators crossing function-call boundaries ────
    # bugs/CODEGEN_compiled_generator_not_first_class_value.md's stated
    # remaining scope: a stored generator passed AS AN ARGUMENT to a
    # function whose (unannotated) param is consumed by `for x in g:`.
    # Before Pass 1.3f-gen, the call-site scalar contract observed `g`'s
    # stale int64_t inference and the callee's param defaulted to int64_t,
    # so the `for` loop hit the unsupported-iterable fallback (compile
    # still succeeded, but the loop body silently never ran).
    test_generator_stdout("generator_passed_as_argument", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def consume(g):
    for x in g:
        print(x)

def main():
    g = counter(3)
    consume(g)
""", "0\n1\n2\n")

    # A generator RETURNED from a function (`def mk(): return counter(3)`)
    # and consumed by the caller — the second first-class shape from the
    # bug report's impact list. Before this step, a call to `mk()` got no
    # MojoGenerator* typing at all on its result (only direct calls to the
    # generator function itself did), so the outer `for` loop fell back.
    test_generator_stdout("generator_returned_from_function", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def mk():
    return counter(3)

def main():
    g = mk()
    for x in g:
        print(x)
""", "0\n1\n2\n")

    # The two boundary shapes COMPOSED: return a generator from one
    # function, pass it into another, consume it there. Confirms the
    # provenance chain (caller assignment -> callee param) resolves
    # transitively rather than only for the immediate hop.
    test_generator_stdout("generator_returned_then_passed_as_argument", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def mk():
    return counter(3)

def consume(g):
    for x in g:
        print(x)

def main():
    consume(mk())
""", "0\n1\n2\n")

    # next() on a generator that has crossed a function boundary — the
    # callee drives _resume/_value on the passed-in param, and the SAME
    # generator keeps yielding correctly in the caller afterward.
    test_generator_stdout("generator_next_through_function_boundary", """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def consume(g):
    print(next(g))
    print(next(g))

def main():
    g = counter(3)
    consume(g)
    print(next(g))
""", "0\n1\n2\n")

    # ── Milestone D: try/except/raise inside a compiled generator body ──────
    # (real C++ exceptions confined to the generator's own .cpp translation
    # unit, translated to the pre-existing mojo_exc_type/msg/obj global state
    # only at the extern "C" `_resume` boundary — see gimple_codegen.py's
    # _cpp_try_stmt/_cpp_raise_stmt and fire_runtime.h's _mojo_exc_pending.)

    # A raise CAUGHT by the generator's OWN internal try/except — continues
    # yielding correctly afterward (not just "doesn't crash").
    test_generator_stdout("generator_raise_caught_internally", """\
def gen_internal_catch():
    i = 0
    while i < 5:
        try:
            if i == 2:
                raise ValueError("boom")
            yield i
        except ValueError:
            yield -1
        i = i + 1

def main():
    for x in gen_internal_catch():
        print(x)
""", "0\n1\n-1\n3\n4\n")

    # A raise NOT caught internally — propagates all the way out through the
    # extern "C" `_resume` boundary to the CALLER's own try/except, with the
    # right exception TYPE (only a ValueError handler matches) and the right
    # MESSAGE (bound via `as e`, read back correctly through the mojo_exc_obj
    # slot) — compared against real interpreter behavior below.
    test_generator_stdout("generator_raise_propagates_to_caller", """\
def gen_raises():
    yield 1
    yield 2
    raise ValueError("boom")

def main():
    try:
        for x in gen_raises():
            print(x)
    except ValueError as e:
        print(e)
""", "1\n2\nboom\n")

    # `yield from` delegating to a generator that raises, uncaught, partway
    # through — confirms the exception propagates correctly THROUGH the
    # delegation (Milestone C step 2) to the outer generator's own caller,
    # with values yielded before the raise (both the outer's own and the
    # relayed inner ones) still coming through in order first.
    test_generator_stdout("generator_yield_from_delegate_raises_propagates", """\
def inner_raises():
    yield 1
    raise KeyError("nope")

def outer_delegates():
    yield 0
    yield from inner_raises()
    yield 99

def main():
    try:
        for x in outer_delegates():
            print(x)
    except KeyError as e:
        print("caught")
        print(e)
""", "0\n1\ncaught\nnope\n")

    # `finally:` actually runs, the right NUMBER of times, across a mix of
    # normal iterations and an internally-caught raise — the observable
    # counterpart to test_gimple.py's compile-only finally coverage (a
    # `finally` result yielded AFTER the loop that used it finishes
    # normally, since `yield` can't appear inside the finally body itself —
    # see _cpp_try_stmt's docstring on why).
    test_generator_stdout("generator_try_except_finally_runs_every_time", """\
def gen_with_cleanup():
    cleanups = 0
    i = 0
    while i < 3:
        try:
            if i == 1:
                raise KeyError("x")
            yield i
        except KeyError:
            yield -1
        finally:
            cleanups = cleanups + 1
        i = i + 1
    yield cleanups

def main():
    for x in gen_with_cleanup():
        print(x)
""", "0\n-1\n2\n3\n")

    # Early exit (`break`) out of a `for` loop consuming a generator that has
    # an ACTIVE `try/finally` suspended mid-`co_yield` inside the try body —
    # the real-exception-machinery counterpart to Milestone B's early-
    # destroy precedent (for_loop_breaks_early_out_of_generator) and
    # Milestone C step 2's yield-from-early-break test. Per the C++20
    # coroutine-frame-destruction rules this relies on (see _cpp_try_stmt's
    # docstring on `_MojoScopeExit`), the finally-guard's destructor must
    # still fire correctly even though the coroutine is destroyed mid-try,
    # never reaching the finally "the normal way" — a crash/hang here (e.g.
    # from the guard's lambda capturing something already invalid) would
    # fail this test's subprocess run, which is the real thing being
    # checked, exactly like the precedent tests this one is modeled on.
    test_generator_stdout("generator_try_finally_survives_early_break", """\
def gen_finally_early_exit():
    i = 0
    while i < 100:
        try:
            yield i
        finally:
            i = i + 1

def main():
    for x in gen_finally_early_exit():
        if x == 2:
            break
        print(x)
""", "0\n1\n")

    # try/else/finally in a generator loop: on a normal (no-exception) pass
    # the `else` clause runs, THEN `finally`, each exactly once per
    # iteration. Regression guard for the fall-through path that used to
    # run the finally body twice (once falling into the finally label,
    # once again inline) — here it would have doubled BOTH `seen` and
    # `done`.
    test_generator_stdout("generator_try_else_finally_counts_once", """\
def gen():
    seen = 0
    done = 0
    i = 0
    while i < 3:
        try:
            yield i
        except KeyError:
            seen = seen + 100
        else:
            seen = seen + 1
        finally:
            done = done + 1
        i = i + 1
    yield seen
    yield done

def main():
    for x in gen():
        print(x)
""", "0\n1\n2\n3\n3\n")

    # Early `return` out of a try body that has a `finally`, inside a
    # generator: the finally must run exactly once on the way out and the
    # generator then stops (StopIteration). Regression guard for the
    # deferred-return path.
    test_generator_stdout("generator_try_finally_early_return_runs_once", """\
def gen():
    n = 0
    while True:
        try:
            if n == 2:
                return
            yield n
        finally:
            n = n + 1

def main():
    for x in gen():
        print(x)
    print("end")
""", "0\n1\nend\n")

    # Re-raise (bare `raise` with no value) inside a handler — the exception
    # is caught internally, immediately re-raised, and propagates out
    # uncaught (no value is ever yielded) to the caller's own try/except.
    # Exercises _cpp_raise_stmt's `throw {caught_var};` path (see
    # _cpp_try_stmt's docstring on why a bare `throw;` doesn't work here).
    test_generator_stdout("generator_reraise_propagates_to_caller", """\
def gen_reraise():
    try:
        raise ValueError("inner")
        yield 1
    except ValueError:
        raise

def main():
    try:
        for x in gen_reraise():
            print(x)
    except ValueError as e:
        print("caught")
        print(e)
""", "caught\ninner\n")

    # Multiple typed `except` clauses for DIFFERENT exception types in the
    # same try, each actually dispatching to its own (not just the first)
    # handler — exercises the descendant-OR dispatch chain built by
    # _cpp_try_stmt for real, not just compile-checked.
    test_generator_stdout("generator_multiple_except_types_dispatch_correctly", """\
def gen_multi_except():
    i = 0
    while i < 4:
        try:
            if i == 0:
                raise ValueError("v")
            if i == 1:
                raise KeyError("k")
            yield i
        except ValueError:
            yield -1
        except KeyError:
            yield -2
        i = i + 1

def main():
    for x in gen_multi_except():
        print(x)
""", "-1\n-2\n2\n3\n")

    # A bare `except:` catch-all — every exception type matches it, not just
    # ones that happen to share tag 0.
    test_generator_stdout("generator_bare_except_catches_anything", """\
def gen_bare_except():
    i = 0
    while i < 3:
        try:
            if i == 1:
                raise RuntimeError("x")
            yield i
        except:
            yield -1
        i = i + 1

def main():
    for x in gen_bare_except():
        print(x)
""", "0\n-1\n2\n")

    # LambdaExpr-as-value / bound-method-as-value in a compiled generator
    # body (see bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md) —
    # mirrors pickletools.py's `_genops` shape EXACTLY: the same local
    # (`getpos`) is assigned a zero-arg `lambda` on one branch and a
    # bound-method VALUE (`self.tell`, not immediately called) on the
    # other, then invoked as a plain `getpos()`. The `self`-method variant.
    test_generator_stdout("generator_lambda_and_self_bound_method_as_value", """\
class Ticker:
    def __init__(self, start: Int):
        self.value = start

    def tell(self):
        return self.value

    def run(self, use_lambda: Int):
        if use_lambda:
            getpos = lambda: 42
        else:
            getpos = self.tell
        pos = getpos()
        yield pos

def main():
    tk = Ticker(7)
    for x in tk.run(1):
        print(x)
    for x in tk.run(0):
        print(x)
""", "42\n7\n")

    # Same shape, but the bound method is read off a struct-pointer
    # PARAMETER rather than `self` — the closer match to `_genops`' own
    # `getpos = data.tell` (where `data` is a generator PARAMETER, not the
    # enclosing struct), just with a statically-known struct type (`data`'s
    # real class in pickletools.py is a dynamically-typed io.BytesIO/file
    # object this narrow scalar-body model can't resolve at all — a
    # SEPARATE, honestly-unfixed gap; see that bug doc's own status notes).
    test_generator_stdout("generator_lambda_and_param_bound_method_as_value", """\
class Ticker:
    def __init__(self, start: Int):
        self.value = start

    def tell(self):
        return self.value

def gen(tk: Ticker, use_lambda: Int):
    if use_lambda:
        getpos = lambda: 99
    else:
        getpos = tk.tell
    pos = getpos()
    yield pos

def main():
    tk = Ticker(11)
    for x in gen(tk, 1):
        print(x)
    for x in gen(tk, 0):
        print(x)
""", "99\n11\n")

    # Struct-pointer-yield support (2026-08-20): a generator YIELDING a real
    # struct pointer value, not just accepting one as a parameter. Bare
    # struct-typed-parameter yield already worked before this change (see
    # `_infer_simple_expr_ctype`'s `known` map) — this confirms it as a
    # regression guard now that the same type-inference function also
    # widens IdentExpr/self.field/CallExpr cases.
    test_generator_stdout("struct_ptr_bare_param_yield", """\
class Ticker:
    def __init__(self, start: Int):
        self.value = start

def gen(tk: Ticker):
    yield tk

def main():
    t = Ticker(5)
    for x in gen(t):
        print(x.value)
""", "5\n")

    # `self.<dict-field>.get(key)` yielding a struct-pointer VALUE read out
    # of a `dict[K, StructType]`-typed field — the confirmed real-world
    # shape (Lib/enum.py's `Flag._iter_member_by_value_`:
    # `cls._value2member_map_.get(val)`, a `Flag *`), reduced to a `self`-
    # based (non-classmethod) generator method here since the `cls`-access
    # gap itself is a separate, still out-of-scope limitation (see
    # CODEGEN_generator_function_Lib_enum.md). Exercises: struct-pointer
    # yield-type inference via `_field_dict_val_types` (seeded early, from
    # the field's own `var map: dict[Int, Flag]` declaration, so it's
    # available in time for generator-method translation), the promise/
    # `co_yield`/consumer-side plumbing (unchanged, already generic), the
    # real `mojo_dict_get_int`-based `.get()` codegen this change ALSO
    # added to `_cpp_expr` (the raw `obj.get(k)` C++ fallback it replaces
    # doesn't compile against an opaque `MojoDict *`), and the struct-
    # typedef-visibility widening (`_cpp_value_struct_names`) for a struct
    # that's reachable ONLY via the yielded value's type, not via `self`, a
    # parameter, or a constructor call.
    test_generator_stdout("struct_ptr_dict_get_yield", """\
class Flag:
    def __init__(self, val: Int):
        self.val = val

class Container:
    var map: dict[Int, Flag]

    def __init__(self):
        self.map = {}

    def add(self, k: Int, f: Flag):
        self.map[k] = f

    def gen(self, k: Int):
        yield self.map.get(k)

def main():
    c = Container()
    f = Flag(42)
    c.add(1, f)
    for x in c.gen(1):
        print(x.val)
""", "42\n")

    # General case: a struct-typed receiver's own METHOD call chain
    # returning ANOTHER struct pointer, yielded directly — not just the
    # `.get()` shape above. Exercises `method_return_types` (this file's
    # existing `self.func_return_types`, reused rather than re-derived) in
    # `_infer_simple_expr_ctype`'s CallExpr/MemberExpr branch.
    test_generator_stdout("struct_ptr_method_chain_yield", """\
class Inner:
    def __init__(self, v: Int):
        self.v = v

class Outer:
    def __init__(self, v: Int):
        self.inner = Inner(v)

    def get_inner(self):
        return self.inner

def gen(o: Outer):
    yield o.get_inner()

def main():
    o = Outer(99)
    for x in gen(o):
        print(x.v)
""", "99\n")

    # `cls.<attr>` class-attribute redirect + `cls.<attr>.get(...)` dict
    # lookup inside a compiled @classmethod generator — the exact
    # Lib/enum.py `Flag._iter_member_by_value_` shape (`for val in
    # _iter_bits_lsb(value & cls._flag_mask_): yield cls._value2member_map_.
    # get(val)`), reduced to its two load-bearing pieces: a bare `cls.<attr>`
    # read (`cls._flag_mask_`-equivalent, used inline rather than yielded)
    # and a `cls.<dict-attr>.get(key)` yield whose value type is a real
    # struct pointer (`cls._value2member_map_.get(val)`-equivalent). Called
    # via an INSTANCE (`r.gen(k)`, mirroring enum.py's own real call site,
    # `self._iter_member_(self._value_)`) — invoking a @classmethod
    # generator via the CLASS NAME directly (`Registry.gen(k)`) hits a
    # separate, pre-existing call-site gap in the ordinary (non-generator)
    # GIMPLE path (routing a class-name method call to the generator-start
    # API), out of this fix's scope (see bugs/CODEGEN_generator_function_
    # Lib_enum.md's 2026-08-21 update). See that same doc's update for the
    # full root-cause.
    test_generator_stdout("cls_class_attr_dict_get_yield", """\
class Flag:
    def __init__(self, val: Int):
        self.val = val

class Registry:
    _value_map: dict[Int, Flag] = {}
    _mask: Int = 3

    def __init__(self):
        self._value_map[1] = Flag(42)
        self._value_map[2] = Flag(43)

    @classmethod
    def gen(cls, k: Int):
        m = cls._mask
        if k <= m:
            yield cls._value_map.get(k)

def main():
    r = Registry()
    for x in r.gen(1):
        print(x.val)
    for x in r.gen(2):
        print(x.val)
""", "42\n43\n")

    # `cls.method(...)` call inside a compiled @classmethod generator —
    # resolved purely by NAME (the enclosing struct's own real compiled
    # classmethod), mirroring the `self.method(...)` call case's own
    # mechanism. See bugs/CODEGEN_generator_function_Lib_enum.md's
    # 2026-08-21 update, point (2). Also called via an instance, for the
    # same call-site-gap reason noted above.
    test_generator_stdout("cls_classmethod_call_in_generator", """\
class Helper:
    def __init__(self):
        self.dummy = 0

    @classmethod
    def double(cls, n: Int):
        return n * 2

    @classmethod
    def gen(cls, n: Int):
        yield cls.double(n)

def main():
    h = Helper()
    for x in h.gen(21):
        print(x)
""", "42\n")

    # `yield from sorted(<iterable>, key=lambda x: ...)` — a single-
    # parameter lambda passed directly as a `key=` call argument (not
    # assigned to a local first, unlike `generator_lambda_and_*_bound_
    # method_as_value` above). Real target: Lib/enum.py's
    # `Flag._iter_member_by_def_`: `yield from sorted(cls._iter_member_
    # by_value_(value), key=lambda m: m._sort_order_)` — see
    # bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md's
    # "single-parameter lambda" follow-up. This is also the regression
    # test for a real, confirmed SEGFAULT this same session found and
    # fixed: the promise/consumer-side type inference for `yield from
    # sorted(...)` previously defaulted to char* (the generic "unknown
    # collection" fallback), so the sort's own int64_t-payload MojoList
    # got read back via `mojo_list_get_str` — a garbage pointer
    # dereference — regardless of element type, not just the struct-
    # pointer-element shape. Asserts DESCENDING order (`-m` key) to
    # confirm the comparator is genuinely being invoked per-element, not
    # just passing the list through unsorted.
    test_generator_stdout("generator_sorted_key_lambda_scalar", """\
def gen(xs: list):
    yield from sorted(xs, key=lambda m: -m)

def main():
    for x in gen([3, 1, 2]):
        print(x)
""", "3\n2\n1\n")

    # `for i, d in enumerate(<call to another compiled generator>, start):`
    # inside a generator body — a GENERATOR CALL as enumerate's OWN first
    # argument (flat 2-name target), composed with the sub-generator drive
    # loop and its index tracking. Real target: Lib/calendar.py's
    # `Calendar.itermonthdays2` (`for i, d in
    # enumerate(self.itermonthdays(year, month), self.firstweekday):`) —
    # previously `_cpp_expr` lowered the generator call through the wrong
    # ordinary extern "C" stub (void-returning), producing g++'s "void
    # value not ignored as it ought to be". The free-function callee shape
    # exercises the same delegation machinery through its other branch.
    test_generator_stdout("enumerate_generator_method_arg_start", """\
class Cal:
    def __init__(self):
        self.firstweekday = 2

    def iterdays(self, n):
        yield from range(1, n + 1)

    def iterdaynum(self, n):
        for i, d in enumerate(self.iterdays(n), self.firstweekday):
            yield d, i % 7

def main():
    c = Cal()
    for d, wd in c.iterdaynum(4):
        print(d, wd)
""", "1 2\n2 3\n3 4\n4 5\n")

    test_generator_stdout("enumerate_generator_free_fn_arg_start", """\
def days(n):
    yield from range(1, n + 1)

def numbered(n, start):
    for i, d in enumerate(days(n), start):
        yield d * 100 + i

def main():
    for v in numbered(3, 10):
        print(v)
""", "110\n211\n312\n")

    # `self.<method>()` inside a generator body OMITTING a defaulted
    # trailing parameter (`def scaled(self, mult=2)` called as
    # `self.scaled()`). Real target: Lib/mailbox.py's
    # `_singlefileMailbox.iterkeys` doing `self._lookup()` on
    # `def _lookup(self, key=None)` and `_ProxyFile.__iter__` doing
    # `self.readline()` on `def readline(self, size=None)` — previously
    # the coroutine-body call lowering emitted only the given arguments
    # ("too few arguments to function '_singlefileMailbox__lookup'").
    # The ordinary (non-coroutine) method-call path already padded short
    # calls; the three coroutine-body struct-method call branches now run
    # through the same arity/defaults padding.
    test_generator_stdout("generator_self_method_defaulted_arg", """\
class Box:
    def __init__(self):
        self.base = 100

    def scaled(self, mult=2):
        return self.base * mult

    def gen(self):
        yield self.scaled()
        yield self.scaled(5)

def main():
    b = Box()
    for v in b.gen():
        print(v)
""", "200\n500\n")

    # `lines = []` + `lines.append(v)` + iteration/subscript/len over the
    # local list inside a generator body — the single most common
    # accumulator idiom in real stdlib generators (ftplib.py's mlsd and
    # many others). Previously the literal lowered to raw C++ brace-init
    # text assigned to an int64_t-declared local ("request for member
    # 'append' in 'lines', which is of non-class type 'int64_t'"); now a
    # real MojoList* with element-type tracking driving the accessors.
    test_generator_stdout("generator_list_literal_local_append_iterate", """\
def gen(n):
    acc = []
    acc.append(1)
    acc.append(2 * n)
    yield len(acc)
    yield acc[1]
    total = 0
    for v in acc:
        total = total + v
    yield total

def main():
    for v in gen(10):
        print(v)
""", "2\n20\n21\n")

    test_generator_stdout("generator_str_list_local_roundtrip", """\
def gen():
    lines = []
    lines.append("alpha")
    lines.append("beta")
    for s in lines:
        yield s
    yield lines[0]

def main():
    for v in gen():
        print(v)
""", "alpha\nbeta\nalpha\n")

    # `entry = {}` + string-keyed writes + reads keyed by a loop variable
    # over a string-literal tuple (the tuple-range-for's `auto` target must
    # be tracked as char* or the dict key gets garbage-stringified through
    # mojo_str_from_int).
    test_generator_stdout("generator_dict_local_string_keys", """\
def dgen():
    entry = {}
    entry["alpha"] = 1
    entry["beta"] = 2
    s = 0
    for k in ("alpha", "beta"):
        s = s + entry[k]
    yield s

def main():
    for v in dgen():
        print(v)
""", "3\n")

    # ── Generator-consumption ordering + param-default padding family ─────
    #
    # A DEEP forward-consumption chain: every consumer is defined BEFORE
    # its producer, and each level's unit only becomes compilable after
    # the level below it registers (gen_module's retry passes). The retry
    # loop used to be a hard-coded 3 passes — this 5-deep chain needs 4,
    # so it used to leave head/l3 refused and fall back to interpreting
    # the whole module. Values are chosen so each link's wiring is
    # visible in the final number: tail(3)=0+1+2 -> l1=30 -> l2=130 ->
    # l3=130 -> head=1130.
    test_generator_stdout("generator_forward_consumption_deep_chain", """\
def head(n):
    t = 0
    for x in l3(n):
        t = t + x
    yield t + 1000

def l3(n):
    t = 0
    for x in l2(n):
        t = t + x
    yield t

def l2(n):
    t = 0
    for x in l1(n):
        t = t + x
    yield t + 100

def l1(n):
    t = 0
    for x in tail(n):
        t = t + x
    yield t * 10

def tail(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    for v in head(3):
        print(v)
""", "1130\n")

    # A consuming for-loop omitting a LATER-defaulted argument of the
    # consumed generator (`for x in prod(n)` against `def prod(n,
    # step=10)`): must pad step=10, not refuse on arity and not pad a
    # typed zero (which silently produced 0+1+2=3 instead of 33).
    test_generator_stdout("generator_for_consumption_pads_callee_defaults", """\
def prod(n, step=10):
    i = 0
    while i < n:
        yield i + step
        i = i + 1

def consumer(n):
    total = 0
    for x in prod(n):
        total = total + x
    yield total

def main():
    for v in consumer(3):
        print(v)
""", "33\n")

    # The DIRECT construction call path with an omitted non-zero-offset
    # default (`prod(3)` against `def prod(n, step=10)`): the padding
    # indexed the defaults list WITHOUT its trailing-run offset, so the
    # omitted arg silently got 0 instead of 10 — real compiled output,
    # no refusal, wrong number. Regression test for that silent-miscompile.
    test_generator_stdout("generator_direct_call_pads_nonzero_offset_default", """\
def prod(n, step=10):
    i = 0
    while i < n:
        yield i + step
        i = i + 1

def main():
    total = 0
    for v in prod(3):
        total = total + v
    print(total)
""", "33\n")

    # Same trailing-default padding through the `yield from` delegation
    # drive loop (`yield from inner(base)` against `def inner(start,
    # count=2)`): must delegate with count=2.
    test_generator_stdout("generator_yield_from_pads_callee_defaults", """\
def inner(start, count=2):
    i = start
    k = 0
    while k < count:
        yield i
        i = i + 1
        k = k + 1

def outer(base):
    yield from inner(base)

def main():
    for v in outer(7):
        print(v)
""", "7\n8\n")

    # Method-generator direct call with an omitted default after a
    # leading required non-self param (`c.gen(3)` against `def gen(self,
    # n, step=2)`): the method-call padding must skip `self` AND apply
    # the trailing-run offset — it previously did neither correctly for
    # this shape (padded 0, yielding 10/11/12).
    test_generator_stdout("generator_method_call_pads_nonzero_offset_default", """\
class C:
    def __init__(self, base: Int):
        self.base = base

    def gen(self, n: Int, step: Int = 2):
        i = 0
        while i < n:
            yield self.base + i * step
            i = i + 1

def main():
    c = C(10)
    for v in c.gen(3):
        print(v)
""", "10\n12\n14\n")

    # Pop-time shape discrimination for a heterogeneous / tagged-union
    # `stack` value model: a list holding both scalar elements and nested
    # tuples, drained with `.pop()`, each popped value discriminated with
    # `isinstance(top, tuple)` and (when a tuple) destructured via a
    # tuple-unpack. Exercises: nested-container literal appended to a flat
    # boxed list, `while <list>:` emptiness (not pointer-nullness),
    # `<list>.pop()`, runtime `mojo_is_registered_list` discrimination,
    # and a boxed-value tuple-unpack through the runtime list getters.
    test_generator_stdout("generator_pops_heterogeneous_tagged_stack", """\
def walker():
    stack = [(1, 2)]
    stack.append("leaf")
    stack.append((3, 4))
    while stack:
        top = stack.pop()
        if isinstance(top, tuple):
            a, b = top
            yield a + b
        else:
            yield 99

def main():
    for x in walker():
        print(x)
""", "7\n99\n3\n")

    # Second-level unpack: `marker, payload = stack.pop()` where `payload`
    # is itself a boxed tuple needing its own unpack (the exact `_fwalk`
    # shape from bugs/CODEGEN_generator_function_Lib_os.md — `action,
    # value = stack.pop()` then `isroot, ... = value`).
    test_generator_stdout("generator_pops_stack_two_level_tuple_unpack", """\
def walker():
    stack = []
    stack.append((0, (10, 20, 30)))
    stack.append((1, (40, 50, 60)))
    while stack:
        marker, payload = stack.pop()
        x, y, z = payload
        yield marker + x + y + z

def main():
    for v in walker():
        print(v)
""", "151\n60\n")


    # `var`-declared local (Mojo VarDecl) inside a generator body, plus a
    # string built in the body from a numeric part via String(i) and
    # concatenation — the compiled coroutine emitter used to hard-refuse
    # the VarDecl outright ("unsupported statement in generator body:
    # VarDecl") and, once that was lowered, mis-stringify String(0) as
    # "None" (mojo_str's pointer heuristic reads 0 as NULL).
    test_generator_stdout("generator_vardecl_string_built_in_body", """\
def gen_str(n):
    for i in range(n):
        var s = "item" + String(i)
        yield s

def main():
    for x in gen_str(3):
        print(x)
""", "item0\nitem1\nitem2\n")

    # Resumable list-iterator value model inside a generator body:
    # `it = iter(xs)` binds a real cursor, `next(it)` advances it, a
    # following `for x in it:` continues from where next() left off, and
    # `next(it, default)` returns the default on exhaustion. Plus
    # `min(iterable)`/`max(iterable)` and multi-arg `min(a, b, ...)`.
    # Mirrors bugs/CODEGEN_generator_function_Lib_ipaddress.md's
    # `_find_address_range` shape. Previously every one of these refused
    # the whole module ("unresolved callee 'next(...)'" etc.).
    test_generator_stdout("generator_list_iterator_cursor_and_minmax", """\
def scan(xs):
    it = iter(xs)
    first = next(it)
    yield first
    for x in it:
        yield x
    yield next(it, -1)
    yield min(xs)
    yield max(xs)
    yield min(8, 3, 5, 1, 9)

def main():
    for v in scan([10, 20, 30]):
        print(v)
""", "10\n20\n30\n-1\n10\n30\n1\n")

    # StopIteration from an exhausted list-iterator's next() is a real
    # tagged exception, catchable by an enclosing try/except in the body.
    test_generator_stdout("generator_list_iterator_stopiteration_caught", """\
def scan(xs):
    it = iter(xs)
    yield next(it)
    try:
        yield next(it)
        yield next(it)
    except StopIteration:
        yield 999

def main():
    for v in scan([7]):
        print(v)
""", "7\n999\n")

    # bugs/hard/CODEGEN_coro_stackswitch_iterator_protocol_gaps.md — the A3
    # stack-switch cutover routes a generator BODY through the ordinary
    # codegen, which never had a real iter()/next() over a plain list
    # (only the old cpp-path emitter did, in gimple_cpp_core.py). Below:
    # a STRING-element list iterator (accessor kind picked from the list's
    # tracked element type, not hard-coded to get_int), next(it, default)
    # returning the default only on real exhaustion, and next(it, default)
    # still yielding a real element while the cursor has more.
    test_generator_stdout("generator_str_list_iterator_next_default", """\
def scan():
    xs = ["a", "b"]
    it = iter(xs)
    yield next(it)
    yield next(it, "END")
    yield next(it, "END")

def main():
    for s in scan():
        print(s)
""", "a\nb\nEND\n")

    # enumerate(<generator>) with NO explicit start (0-based) — the
    # zero-arg-start branch of the same _gen_for_enumerate_generator path.
    test_generator_stdout("enumerate_generator_no_start", """\
def src(n):
    for i in range(n):
        yield i * 10

def numbered(n):
    for i, v in enumerate(src(n)):
        yield v + i

def main():
    for x in numbered(4):
        print(x)
""", "0\n11\n22\n33\n")

    # A generator body that consumes its list arg with BOTH next() and a
    # following `for x in it:` — the for-loop must resume from the cursor
    # next() already advanced (single-pass), not restart from element 0.
    test_generator_stdout("generator_list_iter_next_then_for_resumes", """\
def scan(xs):
    it = iter(xs)
    first = next(it)
    yield first
    for x in it:
        yield x

def main():
    for v in scan([1, 2, 3, 4]):
        print(v)
""", "1\n2\n3\n4\n")

    # A generator body that calls `next(it)` from INSIDE `for x in it:` over
    # the same cursor. An A3 stack-switch body goes through the ordinary
    # codegen's `_gen_for_list_iter_cursor`, whose cursor is the index of the
    # next UNCONSUMED element (the advance is part of reading the element, not
    # a post-body step) — so `next(it)` in the body reads the FOLLOWING
    # element, as CPython's `list_iterator.__next__` does, and all four
    # elements are seen exactly once. Before that invariant was restored the
    # post-block advance made `next(it)` re-read the element the loop had just
    # yielded: `1\n1\n3\n3`. Same shape as CPython's own
    # `Tools/cases_generator/analyzer.py::check_escaping_calls`.
    test_generator_stdout("generator_next_inside_for_over_same_it", """\
def scan(xs):
    it = iter(xs)
    for x in it:
        yield x
        yield next(it)

def main():
    for v in scan([1, 2, 3, 4]):
        print(v)
""", "1\n2\n3\n4\n")

    # ── yield-kind inference for identifier / self.field / list-local refs ──
    # (bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md)
    # The Layer-1 pre-pass's _yield_kind() used to have no case for a bare
    # IdentExpr / `self.<field>` / `<list-local>[idx]` reference, so a
    # Float64/String value yielded through one of those silently defaulted
    # to int64_t and was truncated (float) or printed as a raw pointer
    # value (string). _static_env now resolves them from purely-syntactic
    # type sources available at pre-pass time.

    # self.<field> whose type comes from __init__(self, base: Float64)
    test_generator_stdout("generator_yields_self_float_field_plus_int", """\
class Sampler:
    def __init__(self, base: Float64):
        self.base = base
    def samples(self, n: Int):
        i = 0
        while i < n:
            yield self.base + i
            i = i + 1

def main():
    s = Sampler(1.5)
    for x in s.samples(3):
        print(x)
""", "1.5\n2.5\n3.5\n")

    # bare identifier resolved from the generator's own param annotation
    test_generator_stdout("generator_yields_string_param_identifier", """\
def echo(s: String):
    yield s
    yield s

def main():
    for v in echo("hello"):
        print(v)
""", "hello\nhello\n")

    # list-typed local: `xs = [<string literals>]`, `yield xs[i % 2]`
    test_generator_stdout("generator_yields_string_list_local_subscript", """\
def strs():
    xs = ["alpha", "beta"]
    i = 0
    while i < 3:
        yield xs[i % 2]
        i = i + 1

def main():
    for s in strs():
        print(s)
""", "alpha\nbeta\nalpha\n")

    # float local seeded from a float literal, yielded bare
    test_generator_stdout("generator_yields_float_local_identifier", """\
def ramp():
    x = 0.5
    i = 0
    while i < 3:
        yield x
        x = x + 1.0
        i = i + 1

def main():
    for v in ramp():
        print(v)
""", "0.5\n1.5\n2.5\n")

    # ── non-plain assignment targets inside a generator body ──────────
    # (bugs/hard/CODEGEN_generator_non_plain_assignment_target_refused.md)
    # The A3 stack-switch path routes the desugared body through ordinary
    # codegen, which handles self-field write, subscript write, and
    # tuple/list-pattern unpack -- shapes the old cpp eligibility gate
    # refused wholesale.
    test_generator_stdout("generator_list_pattern_unpack_literal_rhs", """\
def g():
    yield 1
    [x] = [42]
    yield x

def main():
    for v in g():
        print(v)
""", "1\n42\n")

    test_generator_stdout("generator_list_pattern_unpack_two_and_call_rhs", """\
def src():
    return [7, 8]

def g():
    [a, b] = src()
    yield a
    yield b
    [c] = [99]
    yield c

def main():
    for v in g():
        print(v)
""", "7\n8\n99\n")

    test_generator_stdout("generator_list_pattern_unpack_comprehension_rhs", """\
def g():
    yield 1
    src = [10, 20, 30]
    [first] = [w for w in src if w == 20]
    yield first

def main():
    for v in g():
        print(v)
""", "1\n20\n")

    test_generator_stdout("generator_self_field_write_between_yields", """\
struct Counter:
    var count: Int
    fn __init__(out self):
        self.count = 0
    def gen(self):
        yield self.count
        self.count = 99
        yield self.count

def main():
    c = Counter()
    for v in c.gen():
        print(v)
""", "0\n99\n")

    test_generator_stdout("generator_subscript_write_between_yields", """\
def g(d):
    yield d[0]
    d[0] = 99
    yield d[0]

def main():
    xs = [1, 2, 3]
    for v in g(xs):
        print(v)
""", "1\n99\n")

    # ── recursive `yield from` forwards extra positional + keyword-only
    # arguments (bugs/hard/CODEGEN_generator_recursive_yield_from_no_arg_
    # forwarding.md). The documented "too few arguments" / yield-type
    # mismatch compile failures are gone on the A3 path.
    test_generator_stdout("generator_recursive_yield_from_extra_positional_arg", """\
def countdown(n, step=1):
    if n <= 0:
        return
    yield n
    yield from countdown(n - step, step)

def main():
    for v in countdown(5, 2):
        print(v)
""", "5\n3\n1\n")

    test_generator_stdout("generator_recursive_yield_from_keyword_only_arg", """\
def countdown(n, *, step=1):
    if n <= 0:
        return
    yield n
    yield from countdown(n - step, step=step)

def main():
    for v in countdown(5, 2 if False else 2):
        print(v)
""", "5\n3\n1\n")

    # ── lambda literals inside a generator body ───────────────────────
    # (bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md) -- 0-, 1-
    # and 2-parameter lambdas, a lambda re-bound on each branch of an
    # if/else, and a lambda passed as a call argument all work via the
    # ordinary codegen path's lambda lifting.
    test_generator_stdout("generator_zero_arg_lambda_called", """\
def g(n):
    getpos = lambda: 7
    i = 0
    while i < n:
        yield getpos()
        i = i + 1

def main():
    for v in g(3):
        print(v)
""", "7\n7\n7\n")

    test_generator_stdout("generator_one_arg_lambda_over_list", """\
def g(xs):
    f = lambda m: m + 1
    for x in xs:
        yield f(x)

def main():
    for v in g([10, 20, 30]):
        print(v)
""", "11\n21\n31\n")

    test_generator_stdout("generator_two_arg_lambda_and_lambda_as_arg", """\
def apply(fn, v):
    return fn(v)

def g(xs):
    add = lambda a, b: a + b
    for x in xs:
        yield apply(lambda m: m * 2, add(x, 10))

def main():
    for v in g([1, 2, 3]):
        print(v)
""", "22\n24\n26\n")

    test_generator_stdout("generator_lambda_rebound_per_branch", """\
def g(pick):
    if pick:
        f = lambda: 42
    else:
        f = lambda: 99
    yield f()

def main():
    for v in g(1):
        print(v)
    for v in g(0):
        print(v)
""", "42\n99\n")

    # ---- Regression tests distilled from the 30 bugs/CODEGEN_generator_
    # function_Lib_*.md stdlib shapes that the doc/COROUTINE.html §5.5 A3
    # stack-switch cutover made compile (previously wholesale-refused by
    # the old gimple_cpp_core.py C++20-coroutine eligibility gate). One
    # minimal shape per stdlib family that flipped to compiling.

    # weakref.WeakValueDictionary.__iter__ / tarfile.TarFile.__iter__ /
    # tempfile._TemporaryFileWrapper.__iter__ / typing._GenericAlias.
    # __iter__ / mailbox / shelve: a generator METHOD on a struct that
    # walks a list field and yields each element.
    test_generator_stdout("generator_method_iterates_list_field", """\
struct Bag:
    var items: List[Int]
    fn __init__(out self):
        self.items = [10, 20, 30]
    fn each(self):
        for x in self.items:
            yield x

def main():
    b = Bag()
    for v in b.each():
        print(v)
""", "10\n20\n30\n")

    # dis.findlinestarts / ipaddress._find_address_range: for-loop over an
    # explicitly-typed list param with a guarded yield inside the loop body.
    test_generator_stdout("generator_guarded_yield_in_for_over_typed_param", """\
def positives(xs: List[Int]):
    for x in xs:
        if x > 0:
            yield x

def main():
    for v in positives([-2, 3, -1, 5, 0, 8]):
        print(v)
""", "3\n5\n8\n")

    # enum._iter_bits_lsb / dis._unpack_opargs: for-loop over range() with a
    # modulo guard, yielding a filtered subset.
    test_generator_stdout("generator_range_loop_with_modulo_guard", """\
def evens(n):
    for x in range(n):
        if x % 2 == 0:
            yield x

def main():
    for v in evens(6):
        print(v)
""", "0\n2\n4\n")

    # glob._iglob / pkgutil.walk_packages / tokenize.tokenize: a generator
    # that delegates to another generator with `yield from`, then yields
    # more of its own values afterward.
    test_generator_stdout("generator_yield_from_then_own_values", """\
def inner(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def outer(n):
    yield from inner(n)
    yield 100
    yield 101

def main():
    for v in outer(3):
        print(v)
""", "0\n1\n2\n100\n101\n")

    # symtable.Symbol._flags_str / tokenize helpers: accumulate across
    # yields with a running local updated before each yield, iterating a
    # locally-built int list.
    test_generator_stdout("generator_running_local_across_yields", """\
def deltas():
    xs = [1, 2, 3, 4]
    total = 0
    for x in xs:
        total = total + x
        yield total

def main():
    for v in deltas():
        print(v)
""", "1\n3\n6\n10\n")

    # bytes / bytearray / memoryview VALUE TYPES inside a compiled
    # generator body. The
    # A3 stack-switch cutover routes a generator body through ordinary
    # codegen, which gained full bytes/bytearray/memoryview support in
    # Stages 1-3 -- these lock in that it actually works end-to-end from
    # inside a `yield`ing body.
    test_generator_stdout("generator_memoryview_index", """\
def g(data):
    yield memoryview(data)[0]
    yield memoryview(data)[2]

def main():
    var b = bytes([10, 20, 30])
    for x in g(b):
        print(x)
""", "10\n30\n")

    test_generator_stdout("generator_bytes_literal_iteration", """\
def g():
    var b = bytes([1, 2, 3])
    for x in b:
        yield x * 2

def main():
    for x in g():
        print(x)
""", "2\n4\n6\n")

    test_generator_stdout("generator_bytearray_mutation", """\
def g():
    var ba = bytearray()
    ba.append(5)
    ba.append(7)
    yield ba[0]
    yield ba[1]
    yield len(ba)

def main():
    for x in g():
        print(x)
""", "5\n7\n2\n")

    # A @classmethod generator that builds a memoryview over an
    # unannotated (bytes) parameter and iterates it -- the shape of
    # zipfile's `_Extra.split` (bugs/COMPILE_FAIL_zipfile___init__.md).
    # Newly A3-eligible (gimple_gen_coro._eligible classmethod path).
    test_generator_stdout("generator_classmethod_memoryview", """\
struct E:
    @classmethod
    def split(cls, data):
        var mv = memoryview(data)
        var i = 0
        while i < len(mv):
            yield mv[i]
            i = i + 1

def main():
    for x in E.split(bytes([4, 5, 6])):
        print(x)
""", "4\n5\n6\n")

    test_generator_stdout("generator_classmethod_scalar", """\
struct C:
    @classmethod
    def upto(cls, n: Int):
        var i = 0
        while i < n:
            yield i * i
            i = i + 1

def main():
    for x in C.upto(4):
        print(x)
""", "0\n1\n4\n9\n")

    # ── "cluster B": heterogeneous / tagged tuple-yield value model ────────
    # A stack-switch generator whose tuple `yield`s carry a slot that is a
    # different scalar kind at different yield sites, and/or a `None` in a
    # slot, and/or a list-valued slot. The A3 backend unifies each slot's
    # type across every yield site (`_generator_tuple_slots`) and the
    # consumer unpacks per-slot through the runtime list getters
    # (`_emit_generator_tuple_unpack`). Regression coverage for
    # bugs/CODEGEN_generator_function_Lib_{modulefinder,pickletools,os,
    # test_test_string_test_string}.md — the outer-tuple-slot half of that
    # cluster. (Nested-tuple slots with heterogeneous inner elements remain
    # honestly refused — see the modulefinder doc.)

    # str | None slot: `is None` on the nil slot must test true.
    test_generator_stdout("gen_tuple_slot_str_or_none", """\
def parse(n: Int):
    yield "lit", "field", "spec"
    yield "tail", None, None

def main():
    for text, name, spec in parse(1):
        print(text)
        if name is None:
            print("<none>")
        else:
            print(name)
""", "lit\nfield\ntail\n<none>\n")

    # list-valued slots (os.walk's `(dirpath, dirnames, filenames)` shape).
    test_generator_stdout("gen_tuple_slot_list_valued", """\
def walk(n: Int):
    var d1 = ["sub"]
    var f1 = ["a", "b"]
    yield "root", d1, f1
    var d2 = ["x", "y"]
    var f2 = ["c"]
    yield "root/sub", d2, f2

def main():
    for path, dirs, files in walk(1):
        print(path)
        for x in dirs:
            print(x)
        for x in files:
            print(x)
""", "root\nsub\na\nb\nroot/sub\nx\ny\nc\n")

    test_generator_stdout("gen_tuple_mixed_arity_preserves_length", """\
def pairs(wide):
    if wide:
        yield 1, 2, 3
    else:
        yield 4, 5, 6, 7

def main():
    for row in pairs(True):
        print(len(row))
    for a, b, c in pairs(True):
        print(a, b, c)
    for a, b, c, d in pairs(False):
        print(a, b, c, d)
""", "3\n1 2 3\n4 5 6 7\n")

    # ── Generator EXPRESSIONS ────────────────────────────────────────────
    # `(x * 2 for x in xs)` is a real lazy generator on BOTH paths now:
    # fire_compiler.desugar_genexps rewrites it into a call to a
    # synthesized module-level generator FUNCTION (sharing
    # fire_compiler.genexp_body with the interpreter's own
    # MojoGeneratorObject path), instead of the eager list this used to
    # materialize. Laziness is observable: an unbounded source consumed
    # with an early `break` must terminate and produce only what was read.

    test_generator_stdout("genexp_values_and_condition", """\
def main():
    print(list(x * 2 for x in range(5) if x % 2 == 0))

main()
""", "[0, 4, 8]\n")

    test_generator_stdout("genexp_is_lazy_early_break_over_unbounded_source", """\
def main():
    out = []
    for x in (i * i for i in range(1000000)):
        out.append(x)
        if len(out) == 3:
            break
    print(out)

main()
""", "[0, 1, 4]\n")

    test_generator_stdout("genexp_nested_for_clauses", """\
def main():
    print(list(a * 10 + b for a in [1, 2] for b in [3, 4] if b != 3))

main()
""", "[14, 24]\n")

    # A name the enclosing function reads is CAPTURED as a parameter of the
    # synthesized generator, so the arithmetic in the body still sees a
    # real typed value (not an erased box).
    test_generator_stdout("genexp_captures_enclosing_local", """\
def scaled(k):
    out = []
    for v in (x * k for x in [1, 2, 3]):
        out.append(v)
    return out

def main():
    print(scaled(10))

main()
""", "[10, 20, 30]\n")

    # ... and a MODULE-level name is read directly by the hoisted function
    # (no parameter, so no type is lost through one).
    test_generator_stdout("genexp_over_module_level_iterable", """\
DATA = [5, 6, 7]

def main():
    print(list(x + 1 for x in DATA))

main()
""", "[6, 7, 8]\n")

    test_generator_stdout("genexp_string_elements", """\
def main():
    print(list(s + "!" for s in ["a", "b"]))

main()
""", "['a!', 'b!']\n")

    # The unparenthesized sole-argument form (`sum(x for x in ...)`), whose
    # argument is a generator: consumes it through the shared
    # `_materialize_as_list` chokepoint's new MojoGenerator* case, which
    # drains it via its own resume/value/destroy API.
    test_generator_stdout("genexp_passed_to_sum_builtin", """\
def main():
    print(sum(x * 2 for x in [1, 2, 3]))

main()
""", "12\n")

    # `any`/`all`/`max` route through the same chokepoint. (Printed via
    # int(...) because this path's `print` renders a bool as 1/0 — the same
    # for a plain list, so what is under test is the genexp being consumed
    # at all, not bool formatting.)
    test_generator_stdout("genexp_passed_to_any_all_max", """\
def main():
    print(int(any(x > 2 for x in [1, 2, 3])))
    print(int(all(x > 0 for x in [1, 2, 3])))
    print(max(x for x in [3, 1, 2]))

main()
""", "1\n1\n3\n")

    # A generator expression nested inside another one: the inner one is
    # desugared first (bottom-up) and the outer hoisted function calls it.
    # The outer's ELEMENT must be a scalar — a compiled generator's value
    # slot carries scalars only, so a generator that yields a container
    # (including a nested genexp's list) is a pre-existing limitation of
    # the generator value model, not of this desugaring.
    test_generator_stdout("genexp_nested_inside_genexp", """\
def main():
    print(list(sum(y for y in range(x)) for x in [2, 3]))

main()
""", "[1, 3]\n")

    # ── The generator protocol: send() ───────────────────────────────────
    # `g.send(v)` resumes the generator, handing it `v` as the value of the
    # `yield` it is suspended on. Before this it was read as a FIELD access
    # on the generator object and emitted a call to an undefined
    # `_MojoGenerator_send` symbol, so any use of it failed to link.

    test_generator_stdout("generator_send_resumes_with_value", """\
def echo():
    x = yield 1
    yield x * 2

def main():
    g = echo()
    print(next(g))
    print(g.send(21))

main()
""", "1\n42\n")

    # send() into a string-valued (`value_kind` 'p') generator.
    test_generator_stdout("generator_send_string_value", """\
def gen():
    who = yield "ready"
    yield "hello " + who

def main():
    g = gen()
    print(next(g))
    print(g.send("world"))

main()
""", "ready\nhello world\n")

    # ... and into a double-valued ('d') one, whose value slot carries the
    # raw 64 bits (bit-cast, exactly like a yielded double).
    test_generator_stdout("generator_send_double_value", """\
def gen():
    got = yield 1.5
    yield got * 2.0

def main():
    g = gen()
    print(next(g))
    print(g.send(3.0))

main()
""", "1.5\n6.0\n")

    # A bare `next(g)` statement — the value-discarding form. The
    # statement-level dispatch skipped the generator `next` entirely and
    # emitted a call to a `next` function that exists nowhere.
    test_generator_stdout("generator_bare_next_statement", """\
def gen():
    yield 1
    yield 2

def main():
    g = gen()
    next(g)
    next(g)
    try:
        next(g)
        print("no stop")
    except StopIteration:
        print("stopped")

main()
""", "stopped\n")

    # A generator expression over a PARAMETER of the enclosing function is
    # desugared into a generator function whose own parameter carries that
    # parameter's declared annotation — the declaration is authoritative, so
    # the body types its loop variable from it instead of guessing from a
    # runtime tag (which is what made the untyped-parameter form degrade to
    # `char *` string arithmetic on a list of ints).
    test_generator_stdout("genexp_over_annotated_param_with_capture", """\
def scaled(items: List[Int], k: Int):
    return list(x * k for x in items)

def main():
    print(scaled([1, 2, 3], 10))

main()
""", "[10, 20, 30]\n")

    test_generator_stdout("genexp_over_annotated_param_with_condition", """\
def evens(items: List[Int]):
    return list(x * 2 for x in items if x % 2 == 0)

def main():
    print(evens([1, 2, 3, 4]))

main()
""", "[4, 8]\n")

    # ... and it is a REAL lazy generator, not a materialized list: the
    # element expression's side effect runs once per item actually
    # consumed, so an early `break` leaves the rest unevaluated.
    # (A struct RECEIVER inside the expression — `(c.note(i) for i in ...)`
    # — is deliberately NOT desugared: the coroutine body has no working
    # model for it and lowered to garbage. Pinned as a refusal below.)
    test_generator_stdout("genexp_is_lazy_not_materialized", """\
SEEN = []

def note(v: Int) -> Int:
    SEEN.append(v)
    return v * v

def main():
    out = []
    for x in (note(i) for i in range(1000)):
        out.append(x)
        if len(out) == 3:
            break
    print(out)
    print(len(SEEN))

main()
""", "[0, 1, 4]\n3\n")

    # A generator consumed by enumerate(): the pair list is built from the
    # materialized generator, so the indices are real (and the generator
    # expression path underneath is lazy).
    test_generator_stdout("enumerate_over_generator", """\
def nums():
    yield 7
    yield 8

def main():
    print(list(enumerate(nums())))

main()
""", "[(0, 7), (1, 8)]\n")

    # ── The rest of the protocol: throw() / close() ─────────────────────
    # Both inject an exception INTO the suspended body. This only became
    # expressible once `try/finally` ran its finally on the EXCEPTION path
    # too (previously a `finally` in a generator body was skipped on every
    # non-normal exit, so there was no cleanup for close() to run) and once
    # the runtime's close helper swallowed the GeneratorExit it throws
    # instead of letting it escape past the caller.
    #
    # NOTE: every generator here yields ONE value kind. A generator that
    # yields two DIFFERENT kinds (e.g. an int then a string) is refused by
    # the compiled value model — its slot is typed from the yields as a
    # whole, so the mismatch used to SEGFAULT the compiler. It is unrelated
    # to throw/close (such a generator is unreachable without them), and
    # these tests are about a single kind. See
    # `generator_mixed_yield_kinds_*` below for the mixed-kind shape.

    test_generator_stdout("generator_throw_caught_inside_generator", """\
def gen():
    try:
        yield 1
    except ValueError:
        yield 99

def main():
    g = gen()
    print(next(g))
    print(g.throw(ValueError("x")))

main()
""", "1\n99\n")

    # An exception the generator does NOT catch propagates to the CALLER,
    # where an enclosing `except` sees it — and the generator's `finally`
    # still runs on the way out.
    test_generator_stdout("generator_throw_propagates_to_caller", """\
def gen():
    try:
        yield 1
        yield 2
    finally:
        print("cleanup")

def main():
    g = gen()
    print(next(g))
    try:
        g.throw(ValueError("x"))
        print("not reached")
    except ValueError:
        print("caught")
    print("after")

main()
""", "1\ncleanup\ncaught\nafter\n")

    test_generator_stdout("generator_close_runs_finally_cleanup", """\
def gen():
    try:
        yield 1
        yield 2
    finally:
        print("cleanup")

def main():
    g = gen()
    print(next(g))
    g.close()
    print("after")

main()
""", "1\ncleanup\nafter\n")

    # close() on an already-exhausted generator is a no-op, and afterwards
    # the generator really is finished (next() raises StopIteration).
    test_generator_stdout("generator_close_on_exhausted_is_noop", """\
def gen():
    yield 1

def main():
    g = gen()
    print(next(g))
    g.close()
    g.close()
    try:
        next(g)
        print("no stop")
    except StopIteration:
        print("stopped")

main()
""", "1\nstopped\n")

    # `g.throw(ValueError)` with no instance is `ValueError()` — real
    # Python's own normalization — and propagates like any other.
    test_generator_stdout("generator_throw_bare_exception_class", """\
def gen():
    while True:
        yield 1

def main():
    g = gen()
    print(next(g))
    try:
        g.throw(ValueError)
        print("not reached")
    except ValueError:
        print("caught")

main()
""", "1\ncaught\n")

    # An argument that is not an exception class is refused honestly rather
    # than guessed at.
    test_generator_refused("generator_throw_non_exception_refused", """\
def gen():
    yield 1

def main():
    g = gen()
    print(next(g))
    g.throw(42)

main()
""", "expected an exception class name")

    # ── Standard consumers of a generator ────────────────────────────────
    # `sorted()` / `zip()` used to hand their runtime helpers the generator
    # handle itself (every one of those helpers walks a MojoList), which
    # read a coroutine object as a list header — a hard crash. Both now go
    # through the shared `_materialize_as_list` chokepoint, and `zip`'s
    # result is a real MojoList* of pair-lists rather than an opaque void*.

    # (No `key=` here: the compiled `sorted` ignores a key function for
    # EVERY input type, lists included — a pre-existing, non-generator gap.
    # This test is about the generator being consumable at all.)
    test_generator_stdout("sorted_over_generator", """\
def nums():
    yield 3
    yield 1
    yield 2

def main():
    print(sorted(nums()))

main()
""", "[1, 2, 3]\n")

    test_generator_stdout("sorted_generator_expression", """\
def main():
    print(sorted(x * 2 for x in [3, 1, 2]))

main()
""", "[2, 4, 6]\n")


    test_generator_stdout("zip_over_generator_for_loop", """\
def left():
    yield 1
    yield 2

def main():
    for x, y in zip(left(), [3, 4]):
        print(x, y)

main()
""", "1 3\n2 4\n")

    # ── a generator CONSUMING a sibling generator ──────────────────────────
    # `_static_env` is the purely-syntactic name -> yield-kind map that
    # decides a generator's `value_ctype`, and its for-loop branch only knew
    # list-typed locals and list literals. A `for f in <sibling gen>():`
    # iterable is a CallExpr, so the loop target got no entry, `yield f`
    # inferred None, and the consumer's OWN value_ctype fell to the int64_t
    # default. The bytes were always right — only the static type was lost —
    # so this printed the yielded string's ADDRESS as a decimal integer,
    # exit 0, and the wrong value_ctype was registered for every downstream
    # consumer, compounding along a chain. The `yield from` twin of this was
    # already resolved; this is the consuming twin. See
    # `_sibling_gen_kind` in mojo/middle/coro.py for the mechanism.

    # the minimal case: one hop. Used to print a pointer's bit pattern.
    test_generator_stdout("generator_consuming_generator_string_kind", """\
def inner():
    yield "a.txt"

def outer(g):
    for f in inner():
        if f.endswith(".txt"):
            yield f

def main():
    for v in outer("x"):
        print(v)

main()
""", "a.txt\n")

    # THREE hops, plus a double-yielding callee. The chain is the point:
    # the defect compounded, so one hop would not have caught a fix that
    # only repaired the immediate callee. The `double` is the OTHER wrong
    # answer from the same root cause — an int64_t slot truncating a float
    # to 2 rather than a pointer printed as an address — so it pins the
    # fix as being about the KIND, not about strings specifically.
    test_generator_stdout("generator_consumption_chain_and_float_kind", """\
def leaf():
    yield "deep.txt"

def mid():
    for x in leaf():
        yield x

def top():
    for x in mid():
        yield x

def half():
    yield 2.5

def wrap():
    for x in half():
        yield x

def main():
    for v in top():
        print(v)
    for w in wrap():
        print(w)

main()
""", "deep.txt\n2.5\n")

    # A generator METHOD consuming a module-level sibling, and a consumer
    # whose yield is a DERIVED value rather than the loop target itself.
    # The derived case is the interesting one: `_yield_kind`'s BinaryOp
    # branch reported 'p' for `f + "!"` even while the loop target `f` was
    # untyped, so it came out RIGHT by accident and would have kept passing
    # under a narrower fix.
    test_generator_stdout("generator_method_consuming_generator_kind", """\
def leaf():
    yield "one.txt"
    yield "two.txt"

def derived():
    for f in leaf():
        yield f + "!"

class Box:
    def __init__(self):
        self.items = 0
    def take(self):
        for f in leaf():
            self.items = self.items + 1
            yield f

def main():
    for w in derived():
        print(w)
    b = Box()
    for z in b.take():
        print(z)
    print(b.items)

main()
""", "one.txt!\ntwo.txt!\none.txt\ntwo.txt\n2\n")

    # ── a nested `async def` capturing an enclosing PARAMETER ───────────
    # The capture-plan producer for a captured PARAMETER built a 2-tuple while
    # the three consumers in `_apply_nested_async_capture` unpacked
    # 3-tuples, so every annotated-parameter capture raised
    # `ValueError: not enough values to unpack (expected 3, got 2)` out of
    # the compiler -- on a feature that had been separately recorded as
    # already-landed. Asserted on STDOUT, not on the generated C: the C
    # cannot distinguish a right value from a plausible wrong one here (the
    # bug doc makes that point about the struct-capture test that shipped
    # with it), and "does not raise" would have passed against a plan that
    # silently dropped the mutation.
    test_generator_stdout("nested_async_captures_enclosing_param_int", """\
def run(seed: Int) raises:
    @parameter
    async def bump():
        seed += 2
    var t0 = create_task(bump())
    t0.wait()
    print(seed)

def main():
    run(10)
""", "12\n")

    # ... and the same shape for the other two boxable scalar param kinds
    # plus a struct local in the SAME nested async, which is the case that
    # mixes both plan producers: before the plan entries were a named shape,
    # the struct local's 3-tuple and the parameter's 2-tuple met in one
    # `cap_map` and the pass that unpacked them could not tell which was
    # which.
    test_generator_stdout("nested_async_captures_param_and_struct_local", """\
class Point:
    def __init__(self, x):
        self.x = x

def run(n: Int, ratio: Float64, tag: String) raises:
    var p = Point(1)

    @parameter
    async def bump():
        n += 1
        ratio += 1.0
        tag += "b"
        p.x += 1

    var t0 = create_task(bump())
    t0.wait()
    print(n, ratio, tag, p.x)

def main():
    run(1, 1.0, "a")
""", "2 2.0 ab 2\n")

    # ── TWO nested asyncs capturing the SAME enclosing local ────────────
    # The mechanism: `_apply_nested_async_capture` is
    # called ONCE PER nested async, and it rewrites the enclosing local's
    # initializer IN PLACE. So the second nested async's capture plan saw
    # `var n = __mojo_box_new_i64(1)` -- an initializer it could not type
    # -- concluded the capture was unboxable, and dropped that async to
    # the C++ backend, which has no capture model at all and threaded a
    # capture parameter into `{base}_start` that the `create_task` call
    # site never passed:
    #
    #     prog.mojo:13:10: error: too few arguments to function
    #     '_mojoasync_run_a2_start'; expected 1, have 0
    #
    # A hard error blaming generated code, for a shape that is a two-line
    # variant of one that already worked. It is also the shape where the
    # naive repair is a silent wrong VALUE rather than a loud one: boxing
    # the local a second time allocates a second cell, and re-running the
    # enclosing-body rewrite wraps every read twice
    # (`__mojo_box_get_i64(__mojo_box_get_i64(n))` -- reading the box
    # POINTER as its contents, i.e. a heap address), which prints instead
    # of erroring. Hence the plan now recognises an already-boxed local
    # and the wiring is idempotent per captured name.
    test_generator_matches_cpython("two_nested_asyncs_share_one_captured_local", """\
def run() raises:
    var n = 1

    @parameter
    async def a1():
        n += 1

    @parameter
    async def a2():
        n += 1

    var t0 = create_task(a1())
    t0.wait()
    var t1 = create_task(a2())
    t1.wait()
    print(n)

def main() raises:
    run()
""", """\
import asyncio

async def run():
    n = 1

    async def a1():
        nonlocal n
        n += 1

    async def a2():
        nonlocal n
        n += 1

    await a1()
    await a2()
    print(n)

asyncio.run(run())
""")

    # Three, over all three boxable kinds AND a struct cell, so the shared
    # box is exercised for every `_BOX_SHIMS` entry plus Increment E's
    # pointer round-trip -- the struct case is the one where a second cell
    # would not merely lose the write but leave the two nested bodies with
    # incompatible element types.
    test_generator_matches_cpython("three_nested_asyncs_share_mixed_captures", """\
struct Point:
    var x: Int
    fn __init__(out self, x: Int):
        self.x = x

def run(seed: Int, ratio: Float64, tag: String) raises:
    var p = Point(0)

    @parameter
    async def a1():
        seed += 1
        ratio += 1.0
        tag += "b"
        p.x += 1

    @parameter
    async def a2():
        seed += 10
        ratio += 10.0
        tag += "c"
        p.x += 10

    @parameter
    async def a3():
        seed += 100
        ratio += 100.0
        tag += "d"
        p.x += 100

    var t0 = create_task(a1())
    t0.wait()
    var t1 = create_task(a2())
    t1.wait()
    var t2 = create_task(a3())
    t2.wait()
    print(seed, ratio, tag, p.x)

def main() raises:
    run(1, 1.0, "a")
""", """\
import asyncio

class Point:
    def __init__(self, x):
        self.x = x

async def run(seed, ratio, tag):
    p = Point(0)

    async def a1():
        nonlocal seed, ratio, tag, p
        seed += 1
        ratio += 1.0
        tag += "b"
        p.x += 1

    async def a2():
        nonlocal seed, ratio, tag, p
        seed += 10
        ratio += 10.0
        tag += "c"
        p.x += 10

    async def a3():
        nonlocal seed, ratio, tag, p
        seed += 100
        ratio += 100.0
        tag += "d"
        p.x += 100

    await a1()
    await a2()
    await a3()
    print(seed, ratio, tag, p.x)

asyncio.run(run(1, 1.0, "a"))
""")

    # The cross-closure shape (the doc's item 4) with a SECOND nested async
    # in the mix: the shared box is threaded through the ordinary nested
    # sibling `caller()`, which calls both. This is where the hidden
    # trailing parameter is declared per sibling, so a second pass that
    # appended it again would produce a duplicated declaration.
    test_generator_matches_cpython("two_nested_asyncs_shared_capture_through_sibling", """\
def run(n: Int) raises:
    @parameter
    async def a1():
        n += 1

    @parameter
    async def a2():
        n += 1

    def caller() raises:
        var t = create_task(a1())
        t.wait()
        var u = create_task(a2())
        u.wait()

    caller()
    print(n)

def main() raises:
    run(0)
""", """\
import asyncio

async def run(n):
    async def a1():
        nonlocal n
        n += 1

    async def a2():
        nonlocal n
        n += 1

    async def caller():
        await a1()
        await a2()

    await caller()
    print(n)

asyncio.run(run(0))
""")

    # A nested async that captures NOTHING beside one that does: the
    # non-capturing one must be unaffected by the shared-box bookkeeping
    # (it has an empty plan, so it must neither claim the name nor have a
    # hidden parameter added).
    test_generator_matches_cpython("capturing_and_noncapturing_nested_async", """\
def run() raises:
    var n = 0

    @parameter
    async def noop():
        pass

    @parameter
    async def bump():
        n += 1

    var t0 = create_task(noop())
    t0.wait()
    var t1 = create_task(bump())
    t1.wait()
    var t2 = create_task(bump())
    t2.wait()
    print(n)

def main() raises:
    run()
""", """\
import asyncio

async def run():
    n = 0

    async def noop():
        pass

    async def bump():
        nonlocal n
        n += 1

    await noop()
    await bump()
    await bump()
    print(n)

asyncio.run(run())
""")

    # ── call-site yield-kind evidence: the holes and the fixes ─────────
    # bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md. A call
    # site the static scan cannot type used to leave the slot neither
    # resolved nor conflicting, so the yield slot defaulted to int64_t and
    # truncated (or printed an address) with exit 0. It now propagates
    # through the caller's own unannotated parameter instead, because the
    # same whole-module scan that types a generator's params also types an
    # ordinary function's -- and the synthesized generator-expression body
    # is a module-level generator called with its ENCLOSING function's
    # parameters, which is the shape below.
    test_generator_stdout("generator_callsite_through_unannotated_caller_param", """\
def g(x):
    yield x

def caller(v):
    for r in g(v):
        print(r)

def main():
    for r in g(3.5):
        print(r)
    caller(9.5)
""", "3.5\n9.5\n")

    # The same route with a STRING, which is the case that used to print
    # the pointer's own address as a decimal (measured 4340503928) rather
    # than the string.
    test_generator_stdout("generator_callsite_string_through_caller_param", """\
def g(x):
    yield x

def caller(v):
    for r in g(v):
        print(r)

def main():
    caller("hi")
""", "hi\n")

    # `self.<field>` at a CALL site: `_scan_callsite_param_kinds` used to
    # build the caller's env with no `struct_def`, so `g(self.k)` was
    # untypable inside every method even with `k: Float64` in the class
    # body -- a hole, hence (before the hole rule) a silent int64_t slot
    # printing `3`.
    test_generator_stdout("generator_callsite_self_field_kind", """\
class C:
    def __init__(self, k: Float64):
        self.k = k

    def go(self):
        for r in g(self.k):
            print(r)

def g(x):
    yield x

def main():
    var c = C(3.5)
    c.go()
""", "3.5\n")

    # A hole that genuinely cannot be closed, refused rather than
    # miscompiled -- and refused even though a SECOND, textbook-resolvable
    # call site (`g(3.5)`) is right there in the module. That combination
    # is the doc's sharpest claim: the old rule dropped the untypable
    # argument's `None` and let the surviving literal evidence resolve the
    # slot, so a program with a clean float call site still truncated
    # whenever one other caller was opaque. Here the opaque argument is a
    # call to a function whose return is computed rather than a literal,
    # which no amount of widening reaches -- there is no evidence to widen
    # into -- and a computed return could be a float.
    test_generator_refused("generator_callsite_untypable_argument_refused", """\
def pick(a, b):
    return a

def g(x):
    yield x

def main():
    for r in g(3.5):
        print(r)
    for r in g(pick(1, 2)):
        print(r)
""", "yields ['x'], whose call sites do not all pass the same")

    _foreign_a3_generator_handle_next()
    _foreign_a3_generator_handle_for_loop()
    _foreign_cpp_module_global_value()
    _cpp_for_over_callable_local_is_named()
    _cpp_coroutine_builtin_module_constant()
    _cpp_coroutine_exc_ctor_value()

    # ── `async for` over a compiled async generator, driven by an ORDINARY
    # function. An async generator is consumed by `async for`, and the
    # consumer need not be a coroutine itself: real Python lets an ordinary
    # `async def`-less function do it, and the doc's own repro does exactly
    # that. This compiler had no lowering for that consumer at all --
    # `_gen_for_iter` saw a `MojoGenerator *` it could not resolve to a
    # generator api (a NESTED `async def gen()`'s call site is rewritten by
    # coro.py to the qualified `__mgco_outer_gen_start`, which no
    # bare-name `_generator_api` lookup can see) and dropped the loop body
    # with a `mojo_unsupported_iter` warning: CPython printed 11, the
    # compiled program printed 0, exit 0, no error.
    #
    # Every case below is asserted against CPython run on a reference twin
    # AT TEST TIME (`test_generator_matches_cpython`), because every
    # failure mode in this area is a silent wrong value and a
    # hand-transcribed "expected" string is exactly how one gets enshrined.
    test_generator_matches_cpython("nested_async_gen_driven_by_async_for", """\
def outer() raises:
    var acc = 0

    async def gen():
        acc = acc + 1
        yield 10

    async for x in gen():
        acc = acc + x
    print(acc)

def main() raises:
    outer()
""", """\
import asyncio

async def outer():
    acc = 0

    async def gen():
        nonlocal acc
        acc = acc + 1
        yield 10

    async for x in gen():
        acc = acc + x
    print(acc)

asyncio.run(outer())
""")

    # The no-capture neighbour, which is the doc's own attribution check:
    # the same wrong `0` appeared with no capture at all, so the defect was
    # the loop lowering, not the capture boxing. It must be driven here too
    # (this one already worked via the bare-name path -- the nested one did
    # not -- which is exactly why both are here).
    test_generator_matches_cpython("nested_async_gen_multiple_yields", """\
def outer() raises:
    var acc = 0

    async def gen():
        yield 3
        yield 4
        yield 5

    async for x in gen():
        acc = acc + x
    print(acc)

def main() raises:
    outer()
""", """\
import asyncio

async def outer():
    acc = 0

    async def gen():
        yield 3
        yield 4
        yield 5

    async for x in gen():
        acc = acc + x
    print(acc)

asyncio.run(outer())
""")

    # `break` inside the driven loop, plus a STRING capture in the same
    # generator, so the drive loop is exercised alongside a non-int box kind.
    test_generator_matches_cpython("nested_async_gen_async_for_with_break", """\
def outer() raises:
    var acc = 0
    var msg = String("a")

    async def gen():
        msg += "b"
        yield 7
        yield 8
        yield 9

    async for x in gen():
        if x == 8:
            break
        acc = acc + x
    print(acc, msg)

def main() raises:
    outer()
""", """\
import asyncio

async def outer():
    acc = 0
    msg = "a"

    async def gen():
        nonlocal msg
        msg += "b"
        yield 7
        yield 8
        yield 9

    async for x in gen():
        if x == 8:
            break
        acc = acc + x
    print(acc, msg)

asyncio.run(outer())
""")

    # A TOP-LEVEL async generator driven the same way: already worked (its
    # call site does reach the bare-name `_generator_api` path), kept as the
    # control that the nested fix did not change the existing route.
    test_generator_matches_cpython("toplevel_async_gen_driven_by_async_for", """\
async def gen():
    yield 3
    yield 4

def outer() raises:
    var acc = 0
    async for x in gen():
        acc = acc + x
    print(acc)

def main() raises:
    outer()
""", """\
import asyncio

async def gen():
    yield 3
    yield 4

async def outer():
    acc = 0
    async for x in gen():
        acc = acc + x
    print(acc)

asyncio.run(outer())
""")

    # ── the wait-descriptor boundary ────────────────────────────────────
    # A coroutine's yield channel carries EITHER a real value (`yield e`)
    # OR a wait-descriptor (every parking `await`, is_wd=1) -- see
    # mojo_coro.h. An ordinary function has no channel of its own to
    # forward a descriptor into, so a descriptor reaching it would be
    # BOUND AS THE LOOP VARIABLE. Measured before this was fixed: a
    # generator that awaited `asyncio.sleep(0)` and then yielded 10 printed
    # a heap ADDRESS instead of 10, exit 0, no diagnostic -- a real silent
    # miscompile, on the top-level route as much as the nested one.
    #
    # It is now a compile-time REFUSAL, which is what the C++ backend has
    # always done for this consumer shape (there, for an unrelated reason:
    # `async for` is only legal inside an async body). Deliberately NOT
    # special-cased on the input -- the question asked is the fixed point of
    # "can this body ever park", so the next case shows the analysis is not
    # simply "any await at all".
    test_generator_refused("async_for_over_parking_async_gen_refused", """\
import asyncio

async def gen():
    await asyncio.sleep(0)
    yield 10

def outer() raises:
    var acc = 0
    async for x in gen():
        acc = acc + x
    print(acc)

def main() raises:
    outer()
""", "ordinary function")

    # ... and the same through a nested generator, i.e. the case the new
    # call-site registration newly made reachable at all.
    test_generator_refused("async_for_over_nested_parking_async_gen_refused", """\
import asyncio

def outer() raises:
    var acc = 0

    async def gen():
        await asyncio.sleep(0)
        yield 10

    async for x in gen():
        acc = acc + x
    print(acc)

def main() raises:
    outer()
""", "ordinary function")

    # A generator whose awaits are all of a coroutine that provably never
    # parks is driven for real: `await clean()` lowers to an inline nested
    # drive loop whose resume never yields a descriptor, so the fixed point
    # resolves this body to "never forwards" and the loop is complete. If
    # the analysis were only "contains an await", this would be refused --
    # which is why it is here, as the counterweight to the two above.
    test_generator_matches_cpython("async_for_over_nonparking_await", """\
async def clean() -> Int:
    return 5

async def gen():
    await clean()
    yield 10

def outer() raises:
    var acc = 0
    async for x in gen():
        acc = acc + x
    print(acc)

def main() raises:
    outer()
""", """\
import asyncio

async def clean():
    return 5

async def gen():
    await clean()
    yield 10

async def outer():
    acc = 0
    async for x in gen():
        acc = acc + x
    print(acc)

asyncio.run(outer())
""")

    # The fixed point has to be a GREATEST one, or mutual recursion is a
    # hole: `a` awaits `b` and `b` parks, so neither is channel-free, so
    # driving `a` from an ordinary function cannot forward `b`'s descriptor.
    # Under a least fixed point each would conclude the other is clean and
    # this would compile to the heap-address answer again.
    test_generator_refused("async_for_over_mutually_awaiting_gen_refused", """\
import asyncio

async def a():
    await b()
    yield 1

async def b():
    await asyncio.sleep(0)
    return 0

def outer() raises:
    var acc = 0
    async for x in a():
        acc = acc + x
    print(acc)

def main() raises:
    outer()
""", "ordinary function")

    # The OTHER consumer of the same channel. `next(g)` is lowered by
    # `_lower_generator_next`, a different function in a different file, and
    # it was left unguarded -- so the same generator printed a heap ADDRESS
    # for the first `next(g)`, then the right 10 for the second, exit 0, no
    # diagnostic. One question ("can this coroutine ever put a
    # wait-descriptor on its channel?"), so one analysis, asked of each
    # consumer in turn rather than duplicated per lowering.
    test_generator_refused("next_on_parking_async_gen_refused", """\
import asyncio

async def gen():
    await asyncio.sleep(0)
    yield 10
    yield 20

def outer() raises:
    var g = gen()
    print(next(g))
    print(next(g))

def main() raises:
    outer()
""", "`next()` on async generator")

    # ... and the same loop driver over a plain (non-`async`) `for`. A
    # `TypeError` in CPython, so there is no correct answer to preserve
    # here -- only the silent garbage to remove.
    test_generator_refused("plain_for_over_parking_async_gen_refused", """\
import asyncio

async def gen():
    await asyncio.sleep(0)
    yield 10

def outer() raises:
    for x in gen():
        print(x)

def main() raises:
    outer()
""", "ordinary function")

    # The control for both: the same two spellings over a generator that
    # provably never parks keep working, so the guard is on the analysis
    # rather than on the syntax.
    test_generator_matches_cpython("next_and_plain_for_over_clean_async_gen", """\
async def gen():
    yield 10
    yield 20

def outer() raises:
    var g = gen()
    print(next(g))
    for x in g:
        print(x)

def main() raises:
    outer()
""", """\
import asyncio

async def gen():
    yield 10
    yield 20

async def outer():
    g = gen()
    print(await g.__anext__())
    async for x in g:
        print(x)

asyncio.run(outer())
""")

    # A nested async GENERATOR with NO captures of its own, driven by
    # `async for` from a sibling nested `async def`. The unthreadable-
    # call-site test used to run only for a generator that captured
    # something, so this one was hoisted -- and the call site inside the
    # sibling's hoisted body was left as the BARE `gen_start`, because
    # `_rewrite_asyncio_run_stmts` can only qualify a call that is still in
    # the enclosing function's own body, and a nested async's body has
    # been hoisted out of it by then. The program linked against a
    # `__mgco_gen_start` nothing defines, the call degraded to the
    # "unavailable in compiled mode" stub, and the loop consumed a
    # generator that never ran:
    #
    #     __mgco_gen_start: unavailable in compiled mode0    (CPython: 3)
    #
    # A refusal is the correct outcome here, and it is the one the
    # capturing version of this shape already got. (The C++ backend
    # compiles and runs this one correctly -- see
    # `nested_async_gen_no_capture_drive_compiles_on_cpp_backend` in
    # test_gimple.py -- because it needs no capture model, which is exactly
    # why the guard is not simply "driven by a nested async".)
    test_generator_refused("nested_captureless_gen_driven_by_nested_async_refused", """\
def outer() raises:
    var acc = 0

    async def gen():
        yield 1
        yield 2

    @parameter
    async def consume():
        async for x in gen():
            acc = acc + x

    var t = create_task(consume())
    t.wait()
    print(acc)

def main() raises:
    outer()
""", "cannot compile module")

    # bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md "Item 8", the
    # GENERATOR half: `for <t> in <list param>:` inside a generator. A
    # generator's params cross the stack-switch ABI as untyped `int64_t`
    # slots, so the loop reached the ordinary lowering as a boxed handle with
    # no container type and no element type; the runtime dict-or-list
    # dispatch's dict arm then won the shared `r` (dict keys are `char *`)
    # and the `double` yield slot could not be fed from it. Before the fix
    # this was an honest COMPILE ERROR ("pointer value used where a
    # floating-point was expected"); it now prints what CPython prints.
    #
    # Both element kinds are covered, and both are CPython-verified on the
    # identical program text.
    test_generator_stdout("generator_for_over_list_param_from_float_literal", """\
def rows(data):
    for r in data:
        yield r

def main():
    for v in rows([1.5, 2.5]):
        print(v)
""", "1.5\n2.5\n")

    # A string element was ALREADY correct before this change -- `char *` is a
    # pointer, so it satisfied the guard's old `_boxed_elem.endswith(' *')`
    # condition and the list path was taken. Pinned anyway, because the guard
    # is what this change widened and this is the half that used to depend on
    # the narrow form of it.
    test_generator_stdout("generator_for_over_list_param_from_str_literal", """\
def rows(data):
    for r in data:
        yield r

def main():
    for v in rows(["a", "b"]):
        print(v)
""", "a\nb\n")

    # Same shape through a list-typed LOCAL rather than a literal, so the
    # contract is read off the caller's env: the loop target's type must not
    # depend on how the caller spelled the list.
    test_generator_stdout("generator_for_over_list_param_from_local", """\
def rows(data):
    for r in data:
        yield r

def main():
    xs = [1.5, 2.5]
    for v in rows(xs):
        print(v)
""", "1.5\n2.5\n")

    # The dict arm must stay: a parameter with NO list evidence at all (here
    # the argument is a dict local, which the callsite scan cannot type into a
    # `('list', k)` answer) must keep the runtime dict-or-list dispatch, or
    # every `for k in <dict>` through a generator would silently iterate
    # nothing. This is the negative half of the guard above.
    test_generator_stdout("generator_for_over_unknown_param_still_dispatches", """\
def rows(data):
    for r in data:
        print(r)
    yield 0

def main():
    var d = {"k": 7}
    for v in rows(d):
        print(v)
""", "k\n0\n")

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()

    if _FAIL:
        print(f"\n{_PASS} passed, {_FAIL} failed")
        raise SystemExit(1)
    print(f"\n{_PASS} passed, {_FAIL} failed")


if __name__ == '__main__':
    run_tests()
