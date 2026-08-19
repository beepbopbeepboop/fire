"""REAL behavioral tests for the two closure-capture bugs documented in
bugs/CODEGEN_device_context_captured_function_parameter_closures_broken.md,
blocking std/gpu/host/device_context.mojo independent of async:

Repro 1 — a comptime FUNCTION-TYPED bracket parameter on a struct method,
called from a nested closure (`enqueue_cpu_function[func: def() capturing ->
None](self): def wrapper() capturing -> None: func() ...`), previously
lowered to a bogus, unresolved bare C identifier call (`func()`, declared via
a catch-all variadic extern) instead of the real bound callee — the bracket
argument was silently DROPPED at the `obj.method[X](...)` call site
(_lower_call's "Subscripted method call" branch unconditionally forwarded
without it).

Repro 2 — a runtime `FuncType`-parametrized closure argument (`def
enqueue_cpu_function[FuncType: def() -> None](self, func: FuncType): def
wrapper() capturing -> None: func() ...`) — the environment-struct capture
itself was fine, but the STATEMENT-level call to a captured function-pointer
variable (`func()` as its own statement, discarding the result) silently
evaluated the call's arguments and then dropped the call entirely
(_gen_stmt_ExprStmt's "stub it out" guard never actually emitted the
indirect-call helper _lower_call's identical guard already used).

Both are fixed in gimple_codegen.py:
  - _gen_stmt_ExprStmt's captured-function-pointer guard now calls
    _lower_fnptr_call instead of dropping the call (Repro 2).
  - A new _method_threaded_comptime_params mechanism threads a function-
    typed, actually-used comptime bracket method parameter through as an
    ordinary trailing C parameter, and the "obj.method[X](...)" call site
    forwards the bracket argument as an extra positional arg (Repro 1).

This compiles + links + RUNS the exact repros (not compile-only) via
driver.compile_program (mirrors test_comptime_bracket_params.py's harness)
and asserts on real stdout.
"""
import os
import subprocess
import tempfile

import driver
import gimple_codegen
from build_config import find_gcc

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')
GCC = find_gcc()

_PASS = 0
_FAIL = 0


def _build_and_run(mojo_src: str, filename: str = 'prog.mojo') -> str:
    wd = tempfile.mkdtemp(prefix='mojo_closure_capture_')
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


def _check_gcc_syntax_only(mojo_src: str, filename: str = 'prog.mojo') -> None:
    """Like compile_stdlib.py's own check (compile_module_to_c_cached +
    `gcc -fgimple -fsyntax-only`): proves the module compiles to valid C at
    all, without needing a full link+run — matching what actually broke
    (a hard "redefinition of parameter" gcc error) for the two overload-
    collision regressions this guards. Raises with the gcc stderr on
    failure."""
    c_code = gimple_codegen.compile_to_gimple(mojo_src, do_imports=False, filename=filename)
    wd = tempfile.mkdtemp(prefix='mojo_closure_capture_syntax_')
    c_path = os.path.join(wd, 'prog.c')
    with open(c_path, 'w') as f:
        f.write(c_code)
    r = subprocess.run([GCC, '-fgimple', f'-I{RUNTIME_DIR}', '-fsyntax-only', c_path],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"gcc -fgimple -fsyntax-only failed: {r.stderr}")


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def test_repro1_comptime_function_bracket_param_via_nested_closure():
    """The bug report's exact Repro 1: a comptime function-type bracket
    parameter, called only via a nested closure. Previously printed nothing
    useful (bogus unresolved `func()` call); now must print "ran"."""
    src = """\
struct Ctx:
    var api: String
    def __init__(out self):
        self.api = String("cpu")

    def enqueue_cpu_function[
        func: def() capturing -> None,
    ](self) raises:
        def wrapper() capturing -> None:
            func()
        wrapper()

fn func_impl():
    print("ran")

def main() raises:
    var c = Ctx()
    c.enqueue_cpu_function[func_impl]()
"""
    out = _build_and_run(src)
    check("Repro 1: c.enqueue_cpu_function[func_impl]() actually calls func_impl -> 'ran'",
          out == "ran\n", detail=repr(out))


def test_repro2_runtime_functype_closure_argument():
    """The bug report's exact Repro 2: an ordinary runtime FuncType-typed
    parameter captured into a nested closure and called as a bare statement.
    Previously the call was silently dropped (args evaluated, call never
    emitted); now must print "ran"."""
    src = """\
struct Ctx:
    var api: String
    def __init__(out self):
        self.api = String("cpu")

    def enqueue_cpu_function[
        FuncType: def() -> None,
    ](self, func: FuncType) raises:
        def wrapper() capturing -> None:
            func()
        wrapper()

fn func_impl():
    print("ran")

def main() raises:
    var c = Ctx()
    c.enqueue_cpu_function(func_impl)
"""
    out = _build_and_run(src)
    check("Repro 2: c.enqueue_cpu_function(func_impl) actually calls func_impl -> 'ran'",
          out == "ran\n", detail=repr(out))


def test_sibling_overloads_same_method_name_one_needs_threading_one_does_not():
    """Regression guard for the overload-collision bug found while fixing
    Repro 1 (std/memory/span.mojo's real shape, e.g. its two
    `binary_search_by` overloads): two methods sharing a name ON THE SAME
    STRUCT, only one of which has a function-typed comptime bracket
    parameter that's actually called — the other has an ordinary
    ``func``-named parameter typed by ITS OWN (never directly referenced)
    comptime type parameter. A name-only (not overload-id-scoped) key wrongly
    threaded the first overload's decision onto the second too, adding a
    duplicate ``func`` C parameter and producing a hard gcc redefinition
    error at COMPILE time — regardless of whether the second overload is
    ever actually called (struct methods compile unconditionally).

    Verifies compilation only (matching compile_stdlib.py's own `gcc
    -fgimple -fsyntax-only` check, which is exactly what the "redefinition
    of parameter" regression broke) rather than a full run: once this call
    site's bracket argument is appended as an extra positional arg (to match
    the threaded overload's real, AUGMENTED C signature), correctly picking
    between two sibling overloads whose AUGMENTED argument counts happen to
    coincide is a separate, pre-existing overload-resolution limitation
    this fix doesn't touch (_lower_method_call's dispatch matches by the
    ORIGINAL, pre-threading Mojo-level argument count) — not exercised
    here."""
    src = """\
struct Box:
    var tag: String
    def __init__(out self):
        self.tag = String("box")

    def apply[
        func: def(Int) -> Int,
    ](self, x: Int) -> Int:
        def wrapper() capturing -> Int:
            return func(x)
        return wrapper()

    def apply[
        FuncType: def(Int) -> Int,
    ](self, func: FuncType, x: Int, y: Int) -> Int:
        return func(x) + y

fn double_it(x: Int) -> Int:
    return x * 2

def main() raises:
    var b = Box()
    print(b.apply[double_it](21))
"""
    _check_gcc_syntax_only(src)
    check("sibling overloads (one threaded, one not) both compile cleanly (no duplicate-parameter error)",
          True)


def test_sibling_methods_same_name_different_structs():
    """Regression guard for the cross-STRUCT collision bug found while
    fixing Repro 1 (std/builtin/variadics.mojo's real shape): two UNRELATED
    structs each define a method with the same name, only one of which has a
    function-typed comptime bracket parameter that's actually called. A
    struct-name-blind key wrongly threaded one struct's decision onto the
    other's same-named (but ordinary) method, duplicating a parameter."""
    src = """\
struct Alpha:
    var a: Int
    def __init__(out self):
        self.a = 1
    def run[
        FuncType: def(Int) -> Int,
    ](self, func: FuncType, x: Int) -> Int:
        return func(x) + 100

struct Beta:
    var b: Int
    def __init__(out self):
        self.b = 2
    def run[
        func: def(Int) -> Int,
    ](self, x: Int) -> Int:
        def wrapper() capturing -> Int:
            return func(x)
        return wrapper()

fn triple_it(x: Int) -> Int:
    return x * 3

def main() raises:
    var a = Alpha()
    var beta = Beta()
    print(a.run(triple_it, 5))
    print(beta.run[triple_it](5))
"""
    out = _build_and_run(src)
    check("cross-struct same-name methods: Alpha.run(triple_it,5)=115, Beta.run[triple_it](5)=15",
          out == "115\n15\n", detail=repr(out))


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
    import sys
    sys.exit(0 if run_all() else 1)
