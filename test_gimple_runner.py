"""Test runner that compiles and executes GIMPLE programs.

Uses gcc (gcc-15 if available, else fallback) with -fgimple to compile and execute
GIMPLE-annotated C code. This tests the GIMPLE backend which is used for the gimple codegen tests.
"""
import os
import sys
import subprocess
import tempfile
from io import StringIO
from build_config import find_gcc

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_HDR = os.path.join(HERE, 'runtime', 'fire_runtime.h')

_PASS = 0
_FAIL = 0
_TIMEOUT = 0


def compile_mojo_to_gimple_exe(mojo_src: str) -> str:
    """Compile mojo source to GIMPLE executable, return path to executable."""
    from gimple_codegen import compile_to_gimple

    with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
        # Compile mojo to GIMPLE C code
        c_code = compile_to_gimple(mojo_src)
        f.write(c_code)
        c_file = f.name

    exe_file = c_file.replace('.c', '.exe')

    try:
        # Compile GIMPLE C to executable using gcc -fgimple
        runtime_dir = os.path.join(HERE, 'runtime')
        sources = [c_file, os.path.join(runtime_dir, 'fire_runtime.c')]
        # A3 stack-switch coroutine runtime (doc/COROUTINE.html): the
        # generated C calls __mgco_* / __mojo_gen_* whenever gimple_gen_coro
        # lowered a generator — which now includes every compiled generator
        # EXPRESSION, since fire_compiler.desugar_genexps rewrites those
        # into real generator functions. fire.py's own build_executable
        # decides this with the identical textual check on the generated C
        # (see its `if '__mgco_' in c_code ...` block); mirror it here so
        # this runner can execute generator programs at all, instead of
        # failing to link with undefined __mojo_gen_new_* symbols.
        if '__mgco_' in c_code or '__mojo_coro_yield_i' in c_code:
            import platform as _plat
            _arch_src = ('fire_coro_ctx_aarch64.S'
                         if _plat.machine().lower() in ('arm64', 'aarch64')
                         else 'fire_coro_ctx_generic.c')
            for _cs in ('fire_coro_gen.c', 'fire_coro.c', 'fire_async_sched.c',
                        _arch_src):
                sources.append(os.path.join(runtime_dir, _cs))
        result = subprocess.run(
            [find_gcc(), '-fgimple',
             f'-I{runtime_dir}',
             '-o', exe_file, *sources],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"gcc -fgimple compilation failed: {result.stderr}")
        return exe_file
    finally:
        try:
            os.unlink(c_file)
        except:
            pass


def run_executable(exe_path: str) -> int:
    """Execute the program and return its exit code."""
    result = subprocess.run(
        [exe_path],
        capture_output=True,
        timeout=10
    )
    return result.returncode


# Freed memory is filled with 0x55 bytes (macOS libmalloc; ignored elsewhere), so a
# use-after-free reads garbage deterministically instead of "usually still the old
# value". Ownership-freeing tests are only worth having if a wrong free is visible.
_SCRIBBLE_ENV = dict(os.environ, MallocScribble='1')


def run_executable_stdout(exe_path: str) -> str:
    """Execute the program and return its captured stdout, decoded."""
    result = subprocess.run(
        [exe_path],
        capture_output=True,
        timeout=10,
        env=_SCRIBBLE_ENV
    )
    return result.stdout.decode('utf-8', errors='replace')


def test_gimple_execution(name: str, mojo_src: str, expected_return: int = 0):
    """Test that mojo code compiles to GIMPLE and executes with expected return code."""
    global _PASS, _FAIL, _TIMEOUT
    exe_path = None
    try:
        exe_path = compile_mojo_to_gimple_exe(mojo_src)
        result = run_executable(exe_path)
        if result == expected_return:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected return {expected_return}, got {result}")
            _FAIL += 1
    except subprocess.TimeoutExpired as e:
        # A timeout is LOAD, not a wrong answer: these are 30s/10s
        # subprocess budgets, and running this suite back-to-back with the
        # other heavyweight suites can blow them on an otherwise healthy
        # binary. Reporting it as a plain FAIL makes infra noise
        # indistinguishable from a real miscompile, which costs a full
        # debugging cycle to disprove. Counted separately, on its own
        # grep-able prefix.
        print(f"TIMEOUT {name}: {e}")
        _TIMEOUT += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1

    finally:
        if exe_path:
            try:
                os.unlink(exe_path)
            except:
                pass


def test_gimple_stdout(name: str, mojo_src: str, expected_stdout: str):
    """Test that mojo code compiles to GIMPLE, executes, and prints exactly
    `expected_stdout`. Unlike test_gimple_execution's exit-code check, this
    verifies the ACTUAL printed value — needed for bugs where the compiled
    binary runs fine and exits 0 but prints a wrong/garbage value (e.g. a
    raw pointer reinterpreted as an integer instead of the real string), a
    class of bug an exit-code-only check can't detect at all."""
    global _PASS, _FAIL, _TIMEOUT
    exe_path = None
    try:
        exe_path = compile_mojo_to_gimple_exe(mojo_src)
        out = run_executable_stdout(exe_path)
        if out == expected_stdout:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected stdout {expected_stdout!r}, got {out!r}")
            _FAIL += 1
    except subprocess.TimeoutExpired as e:
        # A timeout is LOAD, not a wrong answer: these are 30s/10s
        # subprocess budgets, and running this suite back-to-back with the
        # other heavyweight suites can blow them on an otherwise healthy
        # binary. Reporting it as a plain FAIL makes infra noise
        # indistinguishable from a real miscompile, which costs a full
        # debugging cycle to disprove. Counted separately, on its own
        # grep-able prefix.
        print(f"TIMEOUT {name}: {e}")
        _TIMEOUT += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1

    finally:
        if exe_path:
            try:
                os.unlink(exe_path)
            except:
                pass


def test_gimple_bounded_memory(name: str, mojo_src: str, expected_stdout: str, limit_mb: int):
    """The program prints exactly `expected_stdout` AND its peak RSS stays
    under `limit_mb`. A leak in a loop shows up as RSS proportional to the
    iteration count while stdout stays correct, so neither
    test_gimple_stdout nor an exit-code check can see it; size the loop so
    the leak, if present, is several times `limit_mb` (see doc/MEMORY.html
    section 8 for why one size proves nothing about a slope, and why this
    limit is a tripwire rather than a measurement). Peak RSS is read from a
    fresh helper interpreter's RUSAGE_CHILDREN so it is this binary's own
    peak, not the max over every child this suite has ever spawned."""
    global _PASS, _FAIL, _TIMEOUT
    exe_path = None
    try:
        exe_path = compile_mojo_to_gimple_exe(mojo_src)
        probe = (
            "import resource, subprocess, sys\n"
            "import os\n"
            "r = subprocess.run([sys.argv[1]], capture_output=True, timeout=60,\n"
            "                   env=dict(os.environ, MallocScribble='1'))\n"
            "sys.stdout.buffer.write(r.stdout)\n"
            "sys.stderr.write(str(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss))\n"
        )
        r = subprocess.run([sys.executable, "-c", probe, exe_path],
                           capture_output=True, timeout=90)
        out = r.stdout.decode('utf-8', errors='replace')
        maxrss = int(r.stderr.decode().strip().splitlines()[-1])
        rss_mb = maxrss / (1024 * 1024) if sys.platform == 'darwin' else maxrss / 1024
        if out == expected_stdout and rss_mb <= limit_mb:
            print(f"PASS  {name}  (peak {rss_mb:.1f} MB <= {limit_mb})")
            _PASS += 1
        else:
            print(f"FAIL  {name}: stdout {out!r} (want {expected_stdout!r}), "
                  f"peak RSS {rss_mb:.1f} MB (limit {limit_mb})")
            _FAIL += 1
    except subprocess.TimeoutExpired as e:
        print(f"TIMEOUT {name}: {e}")
        _TIMEOUT += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1
    finally:
        if exe_path:
            try:
                os.unlink(exe_path)
            except:
                pass


def test_gimple_runtime_error(name: str, mojo_src: str, expected_substr: str):
    """Assert the compiled program FAILS at RUNTIME with `expected_substr` on
    stderr — the shape of a wrong-but-compiles bug's correct counterpart: a
    call CPython rejects outright (`b'a'.isprintable()`, a `ljust` fill of
    the wrong length). `test_gimple_stdout` cannot see these, because the
    program exits non-zero with the message on stderr rather than printing;
    `test_gimple_execution`'s exit-code check cannot either, because it
    would also pass for a segfault or an unrelated gcc failure."""
    global _PASS, _FAIL, _TIMEOUT
    exe_path = None
    try:
        exe_path = compile_mojo_to_gimple_exe(mojo_src)
        result = subprocess.run([exe_path], capture_output=True, timeout=10)
        err = result.stderr.decode('utf-8', errors='replace')
        if result.returncode != 0 and expected_substr in err:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected a non-zero exit with {expected_substr!r} "
                  f"on stderr, got rc={result.returncode} err={err[-300:]!r}")
            _FAIL += 1
    except subprocess.TimeoutExpired as e:
        print(f"TIMEOUT {name}: {e}")
        _TIMEOUT += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1
    finally:
        if exe_path:
            try:
                os.unlink(exe_path)
            except:
                pass


def run_tests():
    """Run GIMPLE-specific tests."""

    # 1. Simple arithmetic in GIMPLE
    test_gimple_execution("gimple_arithmetic", """\
def main() -> Int:
    var a: Int = 10
    var b: Int = 32
    return a + b
""", expected_return=42)

    # 2. Nested control flow in GIMPLE
    test_gimple_execution("gimple_nested_if", """\
def main() -> Int:
    var x: Int = 5
    if x > 0:
        if x > 3:
            return 42
        else:
            return 0
    else:
        return -1
""", expected_return=42)

    # 3. Loop in GIMPLE
    test_gimple_execution("gimple_loop", """\
def main() -> Int:
    var sum: Int = 0
    var i: Int = 0
    while i < 10:
        sum = sum + i
        i = i + 1
    return sum
""", expected_return=45)

    # 4. Function calls in GIMPLE (no function call restrictions yet)
    test_gimple_execution("gimple_function_call", """\
def add(x: Int, y: Int) -> Int:
    return x + y

def main() -> Int:
    return add(20, 22)
""", expected_return=42)

    # 5. For loop in GIMPLE
    # TODO: Bug in loop variable handling - produces 208 instead of 720
    # test_gimple_execution("gimple_for_loop", """\
    # def main() -> Int:
    #     var product: Int = 1
    #     for i in range(1, 7):
    #         product = product * i
    #     return product
    # """, expected_return=720)

    # 6. Recursion in GIMPLE
    test_gimple_execution("gimple_recursion", """\
def fib(n: Int) -> Int:
    if n <= 1:
        return 1
    else:
        return fib(n - 1) + fib(n - 2)

def main() -> Int:
    return fib(9)
""", expected_return=55)

    # 7. Multiple local variables
    test_gimple_execution("gimple_locals", """\
def main() -> Int:
    var a: Int = 5
    var b: Int = 10
    var c: Int = 20
    return a + b + c
""", expected_return=35)

    # 8. Augmented assignment
    test_gimple_execution("gimple_aug_assign", """\
def main() -> Int:
    var x: Int = 10
    x += 5
    x *= 2
    x -= 8
    return x
""", expected_return=22)

    # 10. set(iterable) / list(iterable) constructors actually populate the
    # collection from the argument, instead of silently producing an empty
    # one — see bugs/CODEGEN_set_list_ctor_ignores_iterable_arg.md. This is
    # a genuine behavioral check (len() + a sum over the iterated elements),
    # not just "does it compile": the bug compiled clean and returned 0 for
    # everything below before the fix.
    test_gimple_execution("gimple_set_ctor_from_list", """\
def main() -> Int:
    var s: Set = set([1, 2, 3, 3])
    var total: Int = 0
    for x in s:
        total = total + x
    return len(s) * 10 + total
""", expected_return=36)  # len == 3 (deduped), elements sum to 1+2+3 == 6

    test_gimple_execution("gimple_list_ctor_from_list", """\
def main() -> Int:
    var l: List = list([1, 2, 3])
    var total: Int = 0
    for x in l:
        total = total + x
    return len(l) * 10 + total
""", expected_return=36)  # len == 3, elements sum to 1+2+3 == 6

    # 9. Matrix multiply operator (simple test with scalar multiplication)
    # TODO: Full matrix multiply example with actual 2D arrays once struct literals work
    # For now, test that the @ operator parses and compiles
    # (full implementation requires struct __matmul__ method binding)

    # 10. A bound method referenced as a plain VALUE (not called
    # immediately) — `f = self.b` — then invoked later via `f()`. Compiling
    # this used to fail outright (a C compiler error, not just a wrong
    # answer — see bugs/CODEGEN_bound_method_as_value_not_resolved.md), so
    # this is a real behavioral round-trip check, not just "it compiles":
    # confirms the stored value actually calls back into the right method
    # WITH the right `self`, not merely that gcc accepts the generated C
    # (the same "compiles but produces the wrong answer" class of bug the
    # set()/list() ctor fix hit).
    test_gimple_execution("gimple_bound_method_as_value", """\
class C:
    def b(self) -> Int:
        return 42
    def a(self) -> Int:
        f = self.b
        return f()

def main() -> Int:
    var c: C = C()
    return c.a()
""", expected_return=42)

    # 10a2. A local branch-joined between a lambda value and a `self.method`
    # bound-method value, then called — the call site can't tell statically
    # which kind of callable is live, so it must dynamically dispatch
    # (mojo_maybe_bound_call_N). Previously the join collapsed the slot to
    # void* and the call unconditionally used mojo_fnptr_call_0, so the
    # bound-method branch called the MojoBoundMethod struct as code (bus
    # error). See bugs/hard/CODEGEN_coro_stackswitch_body_semantics_gaps.md
    # #3. Reproduces in a plain (non-generator) method — this is the
    # codegen-wide check; the generator twin is in
    # test_gimple_generator_runner.py.
    test_gimple_stdout("gimple_branch_joined_lambda_and_bound_method_value", """\
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
        print(getpos())

fn main():
    tk = Ticker(7)
    tk.run(1)
    tk.run(0)
""", "42\n7\n")

    # A CAPTURING lambda: `n` lives in the enclosing function, but a lifted
    # lambda is a top-level C function that does not contain it, so the read
    # stubbed to 0 — silently, exit 0. When the lambda's local is called
    # directly in the same function and never escapes, the body is inlined at
    # the call site instead, where the name resolves. Covers an int capture, a
    # capture used through a builtin, and a second lambda in the same
    # function. See bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md.
    test_gimple_stdout("gimple_capturing_lambda_inlined_at_call", """\
fn outer():
    var n = 7
    var f = lambda: n
    print(f())
    var xs = [1, 2, 3]
    var g = lambda: len(xs)
    print(g())
    var h = lambda x: n + x
    print(h(1))

fn main():
    outer()
""", "7\n3\n8\n")

    # The inline reduction must NOT fire when the lambda's local escapes —
    # there is no call site to inline into, so the lambda stays lifted. The
    # lifted capturing lambda used to LOSE the capture (its body is a
    # top-level C function that does not contain `n`, and the read stubbed
    # to 0), printing 1 instead of 8. That expectation was pinned
    # deliberately so the env-struct work would flip this test instead of
    # changing it silently — and it has now landed: `_lower_LambdaExpr`
    # gives a capturing lambda a heap env (a `MojoBoundMethod`, env as its
    # first parameter), so it is correct whether or not it escapes. Expected
    # output is now CPython's answer. See
    # bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md.
    test_gimple_stdout("gimple_escaping_capturing_lambda_still_lifted", """\
fn apply(f, v):
    return f(v)

fn main():
    var n = 7
    var e = lambda x: n + x
    print(apply(e, 1))
""", "8\n")

    # A VARIADIC lambda. The lifted definition was always correct — its
    # parameters are the PACKED forms (`MojoList *` for `*args`, `MojoDict *`
    # for `**kwargs`) — but the lambda's VALUE was a bare function pointer,
    # and `mojo_fnptr_call_N` is arity-based: it casts the callee to
    # `int64_t(*)(int64_t, ...)` and passes the arguments written at the call
    # positionally. So `e(4, 5)` handed the callee `a = 4` where a
    # `MojoList *` was wanted, and the body dereferenced address 4 — every one
    # of these SIGSEGV'd before the fix, whatever the lambda captured.
    # `_lower_LambdaExpr` now materializes a `MojoVarargFn` (callee, env,
    # leading-parameter count, and which of the three shapes it has), and the
    # runtime dispatch helpers pack. See
    # bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md.
    test_gimple_stdout("gimple_variadic_lambda_positional_args_packed", """\
def add(a, b):
    return a + b

def main():
    e = lambda *a: add(a[0], a[1])
    print(e(4, 5))
""", "9\n")

    # A variadic lambda's `*args` really is a sequence: len(), iteration and
    # indexing all read the packed list, and the ZERO-argument call packs an
    # empty one rather than passing a stray scalar.
    test_gimple_stdout("gimple_variadic_lambda_args_is_a_sequence", """\
def main():
    e = lambda *a: len(a) * 10 + a[0]
    print(e())
    print(e(1, 2, 3))
""", "0\n31\n")

    # CAPTURING + variadic: the closure env leads the packed parameters, and
    # the capture is read through it. This is the corpus shape
    # `Lib/importlib/util.py`'s LazyLoader factory has
    # (`lambda *args, **kwargs: cls(loader(*args, **kwargs))`).
    test_gimple_stdout("gimple_variadic_lambda_captures_env", """\
def add(a, b):
    return a + b

def main():
    n = 7
    e = lambda *args, **kwargs: add(n, args[0])
    print(e(1))
    m = 2
    f = lambda *args, **kwargs: m * 100 + len(args) + len(kwargs)
    print(f(1, 2, z=3))
""", "8\n203\n")

    # Keyword arguments at the call site reach a `**kwargs` callee, packed
    # into the MojoDict the lifted body reads. A call with none must still
    # hand the callee a real (empty) dict, never NULL: `len(k)` and `k['x']`
    # are ordinary spellings and NULL segfaults on the second.
    test_gimple_stdout("gimple_variadic_lambda_kwargs_reach_the_callee", """\
def main():
    e = lambda *a, **k: len(a) * 100 + len(k)
    print(e(1, 2))
    print(e(1, 2, z=9))
    only = lambda **k: len(k)
    print(only(a=1, b=2, c=3))
    print(only())
""", "200\n201\n3\n0\n")

    # ORDINARY leading parameters ahead of the `*args` stay POSITIONAL — the
    # callee declares them before its `*args`, so they must not be packed —
    # and everything after them is what `*args` collects. This shape did not
    # compile at all before the fix: the forward declaration built for the
    # lambda silently dropped its `*`-prefixed parameters, so GCC rejected
    # `int64_t f(int64_t)` against a definition of `int64_t f(int64_t,
    # MojoList *)` as conflicting types.
    test_gimple_stdout("gimple_variadic_lambda_fixed_prefix_stays_positional", """\
def main():
    two = lambda f, g, *a: f * g + len(a)
    print(two(3, 4, 1, 2))
    four = lambda a, b, c, d, *rest: a + b + c + d + len(rest)
    print(four(1, 2, 3, 4, 5, 6))
""", "14\n12\n")

    # Because the packing happens at the RUNTIME dispatch point rather than
    # at each call site, every way of holding the value works at once: passed
    # as an argument, returned, stored in a dict, stored in a struct field,
    # rebound across branches, and used as a `sorted(key=)` / `map` / `filter`
    # callable. The `Lib/doctest.py` shape this bug doc names is the struct
    # field one (`_colorize.can_colorize = lambda *args, **kwargs: False`).
    test_gimple_stdout("gimple_variadic_lambda_works_through_every_holder", """\
def apply(f, v):
    return f(v, v)

def mk():
    return lambda *a: a[0] * 2

class Box:
    def __init__(self):
        self.fn = None

def main():
    print(apply(lambda *a: a[0] + a[1], 3))
    print(mk()(21))
    d = {}
    d['k'] = lambda *a: a[0] + a[1]
    from_dict = d['k']
    print(from_dict(2, 3))
    b = Box()
    b.fn = lambda *a: a[0] + 1
    print(b.fn(41))
    if 1:
        r = lambda *a: a[0]
    else:
        r = lambda *a: a[1]
    print(r(7, 8))
    print(sorted([1, 2, 3], key=lambda *a: -a[0]))
    print(list(map(lambda *a: a[0] * 10, [1, 2])))
""", "6\n42\n5\n42\n7\n[3, 2, 1]\n[10, 20]\n")

    # More than four arguments. `mojo_fnptr_call_N` used to stop at four and
    # silently drop the rest — for a `*args` callee that means losing
    # elements, so the helpers now go to eight. (The truncation was a silent
    # wrong value for every five-or-more-argument indirect call, not only
    # this one.)
    test_gimple_stdout("gimple_fnptr_call_carries_more_than_four_args", """\
def main():
    f = lambda *a: len(a)
    print(f(1, 2, 3, 4, 5, 6, 7))
""", "7\n")

    # `lambda *a, **k: <expr>` forwarding its own arguments on, which is what
    # every one of the three real corpus occurrences does.
    test_gimple_stdout("gimple_variadic_lambda_forwards_its_arguments", """\
def add3(a, b, c):
    return a + b + c

def walk(*a, **k):
    return len(a) * 10 + len(k)

def main():
    unpack = lambda *a: add3(*a)
    print(unpack(1, 2, 3))
    both = lambda *a, **k: walk(*a, **k)
    print(both(1, 2, 3))
    print(both(1, z=5))
""", "6\n30\n11\n")

    # The SAME defect for a NAMED function taken as a value, which is the
    # same packing with no lambda involved: `def m(*a)` really does take a
    # `MojoList *`, so `r = m; r(1, 2, 3)` handed the callee the integer 1
    # where a list pointer was wanted and it dereferenced address 1 — a
    # SIGSEGV. A DIRECT call by name is untouched and still goes through
    # `_lower_named_call`'s own packing; only the value form changes, and it
    # changes to the same `MojoVarargFn` a variadic lambda gets.
    test_gimple_stdout("gimple_variadic_named_function_through_a_value", """\
def m(*a):
    return len(a)

def both(*a, **k):
    return len(a) * 100 + len(k)

def main():
    r = m
    print(r(1, 2, 3))
    s = both
    print(s(1, 2, z=3))
    print(s(1, 2))
    print(m(1, 2, 3))
    print(both(1, 2, z=3))
""", "3\n201\n200\n3\n201\n")

    # 10a3. Heterogeneous stack drained with .pop(), each popped value
    # discriminated with `isinstance(top, tuple)`. `isinstance(x, tuple)`
    # had no real lowering (fell through to an always-false runtime stub),
    # so the tuple branch was dead. See
    # bugs/hard/CODEGEN_coro_stackswitch_body_semantics_gaps.md #4.
    test_gimple_stdout("gimple_isinstance_tuple_on_heterogeneous_pop", """\
fn walk():
    stack = [(1, 2)]
    stack.append("leaf")
    stack.append((3, 4))
    while stack:
        top = stack.pop()
        if isinstance(top, tuple):
            a, b = top
            print(a + b)
        else:
            print(99)

fn main():
    walk()
""", "7\n99\n3\n")

    # 10b. A BUILTIN-CONTAINER method bound to a local and invoked later —
    # `append = xs.append` / `a = ba.append` — the container twin of #10.
    # Behavioral round-trip: the bound value must mutate the ORIGINAL
    # container. bytes/bytearray + memoryview used to emit an invalid
    # `->append` field access ('MojoBytes' has no member named 'append');
    # zipfile's `_ZipDecrypter.decrypter` is the real trigger.
    test_gimple_execution("gimple_bound_container_method_value", """\
def main() -> Int:
    xs = [10]
    f = xs.append
    f(20)
    f(30)
    ba = bytearray()
    a = ba.append
    a(65)
    a(66)
    return xs[2] + len(xs) + ba[0] + len(ba)
""", expected_return=30 + 3 + 65 + 2)

    # 11. An f-string whose nested `{...}` interpolation contains a string
    # literal reusing the SAME quote character as the f-string's own
    # delimiter (legal since PEP 701 / Python 3.12) — this used to truncate
    # the f-string at the first reused quote (see
    # bugs/PARSE_FAIL_fstring_same_quote_reuse.md), producing a "could not
    # be compiled" warning (falling back to mangled literal text). This is
    # a real behavioral round-trip check (VALUE, not just "it compiles"):
    # `len('ab')` interpolates to `2`, and the surrounding f-string text
    # ("value: ") must have survived intact around the reused-quote call,
    # so `len(x)` on the final string confirms both the interpolated value
    # AND the literal text boundaries are correct, not just that some
    # string got produced.
    test_gimple_execution("gimple_fstring_same_quote_reused", """\
def main() -> Int:
    x = f'value: {len('ab')}'
    return len(x)
""", expected_return=len("value: 2"))

    # 12. Untyped-parameter identity function called with a string argument
    # — bugs/CODEGEN_untyped_param_string_passthrough_wrong.md. `a` has no
    # body-usage evidence at all (just returned unchanged), so the
    # parameter and the function's inferred return type used to default to
    # int64_t; the real char* argument was silently reinterpreted as an
    # integer and printed as a garbage large number. A pure "does it
    # compile"/exit-code check can't catch this at all (the binary built
    # and exited 0 both before and after the fix) — must check stdout.
    test_gimple_stdout("gimple_untyped_param_string_passthrough", """\
def g(a):
    return a
print(g("ab"))
""", "ab\n")

    # 13. Same bug, explicitly-annotated sibling — confirms the fix to the
    # UNANNOTATED-parameter inference path didn't disturb the already-correct
    # annotated path.
    test_gimple_stdout("gimple_typed_param_string_passthrough_still_works", """\
def g(a: str) -> str:
    return a
print(g("ab"))
""", "ab\n")

    # 14. Two-untyped-parameter shape (`a + b`, both strings) — the shape
    # that originally surfaced via an f-string interpolating a run-time-
    # computed string value from a function just like this one (see
    # bugs/PARSE_FAIL_fstring_same_quote_reuse.md's verification pass).
    test_gimple_stdout("gimple_untyped_param_string_concat_passthrough", """\
def g(a, b):
    return a + b
y = g("a", "b")
print(y)
""", "ab\n")

    # 15. Same two-param concat shape, but the result is read back through an
    # f-string interpolation (`{y}`) rather than a plain print(y) — the exact
    # surrounding shape that originally surfaced this bug class.
    test_gimple_stdout("gimple_untyped_param_string_concat_fstring", """\
def g(a, b):
    return a + b
y = g("a", "b")
print(f"result: {y}")
""", "result: ab\n")

    # 15b. Mojo's CAPITALIZED type constructors are the same operations as
    # the lowercase builtins (and the interpreter already treats them that
    # way). `String(i)` used to fall through to the generic call path and be
    # emitted as a bare C cast of the argument, so `"item" + String(i)`
    # concatenated the integer's raw bits as a pointer — a silent wrong
    # answer (and a crash for a real pointer value), invisible to a
    # compile-only or exit-code check.
    test_gimple_stdout("gimple_capitalized_String_constructor", """\
print("item" + String(7))
print(String(1.5))
""", "item7\n1.5\n")

    # `Int`/`Float`/`Bool` are deliberately NOT aliased to their lowercase
    # builtins: this codegen's generic call path already lowers them right,
    # including for a struct argument, where the `int` builtin's stringifying
    # path would not (test/builtin/test_bfloat16.mojo's
    # `Int(BFloat16(3.0))` regressed to "cannot convert to a pointer type").
    # Pinned here so a future alias attempt has to face this case.
    test_gimple_stdout("gimple_capitalized_Int_and_Bool_constructors", """\
print(Int(41) + 1)
print(int(Bool(1)))
""", "42\n1\n")

    # 15b2. A generator expression whose element uses a STRUCT/method
    # receiver is deliberately left on the eager (but CORRECT) lowering by
    # fire_compiler's genexp desugar: the compiled coroutine body has no
    # working model for a captured receiver, and lowering it anyway printed
    # raw pointer garbage. The answer must still be right — just not lazy.
    test_gimple_stdout("gimple_genexp_struct_receiver_still_correct", """\
struct Counter:
    var n: Int
    def __init__(out self):
        self.n = 0
    def note(self, v: Int) -> Int:
        self.n = self.n + 1
        return v * v

c = Counter()
out = []
for x in (c.note(i) for i in range(4)):
    out.append(x)
print(out)
print(c.n)
""", "[0, 1, 4, 9]\n4\n")

    # enumerate() in VALUE position. The runtime's mojo_enumerate is an
    # identity passthrough, so `list(enumerate([7, 8]))` returned the VALUES
    # with no indices at all, and over a generator the consuming list() found
    # nothing iterable in the coroutine handle and produced an empty list —
    # silently. Routed through a comprehension instead (what list(x) does)
    # it produced `[0, 1]`, because that path's synthetic target has ONE
    # slot and the enumerate loop bound the INDEX to it, dropping the value.
    # Built directly now, and repr'd by the pair-aware runtime helpers so
    # the index prints as 0 rather than the None sentinel.
    test_gimple_stdout("gimple_list_of_enumerate", """\
print(list(enumerate([7, 8])))
""", "[(0, 7), (1, 8)]\n")

    # (Function scope deliberately: a module-level global assigned a CALL's
    # result — `z = sorted([3, 1])` — still loses its container typing and
    # prints a raw pointer. That is a separate pre-existing gap in how a
    # module-level global's type is derived from a call result, and is not
    # what this test is about; the module-level NESTED LITERAL form below is
    # fixed and covered separately.)
    test_gimple_stdout("gimple_enumerate_value_printed", """\
def main():
    z = enumerate([7, 8])
    print(len(z))
    print(z)

main()
""", "2\n[(0, 7), (1, 8)]\n")

    # A module-level nested list literal: the store side records the inner
    # lists' element type, but the READ of the global dropped it, so the repr
    # fell back to the generic list walker — whose int-vs-pointer heuristic
    # saw a boxed 0 and printed the None sentinel, giving
    # `[[None, 7], [1, 8]]` for `[[0, 7], [1, 8]]`.
    test_gimple_stdout("gimple_global_nested_list_literal", """\
z = [[0, 7], [1, 8]]
print(z)
""", "[[0, 7], [1, 8]]\n")

    # sorted(key=...) / reverse=. The ordinary GIMPLE path dropped both, so
    # `sorted([1, 3, 2], key=lambda v: -v)` sorted ASCENDING and
    # `reverse=True` did nothing — silently, and differently from the C++20
    # companion path, which implements both (so the same source sorted
    # differently depending on which backend handled it).
    test_gimple_stdout("gimple_sorted_key_lambda", """\
print(sorted([1, 3, 2], key=lambda v: -v))
""", "[3, 2, 1]\n")

    # A builtin as the key: `key=len` is the single most common form, and
    # going through the ordinary call path is what makes it work (a lambda
    # lowers to a function-pointer VARIABLE, not a callable symbol). The
    # element keeps its real `char *` type, so `len` sees the string rather
    # than its address.
    test_gimple_stdout("gimple_sorted_key_builtin_len", """\
print(sorted(["ccc", "a", "bb"], key=len))
""", "['a', 'bb', 'ccc']\n")

    test_gimple_stdout("gimple_sorted_reverse", """\
print(sorted([1, 3, 2], reverse=True))
print(sorted(["b", "a", "c"], reverse=True))
""", "[3, 2, 1]\n['c', 'b', 'a']\n")

    # reverse=True composes with key= (the sort is by key, then flipped) —
    # sorting by -v descending puts the original order back.
    test_gimple_stdout("gimple_sorted_key_and_reverse", """\
print(sorted([1, 3, 2], key=lambda v: -v, reverse=True))
""", "[1, 2, 3]\n")

    # A named function as the key. Deliberately an INT element: with a
    # string element an unannotated named function's `int64_t` parameter
    # receives the string bits and `len` misreads them
    # (`sorted(["ccc","a","bb"], key=bylen)` -> ['bb','ccc','a']) — a
    # pre-existing compiled-path string-argument typing gap, independent of
    # sorted (the same function called directly is correct), so it is not
    # pinned here as if it worked. A LAMBDA and a BUILTIN key both handle
    # string elements correctly, and both are covered above.
    test_gimple_stdout("gimple_sorted_key_function", """\
def negate(x):
    return -x

print(sorted([1, 3, 2], key=negate))
""", "[3, 2, 1]\n")

    # A string key is compared as a string, not as the address in its int64_t
    # slot (which would order by ADDRESS): the runtime picks the comparison
    # with mojo_boxed_is_str, since a lambda's declared return type is
    # int64_t whatever it returns and the codegen cannot tell.
    test_gimple_stdout("gimple_sorted_string_key", """\
print(sorted(["bb", "a", "ccc"], key=lambda s: s))
""", "['a', 'bb', 'ccc']\n")

    # The test above only catches a broken mojo_boxed_is_str BY LUCK: the
    # three literals it uses sit in a merged .rodata section at ...644,
    # ...647, ...649 — i.e. ALREADY ASCENDING BY ADDRESS — so comparing the
    # keys as raw int64_t pointers instead of strings reproduces the input
    # order, and the assertion only trips because the input is already
    # sorted. Any other input would pass silently while being sorted by
    # memory address. This one emits the same three literal CONTENTS in
    # the opposite order, so the .rodata addresses DESCEND while the
    # strings must still sort ascending — a regressed discriminator can no
    # longer pass by coincidence, and the keyless form is pinned alongside
    # it because it shares the same recovery path.
    test_gimple_stdout("gimple_sorted_string_key_not_in_address_order", """\
print(sorted(["ccc", "a", "bb"], key=lambda s: s))
print(sorted(["ccc", "a", "bb"]))
""", "['a', 'bb', 'ccc']\n['a', 'bb', 'ccc']\n")

    # A guard rather than a fails-before regression: runtime-BUILT strings
    # are heap-allocated, so they are 8-byte aligned and malloc_size() >= 8,
    # and therefore satisfied even the over-strict predicate that used to
    # reject literals. Pinned anyway, because "literal and heap string are
    # BOTH strings" is the invariant the discriminator actually has to
    # hold, and this is the half that a future tightening could break
    # silently. A runtime that recognises only one of the two shapes is
    # the bug both this and the two cases above exist to catch.
    test_gimple_stdout("gimple_sorted_string_key_runtime_built", """\
def k3(x):
    return x + "!"

names = ["ccc", "a", "bb"]
print(sorted(names, key=lambda s: k3(s)))
print(sorted(names, key=lambda s: s + "!"))
""", "['a', 'bb', 'ccc']\n['a', 'bb', 'ccc']\n")

    # ── MojoSet rehash: the `tag == 2` (bytes) domain ────────────────────
    # `_set_grow`'s replay had a `tag == 0` branch and a `tag == 1` branch
    # and NO `tag == 2` branch, so every BYTES element in a set was
    # discarded by the rehash — and its `val_s` leaked, because the free
    # lived in the tag-1 branch. `mojo_set_init` starts `cap` at 8 and
    # grows when `used * 2 >= cap`, so the first grow is the FOURTH insert
    # and every bytes set of 4+ elements silently lost all but the element
    # that triggered the grow:
    #
    #     s = {b'a', b'b', b'c', b'd', b'e'}
    #     print(len(s))          ->  1        (expected 5)
    #
    # A silent wrong answer, not a crash: the set is still a valid set
    # afterwards, so nothing else reports it. Only the compiled path is
    # affected — the interpreter's set is CPython's.
    #
    # The other two element domains are pinned alongside it because the
    # same replay previously probed every key TWICE (once inside the public
    # adder, once more to recover the index the adder had already found)
    # and strdup'd + freed every string entry for a net no-op. Both were
    # removed by the same rewrite and both are silent if they regress.
    test_gimple_stdout("gimple_set_bytes_survive_rehash", """\
s = {b'a', b'b', b'c', b'd', b'e'}
print(len(s), b'e' in s, b'a' in s, b'c' in s)
""", "5 True True True\n")

    test_gimple_stdout("gimple_set_bytes_many_rehashes", """\
s = set()
for i in range(30):
    s.add(b'k' + str(i).encode())
print(len(s), b'k0' in s, b'k29' in s)
""", "30 True True\n")

    test_gimple_stdout("gimple_set_str_rehash_unchanged", """\
s = set()
for i in range(30):
    s.add('k' + str(i))
print(len(s), 'k0' in s, 'k29' in s)
""", "30 True True\n")

    test_gimple_stdout("gimple_set_int_rehash_unchanged", """\
s = set()
for i in range(30):
    s.add(i * 7)
print(len(s), 0 in s, 203 in s)
""", "30 True True\n")

    # All three tag domains in ONE set, so a replay that handled only some
    # of them — the shape the bug actually had — is caught even when each
    # domain survives on its own. 4 + 10 = 14 elements, so two rehashes.
    test_gimple_stdout("gimple_set_mixed_domains_rehash", """\
s = {1, 'a', b'b', 2}
for i in range(10):
    s.add(100 + i)
print(len(s), 1 in s, 'a' in s, b'b' in s, 105 in s)
""", "14 True True True True\n")

    # A container element keeps its real type for the key, so `t[0]` works —
    # binding it as int64_t emitted "conflicting types" from the lambda's
    # forward declaration.
    test_gimple_stdout("gimple_sorted_key_tuple_element", """\
print(sorted([(2, "b"), (1, "a")], key=lambda t: t[0]))
""", "[(1, 'a'), (2, 'b')]\n")

    # Keyless sorted is unchanged by all of the above.
    test_gimple_stdout("gimple_sorted_plain_unchanged", """\
print(sorted([3, 1, 2]))
print(sorted(["b", "a"]))
""", "[1, 2, 3]\n['a', 'b']\n")

    # ── Module-level globals assigned a CALL's result ──────────────────
    # The global's C type is inferred by a pre-pass that honored only
    # `char *` from the type estimator and defaulted every OTHER pointer to
    # int64_t, so the global was declared an integer and printing it showed
    # the container's ADDRESS. The value was always right; the declaration
    # was not. Three separate sites discarded the pointer, so all three
    # shapes are covered.
    test_gimple_stdout("gimple_global_from_builtin_call", """\
z = sorted([3, 1])
print(z)
""", "[1, 3]\n")

    test_gimple_stdout("gimple_global_from_enumerate_call", """\
z = enumerate([7, 8])
print(z)
""", "[(0, 7), (1, 8)]\n")

    # `range()` returned `void *`, so nothing downstream could attach an
    # element type and the leading 0 hit the repr's int-vs-pointer
    # heuristic and printed the None sentinel: `[None, 1, 2]`.
    test_gimple_stdout("gimple_global_from_range_call", """\
z = range(3)
print(z)
""", "[0, 1, 2]\n")

    # Container-returning METHODS took a third path, which hardcoded
    # int64_t instead of consulting the estimator at all.
    test_gimple_stdout("gimple_global_from_dict_method_call", """\
z = {"a": 1}.keys()
w = {"a": 1}.values()
print(z)
print(w)
""", "['a']\n[1]\n")

    test_gimple_stdout("gimple_global_from_str_method_call", """\
z = "a,b".split(",")
print(z)
""", "['a', 'b']\n")

    # ── map() / filter() ───────────────────────────────────────────────
    # The runtime's mojo_map/mojo_filter are IDENTITY STUBS (a char*
    # function pointer cannot call back into a GIMPLE-compiled body), so
    # `map` handed back the input list unchanged, `list(map(f, xs))` printed
    # the INPUT rather than the mapped values, and `for v in map(f, xs):`
    # iterated the wrong values. The per-element calls are now lowered in
    # the codegen, which is also what lets the result's element type be
    # known.
    test_gimple_stdout("gimple_map_value", """\
print(list(map(lambda v: v * 2, [1, 2])))
""", "[2, 4]\n")

    test_gimple_stdout("gimple_map_for_loop", """\
for v in map(lambda v: v + 1, [1, 2, 3]):
    print(v)
""", "2\n3\n4\n")

    # A builtin callee: the result elements are strings, and recording them
    # as int64_t printed the two string ADDRESSES as decimals.
    test_gimple_stdout("gimple_map_builtin_str", """\
print(list(map(str, [1, 2])))
""", "['1', '2']\n")

    test_gimple_stdout("gimple_filter_value", """\
print(list(filter(lambda v: v > 1, [1, 2, 3])))
""", "[2, 3]\n")

    # filter keeps the INPUT's elements: appending the predicate's verdict
    # instead made this `[1, 1]` (two truthy verdicts, both the value 1).
    test_gimple_stdout("gimple_filter_for_loop", """\
for v in filter(lambda v: v > 1, [1, 2, 3]):
    print(v)
""", "2\n3\n")

    # ── Booleans print as True/False ───────────────────────────────────
    # Every printed boolean went through the generic numeric path
    # (printf_fmt('_Bool') -> "%d"), so `print(True)` printed `1`. This is
    # not about any/all: a bare literal was wrong too.
    test_gimple_stdout("gimple_bool_literal_prints", """\
print(True)
print(False)
""", "True\nFalse\n")

    test_gimple_stdout("gimple_bool_comparison_prints", """\
print(1 == 1)
print(1 == 2)
""", "True\nFalse\n")

    # A bool local: its C type is the plain int a BoolLiteral lowers to, so
    # the static type alone cannot see it — the name is recorded instead.
    test_gimple_stdout("gimple_bool_local_prints", """\
b = True
print(b)
""", "True\n")

    # any/all/isinstance are C ints by design; only the static type knows
    # the value is a bool.
    test_gimple_stdout("gimple_bool_builtin_prints", """\
print(any([0, 1]))
print(all([1, 1]))
print(isinstance(1, int))
print(1 in [1, 2])
""", "True\nTrue\nTrue\nTrue\n")

    # ── round() ────────────────────────────────────────────────────────
    # The one-argument form had no lowering at all and returned a float, so
    # `round(2.6)` printed `3.0`; Python returns an int. Python also rounds
    # half to even, which C's `round()` does NOT (it gives 3 for 2.5), so
    # `rint` is the correct libm call.
    test_gimple_stdout("gimple_round_one_arg_returns_int", """\
print(round(2.6))
print(round(2.5))
print(round(-2.5))
""", "3\n2\n-2\n")

    # The two-argument form was DEAD CODE: it sat below the arity fixup that
    # clamps arguments to the callee's known C signature, and `round`'s is
    # libc's `double round(double)` — one parameter — so the ndigits
    # argument was dropped and `round(2.567, 2)` computed `round(2.567)`.
    test_gimple_stdout("gimple_round_two_args_keeps_ndigits", """\
print(round(2.567, 2))
""", "2.57\n")

    # ── dict keys held in an untyped int64 slot ────────────────────────
    # A lambda parameter is typed int64_t whatever it is handed, so a string
    # key arrives as its pointer bits with nothing recorded anywhere. The
    # codegen stringified that by address and looked up "97", so
    # `d[k]` returned 0.
    test_gimple_stdout("gimple_dict_key_from_untyped_slot", """\
d = {"a": 1}
f = lambda k: d[k]
print(f("a"))
""", "1\n")

    # ── Lambdas that close over the enclosing function ──────────────────
    # A lambda is lifted to a top-level C function, so a value it reads from
    # the function it was written in has nowhere to live in a plain code
    # address. Those reads used to be emitted as a hard 0:
    #     d = {"a": 1}
    #     f = lambda k: d[k]
    #     print(f("a"))          ->  0
    # silently wrong — latent in the compiler's own source only because the
    # self-hosted binary compiles uncached and never calls the builder. A
    # closing lambda is now a MojoBoundMethod: the lifted function takes a
    # heap env as its first parameter and the value materialized at the
    # reference site is `mojo_bound_method_new(fn, env)`. It works at every
    # call site because mojo_fnptr_call_N dispatches on the callee.
    test_gimple_stdout("gimple_lambda_captures_enclosing_local", """\
def main():
    d = {"a": 1}
    f = lambda k: d[k]
    print(f("a"))

main()
""", "1\n")

    # …as a sorted() key, the shape that also required the forward
    # declaration to mirror the definition's own parameter resolution (the
    # call site binds the dict's `char *` key element to the lambda's
    # parameter, so an independently computed declaration said `char *` where
    # the definition inferred `int64_t`).
    test_gimple_stdout("gimple_lambda_capture_as_sorted_key", """\
def main():
    d = {"b": 2, "a": 1}
    print(sorted(d, key=lambda k: d[k]))

main()
""", "['a', 'b']\n")

    # …as a map() callable, whose per-element calls the codegen lowers itself.
    test_gimple_stdout("gimple_lambda_capture_in_map", """\
def main():
    n = 3
    print(list(map(lambda v: v + n, [1, 2])))

main()
""", "[4, 5]\n")

    test_gimple_stdout("gimple_lambda_capture_scalar", """\
def main():
    n = 10
    f = lambda v: v + n
    print(f(5))

main()
""", "15\n")

    # The default-argument capture form still works, and a parameter must NOT
    # be treated as capturing without a real default: the old
    # `default is None and pname in var_types` fallback gave every parameter
    # an env field it never read, and the body emitted `_env->v` against a
    # struct with no such member.
    #
    # This also happens to be one of only two lowerings in the whole suite
    # that route a boxed int64_t through mojo_cstr_or_int_str, so it
    # silently became a regression test for the runtime's str-vs-container
    # discriminator. The emitted C is correct on its own (`_env->d` is read
    # properly) and this printed 0 when mojo_boxed_is_str was aliased to
    # _mojo_tagged_addr_ok: that predicate's 8-byte-alignment and
    # malloc_usable_size >= 8 requirements are obligations for reading an
    # int64_t type tag, and a .rodata string literal satisfies NEITHER
    # (measured: `"a"` lands at an address whose low 3 bits are 7, with
    # malloc_size() == 0). The literal key was therefore formatted as a
    # decimal address and the dict lookup missed. See the sorted-key tests
    # above for the same root cause seen from the other side, and
    # runtime/fire_runtime.c's mojo_boxed_is_str docstring for the fix.
    test_gimple_stdout("gimple_lambda_captures_via_default_arg", """\
def main():
    d = {"a": 1}
    f = lambda k, d=d: d[k]
    print(f("a"))

main()
""", "1\n")

    # ── Transient dict keys / concat temporaries are RELEASED, borrowed ones
    # are not (doc/MEMORY.html section 4). Two directions, both needed:
    # the leak (an Int-keyed dict in a loop grew ~48 B/iteration) and the
    # over-free (freeing a key that was really a borrowed string would crash
    # or corrupt the dict). 4M iterations leaked ~190 MB before the release;
    # the limit is a tripwire far below that and far above the ~10 MB floor.
    test_gimple_bounded_memory("gimple_int_dict_key_release_bounded", """\
def main():
    var d: Dict[Int, Int] = {}
    var total = 0
    for i in range(3000000):
        d[i % 10] = i
        total += d[i % 10] - i + 1
        if (i % 10) in d:
            total += 1
        total += d.get(i % 7, 0) - d.get(i % 7, 0)
    print(total)
    print(len(d))

main()
""", "6000000\n10\n", 40)

    test_gimple_stdout("gimple_dict_key_release_keeps_borrowed_string_key", """\
def main():
    d = {"a": 1, "bb": 2}
    f = lambda k, d=d: d[k]
    print(f("a"))
    print(f("bb"))
    print(f("a") + f("bb"))
    n = {1: 10, 2: 20}
    n[3] = 30
    n[1] += 5
    print(n[1], n[2], n[3], len(n))
    print(2 in n, 9 in n)
    print(n.get(2, 0), n.get(9, -1))
    del n[2]
    print(len(n))

main()
""", "1\n2\n3\n15 20 30 3\nTrue False\n20 -1\n2\n")

    test_gimple_stdout("gimple_concat_chain_does_not_free_aliased_operand", """\
def main():
    a = String("ab")
    s = a + String("cd")
    t = s + String("ef")
    u = t + s
    print(s)
    print(t)
    print(u)
    n = String("n=") + 7 + String("!")
    print(n)

main()
""", "abcd\nabcdef\nabcdefabcd\nn=7!\n")

    # ── Loop-body-scoped container destruction (doc/MEMORY.html section 7.1).
    # A container declared directly in a loop body is owned by that body:
    # freed at the end of each iteration and before every break/continue/
    # return that leaves it. Two things are pinned at once — the printed
    # results (so an over-free or a wrong exit path shows up as a wrong
    # answer or a crash) and peak RSS (so a missing free shows up as a leak
    # several times the limit; unfixed, each of these grows ~100-300 MB).
    test_gimple_bounded_memory("gimple_loop_scoped_containers_all_exit_paths", """\
def early_return(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var l: List[Int] = []
        l.append(i)
        l.append(i * 2)
        if i == 7:
            return t + len(l) * 100 + l[1]
        t += len(l)
    return -1

def brk_cont(n: Int) -> Int:
    var t = 0
    for i in range(n):
        if i % 5 == 0:
            continue
        var d: Dict[String, Int] = {}
        d["a"] = i
        if i == 13:
            break
        if i % 2 == 0:
            continue
        t += d["a"]
    return t

def nested(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var outer: List[Int] = []
        outer.append(i)
        for j in range(4):
            var inner: Dict[String, Int] = {}
            inner["k"] = j
            if j == 2:
                continue
            if j == 3:
                break
            t += inner["k"] + len(outer)
        t += len(outer)
    return t

def while_loop(n: Int) -> Int:
    var t = 0
    var i = 0
    while i < n:
        var s = {1, 2, 3}
        s.add(i)
        i += 1
        if i == 6:
            continue
        t += len(s)
    return t

def main():
    print(early_return(20))
    print(brk_cont(30))
    print(nested(10))
    print(while_loop(10))
    var total = 0
    for k in range(200000):
        total += early_return(9) + brk_cont(16) + nested(3) + while_loop(4)
    print(total)
""", "228\n31\n40\n33\n56800000\n", 40)

    test_gimple_bounded_memory("gimple_loop_scoped_containers_freed_on_exception_unwind", """\
def boom(n: Int) raises:
    if n % 3 == 0:
        raise Error("boom")

def scan(i: Int) -> Int:
    var t = 0
    try:
        for k in range(4):
            var l: List[Int] = []
            l.append(k)
            l.append(i)
            boom(k + i)
            t += len(l)
    except:
        t += 100
    return t

def main():
    var total = 0
    for i in range(150000):
        total += scan(i)
    print(total)
""", "15300000\n", 40)

    # ── Solver widening + small-buffer lists (doc/MEMORY.html sections 3.B, 7).
    # Non-empty literals are stack-homed and freed per iteration; a local that
    # is only iterated, passed to callees that provably never keep it, or
    # declared under the same name in sibling loops is still owned by its loop
    # body. Bounded RSS pins the free; the printed values pin that nothing was
    # freed too early (every one of these read the container after its last
    # mutation and across the small-buffer boundary).
    test_gimple_bounded_memory("gimple_loop_scoped_nonempty_literals_stack_homed", """\
def work(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var a = [1, 2, 3, i]
        var b = {1, 2, i % 3}
        var d = {"x": i, "y": 2}
        var s = ["p", "q"]
        t += len(a) + a[3] + len(b) + d["x"] + d["y"] + len(s) + len(s[0])
        if i == 2:
            continue
        if i == 7:
            return t * 1000 + len(a)
    return t

def main():
    print(work(10))
    var total = 0
    for k in range(150000):
        total += work(5)
    print(total)
""", "147004\n11550000\n", 40)

    test_gimple_bounded_memory("gimple_solver_callee_summaries_iteration_sibling_loops", """\
def total(l: List[Int]) -> Int:
    var t = 0
    for x in l:
        t += x
    return t

def fill(mut l: List[Int], n: Int):
    for i in range(n):
        l.append(i)

def sibling(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var tmp: List[Int] = []
        tmp.append(i)
        t += len(tmp)
    for j in range(n):
        var tmp: List[Int] = []
        tmp.append(j)
        tmp.append(j)
        t += len(tmp)
    return t

def main():
    var acc = 0
    for i in range(200000):
        var a: List[Int] = []
        fill(a, 6)
        acc += total(a) + sibling(3)
        var c = 0
        for y in a:
            if y > 2:
                c += y
        acc += c
    print(acc)
""", "7200000\n", 40)

    # A list starts in a 4-slot inline buffer and is copied to the heap when it
    # outgrows it; insert/pop/reverse/extend/slice and a returned (escaping)
    # list all cross that boundary. (The `[10, 20]` argument to extend and the
    # slice result are call-result containers, which still leak by design, so
    # this one checks values only.)
    test_gimple_stdout("gimple_list_small_buffer_growth_boundary", """\
def grow(n: Int) -> Int:
    var t = 0
    for r in range(n):
        var a: List[Int] = []
        for i in range(r + 1):
            a.append(i * 3)
        t += len(a) + a[0] + a[len(a) - 1]
    return t

def ops() -> Int:
    var l: List[Int] = []
    for i in range(3):
        l.append(i)
    l.insert(0, 99)
    l.insert(2, 77)
    l.append(5)
    l.append(6)
    l.append(7)
    var s = 0
    for x in l:
        s += x
    var p = l.pop()
    l.reverse()
    var m = [10, 20]
    l.extend(m)
    var c = l[1:4]
    return s * 1000 + p + len(l) * 7 + len(c) + l[0] + l[len(l) - 1]

def heap_escape(n: Int) -> List[Int]:
    var r: List[Int] = []
    for i in range(n):
        r.append(i + 1)
    return r

def main():
    print(grow(9))
    print(ops())
    var h = heap_escape(2)
    var g = heap_escape(6)
    print(len(h), h[1], len(g), g[5])
    var acc = 0
    for k in range(100000):
        acc += (grow(6) + ops()) % 1000
    print(acc)
""", "153\n197099\n2 2 6 6\n16500000\n")

    # ── Temporary containers (doc/MEMORY.html section 7): a container built by
    # an expression and consumed exactly once — a `for` iterable (display,
    # comprehension), an `extend` source (display, slice, `+` result), a `+`
    # operand — is freed by its consumer. Every exit from the loop over a
    # temporary is exercised (normal, `break`, `continue`, an early `return`),
    # and the printed values pin that nothing was freed before it was read.
    test_gimple_bounded_memory("gimple_temporary_containers_freed_by_consumer", """\
def work(n: Int) -> Int:
    var t = 0
    var base: List[Int] = [1, 2, 3]
    for i in range(n):
        for z in [v * 2 for v in base]:
            t += z
            if z == 4:
                break
        var acc: List[Int] = []
        acc.extend([i, 1])
        acc.extend(base[0:2])
        acc.extend([1, 2] + [3])
        t += len(acc) + acc[0]
        for q in [10, 20]:
            if i == n - 1 and q == 20:
                return t * 100 + q
            if q == 10:
                continue
            t += q
    return t

def main():
    print(work(1))
    print(work(5))
    var total = 0
    for k in range(60000):
        total += work(4) % 1000
    print(total)
""", "1320\n15520\n49200000\n", 40)

    # A local bound from a CALL RESULT (a slice, a comprehension, `.keys()`, a
    # `+`) owns its value only when codegen can prove the value fresh at the
    # declaration (emit_infra.maybe_push_owned_local). The other half of this
    # test is the point: `stored = h.get()` returns `self.items`, a container
    # the struct still owns, so it must NEVER be freed — if the freshness check
    # were wrong the second call would read a freed list, and the final sum of
    # `h.items` (printed last) would not be 6.
    test_gimple_bounded_memory("gimple_call_result_locals_owned_only_when_fresh", """\
struct Holder:
    var items: List[Int]

    def __init__(out self):
        self.items = [1, 2, 3]

    def get(self) -> List[Int]:
        return self.items

def work(h: Holder, base: List[Int], d: Dict[String, Int], n: Int) -> Int:
    var t = 0
    for i in range(n):
        var a = base[0:2]
        var c = [v + i for v in base]
        var k = d.keys()
        var s = base + base
        var stored = h.get()
        t += len(a) + a[1] + len(c) + c[2] + len(k) + len(s) + s[4] + len(stored) + stored[0]
        if i == 2:
            continue
        if i == 3:
            break
    return t

def main():
    var h = Holder()
    var base: List[Int] = [5, 6, 7]
    var d: Dict[String, Int] = {"x": 1, "y": 2}
    print(work(h, base, d, 2))
    print(work(h, base, d, 9))
    print(len(h.items))
    var total = 0
    for k in range(50000):
        total += work(h, base, d, 6) % 1000
    print(total)
    print(h.items[0] + h.items[1] + h.items[2])
""", "73\n150\n3\n7500000\n6\n", 40)

    # A caller owns what a user function returns only when the function is
    # PROVEN to hand back a brand-new container (ownership_destruct.
    # analyze_returns_fresh: every path returns a display or a local built once
    # from one that escapes only through the return, or `return l^`). `mk`/
    # `mk_direct` qualify, also when only their length is read (`len(mk(i))`);
    # `Box.get` returns a list the struct still owns, so `s = bx.get()` must
    # never be freed — the last printed value (the sum of `bx.items`, 24) is
    # what a wrongly freed list would corrupt.
    test_gimple_bounded_memory("gimple_fresh_returning_functions_owned_by_caller", """\
struct Box:
    var items: List[Int]

    def __init__(out self):
        self.items = [7, 8, 9]

    def get(self) -> List[Int]:
        return self.items

def mk(i: Int) -> List[Int]:
    var l: List[Int] = []
    l.append(i)
    l.append(i + 1)
    return l^

def mk_direct(i: Int) -> List[Int]:
    return [i, 2]

def work(bx: Box, n: Int) -> Int:
    var t = 0
    for i in range(n):
        var a = mk(i)
        var b = mk_direct(i)
        var s = bx.get()
        t += len(a) + a[1] + b[0] + b[1] + s[0] + s[2]
        t += len(mk(i)) + len(mk_direct(i)) + len(bx.get())
        if i == 1:
            continue
        if i == 4:
            break
    return t

def main():
    var bx = Box()
    print(work(bx, 3))
    print(work(bx, 9))
    var total = 0
    for k in range(60000):
        total += work(bx, 6) % 1000
    print(total)
    print(bx.items[0] + bx.items[1] + bx.items[2])
""", "90\n160\n9600000\n24\n", 40)

    # ── Struct instances (doc/MEMORY.html section 7): a local bound to a
    # constructor call of a VETTED struct is owned — freed at scope exit — only
    # while every use is a field access, a method that provably never retains
    # `self`, or a function whose parameter provably is not kept; and only if
    # `__init__` does not retain `self`. The first program is the positive case
    # under a memory bound. The second has, next to an owned struct, one that
    # `enroll` stores into a list the caller keeps: it must NOT be freed, and the
    # checksum over the enrolled structs (printed 4th) is read after `work` has
    # returned, so a wrongly freed struct corrupts it.
    test_gimple_bounded_memory("gimple_struct_locals_owned_when_never_retained", """\
struct Pt:
    var x: Int
    var y: Int

    def __init__(out self, x: Int, y: Int):
        self.x = x
        self.y = y

    def total(self) -> Int:
        return self.x + self.y

def peek(q: Pt) -> Int:
    return q.x * 2

def work(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var p = Pt(i, 3)
        t += p.total() + peek(p) + p.x
        p.x = 1
        t += p.x
        if i == 2:
            continue
        if i == 4:
            break
    return t

def once(k: Int) -> Int:
    var p = Pt(k, 5)
    return p.total() + peek(p)

def main():
    print(work(3))
    print(work(9))
    var total = 0
    for r in range(400000):
        total += work(6) % 1000 + once(r % 100)
    print(total)
""", "24\n60\n85400000\n", 40)

    test_gimple_stdout("gimple_struct_local_retained_by_a_method_is_not_freed", """\
struct Pt:
    var x: Int
    var y: Int

    def __init__(out self, x: Int, y: Int):
        self.x = x
        self.y = y

    def total(self) -> Int:
        return self.x + self.y

    def enroll(self, into: List[Pt]):
        into.append(self)

def peek(q: Pt) -> Int:
    return q.x * 2

def work(n: Int, kept: List[Pt]) -> Int:
    var t = 0
    for i in range(n):
        var p = Pt(i, 3)
        t += p.total() + peek(p) + p.x
        var q = Pt(i + 1, 4)
        q.enroll(kept)
        t += q.y
        if i == 2:
            continue
        if i == 4:
            break
    return t

def main():
    var kept: List[Pt] = []
    print(work(3, kept))
    print(work(9, kept))
    print(len(kept))
    var s = 0
    for k in range(len(kept)):
        s += kept[k].x * 10 + kept[k].y
    print(s)
    var total = 0
    for r in range(40000):
        var kk: List[Pt] = []
        total += work(6, kk) % 1000 + len(kk)
    print(total)
""", "33\n75\n8\n242\n3200000\n")

    # ── Strings bound to locals (doc/MEMORY.html section 3.B). A local bound
    # to a provably FRESH string (a `+` result, `String(i)`, a slice) is owned and
    # freed at scope exit, but only when every use is a read: `len`, a comparison,
    # a condition, the left operand of `+`, a right operand after a string
    # literal, and method calls whose result is consumed on the spot. The second
    # program is the other half: `str(y)` can RETURN its own argument, so `b2`
    # aliases `y`, which is then stored in a list the caller keeps, and `y` may not
    # be freed. (`z.strip()` no longer aliases `z`: the str methods always return a
    # copy, so `z` IS freed while `a2` lives on in the list.) The runner scribbles
    # freed memory, so a wrong free makes the comparisons (printed 4th) fail
    # instead of usually passing.
    test_gimple_bounded_memory("gimple_string_locals_owned_when_only_read", """\
def work(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var s = String("n=") + String(i)
        t += len(s)
        if s == "n=3":
            t += 100
        var u = s + "!"
        t += len(u)
        var w = "id:" + s
        t += len(w)
        if len(s) > 2:
            t += 1
        if i == 2:
            continue
        if i == 4:
            break
    return t

def once(k: Int) -> Int:
    var s = String("k") + String(k)
    return len(s) + len(s + "z")

def main():
    print(work(3))
    print(work(9))
    var total = 0
    for r in range(300000):
        total += work(6) % 1000 + once(r % 100)
    print(total)
""", "42\n170\n53040000\n", 40)

    # The str methods always return a copy (runtime `_str_fresh_copy`), so a local bound
    # to `s.strip()` / `.upper()` / `.replace()` / `.lower().lstrip()` is owned and freed
    # each iteration, and a method chain no longer keeps the receiver alive.
    test_gimple_bounded_memory("gimple_string_method_results_are_owned", """\
def work(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var s = String("  n=") + String(i) + String("  ")
        var a = s.strip()
        var b = a.upper()
        var c = b.replace("N", "M")
        var d = c.lower().lstrip()
        t += len(a) + len(b) + len(c) + len(d)
        if c == "M=3":
            t += 100
    return t

def main():
    print(work(3))
    print(work(9))
    var total = 0
    for r in range(300000):
        total += work(6) % 1000
    print(total)
""", "36\n208\n51600000\n", 40)

    test_gimple_stdout("gimple_string_local_aliased_by_strip_or_str_is_not_freed", """\
def work(n: Int, kept: List[String]) -> Int:
    var t = 0
    for i in range(n):
        var s = String("n=") + String(i)
        t += len(s)
        var z = String("x") + String(i)
        var a2 = z.strip()
        kept.append(a2)
        var y = String("y") + String(i)
        var b2 = str(y)
        kept.append(b2)
        if i == 2:
            continue
        if i == 4:
            break
    return t

def main():
    var kept: List[String] = []
    print(work(3, kept))
    print(work(9, kept))
    print(len(kept))
    var hits = 0
    for k in range(len(kept)):
        if kept[k] == "x0":
            hits += 1
        if kept[k] == "x1":
            hits += 10
        if kept[k] == "y2":
            hits += 100
        if kept[k] == "x4":
            hits += 1000
        if kept[k] == "y3":
            hits += 10000
    print(hits)
    var total = 0
    for r in range(20000):
        var kk: List[String] = []
        total += work(6, kk) % 1000
    print(total)
""", "9\n15\n16\n11222\n300000\n")

    # ── Integer dict keys (doc/MEMORY.html section 10.4). An Int key is stored as an
    # INTEGER slot (its decimal string kept alongside, so iteration/repr/copy/pop
    # are unchanged) and looked up through `_kw` entry points that take the raw
    # word. Every operation is exercised — set, get, augmented set, `in`,
    # `get(k, default)`, `pop`, `del`, `setdefault`, negative/zero/large keys, a
    # string-keyed dict next to them, and a dict created and dropped in a loop —
    # against CPython's answers. (The C shape is pinned in test_gimple.py.)
    test_gimple_stdout("gimple_int_dict_keys_word_lookup_all_operations", """\
def main():
    var d: Dict[Int, Int] = {}
    for i in range(1000):
        d[i % 37] = i
    var acc = 0
    for i in range(1000):
        acc += d[i % 37] % 5
        if (i % 41) in d:
            acc += 1
    d[5] += 100
    acc += d[5] % 1000
    acc += d.get(9999, -3) + d.get(3, 0)
    acc += d.pop(4)
    del d[6]
    acc += len(d)
    print(acc)
    var n: Dict[Int, Int] = {}
    n[0] = 7
    n[-1] = 8
    n[-2000000000] = 9
    n[2000000000] = 10
    n[12] = 11
    n[12] += 1
    print(n[0] + n[-1] + n[-2000000000] + n[2000000000] + n[12])
    print(len(n))
    print(-1 in n)
    print(-2 in n)
    print(n.setdefault(77, 5))
    print(n.setdefault(0, 99))
    print(len(n))
    var s: Dict[String, Int] = {}
    s["abc"] = 1
    s["12"] = 2
    s["abd"] = 3
    print(s["abc"] + s["12"] + s["abd"])
    print(len(s))
    print("12" in s)
    print("13" in s)
    var tot = 0
    for r in range(20000):
        var e: Dict[Int, Int] = {}
        for k in range(10):
            e[k * 3 - 7] = k
        tot += e[2] + len(e)
        if (r % 3) in e:
            tot += 1
    print(tot)
""", "5017\n46\n5\nTrue\nFalse\n5\n7\n6\n6\n3\nTrue\nFalse\n266666\n")

    # ── An unannotated integer local is 64-bit (bugs/CODEGEN_unannotated_int_local_is_32_bit.md).
    # `var a = 0` used to be a 32-bit `int`, so the accumulator wrapped at 2^31 while
    # `var b: Int = 0` and CPython both reached 6000000000.
    test_gimple_stdout("gimple_unannotated_integer_local_is_64_bit", """\
def main():
    var a = 0
    var b: Int = 0
    for i in range(3):
        a += 2000000000
        b += 2000000000
    print(a)
    print(b)
    var c = 1
    for i in range(40):
        c = c * 2
    print(c)
    var d = 5
    d = d * 1000000000
    print(d)
""", "6000000000\n6000000000\n1099511627776\n5000000000\n")

    # ── Struct methods get the same ownership treatment as plain functions, and the typed
    # empty constructors `List[T]()` / `Dict[K, V]()` / `Set[T]()` are containers like `[]`/`{}`:
    # stack-homed when they do not escape, freed at scope exit when they must live on the heap.
    # A method that stores a local into `self` (or returns it) must NOT free it.
    test_gimple_bounded_memory("gimple_struct_method_locals_and_typed_constructors_are_owned", """\
struct Acc:
    var total: Int
    var held: List[Int]

    def __init__(out self):
        self.total = 0
        self.held = List[Int]()

    def work(mut self, n: Int):
        for i in range(n):
            var l = [i, i + 1, i + 2]
            var d: Dict[Int, Int] = {}
            d[i] = i
            var s = String("k") + String(i)
            self.total += len(l) + len(d) + len(s)

    def build(self, n: Int) -> Int:
        var l = List[Int]()
        for i in range(n):
            l.append(i)
        var e = Dict[Int, Int]()
        e[1] = 2
        var t = Set[Int]()
        t.add(3)
        return len(l) + len(e) + len(t)

    def remember(mut self, n: Int):
        var l = List[Int]()
        l.append(n)
        self.held = l

    def make(self, n: Int) -> List[Int]:
        var l = List[Int]()
        l.append(n)
        return l

def main():
    var a = Acc()
    for r in range(200000):
        a.work(6)
        a.total += a.build(5)
    a.remember(41)
    var m = a.make(7)
    print(a.total)
    print(a.held[0])
    print(m[0])
    print(len(a.held) + len(m))
""", "8600000\n41\n7\n2\n", 40)

    # ── A struct instance that is an owned local and never escapes lives in the frame
    # (`_init_P (&storage)`), not on the heap; one that is returned or stored in a list is
    # still heap-allocated and must survive its function (the runner scribbles freed memory).
    test_gimple_bounded_memory("gimple_owned_struct_locals_live_in_the_frame", """\
struct P:
    var x: Int
    var y: Int

    def __init__(out self, x: Int, y: Int):
        self.x = x
        self.y = y

    def sum(self) -> Int:
        return self.x + self.y

def work(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var p = P(i, i + 1)
        t += p.sum()
        var q = P(p.y, p.x)
        t += q.x - q.y
    return t

def once(k: Int) -> Int:
    var p = P(k, 2)
    return p.sum()

def make(k: Int) -> P:
    var p = P(k, 5)
    return p

def keep(k: Int, out_list: List[P]):
    var p = P(k, 9)
    out_list.append(p)

def main():
    print(work(4))
    var total = 0
    for r in range(300000):
        total += work(6) % 1000 + once(r % 10)
    print(total)
    var m = make(3)
    var kept: List[P] = []
    for k in range(3):
        var p = P(k, 9)
        kept.append(p)
    print(m.x + m.y)
    print(kept[0].y + kept[1].x + kept[2].sum())
""", "20\n14550000\n8\n21\n", 40)

    # ── A dict owns its key strings: a key that escapes by iteration (`for k in d: out.append(k)`)
    # must keep the dict from being freed, or the returned list dangles (the runner scribbles freed
    # memory and a second allocation reuses the block). Real: fire_compiler's Parser._parse_paren_args.
    test_gimple_stdout("gimple_dict_key_escaping_by_iteration_is_not_freed_with_the_dict", """\
def pairs(n: Int) -> List[String]:
    var keywords: Dict[String, Int] = {}
    keywords["alpha" + String(n)] = n
    keywords["beta" + String(n)] = n + 1
    var out: List[String] = []
    for k in keywords:
        out.append(k)
    return out

def main():
    var a = pairs(1)
    var b = pairs(2)
    var junk = String("zzzzzzzzzzzz") + String(7)
    print(len(a))
    print(a[0])
    print(a[1])
    print(b[0])
""", "2\nalpha1\nbeta1\nalpha2\n")

    # ── Iterating a Dict[Int, V] yields integer keys (bugs/CODEGEN_iterating_an_int_keyed_dict_yields_string_keys.md).
    # The keys used to come back as decimal STRINGS typed `char *`, so `ks += k` added
    # pointers. Covers `for k in d`, `.keys()`, `.items()` (pair and unpacked forms, a
    # parameter) and a string-keyed dict reusing the loop name (which must stay strings).
    test_gimple_stdout("gimple_int_keyed_dict_iteration_yields_ints", """\
def total(d: Dict[Int, Int]) -> Int:
    var t = 0
    for k, v in d.items():
        t += k * 100 + v
    return t

def main():
    var d: Dict[Int, Int] = {}
    d[5] = 50
    d[7] = 70
    d[1] = 10
    var ks = 0
    for k in d:
        ks += k
    print(ks)
    var tot = 0
    for kv in d.items():
        tot += kv[0] + kv[1]
    print(tot)
    var t2 = 0
    for kv in d.items():
        t2 += kv.key * 2
    print(t2)
    var t3 = 0
    for k in d.keys():
        t3 += k
    print(t3)
    print(total(d))
    var s: Dict[String, Int] = {}
    s["a"] = 1
    for k in s:
        print(k)
""", "13\n143\n26\n13\n1430\na\n")

    # ── zip() / dict.items() pair shapes ───────────────────────────────
    # zip and dict.items() yield TUPLES. Unmarked, they printed as
    # `[[1, 3], [2, 4]]`; and a pair's first slot is a real value (the 0
    # INDEX of the first pair), which the generic element repr answers
    # "None" for, giving `[(None, 2), (1, 3)]`.
    test_gimple_stdout("gimple_zip_value_pairs_are_tuples", """\
print(zip([0, 1], [2, 3]))
""", "[(0, 2), (1, 3)]\n")

    test_gimple_stdout("gimple_dict_items_pairs_are_tuples", """\
print({"a": 1}.items())
""", "[('a', 1)]\n")

    test_gimple_stdout("gimple_enumerate_start_and_strings", """\
print(list(enumerate([7, 8], 1)))
print(list(enumerate(["a", "b"])))
print(list(enumerate(["a", "b"], start=5)))
""", "[(1, 7), (2, 8)]\n[(0, 'a'), (1, 'b')]\n[(5, 'a'), (6, 'b')]\n")

    # The `for` and comprehension forms were already right — pinned so the
    # value-position work cannot regress them.
    test_gimple_stdout("gimple_enumerate_for_and_comprehension_unchanged", """\
for i, v in enumerate([7, 8]):
    print(i, v)
print([i for i, v in enumerate([7, 8])])
print([v for i, v in enumerate([7, 8], 3)])
""", "0 7\n1 8\n[0, 1]\n[7, 8]\n")

    # 15c. ... and a module's OWN `def String(...)` still wins over the
    # builtin alias (the same shadowing guarantee `str`/`enumerate`/
    # `hasattr` already have).
    test_gimple_stdout("gimple_capitalized_constructor_shadowing", """\
def String(v):
    return "shadowed"

print(String(7))
""", "shadowed\n")

    # 16. Same two-param concat shape, but called DIRECTLY inline inside the
    # f-string's `{...}` interpolation — no intermediate variable at all.
    # bugs/CODEGEN_untyped_param_string_direct_fstring_call.md: an f-string
    # interpolation's `{expr}` sub-expression is raw source text kept inside
    # the StringLiteral node, only parsed at actual codegen time — it was
    # invisible to the earlier cross-call scalar-contract call-site scan
    # (_collect_calls/_calls_in_stmts) that the `y = g(...)` shape above
    # goes through, so `g`'s param/return types never got corrected from
    # int64_t to char* for this shape specifically.
    test_gimple_stdout("gimple_untyped_param_string_direct_fstring_call", """\
def g(a, b):
    return a + b
print(f"result: {g('a', 'b')}")
""", "result: ab\n")

    test_gimple_stdout("gimple_print_double_python_repr", """\
def main():
    x = 2.0 * 2.5
    print(x)
    print(10.0)
    print(1.0e20)
    print(0.1 + 0.2)
    print([x, 1.5])
""", "5.0\n10.0\n1e+20\n0.30000000000000004\n[5.0, 1.5]\n")

    # 17. Dynamic-attribute Steps 1-4 (bugs/hard/CODEGEN_dynamic_attribute_
    # on_generic_object.md): a genuinely NEW attribute set on an opaque
    # object (real per-object storage, not a silent no-op) and a MISSING
    # dynamic attribute raising a real, catchable AttributeError (not the
    # old silent-0 stub) -- both required for this doc's own minimal repro
    # (`try: x = cls.__slot_names__ except AttributeError: ...`) to behave
    # correctly, not merely "stop erroring at compile time". Checks the
    # first call takes the except branch (miss, initializes), and a SECOND
    # call with the same object takes the fast path and sees the value the
    # first call actually stored -- confirms mojo_setattr's storage is
    # real and persists per-object, not just that mojo_raise_attribute_
    # error fires once.
    test_gimple_stdout("gimple_dynamic_attribute_real_storage_and_attributeerror", """\
class Holder:
    pass


def get_or_init(cls):
    try:
        slotnames = cls.__slot_names__
        print("fast path, got:", len(slotnames))
    except AttributeError:
        print("miss, initializing")
        slotnames = cls.__slot_names__ = []
    slotnames.append("x")
    return slotnames


def main():
    h = Holder()
    r1 = get_or_init(h)
    print("after first call:", len(r1))
    r2 = get_or_init(h)
    print("after second call:", len(r2))


main()
""", "miss, initializing\nafter first call: 1\nfast path, got: 1\nafter second call: 2\n")

    # 18. Sub-case C (bugs/hard/CODEGEN_dynamic_attribute_on_generic_
    # object.md Step 4): a dynamic attribute set/read on a value whose
    # static type resolved to one of this codegen's own FIXED-layout
    # runtime structs (MojoBoundMethod, here -- a capturing closure) rather
    # than an opaque int64_t/void*. Confirmed real instance: Tools/scripts/
    # var_access_benchmark.py's `inner.__name__ = 'read_nonlocal'` / a
    # later `f.__name__` read. Before this fix: a hard GCC "'MojoBoundMethod'
    # has no member named '__name__'" compile failure (the write went
    # through a raw `->__name__` field write no such C struct field exists
    # for) -- not merely a wrong runtime value, an outright compile error.
    test_gimple_stdout("gimple_dynamic_attribute_fixed_runtime_struct_bound_method", """\
def make_closure():
    captured = 10

    def inner():
        return captured + 1

    return inner


def main():
    f = make_closure()
    f.__name__ = "read_nonlocal"
    print(f.__name__)
    print(f())


main()
""", "read_nonlocal\n11\n")

    # 19. (bugs/CODEGEN_keyword_only_ctor_call_skips_earlier_default.md) A
    # keyword-only constructor call must fill every SKIPPED earlier param
    # with its own declared default, not 0. Before the fix: `Derived(b=99)`
    # emitted a=0, b=99, c=3 -- a silent wrong value, invisible to any
    # compile-only gate.
    test_gimple_stdout("gimple_ctor_kwarg_skipped_earlier_defaults", """\
struct Base:
    var a: Int
    var b: Int
    var c: Int
    fn __init__(out self, a: Int = 1, b: Int = 2, c: Int = 3):
        self.a = a
        self.b = b
        self.c = c

fn main():
    var d = Base(b=99)
    print(d.a)
    print(d.b)
    print(d.c)

main()
""", "1\n99\n3\n")

    # 20. Same bug through the **kwargs ctor slot: unknown keywords pack
    # into the dict while earlier defaulted params keep their real default.
    test_gimple_stdout("gimple_ctor_kwargs_pack_keeps_earlier_default", """\
struct Cfg:
    var verbose: Int
    var rest: Dict[String, Int]
    fn __init__(out self, verbose: Int = 5, **rest):
        self.verbose = verbose
        self.rest = rest

fn main():
    var c = Cfg(level=2)
    print(c.verbose)

main()
""", "5\n")

    # 21. Builtin `dict` subclassing (Counter/OrderedDict shape) -- see
    # bugs/COMPILE_FAIL_collections___init__.md. `class X(dict)` gets a
    # synthesized `_data: MojoDict *` backing store allocated by
    # `_alloc_X`; inherited `d[k]`, `d[k] = v`, `d[k] += n`, `k in d`,
    # `len(d)` route to it, and `__missing__` handles a subscript-read
    # miss (Counter uses this to return 0). A compile-only gate can't
    # catch a wrong runtime value here.
    test_gimple_stdout("gimple_dict_subclass_counter_shape", """\
class Bag(dict):
    def __missing__(self, key) -> int:
        return 0

def main():
    b = Bag()
    b["a"] = 5
    b["a"] += 3
    b["b"] += 1
    print(b["a"])
    print(b["b"])
    print(b["never_set"])
    print(len(b))
    if "a" in b:
        print("has a")
    if "zzz" not in b:
        print("no zzz")
""", "8\n1\n0\n2\nhas a\nno zzz\n")

    # 21b. Inherited container METHODS on a dict-subclass instance —
    # `.get()/.keys()/.values()/.items()/.update()/.pop()/.setdefault()`
    # and `for k in d` — delegate to the hidden `_data` backing store.
    # A compile-only gate can't catch a wrong runtime value here.
    test_gimple_stdout("gimple_dict_subclass_container_method_delegation", """\
class Bag(dict):
    def __missing__(self, key) -> int:
        return 0

def main():
    b = Bag()
    b["a"] = 5
    b["b"] = 2
    b["c"] = 9
    print(b.get("a"))
    print(b.get("zzz", 42))
    total = 0
    for k in b:
        total += b[k]
    print(total)
    for k, v in b.items():
        print(v)
    print(len(b.keys()))
    s = 0
    for x in b.values():
        s += x
    print(s)
    other = Bag()
    other["d"] = 1
    b.update(other)
    print(len(b))
    print(b.pop("a"))
    print(b.setdefault("e", 7))
    print(b.setdefault("b", 100))
""", "5\n42\n16\n5\n2\n9\n3\n16\n4\n5\n7\n2\n")

    # 21c. A subclass method override beats builtin-dict delegation, and
    # delegation still reaches through a transitive (non-overriding) base.
    test_gimple_stdout("gimple_dict_subclass_override_beats_delegation", """\
class Bag(dict):
    def keys(self) -> str:
        return "override"

class Sub(Bag):
    def __missing__(self, key) -> int:
        return 0

def main():
    s = Sub()
    s["x"] = 1
    s["y"] = 2
    print(s.keys())
    print(s.get("x"))
    for k, v in s.items():
        print(k)
""", "override\n1\nx\ny\n")

    # 21d. Builtin `bytes` subclassing (`class _Extra(bytes)`, zipfile) --
    # see bugs/COMPILE_FAIL_zipfile___init__.md. `super().__new__(cls, v)`
    # populates the synthesized `_data: MojoBytes *` payload; inherited
    # len/index/slice/iter/eq/concat/`in`/`.decode`/`.hex`/`.startswith`/
    # `.split` route to it; extra `self.<attr>` fields sit alongside;
    # `isinstance(_, bytes)` is true; a method override wins. A
    # compile-only gate can't catch a wrong runtime value here.
    # NOTE on the bool expectations in the bytes/memoryview tests below
    # (`True`/`False`, where they previously read `1`/`0`): every printed
    # boolean used to take the generic numeric path and print its int form.
    # Python prints True/False, so those expectations were wrong and are
    # corrected here rather than preserved.
    test_gimple_stdout("gimple_bytes_subclass_shape", """\
class Extra(bytes):
    def __new__(cls, v, id=0):
        return super().__new__(cls, v)
    def __init__(self, v, id=0):
        self.id = id

def main():
    e = Extra(b"hello world", 42)
    print(len(e))
    print(e[1])
    print(e.id)
    print(e[0:5].decode())
    if e == b"hello world":
        print("eq")
    if b"wor" in e:
        print("contains")
    total = 0
    for c in e:
        total += c
    print(total)
    print(e.hex())
    print(e.startswith(b"hello"))
    parts = e.split(b" ")
    print(len(parts))
    if isinstance(e, bytes):
        print("is bytes")
    c2 = e + b"!"
    print(c2.decode())
""", "11\n101\n42\nhello\neq\ncontains\n1116\n68656c6c6f20776f726c64\nTrue\n2\nis bytes\nhello world!\n")

    test_gimple_stdout("gimple_bytes_subclass_method_override", """\
class B(bytes):
    def __new__(cls, v):
        return super().__new__(cls, v)
    def hex(self) -> str:
        return "OVR"

def main():
    b = B(b"ab")
    print(b.hex())
    print(len(b))
""", "OVR\n2\n")

    # 21e. `b''.join(<iterable of bytes-subclass instances>)` operates on
    # each element's `_data` payload (zipfile's `_Extra.strip`).
    test_gimple_stdout("gimple_bytes_subclass_join", """\
class B(bytes):
    def __new__(cls, v):
        return super().__new__(cls, v)

def main():
    xs = [B(b"aa"), B(b"bb"), B(b"cc")]
    print(b"-".join(xs).decode())
""", "aa-bb-cc\n")

    # Slice-assignment really mutates the list in place (full + bounded,
    # growing and shrinking, pure insert, negative bounds) — this is the
    # regression guard for bugs/CODEGEN_slice_assignment_silently_noops.md
    # (compiled `x[a:b] = y` used to be a silent no-op).
    test_gimple_stdout("gimple_slice_assign_mutation", """\
def main():
    a = [1, 2, 3]
    a[0:2] = [7, 8]
    print(a[0])
    print(a[1])
    print(a[2])
    b = [1, 2]
    b[:] = [9, 9, 5]
    print(len(b))
    print(b[2])
    c = [1, 2, 3, 4, 5]
    c[1:4] = [0]
    print(len(c))
    print(c[1])
    print(c[2])
    d = [1, 2, 3]
    d[1:1] = [8, 8]
    print(len(d))
    print(d[1])
    print(d[3])
    e = [1, 2, 3, 4]
    e[-2:] = [9]
    print(len(e))
    print(e[2])
    f = [0, 0, 0, 0, 0]
    f[::2] = [1, 2, 3]
    print(f[0])
    print(f[1])
    print(f[2])
    print(f[4])
    g = [1, 2, 3, 4]
    g[::-1] = [10, 20, 30, 40]
    print(g[0])
    print(g[3])
""", "7\n8\n3\n3\n5\n3\n0\n5\n5\n8\n2\n3\n9\n1\n0\n2\n3\n40\n10\n")

    # ── bytes value type (Stage 1) ───────────────────────────────────────
    test_gimple_stdout("gimple_bytes_literal_len_index", """\
fn main():
    var b = b'\\x00\\x01ABC'
    print(len(b))
    print(b[2])
    print(b[-1])
    print(b[0])
""", "5\n65\n67\n0\n")

    test_gimple_stdout("gimple_bytes_constructors", """\
fn main():
    var z = bytes(3)
    print(len(z), z[0])
    var l = bytes([65, 66, 67])
    print(len(l), l[0], l[2])
    var e = bytes()
    print(len(e))
    var s = bytes("hi", "utf-8")
    print(len(s), s[0], s[1])
""", "3 0\n3 65 67\n0\n2 104 105\n")

    test_gimple_stdout("gimple_bytes_equality_and_truthiness", """\
fn main():
    if b'ab' == b'ab':
        print("eq")
    if b'ab' != b'ac':
        print("ne")
    var b = b'x'
    if b:
        print("truthy")
    var e = bytes()
    if not e:
        print("empty-falsy")
""", "eq\nne\ntruthy\nempty-falsy\n")

    test_gimple_stdout("gimple_bytes_through_functions", """\
fn tail(b: bytes) -> bytes:
    return b

fn size(b = b'abcd') -> Int:
    return len(b)

fn main():
    var t = tail(b'XYZ')
    print(len(t), t[0])
    print(size())
    print(size(b'hello'))
""", "3 88\n4\n5\n")

    test_gimple_stdout("gimple_bytes_repr_print", """\
fn main():
    print(b'a\\x00\\nZ')
""", "b'a\\x00\\nZ'\n")

    # ── bytes value type (Stage 2) ───────────────────────────────────────
    test_gimple_stdout("gimple_bytes_slice", """\
fn main():
    var b = b'Hello, World'
    print(b[0:5])
    print(b[7:])
    print(b[::-1])
    print(b[::2])
""", "b'Hello'\nb'World'\nb'dlroW ,olleH'\nb'Hlo ol'\n")

    test_gimple_stdout("gimple_bytes_iter_and_in", """\
fn main():
    var total = 0
    for x in b'ABC':
        total += x
    print(total)
    if b'ell' in b'Hello':
        print("sub")
    if 101 in b'Hello':
        print("byte")
""", "198\nsub\nbyte\n")

    test_gimple_stdout("gimple_bytes_concat_repeat", """\
fn main():
    print(b'ab' + b'cd')
    print(b'xy' * 3)
    print(3 * b'-')
""", "b'abcd'\nb'xyxyxy'\nb'---'\n")

    test_gimple_stdout("gimple_bytes_methods", """\
fn main():
    print(b'Hello'.startswith(b'He'))
    print(b'Hello'.endswith(b'lo'))
    print(b'a,b,c'.split(b','))
    print(b'a-b-c'.replace(b'-', b'_'))
    print(b'  hi  '.strip())
    print(b'AbC'.upper())
    print(b'abcabc'.find(b'c'))
    print(b'abcabc'.count(b'bc'))
    print(b'DEADBEEF'.hex())
    print(b'hello'.decode('utf-8'))
    print(b','.join(b'x,y'.split(b',')))
""", "True\nTrue\n[b'a', b'b', b'c']\nb'a_b_c'\nb'hi'\nb'ABC'\n2\n2\n4445414442454546\nhello\nb'x,y'\n")

    test_gimple_stdout("gimple_bytes_isinstance", """\
fn main():
    var b = b'x'
    if isinstance(b, bytes):
        print("is-bytes")
    if not isinstance(5, bytes):
        print("int-not-bytes")
""", "is-bytes\nint-not-bytes\n")

    # ── bytes value type (Stage 2b) ──────────────────────────────────────
    test_gimple_stdout("gimple_bytes_percent_format", """\
fn main():
    var n: Int = 42
    print(b'val=%d' % n == b'val=42')
    print(b'%s!' % b'hi' == b'hi!')
    print(b'%02x' % 15 == b'0f')
    print(b'%s=%d;' % (b'k', 7) == b'k=7;')
    print(b'%5d|' % 3 == b'    3|')
""", "True\nTrue\nTrue\nTrue\nTrue\n")

    test_gimple_stdout("gimple_bytes_param_inferred_from_body", """\
fn dec(data) -> String:
    return data.decode('utf-8')
fn main():
    print(dec(b'hello'))
""", "hello\n")

    test_gimple_stdout("gimple_bytes_param_inferred_from_slice_destination", """\
fn header_size(p):
    var header = b''
    if len(p) > 0:
        header = p[0:2]
    return len(header)
fn main():
    print(header_size(b'abcdef'))
""", "2\n")

    test_gimple_stdout("gimple_list_param_slice_destination_stays_list", """\
fn header_size(p):
    var header = []
    header = p[0:2]
    return len(header)
fn main():
    print(header_size([1, 2, 3]))
""", "2\n")

    # ── bytes value type (Stage 3): bytearray + memoryview ───────────────
    test_gimple_stdout("gimple_bytearray_mutation", """\
fn main():
    var ba = bytearray(b'abc')
    ba.append(100)
    ba[0] = 90
    print(1 if bytes(ba) == b'Zbcd' else 0)
    ba.extend(b'XY')
    var x = ba.pop()
    print(x)
    del ba[0]
    print(1 if bytes(ba) == b'bcdX' else 0)
    ba[1:3] = b'ZZZ'
    print(1 if bytes(ba) == b'bZZZX' else 0)
    var t = 0
    for c in ba:
        t = t + c
    print(t)
""", "1\n89\n1\n1\n456\n")

    test_gimple_stdout("gimple_memoryview", """\
fn main():
    var mv = memoryview(b'hello')
    print(mv[1])
    print(len(mv))
    print(1 if mv[1:3].tobytes() == b'el' else 0)
    print(mv.hex())
    print(1 if mv == b'hello' else 0)
    var t = 0
    for x in mv:
        t = t + x
    print(t)
""", "101\n5\n1\n68656c6c6f\n1\n532\n")

    # ── bytes/bytearray/memoryview: the API surface that used to lower to
    # a silent `0` stub (the `_stub_result('int', '0', ...)` fallthrough at
    # the end of _lower_bytes_method) instead of anything real.
    test_gimple_stdout("gimple_bytes_search_family", """\
fn main():
    print(b'abcabc'.find(b'c'))
    print(b'abcabc'.rfind(b'c'))
    print(b'abcabc'.index(b'c'))
    print(b'abcabc'.index(b'c', 3))
    print(b'abcabc'.rfind(b'c', 0, 4))
    print(b'abcabc'.count(b'bc'))
    print(b'abcabc'.count(b'bc', 0, 5))
    print(b'abc'.index(98))
    print(b'abcb'.count(98))
    print(b'abc'.rindex(99))
    print(b'abcabc'.find(b'z'))
""", "2\n5\n2\n5\n2\n2\n1\n1\n2\n2\n-1\n")

    test_gimple_stdout("gimple_bytes_case_and_affix_methods", """\
fn main():
    print(b'hello world'.title())
    print(b'hELLO'.capitalize())
    print(b'Hello'.swapcase())
    print(b'abcabc'.removeprefix(b'ab'))
    print(b'abcabc'.removesuffix(b'bc'))
    print(b'abc'.removeprefix(b'zz'))
    print(b'a'.ljust(5, 46))
    print(b'a'.rjust(5, 46))
    print(b'a'.center(5, 46))
    print(b'a'.ljust(5, b'.'))
    print(b'a'.rjust(5, b'-'))
    print(b'a'.center(5, b'*'))
    print(b'ab'.ljust(5, b'.'))
    print(b'ab'.center(5, b'.'))
    print(b'a'.ljust(2, b'.'))
    print(b'a'.ljust(fillchar=b'#', width=4))
    print(b'42'.zfill(5))
    print(b'-42'.zfill(5))
    print(b'42'.zfill(2))
""", "b'Hello World'\nb'Hello'\nb'hELLO'\nb'cabc'\nb'abca'\nb'abc'\n"
     "b'a....'\nb'....a'\nb'..a..'\n"
     "b'a....'\nb'----a'\nb'**a**'\nb'ab...'\nb'..ab.'\nb'a.'\nb'a###'\n"
     "b'00042'\nb'-0042'\nb'42'\n")

    # `isprintable` and `isnumeric` are `str` methods. CPython raises
    # AttributeError for them on a `bytes` receiver, and so does this
    # compiler's own interpreter reference (myinterpreter.py leaves them to
    # Python's bytes). They used to be IMPLEMENTED here anyway, on the
    # stated grounds that "Python defines only the ASCII flavours of these on
    # bytes" — which is not what CPython does — so `b'a'.isprintable()`
    # answered True and the two families disagreed with the reference. The
    # honest answer is the raise, which is what CPython gives; a wrong-length
    # fill is the same shape of error.
    test_gimple_runtime_error("gimple_bytes_isprintable_raises", """\
fn main():
    print(b'a'.isprintable())
""", "AttributeError: 'bytes' object has no attribute 'isprintable'")

    test_gimple_runtime_error("gimple_bytes_isnumeric_raises", """\
fn main():
    print(b'1'.isnumeric())
""", "AttributeError: 'bytes' object has no attribute 'isnumeric'")

    test_gimple_runtime_error("gimple_bytes_bad_fill_length_raises", """\
fn main():
    print(b'a'.ljust(4, b'..'))
""", "TypeError: ljust() argument 2 must be a byte string of length 1, not 2")

    # `ljust`/`rjust`/`center`'s fillchar is a ONE-BYTE value, and in
    # CPython the only spelling that produces one is a one-byte `bytes` —
    # the bare int these two cases use is a fire extension (kept: the
    # corpus and the case above both use it), and it must not have
    # displaced the CPython spelling. It used to: the bytes fill was read
    # as a scalar, so `b'a'.ljust(4, b'.')` padded with the low byte of a
    # HEAP ADDRESS and printed a different wrong value on every run.
    # A wrong LENGTH is a TypeError, at runtime (the fill is not a
    # compile-time constant) — see gimple_bytes_bad_fill_length_raises.
    test_gimple_stdout("gimple_bytes_affix_bytes_fillchar", """\
fn main():
    print(b'ab'.ljust(6, b'_'))
    print(b'ab'.rjust(6, b'_'))
    print(b'ab'.center(6, b'_'))
    print(b'x'.ljust(4, b'\\x00'))
    var f = b'='
    print(b'ab'.ljust(5, f))
    print(b'ab'.ljust(5, b'xy'[0:1]))
""", "b'ab____'\nb'____ab'\nb'__ab__'\nb'x\\x00\\x00\\x00'\nb'ab==='\nb'abxxx'\n")

    # CPython's `bytes` predicates, transcribed. Three of these EXPECTED
    # strings were wrong and this case is why the bugs survived:
    #   * `b''.isalpha()`/`b''.isdigit()` were expected True. Python's
    #     "every char is in C" is False over an empty string; only isascii
    #     (and isprintable, which `bytes` does not have) is vacuously True.
    #   * `b'a b'.isprintable()` was expected True. `isprintable` is a
    #     `str` method: `b'a b'.isprintable()` is an AttributeError in
    #     CPython AND in this compiler's own interpreter reference, so
    #     asking it of a `bytes` receiver is now a real raise, pinned by
    #     gimple_bytes_str_only_predicates_raise below. Its slot here is
    #     taken by isascii on a non-ASCII byte.
    # The islower/isupper/istitle rows are new and were all wrong: a
    # `bytes` predicate ignores UNCASED characters, so `b'ab1'.islower()`
    # is True, and istitle needs at least one cased char and a fresh title
    # run after every uncased one.
    test_gimple_stdout("gimple_bytes_predicates", """\
fn main():
    print(b'abc'.isalpha(), b'a1'.isalnum(), b'12'.isdigit())
    print(b' '.isspace(), b'AB'.isupper(), b'ab'.islower())
    print(b'Hello World'.istitle(), b'hi'.isascii(), b'\xff'.isascii())
    print(b'ab1'.isalpha(), b'ab'.isupper(), b'Hello world'.istitle())
    print(b''.isalpha(), b''.isdigit())
    print(b''.isalnum(), b''.isspace(), b''.islower(), b''.isupper())
    print(b''.istitle(), b''.isascii())
    print(b'ab1'.islower(), b'AB1'.isupper(), b'1ab'.islower(), b'1AB'.isupper())
    print(b'1'.istitle(), b'_'.istitle(), b'A1B'.istitle(), b'a1B'.istitle())
    print(b'Hello_World'.istitle(), b'Hello world'.istitle())
""", "True True True\nTrue True True\nTrue True False\nFalse False False\n"
     "False False\nFalse False False False\nFalse True\n"
     "True True True True\nFalse False True False\nTrue False\n")

    # The `str` half of the same ten predicates. `isprintable`/`isnumeric`
    # are `str`-only in CPython and were NOT implemented on this side at
    # all: `"1".isnumeric()` fell to the generic unknown-method stub and
    # answered a raw int `0` — printed as `0`, not `False`, and wrong for
    # `"1"` (True) and for `"a".isprintable()` (also True). `istitle` and
    # `isascii` were missing the same way. They now share the bytes
    # predicates' kernel, so the two families cannot drift again.
    # LIMITATION, stated here because it is a real divergence: the kernel
    # works over a UTF-8 byte window and has no Unicode category table, so
    # a non-ASCII char is "not in any ASCII class" — `'é'.isalpha()` is
    # False here and True in CPython, and `'²'.isnumeric()` likewise. That
    # limit already applied to isalpha/isalnum/isdigit/isspace before this
    # change; isprintable is exact over ASCII and the C1 control block.
    test_gimple_stdout("gimple_str_predicates", """\
fn main():
    print('a'.isalpha(), ''.isalpha(), 'a1'.isalpha())
    print('12'.isdigit(), ''.isdigit(), '1a'.isdigit())
    print('a1'.isalnum(), ''.isalnum(), 'a-'.isalnum())
    print('a b'.isspace(), ''.isspace(), 'a'.isspace())
    print('A1'.isupper(), '1'.isupper(), ''.isupper(), 'A1'.islower())
    print('a1'.islower(), '_'.islower(), ''.islower(), 'A_1'.islower())
    print('Hello World'.istitle(), '1'.istitle(), ''.istitle())
    print('A1B'.istitle(), 'a1B'.istitle(), 'Hello world'.istitle())
    print('hi'.isascii(), ''.isascii(), chr(0xff).isascii())
    print('a'.isprintable(), ' '.isprintable(), ''.isprintable())
    print(chr(9).isprintable(), chr(0x7f).isprintable())
    print('1'.isnumeric(), 'a'.isnumeric(), ''.isnumeric(), '12x'.isnumeric())
""", "True False False\nTrue False False\nTrue False False\nFalse False False\n"
     "True False False False\nTrue False False False\n"
     "True False False\nTrue False False\nTrue True False\n"
     "True True True\nFalse False\nTrue False False False\n")

    # partition/rpartition return a TUPLE in CPython and were returning an
    # unmarked list here, so the three expected strings below said `[...]`
    # where CPython says `(...)`. Two more divergences in the same function,
    # both found while fixing that one and neither in the original report:
    #   * the no-match arms were SWAPPED between the two methods, so
    #     `b'abc'.partition(b'=')` and `b'abc'.rpartition(b'=')` each
    #     returned the other's answer — on the common case of a separator
    #     that is not present, not an edge case;
    #   * an EMPTY separator is a ValueError in CPython and was answered
    #     `(b'', b'', b'a=b')` here (pinned by the raise case below).
    test_gimple_stdout("gimple_bytes_partition_split_limits", """\
fn main():
    print(b'a=b'.partition(b'='))
    print(b'a=b=c'.rpartition(b'='))
    print(b'abc'.partition(b'='))
    print(b'abc'.rpartition(b'='))
    print(b''.partition(b'='))
    print(b'=a'.partition(b'='))
    print(b'a==b'.rpartition(b'='))
    print(b'a,b,c'.split(b',', 1))
    print(b'a,b,c'.rsplit(b',', 1))
    print(b'a,b,c'.split(b',', maxsplit=1))
    print(b'a b  c'.split())
    print(b'a\\nb\\n'.splitlines(True))
    print(b'aaa'.replace(b'a', b'b', 2))
    print(b'aaa'.replace(b'a', b'b', 0))
""", "(b'a', b'=', b'b')\n(b'a=b', b'=', b'c')\n(b'abc', b'', b'')\n(b'', b'', b'abc')\n"
     "(b'', b'', b'')\n(b'', b'=', b'a')\n(b'a=', b'=', b'b')\n"
     "[b'a', b'b,c']\n[b'a,b', b'c']\n[b'a', b'b,c']\n[b'a', b'b', b'c']\n"
     "[b'a\\n', b'b\\n']\nb'bba'\nb'aaa'\n")

    test_gimple_runtime_error("gimple_bytes_partition_empty_sep_raises", """\
fn main():
    print(b'a=b'.partition(b''))
""", "ValueError: empty separator")

    test_gimple_stdout("gimple_bytes_fromhex_maketrans_translate", """\
fn main():
    print(bytes.fromhex('68656c6c6f'))
    print(bytes.fromhex('68 65 6c'))
    print(bytes.fromhex('DEADBEEF'))
    print(b'abc'.translate(bytes.maketrans(b'a', b'b')))
    print(b'abc'.translate(bytes.maketrans(b'a', b'b', b'c')))
    print(b'abc'.translate(bytes(range(256))))
""", "b'hello'\nb'hel'\nb'\\xde\\xad\\xbe\\xef'\nb'bbc'\nb'bbc'\nb'abc'\n")

    test_gimple_stdout("gimple_bytes_membership_in_containers", """\
fn main():
    print(1 if b'a' in [b'a', b'b'] else 0)
    print(1 if b'c' in [b'a', b'b'] else 0)
    var d = {}
    d[b'a'] = 1
    print(d[b'a'], 1 if b'a' in d else 0)
    var s = {b'a', b'b'}
    print(1 if b'a' in s else 0, len(s))
    s.add(b'a')
    print(len(s))
    for x in s:
        print(x)
""", "1\n0\n1 1\n1 2\n2\nb'a'\nb'b'\n")

    # A needle in a DIFFERENT domain than the container's elements is not a
    # comparison the runtime can perform, and the domains already imply the
    # answer: `b'a' == 'a'` is False in Python, so `'a' in [b'a', b'b']` is
    # False. The list case used to cast the `char *` needle to `MojoBytes *`
    # instead, which gcc -fgimple rejects outright — a hard compile error,
    # not a wrong value. Separate case from the set iteration above because
    # set iteration ORDER is not part of what is being pinned here, and
    # adding locals to that program perturbs it.
    test_gimple_stdout("gimple_bytes_membership_across_domains", """\
fn main():
    print(1 if 'a' in [b'a', b'b'] else 0)
    print(1 if b'a' in ['a', 'b'] else 0)
    print(1 if 'a' in {'a', 'b'} else 0)
    var d = {}
    d[b'a'] = 1
    print(1 if 'a' in d else 0, 1 if b'a' in d else 0)
    print(1 if 'a' in (b'q',) else 0, 1 if b'a' in ('q',) else 0)
""", "0\n0\n1\n0 1\n0 0\n")

    # A bytes KEY is its own dict key domain, so `d[b'a']` and `d['a']` are
    # two distinct entries (Python's answer) rather than one aliasing the
    # other — and a bytes-keyed read finds what a bytes-keyed write stored.
    test_gimple_stdout("gimple_bytes_dict_key_domain", """\
fn main():
    var d = {}
    d[b'a'] = 1
    d['a'] = 2
    print(d[b'a'], d['a'], len(d))
    print(1 if 'a' in d else 0, 1 if b'a' in d else 0)
    var e = {b'x': 1.5}
    print(e[b'x'])
    var g = {b'y': 'z'}
    print(g[b'y'])
    var h = {}
    print(h.setdefault(b'k', 7), h[b'k'])
    var f = {b'a', 'a'}
    print(len(f), 1 if 'a' in f else 0, 1 if b'a' in f else 0)
""", "1 2 2\n1 1\n1.5\nz\n7 7\n2 1 1\n")

    # ...and so must get/pop, which read the same domain they wrote. They
    # did not: both called `_char_to_cstr` on the `MojoBytes *` — casting
    # the POINTER to a char* — and then emitted the str-domain runtime
    # helper, so `d[b'a'] = 7; d.get(b'a')` answered 0 and `d.pop(b'a')`
    # neither found the key nor removed it. `setdefault` already guarded on
    # the key type, which is exactly why only these two were wrong. The
    # runtime halves (mojo_dict_get_bytes_*, mojo_dict_pop_bytes_int) were
    # already there and correct; the call sites just never named them.
    test_gimple_stdout("gimple_bytes_dict_get_pop_bytes_key", """\
fn main():
    var d = {}
    d[b'a'] = 7
    print(d.get(b'a'), d.get(b'z'), d.get(b'z', -1))
    print(d.pop(b'a'), len(d), 1 if b'a' in d else 0)
    var e = {}
    e[b'a'] = 7
    e[b'b'] = 8
    print(e.pop(b'z', -1), len(e))
    print(e.pop(b'a'), e.pop(b'b'), len(e))
    var f = {}
    f[b'k'] = 3
    print(f.setdefault(b'k', 9), f.get(b'k'), len(f))
    var g = {}
    g[b'k'] = 3
    print(g.setdefault(b'j', 9), g.get(b'j'), g.get(b'k'), len(g))
    var h = {b's': 'v'}
    print(h.get(b's'), h.pop(b's'), len(h))
    var m = {b'f': 1.5}
    print(m.get(b'f'))
    # a str key and a bytes key are still two distinct entries
    var n = {}
    n[b'a'] = 1
    n['a'] = 2
    print(n.get(b'a'), n.get('a'), n.pop(b'a'), len(n), n['a'])
""", "7 0 -1\n7 0 0\n-1 2\n7 8 0\n3 3 1\n9 9 3 2\nv v 0\n1.5\n1 2 1 1 2\n")

    # A set's loop TARGET is a fresh binding, not a read of an existing
    # name, so two loops over sets of different element domains in one
    # function must both work. They did not: `_declare_var` is
    # first-decl-wins (deliberately, for every other caller), so the second
    # loop wrote its `char *` elements into the first loop's `MojoBytes *`
    # target and gcc -fgimple rejected the assignment — a hard compile
    # error. Not a bytes/set peculiarity: the int-then-str pair failed
    # identically. Accumulate rather than print: set ITERATION ORDER is not
    # what is under test and is not stable.
    test_gimple_stdout("gimple_set_loop_target_rebinds_across_domains", """\
fn main():
    var n = 0
    for x in {b'a', b'b'}:
        n = n + 1
    for x in {'p', 'q'}:
        n = n + len(x)
    for x in {1, 2}:
        n = n + x
    for x in {10, 20}:
        n = n + x
    print(n)
    print(x)
    var s = {b'z', b'y'}
    for x in s:
        n = n + 1
    for x in {'one', 'two'}:
        n = n + len(x)
    print(n, len(s))
""", "37\n20\n45 2\n")

    test_gimple_stdout("gimple_bytearray_index_remove_insert", """\
fn main():
    var ba = bytearray(b'abcb')
    print(ba.index(98), ba.count(98), ba.rfind(b'b'))
    ba.remove(98)
    print(bytes(ba))
    ba.insert(1, 88)
    print(bytes(ba))
    print(bytes(ba[1:3]))
""", "1 2 3\nb'acb'\nb'aXcb'\nb'Xc'\n")

    # `readonly` used to be constant-folded to False here, on the reasoning
    # that "this representation is always a writable 1-D byte window" — a
    # true statement about the WINDOW and an irrelevant one about the
    # ANSWER, which is the mutability of the object the view was taken
    # over. CPython: True for a bytes-backed view, False for a
    # bytearray-backed one, and True again after `bytes(...)` re-wraps it.
    test_gimple_stdout("gimple_memoryview_descriptors", """\
fn main():
    var mv = memoryview(b'abcd')
    print(mv.nbytes, mv.itemsize, mv.format)
    print(mv.obj)
    print(mv.readonly, mv.c_contiguous)
    print(len(mv.cast('B')))
    var ba = bytearray(b'abcd')
    print(memoryview(ba).readonly, memoryview(ba).c_contiguous)
    print(memoryview(bytes(ba)).readonly, memoryview(bytearray(b'xy')).readonly)
    print(mv.cast('B').readonly, mv[1:3].readonly)
    ba[0] = 90
    print(memoryview(ba).readonly)
""", "4 1 B\nb'abcd'\nTrue True\n4\nFalse True\nTrue False\nTrue True\nFalse\n")

    # ── constructor-call-site inference reaches METHOD bodies and
    # MemberExpr/BinaryOp arguments ───────────────────────────────────────
    # `Reader(self._p)` / `Reader(self._p + "!")` inside a method: the
    # ctor-argument observation pass only walked free functions and toplevel,
    # and only resolved bare literals/IdentExprs, so these contributed no
    # evidence, the `__init__` param stayed int64_t, and the field printed as
    # a raw pointer decimal.
    test_gimple_stdout("gimple_ctor_arg_from_method_self_field", """\
class Reader:
    def __init__(self, path):
        self._path = path

class Holder:
    def __init__(self, p):
        self._p = p
    def direct(self):
        var r = Reader(self._p)
        return r._path
    def concat(self):
        var r = Reader(self._p + "!")
        return r._path
    def literal(self):
        var r = Reader("lit")
        return r._path

fn main():
    var h = Holder("hello")
    print(h.direct())
    print(h.concat())
    print(h.literal())
""", "hello\nhello!\nlit\n")

    # The positive case is only safe because the evidence is UNANIMOOUS. A
    # slot with mixed `char *`/`double` call-site evidence must stay at the
    # default rather than pick a winner. (Each field here is separately
    # unanimous: a single field cannot be both types in this codegen's
    # one-type-per-field model at all.)
    test_gimple_stdout("gimple_ctor_arg_unanimous_str_and_int", """\
class FromStr:
    def __init__(self, label):
        self.label = label

class FromInt:
    def __init__(self, count):
        self.count = count

fn use_str():
    var o = FromStr("abc")
    return o.label
fn use_int():
    var o = FromInt(42)
    return o.count

fn main():
    print(use_str())
    print(use_int())
""", "abc\n42\n")

    # ── bytes value type (Stage 4): bytes-typed struct fields ────────────
    # `self._buf = b''` in __init__ makes the field a real bytes value, so
    # a slice of the field and `acc += <bytes>` accumulation work end to
    # end (was: char* field -> mojo_cstr_slice -> char*+MojoBytes* pointer
    # arithmetic + a GCC GIMPLE-FE ICE). COMPILE_FAIL_zipfile___init__.md.
    test_gimple_stdout("gimple_bytes_field_slice_and_augassign", """\
fn chunk() -> bytes:
    return b'hello world'

class Buf:
    def __init__(self):
        self._data = b''
        self._offset = 0

    def fill(self):
        self._data = chunk()

    def drain(self):
        var out = self._data[self._offset:]
        var more = self._data[0:2]
        out += more
        self._data = b''
        self._offset = 0
        return out

def main():
    b = Buf()
    b.fill()
    var r = b.drain()
    print(1 if r == b'hello worldhe' else 0)
    print(len(r))
""", "1\n13\n")

    # ── struct module (binary pack/unpack) ──────────────────────────────
    test_gimple_stdout("gimple_struct_calcsize", """\
fn main():
    print(struct.calcsize('<HH'))
    print(struct.calcsize('>i'))
    print(struct.calcsize('4s2h'))
    print(struct.calcsize('<10s'))
""", "4\n4\n8\n10\n")

    test_gimple_stdout("gimple_struct_pack_unpack_roundtrip", """\
fn main():
    var a = struct.pack('<HH', 1, 2)
    print(len(a), a[0], a[1], a[2], a[3])
    var ta = struct.unpack('<HH', a)
    print(ta[0], ta[1])
    var b = struct.pack('>i', 258)
    print(b[0], b[1], b[2], b[3])
    var tb = struct.unpack('>i', b)
    print(tb[0])
    var c = struct.pack('<q', -1)
    var tc = struct.unpack('<q', c)
    print(tc[0])
    var d = struct.pack('4s', b'ab')
    print(len(d), d[0], d[1], d[2])
    var td = struct.unpack('4s', d)
    print(1 if td[0] == b'ab\\x00\\x00' else 0)
""", "4 1 0 2 0\n1 2\n0 0 1 2\n258\n-1\n4 97 98 0\n1\n")

    test_gimple_stdout("gimple_struct_float_formats", """\
fn main():
    var p = struct.pack('<f', 1.5)
    var t = struct.unpack('<f', p)
    print(t[0])
    var p2 = struct.pack('>d', 2.25)
    var t2 = struct.unpack('>d', p2)
    print(t2[0])
""", "1.5\n2.25\n")

    # A format that MIXES ints and floats. The unpack result is one
    # MojoList, which carries a single element ctype, so this used to
    # degrade wholesale to int64 slots and hand back the float's raw IEEE
    # bits (1 4607182418800017408). The format is a compile-time constant,
    # so each slot's real kind IS statically known — the per-slot kinds are
    # recorded and every statically-indexed read of the result picks the
    # right accessor per index. `print(m)` is the whole-result repr, which
    # reads EVERY slot and so needs its own accessor per slot (see
    # mojo_repr_list_kinds); the un-assigned `print(struct.unpack(...))`
    # spelling is here too, because per-slot kinds are a property of the
    # VALUE and not of whether it was bound to a local.
    # NOT covered, and deliberately: iteration and a computed subscript.
    # Both read a slot whose index is not known at compile time, so the
    # consumer needs ONE static C type for a read that has no single right
    # answer — the same limit a heterogeneous `[1, 2.5]` literal has. See
    # bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md.
    test_gimple_stdout("gimple_struct_mixed_int_float_formats", """\
fn main():
    var m = struct.unpack('<if', b'\\x01\\x00\\x00\\x00\\x00\\x00\\x80?')
    print(m[0])
    print(m[1])
    var q = struct.unpack('>dhh', b'?\\xf0\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\x01')
    print(q[0])
    print(q[1])
    print(q[2])
    var b = struct.unpack('<Bd', b'\\x07\\x00\\x00\\x00\\x00\\x00\\x00\\xf0?')
    print(b[0])
    print(b[1])
    print(struct.unpack('<if', struct.pack('<if', 1, 1.0)))
    var n = struct.unpack('<if', struct.pack('<if', 1, 1.0))
    print(n)
    var c, d = struct.unpack('<if', struct.pack('<if', 1, 1.0))
    print(c)
    print(d)
    var s = struct.Struct('<if')
    print(s.unpack(struct.pack('<if', 1, 1.0)))
    var e, f = struct.unpack('<2sH', struct.pack('<2sH', b'ab', 7))
    print(e)
    print(f)
""", "1\n1.0\n1.0\n2\n1\n7\n1.0\n(1, 1.0)\n(1, 1.0)\n1\n1.0\n(1, 1.0)\nb'ab'\n7\n")

    # The uniform cases must be unchanged by the per-slot-kind path — and the
    # whole-result repr has to stay right for them too, which is a different
    # helper from the one a mixed format takes.
    test_gimple_stdout("gimple_struct_uniform_formats_still_uniform", """\
fn main():
    var d = struct.unpack('<2f', b'\\x00\\x00\\x80?\\x00\\x00\\x00@')
    print(d[0])
    print(d[1])
    print(d)
    var i = struct.unpack('<3i', b'\\x01\\x00\\x00\\x00\\x02\\x00\\x00\\x00\\x03\\x00\\x00\\x00')
    print(i[0])
    print(i[1])
    print(i[2])
    print(i)
    var s = struct.unpack('<4s', b'ab\\x00\\x00')
    print(s[0])
    print(s)
    print(struct.unpack('>dhh', struct.pack('>dhh', 1.0, 2, 1)))
    print(struct.unpack('<Bd', struct.pack('<Bd', 7, 1.0)))
    print(struct.unpack('<2sH', struct.pack('<2sH', b'ab', 7)))
""", "1.0\n2.0\n(1.0, 2.0)\n1\n2\n3\n(1, 2, 3)\nb'ab\\x00\\x00'\n(b'ab\\x00\\x00',)\n(1.0, 2, 1)\n(7, 1.0)\n(b'ab', 7)\n")

    # `struct`'s call surface is positional-only, with three measured
    # exceptions (`Struct(format=)`, and `buffer=`/`offset=` on both
    # `unpack_from`s). Before the arguments were bound, `node.kwargs` was
    # never read at all: `s.unpack_from(b, offset=2)` read offset 0 and
    # returned a well-formed tuple of the WRONG fields, and
    # `struct.calcsize(fmt='<HH')` returned 0 where CPython raises. Every
    # entry point is exercised here, and the exception text is compared
    # because the silent 0 was the whole failure.
    test_gimple_stdout("gimple_struct_keyword_arguments", """\
fn main():
    var b = b'\\x00\\x00\\x05\\x00\\x06\\x00'
    var s = struct.Struct('<HH')
    print(struct.unpack_from('<HH', b, offset=2)[0])
    print(struct.unpack_from('<HH', b, offset=2)[1])
    print(struct.unpack_from('<HH', buffer=b, offset=2)[0])
    print(s.unpack_from(b, offset=2)[0])
    print(s.unpack_from(buffer=b, offset=2)[0])
    print(struct.Struct(format='<HH').size)
    try:
        print(struct.calcsize(fmt='<HH'))
    except TypeError as e:
        print('calcsize:', e)
    try:
        print(struct.pack(fmt='<H', v=1))
    except TypeError as e:
        print('pack:', e)
    try:
        print(struct.unpack(fmt='<HH', buffer=b))
    except TypeError as e:
        print('unpack:', e)
    try:
        print(struct.iter_unpack(fmt='<HH', buffer=b))
    except TypeError as e:
        print('iter_unpack:', e)
    try:
        struct.pack_into('<HH', bytearray(8), offset=0, v=1, w=2)
        print('pack_into: no-error')
    except TypeError as e:
        print('pack_into:', e)
    try:
        print(s.pack(v=1, w=2))
    except TypeError as e:
        print('Struct.pack:', e)
    try:
        print(s.unpack(buffer=b))
    except TypeError as e:
        print('Struct.unpack:', e)
    try:
        s.pack_into(bytearray(8), offset=0, v=1, w=2)
        print('Struct.pack_into: no-error')
    except TypeError as e:
        print('Struct.pack_into:', e)
    try:
        print(struct.unpack_from('<HH', b, bogus=2))
    except TypeError as e:
        print('unpack_from bogus:', e)
    try:
        print(struct.unpack_from('<HH', b, buffer=b))
    except TypeError as e:
        print('unpack_from twice:', e)
    try:
        print(struct.unpack_from(buffer=b, offset=2))
    except TypeError as e:
        print('unpack_from no fmt:', e)
    try:
        print(s.unpack_from(offset=2))
    except TypeError as e:
        print('Struct.unpack_from no buf:', e)
    try:
        print(struct.Struct(bogus=1))
    except TypeError as e:
        print('Struct bogus:', e)
    # The expected text carries the compiled runtime's `TypeError: ` prefix
    # on `str(e)`, where CPython's `str(e)` is the bare message. That prefix
    # is a general, pre-existing divergence of this runtime's Exception
    # __str__ (it is there for a plain `raise ValueError('x')` too) and is
    # not what this test is about: the MESSAGE after the prefix is
    # character-for-character CPython's.
""", "5\n6\n5\n5\n5\n4\n"
        "calcsize: TypeError: _struct.calcsize() takes no keyword arguments\n"
        "pack: TypeError: _struct.pack() takes no keyword arguments\n"
        "unpack: TypeError: _struct.unpack() takes no keyword arguments\n"
        "iter_unpack: TypeError: _struct.iter_unpack() takes no keyword arguments\n"
        "pack_into: TypeError: _struct.pack_into() takes no keyword arguments\n"
        "Struct.pack: TypeError: Struct.pack() takes no keyword arguments\n"
        "Struct.unpack: TypeError: Struct.unpack() takes no keyword arguments\n"
        "Struct.pack_into: TypeError: Struct.pack_into() takes no keyword arguments\n"
        "unpack_from bogus: TypeError: unpack_from() got an unexpected keyword argument 'bogus'\n"
        "unpack_from twice: TypeError: argument for unpack_from() given by name ('buffer') and position (2)\n"
        "unpack_from no fmt: TypeError: unpack_from() takes at least 1 positional argument (0 given)\n"
        "Struct.unpack_from no buf: TypeError: unpack_from() missing required argument 'buffer' (pos 1)\n"
        "Struct bogus: TypeError: Struct() missing required argument 'format' (pos 1)\n")

    test_gimple_stdout("gimple_struct_unpack_from_and_error", """\
fn main():
    var u = struct.unpack_from('<H', b'\\xff\\x01\\x00\\x02', 2)
    print(u[0])
    try:
        var bad = struct.unpack('<HH', b'\\x01\\x00')
        print('no-error')
    except struct.error:
        print('caught')
""", "512\ncaught\n")

    # Stage 2 — struct.Struct instances (compiled-once format).
    test_gimple_stdout("gimple_struct_Struct_instance", """\
fn main():
    var s = struct.Struct('<HH')
    print(s.size)
    print(s.format)
    var t = s.unpack(b'\\x0a\\x00\\x14\\x00')
    print(t[0], t[1])
    var p = s.pack(3, 4)
    print(p[0], p[2])
    var u = s.unpack_from(b'\\x00\\x0a\\x00\\x14\\x00', 1)
    print(u[0], u[1])
""", "4\n<HH\n10 20\n3 4\n10 20\n")

    test_gimple_stdout("gimple_struct_Struct_class_attr", """\
struct CentralDir:
    FIELD_STRUCT = struct.Struct('<HH')

    fn read(self, data: bytes):
        var t = self.FIELD_STRUCT.unpack(data)
        print(t[0], t[1], self.FIELD_STRUCT.size)

fn main():
    var c = CentralDir()
    c.read(b'\\x01\\x00\\x02\\x00')
""", "1 2 4\n")

    # `Struct.format` and `Struct.size` are DATA attributes (CPython models
    # both as getset_descriptors on the type), not methods: reading one
    # gives the format string / the byte count, and CALLING one is a
    # TypeError. The call used to escape the struct-receiver dispatch
    # entirely — `format` is spelled like a container method, so it reached
    # the container-method name-guess and became `mojo_obj_call1(handle,
    # "format", 70)`, a runtime function that is a documented hardcoded
    # `return 0`: a silent wrong value with exit 0, indistinguishable from a
    # real 0. `size` is not in that list and instead fell through to a call
    # to the phantom C symbol `_MojoStructFmt_size`, a LINK failure. The
    # namespace is closed and fully modelled, so both are now the
    # determinate exception they are in CPython, and a name that is not an
    # attribute of the type at all is the AttributeError.
    test_gimple_stdout("gimple_struct_Struct_data_attr_call_raises", """\
fn main():
    var s = struct.Struct('<HH')
    print(s.size, s.format)
    try:
        s.format(70)
        print('no-error')
    except TypeError:
        print('format TypeError')
    try:
        s.size()
        print('no-error')
    except TypeError:
        print('size TypeError')
    try:
        s.nosuch(1)
        print('no-error')
    except AttributeError:
        print('nosuch AttributeError')
""", "4 <HH\nformat TypeError\nsize TypeError\nnosuch AttributeError\n")

    # A module-level runtime CONSTRUCTOR's result, returned from a function.
    # The lowering builds a real `MojoStructFmt *` (mojo_struct_new) and knows
    # its type exactly, but the type ESTIMATOR that writes the function's C
    # prototype had no row for it and answered `int64_t` — so the body was
    # obliged to box the handle through `void *` to satisfy the declaration,
    # and every consumer of the returned value degraded: `s.size` became
    # `_mojo_dispatch_getattr` on an untyped value and raised
    # `AttributeError: size` (exit 1) from a program CPython runs cleanly.
    # Both sides now read one table (mojo/middle/types.py's
    # _STRUCT_MODULE_FN_RETVALS), so they cannot disagree again.
    test_gimple_stdout("gimple_struct_ctor_result_returned_from_function", """\
fn make():
    return struct.Struct('<HH')

fn main():
    var s = make()
    print(s.size)
    print(s.format)

main()
""", "4\n<HH\n")

    # A method call on a struct passed as a free-function PARAMETER. Only the
    # method's NAME varies below, and nothing else about each class does: a
    # parameter used as a method receiver contributes no field accesses, so
    # the struct-inference branch never ran for it and the parameter was
    # decided entirely by a chain of name-based builtin-container fallbacks.
    # `get`/`items`/`keys` -> `MojoDict *`, `hex`/`decode` -> `MojoBytes *`,
    # `append`/`other` -> the `int64_t` default, `find` -> `int64_t` too
    # (its own name poisoned the field-access counter the string heuristic
    # gates on). Four of these eight crashed in a builtin container's runtime
    # helper; the other four boxed the `Box *` and printed it as a decimal
    # with exit 0. The call site is the only place this codegen ever knows
    # the argument's type, so that is where the answer now comes from.
    test_gimple_stdout("gimple_method_call_on_struct_param_not_mistyped", """\
class G:
    def __init__(self, v):
        self.v = v
    def get(self, a):
        return 1
class I:
    def __init__(self, v):
        self.v = v
    def items(self, a):
        return 2
class K:
    def __init__(self, v):
        self.v = v
    def keys(self, a):
        return 3
class A:
    def __init__(self, v):
        self.v = v
    def append(self, a):
        return 4
class F:
    def __init__(self, v):
        self.v = v
    def find(self, a):
        return 5
class H:
    def __init__(self, v):
        self.v = v
    def hex(self, a):
        return 6
class D:
    def __init__(self, v):
        self.v = v
    def decode(self, a):
        return 7
class O:
    def __init__(self, v):
        self.v = v
    def other(self, a):
        return 8

def use_g(p):
    return p.get(0)
def use_i(p):
    return p.items(0)
def use_k(p):
    return p.keys(0)
def use_a(p):
    return p.append(0)
def use_f(p):
    return p.find(0)
def use_h(p):
    return p.hex(0)
def use_d(p):
    return p.decode(0)
def use_o(p):
    return p.other(0)

def main():
    print(use_g(G('s')), use_i(I('s')), use_k(K('s')), use_a(A('s')))
    print(use_f(F('s')), use_h(H('s')), use_d(D('s')), use_o(O('s')))

main()
""", "1 2 3 4\n5 6 7 8\n")

    # The sharpest form of the same defect: BOTH spellings in one binary, on
    # the same object, one line apart. The local receiver was always right
    # (`self` is a known struct pointer, so `_lower_struct_method_call`
    # resolves it); the identical call arriving as an argument was not. There
    # was no diagnostic and the exit code was 0.
    test_gimple_stdout("gimple_method_call_on_struct_param_matches_local", """\
class Box:
    def __init__(self, v):
        self.v = v
    def get(self):
        return self.v

def meth(b):
    return b.get()

def main():
    b = Box('str')
    print(meth(b))
    print(b.get())

main()
""", "str\nstr\n")

    # A field read through the same parameter is unaffected (`char *` and no
    # builtin-container mis-typing), and a method on a REAL dict parameter
    # still resolves as a dict — the fix decides from the call site's argument
    # type, not from a blanket "prefer a user struct over a container".
    test_gimple_stdout("gimple_struct_param_field_and_dict_receiver_unaffected", """\
class Box:
    def __init__(self, v):
        self.v = v

def field(b):
    return b.v

def dict_size(d):
    return len(d)

def main():
    print(field(Box('str')))
    print(dict_size({'a': 1, 'b': 2}))

main()
""", "str\n2\n")

    # The `var` spelling of a class-body field. To Python this is the SAME
    # declaration as the bare `NAME = ...` above — `var` only suppresses a
    # type inference the class body never did — but only the bare spelling
    # reached the class-attribute registration and global-declaration
    # passes. A `var` field got a struct field with NO initializer anywhere,
    # so it stayed NULL and the first read was a live segfault; a scalar
    # `var` field was typed as a `struct <Cls> *` (the "unknown field"
    # fallback) and read back 0.
    test_gimple_stdout("gimple_struct_var_declared_class_field", """\
struct CentralDir:
    var FIELD_STRUCT = struct.Struct('<HH')

    fn read(self, data: bytes):
        var t = self.FIELD_STRUCT.unpack(data)
        print(t[0], t[1], self.FIELD_STRUCT.size)

class Config:
    var NAME = 'hello'
    var N = 5
    var ITEMS = []
    var TABLE = {}

    fn show(self):
        print(self.NAME, self.N, len(self.ITEMS), len(self.TABLE))

fn main():
    var c = CentralDir()
    c.read(b'\\x01\\x00\\x02\\x00')
    Config().show()
""", "1 2 4\nhello 5 0 0\n")

    # struct.pack with a trailing splat arg + the packed bytes fed into a
    # `+` concat whose other operand isn't statically MojoBytes* — the
    # exact shape of zipfile `_write_end_record`'s `struct.pack('<HH' +
    # 'Q'*len(extra), 1, 8*len(extra), *extra) + extra_data` (used to
    # ICE GCC's GIMPLE FE via an `int64 + pointer` POINTER_PLUS).
    test_gimple_stdout("gimple_struct_pack_splat_and_concat", """\
fn main():
    var extra = [10, 20]
    var packed = struct.pack('<HH' + 'Q' * len(extra), 1, 16, *extra)
    var tail = b'ZZ'
    var whole = packed + tail
    print(len(whole))
    var t = struct.unpack('<HHQQ', packed)
    print(t[0], t[1], t[2], t[3])
""", "22\n1 16 10 20\n")

    # Stage 3 — struct.pack_into into a bytearray.
    test_gimple_stdout("gimple_struct_pack_into", """\
fn main():
    var buf = bytearray(8)
    struct.pack_into('<HH', buf, 2, 5, 6)
    print(buf[0], buf[2], buf[4])
""", "0 5 6\n")

    # Generator expression bound to a local, then consumed exactly once by
    # a forward iteration. It is a REAL lazy generator now
    # (fire_compiler.desugar_genexps rewrites it into a call to a
    # synthesized module-level generator function), so this also pins the
    # value-typing of what flows through it.
    # bugs/COMPILE_FAIL_zipfile___init__.md blocker 3.
    test_gimple_stdout("gimple_genexp_local_sum_once", """\
fn main():
    g = (x * 2 for x in [1, 2, 3])
    print(sum(x for x in g))
""", "12\n")

    test_gimple_stdout("gimple_genexp_local_for_once", """\
fn main():
    g = (x + 1 for x in [10, 20, 30])
    for v in g:
        print(v)
""", "11\n21\n31\n")

    # The exact ZipFile._sanitize_windows_name shape: a genexp bound to a
    # PARAMETER (char*-typed slot), iterated by a second genexp, plus a
    # bare `if x` string-truthiness filter (empty string must be dropped).
    test_gimple_stdout("gimple_genexp_param_reassigned_sanitize_shape", """\
fn clean(arcname: String, pathsep: String) -> String:
    arcname = (x.rstrip(" .") for x in arcname.split(pathsep))
    arcname = pathsep.join(x for x in arcname if x)
    return arcname

fn main():
    print(clean("a. /b .// c", "/"))
""", "a/b/ c\n")

    # A genexp local consumed TWICE. It used to be an eagerly materialized
    # list, so the second read saw the same values again (and the consumer
    # paths destroyed the generator handle after the first pass — a
    # use-after-free once genexps became real lazy generators). Generator
    # expressions are now REAL generators (fire_compiler.desugar_genexps),
    # so this asserts CPython's actual semantics: the first pass drains it,
    # the second sees an exhausted generator and sums nothing.
    test_gimple_stdout("gimple_genexp_local_consumed_twice", """\
def main():
    g = (x * 2 for x in [1, 2, 3])
    print(sum(x for x in g))
    print(sum(x for x in g))
""", "12\n0\n")

    # os.path.splitdrive / splitroot — POSIX (see
    # bugs/COMPILE_FAIL_zipfile___init__.md). splitdrive is always
    # ('', p); splitroot follows posixpath (1/>=3 leading slashes -> '/',
    # exactly 2 -> '//').
    test_gimple_stdout("gimple_os_path_splitdrive_splitroot", """\
import os

fn main():
    print(os.path.splitdrive("/usr/bin")[0] + "|" + os.path.splitdrive("/usr/bin")[1])
    print(os.path.splitdrive("rel/x")[1])
    var r = os.path.splitroot("/a/b")
    print(r[0] + "|" + r[1] + "|" + r[2])
    var r2 = os.path.splitroot("//a/b")
    print(r2[1] + "|" + r2[2])
    var r3 = os.path.splitroot("///a/b")
    print(r3[1] + "|" + r3[2])
    var r4 = os.path.splitroot("rel/x")
    print(r4[0] + "|" + r4[1] + "|" + r4[2])
""", "|/usr/bin\nrel/x\n|/|a/b\n//|a/b\n/|//a/b\n||rel/x\n")

    # reversed() over a list / str, and the reversed(sorted(...)) chain
    # that was silently dropped in zipfile/__init__.py:1612.
    test_gimple_stdout("gimple_reversed_list_str_sorted", """\
fn main():
    var xs = [3, 1, 2, 5, 4]
    var acc: Int = 0
    for v in reversed(xs):
        acc = acc * 10 + v
    print(acc)
    var s2: Int = 0
    for v in reversed(sorted(xs)):
        s2 = s2 * 10 + v
    print(s2)
    var out: String = ""
    for c in reversed("hello"):
        out = out + c
    print(out)
""", "45213\n54321\nolleh\n")

    # bugs/PARTIAL_WORK_HANDOFF.md §4.1: a function returning a local it just
    # bound was typed int64_t regardless of the local's real value, so the
    # caller printed the pointer's decimal address instead of the string.
    test_gimple_stdout("gimple_return_local_bound_to_string_literal", """\
def f():
    s = 'abc'
    return s

print(f())
""", "abc\n")

    # §4.2a: print([True, False]) printed [1, None] -- the generic list repr
    # both formats a bool slot with %d instead of True/False AND treats a
    # False (0) slot as the None sentinel.
    test_gimple_stdout("gimple_print_bool_list", """\
print([True, False])
""", "[True, False]\n")

    # §4.2b: print({1, 2}) printed the set's own ADDRESS -- print had no
    # MojoSet * dispatch branch at all (len()/iteration on the same value
    # were already correct).
    test_gimple_stdout("gimple_print_set_literal", """\
print({1, 2})
""", "{1, 2}\n")

    # §4.3: a for-loop TARGET name reused across two loops over different
    # element domains is a REBIND, not a read -- `_declare_var`'s first-
    # decl-wins default silently kept the FIRST loop's int64_t declaration
    # for the second (string) loop, printing pointer decimals with exit 0.
    test_gimple_stdout("gimple_for_loop_target_rebind_int_then_str", """\
for x in [1, 2]:
    print(x)
for x in ['p', 'q']:
    print(x)
""", "1\n2\np\nq\n")

    # bugs/hard/CODEGEN_function_scoped_import_module_not_inlined.md: a
    # cross-module constructor call whose only field-type evidence is an
    # unannotated scalar/container LITERAL argument (`Parameter('v', 7)`,
    # `Parameter` defined in a SIBLING module) left the field `int64_t` in
    # the DEFINING module's own compiled struct -- neither the same-module
    # ctor-literal pass nor its one-hop `_ctxlit_*` companion ever sees a
    # DIFFERENT module's call site. A scalar mismatch is a hard
    # `gcc -fgimple` "non-trivial conversion" failure, so this failed to
    # even COMPILE before the fix (`_xmod_ctor_field_hints`, mirroring the
    # existing `_xmod_gen_param_hints` cross-module pattern).
    def _compile_two_files_do_imports_and_run(defn_filename, defn_src,
                                               use_filename, use_src, timeout=30):
        """Write two sibling .py files, compile the SECOND with
        do_imports=True (single-TU inline path), build with gcc -fgimple,
        run, and return captured stdout. Raises on any failure, with the
        stage that failed in the message (compile / gcc / run)."""
        with tempfile.TemporaryDirectory() as wd:
            open(os.path.join(wd, defn_filename), 'w').write(defn_src)
            entry = os.path.join(wd, use_filename)
            open(entry, 'w').write(use_src)
            from gimple_codegen import compile_to_gimple
            c_code = compile_to_gimple(use_src, do_imports=True, filename=entry)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
            f.write(c_code)
            c_file = f.name
        exe_file = c_file.replace('.c', '.exe')
        try:
            runtime_dir = os.path.join(HERE, 'runtime')
            result = subprocess.run(
                [find_gcc(), '-fgimple', f'-I{runtime_dir}', '-o', exe_file,
                 c_file, os.path.join(runtime_dir, 'fire_runtime.c')],
                capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                raise RuntimeError(f"gcc -fgimple failed: {result.stderr[:300]}")
            return run_executable_stdout(exe_file)
        finally:
            try:
                os.unlink(c_file)
            except Exception:
                pass
            if os.path.exists(exe_file):
                try:
                    os.unlink(exe_file)
                except Exception:
                    pass

    def test_cross_module_ctor_scalar_field_type():
        global _PASS, _FAIL, _TIMEOUT
        name = "cross_module_ctor_scalar_field_type"
        defn = ("class Parameter:\n"
                "    def __init__(self, name, kind=0):\n"
                "        self.name = name\n"
                "        self.kind = kind\n")
        use = ("from xmodctor_defn import Parameter\n"
               "\n"
               "def f():\n"
               "    p = Parameter('v', 7)\n"
               "    return p.name\n"
               "\n"
               "print(f())\n")
        try:
            out = _compile_two_files_do_imports_and_run(
                'xmodctor_defn.py', defn, 'xmodctor_use.py', use)
        except subprocess.TimeoutExpired as e:
            print(f"TIMEOUT {name}: {e}")
            _TIMEOUT += 1
            return
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        if out == "v\n":
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected 'v\\n', got {out!r}")
            _FAIL += 1

    test_cross_module_ctor_scalar_field_type()

    # bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md
    # §4 ("module.Class(...) construction is unresolved on every path"):
    # `mod_a.Dialog("a")` — a struct constructed through its OWNING MODULE
    # object rather than its bare name — lowered to a generic "method call"
    # whose receiver (the module marker) was echoed straight back as the
    # "result", so `x` bound to the module handle and `x.widgetName` raised
    # AttributeError at runtime.
    def test_qualified_module_struct_construction():
        global _PASS, _FAIL, _TIMEOUT
        name = "qualified_module_struct_construction"
        defn = ("class Dialog:\n"
                "    def __init__(self, widgetName):\n"
                "        self.widgetName = widgetName\n")
        use = ("import xmodctor2_defn\n"
               "\n"
               "def main():\n"
               "    x = xmodctor2_defn.Dialog(\"a\")\n"
               "    print(x.widgetName)\n"
               "\n"
               "main()\n")
        try:
            out = _compile_two_files_do_imports_and_run(
                'xmodctor2_defn.py', defn, 'xmodctor2_use.py', use)
        except subprocess.TimeoutExpired as e:
            print(f"TIMEOUT {name}: {e}")
            _TIMEOUT += 1
            return
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        if out == "a\n":
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected 'a\\n', got {out!r}")
            _FAIL += 1

    test_qualified_module_struct_construction()

    # bugs/CODEGEN_fstring_and_str_of_a_list_are_garbage.md: f"{container}"
    # and str(container) read the container's raw header bytes as a C
    # string (`_stringify_value` had no container branch at all, unlike
    # `print`'s dispatch, which was already correct for the same values).
    test_gimple_stdout("gimple_fstring_and_str_of_containers", """\
l = [1, 2, 3]
print(f"{l}")
print(str(l))
s = {1, 2}
print(f"{s}")
d = {'a': 1}
print(str(d))
""", "[1, 2, 3]\n[1, 2, 3]\n{1, 2}\n{'a': 1}\n")


def main():
    gcc = find_gcc()
    result = subprocess.run([gcc, '--version'], capture_output=True)
    if result.returncode != 0:
        print(f"ERROR: gcc not found: {gcc}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("GIMPLE EXECUTION TESTS")
    print("=" * 60)

    run_tests()

    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed"
          + (f", {_TIMEOUT} timed out" if _TIMEOUT else ""))
    sys.exit(0 if _FAIL == 0 else 1)


if __name__ == '__main__':
    main()
