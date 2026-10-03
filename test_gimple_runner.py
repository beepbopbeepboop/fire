"""Test runner that compiles and executes GIMPLE programs.

Uses gcc (gcc-15 if available, else fallback) with -fgimple to compile and execute
GIMPLE-annotated C code. This tests the GIMPLE backend which is used for the gimple codegen tests.
"""
import os
import sys
import platform
import subprocess
import tempfile
from io import StringIO
from build_config import find_gcc
import re

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


def test_gimple_stdout_repeated(name: str, mojo_src: str, expected_stdout: str,
                                runs: int = 8):
    """`test_gimple_stdout`, but runs the binary `runs` times and requires
    EVERY run to agree.

    For a bug whose symptom is reading uninitialised or freed memory, one run
    is a coin flip and the test is worth much less than it looks. The
    capture-by-pointer-of-a-pointer case
    (`gimple_lambda_capture_pointer_local_by_value`) was measured at 8/16
    correct, 4/16 wrong answer, 4/16 SIGSEGV — because the lambda read the
    first 8 bytes of the ADDRESS of a stack local, so what it got depended on
    what the stack happened to hold. A single-run assertion there passes half
    the time, which is the worst kind of regression test: green on the gate
    that introduced the bug.

    Reporting the distinct outcomes (not just the first mismatch) matters too,
    because "wrong value" and "crashed" are different bugs and only the first
    one is a silent-wrong-answer.
    """
    global _PASS, _FAIL, _TIMEOUT
    exe_path = None
    try:
        exe_path = compile_mojo_to_gimple_exe(mojo_src)
        seen = {}
        for _ in range(runs):
            try:
                r = subprocess.run([exe_path], capture_output=True, text=True,
                                   timeout=30)
                key = f"exit {r.returncode}: {r.stdout!r}"
            except subprocess.TimeoutExpired:
                key = "TIMEOUT"
                _TIMEOUT += 1
            seen[key] = seen.get(key, 0) + 1
        if len(seen) == 1 and next(iter(seen)) == f"exit 0: {expected_stdout!r}":
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected {expected_stdout!r} on all {runs} runs, "
                  f"got {sorted(seen.items(), key=lambda kv: -kv[1])}")
            _FAIL += 1
    except subprocess.TimeoutExpired as e:
        print(f"TIMEOUT {name}: {e}")
        _TIMEOUT += 1
    except Exception as e:
        print(f"FAIL  {name}: {e}")
        _FAIL += 1
    finally:
        if exe_path:
            for suffix in ('', '.c'):
                try:
                    os.unlink(exe_path + suffix)
                except OSError:
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


def test_gimple_matches_cpython(name: str, mojo_src: str):
    """Compile, run, and require the COMPILED program's stdout and exit code
    to be byte-identical to CPython's on the same source.

    Stronger than `test_gimple_stdout`, which pins an answer this file has to
    keep in sync by hand, and the right shape for the class of bug where the
    compiled path produces a PLAUSIBLE wrong value: a `lambda: False` called
    through a module global printed `0`, and no fixed expectation written
    after the bug would have said `0` was wrong — only CPython does. It also
    cannot rot: if the compiler starts diverging, this fails.

    CPython is run first and a non-zero exit or empty output from it is
    reported as the test program's own problem, not a compiler failure —
    otherwise a program that raises would 'pass' by matching an empty string
    on both sides.
    """
    global _PASS, _FAIL, _TIMEOUT
    exe_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py',
                                         delete=False) as f:
            f.write(mojo_src)
            entry = f.name
        try:
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                timeout=30)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr.decode('utf-8', 'replace')[:300]}) — the "
                      f"test program itself is wrong, not the compiler")
                _FAIL += 1
                return
            want_out = py.stdout
            want_rc = py.returncode
        finally:
            os.unlink(entry)
        exe_path = compile_mojo_to_gimple_exe(mojo_src)
        got = subprocess.run([exe_path], capture_output=True, timeout=30,
                             env=_SCRIBBLE_ENV)
        if got.stdout == want_out and got.returncode == want_rc:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: CPython {want_out!r} exit {want_rc}, "
                  f"compiled {got.stdout!r} exit {got.returncode}")
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
            except OSError:
                pass


def test_gimple_diagnostic(name: str, mojo_src: str, expected_stderr: str,
                           expected_stdout: str = None, expected_return: int = 0):
    """Assert the compiled program prints `expected_stderr` on stderr and,
    optionally, exactly `expected_stdout` with exit `expected_return`.

    The shape of a LOUD-BUT-CONTINUING refusal — the compiled path's
    established alternative to a signal or to a silent wrong value, the same
    one `mojo_unsupported_iter` and the `_unsupported_generator_names` weak
    stubs use (see those comments for why abort() is worse: no Mojo-level
    try/except can catch SIGABRT, so it takes down the whole process). It
    needs its own helper because `test_gimple_runtime_error` asserts a
    NON-ZERO exit, which is the opposite convention: there the program fails
    as CPython would, here it says what it cannot do and carries on with the
    behaviour the gap already produced. Asserting only the stderr substring
    would be weak, so the stdout and exit code are pinned too where the test
    has an opinion."""
    global _PASS, _FAIL, _TIMEOUT
    exe_path = None
    try:
        exe_path = compile_mojo_to_gimple_exe(mojo_src)
        result = subprocess.run([exe_path], capture_output=True, timeout=10)
        err = result.stderr.decode('utf-8', errors='replace')
        out = result.stdout.decode('utf-8', errors='replace')
        if (expected_stderr in err and result.returncode == expected_return
                and (expected_stdout is None or out == expected_stdout)):
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected {expected_stderr!r} on stderr with "
                  f"exit {expected_return}"
                  + (f' and stdout {expected_stdout!r}' if expected_stdout is not None else '')
                  + f', got exit {result.returncode} err={err[-300:]!r} out={out[-200:]!r}')
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

    # A CALLABLE-VALUED PARAMETER, keyword-only and positional-with-default
    # alike. Both used to be padded with `calls_shared._default_expr_to_pair`'s
    # `('int', '0')` fallback -- i.e. a NULL function pointer -- because that
    # helper had no case for a default that IS a function, so the body called
    # address 0 and the process died with SIGSEGV (exit 139, nothing on
    # stdout). The generator instance of the same shape is
    # `Tools/c-analyzer/c_common/fsutil.py`'s `walk_tree(root, *,
    # walk=_walk_tree)`, tracked in
    # bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md; this is the
    # ordinary-path twin, which that doc did not mention. Expected text is
    # CPython's for the same source.
    test_gimple_stdout("gimple_callable_valued_parameter_default", """\
def twice(x):
    return x + x

def kw_only(x, *, f=twice):
    return f(x)

def positional(x, f=twice):
    return f(x)

def main():
    print(kw_only(3))
    print(kw_only(4, f=twice))
    print(positional(5))
    print(positional(6, twice))

main()
""", "6\n8\n10\n12\n")

    # The same value read out of a parameter and handed on, which is the
    # other half of the fix (`_lower_IdentExpr`'s function-value arm): a
    # function passed as an ARGUMENT must arrive as its real address, not
    # as the `(int64_t)0` placeholder the unknown-identifier fallback
    # emitted.
    test_gimple_stdout("gimple_function_passed_as_argument", """\
def twice(x):
    return x + x

def via_param(x, f):
    return f(x)

def main():
    print(via_param(7, twice))

main()
""", "14\n")

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

    # `print(<unannotated param>)` typed the parameter `char *` (the
    # BUILTIN_PARAM_TYPES entry for `print`, since `print` accepts a value of
    # ANY type in Python and so says nothing about its argument's type), and
    # the call site then passed the integer as a pointer:
    #
    #   void g (char * x) { mojo_print (x); ... }
    #   _t1 = (void *)1; g ((char *)_t1);
    #
    # so `g(1)` strlen'd address 1 and died with SIGSEGV, and `g(1.5)` did
    # not even compile. Every OTHER use of the same parameter was already
    # right (`print("v=", x)`, `print(str(x))`, `print(x + 1)`,
    # `return x`), which is why the trigger is so narrow. The sibling
    # `gimple_untyped_param_string_passthrough` above is the case that must
    # keep working, and the string call site is the third: all three in one
    # test so removing the inference cannot quietly trade a crash for a wrong
    # string.
    test_gimple_stdout("gimple_print_of_untyped_param_is_not_a_pointer", """\
def gi(x):
    print(x)

def gs(x):
    print(x)

def gf(x):
    print(x)
gi(1)
gf(1.5)
gs("s")
""", "1\n1.5\ns\n")

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

    # `l.sort()` — the METHOD — used to be a no-op stub in the runtime
    # (`void mojo_list_sort(MojoList *l) { (void)l; }`), so it returned the
    # list in its original order with exit 0 and said nothing: the worst
    # shape, because `sorted(l)` was right and `l.sort(); x = l` was silently
    # wrong, so the two spellings of one operation disagreed.
    # A lambda inside a nested `def` was lifted and its address taken but
    # never DEFINED, because `_lower_LambdaExpr` puts the body in the
    # `gen._lambda_parts` side table and the nested-closure emission path
    # flushed nothing — so this was a hard `Undefined symbols
    # ...: "__make_make_lambda_1"` LINK failure. A lambda at the same
    # nesting depth in a TOP-LEVEL function does get its definition, which is
    # what made the shape look supported. The shape-independent guard (every
    # `_funcptr_X` initializer has a matching definition) is
    # `every_funcptr_initializer_has_a_definition` in test_gimple.py; this
    # is the end-to-end run beside CPython.
    test_gimple_stdout("gimple_lambda_in_nested_def_is_emitted", """\
def _make():
    def make():
        return lambda x: x + 1
    return make

def main():
    f = _make()()
    print(f(1))
main()
""", "2\n")

    # The two-deep nest is a separate path — a second `gen._gen_lifted_closure`
    # level, so its `_lambda_parts` flush has to happen at each one — and is
    # here rather than assumed to follow from the single-level case.
    # (`*args` is deliberately NOT here: a variadic lambda segfaults on this
    # tree at every nesting depth including top level, which is
    # bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md's already-fixed
    # variadic work sitting in an unlanded branch, not this path.)
    test_gimple_stdout("gimple_lambda_two_deep_nested_def", """\
def a():
    def b():
        def c():
            return lambda: 5
        return c
    return b

def main():
    print(a()()()())
main()
""", "5\n")

    # A callable VALUE's real return type used to be lost at the call,
    # because `mojo_fnptr_call_N` is the homogenized `int64_t` convention —
    # the RIGHT thing for the box it hands back, but the CALLEE is the one
    # that knows the type. So `lambda: False` printed `0` (the bug doc's
    # symptom), `lambda: "hi"` printed its own pointer decimal, and
    # `lambda: 1.5` printed `2.1393696074e-314`: a `double` cannot even ride
    # the `int64_t` return, which reads a general-purpose register the value
    # is not in, so the fix for THAT one is a `double`-returning twin of the
    # helper family rather than a reinterpretation.
    #
    # An ordinary `def` returning the same value is in the same test because
    # it was already right — it is what proves the loss is in the callable
    # VALUE path and not in the return-type inference.
    # `d['k'](2, 3)` — a callable value held in a dict subscript, a
    # name-keyed dispatch table — was stubbed to 0, exit 0, silently wrong.
    # It was lumped in with the ONE other SubscriptExpr callee that is not a
    # runtime value read (`Scalar[x.dtype](...)`, a comptime bracket
    # argument), which `_static_generic_return_ctype` tells apart and which
    # still keeps the stub.
    #
    # The `f = d['k']` line is in the same test because the doc records it as
    # ALREADY working (`print(f(2, 3))` printed 5) — so it is the control
    # that proves the loss is in the subscript-callee dispatch and not in the
    # value representation.
    test_gimple_stdout("gimple_call_through_subscript_callee", """\
def main():
    d = {}
    d['k'] = lambda a, b: a + b
    print(d['k'](2, 3))
    f = d['k']
    print(f(4, 5))
    e = {"j": lambda: "hi"}
    print(e["j"]())
main()
""", "5\n9\nhi\n")

    # The SAME subscript callee, reached with a `MojoBoundMethod *` in the
    # dict instead of a bare function pointer. `note_dict_callable_ret`
    # consulted only `_callable_ret_types`, which is where a non-capturing
    # closure and a lifted free function land; a struct method bound as a
    # value (`C().m`) lands in `_bound_method_ret_types` instead. With no
    # entry for the container, `dd['m'](4)` took the indirect-call stub and
    # printed 0 at exit 0 — while `f = dd['m']; f(4)` in the same program
    # printed CPython's 8, because the value in the dict was a perfectly
    # good bound method all along and `mojo_fnptr_call_1` dispatches it. So
    # this is a missing ENTRY, not a missing mechanism, and the named-local
    # line is in the test as the control that says so.
    #
    # It reproduces only when the bound method is the dict's FIRST callable
    # store: one lambda stored first puts the container in the table and the
    # bound method then rides in on that entry, which is how the original
    # bug report's `d['k'] = lambda a, b: a + b` repro looked already-fixed
    # while this shape stayed broken. `g` is the control for THAT ordering
    # dependence and `e` is the fixed shape: the two dicts differ only in
    # what is stored first.
    test_gimple_stdout("gimple_dict_held_bound_method_through_subscript", """\
class C:
    def m(self, x):
        return x * 2

def main():
    dd = {}
    dd['m'] = C().m
    print(dd['m'](4))
    f = dd['m']
    print(f(5))
    g = {}
    g['cap'] = lambda x: x + 1
    g['m'] = C().m
    print(g['m'](4))
main()
""", "8\n10\n8\n")


    test_gimple_stdout("gimple_callable_value_keeps_its_return_type", """\
def plain():
    return False

def main():
    a = lambda: True
    print(a())
    b = lambda: False
    print(b())
    c = lambda x: x > 1
    print(c(5))
    print(c(0))
    d = lambda: 1.5
    print(d())
    e = lambda: "hi"
    print(e())
    print(plain())
main()
""", "True\nFalse\nTrue\nFalse\n1.5\nhi\nFalse\n")

    # The MODULE-LEVEL spelling of the test above, and the one that was broken.
    # `gimple_callable_value_keeps_its_return_type` puts its lambdas inside
    # `main()`, where a read of the local returns the variable's own C name and
    # the callable's return type survives to the call site. At module scope the
    # target is a field of this module's globals struct, so the store takes a
    # different path from a local assignment AND every read mints a fresh temp
    # — and all three of the "what does this callable really return" tables
    # (`_callable_ret_types`, `_dict_callable_ret`, `_bound_method_ret_types`)
    # were dropped at BOTH of those hops, silently. `mojo_fnptr_call_N` is the
    # homogenized `int64_t` convention (right for the box it hands back, wrong
    # for the value inside), so with the type missing every module-level
    # callable printed the box:
    #
    #     e = lambda: False; print(e())          -> 0            (False)
    #     e = lambda: "hi";  print(e())          -> 4330320072   (its own pointer)
    #     d = {"k": lambda: True}; print(d["k"]()) -> 0           (True)
    #     f = m.truthy;      print(f())          -> 1            (True)
    #
    # CPython-compared rather than pinned, because every answer here is the one
    # a reader would otherwise have to take on trust: `0` looks like a
    # plausible printing of a boolean until you see CPython print `False`.
    test_gimple_matches_cpython("gimple_module_level_callable_keeps_its_return_type", """\
e = lambda: False
print(e())
e2 = lambda x: x > 1
print(e2(5))
print(e2(0))
e3 = lambda: "hi"
print(e3())
e4 = lambda: 1.5
print(e4())
e5 = lambda: 42
print(e5())
e6 = lambda: not False
print(e6())
d = {"k": lambda: True}
print(d["k"]())
""")

    # A second hop through the same tables — a module global that holds
    # another global's callable (`alias = e`), and a dict of callables
    # aliased the same way. Each hop re-keys the tables on a new name, so a
    # carry that only handled the first would still print `0` here, and a
    # dict-of-lambdas alias additionally goes through the separate
    # `_dict_callable_ret` table.
    test_gimple_matches_cpython("gimple_module_level_callable_alias_keeps_its_return_type", """\
e = lambda: False
alias = e
print(alias())
d = {"k": lambda: True}
d2 = d
print(d2["k"]())
""")

    # ── `with` teardown: the `as` target is optional, and so is running
    # ── __exit__ at all. Fixed, and the doc
    # ── (`CODEGEN_with_no_as_target_drops_exit`) is deleted, so this comment
    # ── is the record.

    # `with C():` with NO `as` target used to drop the teardown entirely. The
    # five index-parallel per-item lists `_gen_stmt_WithStmt` feeds
    # `_with_emit_exits` from were appended INSIDE
    # `if item.alias is not None:`, so a no-`as` item appended nothing:
    # `has_exit` stayed False, no `setjmp`-protected region was emitted, and
    # the exit walk iterated an empty list. `__enter__` ran, the body ran, and
    # `__exit__` never did — with exit 0, on every `with` over a class that has
    # one.
    #
    # The interpreter is the reference and gets this right, and
    # `test_runtime_diff.py`'s A/B engine comparison CANNOT see it even in
    # principle: the two engines differ on the OUTPUT, and here the output can
    # be byte-identical (the body worked) while the teardown never ran. So the
    # only shape that catches it is one where `__exit__` PRINTS — which is what
    # both spellings below do, each on the same class so the only difference
    # between the two halves is the `as`.
    #
    # Found on a lock (`build_stdlib_dylib`'s publish lock, commit ccd83a2b):
    # a `with` on a cross-process lock object that never releases it wedges
    # every other process wanting the same lock for the life of the tree, so
    # this is not only a per-iteration leak.
    test_gimple_matches_cpython("gimple_with_no_as_target_still_calls_exit", """\
class Ctx:
    def __init__(self, n):
        self.n = n
    def __enter__(self):
        print("enter", self.n)
        return self.n * 10
    def __exit__(self, a, b, c):
        print("exit", self.n)

def with_alias():
    with Ctx(1) as v:
        print("as", v)

def without_alias():
    with Ctx(2):
        print("noas")

with_alias()
without_alias()
""")

    # The exceptional and early-exit paths, which are separate emission sites
    # and separate bugs — all silent, all with exit 0:
    #   * a `raise` in the body has to unwind through the bb_exc arm, which
    #     emits the exit again, so `__exit__` must appear exactly ONCE (twice
    #     would be a different wrong answer, and a visible one);
    #   * a `return` out of the body used to emit the teardown AFTER the
    #     `return`, i.e. the cleanup was itself unreachable — same for the
    #     `continue`/`break` arm, which popped the exception stack and emitted
    #     nothing else.
    # Those two leaked on the `as` spelling too, so they are pre-existing and
    # independent of the no-`as` fix; they are here because a no-`as` `with`
    # only reaches the setjmp region at all now that it registers.
    test_gimple_matches_cpython("gimple_with_teardown_on_raise_return_and_loop_exit", """\
class Ctx:
    def __init__(self, n):
        self.n = n
    def __enter__(self):
        print("enter", self.n)
        return self.n
    def __exit__(self, a, b, c):
        print("exit", self.n)

def raising():
    try:
        with Ctx(1):
            print("raising")
            raise ValueError("boom")
    except ValueError:
        print("caught")

def returning():
    with Ctx(2):
        print("returning")
        return 7

def looping():
    for i in range(3):
        with Ctx(3 + i):
            print("loop", i)
            if i == 1:
                continue
            if i == 2:
                break

raising()
print("ret", returning())
looping()
""")

    # A MULTI-ITEM `with` has to unwind in REVERSE acquisition order —
    # `exit 7` before `exit 6` — which is the entire point of nesting: an
    # inner context manager's teardown may depend on the outer one's state
    # still being live. `_with_emit_exits` walked its index-parallel item
    # lists FORWARD, so every multi-item `with` released the outer manager
    # first (a multi-item `with` unwound forward, so the outer one was released first),
    # silently, exit 0.
    #
    # Every exit route is in the one program because there are five emission
    # sites for the same walk (normal tail, the `return` interceptor, the
    # loop `continue`/`break` arm, the setjmp exception arm, and the no-`__exit__`
    # fallback) and each is a separate place to get the order wrong. `as` on
    # the first item only, because the teardown order is independent of it
    # and CPython has to agree about the alias too.
    test_gimple_matches_cpython("gimple_multi_item_with_unwinds_in_reverse", """\
class Ctx:
    def __init__(self, n):
        self.n = n
    def __enter__(self):
        print("enter", self.n)
        return self.n
    def __exit__(self, a, b, c):
        print("exit", self.n)

def three():
    with Ctx(1), Ctx(2), Ctx(3):
        print("body")

def raiser():
    with Ctx(4) as a, Ctx(5):
        print("before", a)
        raise ValueError("boom")

def early():
    with Ctx(6), Ctx(7):
        return 99

def nested():
    with Ctx(8):
        with Ctx(9):
            print("inner")

three()
try:
    raiser()
except ValueError as e:
    print("caught", e)
print("early", early())
nested()
""")

    # Iterating a value that is not a container RAISES, for every consumer of
    # the shared chokepoint — and a string, which IS iterable, is answered
    # rather than refused.
    #
    # The chokepoint (`_materialize_as_list`'s ambiguous arm) had two wrong
    # answers for one decision. It used to WALK whatever it was handed, so
    # `list(12345678)` died with SIGSEGV; the fail-closed arm that fixed the
    # crash answered an EMPTY list instead, which is a silent wrong answer —
    # a program's loop body never runs and nothing says so, exit 0
    # (the shared materialize-as-list chokepoint's not-a-container arm). CPython
    # raises TypeError, so that is what this asserts, one row per consumer
    # because each is a separate emission site over one chokepoint:
    # list/all/any/enumerate/str.join/bytes.join.
    #
    # A `char *` was excluded from `all`/`any`'s materialization arm only
    # because the arm could not answer it, and what it used instead was a stub
    # that never looks at the value: `any("ab")` printed False where CPython
    # prints True. The string rows below are that fix, on both spellings — a
    # statically-typed literal and a value boxed through a parameter.
    # An inlined lambda's value keeps its type across the enclosing
    # function's RETURN boundary, for the kinds the return-type inference can
    # see. The lambda is never materialized here — `_lower_LambdaExpr` records
    # it and `_lower_inlined_lambda_call` emits its body straight into `o2` —
    # so the inlined value is a real `char *` and the only thing that could
    # lose it is `o2`'s own inferred signature, which saw `return fn()` as a
    # call to an unknown callee and inferred `int64_t`. Both functions
    # printed their string's own address.
    #
    # The int row is the control: `int64_t` is already the answer for an int,
    # so it must be unchanged by the fix that teaches the estimator to look
    # through a lambda-bound local. The `double` flavour of the same defect is
    # still open and is recorded with its cause in
    # bugs/CODEGEN_lambda_call_boundary_loses_the_return_type.md.
    test_gimple_matches_cpython("gimple_inlined_lambda_string_return_keeps_its_type", """\
def o2():
    s = 'ab'
    fn = lambda: s
    return fn()

def o3():
    s = 'ab'
    fn = lambda: s + '!'
    return fn()

def i1():
    n = 7
    fn = lambda: n + 1
    return fn()

print(o2())
print(o3())
print(i1())
""")

    test_gimple_runtime_error("gimple_iterating_a_non_container_raises", """\
def ident(x):
    return x

print(list(5))
""", "TypeError")

    test_gimple_runtime_error("gimple_all_of_a_non_container_raises", """\
print(all(5))
""", "TypeError")

    test_gimple_runtime_error("gimple_any_of_a_non_container_raises", """\
print(any(12345678))
""", "TypeError")

    test_gimple_runtime_error("gimple_enumerate_of_a_non_container_raises", """\
print(list(enumerate(7)))
""", "TypeError")

    test_gimple_runtime_error("gimple_str_join_of_a_non_container_raises", """\
print(",".join(3))
""", "TypeError")

    test_gimple_runtime_error("gimple_bytes_join_of_a_non_container_raises", """\
print(b"".join(9))
""", "TypeError")

    # A boxed handle that IS a container: `all`/`any` used to answer from a
    # stub that never looked at the value, so this was True whatever `x` was.
    test_gimple_stdout("gimple_all_any_of_a_boxed_container_reads_it", """\
def ident(x):
    return x

print(all(ident([1, 2])))
print(any(ident([0, 0])))
print(all(ident([])))
""", "True\nFalse\nTrue\n")

    test_gimple_matches_cpython("gimple_a_string_is_iterable_through_the_same_chokepoint", """\
def ident(x):
    return x

print(",".join(ident("a,b")))
print(list(ident("abc")))
print(any(ident("ab")))
print(all(ident("")))
""")

    test_gimple_stdout("gimple_list_sort_method_in_place", """\
def main():
    l = [3, 1, 2]
    l.sort()
    print(l)
    m = ['c', 'a', 'b']
    m.sort()
    print(m)
    n = [3, 1, 2]
    print(sorted(n))
main()
""", "[1, 2, 3]\n['a', 'b', 'c']\n[1, 2, 3]\n")

    # Every element kind the sort has to tell apart. A MojoList slot is a raw
    # int64_t, so a double is its IEEE bits and a str is a pointer: ordering
    # the slots as integers sorts floats by SIGN and strings by ADDRESS. The
    # kind byte the call site passes (gen._elem_of -> TypeLattice.slot_kind_byte)
    # is what makes each of these right. `bool` is an int subclass in Python,
    # so False sorts before True.
    test_gimple_stdout("gimple_list_sort_every_element_kind", """\
def main():
    f = [3.5, -1.25, 2.0]
    f.sort()
    print(f)
    b = [True, False, True]
    b.sort()
    print(b)
    d = ['b', 'a', 'c']
    d.sort()
    print(d)
    n = [[2], [1]]
    n.sort()
    print(n)
main()
""", "[-1.25, 2.0, 3.5]\n[False, True, True]\n['a', 'b', 'c']\n[[1], [2]]\n")

    # `key=` and `reverse=` on the METHOD, which used to be dropped on the
    # floor exactly as they were on `sorted()` before its own fix.
    test_gimple_stdout("gimple_list_sort_key_and_reverse", """\
def main():
    l = [1, 3, 2]
    l.sort(key=lambda v: -v)
    print(l)
    m = [1, 3, 2]
    m.sort(reverse=True)
    print(m)
    w = ['ccc', 'a', 'bb']
    w.sort(key=len)
    print(w)
main()
""", "[3, 2, 1]\n[3, 2, 1]\n['a', 'bb', 'ccc']\n")

    # A list of lists sorts ELEMENTWISE (Python's ordering, shorter first) —
    # the one total order a MojoList-of-MojoList has. Past
    # MOJO_SORT_MAX_DEPTH nesting the two compare equal rather than risking
    # unbounded recursion on a self-referential list.
    test_gimple_stdout("gimple_list_sort_nested_shorter_first", """\
def main():
    l = [[1, 2], [1], [1, 2, 3], []]
    l.sort()
    print(l)
main()
""", "[[], [1], [1, 2], [1, 2, 3]]\n")

    # What Python REFUSES to sort must be refused here too, and loudly. The
    # silent no-op this replaced was indistinguishable from a sort that
    # happened to leave the list alone; a heterogeneous list's only correct
    # answer is the TypeError, so that is what this must be — verified by
    # stderr text because the compiled binary's exit code alone cannot tell a
    # TypeError from an unrelated failure (and the signal it replaced was
    # exit 0 with a wrong list).
    # A callable-valued parameter default naming an IMPORTED module's function
    # (`def probe(x, *, g=os.walk)`) was padded with 0, so `g` arrived as
    # address 0 and the callee called through a null pointer: SIGSEGV, exit
    # 139, no output. Whether `os.walk` was compiled into this translation
    # unit at all is a property of the whole import closure, not of the
    # expression, so "0" is the one answer that is always available and
    # always wrong.
    #
    # The honest answer follows `mojo_unsupported_iter`: say so, loudly, and
    # carry on. `n > 0` printing False is what the null pointer WOULD have
    # printed had it survived — the loop's own "unsupported iterable"
    # diagnostic says the body runs zero times, which is pre-existing
    # behaviour, not something this change introduced.
    test_gimple_diagnostic("gimple_imported_callable_default_is_diagnosed", """\
def probe(x, *, g=os.walk):
    return g(x)

def main():
    r = probe(".")
    n = 0
    for a, b, c in r:
        n = n + 1
    print(n > 0)
main()
""", "mojo_unavailable_callable: 'os.walk'", "False\n")

    # The same default in a callee that NEVER CALLS the parameter must be
    # completely unaffected: the diagnostic lives inside the stub, so it fires
    # on a call, not on a padding. Without this the fix would trade a crash
    # for a spurious message in every program that merely mentions a callable
    # default.
    test_gimple_stdout("gimple_uncalled_imported_callable_default_is_silent", """\
def probe(x, *, g=os.walk):
    return x

def main():
    print(probe("hello"))
main()
""", "hello\n")

    test_gimple_runtime_error("gimple_list_sort_mixed_types_is_a_typeerror", """\
def main():
    l = [1, 'a', 2.5]
    l.sort()
    print(l)
main()
""", "TypeError: list.sort()")

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

    # A subclass that OVERRIDES a class-level constant read the BASE's value,
    # silently, at exit 0 — and so did every method of its own, because a
    # lifted `Child_who` reads `_classattr_Child__tag`, which
    # `_mojo_classattr_init` had initialised from `Base`'s declaration:
    #
    #     _classattr_Base__tag  = 7;
    #     _classattr_Child__tag = 7;      <- Child says 9
    #     _classattr_Grand__tag = 7;      <- Grand says 11
    #
    # `_merge_struct_inheritance` builds a subclass's `.fields` as BASE
    # declarations FIRST and the class's OWN last (its own docstring: "own
    # members override every base"), and the class-attribute emitter broke on
    # the FIRST match — so it took the base's. The whole chain read the root's
    # value. `other`, which NO subclass overrides, is the control that the
    # inherited declaration is still found when there is no own one.
    test_gimple_stdout("gimple_subclass_overrides_a_class_constant", """\
class Base:
    tag = 7
    other = 1

class Child(Base):
    tag = 9

class Grand(Child):
    tag = 11

def main():
    print(Base.tag, Child.tag, Grand.tag)
    print(Base.other, Child.other, Grand.other)
    b = Base()
    c = Child()
    print(b.tag, c.tag)
main()
""", "7 9 11\n1 1 1\n7 9\n")

    # The `cls`-half of the same inheritance story, on the shape most real
    # code uses: a `@classmethod` accessor reading `cls.<attr>`. The doc
    # recorded this as needing a runtime class OBJECT ("feature-sized"), and
    # it does not: the lifted method is emitted PER SUBCLASS and the fix above
    # gives each one its own `_classattr_<Cls>__<attr>` initialiser, so the
    # name-resolved `cls.tag` reads the right one for free. `Base.who()` is in
    # the same test because a fix that made the subclass read its own value by
    # also making the base read the subclass's would pass the first line.
    test_gimple_stdout("gimple_inherited_classmethod_reads_its_own_cls", """\
class Base:
    tag = 7
    @classmethod
    def who(cls):
        return cls.tag

class Child(Base):
    tag = 9

def main():
    print(Child.who())
    print(Base.who())
main()
""", "9\n7\n")

    # A capture DISCOVERY gap, not a truthiness gap, which is what
    # bugs/CODEGEN_captured_string_local_reads_falsey.md reported it as. The
    # lambda-capture scan walked a hand-grown list of AST child fields, and a
    # field that was not on it was an UNDER-approximation of what the body
    # reads: the name never reached the env struct, and the body read a hard
    # `(int64_t)0; /* ct param or undeclared: p */` for it. `p` read as 0, so
    # `p` was falsey, so `sorted` saw all-equal keys and preserved insertion
    # order — which is why the symptom read as "sorted() didn't sort".
    #
    # The field list is now every child-node field on the parser's AST
    # dataclasses, as one table. Each line below is a field that was missing,
    # and each is a name the body really does read:
    #   condition  — `d[k] if s else 0`, the doc's own shape
    #   index      — `d[p]`, a captured name as a subscript key
    #   pairs      — `{'k': s}`, a captured name as a dict value (the list
    #                said `key`/`val`, which no AST node has had for a while)
    #   start/stop — `s[1:]`
    #   operands   — `0 < n < 3`, a comparison chain
    #   kwargs     — `two(a=1, b=n)`
    # Every spelling prints CPython's answer, and each one printed a
    # plausible number or string before, at exit 0.
    test_gimple_stdout("gimple_lambda_capture_of_every_ast_child_field", """\
def two(a, b):
    return a - b

def main():
    d = {'b': 2, 'a': 1}
    p = 'b'
    s = 'abc'
    n = 1
    print(sorted(d, key=lambda k: d[k] if s else 0))
    print((lambda: d[p])())
    print((lambda: {'k': s})())
    print((lambda: s[1:])())
    print((lambda: 0 < n < 3)())
    print((lambda: two(a=1, b=n))())
    print(sorted(d, key=lambda k: d[k] if n else 0))
main()
""", "['a', 'b']\n2\n{'k': 'abc'}\nbc\nTrue\n0\n['a', 'b']\n")

    # …as a sorted() key, the shape that also required the forward
    # declaration to mirror the definition's own parameter resolution (the
    # call site binds the dict's `char *` key element to the lambda's
    # parameter, so an independently computed declaration said `char *` where
    # the definition inferred `int64_t`).
    #
    # Repeated, because this is the case that caught the capture-by-pointer
    # regression below and it is NONDETERMINISTIC: the broken build read
    # `_env->d` as the first 8 bytes of `&d`, so the answer depended on the
    # stack. Measured 8/16 correct, 4/16 wrong, 4/16 SIGSEGV. See
    # test_gimple_stdout_repeated.
    test_gimple_stdout_repeated("gimple_lambda_capture_as_sorted_key", """\
def main():
    d = {"b": 2, "a": 1}
    print(sorted(d, key=lambda k: d[k]))

main()
""", "['a', 'b']\n")

    # The regression itself, stated as its own case, in a shape that reaches the
    # LIFTED path (the lambda has to have an env materialized at the reference
    # site) rather than the beta-reduced/inlined one. That distinction is the
    # whole test: with the bug, the four shapes below all fail, and a lambda
    # that gets inlined never notices. Capturing a local that is ITSELF a
    # pointer puts a `MojoDict **` into a `MojoDict *` env field when the
    # address is taken instead of the value, and the body then reads the first
    # 8 bytes of the address of a stack local.
    #
    # via map(), where the wrong value is unmissable (garbage ~4.3e9 rather
    # than a plausible-but-wrong small int).
    test_gimple_stdout_repeated("gimple_lambda_capture_pointer_local_via_map", """\
def main():
    n = [10]
    print(list(map(lambda v: v + n[0], [1, 2])))

main()
""", "[11, 12]\n")

    # …and two pointer locals at once, so a fix that only handles the
    # single-capture case cannot pass.
    test_gimple_stdout_repeated("gimple_lambda_captures_two_pointer_locals", """\
def main():
    d = {"b": 2, "a": 1}
    off = [0]
    print(sorted(d, key=lambda k: d[k] + off[0]))

main()
""", "['a', 'b']\n")

    # A scalar local captured BY VALUE alongside the pointer one, so the rule
    # has to choose per-capture rather than once per closure.
    test_gimple_stdout_repeated("gimple_lambda_captures_pointer_and_scalar_locals", """\
def main():
    d = {"b": 2, "a": 1}
    z = 0
    print(sorted(d, key=lambda k: d[k] + z))

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

    # A captured local that the lambda body only mentions inside an AST FIELD
    # the capture walk did not visit. `_ast_walk` (emit_calls.py — the walk
    # `_lower_LambdaExpr` derives the capture list from) named 16 child
    # attributes and missed 17 of the 53 AST dataclasses' child-bearing ones,
    # `TernaryExpr.condition` among them. A name reachable ONLY through a
    # missed field is not put in the closure env at all, and the body then
    # reads it through the `ct param or undeclared` fallback, which is a hard
    # 0 — so the value silently became falsey and every truthiness test on it
    # took the wrong branch. `sorted`'s all-equal-keys stable order is what
    # made the symptom read as "sorted() didn't sort".
    #
    # Repeated, and the dict is a MODULE GLOBAL rather than a local on
    # purpose: a dict passed as an unannotated parameter is typed `MojoList *`
    # and `sorted()` then mis-dispatches, which is a different bug with its
    # own doc (CODEGEN_polymorphic_unannotated_param_vacuous_unanimity.md) and
    # would mask this one. Every line below is a DIFFERENT missed field, so a
    # fix that patches only `condition` cannot pass.
    test_gimple_stdout_repeated("gimple_lambda_capture_through_unwalked_fields", """\
D = {"b": 2, "a": 1}


def t_ternary(p):
    return sorted(D, key=lambda k: D[k] if p else 0)


def t_subscript_index(p, k):
    return sorted(D, key=lambda kk: D[kk] + (0 if p[k] else 0))


def t_compare(p, q):
    return sorted(D, key=lambda kk: D[kk] if p < q else 0)


def t_kwargs(p):
    return sorted(D, key=lambda kk: len(p) if p.strip() else 0)


def t_comprehension(p):
    return sorted(D, key=lambda kk: D[kk] + len([c for c in p]))


def t_slice(p):
    return sorted(D, key=lambda kk: D[kk] + len(p[1:2]))


def t_dict_pairs(p):
    return sorted(D, key=lambda kk: D[kk] + len({"z": p}))


print(t_ternary("x"))
print(t_ternary(""))
print(t_subscript_index({"a": 1}, "a"))
print(t_compare("a", "b"))
print(t_kwargs("  "))
print(t_comprehension("ab"))
print(t_slice("abcd"))
print(t_dict_pairs("q"))
""", "['a', 'b']\n['b', 'a']\n['a', 'b']\n['a', 'b']\n['b', 'a']\n"
       "['a', 'b']\n['a', 'b']\n['a', 'b']\n")

    # The reported shape itself, as its own case: `sorted` over a dict whose
    # ordering depends on a captured string. Both the truthy and the falsey
    # value are in it, because the falsey one is the only answer a broken
    # capture can produce and it is ALSO the correct answer for an empty
    # string — so a test with only the empty string would pass either way.
    test_gimple_stdout("gimple_lambda_captured_string_truthiness", """\
def f():
    p = "x"
    d = {"b": 2, "a": 1}
    return sorted(d, key=lambda k: d[k] if p else 0)


def g():
    p = ""
    d = {"b": 2, "a": 1}
    return sorted(d, key=lambda k: d[k] if p else 0)


print(f())
print(g())
""", "['a', 'b']\n['b', 'a']\n")

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

    # ── A capturing lambda's value, and the environment it captured, are ONE
    # allocation unit (doc/MEMORY.html §3.B): a `malloc(sizeof env)` plus a
    # `malloc(sizeof MojoBoundMethod)` plus a `_reg_bound_method` entry per
    # creation, ~74 B/iteration, now flat at 100k and 400k. Four consumers of
    # that ownership are in one program: a lambda in a LOOP BODY (freed at the
    # end of the body and on every `break`/`continue` that leaves it), a
    # function-level one, a non-capturing one (a bare static function pointer,
    # which allocates nothing and must NOT be freed), and one raised past by an
    # exception (freed by the cleanup thunk the declaration pushed, not by the
    # skipped free). The second program is the fail-closed half: a closure
    # stored in a list, captured by another lambda, or aliased must stay alive.
    test_gimple_bounded_memory("gimple_owned_closure_env_is_freed", """\
def work(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var f = lambda x: x + i
        t += f(1)
        if i == 2:
            continue
        if i == 4:
            break
    return t

def once() -> Int:
    var g = lambda x: x * 3
    return g(5)

def boom(n: Int) -> Int:
    var f = lambda x: x + n
    if n > 2:
        raise ValueError("no")
    return f(10)

def main():
    print(work(3))
    print(work(9))
    print(once())
    var total = 0
    for r in range(300000):
        total += work(6) % 1000 + once()
    print(total)
    var hits = 0
    for r in range(20000):
        try:
            hits += boom(9)
        except ValueError as e:
            hits += 1
    print(hits)
""", "6\n15\n15\n9000000\n20000\n", 40)

    test_gimple_stdout("gimple_closure_that_escapes_is_not_freed", """\
def escape_list(kept: List, base: Int) -> Int:
    var t = 0
    for i in range(4):
        var f = lambda x: x + base
        kept.append(f)
        t += f(1)
    return t

def escape_rebind() -> Int:
    var f = lambda x: x + 1
    var g = f
    return g(2)

def capture_chain() -> Int:
    var f = lambda x: x + 1
    var h = lambda y: f(y) + 1
    return h(3)

def main():
    var kept: List = []
    print(escape_list(kept, 10))
    print(len(kept))
    # CALL each stored closure AFTER escape_list returned: freeing it with its
    # scope would dispatch through a freed pointer here, and the base is a
    # PARAMETER precisely so that every stored closure answers the same number
    # and the two engines' answers can be compared.
    var seen = 0
    for k in range(len(kept)):
        var fv = kept[k]
        seen += fv(1)
    print(seen)
    print(escape_rebind())
    print(capture_chain())
    var acc = 0
    for r in range(20000):
        var kk: List = []
        acc += escape_list(kk, 10) % 1000 + escape_rebind() + capture_chain()
    print(acc)
""", "44\n4\n44\n3\n5\n1040000\n")

    # ── A callee that provably returns a FRESH STRING hands ownership to its
    # caller, exactly as one returning a fresh container always has
    # (analyze_returns_fresh, which until now accepted only a container
    # display). The three shapes are the ones the analysis reads off the
    # lowering rather than infers from a type: a `+` (mojo_str_cat always
    # copies), a local bound to a `+`, and a slice (mojo_cstr_slice). Both
    # consumers of that ownership are in the same program: bound to a local and
    # freed at scope exit, and consumed on the spot by `len` (which reads the
    # length and nothing else). The second program is the other side of the
    # rule: a callee that returns its own ARGUMENT, or a plain literal it never
    # owned anything of, must NOT be freed — `str(s)` is the identity for a
    # string, so freeing a returned `str(s)` is a crash. The runner scribbles
    # freed memory, so a wrong free makes the comparisons (printed 3rd) fail
    # rather than usually pass.
    test_gimple_bounded_memory("gimple_fresh_returning_string_functions_are_owned", """\
def mk(i: Int) -> String:
    return "n" + String(i)

def via_local(i: Int) -> String:
    var s = "m" + String(i)
    return s

def via_slice(i: Int) -> String:
    return ("abcdef")[1:3]

def main():
    print(mk(3))
    print(via_local(9))
    print(via_slice(0))
    var total = 0
    for r in range(600000):
        total += len(mk(r % 100)) + len(via_local(r % 100)) + len(via_slice(0))
    var bound = 0
    for r in range(600000):
        var a = mk(r % 100)
        var b = via_local(r % 100)
        var c = via_slice(0)
        bound += len(a) + len(b) + len(c)
    print(total)
    print(bound)
""", "n3\nm9\nbc\n4680000\n4680000\n", 40)

    test_gimple_stdout("gimple_returned_string_that_is_not_fresh_is_not_freed", """\
def alias(s: String) -> String:
    return s

def identity(s: String) -> String:
    return str(s)

def make() -> String:
    return "kept-by-caller"

def work(kept: List[String]) -> Int:
    var t = 0
    for i in range(4):
        kept.append(alias("zz"))
        kept.append(identity("yy"))
        kept.append(make())
        var c = String("q=") + String(i)
        t += len(c)
    return t

def main():
    var kept: List[String] = []
    print(work(kept))
    print(len(kept))
    var hits = 0
    for k in range(len(kept)):
        if kept[k] == "zz":
            hits += 1
        if kept[k] == "yy":
            hits += 10
        if kept[k] == "kept-by-caller":
            hits += 100
    print(hits)
""", "12\n12\n444\n")

    # ── A list that owns its own string ELEMENTS (doc/MEMORY.html §3.B). A
    # `split()` result's elements are fresh allocations made by the runtime
    # function that built the list and by nothing else, but
    # `mojo_list_append_str` stores the pointer it is given, so
    # `mojo_list_free` released the container and left every string behind —
    # ~48 B/iteration, measured over 100k and 400k iterations and now flat.
    # The second program is the fail-closed half: `parts[0]` appended to a
    # list the caller keeps hands an element pointer out of the list, and
    # freeing the elements would dangle it, so the analysis
    # (ownership_destruct.list_elements_owned) must refuse the element free
    # there. The runner scribbles freed memory, so a wrong free shows up as
    # the comparisons (printed 4th) failing rather than usually passing.
    test_gimple_bounded_memory("gimple_split_result_element_strings_are_owned", """\
def work(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var parts = String("a b c").split(" ")
        t += len(parts)
        if i == 2:
            continue
        if i == 4:
            break
    return t

def lines(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var parts = String("x\\ny\\nz").splitlines()
        t += len(parts)
    return t

def main():
    print(work(3))
    print(work(9))
    print(lines(6))
    var total = 0
    for r in range(300000):
        total += work(6) % 1000 + lines(4)
    print(total)
""", "9\n15\n18\n8100000\n", 40)

    test_gimple_stdout("gimple_split_elements_that_escape_are_not_freed", """\
def work(kept: List[String]) -> Int:
    var t = 0
    for i in range(4):
        var parts = String("a b c").split(" ")
        t += len(parts)
        kept.append(parts[0])
        var one = parts[1]
        kept.append(one)
    return t

def main():
    var kept: List[String] = []
    print(work(kept))
    print(len(kept))
    var hits = 0
    for k in range(len(kept)):
        if kept[k] == "a":
            hits += 1
        if kept[k] == "b":
            hits += 10
    print(hits)
    var total = 0
    for r in range(20000):
        var kk: List[String] = []
        total += work(kk) % 1000
    print(total)
""", "12\n8\n44\n240000\n")

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

    # The shape of this compiler's own tokenizer: a scan over a string, one
    # character at a time, asking `c in ('(', '[', '{')` and `c == "x"`. Every
    # step used to malloc a one-character string (mojo_char_to_str) plus a fresh
    # list for each tuple literal, and free neither: ~150 bytes per character,
    # i.e. gigabytes for the self-hosted compiler over its own source
    # (bugs/PERF_selfhost_memory_leak_hunt.md). The characters are now shared
    # immortal strings and a display used only as the right side of `in` is freed
    # after the test. 16M characters here; the leak, if back, is gigabytes.
    test_gimple_bounded_memory("gimple_char_scan_allocates_nothing_per_character", """\
def scan(s: String) -> Int:
    var depth = 0
    var seen = 0
    var i = 0
    while i < len(s):
        var c = s[i]
        if c in ('(', '[', '{'):
            depth += 1
        elif c in (')', ']', '}'):
            depth -= 1
        if c == "x":
            seen += 1
        i += 1
    return depth * 1000 + seen

def main():
    var line = "(x[x{}x]) " * 8
    var total = 0
    for r in range(200000):
        total += scan(line)
    print(total)
""", "4800000\n", 60)

    # Rebuilding a string from its characters must still be right now that the
    # character strings are shared and never freed: `out + ch` frees its own
    # conversion temp only for a number, never for a character (a free of a
    # shared character string would corrupt the heap; the runner scribbles freed
    # memory, so a wrong free changes the output or crashes).
    test_gimple_bounded_memory("gimple_char_concat_never_frees_shared_character", """\
def rebuild(text: String) -> String:
    var out = String("")
    for i in range(len(text)):
        var ch = text[i]
        out = out + ch
    return out

def main():
    var t = String("(x[x{}x]) tokens")
    var hits = 0
    for r in range(100000):
        var u = rebuild(t)
        if u == t:
            hits += 1
    print(hits)
    print(rebuild(t))
    var seen = ""
    for c in "abcabc":
        if c in ["a", "c"]:
            seen = seen + c
    print(seen)
""", "100000\n(x[x{}x]) tokens\nacac\n", 60)

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

    # ── A CONTAINER used as a dict key keys by its VALUE
    # (bugs/CODEGEN_tuple_dict_key_hashed_by_address.md). A tuple word reached
    # the dict as a bare address: `(p, os.path.getmtime(p))` built twice hit
    # twice as often as it missed never, so every lookup grew the dict and the
    # self-hosted `mojoc --dump-full fire.py` carried ~16 GB of it.
    #
    # What is asserted here is the whole key path, not one spelling: store,
    # read, `in`, `get(k, default)`, a dict LITERAL key of the same tuple (the
    # two must agree or one dict is two dicts), a NESTED tuple (whose inner
    # list must be walked by value rather than addressed), and — the half that
    # a literal-only test would pass by accident — a key whose string element
    # is built at RUN time from a runtime value, so the two builds of it are
    # different strings at different addresses. That last case is why the
    # string slot is read by the model's own boxed-string discriminator rather
    # than by a pointer-shape test.
    test_gimple_stdout("gimple_tuple_dict_key_is_content_keyed", """\
def main():
    d = {}
    k1 = ("a", 1)
    k2 = ("a", 1)
    k3 = ("a", 2)
    d[k1] = "one"
    d[("b",)] = "tuple1"
    d[(1, 2)] = "ints"
    print(d[k2], d.get(k3, "none"), d[k3] if k3 in d else "none")
    print(d[("b",)], d[(1, 2)], d.get((2, 1), "none"), d.get(("a", 1), "none"))
    d[k1] = "again"
    print(d[k2], len(d))
    lit = {(9, 9): "lit"}
    lit[(9, 9)] = "lit2"
    print(lit[(9, 9)], len(lit))
    n = {}
    n[(("x",), "y")] = 1
    print(n[(("x",), "y")], n.get((("x",), "z"), "none"))
    for name in ["alpha", "beta", "alpha"]:
        e = {}
        e[(name, len(name))] = 1
        print(e[(name, len(name))], len(e))
main()
""", "one none none\ntuple1 ints none one\nagain 3\nlit2 1\n1 none\n"
       "1 1\n1 1\n1 1\n")

    # The other half of that doc, and the expensive one: a MISSING tuple key
    # grew the dict by one entry per lookup, which is where ~16 GB of the live
    # set on `mojoc --dump-full fire.py` went (a cache keyed by
    # `(module, name)` re-inserting what it had just looked up, every call).
    # stdout alone cannot see it, so this is the bounded-memory shape: the
    # answer is identical with or without the leak, and only the peak is not.
    #
    # The four keys are built ONCE, before the loop, and only INDEXED inside it.
    # That is deliberate: a tuple LITERAL in the loop allocates a list per
    # iteration and nothing ever frees one, which measures a different (also
    # real, also pre-existing) leak — ~180 B per literal, so 1.2 M of them is
    # ~220 MB on its own — and would swamp the ~78 B per LOOKUP this is here to
    # pin. What has to stay flat across the loop is the key rendering and the
    # dict itself, and those are the only things that move when this test fails.
    test_gimple_bounded_memory("gimple_tuple_dict_key_lookup_does_not_grow", """\
def main():
    keys = [("stable", 0), ("stable", 1), ("stable", 2), ("stable", 3)]
    d = {}
    for i in range(300000):
        d[keys[i % 4]] = i
        d[keys[i % 4]]
        if keys[i % 4] in d:
            d[keys[i % 4]] = i
        d.get(keys[i % 4], 0)
    print(len(d))
    print(d[keys[3]])
main()
""", "4\n299999\n", 40)

    # ── `with C():` with no `as` target still runs `__exit__`
    # (bugs/CODEGEN_with_no_as_target_drops_exit.md, deleted with that fix).
    # The five index-parallel lists `_gen_stmt_WithStmt` accumulates per with
    # item were appended from inside `if item.alias is not None:`, so the
    # no-`as` spelling registered nothing: `__enter__` was called, the body ran,
    # and NO teardown was emitted at all — not a wrong `__exit__` argument, no
    # teardown. On a lock that wedges every other process for the life of the
    # tree.
    #
    # It has to RUN to be a test: the generated C is well-formed either way and
    # the body's own output is identical, which is why `test_runtime_diff.py`'s
    # A/B engine comparison cannot see it. `__exit__` prints, so its absence is
    # in stdout. Both spellings are in one program because the fix is exactly
    # "the no-`as` spelling registers like the other one", and the loop is here
    # because a per-iteration teardown leak is what the bug was FOR.
    test_gimple_stdout("gimple_with_no_as_target_still_calls_exit", """\
class Lock:
    def __init__(self, name):
        self.name = name
        self.held = 0
    def __enter__(self):
        self.held = self.held + 1
        print("enter", self.name, self.held)
        return self.held
    def __exit__(self, t, v, tb):
        self.held = self.held - 1
        print("exit", self.name, self.held)

def work():
    l = Lock("A")
    with l:
        print("body no as")
    with l as n:
        print("body as", n)
    print("held after both", l.held)

def loop():
    for i in range(3):
        with Lock("B"):
            print("loop body", i)

def main():
    work()
    loop()
main()
""", "enter A 1\nbody no as\nexit A 0\nenter A 1\nbody as 1\nexit A 0\n"
       "held after both 0\n"
       "enter B 1\nloop body 0\nexit B 0\n"
       "enter B 1\nloop body 1\nexit B 0\n"
       "enter B 1\nloop body 2\nexit B 0\n")

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

    # `var s: Set[Int] = {}` — an empty `{}` is a dict DISPLAY, so resolving
    # the binding from the initializer alone declared `s` a `MojoDict` and
    # stack-allocated dict storage for it. `s.add(i)` then dispatched against
    # a dict header and silently did nothing, `i in s` was False and `len(s)`
    # was 0, all with exit 0; where the body needed the set's real kind the
    # same program instead hard-refused ("cannot coerce MojoDict * to
    # MojoSet *") depending on what else it contained. An empty literal is
    # evidence for no container kind at all, so the annotation decides —
    # through all three places that used to answer from the display alone
    # (the owned-local storage decision, the declaration's ctype, and the
    # coercion). The three spellings are `var s: Set[Int] = {}` (VarDecl),
    # the bare annotated `s: Set[Int] = {}` (an AssignStmt carrying the
    # annotation), and the same with strings.
    test_gimple_stdout("gimple_annotated_set_from_empty_braces", """\
def main():
    var s: Set[Int] = {}
    var acc = 0
    for i in range(10):
        s.add(i % 5)
    for i in range(10):
        if (i % 7) in s:
            acc += 1
    print(acc)
    print(s)
    print(len(s))
    print(0 in s)
    print(9 in s)

main()
""", "8\n{0, 1, 2, 3, 4}\n5\nTrue\nFalse\n")

    test_gimple_stdout("gimple_annotated_set_from_empty_braces_unannotated_spelling", """\
def main():
    s: Set[String] = {}
    s.add("a")
    print(s)
    print(len(s))
    print("a" in s)
    print("b" in s)
    var t: Set[Int] = Set[Int]()
    t.add(3)
    print(t)
    print(3 in t)
    d: Dict[String, Int] = {}
    d["k"] = 1
    print(d)

main()
""", "{'a'}\n1\nTrue\nFalse\n{3}\nTrue\n{'k': 1}\n")

    # A `List[String]` filled only from a CALLEE read back as ints: the
    # element type of a list is otherwise recorded by its `append` sites,
    # and a caller that only sees the list through a call has none — so
    # `kept[0]` was typed int64_t, `len(kept[0])` read the string pointer's
    # bits as a header (6581285), `print(kept[0])` formatted the pointer
    # with %ld, and only the comparison still worked because it dispatched
    # on the string-literal side. The declaration's own annotation is real
    # evidence and is now honoured on all three paths that can consume a
    # binding statement: the two ordinary statement paths, and the
    # owned-local stack allocation that swallows `kept: List[String] = []`
    # whole (which is the shape this very program takes, because `[]` is an
    # empty constructor) and which had no element-type seeding at all.
    # `other` is the control that stays broken and is NOT asserted as
    # correct: an unannotated `other = []` genuinely has no static evidence
    # anywhere, which is what the cross-call element-type contract is for.
    test_gimple_stdout("gimple_annotated_list_string_filled_in_a_callee", """\
def fill(kept):
    kept.append("cde")

def main():
    kept: List[String] = []
    fill(kept)
    print(len(kept[0]))
    print(kept[0])
    print(kept[0] == "cde")
    for k in kept:
        print(k)
        print(len(k))
    ints: List[Int] = []
    ints.append(7)
    print(ints[0] + 1)
    print(f"{kept[0]}")

main()
""", "3\ncde\nTrue\ncde\n3\n8\ncde\n")

    # A dynamically-set attribute whose value is a STRING, read back through
    # every spelling. The struct declared no such field, so the field-scan
    # pass minted a phantom one — and minted it `int`, because that is the
    # "nothing is known about this member" answer and a read-only phantom is
    # the case it is right for. A member that IS assigned is not read-only,
    # and storing a `char *` through a 4-byte `int` field truncates it: the
    # read printed the low 32 bits of the string's address as a decimal, and
    # `len(o.x)` then dereferenced that truncated value and SEGFAULTED. The
    # minted field's type now comes from the value assigned to it (pointer-
    # shaped and floating answers only, so a member assigned an ordinary
    # integer keeps exactly the declaration it always had). `o.n` is that
    # control. `getattr` is the same read by a different spelling, and it
    # needed its own fix: the value was already in the field (the generated
    # `_mojo_getattr_C` reads it) and only the call site's cast was missing,
    # which is gated on the self-hosted source because a bare by-NAME field
    # lookup is unsound for an arbitrary receiver. The receiver's OWN
    # declared field is sound, and is what `o.x` already used, so the two
    # spellings now agree by construction.
    test_gimple_stdout("gimple_dynamic_attribute_string_keeps_its_type", """\
class C:
    pass

def main():
    o = C()
    o.x = "hello"
    o.n = 5
    print(o.x)
    print(len(o.x))
    print(f"{o.x}")
    print(str(o.x))
    print("%s" % o.x)
    print(o.x == "hello")
    print(o.n)
    print(o.n + 1)
    print(getattr(o, "x", ""))

main()
""", "hello\n5\nhello\nhello\nhello\nTrue\n5\n6\nhello\n")

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

    # The doc's item 6a residue: `partition`'s container TYPE. The doc
    # concluded it was unfixable for want of a tuple type; re-tested, that
    # premise is STALE. A tuple type has existed for some time — a
    # `mojo_mark_as_tuple` marker on the MojoList (see that function's own
    # doc comment) — but only repr and `isinstance(x, tuple)` read it, so a
    # "tuple" was a list that merely PRINTED like one. The fix makes the
    # marker load-bearing, and these four cases pin each way it is now
    # observable: the mutation refusals, the value comparison, the
    # cross-type inequality, and the type predicates.
    test_gimple_runtime_error("gimple_tuple_append_raises", """\
fn main():
    print('before')
    t = b'a=b'.partition(b'=')
    t.append(b'z')
""", "'tuple' object has no attribute 'append'")

    # The two item forms are a TypeError with CPython's exact wording, and
    # are NOT the same operation as `.pop` even though all three remove an
    # element — which is why `del t[i]` got its own runtime entry point
    # (mojo_list_delitem) rather than sharing mojo_list_pop_at's.
    test_gimple_runtime_error("gimple_tuple_setitem_raises", """\
fn main():
    print('before')
    t = (1, 2, 3)
    t[0] = 9
""", "'tuple' object does not support item assignment")

    test_gimple_runtime_error("gimple_tuple_delitem_raises", """\
fn main():
    print('before')
    t = (1, 2, 3)
    del t[0]
""", "'tuple' object doesn't support item deletion")

    # The refusals must be TYPED and CATCHABLE, not a print-and-exit: real
    # code distinguishes AttributeError from TypeError here, and a
    # program that guards `if not isinstance(p, list): p.append(...)`
    # depends on being able to catch and continue. Pinned because "raises
    # the right text" and "raises catchably with the right type" are
    # different properties and only the second one is load-bearing.
    test_gimple_stdout("gimple_tuple_mutation_refusals_are_catchable", """\
fn main():
    t = (1, 2, 3)
    try:
        t.append(9)
    except AttributeError:
        print('caught AttributeError')
    try:
        t[0] = 9
    except TypeError:
        print('caught TypeError set')
    try:
        del t[0]
    except TypeError:
        print('caught TypeError del')
    try:
        t.pop()
    except AttributeError:
        print('caught AttributeError pop')
    try:
        t.extend([4])
    except AttributeError:
        print('caught AttributeError extend')
    try:
        t.insert(0, 4)
    except AttributeError:
        print('caught AttributeError insert')
    try:
        t.remove(1)
    except AttributeError:
        print('caught AttributeError remove')
    try:
        t.clear()
    except AttributeError:
        print('caught AttributeError clear')
    try:
        t.reverse()
    except AttributeError:
        print('caught AttributeError reverse')
    try:
        t.sort()
    except AttributeError:
        print('caught AttributeError sort')
    print(t)
    # A REAL list is unaffected by any of that.
    l = [1, 2, 3]
    l.append(4); l.extend([5]); l.insert(0, 0); l.pop()
    l.remove(0); l.reverse(); l.clear()
    print(l, len(l))
    l = [1, 2, 3]
    l[0] = 9; del l[0]; l[0:1] = [7, 8]; del l[0:1]
    print(l)
""", "caught AttributeError\ncaught TypeError set\ncaught TypeError del\n"
     "caught AttributeError pop\ncaught AttributeError extend\n"
     "caught AttributeError insert\ncaught AttributeError remove\n"
     "caught AttributeError clear\ncaught AttributeError reverse\n"
     "caught AttributeError sort\n(1, 2, 3)\n[] 0\n[8, 3]\n")

    # The remaining half of the container TYPE: what the marker decides
    # about the value, not just about mutation. `==` was a raw C POINTER
    # comparison, so two equal containers compared unequal — including two
    # equal tuples, and (the other direction) a tuple equalling a list.
    test_gimple_stdout("gimple_container_value_equality", """\
fn main():
    t = (1, 2)
    u = (1, 2)
    print(t == u, t == (1, 2), u == t, t != u, t == (1, 3))
    l = [1, 2]
    m = [1, 2]
    print(l == m, l == [1, 2], m == l, l != m, l == [1, 3])
    # a tuple is never equal to a list, in either order
    print(t == l, l == t)
    s = b'ab'.split(b'b')
    print(s == [b'a', b''], s != [b'a', b'z'])
    st = (b'a', b'')
    print(st == (b'a', b''), st == s)
    # strings compare by content, not by address
    print(['a', 'b'] == ['a', 'b'], ['a'] == ['b'])
    # floats stored as raw bits
    print([1.5, 2.5] == [1.5, 2.5], [1.5] == [2.5])
    # different lengths
    print([1, 2] == [1, 2, 3], [] == [], () == ())
""", "True True True False False\nTrue True True False False\n"
     "False False\nTrue True\nTrue False\nTrue False\nTrue False\n"
     "False True True\n")

    # `count` counts OCCURRENCES; `x in l` only asks whether there is one.
    # There was no `count` case at all for a list, so every `l.count(v)`
    # fell to the dummy 0-stub and answered 0 for a list that plainly
    # contained the value — a silent wrong value, not an error.
    test_gimple_stdout("gimple_list_count_counts_occurrences", """\
fn main():
    l = [1, 2, 1]
    print(l.count(1), l.count(2), l.count(9))
    m = ['a', 'b', 'a']
    print(m.count('a'), m.count('b'), m.count('z'))
    s = b'ab'.split(b'a')
    print(s.count(b'a'), s.count(b'b'), s.count(b'z'))
    t = (1, 2, 1)
    print(t.count(1), t.count(2))
    print([] .count(1), [1].count(1))
""", "2 1 0\n2 1 0\n0 1 0\n2 1\n0 1\n")

    # The rest of what the marker decides, beyond mutation and equality:
    # the operations that PRESERVE a container's type and the two that do
    # not. `mojo_list_copy` deliberately does NOT propagate the marker
    # (`list(t)` is a list), while slice/concat/repeat do.
    test_gimple_stdout("gimple_tuple_type_preserved_by_ops", """\
fn main():
    t = (1, 2)
    l = [1, 2]
    print(t + (3,), t * 2, t[:], t[:1])
    print(l + [3], l * 2, l[:], l[:1])
    print(list(t), tuple(l), list(l))
    print(isinstance(t, tuple), isinstance(t, list))
    print(isinstance(l, tuple), isinstance(l, list))
    print(isinstance(b'a=b'.partition(b'='), tuple))
    print(isinstance(b'a=b'.partition(b'='), list))
    print(isinstance((1, 2), (int, str)))
    print(isinstance((1, 2), (list, str)))
""", "(1, 2, 3) (1, 2, 1, 2) (1, 2) (1,)\n[1, 2, 3] [1, 2, 1, 2] [1, 2] [1]\n"
     "[1, 2] (1, 2) [1, 2]\nTrue False\nFalse True\nTrue\nFalse\nFalse\nFalse\n")

    test_gimple_stdout("gimple_bytes_fromhex_maketrans_translate", """\
fn main():
    print(bytes.fromhex('68656c6c6f'))
    print(bytes.fromhex('68 65 6c'))
    print(bytes.fromhex('DEADBEEF'))
    print(b'abc'.translate(bytes.maketrans(b'a', b'b')))
    print(b'abc'.translate(bytes.maketrans(b'a', b'b', b'c')))
    print(b'abc'.translate(bytes(range(256))))
""", "b'hello'\nb'hel'\nb'\\xde\\xad\\xbe\\xef'\nb'bbc'\nb'bbc'\nb'abc'\n")

    # Found by a differential sweep of the bytes surface against CPython
    # (one expression per line, run on both engines, diffed). Each of these
    # answered a PLAUSIBLE wrong value with exit 0, or a raw int 0.
    #
    # `startswith`/`endswith` took [start[, end]] and silently DROPPED it —
    # the call site passed only (bytes, prefix), so the comparison ran over
    # the whole string and `b'abc'.startswith(b'a', 1, 2)` said True.
    test_gimple_stdout("gimple_bytes_startswith_endswith_window", """\
fn main():
    print(b'abc'.startswith(b'a', 1, 2))
    print(b'abc'.startswith(b'b', 1, 2))
    print(b'abc'.endswith(b'c', 0, 2))
    print(b'abc'.endswith(b'b', 0, 2))
    print(b'abc'.startswith(b'abc', 0, 3))
    print(b'abc'.endswith(b'abc', 0, 3))
    print(b'abc'.startswith(b'a', -1))
    print(b'abc'.endswith(b'c', -1))
    print(b'abc'.startswith(b'a', 10))
    print(b'abc'.endswith(b'c', 10))
    print(b'abc'.startswith(b'a', 2, 1))
    print(b'abc'.startswith(b'a'))
    print(b'abc'.endswith(b'c'))
    print(b'abc'.startswith(b''))
    print(b''.startswith(b''))
    print(b'abc'.endswith(b''))
""", "False\nTrue\nFalse\nTrue\nTrue\nTrue\nFalse\nTrue\nFalse\nFalse\n"
     "False\nTrue\nTrue\nTrue\nTrue\nTrue\n")

    # `expandtabs` had NO bytes implementation at all: every spelling fell to
    # the generic unknown-method stub and answered a raw int 0. The
    # non-positive-tabsize row is here because CPython REMOVES the tab
    # there (`b'a\\tb\\tc'.expandtabs(0)` is `b'abc'`) rather than leaving it.
    test_gimple_stdout("gimple_bytes_expandtabs", """\
fn main():
    print(b'abc'.expandtabs())
    print(b'a\\tb'.expandtabs(4))
    print(b'\\t'.expandtabs())
    print(b'a\\tb\\tc'.expandtabs(0))
    print(b'a\\tb\\tc'.expandtabs(-1))
    print(b'\\ta\\tb'.expandtabs(1))
    print(b''.expandtabs(0))
    print(b''.expandtabs(4))
    print(b'a\\rb\\tc'.expandtabs(4))
    print(b'a\\t\\f\\tx'.expandtabs(4))
    print(b'a\\tb\\tc'.expandtabs(tabsize=2))
""", "b'abc'\nb'a   b'\nb'        '\nb'abc'\nb'abc'\nb' a b'\nb''\nb''\n"
     "b'a\\rb   c'\nb'a   \\x0c   x'\nb'a b c'\n")

    # `b.translate(table, delete)` dropped the DELETE set entirely, so
    # `b'hello'.translate(None, b'l')` came back unchanged. A table of the
    # wrong length is a ValueError in CPython; a short one used to be
    # partially applied instead.
    test_gimple_stdout("gimple_bytes_translate_delete_set", """\
fn main():
    print(b'hello'.translate(None, b'l'))
    print(b'hello'.translate(None, b'l'))
    print(b'hello'.translate(bytes(range(256)), b'l'))
    print(b'hello'.translate(None, b'lxo'))
    print(b'hello'.translate(None, b''))
    print(b'hello'.translate(bytes(range(256))))
    print(b'abc'.translate(bytes.maketrans(b'a', b'b')))
""", "b'heo'\nb'heo'\nb'heo'\nb'he'\nb'hello'\nb'hello'\nb'bbc'\n")

    test_gimple_runtime_error("gimple_bytes_translate_short_table_raises", """\
fn main():
    print(b'hello'.translate(b'xyz', b'l'))
""", "ValueError: translation table must be 256 characters long")

    # `b.replace(b'', x)` is a real CPython spelling, not a no-op: the empty
    # pattern matches before every character and after the last. It
    # answered the string UNCHANGED, because the loop advances by the
    # pattern length and so never matched at all.
    test_gimple_stdout("gimple_bytes_replace_empty_pattern", """\
fn main():
    print(b'aaa'.replace(b'', b'-'))
    print(b''.replace(b'', b'-'))
    print(b'ab'.replace(b'', b'--'))
    print(b'aaa'.replace(b'', b'-', 2))
    print(b'aaa'.replace(b'', b'-', 0))
    print(b'aaa'.replace(b'a', b'b'))
    print(b'aaa'.replace(b'a', b'b', 2))
    print(b'aaa'.replace(b'a', b'b', 0))
    print(b'hello'.replace(b'l', b'L'))
""", "b'-a-a-a-'\nb'-'\nb'--a--b--'\nb'-a-aa'\nb'aaa'\nb'bbb'\nb'bba'\n"
     "b'aaa'\nb'heLLo'\n")

    # `b.count(b'')` counts len+1 non-overlapping empty matches, not 0. The
    # counting loop advances by needle->len, which is 0, so it could not
    # produce that answer and answered 0 for every input.
    test_gimple_stdout("gimple_bytes_count_empty_needle", """\
fn main():
    print(b'abc'.count(b''))
    print(b''.count(b''))
    print(b'abc'.count(b'b'))
    print(b'aaa'.count(b'a'))
    print(b'aaa'.count(b'a', 1))
    print(b'abc'.count(b'b', 1, 3))
    print(b'abc'.count(97))
    print(b'abc'.count(98, 0, 2))
""", "4\n1\n1\n3\n2\n1\n1\n1\n")

    # `split(b'')` is a ValueError, and it was conflated with the genuinely
    # absent separator (`split()`, which IS a whitespace split) because both
    # arrive as a NULL-or-empty `sep`. So `split(b'')` silently
    # whitespace-split instead of raising.
    test_gimple_runtime_error("gimple_bytes_split_empty_sep_raises", """\
fn main():
    print(b'ab'.split(b''))
""", "ValueError: empty separator")

    test_gimple_runtime_error("gimple_bytes_rsplit_empty_sep_raises", """\
fn main():
    print(b'ab'.rsplit(b''))
""", "ValueError: empty separator")

    test_gimple_stdout("gimple_bytes_split_no_sep_is_whitespace", """\
fn main():
    print(b'a b'.split())
    print(b'a b'.split(None))
    print(b'  a  b '.split())
    print(b'a,,b'.split(b','))
    print(b'a-b-c'.rsplit(b'-', 1))
    print(b'a-b-c'.rsplit(b'-'))
    print(b''.split(b','))
    print(b'a,b'.split(b',', 1))
    print(b'a b c'.split(maxsplit=1))
""", "[b'a', b'b']\n[b'a', b'b']\n[b'a', b'b']\n[b'a', b'', b'b']\n"
     "[b'a-b', b'c']\n[b'a', b'b', b'c']\n[b'']\n[b'a', b'b']\n[b'a', b'b c']\n")

    # `index`/`rindex` RAISE when the subsection is absent; `find`/`rfind`
    # answer -1. All four were one function, so both halves were wrong:
    # `index` printed -1, and the byte-value form of `find` raised.
    test_gimple_runtime_error("gimple_bytes_index_missing_raises", """\
fn main():
    print(b'abc'.index(b'z'))
""", "ValueError: subsection not found")

    test_gimple_runtime_error("gimple_bytes_rindex_missing_raises", """\
fn main():
    print(b'abc'.rindex(b'z'))
""", "ValueError: subsection not found")

    test_gimple_stdout("gimple_bytes_find_rfind_still_return_minus_one", """\
fn main():
    print(b'abc'.find(b'z'))
    print(b'abc'.rfind(b'z'))
    print(b'abc'.find(300 - 203))
    print(b'abc'.rfind(300 - 203))
    print(b'abc'.find(b'b'))
    print(b'abc'.rfind(b'b'))
    print(b'abc'.find(98))
    print(b'abc'.rfind(98))
    print(b'abc'.index(b'c'))
    print(b'abc'.rindex(b'a'))
    print(b'abc'.index(b'c', 2))
    print(b'abc'.rindex(b'a', 0, 2))
""", "-1\n-1\n0\n0\n1\n1\n1\n1\n2\n0\n2\n0\n")

    # A byte VALUE outside 0-255 is a ValueError, not a silently wrapped
    # one: `& 0xFF` turned 300 into 44, so `count(300)` counted 'c'.
    test_gimple_runtime_error("gimple_bytes_count_out_of_range_raises", """\
fn main():
    print(b'abc'.count(300))
""", "ValueError: byte must be in range(0, 256)")

    # `b[i]` at an explicit subscript RAISES out of range. It answered 0,
    # and 0 is not a neutral value here: it is a real byte value, so
    # `if b[i] == 0:` on a short buffer silently took the true branch.
    test_gimple_runtime_error("gimple_bytes_index_out_of_range_raises", """\
fn main():
    print(b'abc'[10])
""", "IndexError: index out of range")

    test_gimple_runtime_error("gimple_bytes_negative_index_out_of_range_raises", """\
fn main():
    print(b'abc'[-10])
""", "IndexError: index out of range")

    test_gimple_runtime_error("gimple_empty_bytes_index_raises", """\
fn main():
    print(b''[0])
""", "IndexError: index out of range")

    test_gimple_stdout("gimple_bytes_in_range_index_still_works", """\
fn main():
    print(b'abc'[0], b'abc'[1], b'abc'[2], b'abc'[-1], b'abc'[-3])
    print(b'ab'[0], b'ab'[-1])
    total = 0
    for b in b'abc':
        total = total + b
    print(total)
""", "97 98 99 99 97\n97 98\n294\n")

    # Iterating `bytes` yields its INTEGERS. all/any/sum/max/min over a
    # bytes object were either the codegen's constant stub or a reinterpret
    # of the MojoBytes header as a list — so `sum(b'abc')` printed a
    # heap-pointer decimal and `max(b'abc')` printed an address.
    test_gimple_stdout("gimple_bytes_builtins_iterate_as_ints", """\
fn main():
    print(all(b'abc'))
    print(all(b''))
    print(all(b'a0b'))
    print(any(b'abc'))
    print(any(b''))
    print(sum(b'abc'))
    print(sum(b''))
    print(max(b'abc'))
    print(min(b'abc'))
    print(max(b'cba'))
    print(min(b'cba'))
    print(max(b'\\x00\\x7f'))
    print(min(b'\\x00\\x7f'))
""", "True\nTrue\nTrue\nTrue\nFalse\n294\n0\n99\n97\n99\n97\n127\n0\n")

    # `any` asks whether any ELEMENT is truthy, and an element of a bytes
    # object is an int where 0 is falsy — so this is not "is the container
    # non-empty", and `any(b'\\x00')` is False in CPython.
    test_gimple_stdout("gimple_bytes_any_tests_elements", """\
fn main():
    print(any(b'\\x00'))
    print(any(b'\\x00\\x00'))
    print(any(b'\\x00a'))
    print(all(b'\\x00\\x00'))
    print(any(b''))
""", "False\nFalse\nTrue\nTrue\nFalse\n")

    # `list(reversed(b))` and `sorted(b)` had no bytes route: the first
    # produced an EMPTY list (the comprehension cannot iterate a reversed()
    # call) and the second SEGFAULTED, reading the MojoBytes header as a
    # list's data pointer and length.
    test_gimple_stdout("gimple_bytes_reversed_and_sorted", """\
fn main():
    print(list(reversed(b'abc')))
    print(list(reversed(b'')))
    print(bytes(reversed(b'abc')))
    print(sorted(b'cba'))
    print(sorted(b''))
    print(sorted(b'cab'))
    for x in sorted(b'ba'):
        print(x)
""", "[99, 98, 97]\n[]\nb'cba'\n[97, 98, 99]\n[]\n[97, 98, 99]\n97\n98\n")

    # `casefold` exists on str and NOT on bytes; `hex` exists on bytes and
    # NOT on str, and takes no arguments. Each pair used to answer a raw
    # int 0 from the generic unknown-method stub — `str.hex` resolving to
    # the runtime's integer formatter, and `bytes.hex` dropping its
    # argument.
    test_gimple_runtime_error("gimple_bytes_casefold_raises", """\
fn main():
    print(b'abc'.casefold())
""", "AttributeError: 'bytes' object has no attribute 'casefold'")

    test_gimple_runtime_error("gimple_str_hex_raises", """\
fn main():
    print('abc'.hex())
""", "AttributeError: 'str' object has no attribute 'hex'")

    test_gimple_runtime_error("gimple_bytes_hex_takes_no_args_raises", """\
fn main():
    print(b'abc'.hex(2))
""", "TypeError: hex() takes no arguments")

    # str.casefold / swapcase / title / capitalize: all four were missing
    # from the str lowering and answered the unknown-method stub's 0.
    test_gimple_stdout("gimple_str_case_methods", """\
fn main():
    print('aBc'.swapcase())
    print('hello world'.title())
    print('aBC'.capitalize())
    print('abc'.capitalize())
    print('ABC'.casefold())
    print('Hello World'.casefold())
    print('aBc dEf'.swapcase())
    print('a1b c'.title())
    print('hello WORLD'.title())
    print(''.title())
    print(''.capitalize())
    print(''.swapcase())
    print('  lead'.capitalize())
""", "AbC\nHello World\nAbc\nAbc\nabc\nhello world\nAbC DeF\nA1B C\n"
     "Hello World\n\n\n\n  lead\n")

    # A bytes literal did not decode \\a, \\b, \\f or \\v, so b"\\f" was TWO
    # characters (backslash, f) rather than one (0x0c) — a silent wrong
    # value in every bytes literal using them, and an inconsistency with
    # the str path, which decoded all four correctly.
    test_gimple_stdout("gimple_bytes_literal_escapes", """\
fn main():
    print(b'\\f')
    print(b'\\v')
    print(b'\\a')
    print(b'\\b')
    print(b'\\x0c')
    print(b'\\f\\v\\a\\b\\n\\t\\r\\0\\\\')
    print(b'a\\fb\\vc')
    print(b'\\q')
    print(rb'\\f')
    print(len(b'\\f'), len(b'\\n'), len(b'\\x41'))
""", "b'\\x0c'\nb'\\x0b'\nb'\\x07'\nb'\\x08'\nb'\\x0c'\n"
     "b'\\x0c\\x0b\\x07\\x08\\n\\t\\r\\x00\\\\'\nb'a\\x0cb\\x0bc'\nb'\\\\q'\n"
     "b'\\\\f'\n1 1 1\n")

    # `x[a:b:0]` is a ValueError in CPython — a zero step is a
    # contradiction, not an empty range. Every slice helper treated step 0
    # as "step 1", so the compiled path answered the WHOLE sequence.
    test_gimple_runtime_error("gimple_bytes_slice_zero_step_raises", """\
fn main():
    print(b'abc'[1:2:0])
""", "ValueError: slice step cannot be zero")

    test_gimple_runtime_error("gimple_list_slice_zero_step_raises", """\
fn main():
    print([1,2,3][0:3:0])
""", "ValueError: slice step cannot be zero")

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

    # `x in <dict>` where the DICT arrived at the test with its static type
    # erased -- a dict handed to an unannotated parameter, which is what any
    # cross-module table looks like -- used to go to `mojo_in_dispatch_int`,
    # and that dispatcher had branches for a list and a set and no dict at
    # all, so it fell off the end and answered False. Compiled, exit 0, no
    # diagnostic; only the ANSWER was wrong, which is why the helper below
    # has to take the dict as a parameter for this to be the erased path.
    #
    # Both key domains are covered because the erased view cannot tell them
    # apart: a str key is a boxed `char *` in the same int64_t the integers
    # use, so the dispatcher's dict branch has to decide between them (the
    # existing `mojo_dict_contains_kw`), and a dict mixing the two domains
    # is the case where deciding wrong is visible.
    test_gimple_stdout("gimple_in_erased_dict_answers_membership", """\
def count_str(keys, d) -> Int:
    var n = 0
    for k in keys:
        if k in d:
            n = n + 1
    return n

def count_int(keys, d) -> Int:
    var n = 0
    for k in keys:
        if k in d:
            n = n + 1
    return n

fn main():
    var names = ["f0", "f1"]
    var byname = {}
    byname["f0"] = 1
    byname["f1"] = 1
    print(count_str(names, byname))
    var nums = [1, 2]
    var bynum = {}
    bynum[1] = 1
    bynum[2] = 1
    print(count_int(nums, bynum))
    # an absent key is still absent, and the mixed-domain dict answers both
    print(count_str(["f0", "f9"], byname))
    print(count_int([1, 9], bynum))
    # a numeric STRING key and the integer it spells are one entry in this
    # runtime (see _dict_set_raw's keykind note), so an erased int needle
    # finds the "1" entry too -- the established answer for d["1"], asserted
    # here because the new dict branch now shares that decision with the
    # dict-subscript path and the two must not drift apart.
    var numeric = {}
    numeric["1"] = 100
    print(count_int([1, 2], numeric), 1 if numeric["1"] == 100 else 0)
    return 0
""", "2\n2\n1\n1\n1 1\n")

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

    # The rest of the memoryview descriptor surface, found by the same
    # differential sweep. None of these had a lowering at either the member
    # read or the call form, so each fell to the generic unknown-member path
    # and printed ITS OWN HEAP ADDRESS as a decimal: `mv.shape` printed
    # 4341225952 where CPython prints `(4,)`. That is a silent wrong value
    # twice over — it is not a shape, and it changes every run, so a program
    # comparing it against anything took a branch decided by the allocator.
    test_gimple_stdout("gimple_memoryview_shape_descriptors", """\
fn main():
    var mv = memoryview(b'abcd')
    print(mv.shape)
    print(mv.strides)
    print(mv.suboffsets)
    print(mv.ndim)
    print(mv.c_contiguous, mv.f_contiguous, mv.contiguous)
    print(memoryview(b'').shape)
    print(memoryview(bytearray(b'abc')).shape)
    print(mv[1:3].shape)
    # The CALL form must agree with the member read, or a program that
    # writes `mv.shape` and one that writes `mv.__getattribute__('shape')`
    # would not.
    print(len(str(mv.shape)))
""", "(4,)\n(1,)\n()\n1\nTrue True True\n(0,)\n(3,)\n(2,)\n4\n")

    test_gimple_stdout("gimple_memoryview_tolist", """\
fn main():
    print(memoryview(b'abcd').tolist())
    print(memoryview(bytearray(b'abc')).tolist())
    print(memoryview(b'').tolist())
    print(memoryview(b'abcd')[1:3].tolist())
    for x in memoryview(b'ab').tolist():
        print(x)
""", "[97, 98, 99, 100]\n[97, 98, 99]\n[]\n[98, 99]\n97\n98\n")

    # An out-of-range memoryview read raises a real, CATCHABLE IndexError.
    # It was a print-and-exit, so a program guarding an optional read
    # (`try: v = mv[n] except IndexError: v = None`) died instead of
    # taking the fallback.
    test_gimple_stdout("gimple_memoryview_index_error_is_catchable", """\
fn main():
    var mv = memoryview(b'abcd')
    print(mv[0], mv[3], mv[-1], mv[-4])
    try:
        print(mv[10])
    except IndexError:
        print('caught IndexError')
    try:
        print(mv[-10])
    except IndexError:
        print('caught IndexError neg')
    print(bytes(mv[1:100]), bytes(mv[1:3]))
""", "97 100 100 97\ncaught IndexError\ncaught IndexError neg\n"
     "b'bcd' b'bc'\n")

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
    # The reads with NO compile-time slot index — iteration, a computed
    # subscript, a copy — are in the two tests below; they are a different
    # mechanism (a BOX, plus the kinds recorded on the value itself) and not
    # a continuation of this one.
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
    # A DERIVED value — one the codegen never saw as a `struct.unpack` call —
    # used to lose the per-slot kinds entirely and print raw IEEE-754 bits
    # again, because they lived in a table keyed by the C value name the
    # unpack was assigned to. They now travel with the VALUE (the runtime
    # records them on it, `mojo_list_set_kinds`), so `list(t)`, `t[:]`,
    # `t + t` and a copy made by any spelling are right. Every expectation
    # here is CPython's, checked on the same program.
    test_gimple_stdout("gimple_struct_mixed_reads_survive_a_derivation", """\
fn main():
    var b = struct.pack('<if', 1, 1.0)
    var t = struct.unpack('<if', b)
    print(t)
    print(list(t))
    print(t[:])
    print(t + t)
    var c = struct.unpack('>dhh', struct.pack('>dhh', 1.0, 2, 1))
    print(c)
    print(list(c))
    print(c[:])
    print(c + c)
    var s = struct.Struct('>dhh')
    print(list(s.unpack(struct.pack('>dhh', 1.0, 2, 1))))
""", "(1, 1.0)\n[1, 1.0]\n(1, 1.0)\n(1, 1.0, 1, 1.0)\n"
       "(1.0, 2, 1)\n[1.0, 2, 1]\n(1.0, 2, 1)\n(1.0, 2, 1, 1.0, 2, 1)\n"
       "[1.0, 2, 1]\n")

    # A read whose slot index is NOT a compile-time constant. There is no
    # single right C type for the value it produces, because the list holds
    # both an int and a float, so the read boxes a float slot
    # (`mojo_list_get_boxed`) and `print` resolves the box by tag. Before
    # this, all three spellings handed back 4607182418800017408 for 1.0.
    # `t[i]` with a computed `i` and `for x in t` are the two shapes the
    # removed doc named; `list(t)` and `t[:]` exercise the same read on a
    # derived value.
    test_gimple_stdout("gimple_struct_mixed_reads_without_a_static_index", """\
fn main():
    var b = struct.pack('<if', 1, 1.0)
    var t = struct.unpack('<if', b)
    for x in t:
        print(x)
    var i = 1
    print(t[i])
    print(t[0])
    for y in list(t):
        print(y)
    var j = 0
    print(list(t)[j])
    var s = struct.Struct('<if')
    for z in s.unpack(b):
        print(z)
""", "1\n1.0\n1.0\n1\n1\n1.0\n1\n1\n1.0\n")

    # Arithmetic on an element read out of a heterogeneous container. The
    # read produces a BOX (a heap cell, because a float has no int64_t
    # spelling), so the operand has to be taken apart before it can be added
    # to or multiplied by. Before this, `t[i] + 1` printed 4353979905 — the
    # box's own address, which is a silent wrong value and the outcome this
    # repo ranks above every other. `_to_int64` is the hook for an integer
    # context; `_lower_binary` always unpacks as a DOUBLE, because a box only
    # ever holds a float and in Python a float operand makes the whole
    # operation a float one.
    #
    # The sixth and ninth lines are the ONE recorded cost of "always a
    # double", asserted here rather than left to rot: a boxed read whose
    # runtime slot turns out to be an INT gets promoted, so its arithmetic
    # result is float-typed and prints `2.0` where CPython prints `2` — the
    # same number, a different format. Choosing per slot would need a
    # runtime branch around the whole operand dispatch, and a wrong value
    # traded for a wrong format is the right way round. Line seven is the
    # control: a read with a COMPILE-TIME index takes no box at all, so
    # `t[0] + 1` is exact.
    test_gimple_stdout("gimple_heterogeneous_element_arithmetic_unboxes", """\
fn main():
    var t = struct.unpack('<if', struct.pack('<if', 1, 1.5))
    var i = 1
    print(t[i])
    print(t[i] + 1)
    print(t[i] * 2.0)
    print(str(t[i]))
    print(f"{t[i]}")
    var k = 0
    print(t[k] + 1)
    print(t[0] + 1)
    var a = [1, 2.5]
    for x in a:
        print(x + 1)
""", "1.5\n2.5\n3.0\n1.5\n1.5\n2.0\n2\n2.0\n3.5\n")

    # The SAME case one level down, in the spelling that is not `var`:
    # `b = [1, 2.5]` / `t = struct.unpack(...)` is an `AssignStmt`, and the
    # per-slot-kind side tables were carried across only by the VarDecl path,
    # so every read of the assigned name used the container's PROMOTED
    # element type ('double') — `b[0]` printed `5e-324`, the int slot's bit
    # pattern read as a denormal double, and the loop printed `5e-324` too.
    # Exit 0, no diagnostic, and the identical `var` spelling one line away
    # was right. `c` is the control: a homogeneous list is untouched, and
    # `t`'s two reads are the static-index and computed-index cases of the
    # same value. (The trailing `2.0` is the documented promotion above, not
    # a defect: a boxed read whose slot turns out to be an int is computed
    # in double.)
    test_gimple_stdout("gimple_heterogeneous_reads_survive_a_plain_assignment", """\
fn main():
    b = [1, 2.5]
    print(b)
    print(b[0])
    var i = 0
    print(b[i])
    for y in b:
        print(y)
    t = struct.unpack('<if', struct.pack('<if', 1, 1.5))
    print(t[0])
    var j = 1
    print(t[j])
    for z in t:
        print(z)
    c = [1, 2, 3]
    for w in c:
        print(w)
""", "[1, 2.5]\n1\n1\n1\n2.5\n1\n1.5\n1\n1.5\n1\n2\n3\n")

    # The same limit one level lower, without `struct` at all: a
    # HETEROGENEOUS LITERAL. `[1, 2.5]` used to append the int through the
    # list-wide 'double' suffix, so the literal printed `[1.0, 2.5]` and
    # iterated as `1.0, 2.5`. The uniform cases must be untouched — a
    # promoted `[1, 2.0]` still holds two doubles, and an all-int list is
    # unchanged.
    test_gimple_stdout("gimple_heterogeneous_list_literal_keeps_each_slot", """\
fn main():
    var a = [1, 2.5]
    print(a)
    for y in a:
        print(y)
    var i = 0
    print(a[i])
    var j = 1
    print(a[j])
    print(len(a))
    print([1, 2.0])
    print([1, 2, 3])
    print(['a', 1])
    for e in [1, 2.5]:
        print(e)
    var f = [1, 2.5]
    print(list(f))
    print(f[:])
""", "[1, 2.5]\n1\n2.5\n1\n2.5\n2\n[1, 2.0]\n[1, 2, 3]\n['a', 1]\n"
       "1\n2.5\n[1, 2.5]\n[1, 2.5]\n")

    # A `struct.Struct` handle held in a CLASS ATTRIBUTE has no local name
    # for the codegen to have recorded the handle's format against, so its
    # unpack result had no per-slot kinds at all and a mixed format's float
    # slot came back as its raw bits on every statically-indexed read
    # (`t[1]`) — the class-attribute residue the removed doc named. Two
    # classes declaring the SAME attribute name with DIFFERENT formats is
    # the case where guessing would be wrong, so the lookup is keyed by the
    # owning type and both must come out right.
    test_gimple_stdout("gimple_struct_class_attribute_handle_format_known", """\
struct A:
    var F = struct.Struct('<if')

    def go(self):
        var t = self.F.unpack(struct.pack('<if', 1, 2.5))
        print(t)
        print(t[0])
        print(t[1])
        var p, q = self.F.unpack(struct.pack('<if', 1, 2.5))
        print(p)
        print(q)

struct B:
    var F = struct.Struct('<2f')

fn main():
    var a = A()
    a.go()
    var t = A.F.unpack(struct.pack('<if', 3, 4.5))
    print(t)
    print(t[0])
    print(t[1])
    var b = B()
    var u = b.F.unpack(struct.pack('<2f', 1.5, 2.5))
    print(u)
    print(u[0])
    print(u[1])
""", "(1, 2.5)\n1\n2.5\n1\n2.5\n(3, 4.5)\n3\n4.5\n(1.5, 2.5)\n1.5\n2.5\n")

    # The same value crossing a FUNCTION boundary. The kinds are recorded on
    # the value at runtime, so the whole-result repr was already right; the
    # read with no compile-time index additionally needs to be LOWERED as a
    # boxed read, and whether it may be is a compile-time question the
    # per-value marker cannot answer — the name the kinds were recorded
    # against died with the callee's frame. So the callee is scanned
    # whole-program before anything is lowered (the same shape as the
    # existing return-ELEMENT-type inference) and the call site reads the
    # answer back. A callee that returns a UNIFORM format is in the test on
    # purpose: it must keep the plain accessor it always had.
    test_gimple_stdout("gimple_struct_mixed_reads_survive_a_function_boundary", """\
fn make(buf: DynamicVector):
    return struct.unpack('<if', buf[0])

fn uniform(buf: DynamicVector):
    return struct.unpack('<HH', buf[0])

fn main():
    var u = make([struct.pack('<if', 7, 0.5)])
    print(u)
    print(u[0])
    print(u[1])
    for x in u:
        print(x)
    var i = 1
    print(u[i])
    print(list(u))
    var v = uniform([struct.pack('<HH', 4, 5)])
    print(v)
    print(v[0])
    print(v[1])
""", "(7, 0.5)\n7\n0.5\n7\n0.5\n0.5\n[7, 0.5]\n(4, 5)\n4\n5\n")

    # The per-slot kinds travel with the VALUE, keyed by the live list's
    # address in a runtime side table — and that table's DELETE was clearing
    # the slot outright instead of closing the probe gap, so freeing one list
    # stripped the kinds off every other live list that shared its probe
    # cluster. Heap MojoLists are 64 bytes apart (sizeof is 56, malloc's
    # size class rounds up), so a bare `addr & mask` home function put EVERY
    # kinds row in one cluster and the collision was the norm, not a
    # coincidence: `pick()` below frees its first local on return, and the
    # list it RETURNS is allocated 64 bytes later, so its repr came back
    # through the no-kinds fallback — which reads each slot with
    # mojo_list_get_int and hands a double's IEEE-754 bit pattern to
    # strlen. It segfaulted. Both halves are pinned here: the printed repr
    # and element reads (which go through mojo_list_get_boxed, so they need
    # the row), and the survival of a second, longer-lived list in the same
    # function (the direct-collision shape, without a callee boundary).
    test_gimple_stdout("gimple_kinds_survive_a_sibling_list_being_freed", """\
fn mixed(x: Float64, s: String) -> List:
    return [x, 1, s]

fn drop_one() -> List:
    var first = mixed(1.5, "aa")
    var kept = mixed(9.5, "zz")
    return kept

fn main():
    var b = drop_one()
    print(b)
    var i = 0
    print(b[i])
    var j = 1
    print(b[j])
    print(b[2] == "zz")
    var a = mixed(2.5, "yy")
    var c = mixed(3.5, "xx")
    print(a)
    print(c)
    print(list(a), list(c))
""", "[9.5, 1, 'zz']\n9.5\n1\nTrue\n[2.5, 1, 'yy']\n[3.5, 1, 'xx']\n[2.5, 1, 'yy'] [3.5, 1, 'xx']\n")

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

    # A parameter ANNOTATED `str` handed a non-string. In Python an
    # annotation is documentation, not a cast, so every line of this is
    # legal and prints what CPython prints. `char *` is this dialect's
    # string slot (`_TYPE_MAP` maps only `str`/`String` to it), so the call
    # site used to satisfy the annotation by BIT-REINTERPRETING the integer:
    # `Dialog(5)` emitted `_t3 = (void *)_t5; _t4 = (char *)_t3;` with
    # `_t5 = (int64_t)5`, and the first `mojo_print` then `strlen`ed address
    # 5 — SIGSEGV, exit -11, not even the line before it reached stdout
    # (both docs FIXED and DELETED with the fix, so this comment is the record:
    # `CODEGEN_annotated_str_param_given_an_int_segfaults`, and the same crash
    # filed a second time as
    # `CODEGEN_method_returning_self_str_field_segfaults`, whose
    # diagnosis pointed at the method's return path and was wrong — the
    # generated C for `Dialog_show` is a correct `char *` load and the fault
    # is entirely upstream, at the constructor's argument).
    #
    # Every spelling of the same mistake is here — a bare literal, a local,
    # and a value reached through a method — and the string cases are here
    # too, because the fix routes an UNTRACKED int64_t through the runtime's
    # own discriminator (`mojo_cstr_or_int_str`) rather than a cast, and that
    # must still hand a genuine boxed `char *` back as the same address.
    #
    # The two large values are the ones the discriminator gets WRONG: it is a
    # range test, so it calls every positive int64 in [2^31, 2^47) a pointer.
    # They are here because the codegen PROVABLY knows an integer literal is
    # an integer, and supplies the answer rather than asking (see
    # bugs/RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md, whose
    # dict-key spelling has its own test below).
    test_gimple_stdout("gimple_annotated_str_param_given_a_non_str", """\
class Dialog:
    def __init__(self, widgetName: str):
        self.widgetName = widgetName
    def show(self):
        return self.widgetName

def echo(s: str):
    print(s)

def main():
    a = Dialog(5)
    print(a.widgetName)
    print(a.show())
    n = 7
    echo(n)
    echo("hello")
    echo(3000000001)
    big = 1099511627776
    echo(big)
main()
""", "5\n5\n7\nhello\n3000000001\n1099511627776\n")

    # A large integer as a dict key. `mojo_boxed_is_str` — the runtime's
    # str-vs-container discriminator, and what the dict's `_kw` entry points
    # ask — is a RANGE test (`_mojo_ptr_shaped`: below 2 GiB, below 2^47), so
    # it calls every positive int64 in [2^31, 2^47) a pointer, and
    # `mojo_dict_set_int_kw(d, 3000000000, 1)` became
    # `mojo_dict_set_int(d, (char *)3000000000, 1)` — a `strcmp` of address
    # 3000000000. SIGSEGV, at -O0, -O2 and under AddressSanitizer alike.
    #
    # The fix is the codegen SUPPLYING the answer, not a better range: an
    # integer literal cannot be a pointer at any magnitude, so the call site
    # knows, and a literal or a local bound from one now renders its decimal
    # and uses the ordinary dict entry point (which re-normalises the text
    # through `_canon_int`, so it is the same integer slot). The `lambda`
    # line is the other half of the contract: a value the codegen genuinely
    # cannot type still goes through the `_kw` twin, and a string passed
    # through one must still be found.
    test_gimple_stdout("gimple_dict_key_above_2gb_is_an_integer", """\
def main():
    d = {}
    d[3000000000] = 1
    print(d[3000000000])
    k = 3000000002
    d[k] = 2
    print(d[k])
    print(3000000000 in d)
    print(1099511627776 in d)
    s = {}
    s["a"] = 7
    f = lambda q: s[q]
    print(f("a"))
    print(s["a"])
main()
""", "1\n2\nTrue\nFalse\n7\n7\n")

    # The CONSTRUCTOR half of the same cross-call struct contract
    # (the ctor-direction cross-call struct contract in `module_gen.py`'s
    # constructor observation pass). The receiver
    # here is `self.w`, whose C type comes from `__init__`'s own unannotated
    # `w`, so the only evidence anywhere is the `L(T(15))` CALL SITE — the
    # free-function pass that fixes the case above cannot see it. Before the
    # fix `w` stayed `int64_t`, the field inherited it, and `self.w.numel()`
    # hit the generic no-op stub and returned the `T *`'s own bits: a
    # pointer-sized garbage decimal, exit 0, no diagnostic.
    test_gimple_stdout("gimple_ctor_param_used_only_as_field_then_receiver", """\
class T:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

class L:
    def __init__(self, w):
        self.w = w
    def numel(self):
        return self.w.numel()

def main():
    print(L(T(15)).numel())

main()
""", "15\n")

    # The same fix reached through a FREE FUNCTION's parameter instead of
    # through a field, and with a second (`char *`) constructor argument
    # beside it, so the struct answer has to be admitted per SLOT and not
    # simply as "this constructor saw a struct somewhere".
    test_gimple_stdout("gimple_ctor_param_struct_and_scalar_slots_are_independent", """\
class T:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

class L:
    def __init__(self, w, tag):
        self.w = w
        self.tag = tag
    def numel(self):
        return self.w.numel()
    def label(self):
        return self.tag

def mk(t):
    return L(t, 'hi')

def main():
    x = mk(T(8))
    print(x.numel(), x.label())

main()
""", "8 hi\n")

    # The `self.<field>` constructor argument, resolved from the owning
    # method's struct — and the one-hop chain that needs it: `Box(self.t)`
    # inside `Holder.go` is only observable once `Holder.t` has a `T *`
    # field type, which is itself written by the same observation pass from
    # `Holder(T(4))` at the call site. So collection and application have to
    # run to a fixpoint; one pass sees `Holder.t` as the int64_t default and
    # the chain stops there.
    test_gimple_stdout("gimple_ctor_param_self_field_argument_resolves_a_chain", """\
class T:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

class Box:
    def __init__(self, w):
        self.w = w
    def numel(self):
        return self.w.numel()

class Holder:
    def __init__(self, t):
        self.t = t
    def go(self):
        return Box(self.t).numel()

def main():
    print(Holder(T(4)).go())

main()
""", "4\n")

    # A genuinely POLYMORPHIC constructor argument — `T` and `U` both passed
    # into the same slot — must stay unresolved, which is the documented rule
    # ("not unanimous over the call sites → leave it at the int64_t default").
    # What is asserted is that the widening above does not resolve such a slot
    # by picking a winner: both classes answer `0` for a method that does not
    # read the field, so a resolved `T *` would still print `0 0` here and the
    # test would pass either way — which is exactly why the receiver-reading
    # variant lives in
    # bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md
    # instead, where the two outcomes are actually distinguishable.
    test_gimple_stdout("gimple_ctor_param_polymorphic_slot_stays_unresolved", """\
class T:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

class U:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n

class L:
    def __init__(self, w):
        self.w = w
    def tag(self):
        return 0

def main():
    print(L(T(2)).tag(), L(U(2)).tag())

main()
""", "0 0\n")

    # A container SHARED ACROSS FUNCTIONS — a module global, populated by a
    # constructor and read by a different function. The mechanism is recorded
    # in `_gmi_phase17_collect_appends`' own docstring
    # (mojo/middle/module_shared.py); its bug doc is deleted. The list
    # is correct at runtime the whole way through; what is lost is the
    # compile-time knowledge of what is IN it, so `REGISTRY[0].numel()`'s
    # receiver is an `int64_t`, finds no matching user method, and hits the
    # generic no-op stub — the `T *`'s own bits as a decimal, exit 0.
    # `print(len(REGISTRY), ...)` printed `4` and the garbage in the same
    # breath, which is what makes the shape easy to miss.
    #
    # Two halves had to change for this, and each is a half on its own:
    # `_gmi_phase17_collect_appends` walked FunctionDef/If/While/For/Try/
    # With but NOT `StructDef`, so an append inside a constructor — the
    # dominant registry shape — was invisible to the whole pass.
    test_gimple_stdout("gimple_global_registry_element_type_survives_a_function_boundary", """\
REGISTRY = []

class T:
    def __init__(self, n):
        self.n = n
        REGISTRY.append(self)
    def numel(self):
        return self.n * 2

def build(k):
    T(k)

def main():
    for i in range(4):
        build(i + 1)
    print(len(REGISTRY), REGISTRY[0].numel())

main()
""", "4 2\n")

    # The same conclusion read back through a comprehension and through a
    # method that is not `numel`, so the fix is a real element type on the
    # global rather than one call site happening to work.
    test_gimple_stdout("gimple_global_registry_element_type_reaches_every_reader", """\
REG = []

class T:
    def __init__(self, n):
        self.n = n
        REG.append(self)
    def numel(self):
        return self.n * 2
    def tag(self):
        return 't'

def report():
    return [r.numel() for r in REG]

def main():
    for i in range(3):
        T(i + 1)
    print(len(REG), report(), REG[2].tag())

main()
""", "3 [2, 4, 6] t\n")

    # The CLASS-ATTRIBUTE spelling, which is a different receiver shape at
    # the append site: `T.registry.append(self)` reads as
    # `MemberExpr(obj=IdentExpr('T'), member='registry')`, so the collector's
    # bare-`IdentExpr` test rejected it and the conclusion was never reached
    # at all. Its key has to be the `_classattr_T__registry` global the
    # class-attribute registration synthesizes, which is what makes the
    # recorded answer reachable by the reader.
    test_gimple_stdout("gimple_class_attribute_registry_element_type", """\
class T:
    registry = []
    def __init__(self, n):
        self.n = n
        T.registry.append(self)
    def numel(self):
        return self.n

class U:
    registry = []
    def __init__(self, n):
        self.n = n
        U.registry.append(self)
    def numel(self):
        return self.n * 7

def main():
    T(3)
    U(4)
    print(len(T.registry), T.registry[0].numel())
    print(len(U.registry), U.registry[0].numel())

main()
""", "1 3\n1 28\n")

    # A local list has always worked (populate and read in the same
    # function), and it must keep working: it is the control that shows the
    # fix is about where the element type is RECORDED, not about the read.
    test_gimple_stdout("gimple_local_registry_element_type_unchanged", """\
class T:
    def __init__(self, n):
        self.n = n
    def numel(self):
        return self.n * 2

def main():
    reg = []
    for i in range(4):
        reg.append(T(i + 1))
    print(len(reg), reg[0].numel())

main()
""", "4 2\n")

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

    # The same class of gap one step further on: a function whose only
    # `return` is a METHOD CALL on a local it just constructed. The call
    # site was already exactly right — the right method, the right mangled
    # symbol, `char *` into a `char *` temp — but the enclosing function's
    # declared return type was `int64_t`, because return-type inference
    # types each `return` expression with `_quick_type`, whose
    # struct-receiver arm looks the receiver's C type up in `var_types`, and
    # at return-inference time that table does not yet hold this function's
    # own locals. One wrong declaration turned the value into a pointer
    # decimal by the time `print` saw it. `h` (a `repr(...)` call, which
    # returns an explicit typed pair) and `k` (a field read) were already
    # right, so the difference is the expression kind, not the method.
    # `m` and `n` are the alias and non-dunder-method forms of the same
    # case.
    test_gimple_stdout("gimple_return_type_from_a_method_call_on_a_local", """\
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "R<" + self.x + ">"
    def twice(self):
        return self.x + self.x

def g():
    p = P("a")
    return p.__repr__()

def h():
    p = P("a")
    return repr(p)

def k():
    p = P("a")
    return p.x

def m():
    p = P("a")
    q = p
    return q.__repr__()

def n():
    p = P("a")
    return p.twice()

def mk():
    return P("a")

def mk2(x):
    return P(x)

def f1():
    p = mk()
    return p.__repr__()

def f2():
    p = mk2("b")
    return p.__repr__()

print(g())
print(h())
print(k())
print(m())
print(n())
print(f1())
print(f2())
""", "R<a>\nR<a>\na\nR<a>\naa\nR<a>\nR<b>\n")

    # A user-defined `__str__`, consulted by `str()` and by `"%s" %` — a
    # SECOND, entirely separate route from the `repr()` one. Both lower to
    # `_stringify_value`, which had no dunder awareness at all: a struct
    # pointer fell to the generic `mojo_str`, i.e. the generated field dump
    # with an empty field list, which is where the bare type name `P` came
    # from. `__str__` is preferred and `__repr__` is the fallback, which is
    # CPython's own order for `str` — so `Q`, which defines only
    # `__repr__`, stringifies as its repr rather than as its type name.
    # A struct with NEITHER is deliberately not asserted here: it keeps the
    # pre-existing lowering, which prints the bare type name where CPython
    # prints `<R object at 0x...>`. That is a real, separate gap — a
    # struct-allocated local carries no runtime type tag for the field-dump
    # dispatch to find, the same missing tag as the container rows left open
    # in bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_
    # container_spellings.md — and freezing the wrong answer here would make
    # it invisible. The `%r` / `repr()` spellings are the controls:
    # unchanged by this, because CPython's fallback there is `__str__` and
    # taking it would change the repr of every struct in the tree that
    # defines `__str__` alone.
    test_gimple_stdout("gimple_user_defined_dunder_consulted_by_str_and_percent_s", """\
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "R<" + self.x + ">"
    def __str__(self):
        return "S<" + self.x + ">"

class Q:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "Q<" + self.x + ">"

p = P("a")
q = Q("b")
print(str(p))
print("%s" % p)
print(f"{p}")
print(str(q))
print("%s" % q)
print(repr(p))
print("%r" % p)
print(repr(q))
print(1)
print("x")
print([1, 2])
print({"a": 1})
""", "S<a>\nS<a>\nS<a>\nQ<b>\nQ<b>\nR<a>\nR<a>\nQ<b>\n1\nx\n[1, 2]\n{'a': 1}\n")

    # A container of structs prints its ELEMENTS through the element's own
    # `__repr__` — the container rows of
    # bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_
    # container_spellings.md, which printed a raw pointer decimal where CPython
    # prints the object (and the decimal moves run to run, so no value
    # comparison could pass).
    #
    # The mechanism: the codegen records, ON THE VALUE, how to render one
    # element (`mojo_list_set_elem_repr(t, _mojo_elem_repr_P)`), because the
    # element's static type is known where the list is built and is
    # unrecoverable later — `_mojo_dispatch_repr` needs a runtime type TAG,
    # which a struct-allocated value does not carry. The shim prefers the
    # user's `__repr__` and falls back to the generated field dump, so a struct
    # with no dunder reprs as `P(x='a')`, which is what it already printed on
    # its own.
    #
    # Every spelling here is one where the element's type IS visible at the
    # literal: a parameter, a local, a slice, a copy, a concatenation. The two
    # shapes where it is not are filed, because each needs a type recorded
    # somewhere it currently is not: an unannotated MODULE-LEVEL binding read
    # at module level (boxed into an int64_t with no type anywhere), and a
    # struct-typed FIELD inside another struct's field dump (the field's
    # semantic type is not in `struct_field_types`, so the dump formats the
    # slot as an integer). See the Status section of the bug doc.
    test_gimple_stdout("gimple_container_element_repr_uses_the_struct_dunder", """\
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "R<" + self.x + ">"

def containers(p: P):
    print(repr([p]))
    print(repr((p,)))
    print(repr([p, p]))
    print(repr([[p]]))
    print(repr([p][0:2]))
    print(repr(list([p])))
    print(repr([p] + [p]))

def main():
    containers(P("a"))
main()
""", "[R<a>]\n(R<a>,)\n[R<a>, R<a>]\n[[R<a>]]\n[R<a>]\n[R<a>]\n"
       "[R<a>, R<a>]\n")

    # §4.2a: print([True, False]) printed [1, None] -- the generic list repr
    # both formats a bool slot with %d instead of True/False AND treats a
    # False (0) slot as the None sentinel.
    test_gimple_stdout("gimple_print_bool_list", """\
print([True, False])
""", "[True, False]\n")

    # repr() of a bool printed `1`/`0` — the right VALUE, the wrong type.
    # print() was already right (`_gen_print`'s `_Bool` arm calls
    # mojo_repr_bool) and so were `%s` and `f'{x}'`, which is exactly what let
    # this survive: the obvious smoke test passes and the spellings that ship
    # are the wrong ones. `_repr_value` had no `_Bool` arm at all, so a
    # `_Bool` fell through to the int64_t one — the ordering trap being that
    # the new arm has to come before the `endswith(' *')` test.
    #
    # `%d` and `%i` are in the same test deliberately: they are RIGHT (Python
    # formats a bool as an int there), and a fix that made them print
    # True/False would pass every other assertion in this file.
    test_gimple_stdout("gimple_repr_of_a_bool_is_true_false", """\
x = 1 == 1
print(repr(x))
print(repr(x == 2))
print('%r' % (x,))
print(f'{x!r}')
print('%d' % (x,))
print('%i' % (x == 2,))
print('%s' % (x,))
print(f'{x}')
print(str(x))
""", "True\nFalse\nTrue\nTrue\n1\n0\nTrue\nTrue\nTrue\n")

    # A bool stored as a dict VALUE is a plain `int` slot by the time it is
    # stored, so the store goes through `mojo_dict_set_bool`, which tags THAT
    # one `_DictSlot.kind == 3` and the dict repr reads the tag. The tag used
    # to be a whole-DICT flag (mojo_mark_dict_bool_values, since deleted), so
    # one bool value made every OTHER value print as True/False too — the last
    # two lines here are the regression that shape caused, and they are why
    # this test has a mixed dict in it at all. `{'k': 1}` (a genuine int) is
    # here too so the tag cannot become a blanket "this dict holds 0/1".
    test_gimple_stdout("gimple_dict_of_bool_values", """\
b = True
print({'k': b})
print({'k': 1 == 1})
print({'k': 1 == 2})
print({'k': 1})
d = {}
d['a'] = b
print(d)
d['n'] = 5
print(d)
print({'ok': True, 'count': 3})
""", "{'k': True}\n{'k': True}\n{'k': False}\n{'k': 1}\n{'a': True}\n"
       "{'a': True, 'n': 5}\n{'ok': True, 'count': 3}\n")

    # A `bool`-ANNOTATED struct field. `_TYPE_MAP` maps `'bool'` to `'int'`
    # on purpose (see struct_bool_fields' docstring), so the field's lowered
    # C type is an ordinary integer and its LAYOUT carries no trace of the
    # bool-ness — every spelling below printed 1/0 while the same value
    # compared (`b.flag == True`) was right, because a comparison makes its
    # own `_Bool`. The annotation is recorded per struct
    # (`gen.struct_bool_fields`, already consulted by the generated
    # `_mojo_repr_<Sn>`) and read back by the ONE shared predicate,
    # `is_python_bool_expr`, so print / repr / str / the %-formats / the
    # f-strings / the dict store / the list literal cannot disagree about the
    # same field — which is the whole point of that predicate.
    #
    # `b.n` (an `int` field) and `%d` of the bool are in the test
    # deliberately: they are RIGHT, and a fix that made them print True/False
    # or 1 would pass every other assertion in this file.
    test_gimple_stdout("gimple_bool_annotated_struct_field", """\
class Box:
    def __init__(self, flag: bool, n: int):
        self.flag = flag
        self.n = n


b = Box(True, 5)
c = Box(False, 5)
print(b.flag)
print(c.flag)
print(repr(b.flag))
print(str(b.flag))
print('%r' % (b.flag,))
print('%s' % (b.flag,))
print('%d' % (b.flag,))
print(f'{b.flag}')
print(f'{b.flag!r}')
print(b.n)
print({'k': b.flag})
print([b.flag])
print([b.flag, c.flag])
print({'flag': b.flag, 'n': b.n})
if b.flag:
    print('then')
""", "True\nFalse\nTrue\nTrue\nTrue\nTrue\n1\nTrue\nTrue\n5\n"
       "{'k': True}\n[True]\n[True, False]\n{'flag': True, 'n': 5}\nthen\n")

    # A `bool`-ANNOTATED struct FIELD, which is the same class one level out
    # from the two tests above: for a field the bool-ness is gone before any
    # chokepoint can look at it. `_TYPE_MAP` maps `'bool'` to `'int'`, so
    # `_resolve_type('bool')` returns `int`, the struct declares `int flag`,
    # and every `_Bool` arm in print/repr/str/the dict store has nothing to
    # fire on. Nine spellings printed `1` and none said anything about it.
    # `struct_bool_fields` already existed and the struct's own generated
    # `__repr__` already consulted it, which is exactly why this survived:
    # `print(b)` said `flag=True` while `print(b.flag)` said `1`.
    #
    # Every consumer is reached through the ONE shared predicate
    # (`is_python_bool_expr`), which gained a MemberExpr arm, so this test
    # pins every spelling rather than the one that was easiest to look at.
    # The `int` field in the same struct and `b.flag + 0` are the controls
    # that a fix did not turn a bool field into something else.
    test_gimple_stdout("gimple_bool_annotated_struct_field", """\
class Box:
    def __init__(self, flag: bool, n: int):
        self.flag = flag
        self.n = n
    def get(self):
        return self.flag

def main():
    b = Box(True, 5)
    c = Box(False, 5)
    print(b.flag)
    print(repr(b.flag))
    print(b.n)
    print(c.flag)
    print('%r' % (b.flag,))
    print(f'{b.flag}')
    print(str(c.flag))
    print({'k': b.flag})
    print(b.get())
    print(repr(b.get()))
    print(b.flag + 0)
    print(b.flag == True)
main()
""", "True\nTrue\n5\nFalse\nTrue\nTrue\nFalse\n{'k': True}\n"
       "True\nTrue\n1\nTrue\n")

    # The two shapes the field case does NOT reach on its own, and the
    # controls that keep them honest. A list of bool fields needs the list
    # LITERAL's element type to be `_Bool`, because the generic list repr
    # both formats a slot as "1" and reads a False (0) slot as the None
    # sentinel -- `[1, None]`, not `[1, 0]`. A bool field read through a
    # BOUND METHOD's receiver (`other.flag` where `other` is a `self`
    # parameter) resolves the receiver's struct rather than `self`, which is
    # the second spelling `_is_python_bool_field` has to answer.
    test_gimple_stdout("gimple_bool_field_in_a_list_and_through_a_receiver", """\
class Box:
    def __init__(self, flag: bool):
        self.flag = flag
    def echo(self, other: Box):
        return other.flag
    def truthy(self):
        if self.flag:
            return 1
        return 0

def main():
    b = Box(True)
    c = Box(False)
    print([b.flag])
    print([b.flag, c.flag])
    print(b.echo(c))
    print(b.truthy())
    print(c.truthy())
main()
""", "[True]\n[True, False]\nFalse\n1\n0\n")

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

    # A `for` loop whose target is a bare 1-tuple — `for patterns, in ...:`,
    # real at c_parser/preprocessor/__init__.py:169
    # (`for patterns, in _resolve_file_values(filename, file_same.items()):`).
    # `_parse_unpack_target` cannot tell a TRAILING comma from a separator, so
    # the parser used to consume the `in` as a second target name and the whole
    # module failed to parse — `169:17: Expected KW got NAME(...)` — which
    # took every c-analyzer file whose closure reaches
    # `c_parser/preprocessor` down with it. The compiled path already
    # unpacks a one-name parenthesised for-target correctly, so restoring the
    # parse restores compiled-path/CPython parity for the shape; asserted here
    # against CPython's own output rather than a hardcoded literal for exactly
    # that reason.
    test_gimple_stdout("gimple_for_target_bare_one_tuple", """\
def main():
    for a, in [(1,), (2,), (3,)]:
        print(a)
    for b, in [('x',), ('y',)]:
        print(b)
""", "1\n2\n3\nx\ny\n")

    # The parser invariant the fix rests on: the bare trailing-comma spelling
    # and the parenthesised one produce the IDENTICAL target representation,
    # so there is exactly one shape for every downstream consumer (the
    # interpreter's `_bind_comprehension_target`, both codegen paths'
    # tuple-target machinery) to learn rather than two spellings. Asserted on
    # the AST, not on behaviour, because the two Python meanings that share
    # this spelling were a separate bug — `for (a) in b:` (parenthesised NAME,
    # no comma) shared this representation with `for (a,) in b:` — since FIXED
    # and its doc deleted, so the comment is the only record: the invariant
    # asserted here is the bare comma and the parens agree, and the paren-NAME
    # no longer does, which is `test_paren_name_vs_one_tuple_for_target_differ`
    # in test_gimple.py.
    def test_for_target_bare_one_tuple_matches_paren_ast():
        global _PASS, _FAIL
        name = "gimple_for_target_bare_one_tuple_matches_paren_ast"
        try:
            import fire_compiler as _N
            def _tgt(src):
                return _N.Parser(_N.py_tokenize(src)).parse_module()[0].target
            _bare = _tgt("for a, in b:\n    pass\n")
            _paren = _tgt("for (a,) in b:\n    pass\n")
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        if _bare == _paren:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: bare trailing comma parses to {_bare!r}, "
                  f"`for (a,) in` parses to {_paren!r}")
            _FAIL += 1

    test_for_target_bare_one_tuple_matches_paren_ast()

    # Item 8 of `CODEGEN_coro_yield_kind_unresolved_callsite` (a
    # bugs/hard doc, FIXED and DELETED with the fix, so this comment and the
    # cases below are the record): a
    # for-loop over a list PARAMETER read every element through
    # `mojo_list_get_int` whenever the argument was a list LITERAL, because
    # the cross-call container element-type contract only ever looked at an
    # argument that was a bare identifier naming a tracked local. `show(xs)`
    # was right and `show([1.5, 2.5])` -- the same call with the list written
    # in place -- printed the floats' raw IEEE-754 bit patterns
    # (4609434218613702656) and a list of strings printed pointer decimals,
    # both exit 0. Every expected value below is CPython's, checked with
    # `python3` on the identical program text.
    test_gimple_stdout("gimple_for_over_list_param_from_float_literal", """\
def show(data):
    for r in data:
        print(r)

def main():
    show([1.5, 2.5])
""", "1.5\n2.5\n")

    # The keyword spelling of the same call: a kwarg names the parameter
    # directly, so the contract reads it the same way.
    test_gimple_stdout("gimple_for_over_list_param_from_keyword_literal", """\
def show(data):
    for r in data:
        print(r)

def main():
    show(data=[1.5, 2.5])
""", "1.5\n2.5\n")

    # A string list is the case where the int64_t default is most visibly
    # wrong: a `char *` element read as an int64_t prints its address.
    test_gimple_stdout("gimple_for_over_list_param_from_str_literal", """\
def show(data):
    for r in data:
        print(r)

def main():
    show(["a", "b"])
""", "a\nb\n")

    # A list of LISTS: the inner element ctype has to reach the callee too,
    # or the outer loop yields a boxed pointer and the inner loop reads
    # garbage. (The bare-identifier form of this already worked.)
    test_gimple_stdout("gimple_for_over_nested_list_param_from_literal", """\
def show(rows):
    for row in rows:
        for cell in row:
            print(cell)

def main():
    show([[1, 2], [3, 4]])
""", "1\n2\n3\n4\n")

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

    def _compile_package_and_run(pkg_name, files, entry_relpath, timeout=60):
        """Write `files` ({relpath: src}) into a temp PACKAGE directory,
        compile `entry_relpath` with do_imports=True (single-TU inline
        path), build with gcc -fgimple, run, and return captured stdout.
        Returns (compiled_stdout, cpython_stdout) so the caller can compare
        the compiled program against the interpreter on the SAME source —
        the comparison this file's other helpers skip because their fixtures
        have no imports to run twice."""
        with tempfile.TemporaryDirectory() as wd:
            for rel, src in files.items():
                path = os.path.join(wd, pkg_name, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, 'w').write(src)
            entry = os.path.join(wd, pkg_name, entry_relpath)
            from gimple_codegen import compile_to_gimple
            c_code = compile_to_gimple(open(entry).read(),
                                       do_imports=True, filename=entry)
            # CPython, on the very same files, from the package's parent so
            # the relative import resolves the same way it must for the
            # compiled path (`python3 -m <pkg>.<entry>`).
            cp = subprocess.run(
                [sys.executable, '-m', pkg_name + '.' +
                 entry_relpath[:-len('.py')].replace('/', '.')],
                cwd=wd, capture_output=True, text=True, timeout=timeout)
            cpython_stdout = cp.stdout
        with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
            f.write(c_code)
            c_file = f.name
        exe_file = c_file.replace('.c', '.exe')
        try:
            runtime_dir = os.path.join(HERE, 'runtime')
            result = subprocess.run(
                [find_gcc(), '-fgimple', f'-I{runtime_dir}', '-o', exe_file,
                 c_file, os.path.join(HERE, 'runtime', 'fire_runtime.c')],
                capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                raise RuntimeError(f"gcc -fgimple failed: {result.stderr[:300]}")
            return run_executable_stdout(exe_file), cpython_stdout
        finally:
            for p in (c_file, exe_file):
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def test_relative_underscore_module_mangled_suffix_agrees():
        """A `from ._helper import f` (leading-dot relative import whose
        module basename starts with `_`) must give the imported free
        function ONE mangled C identifier across its declaration, its
        definition and its call site — even when the defining and importing
        modules DISAGREE about the callee's parameter types.

        The disagreement is the point, not decoration. `count_items` infers
        `items` as `MojoList *` from its own `for it in items:` body; the
        importing module's own `_signature_ctypes` snapshot of the same
        FunctionDef has no such evidence and freezes `int64_t`. The whole
        program shares `_home_def_param_types` precisely so the definer's
        committed signature — the one the emitted definition's overload
        suffix is hashed from — wins that disagreement.

        It did not, for any module whose name has BOTH a leading depth dot
        and its own leading underscore: `_local_def_pts` published the entry
        under `module_name.replace('.', '_')`, which spells `._helper` as
        `__helper`, while every importer resolves the same module as
        `_helper`. The read missed, the all-int64_t tier answered, the two
        halves of one symbol hashed different suffixes, and the build died
        at gcc with

            implicit declaration of function '__helper_count_items_2dbb98';
            did you mean '__helper_count_items_d07985'?

        — the exact shape that refused Tools/c-analyzer's
        c_parser/parser/__init__.py (`_common_set_capture_groups_37bd8e` vs
        `..._6aabcf`). Asserted on the built binary's real stdout against
        CPython's, so a future regression cannot pass by merely compiling:
        the pre-fix state does not compile at all."""
        global _PASS, _FAIL, _TIMEOUT
        name = "relative_underscore_module_mangled_suffix_agrees"
        files = {
            '__init__.py': '',
            '_helper.py': ("def count_items(items, stop):\n"
                           "    n = 0\n"
                           "    for it in items:\n"
                           "        n = n + 1\n"
                           "    return n\n"),
            'main.py': ("from ._helper import count_items\n"
                        "\n"
                        "def main():\n"
                        "    print(count_items(('a', 'b'), 0))\n"
                        "\n"
                        "main()\n"),
        }
        try:
            got, want = _compile_package_and_run(
                'uscore', files, 'main.py')
        except subprocess.TimeoutExpired as e:
            print(f"TIMEOUT {name}: {e}")
            _TIMEOUT += 1
            return
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        if want != "2\n":
            print(f"FAIL  {name}: CPython baseline is not '2\\n' "
                  f"(got {want!r}) — fixture is wrong, not the compiler")
            _FAIL += 1
            return
        if got == want:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: compiled stdout {got!r} != CPython {want!r}")
            _FAIL += 1

    test_relative_underscore_module_mangled_suffix_agrees()

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

    # The `sizeof`/`fnaddr` accessor helpers are file-scope `static`s, and every
    # module's parts land in ONE translation unit, so the sets that decide
    # whether one has already been DEFINED must be shared into every
    # `_compile_imported_module` temp_gen. They were not: each temp_gen
    # started with an empty `_c_helpers_needed` dict AND an empty
    # `_emitted_c_helpers` set, so `_c_helper_def` returned a second
    # definition of a helper the root gen had already emitted, and gcc
    # rejected the closure with `error: redefinition of
    # '_mojo_sizeof_<X>_env'`.
    #
    # Asserted on the GENERATED .ci, not on a built binary: the smallest
    # honest reproducer (two sibling modules with a same-named lifted
    # closure) ALSO collides on the lifted FUNCTION's own name, which is a
    # separate pre-existing defect (see that bug doc's "Related"), so a
    # "does it compile" assertion here would be satisfied by the wrong one of
    # the two being fixed. "Exactly one definition of each accessor" is the
    # property, and it is what sharing buys.
    def test_c_accessor_helpers_emitted_once_across_modules():
        global _PASS, _FAIL, _TIMEOUT
        name = "c_accessor_helpers_emitted_once_across_modules"
        mod = ("def pick(v):\n"
               "    f = lambda x: x + v\n"
               "    return f(1)\n")
        files = {'xhelp_a.py': mod, 'xhelp_b.py': mod,
                 'xhelp_main.py': "import xhelp_a\nimport xhelp_b\n"}
        try:
            with tempfile.TemporaryDirectory() as wd:
                for fn, src in files.items():
                    open(os.path.join(wd, fn), 'w').write(src)
                ep = os.path.join(wd, 'xhelp_main.py')
                from gimple_codegen import compile_to_gimple
                c_code = compile_to_gimple(files['xhelp_main.py'],
                                           do_imports=True, filename=ep)
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        sz = [ln for ln in c_code.splitlines()
              if ln.startswith('static int64_t _mojo_sizeof_')]
        fa = [ln for ln in c_code.splitlines()
              if ln.startswith('static void * _mojo_fnaddr_')]
        if len(sz) == 1 and len(fa) == 1:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected exactly one definition of each "
                  f"sizeof/fnaddr accessor across the closure, got "
                  f"{len(sz)} sizeof and {len(fa)} fnaddr: {sz + fa}")
            _FAIL += 1

    test_c_accessor_helpers_emitted_once_across_modules()

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

    # bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md,
    # the part that is fixable without the type-inference project it is
    # parked on: an iterator struct reached through `from mod import Struct`
    # composes its protocol methods' C names with a hand-written
    # `{Struct}___{method}__` f-string instead of `gen._struct_method_csym`,
    # the tree's ONE composer — so the home-module qualifier was missing and
    # the call went to a symbol nothing defines.
    #
    # The failure mode is worse than a link error. gcc's
    # -Wimplicit-function-declaration fallback types the undeclared call as
    # returning `int`, so `It___iter__(It *)` became an `int` and the `for`
    # lowering assigned that int to an `It *`:
    #
    #   implicit declaration of function 'It___iter__'; did you mean 'itmod_It___iter__'?
    #   assignment to 'It *' from 'int' makes pointer from integer without a cast
    #
    # and `next(obj)`'s `{Struct}___next__` had the identical defect.
    #
    # No CPython comparison here, deliberately: `__has_next__` is a Mojo-only
    # protocol (CPython has no such method and would call `__next__` until it
    # raises), so CPython cannot be the oracle for this fixture — running it
    # loops forever. The expectation is hand-written and the assertion is
    # the built binary's REAL stdout, plus a gcc run that must be clean
    # (pre-fix it does not compile at all).
    def test_cross_module_iterator_struct_protocol_symbols():
        global _PASS, _FAIL, _TIMEOUT
        name = "cross_module_iterator_struct_protocol_symbols"
        defn = ("class It:\n"
                "    def __init__(self):\n"
                "        self.n = 0\n"
                "    def __iter__(self):\n"
                "        return self\n"
                "    def __has_next__(self) -> Bool:\n"
                "        return self.n < 3\n"
                "    def __next__(self) -> Int:\n"
                "        self.n = self.n + 1\n"
                "        return self.n\n"
                "\n"
                "def make() -> It:\n"
                "    return It()\n")
        use = ("from xmoditer_defn import make, It\n"
               "\n"
               "def main():\n"
               "    d = make()\n"
               "    print(next(d))\n"
               "    for x in d:\n"
               "        print(x)\n"
               "    e = It()\n"
               "    print(next(e))\n"
               "\n"
               "main()\n")
        try:
            out = _compile_two_files_do_imports_and_run(
                'xmoditer_defn.py', defn, 'xmoditer_use.py', use)
        except subprocess.TimeoutExpired as e:
            print(f"TIMEOUT {name}: {e}")
            _TIMEOUT += 1
            return
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        # next(d) -> 1 (n becomes 1); the `for` then yields n=2,3 and stops
        # at __has_next__ (n<3); next(e) on a fresh It -> 1.
        if out == "1\n2\n3\n1\n":
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected '1\\n2\\n3\\n1\\n', got {out!r}")
            _FAIL += 1

    test_cross_module_iterator_struct_protocol_symbols()

    # bugs/CODEGEN_unannotated_init_param_field_type_int64_residue.md (deleted
    # with that fix): the cross-module constructor evidence above types a PARAM,
    # but the `_xmod_ctor_field_hints` merge applied it to the FIELD whose name
    # MATCHES the param. So a constructor that stores one param in two fields —
    # `self.s = s` and `self.n = s` — typed only `self.s`, and `b.n` read back
    # as a heap address: the same `char *` stored into an `int64_t` slot,
    # silently wrong, exit 0, and ASLR-varying so no value comparison could ever
    # pass. The identical class in ONE module was already right, which is what
    # says the rule (type the param, then every field assigned from it) rather
    # than "cross-module is hard".
    #
    # Both spellings are in one program because the fix is exactly "the second
    # field types like the first", and CPython is run on the same source so the
    # expected text is anchored rather than recorded.
    def _test_cross_module_ctor_param_types_every_field():
        global _PASS, _FAIL, _TIMEOUT
        name = "cross_module_ctor_param_types_every_field"
        defn = ("class Dialog:\n"
                "    def __init__(self, s):\n"
                "        self.s = s\n"
                "        self.n = s\n"
                "\n"
                "class Pair:\n"
                "    def __init__(self, tag):\n"
                "        self.first = tag\n"
                "        self.second = tag\n"
                "        self.of = [tag]\n")
        use = ("import xmodctor3_defn\n"
               "\n"
               "def main():\n"
               "    b = xmodctor3_defn.Dialog(\"hi\")\n"
               "    print(b.s)\n"
               "    print(b.n)\n"
               "    p = xmodctor3_defn.Pair(\"t\")\n"
               "    print(p.first)\n"
               "    print(p.second)\n"
               "    print(len(p.of))\n"
               "\n"
               "main()\n")
        try:
            out = _compile_two_files_do_imports_and_run(
                'xmodctor3_defn.py', defn, 'xmodctor3_use.py', use)
        except subprocess.TimeoutExpired as e:
            print(f"TIMEOUT {name}: {e}")
            _TIMEOUT += 1
            return
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        # `self.of = [tag]` is a list OF the param, not the param: it must stay
        # a list, which is why this asserts its length rather than its contents.
        want = "hi\nhi\nt\nt\n1\n"
        if out == want:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: expected {want!r}, got {out!r}")
            _FAIL += 1
    _test_cross_module_ctor_param_types_every_field()
    # bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md:
    # two REAL classes sharing a bare name across two modules. The single
    # string this codegen used as a struct's C identity was the bare
    # `StructDef.name`, so whichever module was processed first owned the
    # field table and the second one's `self.<field>` accesses, field types
    # and `__init__` call sites all resolved against the winner's. The
    # helpers below compile 2 or 3 sibling files with do_imports=True, run
    # the result, AND run the same source under CPython, and require the two
    # stdouts to agree — so every assertion here is anchored to what Python
    # actually answers, never to a value this compiler happens to produce.
    def _compile_n_files_and_run(files: dict, entry: str, timeout=60,
                                 extra_runtime=()):
        """Write `files` ({name: source}), compile `entry` with
        do_imports=True (the single-TU inline path), build with gcc -fgimple,
        run, return (compiled_stdout, cpython_stdout, emitted_c). The emitted
        C is handed back because a compile that SUCCEEDS can still be wrong
        about its own shape, and the string-pool case below is one: what it
        emits more than once is invisible to a zero exit code.

        `extra_runtime` names more runtime translation units to link beside
        `fire_runtime.c` — the coroutine set, for a fixture whose sibling
        module yields. Without it such a program emits calls to
        `___mojo_coro_yield_i` / `___mojo_gen_arg` and fails to LINK, which
        says nothing about the shape under test. Raises on any failure with the
        stage that failed in the message."""
        with tempfile.TemporaryDirectory() as wd:
            for name, src in files.items():
                open(os.path.join(wd, name), 'w').write(src)
            ep = os.path.join(wd, entry)
            from gimple_codegen import compile_to_gimple
            c_code = compile_to_gimple(files[entry], do_imports=True,
                                       filename=ep)
            # CPython's own answer for the identical program text, so the
            # expectation is never a hardcoded string this repo chose. Taken
            # INSIDE the `with`, while the source files still exist.
            cp = subprocess.run([sys.executable, ep], capture_output=True,
                                text=True, timeout=timeout, cwd=wd)
            cp_out = cp.stdout
        with tempfile.NamedTemporaryFile(mode='w', suffix='.c',
                                         delete=False) as f:
            f.write(c_code)
            c_file = f.name
        exe_file = c_file.replace('.c', '.exe')
        try:
            runtime_dir = os.path.join(HERE, 'runtime')
            result = subprocess.run(
                [find_gcc(), '-fgimple', f'-I{runtime_dir}', '-o', exe_file,
                 c_file, os.path.join(runtime_dir, 'fire_runtime.c')]
                + list(extra_runtime),
                capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                raise RuntimeError(f"gcc -fgimple failed: {result.stderr[:400]}")
            return run_executable_stdout(exe_file), cp_out, c_code
        finally:
            for p in (c_file, exe_file):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def _check_agrees_with_cpython(name, files, entry, timeout=60):
        """Run `files` both ways; PASS only if compiled == CPython."""
        global _PASS, _FAIL, _TIMEOUT
        try:
            got, want, _c = _compile_n_files_and_run(files, entry, timeout)
        except subprocess.TimeoutExpired as e:
            print(f"TIMEOUT {name}: {e}")
            _TIMEOUT += 1
            return
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        if got == want:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: compiled {got!r} != CPython {want!r}")
            _FAIL += 1

    # A comprehension's `for` target is a NEW binding in the comprehension's own
    # scope, so it cannot reuse the enclosing function's C variable for that
    # name. Every comprehension whose iterable lowers to a `MojoList *` goes
    # through `_compr_list_loop` (whatever its result kind), and that was the
    # one comprehension loop helper NOT passing `_declare_var(..., force=True)`
    # — so the `char *` element was routed through an `(int64_t)` temp into the
    # existing `struct Tok *` variable and gcc refused the whole program:
    #
    #   u.py:10:5: error: assignment to 'Tok *' from 'int64_t' makes pointer
    #   from integer without a cast [-Wint-conversion]
    #
    # This was filed as a doc whose own next step was "reduce to a user-level
    # reproducer", having failed to find one: its negative results (a struct
    # VALUE local, an int64_t local, a `MojoList *` local, a `String` local, a
    # dict local) all came out correct and the shape was reported as narrower
    # than "shadows a struct pointer". It is not: this is that reproducer, six
    # lines of plain Python, because a `class` lowers to a struct and so the
    # fixture is something CPython can run and be the oracle for. Neither the
    # loop-assigned local nor the `if`-nested `return` in the original report
    # is needed. Both the compile and the values are asserted: the helper
    # raises on a gcc failure, so before the fix this case failed at the
    # compile and not on an answer.
    #
    # The second row is the same fix's other half. A comprehension's target
    # does not outlive the comprehension, so the enclosing binding has to come
    # back — `a = [t for t in names]` followed by `print(t.k)` must read the
    # OUTER `t`, not the comprehension's last element. It is printed rather
    # than returned on purpose: a heterogeneous list bound from a call result
    # reads its elements back through the wrong accessor, which is its own
    # filed bug (CODEGEN_list_element_read_defaults_to_str_across_a_call.md)
    # and would otherwise be what made this case red.
    _check_agrees_with_cpython("comprehension_target_shadows_struct_local", {
        'compr_shadow.py': "class Tok:\n"
                           "    def __init__(self, k):\n"
                           "        self.k = k\n"
                           "\n"
                           "def peek(i):\n"
                           "    return Tok(i)\n"
                           "\n"
                           "def f(names):\n"
                           "    t = peek(0)\n"
                           "    return [t for t in names]\n"
                           "\n"
                           "def g(names):\n"
                           "    t = peek(3)\n"
                           "    a = [t for t in names]\n"
                           "    print(t.k)\n"
                           "    return a\n"
                           "\n"
                           "def main():\n"
                           "    r = f(['aa', 'bb'])\n"
                           "    print(r[0])\n"
                           "    print(r[1])\n"
                           "    s = g(['cc'])\n"
                           "    print(s[0])\n"
                           "main()\n",
    }, 'compr_shadow.py')

    # The tuple-target half of the same comprehension target: `[(a, b) for a,
    # b in pairs]` binds BOTH names, so both must be their own bindings (and
    # both must come back afterwards). A `char *` slot against an enclosing
    # struct-pointer slot of the same name was the same int64_t-into-pointer
    # refusal as the single-target row.
    _check_agrees_with_cpython("comprehension_tuple_target_shadows_struct_local", {
        'compr_shadow2.py': "class Tok:\n"
                            "    def __init__(self, k):\n"
                            "        self.k = k\n"
                            "\n"
                            "def f(names):\n"
                            "    a = Tok(7)\n"
                            "    b = Tok(8)\n"
                            "    return [a for a, b in names]\n"
                            "\n"
                            "def main():\n"
                            "    r = f([['p', 'q'], ['r', 's']])\n"
                            "    print(r[0])\n"
                            "    print(r[1])\n"
                            "main()\n",
    }, 'compr_shadow2.py')

    # An imported module's string-literal pool. Its doc
    # (`CODEGEN_inline_import_string_pool_name_collision`) is FIXED and DELETED,
    # so this comment is the record of what it reported and what is actually
    # there.
    #
    # It reported a gcc `redefinition of 'char* _slit_10000'` from an inline
    # compile of a package whose sibling yields strings. Re-measured on this
    # tree, that cannot happen, for two independent reasons: the pool is SHARED
    # across every gen in the closure (`temp_gen._str_pool = gen._str_pool` in
    # `_compile_imported_module`), so two modules cannot mint the same `_slit_N`,
    # and only the ROOT emits definitions, so there is one of those per name at
    # most. And the shape the doc quoted — `static char * x;` at file scope
    # followed by `static char * x = "...";` — is a tentative definition
    # followed by the real one, which C allows (checked: `gcc -c` on exactly
    # that file, and on the definition-first order too).
    #
    # What IS there, and was the doc's step 1 half right about, is that every
    # imported module emits a pool block of its own in the DECLARATION form
    # listing the WHOLE shared pool — so each module re-declared every name
    # interned before it, one redundant line per name per module, quadratic in
    # the imported-module count, in every `.ci` this backend writes. Legal C,
    # invisible to any exit code, and dropped now: `GimpleGen._str_pool_declared`
    # is shared the way `_regex_progs_defined` already is (the same job for the
    # same reason), so a name is declared once per translation unit.
    #
    # Two assertions, because they are different claims. The emitted C must
    # declare each pool name exactly once, whatever the module count — and the
    # program must still print what CPython prints for the identical text, which
    # is the part that would catch a filter that dropped a declaration some
    # module's code needed (`gcc` would say so, but only for the modules this
    # fixture happens to reach).
    #
    # The fixture is the doc's own program — a string-yielding sibling consumed
    # with `next()` and then a `for`, the shape its next step asked a
    # regression for — plus two more string-bearing siblings, so the pool is
    # large enough for the duplication to be unmissable (before the fix this
    # program emitted 13 names' worth of duplicate declarations).
    _RUNTIME_DIR = os.path.join(HERE, 'runtime')

    def _check_string_pool_declared_once(name, files, entry, timeout=60):
        global _PASS, _FAIL, _TIMEOUT
        # The fixture's sibling is a generator, so the image needs the
        # coroutine runtime; `test_gimple_generator_runner.py` names the set
        # (fire_coro.c / fire_coro_gen.c / fire_async_sched.c and the
        # stack-switch context, which is an assembly file on arm64 and C
        # elsewhere).
        _coro_ctx = os.path.join(
            _RUNTIME_DIR, 'fire_coro_ctx_aarch64.S'
            if platform.machine().lower() in ('arm64', 'aarch64')
            else 'fire_coro_ctx_generic.c')
        extra_runtime = [os.path.join(_RUNTIME_DIR, f) for f in
                         ('fire_coro.c', 'fire_coro_gen.c', 'fire_async_sched.c')]
        extra_runtime.append(_coro_ctx)
        try:
            got, want, c_code = _compile_n_files_and_run(files, entry, timeout,
                                                          extra_runtime)
        except subprocess.TimeoutExpired as e:
            print(f"TIMEOUT {name}: {e}")
            _TIMEOUT += 1
            return
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        decls = re.findall(r'^static char \* (_slit_\d+);', c_code, re.M)
        repeated = sorted({d for d in decls if decls.count(d) > 1})
        if repeated:
            print(f"FAIL  {name}: the emitted C declares {len(repeated)} pool "
                  f"name(s) more than once ({repeated[:6]}…) — each imported "
                  f"module emitted a declaration block for the whole shared "
                  f"pool")
            _FAIL += 1
            return
        if got != want:
            print(f"FAIL  {name}: compiled {got!r} != CPython {want!r}")
            _FAIL += 1
            return
        print(f"PASS  {name}  ({len(set(decls))} pool names, each declared "
              f"once)")
        _PASS += 1

    #
    # Every parameter here is ANNOTATED, and that is not decoration: an
    # unannotated parameter of an IMPORTED function is typed from its call
    # sites, and a call site spelled `mod.f(...)` is invisible to the pass that
    # collects them, so such a parameter falls back to `int64_t` and `len(x)`
    # on it reads a list header. Measured, pre-existing, and filed as
    # bugs/CODEGEN_module_boundary_carries_no_value_types.md — the same reason
    # this fixture has no cross-module `yield` either. This test is about the
    # shape of the emitted C; a second defect must not be what makes it red.
    _check_string_pool_declared_once("imported_string_pool_declared_once", {
        'slitpool_rows.py': "def keep(line: str) -> str:\n"
                            "    return line.partition('#')[0]\n",
        'slitpool_words.py': "NAMES = ['alpha', 'beta', 'gamma', 'delta']\n"
                             "def shout(word: str) -> str:\n"
                             "    return word.upper() + '!'\n",
        'slitpool_gaps.py': "SEPS = (',', ';', '\\t')\n"
                            "def width(text: str) -> int:\n"
                            "    return len(text) * 2\n",
        'slitpool_main.py': "import slitpool_rows\n"
                            "import slitpool_words\n"
                            "import slitpool_gaps\n"
                            "def main():\n"
                            "    print(slitpool_rows.keep('a  # x'))\n"
                            "    print(slitpool_words.shout(slitpool_words.NAMES[2]))\n"
                            "    print(slitpool_gaps.width(slitpool_gaps.SEPS[1]))\n"
                            "    for name in slitpool_words.NAMES:\n"
                            "        print(name)\n"
                            "main()\n",
    }, 'slitpool_main.py')

    # The two shapes the bug doc calls out as the LIVE residues, both
    # re-measured on this tree before the fix: (a) a `str` field sharing a
    # NAME with the winner's `int64_t` field was stored as a raw pointer
    # into the winner's int slot, so reading it back printed a heap address
    # (ASLR-varying, exit 0, no diagnostic) where CPython printed the
    # string; (b) a 0-arg `mod_b.Dialog()` called the winner's 1-arg
    # `__init__`, a hard gcc "too few arguments" compile error.
    _check_agrees_with_cpython("same_bare_name_struct_shared_field_cname", {
        'colln_mod_a.py': "class Dialog:\n"
                          "    def __init__(self, n):\n"
                          "        self.n = n\n",
        'colln_mod_b.py': "class Dialog:\n"
                          "    def __init__(self, unused):\n"
                          "        self.n = 'hello'\n",
        'colln_main.py': "import colln_mod_a, colln_mod_b\n"
                         "def main():\n"
                         "    a = colln_mod_a.Dialog(5)\n"
                         "    b = colln_mod_b.Dialog(0)\n"
                         "    print(a.n)\n"
                         "    print(b.n)\n"
                         "main()\n",
    }, 'colln_main.py')

    _check_agrees_with_cpython("same_bare_name_struct_ctor_arity", {
        'colln2_mod_a.py': "class Dialog:\n"
                           "    def __init__(self, n):\n"
                           "        self.n = n\n",
        'colln2_mod_b.py': "class Dialog:\n"
                           "    def __init__(self):\n"
                           "        self.n = 'hello'\n",
        'colln2_main.py': "import colln2_mod_a, colln2_mod_b\n"
                          "def main():\n"
                          "    a = colln2_mod_a.Dialog(5)\n"
                          "    b = colln2_mod_b.Dialog()\n"
                          "    print(a.n)\n"
                          "    print(b.n)\n"
                          "main()\n",
    }, 'colln2_main.py')

    # The doc's §3 shape: the two classes share NO field name, so before the
    # fix the loser's access degraded to a runtime AttributeError rather
    # than a wrong value. Method dispatch has to reach the right class too:
    # both `show` methods are same-named, and the loser's call site used to
    # resolve to the winner's body.
    _check_agrees_with_cpython("same_bare_name_struct_methods_and_fields", {
        'colln3_mod_a.py': "class Dialog:\n"
                           "    def __init__(self, widgetName: str):\n"
                           "        self.widgetName = widgetName\n"
                           "    def show(self):\n"
                           "        return self.widgetName\n",
        'colln3_mod_b.py': "class Dialog:\n"
                           "    def __init__(self, result: str):\n"
                           "        self.result = result\n"
                           "    def show(self):\n"
                           "        return self.result\n",
        'colln3_main.py': "import colln3_mod_a, colln3_mod_b\n"
                          "def main():\n"
                          "    x = colln3_mod_a.Dialog('a')\n"
                          "    y = colln3_mod_b.Dialog('b')\n"
                          "    print(x.widgetName)\n"
                          "    print(y.result)\n"
                          "    print(x.show())\n"
                          "    print(y.show())\n"
                          "main()\n",
    }, 'colln3_main.py')

    # A `from mod import Dialog as X` binding must not change which class a
    # module-qualified construction picks, and the two classes must stay
    # independent when BOTH are constructed in one program (the shape where
    # a single shared field table is most visible).
    _check_agrees_with_cpython("same_bare_name_struct_from_import_alias", {
        'colln4_mod_a.py': "class Dialog:\n"
                           "    def __init__(self, n):\n"
                           "        self.n = n\n",
        'colln4_mod_b.py': "class Dialog:\n"
                           "    def __init__(self, s: str):\n"
                           "        self.s = s\n"
                           "        self.n = 42\n",
        'colln4_main.py': "from colln4_mod_a import Dialog\n"
                          "import colln4_mod_b\n"
                          "def main():\n"
                          "    a = Dialog(3)\n"
                          "    b = colln4_mod_b.Dialog('hi')\n"
                          "    print(a.n)\n"
                          "    print(b.s)\n"
                          "    print(b.n)\n"
                          "main()\n",
    }, 'colln4_main.py')

    # `from b import K` at MODULE level, with `K` read from a function body
    # in the importing module: the value is b's, so the read is
    # `_b_globals.K`, and before the fix it was `_root_globals.K` — a field
    # the importing module's own `<module>_toplev` never declares, so gcc
    # refused the whole program ("'struct _root_toplev' has no member named
    # 'K'"). The self-host closure had 26 such names across 15 modules
    # (bugs/CODEGEN_module_toplevel_undefined_in_selfhost.md's 58-error
    # family); the qualified `b.K` spelling of the same value was already
    # correct, so this is the bare-name half of that pair.
    _check_agrees_with_cpython("imported_module_constant_reads_the_owners_field", {
        'fgi_b.py': "K = 'abc'\n\ndef f():\n    return 1\n",
        'fgi_a.py': "from fgi_b import K\n\ndef main():\n    print(K)\nmain()\n",
    }, 'fgi_a.py')

    # A container global crosses the boundary the same way, and the read has
    # to take its ELEMENT type from the owner's field triple rather than from
    # the importing module's own (empty) overlay — a bare int64_t address for
    # the list when it did not.
    _check_agrees_with_cpython("imported_module_list_constant_keeps_its_elements", {
        'fgj_b.py': "L = [1, 2, 3]\n",
        'fgj_a.py': "from fgj_b import L\n\ndef main():\n    print(L)\n    print(len(L))\nmain()\n",
    }, 'fgj_a.py')

    # `from b import N as J`: the LOCAL spelling is `J` and the owner's FIELD
    # is still `N`, so both halves of the binding have to be tracked — a
    # single "local name == field name" shortcut answers here.
    _check_agrees_with_cpython("imported_module_constant_alias_reads_the_owners_field", {
        'fgk_b.py': "N = 7\n",
        'fgk_a.py': "from fgk_b import N as J\n\ndef main():\n    print(J)\nmain()\n",
    }, 'fgk_a.py')

    # The two rows that must NOT be re-routed, i.e. the gates
    # `_gmi_scan_imported_global_homes` exists to enforce. A module-level
    # `N = ...` rebinds the name in THIS module's namespace (Python
    # semantics), so the bare read afterwards is this module's own field; and
    # a function-local `N` shadows the import outright. Both printed the
    # imported side's value when the routing was unconditional.
    _check_agrees_with_cpython("own_module_global_beats_the_imported_homonym", {
        'fgl_b.py': "N = 'b-side'\n",
        'fgl_a.py': "from fgl_b import N\nN = 'a-side'\n\ndef main():\n    print(N)\nmain()\n",
    }, 'fgl_a.py')
    _check_agrees_with_cpython("local_beats_the_imported_module_global", {
        'fgm_b.py': "N = 'b-side'\n",
        'fgm_a.py': "from fgm_b import N\n\ndef main():\n    N = 'local'\n    print(N)\nmain()\n",
    }, 'fgm_a.py')

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
