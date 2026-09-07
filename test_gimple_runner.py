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
RUNTIME_HDR = os.path.join(HERE, 'runtime', 'mojo_runtime.h')

_PASS = 0
_FAIL = 0


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
        result = subprocess.run(
            [find_gcc(), '-fgimple',
             f'-I{runtime_dir}',
             '-o', exe_file, c_file,
             os.path.join(runtime_dir, 'mojo_runtime.c')],
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


def run_executable_stdout(exe_path: str) -> str:
    """Execute the program and return its captured stdout, decoded."""
    result = subprocess.run(
        [exe_path],
        capture_output=True,
        timeout=10
    )
    return result.stdout.decode('utf-8', errors='replace')


def test_gimple_execution(name: str, mojo_src: str, expected_return: int = 0):
    """Test that mojo code compiles to GIMPLE and executes with expected return code."""
    global _PASS, _FAIL
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
    global _PASS, _FAIL
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
""", "11\n101\n42\nhello\neq\ncontains\n1116\n68656c6c6f20776f726c64\n1\n2\nis bytes\nhello world!\n")

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
""", "1\n1\n[b'a', b'b', b'c']\nb'a_b_c'\nb'hi'\nb'ABC'\n2\n2\n4445414442454546\nhello\nb'x,y'\n")

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
""", "1\n1\n1\n1\n1\n")

    test_gimple_stdout("gimple_bytes_param_inferred_from_body", """\
fn dec(data) -> String:
    return data.decode('utf-8')
fn main():
    print(dec(b'hello'))
""", "hello\n")

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
    # bugs/hard/CODEGEN_struct_module.md — Stage 1 (module-level fns).
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
    # a forward iteration -> materialised as a list (see
    # _seed_genexp_list_narrowing). bugs/COMPILE_FAIL_zipfile___init__.md
    # blocker 3.
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

    # Genexp local consumed TWICE: narrowing must NOT fire; the existing
    # materialise-unconditionally behaviour still applies (both reads see
    # the same list), never a silent-wrong lazy/empty second pass.
    test_gimple_stdout("gimple_genexp_local_consumed_twice", """\
fn main():
    g = (x * 2 for x in [1, 2, 3])
    print(sum(x for x in g))
    print(sum(x for x in g))
""", "12\n12\n")

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
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    sys.exit(0 if _FAIL == 0 else 1)


if __name__ == '__main__':
    main()
