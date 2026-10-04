"""REAL behavioral test for the comptime bracket-parametrized function call
fix (`f[N](...)`) — see
CODEGEN_comptime_bracket_parametrized_function_calls_silently_wrong.

Before the fix, `gimple_codegen.py`'s `_type_expr_to_ann` returned '' for any
literal-valued bracket argument (IntLiteral/BoolLiteral/negative-int), which
`_is_concrete_type_arg` then rejected, so `_elaborate_generic_call` bailed
out and every `f[N](...)` call site fell through `_lower_call`'s final
`if not isinstance(node.func, IdentExpr): return 'int', self._new_val('int',
'0')` catch-all — a SILENT wrong-value miscompile (no exception, valid
-fgimple output), not a refusal. This compiles the exact repro from the bug
report all the way to a real executable (gcc -fgimple -c + link against
runtime/fire_runtime.c via fire.py's link_executable), RUNS it, and asserts
on its ACTUAL stdout — mirrors test_gimple_generator_runner.py's/
test_gimple_async_runner.py's "real build+link+run, not compile-only" shape.
"""
import os
import subprocess
import tempfile

import driver

HERE = os.path.dirname(os.path.abspath(__file__))

_PASS = 0
_FAIL = 0


def _build_and_run(mojo_src: str, filename: str = 'prog.mojo') -> str:
    """Compile+link+run mojo_src through the REAL, real-program driver
    (driver.compile_program — the exact path `python3 fire.py <file.mojo>`
    itself uses): link mode (gimple_codegen.compile_linked), which records
    and links in the elaborated per-call-site instantiation objects a
    comptime-bracket-parametrized call produces (unlike the plain
    compile_to_gimple_cached + single-.o build build_executable() uses for
    `fire build`, which has no notion of extra elaboration objects at all).
    Returns real captured stdout from actually running the built binary."""
    wd = tempfile.mkdtemp(prefix='mojo_comptime_bracket_')
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


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def test_free_function_int_comptime_param():
    """The bug report's exact repro: a plain top-level function with an Int
    comptime bracket parameter, called twice with different bracket values.
    Real Mojo/CPython-equivalent semantics: prints 11 then 22 — previously
    the compiled path printed 0 then 0."""
    src = """\
def add_const[lhs: Int](rhs: Int) -> Int:
    return lhs + rhs

def main() raises:
    print(add_const[1](10))
    print(add_const[2](20))
"""
    out = _build_and_run(src)
    check("add_const[1](10) / add_const[2](20) -> 11 / 22 (not 0 / 0)",
          out == "11\n22\n", detail=repr(out))


def test_two_distinct_bindings_both_get_their_own_specialization():
    """Each distinct bracket-argument tuple must produce (or reuse) its own
    specialized callee — a call site bound to lhs=1 must not somehow share
    the same computed value as one bound to lhs=2 (would indicate the bind
    is a no-op / falls back to some single shared constant)."""
    src = """\
def scale[factor: Int](x: Int) -> Int:
    return x * factor

def main() raises:
    var a = scale[3](10)
    var b = scale[7](10)
    print(a)
    print(b)
    print(a + b)
"""
    out = _build_and_run(src)
    check("scale[3](10)=30, scale[7](10)=70, sum=100 (distinct per-binding results)",
          out == "30\n70\n100\n", detail=repr(out))


def test_bool_comptime_param():
    """A Bool-typed comptime bracket parameter (matches test_tracing.mojo's
    own `test_tracing_add[enabled: Bool, lhs: Int](rhs: Int)` shape) —
    exercises the BoolLiteral branch of _type_expr_to_ann, not just IntLiteral."""
    src = """\
def maybe_add[enabled: Bool, lhs: Int](rhs: Int) -> Int:
    if enabled:
        return lhs + rhs
    return rhs

def main() raises:
    print(maybe_add[True, 5](10))
    print(maybe_add[False, 5](10))
"""
    out = _build_and_run(src)
    check("maybe_add[True,5](10)=15, maybe_add[False,5](10)=10",
          out == "15\n10\n", detail=repr(out))


def test_keyword_bound_function_typed_bracket_param_on_method():
    """A struct method with a KEYWORD-bound function-typed comptime bracket
    parameter (`self.body[f_key=show_k]()`), called directly in the method
    body — dict.mojo/counter.mojo's exact binding form. Two stacked bugs used
    to break this shape:
    1. the call-site pre-scan only mapped POSITIONAL bracket arguments, so a
       keyword-bound function name was never forwarded; _lower_struct_method_
       call's arity padder then filled the threaded trailing C parameter with
       a literal 0 → "call through NULL pointer" segfault;
    2. the parser's generic-param capture counted only bracket depth, not
       parens, so annotations with commas inside `(...)` leaked phantom
       parameter names.
    Real semantics: prints 1."""
    src = """\
def show_k(k: Int) -> None:
    print(k)

struct P:
    var k: Int

    def __init__(out self, k: Int):
        self.k = k

    def body[f_key: def(Int) -> None thin](self):
        f_key(self.k)

    def write_to(self):
        self.body[f_key=show_k]()

def main():
    P(1).write_to()
"""
    out = _build_and_run(src)
    check("keyword-bound f_key=show_k calls through (prints 1)",
          out == "1\n", detail=repr(out))


def test_two_function_typed_bracket_params_with_nested_bracket_annotations():
    """The full dict.mojo `_write_dict_body` shape: TWO function-typed
    comptime bracket parameters whose type annotations contain their own
    brackets AND parenthesized comma-bearing argument lists
    (`f_key: def(Int, List[Int]) -> None thin`). Before the fix,
    _bracket_param_type_annotations' head regex truncated the bracket list at
    the FIRST inner `]` (inside `List[Int]`), so every parameter after f_key
    was invisible: f_val was dropped from the threaded signature, its body
    call degraded to the weak "unavailable in compiled mode" stub (whose
    exported symbol then collided across stdlib modules — the
    "localize 1 dup symbol(s) in std_collections_dict" stopgap), and the
    parser's paren-blind comma split additionally injected a phantom `List`
    parameter that mis-aritized every call site.
    Real semantics: prints 1 then 70."""
    src = """\
def show_k(k: Int, extra: List[Int]) -> None:
    print(k)

def show_v(v: Int) -> None:
    print(v * 10)

struct P:
    var k: Int
    var v: Int

    def __init__(out self, k: Int, v: Int):
        self.k = k
        self.v = v

    def body[
        f_key: def(Int, List[Int]) -> None thin,
        f_val: def(Int) -> None thin,
    ](self):
        var scratch = List[Int](0)
        f_key(self.k, scratch)
        f_val(self.v)

    def write_to(self):
        self.body[f_key=show_k, f_val=show_v]()

def main():
    P(1, 7).write_to()
"""
    out = _build_and_run(src)
    check("both keyword-bound fn params thread through (prints 1, 70)",
          out == "1\n70\n", detail=repr(out))


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
