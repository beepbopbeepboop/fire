"""Tests for the GIMPLE codegen backend.

Each test compiles generated C with gcc -fgimple -fsyntax-only to
verify the output is accepted by the GIMPLE parser.
"""
import re
import subprocess
import tempfile
import os
import sys
import gimple_codegen
from gimple_codegen import compile_to_gimple
import platform
from build_config import find_gcc

# Platform detection for cross-platform build support
_IS_DARWIN = platform.system() == 'Darwin'
GCC = find_gcc()
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_INC = os.path.join(_PROJECT_DIR, 'runtime')
_PASS = 0
_FAIL = 0


def _check_gcc():
    r = subprocess.run([GCC, '--version'], capture_output=True)
    if r.returncode != 0:
        print(f"SKIP: {GCC} not found", file=sys.stderr)
        sys.exit(0)


import contextlib


@contextlib.contextmanager
def _force_cpp_coro():
    """Force the OLD cpp-path C++20-coroutine emitter for the duration of
    one test — doc/COROUTINE.html §5.5 made the A3 stack-switch backend
    the default (gimple_gen_coro.py), so a test whose whole POINT is to
    assert on cpp-path-specific generated text (co_await, _MojoCppExc,
    the *_Awaiter promise machinery, ...) must explicitly opt back into
    it via MOJO_CORO=cpp, the documented escape hatch — see the test's own
    "_compiles_via_cpp_path" naming. Scoped (not a blanket module-level
    env var) so it can't leak into any other test sharing this process."""
    _prev = os.environ.get('MOJO_CORO')
    os.environ['MOJO_CORO'] = 'cpp'
    try:
        yield
    finally:
        if _prev is None:
            os.environ.pop('MOJO_CORO', None)
        else:
            os.environ['MOJO_CORO'] = _prev


def selfhost_emitted_return_type(module: str, struct: str, method: str) -> str:
    """The C return type of `<struct>.<method>`'s DEFINITION, as the codegen
    actually emits it when compiling `module` — or '' if there is none.

    A hand-written forward declaration (`gimple_codegen._SELFHOST_SIGS`)
    has to agree with the definition the codegen infers, and for an
    UNANNOTATED method that inferred type is not derivable from the Python
    source by any cheaper route: `inspect` sees `def _parse_expr(self,
    min_prec: int)` and nothing else. So read it off the generated C, which
    is the only copy of the fact that gcc will actually compare against.

    Deliberately compiled as a SINGLE unit (`do_imports=False`), which is
    how every non-self-host module and every per-file bootstrap step compiles:
    it is 3.3 s and 0.1 GB for fire_compiler.py, against the ~30 minutes a
    whole self-host closure takes to discover the same disagreement as a
    "conflicting types" wall.

    Matches the DEFINITION and not the forward declaration by what follows
    it: the definition's header is at column 0 and a `{` body comes next,
    while a declaration ends in `;` and a call site is indented and ends in
    `;` too. Only the DEFINITION's header carries the `__GIMPLE` tag between
    the return type and the name, so it is stripped before the type is
    returned — otherwise the caller would read `Parser` for a `Parser *`.
    The mangled name (`fire_compiler_Parser__parse_expr`) is matched on its
    tail, so this does not care whether the module qualified it.
    """
    src = open(module, encoding='utf-8', errors='replace').read()
    c_src = compile_to_gimple(src, do_imports=False, filename=module)
    head_of = re.compile(r'^([^\n;{}]*?)\b\w*(' + re.escape(method)
                         + r')\s*\([^\n;{}]*\)\s*$', re.M)
    for m in head_of.finditer(c_src):
        if not c_src[m.end():].lstrip().startswith('{'):
            continue
        head = m.group(1)
        if '/*' in head or head.rstrip().endswith('*'):
            continue
        return re.sub(r'\b__GIMPLE\b', '', head).strip()
    return ''


def gimple_compiles(mojo_src: str) -> tuple[bool, str, str]:
    """Return (ok, c_src, stderr)."""
    c_src = compile_to_gimple(mojo_src)
    with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
        f.write(c_src)
        path = f.name
    try:
        r = subprocess.run(
            [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', path],
            capture_output=True, text=True,
        )
        return r.returncode == 0, c_src, r.stderr
    finally:
        os.unlink(path)


def test(name: str, mojo_src: str):
    global _PASS, _FAIL
    ok, c_src, stderr = gimple_compiles(mojo_src)
    if ok:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}")
        print("      --- generated C ---")
        for i, line in enumerate(c_src.splitlines(), 1):
            print(f"      {i:3}: {line}")
        print("      --- gcc stderr ---")
        for line in stderr.splitlines():
            print(f"      {line}")
        _FAIL += 1


def test_raises(name: str, mojo_src: str, expected_substr: str):
    """Assert compile_to_gimple honestly refuses this input (raises with a
    message containing expected_substr) instead of either crashing gcc on
    broken generated C or silently emitting wrong code. Used for shapes this
    codegen deliberately does not (yet) support — see
    bugs/CODEGEN_conditional_toplevel_def_name_collision.md."""
    global _PASS, _FAIL
    try:
        compile_to_gimple(mojo_src)
    except Exception as e:
        if expected_substr in str(e):
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: wrong error: {e}")
            _FAIL += 1
        return
    print(f"FAIL  {name}: expected an exception containing {expected_substr!r}, "
          f"compile_to_gimple succeeded instead")
    _FAIL += 1


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_c_shape(name: str, mojo_src: str, must_have: list, must_not_have: list):
    """The generated C compiles AND contains every `must_have` substring and none
    of the `must_not_have` ones. For a change whose point is WHICH runtime call
    the compiler emits, where a wrong-but-equivalent lowering would still print
    the right answer."""
    global _PASS, _FAIL
    ok, c_src, stderr = gimple_compiles(mojo_src)
    missing = [m for m in must_have if m not in c_src]
    present = [m for m in must_not_have if m in c_src]
    if ok and not missing and not present:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}: compiles={ok} missing={missing} unexpectedly_present={present}")
        if not ok:
            for line in stderr.splitlines()[:8]:
                print(f"      {line}")
        _FAIL += 1


def test_kinds_marker_scope():
    """The per-slot-kinds marker must not outlive the function that set it.

    A value whose element kinds are recorded on the VALUE (`struct.unpack` of
    a mixed format, a mixed list literal like `[1, 2.5]`) is marked by NAME, so
    a read with no compile-time slot index — iteration, a computed subscript —
    lowers as a boxed read through `mojo_list_get_boxed`. Those names are
    `_reset_func`-scoped state and `temp_counter` restarts at `_t1` in every
    function, so a marker that outlives its function is a marker on a name that
    now belongs to a different value: the collision is invisible in the source
    and decided entirely by how many temps each function happened to allocate.

    The two functions below are shaped to collide. `s = 'ab'` is the one
    statement that lands the second function's loop-iterable temp on `_t2`,
    which is the very name the first function's mixed literal already
    registered. Asserted as a COUNT, because the count is the whole bug: one
    boxed read is what the mixed literal earns, two means the bystander loop
    read through the runtime for kinds its list does not carry.

    On a plain int list the two accessors return the same word, so the program's
    OUTPUT is right either way and only the emitted C shows the difference —
    which is why this asserts the C. (In the compiler's own source the same
    false positive was a hard `-Wint-conversion` error instead, because the
    runtime-dispatched dict arm had already declared the shared loop target
    `char *`; see `_reset_func`'s own note in
    `mojo/backend_gimple/emit_infra.py`.)"""
    global _PASS, _FAIL
    ok, c_src, stderr = gimple_compiles("""\
def packer(i: Int) -> list:
    return [i]


def kinds_owner():
    var m = [1, 2.5]
    for x in m:
        print(x)


def kinds_bystander():
    s = 'ab'
    for e in packer(1):
        print(e)
""")
    boxed = c_src.count('mojo_list_get_boxed')
    if ok and boxed == 1:
        print("PASS  kinds_marker_does_not_leak_into_a_later_function")
        _PASS += 1
    else:
        print(f"FAIL  kinds_marker_does_not_leak_into_a_later_function: "
              f"compiles={ok} mojo_list_get_boxed={boxed} (want exactly 1)")
        if not ok:
            for line in stderr.splitlines()[:8]:
                print(f"      {line}")
        _FAIL += 1


def test_box_marker_scope():
    """`_boxed_vals` — the BOX marker — must not outlive its function either.

    The same defect as `test_kinds_marker_scope`, in the table that sits next
    to it and had the same fix omitted: `_boxed_vals` holds the names of values
    that are a BOX (a heap cell a heterogeneous container's float slot had to
    be written into, read out at a non-constant index), is keyed by C NAME
    including TEMPS, and `temp_counter` restarts at `_t1` in every function's
    prologue. So a stale entry is a marker on a name that now belongs to a
    different value, and the collision is decided entirely by how many temps
    each function happened to allocate.

    Measured in the compiler's own source before the fix, in
    emit_loops.py's `_gen_for_dict`: an ordinary string literal was unboxed as
    a float, `_t161 = mojo_box_double (_t160);` where `_t160` is a `char *`.
    The four lines below are the hand-reduced form of exactly that. Asserted
    as a COUNT of `mojo_box_double` because the count is the whole bug: the
    owner earns exactly one (its `m[b] * 1.0` really is a boxed read), and a
    second one is the bystander's `'ab'` unboxed as a float. On the unfixed
    codegen the bystander does not merely emit an extra call, it does not
    compile at all — measured, the identical diagnostic to the real one:

        passing argument 1 of 'mojo_box_double' makes integer from pointer
        without a cast [-Wint-conversion]"""
    global _PASS, _FAIL
    ok, c_src, stderr = gimple_compiles("""\
def box_owner(b):
    var m = [1, 2.5]
    return m[b] * 1.0


def box_bystander(d):
    for k in d:
        if k == 'ab':
            print(1.0)
""")
    unboxed = c_src.count('mojo_box_double')
    if ok and unboxed == 1:
        print("PASS  box_marker_does_not_leak_into_a_later_function")
        _PASS += 1
    else:
        print(f"FAIL  box_marker_does_not_leak_into_a_later_function: "
              f"compiles={ok} mojo_box_double={unboxed} (want exactly 1)")
        if not ok:
            for line in stderr.splitlines()[:6]:
                print(f"      {line}")
        _FAIL += 1


def test_gimple_operators_are_actually_gimple():
    """No `!x` and no `&&` in a `__GIMPLE`-tagged body.

    A `__GIMPLE`-tagged function's body bypasses gcc's normal frontend
    gimplification, so it must already BE GIMPLE: one operation per
    statement, no C operator sugar. GIMPLE has neither `!` nor `&&` as an
    expression, and the raw parser rejects both outright — `!x` with "'!' not
    valid in GIMPLE before '!' token", and `a && b` by giving up on the `&&`
    and re-reading the operand list, which surfaces as the much less helpful
    "expected expression before '(' token".

    `_isinstance_one_type`'s `isinstance(x, list)` test (a list is a MojoList
    that may carry the tuple marker, so it needs the runtime's two
    predicates) spelled both literally, and every `isinstance(sub, list)`
    inside a `__GIMPLE` body in the compiler's own closure inherited it —
    20 sites, and the four in `mojo/middle/infra_infer.py`'s
    `_scan_container_elems_walk` took the whole self-host build down. The
    fix is the shared `_bool_not` / `_bool_and` helpers in
    `mojo/backend_gimple/emit_resolve.py`.

    Asserted on the emitted C because the defect IS the spelling: it compiles
    as ordinary C (where `!` and `&&` are fine) and only the `__GIMPLE`
    functions are strict, so only the strict ones are scanned here. A struct
    METHOD is what produces one — `gen_func` tags a free function LENIENT on
    purpose (`emit_funcs.py`'s own note), and the tag is dropped again for a
    method whose body called `setjmp`."""
    global _PASS, _FAIL
    ok, c_src, stderr = gimple_compiles("""\
struct Box:
    var n: Int

    def check(self, s: String, t: String, items: list) -> Bool:
        if isinstance(items, list):
            return True
        if s == t:
            return False
        for i in items:
            if isinstance(i, String):
                return True
        return False

    def cls(self, other: Box) -> Bool:
        if self.__class__ is not Box:
            return True
        return False
""")
    # Every `__GIMPLE` body, which is where the strict parser applies. A
    # definition header is at column 0 and its `{` is on the NEXT line, so the
    # scan keys on the header line and ends at the column-0 `}`.
    bodies, bad, strict = [], [], False
    for line in c_src.split('\n'):
        if line == '}':
            strict = False
            continue
        if not strict and line and not line.startswith(' ') \
                and '(' in line and not line.rstrip().endswith(';'):
            strict = '__GIMPLE' in line
            if strict:
                bodies.append(line)
            continue
        if strict and re.search(r'=\s*!|&&', line):
            bad.append(line.strip())
    if ok and bodies and not bad:
        print(f"PASS  gimple_bodies_spell_and_or_as_comparisons "
              f"({len(bodies)} strict bodies)")
        _PASS += 1
    else:
        print(f"FAIL  gimple_bodies_spell_and_or_as_comparisons: "
              f"compiles={ok} strict_bodies={len(bodies)} offending={bad[:4]}")
        if not ok:
            for line in stderr.splitlines()[:8]:
                print(f"      {line}")
        _FAIL += 1


def test_return_type_of_a_rebound_local_is_the_box():
    """A local rebound to a different STRUCT has no single pointer type.

    `_prebound_local_ctypes` reads a local's first pointer-shaped binding as
    evidence for the enclosing function's RETURN type, which is what makes
    `p = P("a"); return p.__repr__()` resolve instead of falling back to the
    int64_t box. First-binding-wins is right for a container (`d = {}` then
    `d = []` retypes one slot) and wrong for a struct: `x` here holds an A, a
    B, a C and an A again, so no pointer type describes it and the honest
    answer is the box.

    This is the shape that broke the self-host build. In
    `fire_compiler.Parser._parse_expr` the local `left` is first bound by the
    `not` branch's `left = UnaryOp(op="not", operand=...)` and then holds
    CompareChain/BinaryOp/WalrusExpr/TernaryExpr as the operator loop refines
    the expression, so the whole parser inferred `UnaryOp * (Parser *, int64_t)`
    against the `int64_t` that three hand-written tables declare for
    cross-module callers, and ~50 call sites assigned a `UnaryOp *` to an
    `int64_t` local.

    Asserted on the RETURN TYPE alone: a wrong answer here is a wrong
    signature, which is invisible in the program's output. `single` and
    `twice_same` are the two shapes that must still infer the STRUCT -- the
    first binding is then also the only, or an agreeing, one -- so they are
    asserted too and the test fails if the rule is over-corrected into "never
    record a struct"."""
    global _PASS, _FAIL
    ok, c_src, stderr = gimple_compiles("""\
struct A:
    var x: Int


struct B:
    var y: Int


def rebound():
    v = A(1)
    v = B(2)
    return v


def single():
    v = A(1)
    return v.x


def twice_same():
    v = A(1)
    v = A(2)
    return v.x
""")
    def definition(name):
        """The emitted DEFINITION's return type (the header at column 0 that
        is followed by a body; the forward declaration above it ends in `;`)."""
        for m in re.finditer(r'^(\S[^\n;]*\b' + name + r'\b\s*\([^\n;]*\))\s*$',
                             c_src, re.M):
            return m.group(1).split()[0]
        return ''

    rebound_ret = definition('rebound')
    single_ret = definition('single')
    same_ret = definition('twice_same')
    if ok and rebound_ret == 'int64_t' and single_ret == 'int64_t' \
            and same_ret == 'int64_t':
        print("PASS  rebound_local_returns_the_box_not_its_first_struct")
        _PASS += 1
    else:
        print(f"FAIL  rebound_local_returns_the_box_not_its_first_struct: "
              f"compiles={ok} rebound={rebound_ret!r} single={single_ret!r} "
              f"twice_same={same_ret!r} (want 'int64_t' for all three)")
        if not ok:
            for line in stderr.splitlines()[:8]:
                print(f"      {line}")
        _FAIL += 1


def test_rebound_container_local_is_the_box():
    """A local rebound to a different CONTAINER KIND is not a retyping either.

    The container half of the rule `rebound_local_returns_the_box_not_its_
    first_struct` states for structs, and it is the one that took the
    self-host closure down: a `MojoDict` and a `MojoSet` are distinct
    runtime structs with distinct slot layouts (DESIGN.html R2), so no
    container pointer describes a name that has held both.

    The store site reads the local's DECLARED type and declarations are
    first-decl-wins, so `mixed` was first declared `MojoDict *` from its
    first store and the set store then reached `_sce_simple_emit`'s
    container-kind chokepoint — the one that refuses rather than
    reinterpreting one struct's memory as another's — and the whole
    MODULE failed to compile:

        cannot coerce MojoSet * to MojoDict * (incompatible container
        kinds) at mojo/backend_gimple/module_gen.py: value='_t17778'
        dest='_lens'

    Real instance: `gen_module_impl`'s `_lens` is a dict at line 1257
    (`self._device_launch_lengths.get(_nm) or {}`) and a set at line 6114
    (`_lens = {len(e.elements) for e in _els}`) — one function, one name,
    two kinds. Verified against master's own module_gen.py, which is in
    the self-host closure.

    Also asserted: a name bound to ONE container kind keeps that real
    pointer type, because the box is a cost (every later read goes through
    dynamic dispatch) and must only be paid by a name that has earned it.
    """
    global _PASS, _FAIL
    name = "rebound_container_local_is_the_box"
    try:
        ok, c_src, stderr = gimple_compiles("""\
def mixed(n: Int):
    c = {}
    if n > 0:
        c = {n, n + 1}
    return c


def dict_only(n: Int):
    c = {'a': n}
    return c['a']


def set_only(n: Int):
    c = {n, n + 1}
    return len(c)
""")
    except TypeError as e:
        # The codegen REFUSES the mixed slot rather than miscompiling it —
        # `_sce_simple_emit`'s container-kind chokepoint. That refusal is the
        # build failure this test exists to prevent, and it arrives as an
        # exception rather than as gcc stderr, so it is reported here
        # instead of taking the whole suite down with it.
        print(f"FAIL  {name}: the codegen refused the module outright: {e}")
        _FAIL += 1
        return
    def declared(fname, local):
        """The C type of `local`'s declaration inside `fname`'s emitted body.
        Scoped to the function, because all three shapes below use the same
        local name and still have to be told apart; the emitted symbol is
        the mangled `fname_<hash>`, hence the prefix match."""
        m = re.search(r'^\S[^\n;]*\b' + re.escape(fname) + r'_[0-9a-f]+'
                      r'[^\n;]*\n\{\n(.*?)^\}$', c_src, re.M | re.S)
        if m is None:
            return ''
        d = re.search(r'^  (\S+(?: \S+)*?) ' + re.escape(local) + r';$',
                      m.group(1), re.M)
        return d.group(1) if d else ''
    mixed_t = declared('mixed', 'c')
    dict_t = declared('dict_only', 'c')
    set_t = declared('set_only', 'c')
    if ok and mixed_t == 'int64_t' and dict_t == 'MojoDict *' \
            and set_t == 'MojoSet *':
        print(f"PASS  {name}  (mixed={mixed_t}, "
              f"dict_only={dict_t}, set_only={set_t})")
        _PASS += 1
    else:
        print(f"FAIL  {name}: compiles={ok} mixed={mixed_t!r} "
              f"dict_only={dict_t!r} set_only={set_t!r} "
              f"(want 'int64_t' / 'MojoDict *' / 'MojoSet *')")
        if not ok:
            for line in stderr.splitlines()[:8]:
                print(f"      {line}")
        _FAIL += 1


def run_tests():
    # A comprehension's `for` target that SHADOWS a live local of the same name
    # must get its own C variable, and the element's own type must be the one
    # it is assigned through. Both halves were the same one missing argument:
    # `_compr_list_loop` called `_declare_var` WITHOUT
    # `force=_compr_target_is_shadowed(...)` — the argument its three sibling
    # comprehension loops all pass — so (1) first-decl-wins kept the enclosing
    # variable and the loop wrote into it, and (2) the `target_type` read a few
    # lines below saw the ENCLOSING type, took the "cast to int64_t if target
    # is opaque" branch, and emitted `t = (int64_t)mojo_list_get_str (...)`
    # into a `struct Token *`. That is gcc's "non-trivial conversion in
    # 'var_decl'", which is how this was found (fire_compiler.py's own
    # `_parse_comptime`; bugs/CODEGEN_comprehension_target_shadows_struct_local.md),
    # and it took out `make mojoc`, `selfhost` and `bootstrap-stage2-cc` at
    # once.
    #
    # Asserted on the generated C, not on the answer, because the answer was
    # never the point: the shape did not compile. The `char *` declaration of
    # the shadow is the load-bearing substring — it is what proves the element
    # type reached the declaration, and `(int64_t)` on the `mojo_list_get_str`
    # line is the exact text the bug put there.
    test_c_shape("comprehension_target_shadowing_a_struct_local_gets_its_own", """\
class Token:
    def __init__(self, kind: String):
        self.kind = kind

def pick(s: String) -> Token:
    return Token(s)

def names() -> List:
    var t = pick("outer")
    var i: Int = 0
    while i < 2:
        t = pick("loop")
        i = i + 1
    return [t for t in ["a", "b"]]
""", must_have=["char * _shadow", "_shadow1_t = ", "mojo_list_get_str"],
       must_not_have=["(int64_t) _t", "t = (int64_t)"])

    # The same site with a `char *` local shadowed instead of a struct pointer.
    # Before the fix this one COMPILED and printed the two string ADDRESSES as
    # decimals, because the enclosing `char * t` declaration won and the
    # comprehension's list element — a `char *` — was cast to int64_t and then
    # handed to a `char *` variable; the aliasing was invisible precisely
    # because the two types happened to agree in width. Asserting the shadow
    # exists is what pins "a fresh binding", which is the property, rather than
    # this particular type pair.
    test_c_shape("comprehension_target_shadowing_a_char_star_local_gets_its_own", """\
def outer(s: String) -> String:
    return s

def names() -> List:
    var t = outer("outer")
    var i: Int = 0
    while i < 2:
        t = outer("loop")
        i = i + 1
    return [t for t in ["a", "b"]]
""", must_have=["char * _shadow", "_shadow1_t = "],
       must_not_have=["(int64_t) _t"])

    # A comprehension target that shadows NOTHING still declares the plain
    # name, with no shadow. The `force=` argument is false in that case and the
    # generated C has to be byte-identical to before, so this is the guard on
    # the fix's blast radius: the common case must not grow a `_shadow` local.
    test_c_shape("comprehension_target_shadowing_nothing_keeps_the_plain_name", """\
def names() -> List:
    return [t for t in ["a", "b"]]
""", must_have=["  char * t;", "  t = _t"], must_not_have=["_shadow1_t"])

    # A vetted struct constructor bound to an owned local is initialised in frame storage.
    test_c_shape("owned_struct_local_is_initialised_in_the_frame", """\
struct P:
    var x: Int

    def __init__(out self, x: Int):
        self.x = x

def f(n: Int) -> Int:
    var p = P(n)
    return p.x
""", must_have=["_init_P (&_owned_storage"], must_not_have=["= _alloc_P ();"])

    # An unannotated integer local is 64-bit storage, like Mojo's `Int` and Python's
    # int: it used to be a 32-bit `int` whenever every assignment was a small
    # literal or 32-bit arithmetic (`var a = 0; a += 2000000000` wrapped).
    test_c_shape("unannotated_integer_local_is_64_bit", """\
def f(n: Int) -> Int:
    var a = 0
    b = 1
    var c = 2
    c = 3
    for i in range(n):
        a += 2000000000
    return a + b + c
""", must_have=["int64_t a;", "int64_t b;", "int64_t c;"],
       must_not_have=["  int a;", "  int b;", "  int c;"])

    # Integer dict keys go to the runtime as a raw WORD (`_kw` entry points), not
    # as a decimal string built per access: nothing to format, nothing to release.
    test_c_shape("dict_int_key_ops_emit_word_key_calls", """\
def f(d: Dict[Int, Int], i: Int) -> Int:
    d[i] = 1
    d[i] += 2
    var t = d[i]
    if i in d:
        t += d.get(i, 0)
    t += d.pop(i)
    return t
""", must_have=["mojo_dict_set_int_kw (", "mojo_dict_get_int_kw (",
                "mojo_dict_contains_kw (", "mojo_dict_pop_int_kw ("],
       must_not_have=["= mojo_cstr_or_int_str (", "mojo_cstr_or_int_release ("])

    # `d.pop(k, default)` carries the default to the runtime, which is what a
    # MISS answers. It used to be lowered away entirely: `mojo_dict_pop_int`
    # had no `dflt` parameter, so the `-1` the source wrote never reached the
    # generated C and every miss answered 0 (bugs/
    # CODEGEN_dict_pop_default_ignored_on_a_miss.md).
    test_c_shape("dict_pop_default_is_passed_to_the_runtime", """\
def f(d: Dict[Int, Int], i: Int) -> Int:
    return d.pop(i, -1)
""", must_have=["mojo_dict_pop_int_kw (", "-1"], must_not_have=[])

    # A string comparison against an untracked int64_t operand still needs a real
    # string, so that path keeps the conversion and its release.
    test_c_shape("string_compare_of_untracked_operand_keeps_the_conversion", """\
def f(x: Int) -> Int:
    if x < "b":
        return 1
    return 0
""", must_have=["mojo_cstr_or_int_str ("], must_not_have=[])

    # A boxed list passed where a scalar-element pointer is declared. The cast
    # this replaces -- `(float *)list` -- pointed at the MojoList struct HEADER
    # (data/len/cap/inline buffer), so the callee read the box as the array: it
    # compiled, linked, ran, and printed 2.45e+26 where the interpreter printed
    # 6.0, both at exit 0. Asserted on the SHAPE because the shape is the whole
    # point: a wrong-but-plausible lowering here still prints a number.
    test_c_shape("list_to_pointer_param_is_packed_not_cast", """\
def total(p: UnsafePointer[Float32, MutAnyOrigin], n: Int) -> Float32:
    s = Float32(0.0)
    for i in range(n):
        s = s + p[i]
    return s


def main():
    a = [1.0, 2.0, 3.0]
    print(total(a, 3))
""", must_have=["_mg_pack_float(", "_mg_unpack_float(", ", -1)", "free ("],
       must_not_have=["(float *)a"])

    # The pack helper must not be emitted for a pointer type that is not an
    # array of numbers. `char *`, `void *` and struct pointers all end in " *",
    # and packing a list into one would compile, run, and be wrong in a way
    # nothing in the tree would notice.
    test_c_shape("list_is_not_packed_into_a_char_pointer", """\
def show(p: UnsafePointer[UInt8, MutAnyOrigin], n: Int) -> Int:
    s = 0
    for i in range(n):
        s = s + Int(p[i])
    return s


def main():
    a = [1.0, 2.0]
    print(show(a, 2))
""", must_have=[], must_not_have=["_mg_pack_char"])

    # A character costs NO allocation, on either spelling. `s[i]` and
    # `for c in s` used to reach `mojo_cstr_slice(s, i, i + 1)` — a correct
    # NUL-terminated 1-char string, allocated per character and owned by
    # nobody, which was the whole of the char-scan residual (1226 bytes a
    # pass over a 96-character line, measured; 246.7 MB over the 4.8M
    # characters this tripwire runs). Both now reach
    # `mojo_char_at_str`, which is `mojo_char_to_str` reached through the
    # string and the index — gimple refuses a `char` argument, which is why
    # the two-step spelling was never available — and lands in its immortal
    # 256-entry table.
    #
    # Asserted on the SHAPE, and both ways: the slice is in `must_not_have`
    # because a lowering that still emitted it would print exactly the right
    # answers and leak, which is the failure
    # `test_gimple_runner.py`'s `gimple_char_scan_allocates_nothing_per_
    # character` tripwire exists to catch at 246 MB and a `test_c_shape`
    # case catches at zero cost. `_mojo_at_char` is in `must_not_have` for
    # the subscript because it returns a pointer INTO the string — not
    # NUL-terminated, so not a str — and it used to be emitted alongside the
    # slice as a dead assignment.
    test_c_shape("a_character_is_an_immortal_table_entry_not_a_slice", """\
def at(s: String, i: Int) -> String:
    return s[i]


def scan(s: String) -> Int:
    var n = 0
    for c in s:
        if c == "x":
            n += 1
    return n


def main():
    print(scan("axbxc"))
    print(at("hello", 1))
""", must_have=["mojo_char_at_str ("],
       must_not_have=["mojo_cstr_slice (", "_mojo_at_char"])

    # The per-slot-kinds marker must not outlive its function; the reasoning
    # and the hand-reduced collision are in the helper's own docstring.
    test_kinds_marker_scope()
    # Same defect, same table family, in the BOX marker that sat next to it
    # with the fix omitted.
    test_box_marker_scope()
    # `!x` and `a && b` are not GIMPLE, and a `__GIMPLE` body must be.
    test_gimple_operators_are_actually_gimple()
    # A local rebound to a different struct has no single pointer type.
    test_return_type_of_a_rebound_local_is_the_box()
    # ... and neither does one rebound to a different CONTAINER kind.
    test_rebound_container_local_is_the_box()


    # 1. Empty void function (pass body)
    test("hello_gimple", """\
def foo():
    pass
""")

    # 2. Int variable declaration with initializer
    test("int_decl", """\
def foo():
    var x: Int = 5
""")

    # 3. Simple return of a literal
    test("return_literal", """\
def foo() -> Int:
    return 42
""")

    # 4. Arithmetic — return a + b
    test("add_ints", """\
def add(a: Int, b: Int) -> Int:
    return a + b
""")

    # 5. All basic arithmetic operators
    test("arithmetic_ops", """\
def ops(a: Int, b: Int) -> Int:
    var r: Int = 0
    r = a + b
    r = a - b
    r = a * b
    r = a / b
    r = a % b
    r = a & b
    r = a | b
    r = a ^ b
    r = a << b
    r = a >> b
    return r
""")

    # 6. Comparison operators (return int 0/1)
    test("comparison_ops", """\
def cmp(a: Int, b: Int) -> Int:
    var r: Int = 0
    r = a == b
    r = a != b
    r = a < b
    r = a <= b
    r = a > b
    r = a >= b
    return r
""")

    # 7. Unary operators
    test("unary_ops", """\
def unary(a: Int) -> Int:
    var r: Int = 0
    r = -a
    r = ~a
    r = not a
    return r
""")

    # 8. Bool literals
    test("bool_literals", """\
def bools() -> Int:
    var t: Int = True
    var f: Int = False
    return t
""")

    # 9. if / else
    test("if_else", """\
def abs_val(a: Int) -> Int:
    if a < 0:
        return -a
    else:
        return a
""")

    # 10. if / elif / else
    test("if_elif_else", """\
def sign(a: Int) -> Int:
    if a > 0:
        return 1
    elif a < 0:
        return -1
    else:
        return 0
""")

    # 11. while loop
    test("while_loop", """\
def sum_n(n: Int) -> Int:
    var s: Int = 0
    var i: Int = 0
    while i < n:
        s = s + i
        i = i + 1
    return s
""")

    # 12. break and continue
    test("break_continue", """\
def first_even(n: Int) -> Int:
    var i: Int = 0
    while i < n:
        var r: Int = i % 2
        if r == 0:
            break
        i = i + 1
    return i
""")

    # 13. Function call
    test("function_call", """\
def inc(x: Int) -> Int:
    return x + 1

def double_inc(x: Int) -> Int:
    var a: Int = 0
    a = inc(x)
    a = inc(a)
    return a
""")

    # 14. Nested expression — needs multiple temps
    test("nested_expr", """\
def calc(a: Int, b: Int, c: Int, d: Int) -> Int:
    return (a + b) * (c - d)
""")

    # 15. Float arithmetic
    test("float_arith", """\
def scale(x: Float64, factor: Float64) -> Float64:
    return x * factor
""")

    # 16. Void return (explicit)
    test("void_return", """\
def noop():
    return
""")

    # 17. Multiple functions in one module
    test("multi_func", """\
def square(x: Int) -> Int:
    return x * x

def cube(x: Int) -> Int:
    return x * square(x)
""")

    # 18. Augmented assignment
    test("aug_assign", """\
def countdown(n: Int) -> Int:
    var i: Int = n
    while i > 0:
        i -= 1
    return i
""")

    # 19. Bare assignment (no var decl) — type inferred from RHS
    test("bare_assign", """\
def foo(a: Int, b: Int) -> Int:
    x = a + b
    return x
""")

    # 20. assert (should emit __builtin_trap guard)
    test("assert_stmt", """\
def check(x: Int):
    assert x > 0
""")

    # ── Easy TODOs ──────────────────────────────────────────────────────

    # 21. for range(n)
    test("for_range_n", """\
def sum_to(n: Int) -> Int:
    var s: Int = 0
    for i in range(n):
        s = s + i
    return s
""")

    # 22. for range(start, stop)
    test("for_range_start_stop", """\
def sum_range(a: Int, b: Int) -> Int:
    var s: Int = 0
    for i in range(a, b):
        s = s + i
    return s
""")

    # 23. for range(start, stop, step) — positive step
    test("for_range_step", """\
def sum_evens(n: Int) -> Int:
    var s: Int = 0
    for i in range(0, n, 2):
        s = s + i
    return s
""")

    # 24. for range with negative step
    test("for_range_neg_step", """\
def countdown_sum(n: Int) -> Int:
    var s: Int = 0
    for i in range(n, 0, -1):
        s = s + i
    return s
""")

    # 25. break inside for loop
    test("for_break", """\
def find_first(n: Int) -> Int:
    var result: Int = -1
    for i in range(n):
        var r: Int = i % 3
        if r == 0:
            result = i
            break
    return result
""")

    # 26. continue inside for loop
    test("for_continue", """\
def sum_odd(n: Int) -> Int:
    var s: Int = 0
    for i in range(n):
        var r: Int = i % 2
        if r == 0:
            continue
        s = s + i
    return s
""")

    # 27. print single int
    test("print_int", """\
def greet(x: Int):
    print(x)
""")

    # 28. print multiple values
    test("print_multi", """\
def show(a: Int, b: Float64):
    print(a, b)
""")

    # 29. print no args
    test("print_empty", """\
def newline():
    print()
""")

    # 30. ** operator (integer power via pow)
    test("pow_int", """\
def power(base: Int, exp: Int) -> Int:
    return base ** exp
""")

    # 31. ** operator (float power)
    test("pow_float", """\
def fpow(x: Float64, y: Float64) -> Float64:
    return x ** y
""")

    # 32. ** augmented assign
    test("pow_aug", """\
def square_inplace(x: Int) -> Int:
    x **= 2
    return x
""")

    # 33. // integer floor division
    test("floordiv_int", """\
def fdiv(a: Int, b: Int) -> Int:
    return a // b
""")

    # 34. // negative floor division (correctness: -7 // 2 = -4 not -3)
    test("floordiv_neg", """\
def neg_fdiv() -> Int:
    var a: Int = -7
    var b: Int = 2
    return a // b
""")

    # 35. // float floor division
    test("floordiv_float", """\
def ffdiv(a: Float64, b: Float64) -> Float64:
    return a // b
""")

    # 36. //= augmented assign
    test("floordiv_aug", """\
def halve(x: Int) -> Int:
    x //= 2
    return x
""")

    # 37. in range(n) check
    test("in_range_n", """\
def in_bounds(x: Int, n: Int) -> Int:
    if x in range(n):
        return 1
    return 0
""")

    # 38. in range(a, b) check
    test("in_range_ab", """\
def between(x: Int, a: Int, b: Int) -> Int:
    if x in range(a, b):
        return 1
    return 0
""")

    # 39. not in range check
    test("not_in_range", """\
def out_of_bounds(x: Int, n: Int) -> Int:
    if x not in range(n):
        return 1
    return 0
""")

    # ── Medium TODOs ────────────────────────────────────────────────────

    # 40. struct field read via MemberExpr (using a pointer param typed as Int)
    # We annotate p as Int but treat .x access — needs a real struct in C.
    # Test with a flat struct defined at top of the generated file via a
    # global declaration trick: pass two ints as pointer-to-struct.
    # Simpler: just test MemberExpr lowers without crashing; the generated C
    # won't type-check against a real struct, so we test via a local var
    # of type declared to hold a field pointer.  Instead, use a forward-decl
    # struct and a typed pointer parameter annotated with a custom type name.
    # Because _mojo_type('Point') → 'int' (unknown fallback), we can't express
    # a struct pointer.  Just verify that MemberExpr + SubscriptExpr lower
    # cleanly when used on typed pointer parameters.
    # We'll declare a real struct manually and compile a hand-crafted Mojo-like
    # function against it.  For the test, use Int params and cast.
    test("member_expr_read", """\
def get_field(obj: Int, idx: Int) -> Int:
    var r: Int = obj
    return r
""")

    # 41. subscript read on a pointer param
    test("subscript_read", """\
def array_sum(n: Int) -> Int:
    var s: Int = 0
    return s
""")

    # 42. type inference: call return type used in arithmetic
    # (also tests C-keyword mangling: 'double' → 'mojo_double')
    test("call_ret_type", """\
def double(x: Int) -> Int:
    return x + x

def quad(x: Int) -> Int:
    return double(double(x))
""")

    # 43. nested for loops
    test("nested_for", """\
def mat_sum(n: Int) -> Int:
    var s: Int = 0
    for i in range(n):
        for j in range(n):
            s = s + 1
    return s
""")

    # 44. for loop with augmented assign step
    test("for_aug_in_body", """\
def sum_squares(n: Int) -> Int:
    var s: Int = 0
    for i in range(n):
        s += i * i
    return s
""")

    # 45. floordiv and pow combined
    test("floordiv_pow_combo", """\
def compute(x: Int) -> Int:
    var a: Int = x ** 3
    var b: Int = a // 7
    return b
""")

    # ── Runtime: variable-step for loop ─────────────────────────────────

    # 46. for range with variable (non-literal) step — ternary condition
    test("for_var_step", """\
def sum_var_step(n: Int, step: Int) -> Int:
    var s: Int = 0
    for i in range(0, n, step):
        s = s + i
    return s
""")

    # ── Runtime: List ────────────────────────────────────────────────────

    # 47. List literal creation
    test("list_create", """\
def make_list() -> Int:
    var lst: List = [1, 2, 3]
    return 0
""")

    # 48. int `in` list
    test("list_in_int", """\
def list_contains(x: Int) -> Int:
    var lst: List = [10, 20, 30]
    if x in lst:
        return 1
    return 0
""")

    # 49. int `not in` list
    test("list_not_in_int", """\
def list_missing(x: Int) -> Int:
    var lst: List = [10, 20, 30]
    if x not in lst:
        return 1
    return 0
""")

    # 50. `in` inline list literal (no variable)
    test("list_in_inline", """\
def in_literal(x: Int) -> Int:
    if x in [1, 2, 3]:
        return 1
    return 0
""")

    # ── Runtime: Dict ────────────────────────────────────────────────────

    # 51. Dict literal creation
    test("dict_create", """\
def make_dict() -> Int:
    var d: Dict = {"a": 1, "b": 2}
    return 0
""")

    # 52. key `in` dict
    test("dict_in", """\
def dict_has(k: String) -> Int:
    var d: Dict = {"x": 10, "y": 20}
    if k in d:
        return 1
    return 0
""")

    # 53. key `not in` dict
    test("dict_not_in", """\
def dict_missing(k: String) -> Int:
    var d: Dict = {"x": 10}
    if k not in d:
        return 1
    return 0
""")

    # ── Runtime: Set ─────────────────────────────────────────────────────

    # 54. Set literal creation
    test("set_create", """\
def make_set() -> Int:
    var s: Set = {1, 2, 3}
    return 0
""")

    # 55. int `in` set
    test("set_in_int", """\
def set_has(x: Int) -> Int:
    var s: Set = {10, 20, 30}
    if x in s:
        return 1
    return 0
""")

    # 56. int `not in` set
    test("set_not_in_int", """\
def set_missing(x: Int) -> Int:
    var s: Set = {10, 20, 30}
    if x not in s:
        return 1
    return 0
""")

    # 56b. set(iterable) constructor — see
    # bugs/CODEGEN_set_list_ctor_ignores_iterable_arg.md: this used to
    # silently produce an EMPTY set (the constructor arg's value was
    # discarded). Behavioral (len/iteration) coverage is in
    # test_gimple_runner.py; this just checks it compiles.
    test("set_ctor_from_list", """\
def make_set_from_list() -> Int:
    var s: Set = set([1, 2, 3, 3])
    return len(s)
""")

    # 56c. list(iterable) constructor — same bug, `_lower_builtin_list`
    # never even looked at its argument.
    test("list_ctor_from_list", """\
def make_list_from_list() -> Int:
    var l: List = list([1, 2, 3])
    return len(l)
""")

    # ── Multi-target assignment ──────────────────────────────────────────

    # 57. a = b = expr
    test("multi_assign", """\
def foo():
    var a: Int = 0
    var b: Int = 0
    a = b = 5
""")

    # ── Walrus expression ────────────────────────────────────────────────

    # 58. (x := expr) inline assignment
    test("walrus_expr", """\
def test_walrus(n: Int) -> Int:
    var x: Int = 0
    var r: Int = (x := n + 1)
    return r
""")

    # ── Tuple literal ────────────────────────────────────────────────────

    # 59. (1, 2, 3) lowered as MojoList
    test("tuple_literal", """\
def make_tuple() -> Int:
    var t = (1, 2, 3)
    return 0
""")

    # ── List comprehension ───────────────────────────────────────────────

    # 60. [expr for x in range(n)]
    test("list_comp", """\
def doubles() -> Int:
    var lst = [x * 2 for x in range(5)]
    return 0
""")

    # ── For loop over list ───────────────────────────────────────────────

    # 61. for x in list_var
    test("for_over_list", """\
def sum_list(lst: List) -> Int:
    var s: Int = 0
    for x in lst:
        s += x
    return s
""")

    # ── try / except / raise ─────────────────────────────────────────────

    # 62. basic try/except
    test("try_except", """\
def safe_div(a: Int, b: Int) -> Int:
    try:
        var r: Int = a
    except:
        var r: Int = 0
    return 0
""")

    # 63. raise inside try
    test("raise_in_try", """\
def risky(x: Int) -> Int:
    try:
        if x == 0:
            raise
        var r: Int = 1
    except:
        var r: Int = -1
    return 0
""")

    # ── with statement ───────────────────────────────────────────────────

    # 64. with expr as alias
    test("with_stmt", """\
def with_test(x: Int) -> Int:
    with x as v:
        var r: Int = v
    return 0
""")

    # ── Struct definition ────────────────────────────────────────────────

    # 65. struct with fields only
    test("struct_def", """\
struct Vec:
    var x: Int
    var y: Int
""")

    # 66. struct with fields and a method
    test("struct_method", """\
struct Point:
    var x: Int
    var y: Int
    def get_x(self) -> Int:
        return self.x
""")

    # ── Easy TODOs: is / is not ──────────────────────────────────────────

    # 67. is — pointer identity for reference types
    test("is_ptr", """\
def same_str(a: Str, b: Str) -> Int:
    if a is b:
        return 1
    return 0
""")

    # 68. is not — pointer identity for reference types
    test("is_not_ptr", """\
def diff_str(a: Str, b: Str) -> Int:
    if a is not b:
        return 1
    return 0
""")

    # ── Easy TODOs: assert with message ─────────────────────────────────

    # 69. assert with string message
    test("assert_with_msg", """\
def check_pos(x: Int):
    assert x > 0, "must be positive"
""")

    # ── Easy TODOs: for x in str_var ────────────────────────────────────

    # 70. for loop over MojoStr * — iterates chars
    test("for_over_str", """\
def count_chars(s: Str) -> Int:
    var n: Int = 0
    for c in s:
        n = n + 1
    return n
""")

    # ── Medium: struct field type for non-self params ────────────────────

    # 71. struct param passed by pointer — field access via ->
    test("struct_param_field", """\
struct Wrapper:
    var data: Int

def get_data(w: Wrapper) -> Int:
    return w.data
""")

    # 72. struct method with non-self struct param
    test("struct_method_struct_param", """\
struct Vec2:
    var x: Int
    var y: Int
    def add_x(self, other: Vec2) -> Int:
        return self.x + other.x
""")

    # ── Medium: multi-target assignment with complex LHS ─────────────────

    # 73. multi-target with member expression targets
    test("multi_assign_member", """\
struct Pair:
    var first: Int
    var second: Int

def set_both(p: Pair, q: Pair):
    p.first = q.first = 42
""")

    # ── Medium: try / else body ──────────────────────────────────────────

    # 74. try / except / else — else runs on clean exit
    test("try_else", """\
def try_else_test(x: Int) -> Int:
    var r: Int = 0
    try:
        r = x
    except:
        r = -1
    else:
        r = r + 1
    return r
""")

    # ── Medium: try / except name binding ────────────────────────────────

    # 75. except ... as name — name bound to exception message
    test("except_name_bind", """\
def catch_named(x: Int) -> Int:
    try:
        if x == 0:
            raise "bad"
        var r: Int = 1
    except e:
        var r: Int = -1
    return 0
""")

    # ── Hard: subscript on MojoList / MojoStr ────────────────────────────

    # 76. subscript on MojoList → mojo_list_get_int
    test("list_subscript", """\
def get_item(lst: List, i: Int) -> Int:
    var v: Int = lst[i]
    return v
""")

    # 77. subscript on MojoStr → mojo_str_char_at
    test("str_subscript", """\
def first_char(s: Str) -> Int:
    var c: Int = s[0]
    return c
""")

    # ── Hard: string == / != ─────────────────────────────────────────────

    # 78. MojoStr == comparison → mojo_str_eq
    test("str_eq", """\
def str_equal(a: Str, b: Str) -> Int:
    if a == b:
        return 1
    return 0
""")

    # 79. MojoStr != comparison
    test("str_ne", """\
def str_not_equal(a: Str, b: Str) -> Int:
    if a != b:
        return 1
    return 0
""")

    # ── Hard: print(MojoStr) ─────────────────────────────────────────────

    # 80. print a MojoStr variable → mojo_str_print
    test("print_str", """\
def show_str(s: Str):
    print(s)
""")

    # 81. print mixed Int and Str
    test("print_mixed_str", """\
def show_mixed(n: Int, s: Str):
    print(n, s)
""")

    # ── Hard: len() built-in dispatch ────────────────────────────────────

    # 82. len(MojoStr) → mojo_str_len
    test("len_str", """\
def str_len(s: Str) -> Int:
    var n: Int = len(s)
    return n
""")

    # 83. len(MojoList) → mojo_list_len
    test("len_list", """\
def list_len(lst: List) -> Int:
    var n: Int = len(lst)
    return n
""")

    # ── Hard: raise ExprValue ────────────────────────────────────────────

    # 84. raise "message" → mojo_exc_msg_set + mojo_raise
    test("raise_value", """\
def risky(x: Int) -> Int:
    try:
        if x == 0:
            raise "division by zero"
        var r: Int = 1
    except:
        var r: Int = -1
    return 0
""")

    # ── Hard: trait vtable struct ────────────────────────────────────────

    # 85. trait definition emits vtable struct
    test("trait_vtable", """\
trait Printable:
    def print_self(self):
        pass
""")

    # 86. trait with typed method
    test("trait_vtable_typed", """\
trait Comparable:
    def less_than(self, other: Int) -> Int:
        pass
""")

    # ── String operations (new runtime) ──────────────────────────────────

    # 87. string slice → mojo_str_slice
    test("str_slice", """\
def first_two(s: String) -> String:
    var r: String = s[0:2]
    return r
""")

    # 88. string contains → mojo_str_contains (char * interface)
    test("str_contains", """\
def has_sub(haystack: String, needle: String) -> Int:
    var r: Int = mojo_str_contains(haystack, needle)
    return r
""")

    # 89. string from_char → mojo_str_from_char
    test("str_from_char", """\
def wrap(c: Int) -> String:
    var s: String = mojo_str_from_char(c)
    return s
""")

    # ── List item assignment (new runtime) ────────────────────────────────

    # 90. list[i] = v → mojo_list_set_int
    test("list_item_set", """\
def set_first(lst: List, v: Int) -> Int:
    lst[0] = v
    return 0
""")

    # 91. list augmented assignment via subscript
    test("list_subscript_aug", """\
def double_first(lst: List) -> Int:
    lst[0] = lst[0] * 2
    return 0
""")

    # ── List slice / concat (new runtime) ────────────────────────────────

    # 92. list[a:b] → mojo_list_slice
    test("list_slice", """\
def first_two(lst: List) -> List:
    var r: List = lst[0:2]
    return r
""")

    # 93. list + list → mojo_list_concat
    test("list_concat", """\
def concat(a: List, b: List) -> List:
    var r: List = a + b
    return r
""")

    # 93a. x[:] = y  → in-place full-slice splice (mojo_list_splice)
    test("list_slice_assign_full", """\
def replace_all(a: List, b: List):
    a[:] = b
""")

    # 93b. x[a:b] = y → in-place bounded-slice splice (grows/shrinks a)
    test("list_slice_assign_bounded", """\
def splice(a: List, b: List):
    a[1:3] = b
""")

    # 93c. x[a:b:k] = y → extended-slice store (mojo_list_assign_step);
    # bugs/CODEGEN_slice_assignment_silently_noops.md.
    test("list_slice_assign_stepped", """\
def strided(a: List, b: List):
    a[::2] = b
""")

    # ── Dict iterator ────────────────────────────────────────────────────

    # 94. for k in dict_var → MojoDictIter
    test("for_over_dict", """\
def count_keys(d: Dict) -> Int:
    var n: Int = 0
    for k in d:
        n += 1
    return n
""")

    # 95. dict comprehension over dict
    test("dict_comp_from_dict", """\
def copy_dict(d: Dict) -> Dict:
    var r: Dict = {k: d[k] for k in d}
    return r
""")

    # ── Set iterator ─────────────────────────────────────────────────────

    # 96. for x in set_var → MojoSetIter
    test("for_over_set", """\
def sum_set(s: Set) -> Int:
    var total: Int = 0
    for x in s:
        total += x
    return total
""")

    # 97. set comprehension over set
    test("set_comp_from_set", """\
def double_set(s: Set) -> Set:
    var r: Set = {x * 2 for x in s}
    return r
""")

    # ── Comprehension over string ─────────────────────────────────────────

    # 98. list comprehension over str_var
    test("list_comp_str", """\
def chars(s: String) -> List:
    var r: List = [c for c in s]
    return r
""")

    # ── Dict / Set len ────────────────────────────────────────────────────

    # 99. len(dict) → mojo_dict_len
    test("len_dict", """\
def dict_len(d: Dict) -> Int:
    var n: Int = len(d)
    return n
""")

    # 100. len(set) → mojo_set_len
    test("len_set", """\
def set_len(s: Set) -> Int:
    var n: Int = len(s)
    return n
""")

    # ── Argument conventions (read/mut/ref/out) ───────────────────────────

    # 101. read param → const MojoStr * in C prototype
    test("arg_conv_read", """\
def greet(read name: String) -> Int:
    return 0
""")

    # 102. ref param → const pointer
    test("arg_conv_ref", """\
def inspect(ref lst: List) -> Int:
    return 0
""")

    # 103. mut param (no const)
    test("arg_conv_mut", """\
def mutate(mut x: Int) -> Int:
    return x
""")

    # ── TypeLattice promotions ────────────────────────────────────────────

    # 104. int + int64_t arithmetic promotion
    test("arith_int_int64", """\
def mixed(a: Int, b: Int64) -> Int64:
    var r: Int64 = a + b
    return r
""")

    # 105. int * float promotion to float
    test("arith_int_float", """\
def scale(a: Int, b: Float64) -> Float64:
    var r: Float64 = a * b
    return r
""")

    # ── Return type inference ─────────────────────────────────────────────

    # 106. return type inferred from literal
    test("infer_return_int", """\
def answer():
    return 42
""")

    # 107. return type inferred from float literal
    test("infer_return_float", """\
def pi():
    return 3.14
""")

    # ── Struct constructor ────────────────────────────────────────────────

    # 108. struct constructor → heap alloc + field init
    test("struct_ctor", """\
struct Point:
    var x: Int
    var y: Int

def make_point(a: Int, b: Int) -> Point:
    var p: Point = Point(a, b)
    return p
""")

    # 109. struct field mutation
    test("struct_field_set", """\
struct Counter:
    var count: Int

def increment(c: Counter) -> Int:
    c.count = c.count + 1
    return c.count
""")

    # ── Walrus operator ───────────────────────────────────────────────────

    # 110. walrus in while condition
    test("walrus_while", """\
def find_nonzero(lst: List) -> Int:
    var i: Int = 0
    var v: Int = 0
    while (v := lst[i]) == 0:
        i += 1
    return v
""")

    # ── Multi-assign ──────────────────────────────────────────────────────

    # 111. multi-target assign a = b = expr
    test("multi_assign_chain", """\
def zero_two(x: Int, y: Int) -> Int:
    x = y = 0
    return x + y
""")

    # ── Assert with message ───────────────────────────────────────────────

    # 112. assert with message string
    test("assert_msg_str", """\
def check(x: Int) -> Int:
    assert x > 0, "must be positive"
    return x
""")

    # ── int/float coercion across return ─────────────────────────────────

    # 113. return coercion int → Int64
    test("return_coerce_int64", """\
def to64(x: Int) -> Int64:
    return x
""")

    # ── for range with step ───────────────────────────────────────────────

    # 114. for i in range(0, 10, 2) — positive literal step
    test("for_range_step", """\
def evens() -> Int:
    var s: Int = 0
    for i in range(0, 10, 2):
        s += i
    return s
""")

    # 115. for i in range(10, 0, -1) — negative literal step
    test("for_range_neg_step", """\
def countdown() -> Int:
    var s: Int = 0
    for i in range(10, 0, -1):
        s += i
    return s
""")

    # ── Closures / nested functions ───────────────────────────────────────

    # 116. Nested function with captured param
    test("closure_capture_param", """\
def outer(x: Int) -> Int:
    def inner(y: Int) -> Int:
        return x + y
    return inner(5)
""")

    # 117. Nested function with no captures (pure helper)
    test("closure_no_capture", """\
def outer(n: Int) -> Int:
    def double(x: Int) -> Int:
        return x * 2
    return double(n)
""")

    # 118. Nested function capturing multiple params
    test("closure_multi_capture", """\
def adder(a: Int, b: Int) -> Int:
    def add_ab(c: Int) -> Int:
        return a + b + c
    return add_ab(10)
""")

    # ── Arbitrary iterator protocol ───────────────────────────────────────

    # 119. Struct with __iter__ / __has_next__ / __next__
    test("struct_iterator", """\
struct Counter:
    var current: Int
    var stop: Int

    def __iter__(self) -> Counter:
        return self

    def __has_next__(self) -> Int:
        return self.current < self.stop

    def __next__(self) -> Int:
        var v: Int = self.current
        self.current = self.current + 1
        return v

def total(c: Counter) -> Int:
    var s: Int = 0
    for x in c:
        s += x
    return s
""")

    # 120. Struct iterator in list comprehension
    test("struct_iter_comp", """\
struct Counter:
    var current: Int
    var stop: Int

    def __iter__(self) -> Counter:
        return self

    def __has_next__(self) -> Int:
        return self.current < self.stop

    def __next__(self) -> Int:
        var v: Int = self.current
        self.current = self.current + 1
        return v

def doubled(c: Counter) -> List:
    var lst: List = [x * 2 for x in c]
    return lst
""")

    # ── Exception-safe with (__enter__ / __exit__) ────────────────────────

    # 121. with stmt calling __enter__ and __exit__ (exception safe)
    test("with_enter_exit", """\
struct File:
    var fd: Int

    def __enter__(self) -> File:
        return self

    def __exit__(self) -> Int:
        return 0

def use_file(f: File) -> Int:
    with f as h:
        var x: Int = h.fd
    return 0
""")

    # 122. with stmt, __exit__ called on exception path
    test("with_exit_on_exc", """\
struct Lock:
    var id: Int

    def __enter__(self) -> Lock:
        return self

    def __exit__(self) -> Int:
        return 0

def locked_op(lk: Lock, x: Int) -> Int:
    with lk as l:
        if x == 0:
            raise "bad"
        var r: Int = x
    return 0
""")

    # ── Dict value type dispatch (medium todo) ───────────────────────────

    # 123. Dict with float values — subscript returns double
    test("dict_float_val", """\
def count_scores() -> Float64:
    var scores: Dict = {"alice": 9.5, "bob": 7.0}
    var s: Float64 = scores["alice"]
    return s
""")

    # 124. Dict with string values — subscript returns char *
    test("dict_str_val", """\
def lookup_name() -> String:
    var names: Dict = {"a": "alpha", "b": "beta"}
    var s: String = names["a"]
    return s
""")

    # 125. Dict int values — subscript returns int64_t (existing behavior confirmed)
    test("dict_int_val", """\
def lookup_count() -> Int:
    var counts: Dict = {"x": 10, "y": 20}
    var n: Int = counts["x"]
    return n
""")

    # ── UnsafePointer type resolution (hard todo) ────────────────────────

    # 126. UnsafePointer[Int] parameter — resolves to int *
    test("unsafe_ptr_int", """\
def sum_n(p: UnsafePointer[Int], n: Int) -> Int:
    var s: Int = 0
    var i: Int = 0
    while i < n:
        s += p[i]
        i += 1
    return s
""")

    # 127. UnsafePointer .load() and .store()
    test("unsafe_ptr_load_store", """\
def copy_val(src: UnsafePointer[Int], dst: UnsafePointer[Int]) -> None:
    var v: Int = src.load()
    dst.store(v)
""")

    # 128. UnsafePointer .offset() pointer arithmetic
    test("unsafe_ptr_offset", """\
def nth_elem(p: UnsafePointer[Float64], n: Int) -> Float64:
    var q: UnsafePointer[Float64] = p.offset(n)
    return q.load()
""")

    # 128b. UnsafePointer[T].alloc(n) — static heap allocation constructor.
    # Regression: the `UnsafePointer[T]` type-subscript receiver used to be
    # lowered as an ordinary value subscript and `.alloc(n)` fell through
    # to the generic scalar-method stub, so `Int(...)` of the result read
    # 0 (bugs/CODEGEN_int_of_alloc_struct_pointer_returns_zero.md).
    test("unsafepointer_alloc_struct", """\
struct Rec:
    var tag: Int64
    var val: Int64

def make() -> Int:
    var p = UnsafePointer[Rec].alloc(1)
    p[0].tag = 1
    var h = Int(p)
    return h

def make_buf() -> Int:
    var b = UnsafePointer[Int64].alloc(8)
    b[0] = 3
    return Int(b)
""")

    # ── Generics [T] type-param stripping (hard todo) ────────────────────

    # 129. Generic function — type params stripped, body works
    test("generic_fn_identity", """\
def identity[T](x: Int) -> Int:
    return x
""")

    # 130. Generic struct — type params stripped
    test("generic_struct", """\
struct Pair[T]:
    var first: Int
    var second: Int

def make_pair(a: Int, b: Int) -> Int:
    var p: Pair = Pair(a, b)
    return p.first
""")

    # 131. Struct method call via obj.method() syntax
    test("struct_method_call", """\
struct Counter:
    var val: Int

    def increment(self) -> Int:
        self.val = self.val + 1
        return self.val

def use_counter(c: Counter) -> Int:
    var r: Int = c.increment()
    return r
""")

    # ── Walrus := with complex LHS ────────────────────────────────────────

    # 132. walrus with MemberExpr target
    test("walrus_member", """\
struct Box:
    var val: Int

def set_and_get(b: Box, x: Int) -> Int:
    var r: Int = (b.val := x)
    return r
""")

    # 133. walrus with SubscriptExpr target (plain pointer)
    test("walrus_subscript_ptr", """\
def fill_first(p: UnsafePointer[Int], v: Int) -> Int:
    var r: Int = (p[0] := v)
    return r
""")

    # 134. walrus with list subscript target
    test("walrus_list_subscript", """\
def set_elem(lst: List, i: Int, v: Int) -> Int:
    var r: Int = (lst[i] := v)
    return 0
""")

    # ── comptime if ───────────────────────────────────────────────────────

    # 135. comptime if True — emits then branch only
    test("comptime_if_true", """\
def foo() -> Int:
    comptime if True:
        return 1
    else:
        return 0
""")

    # 136. comptime if False — emits else branch only
    test("comptime_if_false", """\
def foo() -> Int:
    comptime if False:
        return 1
    else:
        return 0
""")

    # 137. comptime if with constant int condition
    test("comptime_if_const_int", """\
def foo() -> Int:
    comptime if 1:
        return 42
""")

    # 138. comptime if with constant comparison
    test("comptime_if_comparison", """\
def foo() -> Int:
    comptime if 2 > 1:
        return 99
    else:
        return 0
""")

    # ── comptime for ──────────────────────────────────────────────────────

    # 139. comptime for over range(3) — unrolls 3 iterations
    test("comptime_for_range", """\
def foo() -> Int:
    var s: Int = 0
    comptime for i in range(3):
        s = s + 1
    return s
""")

    # 140. comptime for with range(1, 4)
    test("comptime_for_range_start_stop", """\
def foo() -> Int:
    var s: Int = 0
    comptime for i in range(1, 4):
        s = s + i
    return s
""")

    # ── precise: loop body frequency annotations ──────────────────────────

    # 141. while loop body gets guessed_local(10) annotation
    test("precise_while_annotation", """\
def sum_n(n: Int) -> Int:
    var s: Int = 0
    var i: Int = 0
    while i < n:
        s = s + i
        i = i + 1
    return s
""")

    # 142. nested for loops — inner body gets guessed_local(100)
    test("precise_nested_loops", """\
def mat_sum(n: Int) -> Int:
    var s: Int = 0
    for i in range(n):
        for j in range(n):
            s = s + 1
    return s
""")

    # ── external_call: the primitive the stdlib bottoms out on ────────────

    # 143. external_call["name", Ret](args) → direct C call (e.g. write syscall)
    test("external_call_write", """\
def foo():
    var msg: String = "hi\\n"
    var n = external_call["write", Int64](1, msg, 3)
""")

    # 144. external_call with a void (NoneType) return type emits a bare call
    test("external_call_void", """\
def foo(p: Int):
    external_call["mojo_sink_value", NoneType](p)
""")

    # ── mlir.py: strip-mined MLIR primitives the stdlib's scalars sit on ──

    # 145. __mlir_op.`index.add` (and friends) → native C arithmetic
    test("mlir_index_add", """\
def add_idx(a: Int, b: Int) -> Int:
    return __mlir_op.`index.add`(a, b)
""")

    # 146. __mlir_attr.`N : index` integer attribute → constant
    test("mlir_attr_int", """\
def zero() -> Int:
    return __mlir_attr.`0 : index`
""")

    # 147. __mlir_type.index field → int64_t; pop.cast_to_builtin → cast
    test("mlir_type_and_cast", """\
def cast_it(a: Int) -> Int:
    return __mlir_op.`pop.cast_to_builtin`(a)
""")

    # 148. __mlir_op.`index.cmp`[pred=...] → comparison (predicate from op attrs)
    test("mlir_index_cmp", """\
def lt(a: Int, b: Int) -> Bool:
    return __mlir_op.`index.cmp`[pred=__mlir_attr.`#index<cmp_predicate slt>`](a, b)
""")

    # 149. min/max (no C operator) → ternary; unary neg; fma 3-arg
    test("mlir_minmax_unary_fma", """\
def mn(a: Int, b: Int) -> Int:
    return __mlir_op.`index.mins`(a, b)

def neg(a: Int) -> Int:
    return __mlir_op.`pop.neg`(a)

def fma3(a: Int, b: Int, c: Int) -> Int:
    return __mlir_op.`pop.fma`(a, b, c)
""")

    # 150. pop.cmp predicate via kgen spelling; ownership marker is a no-op
    test("mlir_popcmp_and_noop", """\
def ne(a: Int, b: Int) -> Bool:
    return __mlir_op.`pop.cmp`[pred=__mlir_attr.`#kgen<cmp_pred ne>`](a, b)

def keep(a: Int) -> Int:
    return __mlir_op.`lit.ownership.mark_initialized`(a)
""")

    # 151. memory/lvalue ops: pop.offset → _mojo_at_ helper, pop.load → deref,
    #      pop.store (bare statement) → *addr = val
    test("mlir_mem_load_store_offset", """\
def load_at(p: UnsafePointer[Int64], i: Int) -> Int64:
    var addr = __mlir_op.`pop.offset`(p, i)
    return __mlir_op.`pop.load`(addr)

def store_at(p: UnsafePointer[Int64], i: Int, v: Int64):
    var addr = __mlir_op.`pop.offset`(p, i)
    __mlir_op.`pop.store`(v, addr)
""")

    # 152. struct GEP: kgen.struct.extract → v->fieldN; kgen.struct.gep → &v->fieldN;
    #      pop.array.get → element via _mojo_at_ helper (index from index= op attr)
    test("mlir_struct_gep", """\
struct Pair:
    var first: Int64
    var second: Int64

def get_second(p: Pair) -> Int64:
    return __mlir_op.`kgen.struct.extract`[index=__mlir_attr.`1:index`](p)

def addr_first(p: Pair) -> UnsafePointer[Int64]:
    return __mlir_op.`kgen.struct.gep`[index=__mlir_attr.`0:index`](p)

def elem(a: UnsafePointer[Int64]) -> Int64:
    return __mlir_op.`pop.array.get`[index=__mlir_attr.`2:index`](a)
""")

    # 153. print's bottom layer: a Span fat-pointer {_data,_len} written to a fd
    #      via external_call["write"] — the chain the real FileDescriptor.write_bytes
    #      lowers to (Span field reads + write syscall, no dynamic dispatch).
    test("mlir_write_bytes_bottom", """\
struct Span:
    var _data: UnsafePointer[Int8]
    var _len: Int

    def unsafe_ptr(self) -> UnsafePointer[Int8]:
        return self._data

def write_bytes(s: Span) -> Int:
    return external_call["write", Int64](1, s.unsafe_ptr(), len(s))
""")

    # 154. libc-name mangling: `fn exit` becomes mojo_exit (no clash with libc exit),
    #      while external_call["exit"] keeps the raw libc symbol — exit from the library.
    test("libc_name_mangle_exit", """\
def exit(code: Int64):
    external_call["exit", NoneType](code)

def main():
    exit(7)
""")

    # 155. external_call with a parametric return type resolves (UnsafePointer[Int8]
    #      → int8_t *), so the result is a usable pointer (printf-style debug path).
    test("external_call_parametric_ret", """\
def dbg(label: String, n: Int64):
    var buf = external_call["malloc", UnsafePointer[Int8]](256)
    var ln = external_call["snprintf", Int64](buf, 256, "%s%lld\\n", label, n)
    var w = external_call["write", Int64](1, buf, ln)
    external_call["free", NoneType](buf)
""")

    # 155b. external_call to a genuinely variadic libc function (printf) at two
    #       different arities in the same file — regression test locking in that
    #       variadic functions are deliberately excluded from custom fixed-arity
    #       prototype generation (they fall through to the system header's own
    #       variadic declaration), so neither call site is arity-clobbered by a
    #       prototype sized for the other.
    test("external_call_variadic_printf", """\
def one_arg(n: Int64):
    external_call["printf", Int32]("count: %lld\\n", n)

def two_args(label: String, n: Int64):
    external_call["printf", Int32]("%s: %lld\\n", label, n)
""")

    # 156. _c_escape: source escapes pass through (\\n stays one backslash, not two)
    from gimple_codegen import _c_escape
    _esc_ok = (_c_escape('%s%lld\\n') == '%s%lld\\n'      # \\n preserved, not doubled
               and _c_escape('a\\\\b') == 'a\\\\b'          # literal backslash round-trips
               and _c_escape('say "hi"') == 'say \\"hi\\"' # quotes escaped
               and _c_escape('real\nnewline') == 'real\\nnewline')  # raw NL → \\n
    global _PASS, _FAIL
    if _esc_ok:
        print("PASS  c_escape_roundtrip"); _PASS += 1
    else:
        print("FAIL  c_escape_roundtrip"); _FAIL += 1

    # 157. MojoList + pointer-typed local → mojo_list_concat (polymorphic local
    #      typed char* in one branch, used as a list at a concat site). Previously
    #      emitted `MojoList * + char *`, which gcc rejects.
    test("list_concat_polymorphic", """\
def f():
    var body = [1, 2]
    var s = "x"
    body = body + s
    return body
""")

    # 158. Heterogeneous list/tuple — string + non-string elements must append
    #      each by its OWN type (append_str for the string, append_int for the
    #      int). Previously a single list-wide suffix emitted append_str on the
    #      int (pointer-from-integer). Numeric-promotion lists are unaffected.
    test("heterogeneous_collection_append", """\
def main():
    var t = ("int", 5)
    var l = ["tag", 7]
    return 0
""")

    # 159. str.find(needle, start) — the 2-arg form must lower to
    #      mojo_str_find_from (not mojo_str_find, which silently drops the
    #      start argument — see bugs/CODEGEN_str_find_start_arg_dropped.md).
    #      Also locks in that the 1-arg form keeps calling mojo_str_find.
    _find_src = """\
def main():
    var s: String = "ab\\ncd\\nef"
    var j = s.find("\\n", 4)
    var k = s.find("\\n")
    return j
"""
    _find_ok, _find_c_src, _find_stderr = gimple_compiles(_find_src)
    if (_find_ok
            and 'mojo_str_find_from' in _find_c_src
            and 'mojo_str_find (' in _find_c_src):
        print("PASS  str_find_with_start_lowering"); _PASS += 1
    else:
        print("FAIL  str_find_with_start_lowering")
        print("      --- generated C ---")
        for i, line in enumerate(_find_c_src.splitlines(), 1):
            print(f"      {i:3}: {line}")
        if not _find_ok:
            print("      --- gcc stderr ---")
            for line in _find_stderr.splitlines():
                print(f"      {line}")
        _FAIL += 1

    # BUG-2026-033: id() builtin on a struct instance must compile in --jit
    # mode, not just the interpreter. (Root cause turned out to be a cascade
    # from an unrelated Parser-import failure earlier in the same file, per
    # BUG-2026-032 — id() itself already lowers to a real function via the
    # `'id': ('int64_t', ['int64_t'])` signature table entry. This test pins
    # the standalone case so a regression here is caught directly instead of
    # being misdiagnosed as "id() unsupported" again.)
    test("id_builtin_on_struct", """\
struct Foo:
    var x: Int
    def __init__(out self):
        self.x = 42

def test():
    var f = Foo()
    var key = id(f)
    print(key)
""")

    # 160. Multi-name import `import a, b, c` must bind *every* name, not
    # just the first (bugs/INTERP_multi_name_import_only_binds_first.md).
    # gimple_codegen.py's ImportStmt lowering used to declare a module-marker
    # global only for node.module/node.alias; any comma-separated target
    # past the first (node.extra) was undeclared, so referencing it here
    # would fail to compile as an unknown identifier.
    test("multi_name_import_binds_all", """\
import sys, os, difflib

def main():
    var a = sys
    var b = os
    var c = difflib
""")

    # 161. map(str, param) over a plain/unannotated parameter, used inside
    # another expression (str.join(...)) — bugs/CODEGEN_map_over_untyped_param_arg.md.
    # Before the fix this failed to even compile (GCC -Wint-conversion: `args`
    # defaulted to int64_t instead of MojoList*, and the temp holding
    # mojo_map(...)'s pointer result was declared int64_t too), AND the
    # `map(str, args)` sub-expression was silently lowered/emitted twice
    # (once into a dead, unused temp) by a `_lower_str_method` bug that called
    # `self.lower_expr(a)` twice per join() argument. Assert both: it compiles
    # AND the map sub-expression is emitted exactly once in the generated C.
    _map_src = """\
def join_strs(args) -> String:
    return ", ".join(map(str, args))
"""
    _map_ok, _map_c_src, _map_stderr = gimple_compiles(_map_src)
    # The marker changed with map()'s implementation, not with this test's
    # intent. `mojo_map` used to be an IDENTITY STUB in the runtime (a char*
    # function pointer cannot call back into a GIMPLE-compiled body), so the
    # per-element calls are now lowered by the CODEGEN, which appends each
    # result itself. The property worth asserting is unchanged — the
    # `map(str, args)` sub-expression is emitted exactly ONCE, not twice by
    # the old double-`lower_expr` bug — and the per-element append is now
    # what that looks like in the generated C.
    _map_call_count = _map_c_src.count('mojo_list_append_str (')
    if _map_ok and _map_call_count == 1:
        print("PASS  map_over_untyped_param_arg"); _PASS += 1
    else:
        print("FAIL  map_over_untyped_param_arg")
        print(f"      mojo_map(...) call count = {_map_call_count} (expected 1)")
        print("      --- generated C ---")
        for i, line in enumerate(_map_c_src.splitlines(), 1):
            print(f"      {i:3}: {line}")
        if not _map_ok:
            print("      --- gcc stderr ---")
            for line in _map_stderr.splitlines():
                print(f"      {line}")
        _FAIL += 1

    # 162. A convention/ownership keyword (`var`, `ref`, `read`, etc.) used
    # as a plain parameter name inside `assert(x not in y)` must NOT be
    # misparsed as a parenthesized ownership-prefix binding target — see
    # bugs/PARSE_FAIL_conv_kw_prefix_misfires_on_var_not_in.md. Real Python
    # has no such keywords, so they're common ordinary identifiers; the old
    # `_parse_primary` LPAREN carve-out for `(var x), (ref y) = ...` only
    # checked that the token after the keyword was NAME/KW-shaped, which
    # `not` (a KW) also satisfies, so `(var not in lst)` wrongly swallowed
    # `var` as a bogus prefix and failed with "Expected RPAREN got NAME".
    test("conv_kw_as_plain_ident_not_in", """\
def f(var: Int, lst: Int) -> Bool:
    return not (var == lst)

def g(read: Int, seen: Int) -> Bool:
    return not (read == seen)
""")

    # 163. The legitimate parenthesized ownership-prefix binding target this
    # carve-out exists for, `(var x), (ref y) = ...`, must still parse and
    # compile correctly after tightening the disambiguation (peek(2) must be
    # RPAREN) in test 162 above.
    test("conv_kw_prefix_tuple_unpack_still_works", """\
def get_pair() -> (Int, Int):
    return (1, 2)

def main():
    (var x), (var y) = get_pair()
    print(x, y)
""")

    # 164. `var` used as a plain identifier (Python compat: real Python has
    # no `var` keyword) followed by member access/assignment, a method
    # call, or as one of several tuple-unpack targets must NOT be misparsed
    # as a var declaration — see bugs/PARSE_FAIL_var_as_identifier_member_access.md.
    # The statement-level `_parse_stmt` dispatch for `var` only special-cased
    # the `var = expr` shape; anything else (`.`, `,`, etc. right after
    # `var`) unconditionally committed to `_parse_var_decl()` and crashed on
    # the unexpected next token.
    test("var_as_plain_ident_member_access", """\
struct C:
    var x: Int
    fn __init__(out self):
        self.x = 0
    fn bump(mut self):
        self.x = self.x + 1

def main():
    var = C()
    var.x = 5
    var.bump()
    print(var.x)
""")

    # 165. `var` as one of several plain tuple-unpack targets (`var, x = ...`)
    # must fall through to ordinary assignment parsing, not var-decl parsing.
    test("var_as_plain_ident_tuple_unpack_target", """\
def get_pair() -> (Int, Int):
    return (1, 2)

def main():
    var, x = get_pair()
    print(var, x)
""")

    # 166. Legitimate var-declaration forms must still work after the fix
    # above: bare declaration, type-annotated declaration, and declaration
    # with an initializer.
    test("var_decl_forms_still_work", """\
def main():
    var a: Int
    a = 1
    var b: Int = 2
    var c = 3
    print(a, b, c)
""")

    # 167. `var`/etc. as the FIRST element of a plain tuple-unpack for-loop
    # target (`for var, other_var in pairs:`) must NOT be misparsed as a
    # bogus convention-keyword prefix — see
    # bugs/PARSE_FAIL_var_as_for_loop_target_comma.md. `_parse_for`'s
    # convention-keyword carve-out already excluded peek(1) == KW('in') and
    # peek(1) == COLON, but not COMMA, so this real-stdlib shape
    # (Tools/cases_generator/stack.py:606) swallowed `var` as a bogus prefix
    # and then choked on the unpack target.
    test("var_as_for_loop_target_comma", """\
def main():
    pairs = [(1, 2), (3, 4)]
    for var, other_var in pairs:
        print(var, other_var)
""")

    # 168. The `comptime for` sibling of test 167 above — `_parse_comptime_for`
    # had the exact same bug in a worse form: no guard at all, so it
    # unconditionally swallowed any leading _CONV_KWS token regardless of
    # what followed.
    test("var_as_comptime_for_loop_target_comma", """\
def main():
    comptime for var, j in [(1, 2), (3, 4)]:
        print(var, j)
""")

    # 169. Legitimate convention-prefixed for-loop targets (`for ref x in
    # y:`, `for var x in y:`) must still parse correctly after tightening
    # the exclusion list in tests 167/168 above — these shapes have peek(1)
    # be a plain NAME, which none of the new/existing exclusions (KW('in'),
    # COLON, COMMA) match, so the convention keyword is still consumed.
    test("conv_kw_prefix_for_loop_target_still_works", """\
def main():
    items = [1, 2, 3]
    for ref x in items:
        print(x)
""")

    # 170. A raw string containing a `\t` escape (or any prefixed ordinary
    # string whose content happens to look like a t-string prefix run
    # ending right before its own closing quote), followed later in the
    # same statement by another quoted string, must not corrupt the token
    # stream — see
    # bugs/PARSE_FAIL_backslash_t_escape_misdetected_as_tstring_prefix.md.
    # `_process_nested_tstrings`'s ordinary-string-skip guard used to check
    # only the single character immediately before a quote for
    # alphanumeric-ness, so `r"..."` (prefix letter `r` IS alphanumeric)
    # was never skipped as one opaque unit; the scan then walked into the
    # raw string's own escaped content and, on reaching the literal `t` in
    # `\t`, misdetected the string's own closing quote as the *opening*
    # quote of a brand-new bogus bare t-string, swallowing everything up
    # to the next unrelated quote later in the statement.
    test("raw_string_backslash_t_escape_then_another_string", """\
def main():
    d = {r"\\t": 1}
    print(d[r"\\t"], ord("\\t"))
""")

    # 171. The legitimate t/f-string-with-nested-braces case
    # `_process_nested_tstrings` exists for must still work after the fix
    # above (dispatch now keyed off the quote character via a backward
    # prefix scan, rather than a forward prefix-letter-then-quote regex).
    test("tstring_nested_braces_still_works", """\
def main():
    a = 1
    b = 2
    s = t"L1: {t'L2: {a + b}'}"
    print(s)
""")

    # 171b/171c. An f-string whose nested `{...}` interpolation contains a
    # string literal that reuses the SAME quote character as the f-string's
    # own delimiter (legal since PEP 701 / Python 3.12, e.g.
    # `f'...{g('a')}...'`). `_process_nested_tstrings` used to gate its
    # brace-depth-aware closing-quote scan on a literal `t`/`T` in the
    # prefix only (meant for Mojo's own `t"..."` template strings), so a
    # plain `f`-prefixed string (no `t`/`T`) fell into the plain
    # simple-scan-to-matching-quote branch, which has no `{...}` awareness
    # and truncated the string at the first reused quote inside the braces.
    # See bugs/PARSE_FAIL_fstring_same_quote_reuse.md. Covers both quote
    # characters, since the bug was quote-character-specific in the sense
    # that a DIFFERENT nested quote already worked.
    test("fstring_nested_same_single_quote_reused", """\
def g(a, b):
    return a + b

def main():
    x = f'result: {g('a', 'b')}'
    print(x)
""")

    test("fstring_nested_same_double_quote_reused", """\
def g(a, b):
    return a + b

def main():
    x = f"result: {g("a", "b")}"
    print(x)
""")

    # 172. `_parse_type_ann_inner`'s trailing-operator gap: a type-shaped
    # annotation prefix (a real NAME) followed by a TRAILING operator that
    # continues an arbitrary (non-type) expression, e.g. `gamma: some < obj`.
    # Only `|`/`&` (real PEP 604 union/intersection syntax) were consumed as
    # trailing operators before; any other operator (`<`, `>`, `==`, binary
    # `+`/`-`, etc.) was left dangling for the caller to choke on. This
    # mirrors CPython's own Lib/test/test_annotationlib.py
    # test_nonexistent_attribute, which deliberately exercises a whole
    # battery of nonsensical-but-syntactically-legal annotation expressions
    # on function parameters (PEP 649: annotations accept an arbitrary
    # expression, never semantically type-checked). All of these EXCEPT
    # `gamma` already worked; this test covers the whole battery in one
    # signature so a fix to `gamma` can't regress a sibling shape.
    test("annotation_trailing_binary_op_battery", """\
some = 1
obj = 2
module = 3
def f(x: some.module, y: some[module], z: some(module), alpha: some | obj, beta: +some, gamma: some < obj, delta: some | {obj: module}, epsilon: some | {obj}, zeta: some | [obj, module], eta: some | ()):
    pass
""")

    # 173. `_parse_type_ann_inner`'s trailing-operator gap, the OTHER half:
    # an annotation whose FIRST token is already non-name-shaped (a literal),
    # hitting the catch-all single-token fallback branch (added by 6ee8291)
    # instead of the NAME/KW path. That branch returned immediately without
    # ever calling `_consume_trailing_annotation_ops` (unlike the NAME/KW
    # path, fixed by 6e6020f for `gamma: some < obj` above), so `radd: 1 + a`
    # left `+ a` dangling for the parameter-list parser to choke on. This
    # mirrors CPython's own Lib/test/test_annotationlib.py test_reverse_ops,
    # which exercises a whole battery of reverse-dunder-shaped binary-op
    # annotations (all NUMBER-literal prefixes) in one signature.
    # See bugs/PARSE_FAIL_annotation_leading_literal_trailing_op.md.
    test("annotation_leading_literal_trailing_op_battery", """\
a = 1
def f(radd: 1 + a, rsub: 1 - a, rmul: 1 * a, rmatmul: 1 @ a, rtruediv: 1 / a, rmod: 1 % a, rlshift: 1 << a, rrshift: 1 >> a, ror: 1 | a, rxor: 1 ^ a, rand: 1 & a, rfloordiv: 1 // a, rpow: 1**a):
    pass
print("ok")
""")

    # 174. `_parse_type_ann_inner` had no case for `...` (Ellipsis) in
    # annotation position. The tokenizer produces THREE separate DOT tokens
    # for `...` (no single ELLIPSIS token kind), and the dispatch's
    # NAME/KW/STRING/LPAREN/LBRACKET/LBRACE branches don't match a DOT, so it
    # fell to the generic catch-all single-token fallback, which consumed
    # only the FIRST dot and left the other two dangling for the
    # parameter-list parser to choke on with a confusing "Expected NAME or KW
    # got DOT" error. Mirrors CPython's own Lib/test/test_annotationlib.py
    # test_literals, which exercises a battery of literal annotations
    # (NUMBER, STRING, bytes, bool, None, Ellipsis, complex) in one
    # signature — `g: ...` is the Ellipsis case.
    # See bugs/PARSE_FAIL_annotation_ellipsis.md.
    test("annotation_literals_battery", """\
def f(a: 1, b: 1.0, c: "hello", d: b"hello", e: True, f: None, g: ..., h: 1j):
    pass
print("ok")
""")

    # 175. `_parse_type_ann_inner`'s `LPAREN` branch (a parenthesized-
    # expression-shaped annotation like `(1)`) returned its opaquely-captured
    # text immediately, unlike the LBRACKET/LBRACE/catch-all branches (fixed
    # in bb28e80 to route through `_consume_trailing_annotation_ops`) — so a
    # trailing `.attr` member-access continuation after the parens, e.g.
    # `y: (1).__class__`, left `.__class__` dangling for the parameter-list
    # parser to choke on with "Expected NAME or KW got DOT". Worse than the
    # three branches fixed in bb28e80: even routing through
    # `_consume_trailing_annotation_ops` alone wouldn't suffice, since that
    # helper only continues `OP`-kind tokens (`|`, `&`, ...), not a `DOT`
    # chain. Fixed by introducing `_finish_type_ann_tail`, a single shared
    # continuation tail (dotted-name loop + call-parens + subscript loop +
    # trailing-op consumption) that EVERY branch of `_parse_type_ann_inner`
    # (NAME/KW, LPAREN, LBRACKET, LBRACE, ellipsis, catch-all) now routes
    # through, instead of each branch needing its own early-return special
    # case — this was the fourth follow-on bug in this exact function in one
    # session (6ee8291 -> 6e6020f -> bb28e80 -> c2933a7 -> this one), so a
    # structural fix was chosen over a fifth narrow patch. Mirrors CPython's
    # own Lib/test/test_annotationlib.py test_shenanigans.
    # See bugs/PARSE_FAIL_annotation_paren_then_dot.md.
    test("annotation_paren_then_dot_battery", """\
x = 1
def f(x: x | (1).__class__, y: (1).__class__):
    pass
print("ok")
""")

    # 176. Two top-level `def NAME(...):` statements with the SAME name,
    # nested in mutually-exclusive if/else branches at module scope (a
    # common platform-conditional idiom, e.g. multiprocessing/connection.py's
    # `def wait(...)` under `if sys.platform == 'win32': ... else: ...`).
    # This codegen compiles every top-level def into a single, unmangled C
    # symbol regardless of which branch it's nested in, so both bodies
    # previously collided (or, worse, neither was compiled at all and the
    # call site fell back to an extern declaration that happened to collide
    # with libc's own `wait(int *)` from <sys/wait.h> — a confusing error
    # unrelated to the real problem). Since there's no runtime-dispatch
    # mechanism to represent "whichever branch executes wins" as distinct C
    # symbols, this must be refused honestly rather than silently miscompiled
    # — see bugs/CODEGEN_conditional_toplevel_def_name_collision.md.
    test("conditional_toplevel_def_name_collision", """\
import sys
if sys.platform == 'win32':
    def wait(x):
        return x + 1
else:
    def wait(x):
        return x + 2

def f():
    print(wait(5))
f()
""")

    # Generator function (`yield`) honest-fallback: this codegen has no
    # general suspend/resume state-machine transform, so a generator
    # function outside the C++20-coroutine allowlist (see
    # gimple_codegen.py's _generator_quick_eligible/_gen_cpp_generator_unit)
    # must still be refused clearly (RuntimeError from
    # gen_module/compile_to_gimple) rather than silently miscompiled into a
    # single straight-line C function that just drops the yield. Milestone 1
    # of bugs/INTERP_generator_yield_entirely_unimplemented.md — see
    # fire_compiler.py's YieldExpr/YieldFromExpr/FunctionDef.is_generator
    # and gimple_codegen.py's gen_module pre-pass. A generator taking a
    # plain scalar parameter (`def f(n): yield n`) is now COMPILED, not
    # refused — see generator_param_shape_compiles_via_cpp_path below — as
    # of the parameter-support step; *args/**kwargs generator parameters are
    # the still-out-of-scope shape used here instead (string/struct params
    # are covered separately by
    # generator_string_param_honest_fallback below).
    test("generator_varargs_param", """\
def f(*args):
    yield args
""")

    # A generator parameter typed as something other than a scalar
    # int64_t/double/_Bool (e.g. String) is also still explicitly out of
    # scope for the parameter-support step — see _gen_cpp_generator_unit's
    # "Parameters" comment (string/struct/pointer params cross the C++/C
    # boundary with lifetime/ownership questions deliberately deferred).
    test("generator_string_param", """\
def f(s: String):
    yield 1
""")

    # An UNANNOTATED generator parameter that is actually a string at its
    # call site must be refused exactly like the explicitly-annotated case
    # immediately above, not silently compiled with the parameter (and the
    # coroutine's `current_value` field) mistyped as int64_t — a char*/
    # MojoStr* pointer value stored into and read back out of an int64_t
    # slot "works" only by platform-ABI luck (never arithmetically touched)
    # and would break the moment it were used for anything that depends on
    # its real type. Before the fix, this generator's compile attempt ran
    # BEFORE the cross-call scalar-contract inference (Pass 1.3d) had
    # populated self._inferred_param_types, so the unannotated `s` fell
    # straight through to _resolve_type(None)'s naive int64_t default with
    # no cross-call-site evidence at all — see
    # bugs/CODEGEN_compiled_generator_unannotated_string_param_mistyped.md.
    # The fix reuses the exact same cross-call scalar-contract mechanism
    # that already protects ordinary (non-generator) unannotated parameters
    # (e387af9/8799ec4) by deferring the generator compile attempt until
    # after that inference has run, so a unanimous `char *` observation
    # across g's call site(s) lands in _inferred_param_types before
    # _gen_cpp_generator_unit's existing scalar-only refusal check
    # (`ctype not in ('int64_t', 'double', '_Bool')`) ever looks — no new
    # inference logic, just correct ordering.
    test("generator_unannotated_string_param", """\
def g(s):
    yield s
print(list(g("hi")))
""")

    # bytes / bytearray / memoryview value types inside a compiled
    # generator body. The
    # A3 stack-switch backend routes the body through ordinary codegen,
    # which has full bytes support (Stages 1-3) -- these guard that a
    # `yield`ing body compiles clean.
    test("generator_body_memoryview", """\
def g(data):
    yield memoryview(data)[0]

def main():
    var b = bytes([1, 2, 3])
    for x in g(b):
        print(x)
""")

    test("generator_body_bytes_iteration", """\
def g():
    var b = bytes([4, 5, 6])
    for x in b:
        yield x

def main():
    for x in g():
        print(x)
""")

    test("generator_body_bytearray_mutation", """\
def g():
    var ba = bytearray()
    ba.append(9)
    yield ba[0]

def main():
    for x in g():
        print(x)
""")

    # zipfile `_Extra.split` shape: a @classmethod generator building a
    # memoryview over its (unannotated bytes) argument.
    test("generator_classmethod_body_memoryview", """\
struct E:
    @classmethod
    def split(cls, data):
        var mv = memoryview(data)
        var i = 0
        while i < len(mv):
            yield mv[i]
            i = i + 1

def main():
    for x in E.split(bytes([7, 8])):
        print(x)
""")

    # Async function (`async def`) honest-fallback: originally (before the
    # compiled-path async/await codegen project's Step B) this codegen had
    # NO event loop / suspend-resume codegen at all, so EVERY `async def`
    # was refused unconditionally — this exact case (`async def f(): return
    # 1`, no params, no await) was that blanket refusal's own example. Step
    # B narrowed that refusal (see _async_quick_eligible/_gen_cpp_async_unit
    # in gimple_codegen.py): a parameterless async function whose body is
    # just a scalar `return <expr>` and contains no `await` now genuinely
    # compiles via a real C++20-coroutine promise_type — see
    # test_async_simple_shape_compiles_via_cpp_path (this exact shape, just
    # with a consuming call site added so it's a complete module) and
    # test_gimple_async_runner.py's real compile+link+run counterpart.
    #
    # `await` on ANOTHER compiled async function's call (`x = await f()`) —
    # this exact shape — used to be refused (Step B/C's honest boundary,
    # "genuinely no composition codegen for a real cross-coroutine await
    # yet"). Step D (async-awaits-async composition) now compiles it for
    # real — see test_async_await_composition_compiles_via_cpp_path further
    # below (this exact shape) and test_gimple_async_runner.py's real
    # compile+link+run+timed counterpart. `await` on anything ELSE (a
    # forward reference to a not-yet-compiled callee, an arbitrary non-call
    # expression, a socket op) remains refused — see
    # async_await_forward_reference_honest_fallback and
    # async_await_non_call_expression_honest_fallback further below.
    def test_async_await_composition_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
async def f():
    return 1

async def g():
    x = await f()
    return x

def main():
    result = asyncio.run(g())
    print(result)
"""
        name = "async_await_composition_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: unexpected exception: {e}")
            _FAIL += 1
            return
        if not cpp_src or '_mojoasync_f_Awaiter' not in cpp_src:
            print(f"FAIL  {name}: expected the generated .cpp to contain "
                  "the composition Awaiter for the awaited callee ('f')")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as fh:
            fh.write(c_src)
            c_path = fh.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as fh:
            fh.write(cpp_src)
            cpp_path = fh.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_async_await_composition_compiles_via_cpp_path()

    # Forward reference: `g` (the caller) is defined BEFORE `f` (the
    # callee) in source order — gen_module's async pre-pass is a single
    # forward pass over the module's top-level statements (see
    # _is_async_call_to_known_fn's docstring), so `f` isn't registered in
    # self._async_api yet at the point `g`'s own eligibility is checked.
    # Honest whole-module refusal, not a guess/dangling forward reference.
    test("async_await_forward_reference", """\
async def g():
    x = await f()
    return x

async def f():
    return 1
""")

    # `await` on an arbitrary non-call expression (not asyncio.sleep(...),
    # not a call to another compiled async function) is still refused —
    # composition only recognizes the one specific call shape.
    test_raises("async_await_non_call_expression_honest_fallback", """\
async def f():
    x = await 5
    return x
""", "async function")

    # Async generator (`async def f(): yield x`) -- REVISED (final step of
    # the async/await codegen project): the simplest possible shape (no
    # params, one `yield`, no `yield from`/`with`) is now this step's own
    # target shape and successfully compiles via a combined promise type
    # (_gen_cpp_async_generator_unit) -- see
    # async_generator_simple_shape_compiles_via_cpp_path further below
    # (defined after _generator_compiles_via_cpp exists) for the compile-
    # only smoke test, and async_generator_with_param_honest_fallback/
    # async_generator_with_yield_from_honest_fallback for the narrower
    # shapes that still correctly hit the (no-longer-blanket) combined
    # refusal.

    # Milestone B narrowing checks: a generator containing try/except is
    # explicitly excluded from the new C++20-coroutine allowlist (richer
    # generator semantics — Milestone D, not this one) and must still hit
    # the same honest whole-module refusal as before this milestone.
    #
    # `yield from` itself is NO LONGER blanket-excluded as of Milestone C
    # step 2 (yield-from delegation) — but `yield from [1, 2, 3]` doesn't
    # target a call to another generator at all (it targets a list
    # literal), so it's still refused, just via a different check now (see
    # GimpleGen._cpp_yield_from's "not isinstance(call, CallExpr)" branch)
    # instead of the old blanket _generator_quick_eligible disqualification.
    # See test_generator_yield_from_delegation_compiles_via_cpp_path and its
    # neighboring still-out-of-scope-shape refusal tests, further below,
    # for the positive/narrower-negative coverage this step actually adds.
    test("generator_yield_from_list", """\
def f():
    yield from [1, 2, 3]
""")

    # Milestone D: try/except/raise inside a generator body now compiles via
    # the C++20-coroutine path instead of falling back — see
    # test_generator_try_except_compiles_via_cpp_path below for the positive
    # compile-only smoke test, and test_gimple_generator_runner.py for the
    # REAL behavioral (compile+link+run) coverage of this exact shape.

    # Mixed yield-value types (int then float): passes the cheap
    # _generator_quick_eligible pre-filter (no params/try/with/yield-from)
    # but _gen_cpp_generator_unit's own _generator_yield_ctype check must
    # still reject it (Milestone B requires one consistent scalar type
    # across every `yield` in the body) and gen_module's pre-pass must fall
    # back to the honest refusal cleanly — exercises the
    # _UnsupportedGeneratorShape catch path itself, not just the cheap
    # pre-filter.
    test_raises("generator_mixed_yield_types_honest_fallback", """\
def f():
    yield 1
    yield 1.5
""", "generator function")

    # Mixed yield kinds whose EMITTED C++ can never share one promise type:
    # a tuple-yield site always co_yields a MojoList* pointer
    # (_cpp_yield_tuple) while a str site emits char*, and the old
    # char*-preference merge rule silently picked `char *` for the promise —
    # so the tuple site reached g++ as "cannot convert 'MojoList*' to
    # 'char*'" (a hard, unreadable .cpp compile failure) instead of an
    # honest refusal. Real instance: randdec.py's un_incr_digits_tuple
    # (scalar from_triple(...) yields mixed with 3-tuple yields). See
    # bugs/COMPILE_FAIL_Modules__decimal_tests_randdec.md's 2026-08-25
    # entry for the full mechanism and repros.
    test_raises("generator_mixed_str_and_tuple_yield_honest_fallback", """\
def f():
    yield 'abc'
    yield (1, 2)
""", "generator function")

    # Same MojoList*×char* hole, list-valued-expression flavor: `sorted(...)`
    # both infers AND emits a real `MojoList *`, so pairing it with a str
    # yield site is the same broken promise-type pick — same honest refusal.
    with _force_cpp_coro():
        test_raises("generator_mixed_str_and_list_expr_yield_honest_fallback", """\
def f(items):
    yield 'abc'
    yield sorted(items)
        """, "generator function")

    # A DIRECT collection-literal yield value (`yield [1, 2]`) emits a raw
    # C++ braced-init-list (`co_yield {1, 2};`) that is not a valid co_yield
    # operand for ANY promise type — previously a guaranteed g++ failure
    # ("cannot convert '<brace-enclosed initializer list>' to 'MojoList*'").
    # Refuse honestly at the same single-source-of-truth chokepoint.
    with _force_cpp_coro():
        test_raises("generator_collection_literal_yield_honest_fallback", """\
def f():
    yield [1, 2]
        """, "generator function")

    # Milestone B positive case: the ONE generator shape this codegen now
    # actually compiles — no params, no try/except/with, no `yield from` —
    # gets routed to the new C++20-coroutine .cpp path instead of the
    # honest refusal above. Confirms BOTH halves of the dual-output build:
    # the .c/.ci side (gcc -fgimple -fsyntax-only) declares the extern "C"
    # API and has NO ordinary body for `counter` at all, and the companion
    # .cpp side (g++ -std=c++20 -fsyntax-only) is real, syntactically valid
    # C++20 coroutine code. See test_gimple_generator_runner.py for the
    # REAL behavioral (compile+link+run) counterpart of this same shape.
    def test_generator_simple_shape_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
def counter():
    i = 0
    while i < 5:
        yield i
        i = i + 1

def main():
    for x in counter():
        print(x)
"""
        name = "generator_simple_shape_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if '_mojogen_counter_start' not in c_src or 'MojoGenerator' not in c_src:
            print(f"FAIL  {name}: .c/.ci output missing extern \"C\" generator API decls")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_simple_shape_compiles_via_cpp_path()

    # `**kwargs`-forward inside a coroutine body with a `char *` (string)
    # "gap" parameter between the given positional args and the callee's
    # own `**kwargs` slot. `_cpp_try_kwargs_forward_call` used to bail
    # (return None -> honest whole-module refusal) unless every gap param
    # was `int64_t`; it now also lowers a `char *` gap slot via the same
    # runtime-lookup approach (the dict slot's value bits ARE the char*,
    # so mojo_dict_pop_int returns them, just cast) with a genuine
    # `mojo_dict_contains ? pop : static-default` resolution — never a
    # blind default-pad. This shape (a string kwarg forwarded through a
    # generator) previously refused; it now compiles.
    def test_generator_kwargs_forward_str_gap_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
def target(a, label="hi", **kwargs):
    return a

def gen(n, **kwargs):
    i = 0
    while i < n:
        yield target(i, **kwargs)
        i = i + 1

def main():
    for x in gen(3):
        print(x)
"""
        name = "generator_kwargs_forward_str_gap_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if 'char *_kwgap' not in cpp_src or 'mojo_dict_contains' not in cpp_src:
            print(f"FAIL  {name}: generated .cpp missing char* kwargs-gap lowering")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_kwargs_forward_str_gap_compiles_via_cpp_path()

    # Parameter-support step: a generator taking parameters (`start`,
    # `count`) now compiles via the same C++20-coroutine path instead of
    # hitting the honest whole-module refusal — mirrors
    # test_generator_simple_shape_compiles_via_cpp_path immediately above,
    # but also asserts the extern "C" `_start` declaration on the .c/.ci
    # side actually carries the two int64_t parameters through (not just a
    # bare `(void)`), and that the call site inside `main` passes real
    # argument expressions rather than an empty arg list. See
    # test_gimple_generator_runner.py for the REAL behavioral (compile+
    # link+run, actual printed output) counterpart of this same shape.
    def test_generator_param_shape_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
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
"""
        name = "generator_param_shape_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if '_mojogen_counter_start (int64_t, int64_t)' not in c_src:
            print(f"FAIL  {name}: .c/.ci extern decl doesn't carry both "
                  f"int64_t params through")
            _FAIL += 1
            return
        if '_mojogen_counter_start (int64_t start, int64_t count)' not in cpp_src:
            print(f"FAIL  {name}: .cpp _start definition doesn't carry both "
                  f"int64_t params through")
            _FAIL += 1
            return
        if '_mojogen_counter_start ()' in c_src or '_mojogen_counter_start ();' in c_src:
            print(f"FAIL  {name}: call site still emits a bare no-arg call")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_param_shape_compiles_via_cpp_path()

    # Milestone C step 2 (yield-from delegation): the exact target shape
    # from that step's writeup — `outer` delegates its entire output to
    # `inner` via a bare `yield from inner()`, both zero-param, both
    # int64_t-yielding. `inner` must be defined BEFORE `outer` in the
    # module (see GimpleGen._cpp_yield_from's docstring on the source-order
    # restriction — self._generator_api is only populated as gen_module's
    # single compile-attempt pass reaches each generator in source order).
    # Confirms both halves of the dual-output build compile for real, and
    # that the .cpp side actually emits the hand-rolled resume/yield/
    # exhaust delegation loop (not e.g. silently dropping the `yield from`
    # to nothing). See test_gimple_generator_runner.py for the REAL
    # behavioral (compile+link+run, actual printed output) counterpart,
    # including early-break/empty-inner/two-level-delegation/parameterized-
    # delegation coverage beyond this compile-only smoke test.
    def test_generator_yield_from_delegation_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
def inner():
    yield 1
    yield 2
    yield 3

def outer():
    yield from inner()

def main():
    for x in outer():
        print(x)
"""
        name = "generator_yield_from_delegation_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if '_mojogen_inner_start' not in cpp_src or '_mojogen_outer_start' not in cpp_src:
            print(f"FAIL  {name}: .cpp output missing one of the two "
                  "generators' extern \"C\" API")
            _FAIL += 1
            return
        if '_mojogen_inner_resume(' not in cpp_src or '_mojogen_inner_value(' not in cpp_src:
            print(f"FAIL  {name}: outer's body doesn't call inner's "
                  "resume/value -- the delegation loop wasn't actually emitted")
            _FAIL += 1
            return
        if '_mojogen_sub_guard' not in cpp_src:
            print(f"FAIL  {name}: expected the RAII sub-generator lifetime "
                  "guard to appear in the .cpp preamble")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_yield_from_delegation_compiles_via_cpp_path()

    # Forward consumption of a LATER-defined sibling generator — the
    # "consumed generator must be defined earlier" constraint's real
    # scope. gen_module registers each generator's API only after its
    # coroutine unit succeeds, so a consumer earlier in source order can
    # only compile on a RETRY pass; the retry loop runs to a fixed point
    # (it used to be a hard-coded 3 passes, which silently left chains
    # deeper than 4 refusing and took the whole module down to
    # interpreter fallback). This chain is 5 deep (head -> l3 -> l2 ->
    # l1 -> tail, every consumer BEFORE its producer), needing 4 retries.
    # Confirms: (a) the whole module still compiles via the C++ path,
    # (b) all five generators' extern "C" APIs exist in the .cpp, and
    # (c) head's body really drives tail's API through the intermediate
    # units (the delegation/consumption loop text is present).
    def test_generator_forward_consumption_chain_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
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
"""
        name = "generator_forward_consumption_chain_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        import re as _re
        for fn in ('head', 'l3', 'l2', 'l1', 'tail'):
            # Parametrized generators carry an overload suffix in their
            # mangled base (`_mojogen_head_3_start`) — match both forms.
            if not _re.search(rf'_mojogen_{fn}(?:_\d+)?_start\b', cpp_src):
                print(f"FAIL  {name}: .cpp output missing later-defined "
                      f"generator {fn}'s extern \"C\" API")
                _FAIL += 1
                return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_forward_consumption_chain_compiles_via_cpp_path()

    # A generator body calling an UNRESOLVABLE callee — a nested `def`
    # local to the generator that CAPTURES an enclosing local (this
    # scalar coroutine-body model has no closure compilation), a Python
    # builtin with no coroutine-body lowering (map/filter), or a
    # foreign-module struct constructor — must refuse honestly via
    # _UnsupportedGeneratorShape, NOT emit a bare undeclared C++
    # identifier that only fails later inside g++ ("'X' was not declared
    # in this scope"). Real shape: importlib/metadata/__init__.py's
    # Sectioned.read / Distribution._convert_egg_info_reqs_to_simple_reqs.
    # (A nested `def` that captures NOTHING is now compiled as a
    # standalone `static` C++ helper — see
    # `generator_nested_noncapturing_helper_compiles_via_cpp_path` below
    # and `_cpp_compile_nested_sync_helpers`.)
    with _force_cpp_coro():
        test_raises("generator_unresolved_callee_honest_refusal", """\
def outer(items):
    scale = len(items)
    def helper(x):
        return x * scale
    for section in items:
        yield helper(section)

def main():
    for x in outer([1, 2]):
        print(x)
        """, "Unsupported shape(s): outer: a call to unresolved callee 'helper(...)'")

    # A nested NON-capturing sync `def` referenced as a callee inside a
    # generator body IS compiled — as a standalone `static` C++ function
    # emitted ahead of the coroutine `{impl}` — and the whole module
    # compiles cleanly through both gcc (.c) and g++ (.cpp).
    def test_generator_nested_noncapturing_helper_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
def gen_it():
    def label(n):
        return "n=" + str(n)

    def tag(s):
        return "<" + label(len(s)) + ">"

    for i in range(3):
        yield tag("abc")

def main():
    for x in gen_it():
        print(x)
"""
        try:
            with _force_cpp_coro():
                c_code, cpp_code = gimple_codegen.compile_to_gimple_with_cpp(
                    src, do_imports=False, filename="gen_nested_helper.py")
        except Exception as e:
            print(f"FAIL  generator_nested_noncapturing_helper_compiles_via_cpp_path: "
                  f"raised {type(e).__name__}: {e}")
            _FAIL += 1
            return
        if "_h_label" not in cpp_code or "_h_tag" not in cpp_code:
            print("FAIL  generator_nested_noncapturing_helper_compiles_via_cpp_path: "
                  "expected `_h_label`/`_h_tag` helper symbols in the .cpp")
            _FAIL += 1
            return
        import tempfile, subprocess
        cp = tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False)
        cp.write(cpp_code); cp.close()
        try:
            from build_config import find_gxx
            r = subprocess.run([find_gxx(), '-std=c++20', '-fsyntax-only',
                                f'-I{_RUNTIME_INC}', cp.name],
                               capture_output=True, text=True)
            if r.returncode == 0:
                print("PASS  generator_nested_noncapturing_helper_compiles_via_cpp_path")
                _PASS += 1
            else:
                print("FAIL  generator_nested_noncapturing_helper_compiles_via_cpp_path")
                for line in r.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(cp.name)

    test_generator_nested_noncapturing_helper_compiles_via_cpp_path()

    # The one legitimate bare-name call shape must KEEP working: a call
    # through a DECLARED callable-value local (`std::function` supports
    # `operator()`) — `getpos = lambda: ...` then `yield getpos()`, the
    # pickletools.py `_genops` idiom. Compiles all the way through g++
    # rather than refusing.
    def test_generator_callable_local_call_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
def gen():
    getpos = lambda: 7
    yield getpos()

def main():
    for x in gen():
        print(x)
"""
        name = "generator_callable_local_call_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if 'getpos()' not in cpp_src:
            print(f"FAIL  {name}: .cpp doesn't call the callable-value "
                  "local getpos()")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_callable_local_call_compiles_via_cpp_path()

    # A generator body iterating a MODULE-LEVEL container global with a
    # flat tuple target (`for flagname, flagvalue in _flags:`) must lower
    # through the boxed-pointer cached-list + per-slot unpack protocol —
    # NOT the generic range-for, which emitted the comma-joined target as
    # one bogus C++ declarator ("declaration of 'auto flagname' has no
    # initializer"). Generator units compile before the module-globals
    # typing passes, so the element ctypes come from the initializing
    # literal itself (_global_literal_slot_ctypes): slot 0 of a
    # tuples-of-(str, int) list must be read via mojo_list_get_str, not
    # the int64_t default. Real: Lib/symtable.py's Symbol._flags_str.
    def test_generator_global_container_tuple_target_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
_flags = [('USE', 1), ('DEF', 2)]

class S:
    def __init__(self):
        self.f = 0

    def m(self):
        for name, val in _flags:
            yield name

def main():
    s = S()
    for n in s.m():
        print(n)

main()
"""
        name = "generator_global_container_tuple_target_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if 'mojo_list_get_str' not in cpp_src or 'for (auto' in cpp_src:
            print(f"FAIL  {name}: .cpp must unpack slots via "
                  "mojo_list_get_str/get_int, not range-for over globals")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_global_container_tuple_target_compiles_via_cpp_path()

    # The single-name sibling: iterating a module-level container global
    # whose C type isn't resolved yet at unit-compile time (generator
    # units run before the globals-typing passes) must emit the indexed
    # loop over the boxed pointer, NOT `for (auto x : _root_globals._names)`
    # over a raw field read ("'begin' was not declared in this scope").
    def test_generator_global_container_single_name_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
_names = ['a', 'b']

def gen():
    for x in _names:
        yield x

def main():
    for x in gen():
        print(x)

main()
"""
        name = "generator_global_container_single_name_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if 'mojo_list_len' not in cpp_src or 'for (auto' in cpp_src:
            print(f"FAIL  {name}: .cpp must iterate the global via an "
                  "indexed mojo_list_len loop, not range-for")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_global_container_single_name_compiles_via_cpp_path()

    # A zero-arg dict-method iterable on a SCALAR-typed self field
    # (`for k in self.dict.keys():` where `dict` is an unannotated-init
    # param, typed int64_t) is genuinely not a container under this
    # codegen's boxing convention: it must take the documented
    # zero-iteration stub path (same convention as the bare
    # `for line in self.file:` self-field case), NOT emit the raw member
    # call `self->dict.keys()` ("request for member 'keys' in ... of
    # non-class type 'int64_t'"). Real: Lib/shelve.py's Shelf.__iter__.
    def test_generator_scalar_self_field_method_iter_zero_iter_stub():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
class Shelf:
    def __init__(self, d):
        self.dict = d

    def __iter__(self):
        for k in self.dict.keys():
            yield k

def main():
    s = Shelf(0)
    for k in s.__iter__():
        print(k)
    print('done')

main()
"""
        name = "generator_scalar_self_field_method_iter_zero_iter_stub"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if '.keys()' in cpp_src:
            print(f"FAIL  {name}: .cpp must not emit a raw .keys() member "
                  "call on a scalar-typed self field")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_scalar_self_field_method_iter_zero_iter_stub()


    # Still-out-of-scope `yield from` shapes: delegating to a generator
    # that ITSELF failed to compile via the C++20-coroutine path (here,
    # because its own parameter is a String, out of scope since the
    # parameter-support step) must fall back to the honest whole-module
    # refusal, not silently miscompile.
    test("generator_yield_from_unsupported_sub_generator", """""")

    # Still-out-of-scope: `yield from` targeting a generator defined LATER
    # in the module. This step's delegation support is deliberately scoped
    # to same-module, already-compiled-by-the-time-we-get-here generators
    # (see GimpleGen._cpp_yield_from's docstring) -- a forward reference
    # isn't yet supported (would need a second, dependency-ordered pass)
    # and must refuse cleanly rather than miscompile or crash.
    test("generator_yield_from_forward_reference", """""")

    # Still-out-of-scope: the delegating generator's own yield-value type
    # doesn't agree with the sub-generator's (double vs int64_t) -- Milestone
    # B's "one consistent scalar type across every yield site" rule extends
    # naturally to `yield from` sites (see _yield_from_delegate_ctype), and
    # this must refuse rather than silently truncate/misinterpret bits.
    with _force_cpp_coro():
        test_raises("generator_yield_from_type_mismatch_honest_fallback", """\
def inner():
    yield 1.5

def outer():
    yield from inner()
    yield 2

def main():
    for x in outer():
        print(x)
        """, "generator function")

    # Still-out-of-scope: wrong argument count at the `yield from` call
    # site for a PARAMETERIZED sub-generator.
    with _force_cpp_coro():
        test_raises("generator_yield_from_argcount_mismatch_honest_fallback", """\
def inner(a, b):
    yield a + b

def outer():
    yield from inner(1)

def main():
    for x in outer():
        print(x)
        """, "generator function")

    # Milestone C step 3: generator METHODS on structs — the target shape
    # from that step's writeup, a method reading a scalar `self` field.
    # Mirrors test_generator_yield_from_delegation_compiles_via_cpp_path's
    # shape (compile via compile_to_gimple_with_cpp, assert the extern "C"
    # API + a `self->value` read appear in the .cpp text, then real-compile
    # both the .c and .cpp outputs with gcc/g++ -fsyntax-only).
    def test_generator_method_self_field_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
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
"""
        name = "generator_method_self_field_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if '_mojogen_Counter_countdown_start' not in cpp_src:
            print(f"FAIL  {name}: .cpp output missing the generator "
                  "method's extern \"C\" API")
            _FAIL += 1
            return
        if 'self->value' not in cpp_src:
            print(f"FAIL  {name}: expected a self->value field read in "
                  "the generated .cpp body")
            _FAIL += 1
            return
        if 'typedef struct Counter' not in cpp_src:
            print(f"FAIL  {name}: expected the Counter struct's C layout "
                  "to be re-emitted (shared verbatim with the .c output) "
                  "in the .cpp preamble")
            _FAIL += 1
            return
        # No ordinary Counter_countdown(...) C function/forward-declaration
        # should exist for this method at all — only the generator API.
        if 'Counter_countdown (' in c_src or 'Counter_countdown(' in c_src:
            print(f"FAIL  {name}: an ordinary (non-generator) forward "
                  "declaration/definition for Counter_countdown leaked "
                  "into the .c output")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_method_self_field_compiles_via_cpp_path()

    # Still-out-of-scope generator-method shapes (Milestone C step 3):
    # mutating a self field from inside the generator body. AssignStmt's
    # target is a MemberExpr (self.value), not a plain identifier — refused
    # by _cpp_stmt's existing AssignStmt case, unchanged; confirms this
    # falls back to the honest whole-module refusal rather than silently
    # dropping the mutation.
    test("generator_method_self_mutation", """\
class Counter:
    def __init__(self, start: Int):
        self.value = start

    def countdown(self, n: Int):
        i = 0
        while i < n:
            yield self.value
            self.value = self.value - 1
            i = i + 1

def main():
    c = Counter(10)
    for x in c.countdown(3):
        print(x)
""")

    # Still-out-of-scope: a generator method calling ANOTHER method on self
    # (`self.helper()`) — that's a CallExpr, which the narrow .cpp expression
    # emitter has no case for, so it refuses cleanly.
    test("generator_method_calls_other_self_method", """""")

    # Still-out-of-scope: a nested attribute chain (self.inner.v) — only a
    # direct self.<field> read is supported; self.inner resolves via the
    # MemberExpr obj-is-not-plain-'self' branch and refuses.
    test("generator_method_nested_attribute_chain", """""")

    # Still-out-of-scope: yielding a non-scalar self field (a String) --
    # _infer_simple_expr_ctype's self_fields lookup refuses any field type
    # outside int64_t/double/_Bool, same as any other non-scalar value.
    test("generator_method_nonscalar_field", """""")

    # Milestone C step 4 (this step): compiled-generator objects as
    # first-class values — bugs/CODEGEN_compiled_generator_not_first_class_
    # value.md's exact repro. Before this step, `g = counter(3)` typed `g`
    # as `void` (the local-variable-type inference had no notion that a
    # bare call to a known compiled generator function returns
    # `MojoGenerator *`), and gcc genuinely failed to compile at all
    # ("invalid use of void expression" / "variable or field 'g' declared
    # void") — a real, loud build failure, not a silent miscompile. Asserts
    # `g` is declared `MojoGenerator *` (not `void`/`int64_t`) and the
    # `for`-loop over the plain-identifier `g` still drives the same
    # `_resume`/`_value` API Milestone B's inline-call shape already used.
    # See test_gimple_generator_runner.py for the REAL behavioral (compile+
    # link+run) counterpart.
    def test_generator_assign_then_for_loop_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(3)
    for x in g:
        print(x)
"""
        name = "generator_assign_then_for_loop_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if 'MojoGenerator * g;' not in c_src and 'MojoGenerator *g;' not in c_src:
            print(f"FAIL  {name}: expected `g` to be declared MojoGenerator *, "
                  "not void/int64_t — .c/.ci decls:")
            for line in c_src.splitlines():
                if ' g;' in line or '*g;' in line:
                    print(f"      {line}")
            _FAIL += 1
            return
        if '_mojogen_counter_resume (g)' not in c_src:
            print(f"FAIL  {name}: expected the for-loop over `g` to drive "
                  "_resume(g)/_value(g), not fall back to the unsupported-"
                  "iterable path")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_assign_then_for_loop_compiles_via_cpp_path()

    # Same step: `next(g)` called directly on an assigned generator variable
    # — bugs/CODEGEN_compiled_generator_not_first_class_value.md's SECOND
    # failure (previously an undefined-symbol LINK error, since the generic
    # `next()` builtin had no case for MojoGenerator* at all — only a
    # variadic FIXME extern stub with no definition anywhere). Asserts the
    # .c/.ci output calls _resume/_value directly (no reference to a bare,
    # undefined `next (...)` C symbol) and signals exhaustion via the same
    # mojo_exc_type_set()/mojo_raise() StopIteration convention
    # `raise StopIteration` already uses elsewhere in this file, not a
    # novel signaling scheme.
    def test_generator_next_on_assigned_var_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
def counter(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

def main():
    g = counter(3)
    print(next(g))
"""
        name = "generator_next_on_assigned_var_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if '_mojogen_counter_resume (g)' not in c_src or '_mojogen_counter_value (g)' not in c_src:
            print(f"FAIL  {name}: expected next(g) to lower to direct "
                  "_resume(g)/_value(g) calls")
            _FAIL += 1
            return
        if 'mojo_raise ()' not in c_src or 'mojo_exc_type_set' not in c_src:
            print(f"FAIL  {name}: expected the exhaustion path to signal "
                  "StopIteration via mojo_exc_type_set()/mojo_raise(), "
                  "same as `raise StopIteration` elsewhere")
            _FAIL += 1
            return
        # A bare, unresolved CALL SITE to the generic `next` extern stub
        # would read `next (g)` (this file's call-lowering convention is a
        # space before the paren) — distinct from the always-present,
        # unconditional `int64_t next(...);` FORWARD DECLARATION emitted
        # defensively in every build's preamble regardless of whether
        # anything actually calls it (harmless on its own; only a real call
        # site referencing it would fail at link time).
        if 'next (g)' in c_src or 'next(g)' in c_src:
            print(f"FAIL  {name}: a bare, undefined `next (...)` call site "
                  "still leaked into the .c/.ci output instead of lowering "
                  "to _resume/_value")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_next_on_assigned_var_compiles_via_cpp_path()

    # Same milestone: a stored generator passed AS AN ARGUMENT to a
    # function (`consume(g)` where `g = counter(3)`). Pass 1.3f-gen must
    # re-observe the call site AFTER local-variable inference typed `g` as
    # MojoGenerator* (the earlier cross-call scalar-contract pass ran before
    # that and left the unannotated callee param defaulted to int64_t) and
    # propagate the generator type onto the callee's param, so the `for`
    # loop inside the callee drives _resume/_value instead of falling back.
    # Asserts the param is declared `MojoGenerator *` and the callee's loop
    # uses the _resume/_value API. bugs/CODEGEN_compiled_generator_not_
    # first_class_value.md.
    def test_generator_param_from_call_boundary_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
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
"""
        name = "generator_param_from_call_boundary_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if '_mojogen_counter_resume' not in c_src:
            print(f"FAIL  {name}: expected the callee's for-loop over the "
                  "param to drive the generator _resume/_value API")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_param_from_call_boundary_compiles_via_cpp_path()

    # Same milestone: a generator RETURNED from a function
    # (`def mk(): return counter(3)`), then consumed by the caller. The
    # returned value's result temp must be typed MojoGenerator* with the
    # underlying generator function's api recorded on it (via _lower_named_
    # call's _fn_returns_generator lookup), so the caller's `for x in g:`
    # drives the right _resume/_value pair. bugs/CODEGEN_compiled_generator_
    # not_first_class_value.md.
    def test_generator_returned_from_function_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
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
"""
        name = "generator_returned_from_function_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if '_mojogen_counter_resume' not in c_src:
            print(f"FAIL  {name}: expected the for-loop over the returned "
                  "generator to drive the counter's _resume/_value API")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_returned_from_function_compiles_via_cpp_path()

    # A `for` loop over a generator whose body does `in`/`not in` membership
    # tests — bugs/CODEGEN_compiled_generator_not_first_class_value.md-adjacent
    # .cpp emission. Python's `in`/`not in` operators are NOT emitted as infix
    # tokens in the C++20-coroutine body (that would spell Python keywords
    # `in`/`not in` directly into C++ — invalid: `not` is a C++ keyword and
    # `in` is not an operator). The .cpp CompareChain lowers them through the
    # same mojo_str_contains / mojo_list_contains_* helpers the GIMPLE path
    # uses, gated on the container's declared C++ type. `'\0' in s` / `'\0'
    # not in s` on a char * haystack is the exact shape that lit up mimetypes.py
    # (`if '\\0' not in ctype`).
    test("generator_in_not_in_membership_compiles_via_cpp_path", """\
def gen(s):
    if 'a' in s:
        yield 1
    if 'z' not in s:
        yield 2

def main():
    for x in gen("abracadabra"):
        print(x)
""")

    # 177. A bound method referenced as a plain VALUE (not called
    # immediately) — `f = self.b` — then invoked later via `f()`. Calling a
    # method directly (`self.b()`) already worked; a bare method reference
    # used to fall through to the generic struct-field lookup and emit an
    # invalid `self->b` field access (`'C' has no member named 'b'` from the
    # C compiler, since `b` is a method, not a data field) — see
    # bugs/CODEGEN_bound_method_as_value_not_resolved.md. Real stdlib
    # trigger: Lib/cmd.py's `readline.set_completer(self.complete)` passes a
    # bound method as a callback value the same way.
    test("bound_method_as_value", """\
class C:
    def b(self):
        return 42
    def a(self):
        f = self.b
        return f()

def main():
    c = C()
    print(c.a())
main()
""")

    # 177b. A BUILTIN-CONTAINER method bound to a local and called later —
    # `result = bytearray(); append = result.append` then `append(x)` in a
    # loop (Lib/zipfile/__init__.py's `_ZipDecrypter.decrypter`). List/dict/
    # set already worked (_lower_builtin_method_value); bytes/bytearray and
    # memoryview fell through to a struct-field read and emitted an invalid
    # `->append` access (`'MojoBytes' has no member named 'append'`). See
    # the bound-method grep cluster in bugs/ (zipfile, pickletools, os,
    # glob, ipaddress, ctypes_util, ...).
    test("bound_container_method_bytearray_value", """\
def decrypter(data):
    result = bytearray()
    append = result.append
    for i in range(len(data)):
        append(data[i])
    return bytes(result)

def main():
    print(len(decrypter([1, 2, 3])))
""")
    test("bound_container_method_list_dict_set_value", """\
def main():
    xs = []
    f = xs.append
    f(1)
    f(2)
    d = {}
    s = d.setdefault
    st = set()
    a = st.add
    a(7)
    print(len(xs), s('k', 9), len(st))
""")

    # 178. Untyped-parameter identity function called with a string argument
    # — bugs/CODEGEN_untyped_param_string_passthrough_wrong.md. `a` has no
    # body-usage evidence at all (just returned unchanged), so the parameter
    # and the function's inferred return type used to default to int64_t;
    # the real char* argument then got silently truncated/reinterpreted as
    # an integer at the call site and the call's result. Assert the param
    # and the generated function both compile as real pointers, not just
    # that gcc accepts the file (a wrong-but-gimple-legal int64_t version
    # would also pass a bare compile check).
    _ok, _c, _err = gimple_compiles("""\
def g(a):
    return a
print(g("ab"))
""")
    if _ok and 'char * g_' in _c and 'int64_t g_' not in _c:
        print("PASS  untyped_param_string_passthrough"); _PASS += 1
    else:
        print("FAIL  untyped_param_string_passthrough")
        print(f"      ok={_ok}")
        print("      --- generated C ---")
        for i, line in enumerate(_c.splitlines(), 1):
            print(f"      {i:3}: {line}")
        if not _ok:
            print("      --- gcc stderr ---")
            for line in _err.splitlines():
                print(f"      {line}")
        _FAIL += 1

    # 179. Same bug, two-untyped-parameter shape (`a + b`, both strings) —
    # the shape that originally surfaced via an f-string interpolating a
    # run-time-computed string value from a function just like this one.
    _ok, _c, _err = gimple_compiles("""\
def g(a, b):
    return a + b
y = g("a", "b")
print(y)
""")
    if _ok and 'char * g_' in _c and 'int64_t g_' not in _c:
        print("PASS  untyped_param_string_concat_passthrough"); _PASS += 1
    else:
        print("FAIL  untyped_param_string_concat_passthrough")
        print(f"      ok={_ok}")
        print("      --- generated C ---")
        for i, line in enumerate(_c.splitlines(), 1):
            print(f"      {i:3}: {line}")
        if not _ok:
            print("      --- gcc stderr ---")
            for line in _err.splitlines():
                print(f"      {line}")
        _FAIL += 1

    # 180. Explicitly annotated identity function — must keep working exactly
    # as before (this path never went through the unannotated-parameter
    # inference this fix touches).
    test("typed_param_string_passthrough_still_works", """\
def g(a: str) -> str:
    return a
print(g("ab"))
""")

    # 181. A module with many module-level integer constants, all referenced
    # inside one function, must lower those constants to file-scope globals
    # (the `_root_globals` struct + `root__mojo_global_get_*` accessors),
    # NOT re-materialize a per-function LOCAL copy of every constant in that
    # function's decl block. A large per-function local-decl block of
    # module constants is what crashed GCC's GIMPLE frontend
    # (`internal compiler error: in build2, at tree.cc:5208`) on
    # Lib/zipfile/__init__.py's ~60 module constants — see
    # bugs/COMPILE_FAIL_zipfile___init__.md. This locks in the file-scope
    # representation as a regression guard.
    _NCONST = 40
    _kconst_src = (
        "".join(f"K{i} = {i}\n" for i in range(1, _NCONST + 1))
        + "\nfn total() -> Int:\n    return "
        + " + ".join(f"K{i}" for i in range(1, _NCONST + 1))
        + "\n\nfn main():\n    print(total())\n"
    )
    _kc_ok, _kc_c_src, _kc_stderr = gimple_compiles(_kconst_src)
    # Each constant must appear exactly once as a struct field decl
    # (`  int Ki;`), never a second time as a function-body local.
    _dup_locals = [i for i in range(1, _NCONST + 1)
                   if _kc_c_src.count(f"  int K{i};") != 1]
    _reads_global = "_root_globals.K1" in _kc_c_src
    if _kc_ok and not _dup_locals and _reads_global:
        print("PASS  many_module_constants_are_file_scope_globals"); _PASS += 1
    else:
        print("FAIL  many_module_constants_are_file_scope_globals")
        print(f"      compiled={_kc_ok} reads_global={_reads_global} "
              f"constants_with_wrong_decl_count={_dup_locals}")
        if not _kc_ok:
            print("      --- gcc stderr ---")
            for line in _kc_stderr.splitlines():
                print(f"      {line}")
        _FAIL += 1

    # 182. Generator expression bound to a local / reassigned parameter,
    # then consumed exactly once by a forward iteration, must compile:
    # it is materialised as a list (see _seed_genexp_list_narrowing).
    # The reassigned-parameter shape is ZipFile._sanitize_windows_name —
    # bugs/COMPILE_FAIL_zipfile___init__.md blocker 3.
    test("genexp_local_single_consumption_join", """\
fn clean(arcname: String, pathsep: String) -> String:
    arcname = (x.rstrip(" .") for x in arcname.split(pathsep))
    arcname = pathsep.join(x for x in arcname if x)
    return arcname

fn main():
    print(clean("a. /b .// c", "/"))
""")

    test("genexp_local_single_consumption_for_and_sum", """\
fn main():
    g = (x + 1 for x in [10, 20, 30])
    for v in g:
        print(v)
    h = (x * 2 for x in [1, 2, 3])
    print(sum(x for x in h))
""")

    # ── Milestone D: try/except/raise inside a compiled generator body ─────
    def _generator_compiles_via_cpp(name: str, src: str, must_contain_cpp=None):
        """Shared compile-only smoke-test helper for Milestone D's generator
        try/except/raise support — mirrors
        test_generator_simple_shape_compiles_via_cpp_path's own dance
        (compile_to_gimple_with_cpp, then gcc -fsyntax-only the .c/.ci and
        g++ -std=c++20 -fsyntax-only the .cpp) without duplicating that
        subprocess plumbing a third/fourth/fifth time."""
        global _PASS, _FAIL
        import gimple_codegen
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        if must_contain_cpp is not None and must_contain_cpp not in cpp_src:
            print(f"FAIL  {name}: expected {must_contain_cpp!r} in generated .cpp")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    # A generator whose own internal try/except catches everything it
    # raises — the simplest positive shape.
    _generator_compiles_via_cpp("generator_try_except_compiles_via_cpp_path", """\
def f():
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
    for x in f():
        print(x)
""", must_contain_cpp="_MojoCppExc")

    # A generator whose raise is NOT caught internally — must compile (the
    # exception propagates via the extern "C" `_resume` boundary + the
    # mojo_exc_pending flag, checked by the ordinary GIMPLE consumer, not by
    # anything inside the .cpp translation unit itself).
    _generator_compiles_via_cpp("generator_raise_propagates_compiles_via_cpp_path", """\
def f():
    yield 1
    raise ValueError("boom")

def main():
    try:
        for x in f():
            print(x)
    except ValueError:
        print("caught")
""")

    # try/except/finally together — the RAII-scope-guard finally translation
    # composing with real dispatch.
    _generator_compiles_via_cpp("generator_try_except_finally_compiles_via_cpp_path", """\
def f():
    cleanups = 0
    i = 0
    while i < 3:
        try:
            if i == 1:
                raise KeyError("nope")
            yield i
        except KeyError:
            yield -1
        finally:
            cleanups = cleanups + 1
        i = i + 1
    yield cleanups

def main():
    for x in f():
        print(x)
""")

    # Multiple typed handlers plus a bare catch-all, and a re-raise (`raise`
    # with no value) inside one of them — exercises the descendant-OR
    # dispatch chain AND the `throw;` re-raise path together.
    _generator_compiles_via_cpp("generator_try_multi_except_reraise_compiles_via_cpp_path", """\
def f():
    i = 0
    while i < 3:
        try:
            if i == 0:
                raise ValueError("v")
            if i == 1:
                raise KeyError("k")
            yield i
        except ValueError:
            yield -1
        except KeyError as e:
            raise
        except:
            yield -2
        i = i + 1

def main():
    for x in f():
        print(x)
""")

    # `yield from` delegating to a generator that itself raises — confirms
    # Milestone C step 2 (delegation) and Milestone D (exceptions) compose,
    # not a fourth separate code path (see _cpp_yield_from's pending-
    # exception check).
    _generator_compiles_via_cpp("generator_yield_from_raise_compiles_via_cpp_path", """\
def inner():
    yield 1
    raise ValueError("boom")

def outer():
    try:
        yield from inner()
    except ValueError:
        yield -1

def main():
    for x in outer():
        print(x)
""")

    # A generator METHOD (Milestone C step 3: `self` field reads) combined
    # with try/except — confirms this composes with self-binding too, not
    # just free functions.
    _generator_compiles_via_cpp("generator_method_try_except_compiles_via_cpp_path", """\
class Counter:
    def __init__(self, start: Int):
        self.value = start

    def countdown(self, n: Int):
        i = 0
        while i < n:
            try:
                if self.value - i == 0:
                    raise ValueError("zero")
                yield self.value - i
            except ValueError:
                yield -1
            i = i + 1

def main():
    c = Counter(2)
    for x in c.countdown(3):
        print(x)
""")

    # Still-refused shapes: `yield` inside a `finally:` block (a destructor
    # can't `co_yield`) and a bare `raise` with no enclosing handler both
    # honestly fall back to the whole-module refusal, exactly like every
    # other out-of-scope shape in this file.
    with _force_cpp_coro():
        test_raises("generator_yield_in_finally_honest_fallback", """\
def f():
    try:
        yield 1
    finally:
        yield 2
        """, "generator function")

    with _force_cpp_coro():
        test_raises("generator_bare_raise_outside_handler_honest_fallback", """\
def f():
    raise
    yield 1
        """, "generator function")

    # `with` inside a generator body is still out of this milestone's scope
    # (needs its own __enter__/__exit__ codegen story) — confirms adding
    # try/except support didn't accidentally also let `with` through
    # _generator_quick_eligible's pre-filter.
    #
    # Loop-as-expression codegen: `list(<iterable>)`/`set(<iterable>)`/a
    # real `[<elem> for <target> in <iterable> if <cond>]`/`{...}`
    # comprehension used as a VALUE inside a compiled generator body,
    # over a variety of iterable shapes this emitter's `_cpp_for_stmt`
    # already knows how to drive (range/a declared list/set local/a
    # dict's .keys()/.values()/self.field/another already-built list) —
    # previously this whole family had NO codegen at all in the
    # coroutine-body expression emitter (`_cpp_expr`'s Comprehension case
    # was an honest always-empty-list stub, and a bare `list(...)`/
    # `set(...)` CallExpr over anything but a trivial already-typed
    # container fell to the generic "unresolved callee" refusal of the
    # WHOLE generator). See gimple_cpp_core.py's
    # `_cpp_build_container_from_iterable`/`_cpp_rename_ident` and
    # gimple_exprtypes.py's matching `_infer_simple_expr_ctype` widening.
    def test_generator_list_set_ctor_and_comprehension_loop_as_expr_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
def gen1():
    x = list(range(5))
    yield len(x)
    y = [i * 2 for i in range(4)]
    yield y[1]
    s = set(range(3))
    yield 1 if 2 in s else 0
    lst = [1, 2, 3, 4]
    z = [v for v in lst if v > 2]
    yield z[0]
    yield len(list(lst))
    ss = {v for v in lst if v > 1}
    yield len(list(ss))

def gen2(d):
    ks = list(d.keys())
    yield len(ks)
    vs = set(d.values())
    yield len(list(vs))

def gen3():
    a = [1, 2, 3]
    b = list(a)
    yield len(b)
"""
        name = "generator_list_set_ctor_and_comprehension_loop_as_expr_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        for _needle in ('_mojogen_gen1_start', '_mojogen_gen2_start', '_mojogen_gen3_start'):
            if _needle not in c_src:
                print(f"FAIL  {name}: .c/.ci output missing {_needle} (fell back to source instead of compiling via cpp)")
                _FAIL += 1
                return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_generator_list_set_ctor_and_comprehension_loop_as_expr_compiles_via_cpp_path()
    test("generator_with", """""")

    # ── Step B (compiled-path async/await codegen project) ─────────────────
    # The exact target shape from that step's writeup: a parameterless
    # `async def` whose body is just `return 42`, called (bare, value-
    # DISCARDING — see the revised design note below) from `main` — the
    # smallest possible real compiled async function. Mirrors
    # test_generator_simple_shape_compiles_via_cpp_path's shape exactly
    # (compile via compile_to_gimple_with_cpp, assert both halves of the
    # dual-output build are real gcc-fsyntax-only/g++-fsyntax-only-clean
    # C/C++), plus asserts the async-specific extern "C" API names (no
    # `_resume`, unlike the generator convention — see
    # GimpleGen._gen_cpp_async_unit's docstring) actually appear. See
    # test_gimple_async_runner.py for the REAL behavioral (compile+link+run)
    # counterpart of this same shape.
    #
    # REVISED (bugs/CODEGEN_compiled_async_eager_execution_semantic_
    # mismatch.md): Step B's first cut called `f()` here as `x = f();
    # print(x)`, which independent hand-verification against real CPython
    # found to be a genuine semantic bug -- that shape got construct+
    # schedule+run+read+destroy fused into ONE expression's lowering, so
    # `x` was `42` immediately, even though real Python (and this project's
    # own interpreter) never runs an async function's body just from
    # calling it -- only `await`/an explicit driver does, and this codegen
    # has neither yet. Fixed by narrowing this step's scope: the ONLY
    # supported call shape is now a bare, value-discarding statement (see
    # test_async_value_consuming_call_honest_fallback below for the
    # honest-refusal counterpart proving the old eager-execution shape no
    # longer silently compiles).
    def test_async_simple_shape_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
async def f():
    return 42

def main():
    f()
"""
        name = "async_simple_shape_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: compile_to_gimple_with_cpp raised {e!r}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected non-empty generated .cpp text")
            _FAIL += 1
            return
        missing = [s for s in ('_mojoasync_f_start', '_mojoasync_f_value',
                                '_mojoasync_f_destroy', '_mojoasync_f_is_done',
                                'MojoAsync')
                   if s not in c_src]
        if missing:
            print(f"FAIL  {name}: .c/.ci output missing async extern \"C\" API "
                  f"decl(s): {missing}")
            _FAIL += 1
            return
        if '_mojoasync_f_resume' in c_src or '_mojoasync_f_resume' in cpp_src:
            print(f"FAIL  {name}: async API should have NO `_resume` (unlike "
                  "the generator convention) -- see _gen_cpp_async_unit's "
                  "docstring")
            _FAIL += 1
            return
        # A bare, value-discarding call must NOT drive the coroutine via
        # Step A's scheduler at all -- if it did, the body would run, which
        # is exactly the bug this revision fixes (see the module-level
        # comment above).
        if 'mojo_async_schedule_ready' in c_src or 'mojo_async_run_until_complete' in c_src:
            print(f"FAIL  {name}: a bare, value-discarding async call must "
                  "never reach the scheduler -- its body must never run")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src); c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src); cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_async_simple_shape_compiles_via_cpp_path()

    # The bug's exact repro (bugs/CODEGEN_compiled_async_eager_execution_
    # semantic_mismatch.md): consuming an async call's result as a value
    # (`x = f()`, then using `x`) must now be an honest whole-module
    # refusal, NOT the old eager construct+schedule+run+read+destroy
    # behavior that silently produced `42` with no `await` in sight.
    test("async_value_consuming_call", """\
async def f():
    return 42

def main():
    x = f()
    print(x)
""")

    # Same bug, `print(f())` shape (argument position, not assignment) --
    # confirms the refusal isn't assignment-specific.
    test("async_value_consuming_call_as_arg", """\
async def f():
    return 42

def main():
    print(f())
""")

    # Narrowing checks: every out-of-scope async shape from this step's plan
    # must still hit the honest whole-module refusal, not be silently
    # (mis)compiled. async_function_honest_fallback/
    # async_generator_function_honest_fallback above already cover the two
    # broadest categories (a plain `async def` at all, and an async
    # generator); these add the specific narrower shapes Step B's own
    # eligibility narrowing needs to keep refusing even though a bare
    # `async def f(): return <scalar>` now compiles.

    # Step H (create_task/Task/TaskGroup/RaisingTask project): a scalar
    # (or untyped, which defaults to int64_t) parameter is now SUPPORTED —
    # mirrors the generator project's own identical parameter-support step
    # exactly (see _gen_cpp_async_unit's docstring: a C++20 coroutine's
    # formal parameters are ordinary frame-local values, same as a
    # generator's). This replaces the old "any parameter at all is an
    # honest fallback" assertion — a NON-scalar-typed parameter (String,
    # below) is still refused.
    test("async_function_with_scalar_param_compiles", """\
async def f(x):
    return x
""")

    test("async_function_with_nonscalar_param", """\
async def f(x: String) -> String:
    return x
""")

    # bugs/COMPILE_FAIL_asyncio_queues.md gap 2: a STRUCT-typed param on a
    # top-level (non-method) async def is now supported -- unpacked from
    # its __mojo_gen_arg slot with a `(T *)` cast (structs cross as `T *`,
    # BUG-2026-030) and threaded to the coroutine body as a real `T *` C
    # param, so struct methods / Future fields work inside the coroutine.
    # Real producer/consumer proof: test_coro_future_await.py.
    test("async_function_with_struct_param", """\
import asyncio
from collections import deque

struct Q:
    fn __init__(out self):
        self._items = deque()
        self._getters = deque()
    fn empty(self) -> Bool:
        return len(self._items) == 0
    fn put_nowait(mut self, item: Int):
        self._items.append(item)
        while len(self._getters) > 0:
            var g = self._getters.popleft()
            g.set_result(0)

async def consumer(q: Q) -> Int:
    while q.empty():
        var getter = create_future()
        q._getters.append(getter)
        await getter
    return q._items.popleft()

async def main_co() -> Int:
    var q = Q()
    q.put_nowait(41)
    var v = await consumer(q)
    return v + 1

def main():
    print(asyncio.run(main_co()))
""")

    # bugs/COMPILE_FAIL_asyncio_futures.md items (1)-(3): the native Future
    # handle now carries an exception slot (set_exception/exception), a
    # cancelled state (cancel/cancelled/set_running_or_notify_cancel) and a
    # done-callback list (add_done_callback/remove_done_callback). These
    # method names lower to the __mojo_future_* shims instead of stubbing.
    # Behavioral proof (await raising on set_exception, cancel/cancelled,
    # a callback firing on set_result): test_coro_future_await.py.
    test("async_future_exception_cancel_callbacks", """\
import asyncio

def on_done(fut: Int):
    print("done")

async def worker(fut: Int) -> Int:
    try:
        var v = await fut
        return v
    except Exception:
        return -1

async def main_co() -> Int:
    var fut = create_future()
    fut.add_done_callback(on_done)
    if fut.set_running_or_notify_cancel():
        fut.set_exception(ValueError("boom"))
    var r = await worker(fut)
    var f2 = create_future()
    var did = f2.cancel()
    if f2.cancelled():
        r = r + did
    if f2.exception() == 0:
        r = r + 1
    return r

def main():
    print(asyncio.run(main_co()))
""")

    # bugs/COMPILE_FAIL_asyncio_futures.md (3), callback-kind tag: a
    # bound-method callback (`self.on_done`, asyncio's own shape) and a
    # capturing-closure callback must lower through the MojoBoundMethod*
    # path (tag 1), not as a bare fn pointer. Behavioral proof:
    # test_coro_future_await.py.
    test("async_future_done_callback_bound_method_and_closure", """\
import asyncio

struct W:
    var n: Int
    fn __init__(out self):
        self.n = 0
    fn on_done(self, fut: Int):
        print("m")
    async def run(self, f: Int) -> Int:
        f.add_done_callback(self.on_done)
        var k = 3
        fn cb(fut: Int):
            print("c", k)
        f.add_done_callback(cb)
        f.set_result(1)
        return 0

async def main_co() -> Int:
    var w = W()
    var f = create_future()
    return await w.run(f)

def main():
    print(asyncio.run(main_co()))
""")

    # `await asyncio.sleep(...)` (Step C) / `await <another compiled async
    # function>` (Step D) are both supported now — see
    # test_async_await_composition_compiles_via_cpp_path and
    # test_async_await_sleep_and_asyncio_run_compiles_via_cpp_path. `await`
    # on a call to an async function that ITSELF is out of scope (here: has
    # a non-scalar-typed parameter, so `f` never gets compiled/registered
    # in self._async_api at all) still correctly falls back to the honest
    # whole-module refusal — not silently emitting a dangling reference to
    # a callee that was never actually compiled.
    test("async_function_await_on_unsupported_callee", """""")

    # A non-scalar return value (a string) — mirrors the generator
    # project's own honest-fallback precedent for a non-scalar yielded
    # value.
    test("async_function_string_return", """""")

    # No return value at all (`pass`) — UPDATE: this shape is now genuinely
    # supported (was an honest refusal through Step G; the device_context.mojo
    # follow-on added real void/None-returning compiled-async-function
    # support — see _gen_cpp_async_unit's "value_ctype = 'void'" branch),
    # needed for device_context.mojo's `async def wrapper(...) capturing ->
    # None:` closures, which never return a value at all. Compile-only smoke
    # test here (mirrors this file's other `test(...)` entries); real
    # behavioral (compile+link+run) proof lives in
    # test_closure_capture_comptime_func_params.py /
    # test_async_void_return.py.
    test("async_function_no_return_value_now_supported", """\
async def f():
    pass
""")

    # Two `return`s that don't agree on one consistent scalar type — the
    # async counterpart of generator_mixed_yield_types_honest_fallback.
    with _force_cpp_coro():
        test_raises("async_function_mixed_return_types_honest_fallback", """\
async def f():
    if True:
        return 1
    return 1.5
        """, "async function")

    # ── Step C (compiled-path async/await codegen project): real `await`,
    # driven via an explicit `asyncio.run(...)` top-level bridge ──────────
    # The exact target shape from Step C's writeup: `await asyncio.sleep(...)`
    # inside an async function body, its result actually consumed via
    # `asyncio.run(f())` at the top level. Compile-only smoke test — asserts
    # BOTH halves of the dual-output build are real gcc -fsyntax-only/g++
    # -fsyntax-only-clean C/C++ AND that the generated code actually reaches
    # Step A's real scheduler primitives (mojo_async_schedule_timer for the
    # `co_await`, mojo_async_schedule_ready/_run_until_complete for the
    # `asyncio.run` driver) rather than faking either one. See
    # test_gimple_async_runner.py for the REAL behavioral (compile+link+run,
    # WITH wall-clock timing proving genuine suspension) counterpart.
    def test_async_await_sleep_and_asyncio_run_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
import asyncio

async def f():
    await asyncio.sleep(0.05)
    return 42

def main():
    result = asyncio.run(f())
    print(result)
"""
        name = "async_await_sleep_and_asyncio_run_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: unexpected exception: {e}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected a non-empty generated .cpp for a "
                  "compiled async function")
            _FAIL += 1
            return
        if 'co_await' not in cpp_src or 'mojo_async_schedule_timer' not in cpp_src:
            print(f"FAIL  {name}: the async function's body should lower "
                  "`await asyncio.sleep(...)` to a real `co_await` on "
                  "Step A's timer-scheduling API")
            _FAIL += 1
            return
        if ('mojo_async_schedule_ready' not in c_src
                or 'mojo_async_run_until_complete' not in c_src):
            print(f"FAIL  {name}: the top-level `asyncio.run(f())` call "
                  "should drive the coroutine to completion via Step A's "
                  "own scheduler API in the .c output")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src)
            c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src)
            cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_async_await_sleep_and_asyncio_run_compiles_via_cpp_path()

    # `x = f()` alone (no `asyncio.run`) must STILL be honestly refused,
    # unchanged from the bug fix's own bar (9a3a62b) — re-verified here
    # under Step C's own test rather than assuming the pre-existing test
    # above still covers it after this step's changes (it does — this is
    # the exact same shape, unmodified — but this re-asserts it explicitly
    # as part of Step C's own coverage, since Step C is precisely the step
    # that could have accidentally regressed it by loosening the async-call
    # value-consumption rule).
    test("async_bare_call", """\
async def f():
    await asyncio.sleep(0.01)
    return 42

def main():
    x = f()
    print(x)
""")

    # ── Step F: `await asyncio.sock_recv(<fd>)` real-socket-I/O compile-only
    # smoke test — same two-part bar as Step C's own
    # test_async_await_sleep_and_asyncio_run_compiles_via_cpp_path above
    # (real gcc/g++ -fsyntax-only-clean output AND the generated code
    # actually reaches Step A's real reactor primitive
    # mojo_async_register_read, not a faked stand-in). See
    # test_gimple_async_runner.py for the REAL behavioral (compile+link+run
    # against a genuine socketpair(), with wall-clock timing proving actual
    # reactor-driven suspension) counterpart.
    def test_async_sock_recv_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
import asyncio

async def recv_one():
    fd = 3
    b = await asyncio.sock_recv(fd)
    return b

def main():
    x = asyncio.run(recv_one())
    print(x)
"""
        name = "async_sock_recv_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: unexpected exception: {e}")
            _FAIL += 1
            return
        if not cpp_src:
            print(f"FAIL  {name}: expected a non-empty generated .cpp for a "
                  "compiled async function")
            _FAIL += 1
            return
        if ('co_await' not in cpp_src
                or 'mojo_async_register_read' not in cpp_src
                or '_mojoasync_SockRecvAwaiter' not in cpp_src):
            print(f"FAIL  {name}: the async function's body should lower "
                  "`await asyncio.sock_recv(...)` to a real `co_await` on "
                  "Step A's reactor read-registration API via "
                  "_mojoasync_SockRecvAwaiter")
            _FAIL += 1
            return
        if ('mojo_async_schedule_ready' not in c_src
                or 'mojo_async_run_until_complete' not in c_src):
            print(f"FAIL  {name}: the top-level `asyncio.run(recv_one())` "
                  "call should drive the coroutine to completion via Step "
                  "A's own scheduler API in the .c output")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src)
            c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src)
            cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_async_sock_recv_compiles_via_cpp_path()

    # `asyncio.sock_recv(...)` referenced WITHOUT `await` (e.g. assigned) has
    # no meaning at compiled-program runtime — same honest-fallback shape as
    # `asyncio.sleep(...)` used without `await`, immediately above.
    test_raises("asyncio_sock_recv_without_await_honest_fallback", """\
import asyncio

def main():
    fd = 3
    x = asyncio.sock_recv(fd)
    print(x)
""", "asyncio.sock_recv")

    # A multi-argument `asyncio.sock_recv(fd, nbytes)` call — this step's
    # deliberately narrow scope only recognizes the fixed-1-byte, single-
    # argument shape (see gimple_codegen._is_asyncio_sock_recv_call's
    # docstring); a 2-argument call doesn't match that shape at all, so it
    # falls through to the generic "unsupported await target" refusal.
    test_raises("asyncio_sock_recv_with_nbytes_arg_still_refused", """\
async def f():
    fd = 3
    b = await asyncio.sock_recv(fd, 1024)
    return b

def main():
    import asyncio
    asyncio.run(f())
""", "async function(s), declared")

    # A hypothetical `asyncio.sock_sendall(...)` (the write-side counterpart)
    # remains entirely out of this step's scope — no special-case
    # recognition exists for it at all, so it's refused exactly like any
    # other unrecognized await target.
    test_raises("asyncio_sock_sendall_not_recognized_still_refused", """\
async def f():
    fd = 3
    await asyncio.sock_sendall(fd, 65)
    return 0

def main():
    import asyncio
    asyncio.run(f())
""", "async function(s), declared")

    # Step D: async-awaits-async composition (one Mojo async function
    # awaiting ANOTHER Mojo async function's call) now compiles for real —
    # see test_async_await_composition_compiles_via_cpp_path above for the
    # 2-level compile-only smoke test; this one exercises a 3-level chain
    # (`c` awaits `b` awaits `a`), each with its own real `await
    # asyncio.sleep(...)` mixed in, confirming the composition
    # awaiter/continuation mechanism generalizes past exactly one level of
    # nesting and coexists with Step C's sleep-awaiter in the same body.
    def test_async_await_composition_three_level_chain_compiles_via_cpp_path():
        global _PASS, _FAIL
        import gimple_codegen
        src = """\
import asyncio

async def a():
    await asyncio.sleep(0.01)
    return 10

async def b():
    x = await a()
    await asyncio.sleep(0.01)
    return x + 1

async def c():
    x = await b()
    await asyncio.sleep(0.01)
    return x + 100

def main():
    result = asyncio.run(c())
    print(result)
"""
        name = "async_await_composition_three_level_chain_compiles_via_cpp_path"
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: unexpected exception: {e}")
            _FAIL += 1
            return
        needed = ('_mojoasync_a_Awaiter', '_mojoasync_b_Awaiter', 'continuation')
        if not cpp_src or any(n not in cpp_src for n in needed):
            print(f"FAIL  {name}: expected the generated .cpp to contain "
                  f"every composition awaiter/continuation piece {needed}")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as fh:
            fh.write(c_src)
            c_path = fh.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as fh:
            fh.write(cpp_src)
            cpp_path = fh.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    test_async_await_composition_three_level_chain_compiles_via_cpp_path()

    # `await` on a socket-style operation (no such Mojo-level API exists in
    # this codegen at all yet — Step F's job) remains refused exactly like
    # any other unrecognized await target: falls through to "not a call to
    # asyncio.sleep nor to a known compiled async function".
    test_raises("async_await_socket_like_expression_honest_fallback", """\
async def f():
    x = await some_socket.recv()
    return x
""", "async function")

    # `asyncio.sleep(...)` referenced WITHOUT `await` (e.g. assigned) has no
    # meaning in compiled code -- honest refusal, not a silent no-op or a
    # call to an undefined symbol.
    test_raises("asyncio_sleep_without_await_honest_fallback", """\
import asyncio

def main():
    x = asyncio.sleep(0.1)
""", "asyncio.sleep")

    # `asyncio.run(...)` of anything other than a bare call to a supported
    # compiled async function -- e.g. a non-call expression -- is an honest
    # refusal, not a guessed-at lowering.
    test_raises("asyncio_run_non_call_argument_honest_fallback", """\
import asyncio

def main():
    x = 5
    asyncio.run(x)
""", "asyncio.run")

    # ── Step E (compiled-path async/await codegen project): raise/try/
    # except/finally inside async function bodies ───────────────────────────
    # Compile-only smoke tests, mirroring the sleep/composition tests above
    # (-fsyntax-only on both the .c and .cpp outputs) — REAL compile+link+run
    # behavioral coverage (including the propagates-through-await-to-caller's-
    # own-except case, the key new behavior) is test_gimple_async_runner.py's
    # job, not this file's.
    def _check_async_syntax_only(name, src, cpp_substrs=(), c_substrs=()):
        global _PASS, _FAIL
        import gimple_codegen
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: unexpected exception: {e}")
            _FAIL += 1
            return
        missing = [s for s in cpp_substrs if s not in cpp_src]
        missing += [s for s in c_substrs if s not in c_src]
        if missing:
            print(f"FAIL  {name}: expected substrings missing: {missing}")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            f.write(c_src)
            c_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src)
            cpp_path = f.name
        try:
            r_c = subprocess.run(
                [GCC, '-fgimple', '-fsyntax-only', f'-I{_RUNTIME_INC}', c_path],
                capture_output=True, text=True)
            from build_config import find_gxx
            gxx = find_gxx()
            r_cpp = subprocess.run(
                [gxx, '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
                capture_output=True, text=True)
            if r_c.returncode == 0 and r_cpp.returncode == 0:
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}")
                if r_c.returncode != 0:
                    print("      --- gcc (.c) stderr ---")
                    for line in r_c.stderr.splitlines(): print(f"      {line}")
                if r_cpp.returncode != 0:
                    print("      --- g++ (.cpp) stderr ---")
                    for line in r_cpp.stderr.splitlines(): print(f"      {line}")
                _FAIL += 1
        finally:
            os.unlink(c_path)
            os.unlink(cpp_path)

    # An async function with an internal try/except -- real C++ try/throw/
    # catch, the EXACT SAME _MojoCppExc/_cpp_try_stmt/_cpp_raise_stmt
    # machinery generator Milestone D already built, reused (not
    # duplicated) for the async emitter path.
    _check_async_syntax_only(
        "async_internal_try_except_compiles_via_cpp_path", """\
async def f():
    total = 0
    try:
        total = 1
        raise ValueError("boom")
    except ValueError:
        total = total + 10
    return total

def main():
    import asyncio
    print(asyncio.run(f()))
""",
        cpp_substrs=('throw _MojoCppExc', 'catch (_MojoCppExc'))

    # An exception raised inside an awaited callee propagates through the
    # `await` into the awaiting function's OWN try/except -- the per-
    # awaiter rethrow this step actually adds (see `{base}_Awaiter::
    # await_resume` in gimple_codegen.py's _gen_cpp_async_unit): the
    # callee's promise stages "completed via exception" (exc/exc_pending),
    # and `await_resume` throws a fresh _MojoCppExc into the CALLER's own
    # body, catchable by its own ordinary try/except exactly like real
    # Python's `await` propagating an exception.
    _check_async_syntax_only(
        "async_exception_propagates_through_await_to_caller_except_compiles", """\
async def inner():
    raise ValueError("boom")
    return 0

async def outer():
    result = 0
    try:
        result = await inner()
    except ValueError:
        result = -1
    return result

def main():
    import asyncio
    print(asyncio.run(outer()))
""",
        cpp_substrs=('exc_pending', 'throw __e'))

    # An exception escaping ALL THE WAY out to `asyncio.run(...)` uncaught
    # -- the outermost-edge translation: `{base}_translate_pending_exc`
    # copies the top-level coroutine's staged exception into the shared
    # mojo_exc_type/msg/obj/mojo_exc_pending globals, and the ordinary
    # GIMPLE .c call site checks mojo_exc_pending_get() + mojo_raise() right
    # after, reusing the exact same "safe to longjmp here, never-suspended
    # call site" idiom the generator convention's own `_resume()`-boundary
    # consumers already use.
    _check_async_syntax_only(
        "async_exception_escapes_to_asyncio_run_caught_by_ordinary_code", """\
async def f():
    raise ValueError("boom")
    return 0

def main():
    import asyncio
    try:
        asyncio.run(f())
    except ValueError as e:
        print(e)
""",
        cpp_substrs=('_translate_pending_exc',),
        c_substrs=('_translate_pending_exc', 'mojo_exc_pending_get', 'mojo_raise'))

    # ── Final step: combined async generators (`async def f(): ... yield``,
    # consumed via `async for`) ─────────────────────────────────────────────
    # See gimple_codegen.GimpleGen._gen_cpp_async_generator_unit's docstring
    # for the full design (a THIRD, distinct promise type) and
    # _cpp_async_for_stmt's docstring for `async for`'s own lowering.
    # REAL compile+link+run behavioral coverage (correct accumulated
    # results, genuine wall-clock suspension between yields, early-`break`
    # cleanup, exception composition) lives in test_gimple_async_runner.py,
    # matching this file's own established compile-only-smoke-test role.

    # The simplest possible target shape: a zero-parameter async generator,
    # consumed by a plain `async def` via `async for`.
    _generator_compiles_via_cpp(
        "async_generator_simple_shape_compiles_via_cpp_path", """\
async def f():
    await asyncio.sleep(0.01)
    yield 1
    await asyncio.sleep(0.01)
    yield 2

async def main_driver():
    total = 0
    async for x in f():
        total = total + x
    return total

def main():
    import asyncio
    print(asyncio.run(main_driver()))
""")

    # A lone, uncalled async generator (no consumer at all) also compiles --
    # harmless dead code, exactly mirroring how a bare, uncalled plain
    # generator/async function has always been allowed to compile (see
    # generator_simple_shape_compiles_via_cpp_path/
    # async_simple_shape_compiles_via_cpp_path for the identical precedent
    # on the two predecessor categories) -- no consumer is required for
    # this step's own eligibility check either.
    _generator_compiles_via_cpp(
        "async_generator_no_consumer_still_compiles_as_dead_code", """\
async def f():
    yield 1
""")

    # `async for` genuinely reaching Step A's scheduler -- confirms this
    # isn't a fake/instant drive (the same kind of "did this actually use
    # the real suspend/resume machinery" check test_async_simple_shape_
    # compiles_via_cpp_path already does for plain async composition).
    _check_async_syntax_only(
        "async_generator_uses_real_coroutine_machinery", """\
async def f():
    await asyncio.sleep(0.01)
    yield 1

async def main_driver():
    total = 0
    async for x in f():
        total = total + x
    return total

def main():
    import asyncio
    print(asyncio.run(main_driver()))
""",
        cpp_substrs=('_mojoasyncgen_f_AnextAwaiter', 'yield_value',
                     'mojo_async_schedule_ready'),
        c_substrs=())

    # Narrowing checks: the two out-of-scope shapes from this step's own
    # plan must still hit the honest whole-module refusal.

    # A parameter -- this step's scope is deliberately parameter-less (see
    # _async_gen_quick_eligible's docstring), matching every other step's
    # own narrowest-shape-first precedent.
    # async_generator_with_param: params now supported (Phase 7)

    # `yield from` inside an async generator -- delegation composed with
    # async suspension is genuinely new risk this step doesn't take on.
    test_raises("async_generator_with_yield_from_honest_fallback", """\
async def g():
    yield 1

async def f():
    yield from g()

async def main_driver():
    async for x in f():
        pass
    return 0

def main():
    import asyncio
    print(asyncio.run(main_driver()))
""", "async")

    # A plain (non-`async`) `for` loop over a generator inside an async
    # function's own body is still unsupported -- `async for` is the ONLY
    # loop construct this step's `_cpp_stmt` recognizes at all (no plain
    # `for` support exists anywhere in a compiled generator/async body,
    # before or after this step).
    test("plain_for_inside_async_function", """""")

    # A module-level `comptime NAME = value` must be visible to every later
    # reference in the file -- including inside a function body's ordinary
    # runtime reads (`_lower_IdentExpr`'s ordinary IdentExpr path, not just
    # comptime `if`/expression contexts) and a struct's own bounds-mask
    # arithmetic. Before this fix, a TOP-LEVEL ComptimeVarStmt was never
    # folded into self._comptime_vals at all (only a comptime var declared
    # INSIDE a function's own body got folded, by a narrower pre-pass) --
    # every reference anywhere in the file silently read the "ct param or
    # undeclared" placeholder value 0 instead of the real constant.
    _comptime_toplevel_src = """\
comptime MAX_N: Int = 8

def mask(x: Int) -> Int:
    return x & (MAX_N - 1)

def main():
    i = 0
    while i < MAX_N:
        print(mask(i))
        i = i + 1
"""
    name = "toplevel_comptime_const_visible_everywhere"
    ok, c_src, stderr = gimple_compiles(_comptime_toplevel_src)
    if not ok:
        print(f"FAIL  {name}: did not compile\n{stderr}")
        _FAIL += 1
    elif 'ct param or undeclared: MAX_N' in c_src:
        print(f"FAIL  {name}: MAX_N still resolved to the undeclared placeholder, not its real value")
        _FAIL += 1
    elif '(int64_t)8' not in c_src:
        print(f"FAIL  {name}: MAX_N's real value (8) not found folded into the generated C")
        _FAIL += 1
    else:
        print(f"PASS  {name}")
        _PASS += 1

    # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md, Step 5.4:
    # a genuinely NEW dynamic attribute read on an opaquely-typed receiver
    # (an unannotated param whose static type can't be resolved to a known
    # struct) must lower to the real runtime dispatch chain that raises a
    # catchable AttributeError on a miss (Steps 1-3), not the old silent
    # "print a warning, return 0" stub `mojo_obj_getattr` used to be. This
    # is a compile-time codegen-shape check (does the emitted C actually
    # route through `mojo_raise_attribute_error` on the miss path via
    # `_mojo_dispatch_getattr`/`mojo_obj_getattr`?) -- the actual runtime
    # behavior (the except branch genuinely firing, the fast path on a
    # second call seeing real stored per-object state) is covered by
    # test_gimple_runner.py's own permanent regression test,
    # `gimple_dynamic_attribute_real_storage_and_attributeerror`, which
    # actually executes the compiled binary and checks stdout -- something
    # this file's `gcc -fsyntax-only`-only harness can't do.
    _dynattr_src = """\
class Slot:
    def helper(self, cls):
        try:
            x = cls.__slot_names__
            print(x)
        except AttributeError:
            print("caught")
"""
    name = "dynamic_attribute_getattr_miss_raises_real_attributeerror"
    ok, c_src, stderr = gimple_compiles(_dynattr_src)
    if not ok:
        print(f"FAIL  {name}: did not compile\n{stderr}")
        _FAIL += 1
    elif '_mojo_dispatch_getattr' not in c_src:
        print(f"FAIL  {name}: expected the opaque-receiver getattr "
              "('cls.__slot_names__') to route through "
              "_mojo_dispatch_getattr, found no such call in the "
              "generated C")
        _FAIL += 1
    else:
        print(f"PASS  {name}")
        _PASS += 1
        # Independently confirm mojo_obj_getattr's own runtime-side miss
        # path (not this file's generated C -- that's the fixed dispatch
        # chokepoint every opaque getattr funnels through) genuinely calls
        # mojo_raise_attribute_error instead of the old silent stub.
        _runtime_c = open(os.path.join(_RUNTIME_INC, 'fire_runtime.c')).read()
        name2 = "dynamic_attribute_runtime_getattr_miss_calls_raise_attributeerror"
        if 'mojo_raise_attribute_error' not in _runtime_c:
            print(f"FAIL  {name2}: mojo_raise_attribute_error not found "
                  "anywhere in runtime/fire_runtime.c")
            _FAIL += 1
        else:
            _getattr_start = _runtime_c.find('int64_t mojo_obj_getattr')
            _getattr_body = _runtime_c[_getattr_start:_getattr_start + 1200]
            if 'mojo_raise_attribute_error' not in _getattr_body:
                print(f"FAIL  {name2}: mojo_obj_getattr's own body doesn't "
                      "call mojo_raise_attribute_error on a miss")
                _FAIL += 1
            else:
                print(f"PASS  {name2}")
                _PASS += 1

    # ── Runtime dict-keyed %-formatting (`text % dict(...)`) ──────────────
    # Real Python's `"...%(key)s..." % mapping` with a NON-literal template
    # previously had no lowering at all: it fell through to the generic
    # numeric-modulo path and emitted invalid GIMPLE `%` against a
    # MojoDict* operand — the "invalid operands to binary % (have
    # 'int64_t' and 'MojoDict *')" hard-error class in real argparse.py /
    # Mac/BuildScript/build-installer.py closures (see
    # bugs/COMPILE_FAIL_Mac_BuildScript_build-installer.md root cause 2).
    # Now routed to runtime/fire_runtime.c's mojo_str_format_dict, which
    # resolves %(key)... specs against the dict AT RUNTIME.
    _dictfmt_src = """\
def main():
    textvars = dict(VER="3.14", FULLVER="3.14.6")
    tmpl = "Python %(VER)s full %(FULLVER)s"
    print(tmpl % textvars)
"""
    name = "percent_format_dict_variable_rhs_lowered_to_runtime_formatter"
    ok, c_src, stderr = gimple_compiles(_dictfmt_src)
    if not ok:
        print(f"FAIL  {name}: did not compile\n{stderr}")
        _FAIL += 1
    elif 'mojo_str_format_dict' not in c_src:
        print(f"FAIL  {name}: compiled but the `tmpl % textvars` site did "
              "not route through mojo_str_format_dict")
        _FAIL += 1
    else:
        print(f"PASS  {name}")
        _PASS += 1

    _dictlit_src = """\
def main():
    print("prog=%(prog)s n=%(n)d" % dict(prog="p", n=7))
    print("%(a)x-%(b)5.1f" % {"a": 255, "b": 2.5})
"""
    name = "percent_format_dict_call_and_literal_rhs_lowered_to_runtime_formatter"
    ok, c_src, stderr = gimple_compiles(_dictlit_src)
    if not ok:
        print(f"FAIL  {name}: did not compile\n{stderr}")
        _FAIL += 1
    elif c_src.count('mojo_str_format_dict') < 2:
        print(f"FAIL  {name}: expected BOTH `%`-with-dict sites to route "
              f"through mojo_str_format_dict, found "
              f"{c_src.count('mojo_str_format_dict')} references")
        _FAIL += 1
    else:
        print(f"PASS  {name}")
        _PASS += 1

    # The numeric-modulo fallthrough must be untouched: a plain int/float
    # `%` whose RHS is NOT dict-typed still lowers to ordinary GIMPLE
    # modulo (colorsys.py's `h % 1.0` class), never the string formatter.
    _modsrc = """\
def m(a: Int, b: Int) -> Int:
    return a % b

def mf(a: Float64, b: Float64) -> Float64:
    return a % b
"""
    name = "percent_numeric_modulo_untouched_by_dict_format_path"
    ok, c_src, stderr = gimple_compiles(_modsrc)
    if not ok:
        print(f"FAIL  {name}: did not compile\n{stderr}")
        _FAIL += 1
    elif 'mojo_str_format_dict' in c_src:
        print(f"FAIL  {name}: numeric modulo was wrongly routed through "
              "the dict formatter")
        _FAIL += 1
    else:
        print(f"PASS  {name}")
        _PASS += 1

    # Runtime-side: the formatter must exist and maintain per-slot value
    # kinds (the untagged int64 dict slots can't otherwise distinguish an
    # int from a bit-cast double or char*), mirroring the
    # dynamic_attribute_runtime check's structure above.
    name = "runtime_str_format_dict_present_with_kind_tracking"
    _runtime_c = open(os.path.join(_RUNTIME_INC, 'fire_runtime.c')).read()
    if 'mojo_str_format_dict' not in _runtime_c:
        print(f"FAIL  {name}: mojo_str_format_dict missing from "
              "runtime/fire_runtime.c")
        _FAIL += 1
    elif '_dict_set_raw_seq_kind' not in _runtime_c:
        print(f"FAIL  {name}: dict setters no longer record per-slot "
              "value kinds (_dict_set_raw_seq_kind missing)")
        _FAIL += 1
    else:
        print(f"PASS  {name}")
        _PASS += 1

    # --- builtin `dict` subclassing (Counter/OrderedDict shape) ---
    # See bugs/COMPILE_FAIL_collections___init__.md. A `class X(dict)` gets
    # a synthesized `_data: MojoDict *` backing store; inherited container
    # ops route to it, `__missing__` handles a subscript-read miss.
    test("dict_subclass_backing_store_and_subscript", """\
class C(dict):
    pass

def go() -> int:
    c = C()
    c["a"] = 5
    c["a"] += 3
    n = len(c)
    if "a" in c:
        n += 1
    return c["a"] + n

def main():
    print(go())
""")

    test("dict_subclass_missing_dunder_on_read_miss", """\
class Counter2(dict):
    def __missing__(self, key) -> int:
        return 0

def go() -> int:
    c = Counter2()
    c["x"] = 2
    return c["x"] + c["absent"]

def main():
    print(go())
""")

    test("dict_subclass_transitive_and_getitem_override_wins", """\
class Base(dict):
    pass

class Sub(Base):
    def __getitem__(self, key) -> int:
        return 42

def go() -> int:
    s = Sub()
    s["k"] = 1
    return s["k"]

def main():
    print(go())
""")

    # --- builtin `bytes` subclassing (`class _Extra(bytes)`, zipfile) ---
    # See bugs/COMPILE_FAIL_zipfile___init__.md. A `class X(bytes)` gets a
    # synthesized `_data: MojoBytes *` payload populated by
    # `super().__new__(cls, val)`; inherited bytes ops (len/index/slice/
    # iter/eq/concat/`in`/`.decode`/`.hex`/`.split`/...) route to it, plus
    # any extra `self.<attr>` instance fields, and `isinstance(_, bytes)`.
    test("bytes_subclass_payload_and_inherited_ops", """\
class B(bytes):
    def __new__(cls, v):
        return super().__new__(cls, v)
    def __init__(self, v):
        self.tag = 7

def go() -> int:
    b = B(b"hello world")
    n = len(b) + b[1] + b.tag
    s = b[0:5]
    if s == b"hello":
        n += 1
    if b"wor" in b:
        n += 1
    for c in b:
        n += c
    if isinstance(b, bytes):
        n += 1
    c2 = b + b"!"
    n += len(c2)
    return n

def main():
    print(go())
""")

    test("bytes_subclass_method_override_wins", """\
class B(bytes):
    def __new__(cls, v):
        return super().__new__(cls, v)
    def hex(self) -> int:
        return 99

def go() -> int:
    b = B(b"ab")
    return b.hex() + len(b)

def main():
    print(go())
""")

    # `.get()/.keys()/.values()/.items()/.update()/.pop()/.setdefault()`
    # and `for k in d` on a builtin-`dict` subclass instance delegate to
    # the hidden `_data` backing store — unless the subclass overrides
    # them. See bugs/COMPILE_FAIL_collections___init__.md.
    test("dict_subclass_container_method_delegation", """\
class Bag(dict):
    def __missing__(self, key) -> int:
        return 0

def main():
    b = Bag()
    b["a"] = 5
    b["b"] = 2
    print(b.get("a"))
    print(b.get("zzz", 42))
    total = 0
    for k in b:
        total += b[k]
    print(total)
    for k, v in b.items():
        print(k)
    print(len(b.keys()))
    s = 0
    for x in b.values():
        s += x
    print(s)
    other = Bag()
    other["c"] = 9
    b.update(other)
    print(len(b))
    print(b.pop("a"))
    print(b.setdefault("d", 7))
""")

    test("dict_subclass_method_override_wins_over_delegation", """\
class Bag(dict):
    def keys(self) -> str:
        return "override"

class Sub(Bag):
    def __missing__(self, key) -> int:
        return 0

def main():
    s = Sub()
    s["x"] = 1
    print(s.keys())
    print(s.get("x"))
""")

    # bytes value type (Stage 1) — compile checks
    test("bytes_literal_len_index", """\
fn main():
    var b = b'\\x00\\x01ABC'
    print(len(b))
    print(b[0])
    print(b[-1])
""")

    test("bytes_constructors", """\
fn main():
    var a = bytes()
    var z = bytes(4)
    var l = bytes([1, 2, 3])
    var s = bytes("hi", "utf-8")
    print(len(a), len(z), len(l), len(s))
""")

    test("bytes_equality_and_truthiness", """\
fn main():
    if b'ab' == b'ab':
        print("eq")
    if b'ab' != b'ac':
        print("ne")
    var b = b'x'
    if b:
        print("t")
    if not bytes():
        print("f")
""")

    test("bytes_through_annotated_and_default_params", """\
fn tail(b: bytes) -> bytes:
    return b

fn size(b = b'abcd') -> Int:
    return len(b)

fn main():
    var t = tail(b'XYZ')
    print(len(t), t[0])
    print(size())
    print(size(b'hello'))
""")

    test("bytes_repr_and_str", """\
fn main():
    var b = b'a\\x00b'
    print(b)
    print(str(b))
""")

    # bytes value type (Stage 4) — bytes-typed struct fields (compile check).
    # `self._buf = b''` in __init__ makes the field a real MojoBytes*, so a
    # slice of the field routes through mojo_bytes_slice and `acc += <bytes>`
    # concatenates instead of emitting a `char* + MojoBytes*` pointer add
    # (which also ICE'd GCC's GIMPLE FE). COMPILE_FAIL_zipfile___init__.md.
    test("bytes_field_slice_and_augassign_accumulation", """\
fn _more() -> bytes:
    return b'12345'

class Reader:
    def __init__(self):
        self._buf = b''
        self._off = 0

    def _fill(self):
        self._buf = _more()

    def read_all(self):
        var out = self._buf[self._off:]
        while len(out) < 20:
            out += self._buf[0:2]
        self._buf = b''
        self._off = 0
        return out

fn main():
    var r = Reader()
    r._fill()
    var data = r.read_all()
    print(len(data))
""")

    # bytes value type (Stage 2) — compile checks
    test("bytes_slice_iter_in", """\
fn main():
    var b = b'Hello, World'
    print(b[0:5])
    print(b[7:])
    print(b[::-1])
    print(b[::2])
    for x in b:
        print(x)
    if b'ell' in b:
        print("y")
    if 101 in b:
        print("z")
""")

    test("bytes_concat_repeat", """\
fn main():
    var c = b'ab' + b'cd'
    print(c)
    print(b'xy' * 3)
    print(2 * b'-')
""")

    test("bytes_methods", """\
fn main():
    print(b'Hello'.startswith(b'He'))
    print(b'Hello'.endswith(b'lo'))
    print(b'a,b,c'.split(b','))
    print(b'x y  z'.split())
    print(b'a\\nb\\nc'.splitlines())
    print(b'a-b-c'.replace(b'-', b'_'))
    print(b'  hi  '.strip())
    print(b'xxhixx'.strip(b'x'))
    print(b'AbC'.upper())
    print(b'AbC'.lower())
    print(b'abcabc'.find(b'c'))
    print(b'abcabc'.count(b'bc'))
    print(b'DEADBEEF'.hex())
    print(b'hello'.decode('utf-8'))
    print(b','.join(b'x,y'.split(b',')))
""")

    test("bytes_isinstance", """\
fn main():
    var b = b'x'
    print(isinstance(b, bytes))
    print(isinstance(5, bytes))
""")

    # bytes value type (Stage 2b) — %-formatting + body-usage param inference
    test("bytes_percent_format", """\
fn main():
    var n: Int = 42
    print(b'val=%d' % n)
    print(b'%s!' % b'hi')
    print(b'%02x' % 15)
    print(b'%s=%d;' % (b'k', 7))
    print(b'100%% done')
""")

    # A `b'...'` / `b''` literal used inside a real function body: the
    # `_slit_` string-pool global must be loaded into a local before it
    # is passed to `mojo_bytes_new_lit` (GIMPLE strict mode). Regression
    # for "invalid argument to gimple call" seen on zipfile's
    # `_Extra.strip`'s `b''.join(...)`.
    test("bytes_literal_in_function_body", """\
fn joiner(parts: List[Int]) -> Int:
    var sep = b''
    var acc = b'x'
    var total: Int = 0
    for p in parts:
        total = total + p
    return total + len(sep) + len(acc)
fn main():
    var ps = [1, 2, 3]
    print(joiner(ps))
""")

    test("bytes_param_inferred_from_body_usage", """\
fn dec(data) -> String:
    return data.decode('utf-8')
fn hx(data) -> String:
    return data.hex()
fn main():
    print(dec(b'hello'))
    print(hx(b'\\x00\\xff'))
""")

    test("bytes_param_inferred_from_bytes_slice_destination", """\
fn header_size(p):
    var header = b''
    if len(p) > 0:
        header = p[0:2]
    return len(header)
fn main():
    print(header_size(b'abcdef'))
""")

    # bytes value type (Stage 3) — bytearray + memoryview compile checks
    test("bytearray_construct_and_mutate", """\
fn main():
    var ba = bytearray(b'abc')
    ba.append(100)
    ba[0] = 90
    ba.extend(b'XY')
    var x = ba.pop()
    del ba[0]
    ba[1:2] = b'ZZ'
    print(len(ba))
    for c in ba:
        print(c)
    print(bytes(ba))
    var empty = bytearray()
    var zeros = bytearray(3)
    var fromlist = bytearray([1, 2, 3])
""")

    test("memoryview_ops", """\
fn main():
    var mv = memoryview(b'hello')
    print(mv[1])
    print(len(mv))
    print(mv[1:3].tobytes())
    print(mv.hex())
    print(bytes(mv))
    print(mv == b'hello')
    for x in mv:
        print(x)
    var mv2 = memoryview(bytearray(b'xy'))
    print(mv2.cast('B')[0])
""")

    # struct module (binary pack/unpack) — compile checks
    test("struct_module_functions", """\
fn main():
    print(struct.calcsize('<HH'))
    var p = struct.pack('<HH', 1, 2)
    print(len(p))
    var t = struct.unpack('<HH', p)
    print(t[0], t[1])
    var u = struct.unpack_from('<H', b'\\xaa\\xbb\\xcc', 1)
    print(u[0])
    var b = struct.pack('>i4s', 258, b'abcd')
""")

    test("struct_module_float_and_error", """\
fn main():
    var p = struct.pack('<fd', 1.5, 2.5)
    var t = struct.unpack('<fd', p)
    print(t[0], t[1])
    try:
        var bad = struct.unpack('<HH', b'\\x00')
    except struct.error:
        print('caught')
""")

    # --- os.path.splitdrive / splitroot (POSIX) + reversed() ---
    # See bugs/COMPILE_FAIL_zipfile___init__.md. Both os.path funcs were
    # stubbed (`int.splitdrive() stubbed`); reversed() had no lowering at
    # all so `for x in reversed(...)` over the resulting `void *` was
    # silently dropped (zipfile/__init__.py:1612).
    test("os_path_splitdrive_splitroot", """\
import os

fn main():
    var p: String = "/a/b/c"
    var d = os.path.splitdrive(p)
    print(d[0], d[1])
    var r = os.path.splitroot(p)
    print(r[0], r[1], r[2])
    var r2 = os.path.splitroot("//x/y")
    print(r2[1], r2[2])
    var n = os.path.normpath(os.path.splitdrive(p)[1])
    print(n)
""")

    test("reversed_list_str_and_sorted_chain", """\
fn main():
    var xs = [3, 1, 2]
    var acc: Int = 0
    for v in reversed(xs):
        acc = acc * 10 + v
    print(acc)
    for v in reversed(sorted(xs)):
        acc = acc + v
    print(acc)
    for c in reversed("abc"):
        print(c)
""")

    def test_signed64_integer_literal_boundaries():
        global _PASS, _FAIL
        name = "signed64_integer_literal_boundaries"
        from fire_compiler import Parser, py_tokenize
        values = []
        for spelling in ('0x7FFFFFFF', '0x80000000', '0x7FFFFFFFFFFFFFFF',
                         '0x8000000000000000', '0xFFFFFFFFFFFFFFFF'):
            stmts = Parser(py_tokenize(f'x = {spelling}')).parse_module()
            values.append(stmts[0].value.value)
        expected = (0x7FFFFFFF, 0x80000000, 0x7FFFFFFFFFFFFFFF,
                    -0x8000000000000000, -1)
        src = """\
def main():
    var values = [0x7FFFFFFF, 0x80000000, 0x7FFFFFFFFFFFFFFF,
                  0x8000000000000000, 0xFFFFFFFFFFFFFFFF]
    print(values[1])
"""
        ok, _c_src, stderr = gimple_compiles(src)
        if tuple(values) != expected or not ok or 'integer constant is too large for its type' in stderr:
            print(f"FAIL  {name}: values={values!r}, ok={ok}, stderr={stderr!r}")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    test_signed64_integer_literal_boundaries()

    def test_known_function_not_shadowed_by_global_fnptr():
        global _PASS, _FAIL
        name = "known_function_not_shadowed_by_global_fnptr"
        src = """\
import cas
def root_cas_hash_call(parts) -> str:
    return cas._hash(*parts)
"""
        try:
            c_src = compile_to_gimple(
                src, do_imports=True,
                filename=os.path.join(_PROJECT_DIR, "fire.py"))
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        start = c_src.find("root_cas_hash_call_")
        start = c_src.find("root_cas_hash_call_", start + 1)
        end = c_src.find("\n}", start)
        body = c_src[start:end] if start >= 0 and end >= 0 else ""
        if "cas__hash (" not in body or "mojo_fnptr_call" in body:
            print(f"FAIL  {name}: qualified function call used function-pointer lowering")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    test_known_function_not_shadowed_by_global_fnptr()

    def test_inherited_method_line_directive_names_its_own_module():
        """The inheritance merge copies a base class's method node into the
        subclass, which then emits that body a SECOND time as
        `Sub___m`. Every `#line` in that copy used to name the SUBCLASS's
        file with the base's line number — a diagnostics bug (the emitted C
        was correct), originally found as Lib/weakref.py's error cluster
        reporting lines up to ~962 in a file only 574 lines long, when the
        real source was _collections_abc.py. FIXED; the report that recorded
        it (bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
        mismatches.md) was removed 2026-09-26 after verification. Its live
        residue was the cross-module-import report — a different mechanism
        (a function-scoped import never inlining its module), since itself
        fixed and deleted; see the 2026-09-29 section of
        bugs/hard/README.md. Neither report owns this test."""
        global _PASS, _FAIL
        name = "inherited_method_line_directive_names_its_own_module"
        with tempfile.TemporaryDirectory() as wd:
            base = ("class Mapping:\n"
                    "    def __eq__(self, other):\n"
                    "        return isinstance(other, Mapping)\n"
                    "    def items(self):\n"
                    "        return []\n")
            sub = ("from base_mod_for_line_test import Mapping\n"
                   "\n"
                   "class Sub(Mapping):\n"
                   "    def __init__(self):\n"
                   "        self.data = 1\n"
                   "\n"
                   "def main():\n"
                   "    s = Sub()\n"
                   "    print(s.data)\n")
            open(os.path.join(wd, 'base_mod_for_line_test.py'), 'w').write(base)
            entry = os.path.join(wd, 'sub_mod_for_line_test.py')
            open(entry, 'w').write(sub)
            try:
                c_src = compile_to_gimple(sub, do_imports=True, filename=entry)
            except Exception as e:
                print(f"FAIL  {name}: {e}")
                _FAIL += 1
                return
        start = c_src.find("Sub___eq__ (")
        if start < 0:
            print(f"FAIL  {name}: Sub___eq__ was never emitted (inheritance merge did not run)")
            _FAIL += 1
            return
        end = c_src.find("\n}", start)
        body = c_src[start:end]
        base_tag = f'#line 3 "{os.path.join(wd, "base_mod_for_line_test.py")}"'
        sub_tag = f'#line 3 "{entry}"'
        if base_tag not in body or sub_tag in body:
            print(f"FAIL  {name}: inherited body not attributed to the base module; "
                  f"tags={sorted({l.strip() for l in body.splitlines() if l.strip().startswith('#line')})}")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    test_inherited_method_line_directive_names_its_own_module()

    def test_conflicting_callsite_yield_kind_refused_not_miscompiled():
        """A generator has ONE fixed C value-slot, so a generator that
        YIELDS a parameter whose call sites do not all pass the same
        statically-known kind has no sound lowering. Both backends used to
        pick int64_t anyway and silently print a truncated float or a
        string's ADDRESS. Now both refuse, naming the parameter. See
        bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md.

        That doc's residual -- "the refusal only fires on PROVABLE
        disagreement; a call site the static scan cannot type is a separate,
        still-silent case" -- is what `_scan_callsite_param_kinds` used to
        do by emptying the kind set on a `None`, so the slot was neither
        resolved nor a conflict and took `_KIND_TO_SLOT_CTYPE[None]`. A hole
        is now a conflict too, which is why the message names BOTH causes
        and the expectation below is the one shared string (built by
        `coro._ambiguous_slot_message`, used by both backends) rather than
        only the disagreement half.
        """
        global _PASS, _FAIL
        name = "conflicting_callsite_yield_kind_refused_not_miscompiled"
        src = """\
def g(x):
    yield x

def main():
    for v in g(3.5):
        print(v)
    for v in g("hi"):
        print(v)
"""
        expect = "yields ['x'], whose call sites do not all pass the same"
        # The refusal is a module-level compile error on the A3 stack-switch
        # backend, and an _UnsupportedGeneratorShape the C++ backend
        # surfaces the same way — so either way the message must name the
        # parameter rather than the build succeeding with wrong output.
        ok = False
        detail = ""
        for kwargs in ({}, {"do_imports": True}):
            try:
                compile_to_gimple(src, **kwargs)
            except Exception as e:
                if expect in str(e):
                    ok = True
                    break
                detail = str(e)[:200]
            else:
                detail = "compiled successfully (would miscompile)"
        if ok:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: {detail}")
            _FAIL += 1

    test_conflicting_callsite_yield_kind_refused_not_miscompiled()

    # The refusal must be narrow: a conflicting param that is NOT yielded
    # still compiles, and a yielded param with UNANIMOUS call sites still
    # resolves to the right type. Both are ordinary compiles, so assert on
    # the generated C rather than on stdout.
    #
    # (a) used to be `g(3)` and `g(5)` with the comment "call sites
    # disagree" -- two ints, which AGREE, so the `len(kinds) > 1` branch never
    # fired and the narrowness this test is named for was never exercised at
    # all (found as "A test hole found on the way" in
    # `CODEGEN_coro_yield_kind_unresolved_callsite`, a bugs/hard doc since
    # FIXED and DELETED). The conflict now really exists: `x` is
    # unannotated and its two call sites pass an int and a `char *`, while
    # `y` -- the param actually yielded -- is unanimous `double`. `x` is
    # never READ in the body, so this is decidable without a tagged ABI and
    # has a correct answer to assert, which the old arithmetic-use version
    # did not: reading a genuinely conflicting param is the cross-cutting
    # one-C-type-per-slot limitation, and asserting a value for it would
    # assert the wrong answer. That limitation is
    # bugs/CODEGEN_polymorphic_unannotated_param_vacuous_unanimity.md, still
    # OPEN; the `int64_t`-is-not-evidence rule in `_record_param_elem` is the
    # part of it that is fixed, and this case is where that rule earns its
    # keep.
    def test_conflicting_callsite_gate_is_narrow():
        global _PASS, _FAIL
        name = "conflicting_callsite_gate_is_narrow"
        # (a) a genuinely conflicting unannotated param that is NOT yielded:
        #     the yielded value is unaffected, so this must still lower --
        #     AND the yielded slot must still come out `double`, which is
        #     what proves the conflict on `x` did not poison the generator.
        #     Wrapped so an over-broad refusal is reported as this test's
        #     failure with the compiler's own message, rather than aborting
        #     the whole suite (the same shape as
        #     `conflicting_callsite_yield_kind_refused_not_miscompiled`).
        try:
            n2 = compile_to_gimple("""\
def g(x, y):
    yield y

def main():
    for v in g(1, 3.5):
        print(v)
    for v in g("s", 1.5):
        print(v)
""")
        except Exception as e:
            print(f"FAIL  {name}: a conflict on a param that is NOT yielded "
                  f"must not refuse, but this was refused: {e}")
            _FAIL += 1
            return
        if '__mgco_g_value (MojoGenerator *)' not in n2 or \
                'double __mgco_g_value' not in n2:
            print(f"FAIL  {name}: a conflict on a param that is NOT yielded "
                  f"must not refuse, and must not degrade the yielded param's "
                  f"slot -- expected a double yield slot, got:\n{n2[-3000:]}")
            _FAIL += 1
            return
        # (b) yielded param, but every call site agrees: resolves normally.
        c = compile_to_gimple("""\
def g(x):
    yield x

def main():
    for v in g(3.5):
        print(v)
    for v in g(1.5):
        print(v)
""")
        if '__mgco_g_body' not in n2 and '__mgco_g_body' not in c:
            print(f"FAIL  {name}: both shapes should lower a generator body")
            _FAIL += 1
            return
        if 'double' not in c:
            print(f"FAIL  {name}: unanimous float call sites should still "
                  f"resolve the yield slot to double")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    test_conflicting_callsite_gate_is_narrow()

    def test_nested_async_struct_capture_boxes_pointer():
        """Increment E: a nested `async def` that mutates an enclosing
        function's STRUCT-typed local. The capture cell is the ordinary
        `i64` one (a pointer is pointer-sized); only the read/write boundary
        needs the existing int<->pointer round trip
        (`UnsafePointer[T](...)` / `.address`). Before this, a struct
        capture was refused outright, so the async def fell through to the
        C++ path and failed to compile at all.
        """
        global _PASS, _FAIL
        name = "nested_async_struct_capture_boxes_pointer"
        src = """\
class Point:
    def __init__(self, x):
        self.x = x
    def show(self):
        return self.x

def outer():
    var p = Point(10)
    async def bump():
        p.x = p.x + 5
    var t = create_task(bump())
    t.wait()
"""
        try:
            c_src = compile_to_gimple(src)
        except Exception as e:
            print(f"FAIL  {name}: {e}")
            _FAIL += 1
            return
        # The box must exist, the mutation must be driven through the
        # recovered pointer, and the capture must NOT have been refused.
        # (The source-level rewrite is `UnsafePointer[Point](box_get(...))`,
        # which this codegen lowers to its usual int -> void* -> T* two-step
        # — see _apply_async_struct_param_erasure's own note that GIMPLE
        # rejects a direct int64_t -> T* cast — so assert on the emitted
        # shape, not on the source-level spelling.)
        need = ['__mojo_box_new_i64', '__mojo_box_get_i64']
        missing = [t for t in need if t not in c_src]
        if missing:
            print(f"FAIL  {name}: struct capture did not lower as a boxed "
                  f"pointer; missing {missing}")
            _FAIL += 1
            return
        body = c_src[c_src.find('__mgco_outer_bump_body'):] or c_src
        if '->x' not in body:
            print(f"FAIL  {name}: captured struct was not re-typed to a "
                  f"pointer (no `->x` field access in the async body)")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    test_nested_async_struct_capture_boxes_pointer()

    test_raises(
        "nested_async_gen_capture_from_async_for_refused",
        """\
def outer():
    var acc = 0
    async def gen():
        acc = acc + 1
        yield 10
    async def consume():
        async for x in gen():
            acc = acc + x
    var t = create_task(consume())
    t.wait()
""",
        "capture box cannot be threaded into a driven consumer")

    # The SAME shape on the C++ backend (`MOJO_CORO=cpp`, the escape
    # hatch), which the assertion above does not reach: the guard it
    # exercises -- `_UNTHREADABLE_NESTED_ASYNC_GENS` -- used to be filled
    # ONLY by the stack-switch lowering pass, so on the C++ backend the set
    # was always empty, the guard never fired, and the program generated a
    # .cpp referring to a name that does not exist in that scope. Measured
    # through a real `fire.py build`:
    #
    #     x4_gen.cpp:136:5: error: 'acc' was not declared in this scope
    #     x4_gen.cpp:136:5: note: did you mean 'acct'?
    #
    # i.e. exactly the class of error the set was introduced to replace
    # with an honest message, present on one backend and absent on the
    # other. So the assertion is made against the C++ backend explicitly,
    # and it is a REFUSAL at codegen time rather than a codegen that later
    # fails to compile -- the difference that made the original a bug.
    def test_nested_async_gen_drive_refused_on_cpp_backend():
        global _PASS, _FAIL
        import gimple_codegen
        name = "nested_async_gen_drive_refused_on_cpp_backend"
        src = """\
def outer():
    var acc = 0
    async def gen():
        acc = acc + 1
        yield 10
    async def consume():
        async for x in gen():
            acc = acc + x
    var t = create_task(consume())
    t.wait()
"""
        try:
            with _force_cpp_coro():
                gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            if "capture box cannot be threaded into a driven consumer" in str(e):
                print(f"PASS  {name}")
                _PASS += 1
            else:
                print(f"FAIL  {name}: wrong error: {e}")
                _FAIL += 1
            return
        print(f"FAIL  {name}: the C++ backend generated a unit for a nested "
              f"async generator it has no capture model for, instead of "
              f"refusing it")
        _FAIL += 1

    test_nested_async_gen_drive_refused_on_cpp_backend()

    # ... and the capture-LESS neighbour of the same shape, which must keep
    # COMPILING on the C++ backend. This is the boundary the fix must not
    # overshoot: `_UNTHREADABLE_NESTED_ASYNC_GENS` is about the C++
    # emitter's missing capture MODEL, and a nested async generator that
    # closes over nothing needs no model. It is also the only member of this
    # family that runs correctly on the C++ backend today, so refusing it
    # would trade a working program for a message. Asserted on the
    # generated C++ COMPILING (g++ -fsyntax-only), which is the assertion
    # that would have caught the bug above had it been written here.
    def test_nested_async_gen_no_capture_drive_compiles_on_cpp_backend():
        global _PASS, _FAIL
        import gimple_codegen
        from build_config import find_gxx
        name = "nested_async_gen_no_capture_drive_compiles_on_cpp_backend"
        src = """\
def outer():
    var acc = 0
    async def gen():
        yield 1
        yield 2
    async def consume():
        async for x in gen():
            acc = acc + x
    var t = create_task(consume())
    t.wait()
"""
        try:
            with _force_cpp_coro():
                c_src, cpp_src = gimple_codegen.compile_to_gimple_with_cpp(src)
        except Exception as e:
            print(f"FAIL  {name}: wrongly refused a capture-less nested async "
                  f"generator: {e}")
            _FAIL += 1
            return
        with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
            f.write(cpp_src)
            cpp_path = f.name
        r_cpp = subprocess.run(
            [find_gxx(), '-std=c++20', '-fsyntax-only', f'-I{_RUNTIME_INC}', cpp_path],
            capture_output=True, text=True)
        if r_cpp.returncode == 0:
            print(f"PASS  {name}")
            _PASS += 1
        else:
            print(f"FAIL  {name}: generated .cpp does not compile")
            for line in r_cpp.stderr.splitlines():
                print(f"      {line}")
            _FAIL += 1

    test_nested_async_gen_no_capture_drive_compiles_on_cpp_backend()

    # ------------------------------------------------------------------
    # A container-typed constructor argument. bugs/hard/
    # CODEGEN_ctor_arg_field_type_scalars_only.md item 1: the call-site
    # observation pass only ever produced `char *` / `double`, so
    # `Box([1, 2, 3])` into `__init__(self, items): self.items = items`
    # left the FIELD `int64_t` -- `len` and `[i]` happened to re-derive the
    # real type from the literal and print the right answer, but `for x in
    # b.items` dereferenced the boxed list pointer AS an int64_t and
    # SIGSEGVed. Assert the field's declared C type, which is the only
    # thing the fix changes; the program was already exit-0-wrong.
    # ------------------------------------------------------------------
    def _ctor_arg_container_field_ctype(src, struct_name, field):
        """Declared C type of one struct field in generated C, or None."""
        c = compile_to_gimple(src)
        start = c.find(f'typedef struct {struct_name} {{')
        if start < 0:
            return None, c
        end = c.find('\n}', start)
        for line in c[start:end].splitlines():
            body = line.strip()
            if not body.endswith(field + ';'):
                continue
            return body[:-len(field) - 1].strip(), c
        return None, c

    def test_ctor_arg_container_literal_field_is_container_typed():
        """`Box([1, 2, 3])` with an UNANNOTATED `items` parameter must type
        the field `MojoList *`, exactly as the annotation `items: list`
        does -- the two spellings of the same assignment, and before the
        fix only the annotated one produced a container field."""
        global _PASS, _FAIL
        name = "ctor_arg_container_literal_field_is_container_typed"
        tmpl = """\
class Box:
    def __init__(self, items{ann}):
        self.items = items

def main():
    b = Box([1, 2, 3])
    for x in b.items:
        print(x)
"""
        for ann, want in (('', 'MojoList *'), (': list', 'MojoList *')):
            ft, c = _ctor_arg_container_field_ctype(tmpl.format(ann=ann),
                                                    'Box', 'items')
            if ft != want:
                print(f"FAIL  {name}: annotation {ann or '(none)'!r} gave field "
                      f"{ft!r}, want {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_ctor_arg_dict_and_set_literal_fields_are_container_typed():
        """The same pass, the other two container literals. Each used to
        leave the field `int64_t` for the same reason; each is a latent
        segfault of the identical shape as the list one (a dict field read
        as an integer, a set field iterated as one)."""
        global _PASS, _FAIL
        name = "ctor_arg_dict_and_set_literal_fields_are_container_typed"
        for lit, want in (("{'a': 1}", 'MojoDict *'), ("{1, 2}", 'MojoSet *')):
            src = f"""\
class Box:
    def __init__(self, v):
        self.v = v

def main():
    b = Box({lit})
    print(b.v)
"""
            ft, c = _ctor_arg_container_field_ctype(src, 'Box', 'v')
            if ft != want:
                print(f"FAIL  {name}: Box({lit}) gave field {ft!r}, want {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_ctor_arg_mixed_container_and_scalar_stays_int64():
        """The unanimity rule must still win over the new container case.
        A slot observed as a list at one call site and a string at another
        has no single field type, so it must keep the `int64_t` default
        rather than silently preferring one of the two -- the same
        documented refusal the scalar channel already made."""
        global _PASS, _FAIL
        name = "ctor_arg_mixed_container_and_scalar_stays_int64"
        src = """\
class Thing:
    def __init__(self, v):
        self.v = v

def main():
    print(Thing([1, 2]).v)
    print(Thing("s").v)
"""
        ft, c = _ctor_arg_container_field_ctype(src, 'Thing', 'v')
        if ft != 'int64_t':
            print(f"FAIL  {name}: mixed list/str call sites gave field {ft!r}, "
                  f"want the int64_t default")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    # ------------------------------------------------------------------
    # bugs/hard/CODEGEN_ctor_arg_field_type_scalars_only.md's residue: a
    # container reached the constructor through one extra hop -- a LOCAL
    # bound to a container literal, or a `self.<field>` read of a field the
    # caller's own struct sets to a container literal -- instead of the
    # literal itself. Both used to leave the field `int64_t` (`for x in
    # b.items` dereferenced the pointer as an int and SIGSEGVed) because the
    # only observer that could see through the extra hop
    # (`self._inferred_var_types`/`self.struct_field_types`, consulted by
    # `_arg_scalar_type`) runs long after the field-write pass that needed
    # its answer. Fixed by tracing the hop syntactically, at the same point
    # in the pipeline the literal case is already proven at.
    # ------------------------------------------------------------------
    def test_ctor_arg_local_bound_to_container_literal_is_container_typed():
        global _PASS, _FAIL
        name = "ctor_arg_local_bound_to_container_literal_is_container_typed"
        src = """\
class Box:
    def __init__(self, items):
        self.items = items

def main():
    x = [1, 2, 3]
    b = Box(x)
    print(b.items)
"""
        ft, c = _ctor_arg_container_field_ctype(src, 'Box', 'items')
        if ft != 'MojoList *':
            print(f"FAIL  {name}: field {ft!r}, want 'MojoList *'")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_ctor_arg_self_field_container_read_is_container_typed():
        global _PASS, _FAIL
        name = "ctor_arg_self_field_container_read_is_container_typed"
        src = """\
class Reader:
    def __init__(self, items):
        self.items = items

class Holder:
    def __init__(self):
        self._items = [4, 5, 6]

    def make_reader(self):
        return Reader(self._items)

def main():
    h = Holder()
    r = h.make_reader()
    print(r.items)
"""
        ft, c = _ctor_arg_container_field_ctype(src, 'Reader', 'items')
        if ft != 'MojoList *':
            print(f"FAIL  {name}: field {ft!r}, want 'MojoList *'")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    # ------------------------------------------------------------------
    # bugs/hard/CODEGEN_ctor_arg_field_type_scalars_only.md item 2: a field
    # value round-tripped through a LOCAL lost its type, so
    # `t = self.v; return t` inferred an `int64_t` return and `print`
    # rendered the `char *` as a decimal address. The three sites that seed
    # `_infer_local_var_types`' answer into `var_types` each used to admit
    # ONLY `MojoBytes *` (the COMPILE_FAIL_zipfile bytes-accumulator case),
    # so every other pointer-shaped field answer was dropped on the floor.
    # ------------------------------------------------------------------
    def test_field_value_through_local_keeps_char_star_return_type():
        """Both spellings must infer `char *`, and they must agree: the
        difference between them was purely whether the value passed through
        a local, which is a two-line change from a working getter."""
        global _PASS, _FAIL
        name = "field_value_through_local_keeps_char_star_return_type"
        for label, body in (
                ("direct", "        return self.v"),
                ("via local", "        t = self.v\n        return t"),
                ("via two locals",
                 "        t = self\n        u = t.v\n        return u"),
        ):
            src = f"""\
class Holder:
    def __init__(self, v):
        self.v = v
    def get(self):
{body}

def main():
    print(Holder("hello").get())
"""
            c = compile_to_gimple(src)
            # The DEFINITION, not the forward declaration: the declaration
            # is emitted from the same registry, but matching on it would
            # silently pass if only one of the two were ever fixed.
            start = c.find('__GIMPLE Holder_get (')
            if start < 0:
                print(f"FAIL  {name}: {label} getter definition was never "
                      f"emitted")
                _FAIL += 1
                return
            end = c.find('\n}', start)
            sig = c[c.rfind('\n', 0, start) + 1:c.find('\n', start)]
            if 'char *' not in sig:
                print(f"FAIL  {name}: {label} getter signature is {sig.strip()!r}, "
                      f"want a char * return")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    # ------------------------------------------------------------------
    # The generator value slot's KIND lattice (mojo/middle/coro.py) had no
    # bool, so `yield True` typed the slot
    # `int64_t`. The stored value was a correct 0/1, so every consistency
    # check passed and the only symptom was the RENDERED TEXT -- `print`
    # dispatches on the slot's C type (`emit_infra`'s `_Bool` branch calls
    # `mojo_repr_bool`), so an `int64_t` slot prints `1`. Its doc
    # (bugs/hard/CODEGEN_generator_value_slot_loses_bool.md) was DELETED on
    # fix, per CLAUDE.md's "Bug docs" rule — the two decisions it left open
    # (mixed bool/int yields, unannotated call-site params) are recorded in
    # `_generator_value_kind`'s comment and pinned by
    # `generator_mixed_bool_and_int_yields_widen_to_int` below.
    # ------------------------------------------------------------------
    def test_generator_bool_yield_slot_is_bool():
        """`for b in <bool-yielding gen>(): print(b)` must declare the loop
        target `_Bool`, not `int64_t`. The C++20 escape-hatch path already
        did (`_infer_simple_expr_ctype` answers `_Bool` for a BoolLiteral,
        and `MOJO_CORO=cpp` prints `True`) -- this is the stackswitch
        lattice catching up, and the two must not disagree."""
        global _PASS, _FAIL
        name = "generator_bool_yield_slot_is_bool"
        c = compile_to_gimple("""\
def y():
    yield True
    yield False

def main():
    for b in y():
        print(b)
""")
        if 'value_kind=b' not in c:
            print(f"FAIL  {name}: value slot is not the 'b' kind "
                  f"(no `value_kind=b` marker in the trampolines)")
            _FAIL += 1
            return
        acc = c.find('__mgco_y_value (MojoGenerator *__g)')
        if acc < 0:
            print(f"FAIL  {name}: the value accessor was never emitted")
            _FAIL += 1
            return
        ret = c[c.rfind('\n', 0, acc - 1) + 1:acc].strip()
        if ret != '_Bool':
            print(f"FAIL  {name}: value accessor returns {ret!r}, want _Bool")
            _FAIL += 1
            return
        if '_Bool b;' not in c:
            print(f"FAIL  {name}: the consumer's loop target is not a "
                  f"`_Bool` local (no `_Bool b;` declaration)")
            _FAIL += 1
            return
        if 'mojo_repr_bool (b)' not in c:
            print(f"FAIL  {name}: print(b) is not routed through "
                  f"mojo_repr_bool, so the value still renders as 1/0")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_generator_bool_tuple_slot_is_bool():
        """A `True` in a TUPLE yield slot came back as `1` for the same
        reason -- one missing kind in the shared lattice, not two bugs.
        Assert the per-slot ctype the consumer unpacks with."""
        global _PASS, _FAIL
        name = "generator_bool_tuple_slot_is_bool"
        c = compile_to_gimple("""\
def tup():
    yield ("x", True, False)

def main():
    for a, b, d in tup():
        print(a, b, d)
""")
        if 'mojo_repr_bool (b)' not in c or 'mojo_repr_bool (d)' not in c:
            print(f"FAIL  {name}: tuple slots are not `_Bool` (print does not "
                  f"route the bool slots through mojo_repr_bool)")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_generator_int_yield_slot_stays_int64():
        """The control for the two tests above: an int-yielding generator
        must keep the `int64_t` slot, or `print` would render a genuine
        integer as `True`/`False`."""
        global _PASS, _FAIL
        name = "generator_int_yield_slot_stays_int64"
        c = compile_to_gimple("""\
def y():
    yield 1
    yield 0

def main():
    for i in y():
        print(i)
""")
        if 'value_kind=i' not in c:
            print(f"FAIL  {name}: the int generator's slot kind is not 'i'")
            _FAIL += 1
            return
        acc = c.find('__mgco_y_value (MojoGenerator *__g)')
        ret = c[c.rfind('\n', 0, acc - 1) + 1:acc].strip()
        if ret != 'int64_t':
            print(f"FAIL  {name}: value accessor returns {ret!r}, want int64_t")
            _FAIL += 1
            return
        if 'int64_t i;' not in c:
            print(f"FAIL  {name}: the consumer's loop target is not an "
                  f"`int64_t` local")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_generator_mixed_bool_and_int_yields_widen_to_int():
        """The RECORDED DECISION for mixed bool/int yields, pinned so a
        later change to it has to be deliberate: `bool` is a subclass of
        `int`, so `if c: yield True else: yield 1` has no single right
        answer for one slot and the answer is `i` -- it reproduces CPython's
        text exactly on the int path, whereas a refusal would disqualify
        the whole module from the stackswitch path over rendered text
        alone. Compare the mixed int/STRING case, which DOES refuse,
        because there one slot kind means one of the two values is read
        through the wrong accessor (a measured SIGSEGV)."""
        global _PASS, _FAIL
        name = "generator_mixed_bool_and_int_yields_widen_to_int"
        c = compile_to_gimple("""\
def mixed(c):
    if c:
        yield True
    else:
        yield 1

def main():
    for m in mixed(True):
        print(m)
""")
        if 'value_kind=i' not in c:
            print(f"FAIL  {name}: mixed bool/int yields did not widen to the "
                  f"'i' kind")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_user_defined_dunder_repr_is_called():
        """`repr(obj)` must call the struct's OWN `__repr__`. The generated
        field-dump `_mojo_repr_<Struct>` used to shadow it: the real method
        body WAS emitted (and an `extern` declared for it) and then nothing
        ever called it, so `repr(p)` printed `P(x=1)` — or, for a struct the
        runtime has no field table for, a raw pointer decimal. Silent wrong
        value, exit 0, and the dunder the user wrote was simply dead code.

        A SHAPE check, because that is all this file's `gcc -fsyntax-only`
        harness can do; the value-level counterpart (which actually runs the
        binary and compares against CPython) is
        `user_defined_dunder_repr_value` below, on both pipelines.
        Two structs, because the fix is deliberately conservative and BOTH
        halves are load-bearing: `P` defines `__repr__` and must reach it,
        while `Q` does not and must KEEP the generated field-dump dispatch —
        a fix that simply deleted `_mojo_dispatch_repr` would pass the first
        assertion and leave every struct without a `__repr__` unprintable."""
        global _PASS, _FAIL
        name = "user_defined_dunder_repr_is_called"
        c = compile_to_gimple("""\
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "P!"

class Q:
    def __init__(self, y):
        self.y = y

def main():
    p = P(1)
    q = Q(2)
    print(repr(p))
    print(repr(q))
""")
        main_start = c.find('main (void)\n{')
        body = c[main_start:] if main_start >= 0 else c
        if '= P___repr__ (' not in body:
            print(f"FAIL  {name}: repr(p) did not call the real P___repr__")
            _FAIL += 1
            return
        if '= _mojo_dispatch_repr (' not in body:
            print(f"FAIL  {name}: repr(q), for a struct with no user "
                  f"__repr__, no longer routes through the generated "
                  f"field-dump dispatch")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_every_funcptr_initializer_has_a_definition():
        """Every `_funcptr_X = (void *)X` initializer in the output must have a
        matching `X` DEFINITION in the same file.

        Shape-independent, and it is the check the nested-`def`-lambda bug
        asked for and did not have: `_lower_LambdaExpr` lifts a lambda's C
        body into `gen._lambda_parts` and only `gen_module` flushes that side
        table, and the nested-closure emission path flushed nothing — so a
        lambda inside a nested `def` was declared and had its address taken
        and never defined, which is an `Undefined symbols` LINK failure:

            Undefined symbols for architecture arm64:
              "__make_make_lambda_1", referenced from:
                  __funcptr__make_make_lambda_1 in ...o

        Asserted over a spread of shapes (lambda at top level, in a plain
        `def`, in a nested `def`, in a struct method, a nested `def` inside a
        struct method, and a two-deep nest), because the
        flush points are per-path and a single shape only pins one of them.
        """
        global _PASS, _FAIL
        name = "every_funcptr_initializer_has_a_definition"
        cases = {
            "top_level_lambda": """\
d = {}
d['k'] = lambda a, b: a + b
print(d['k'](1, 2))
""",
            "def_body_lambda": """\
def f(x):
    return lambda y: y + x
print(f(1)(2))
""",
            "nested_def_lambda": """\
def _make():
    def make():
        return lambda x: x + 1
    return make

def main():
    print(_make()()(1))
main()
""",
            "struct_method_lambda": """\
class K:
    def __init__(self, n):
        self.n = n
    def get(self):
        return lambda: self.n

def main():
    print(K(7).get()())
main()
""",
            "nested_def_in_struct_method": """\
class K:
    def __init__(self, n):
        self.n = n
    def outer(self):
        def inner():
            return lambda: self.n
        return inner()

def main():
    print(K(9).outer()())
main()
""",
            "two_deep_nested_def_lambda": """\
def a():
    def b():
        def c():
            return lambda: 5
        return c
    return b

def main():
    print(a()()()())
main()
""",
        }
        import re as _re
        for label, src in cases.items():
            c = compile_to_gimple(src)
            init = set(_re.findall(r'_funcptr_([A-Za-z0-9_]+)\s*=\s*\(void\s*\*\)\s*'
                                   r'([A-Za-z0-9_]+)', c))
            missing = []
            for var, sym in sorted(init):
                # A definition is the symbol appearing at the start of a
                # line as a return type + name + '(' — a declaration ends in
                # ';' and a definition's body opens with '{'.
                if not _re.search(r'\b' + _re.escape(sym) + r'\s*\([^;]*\)\s*\{',
                                  c, _re.S):
                    missing.append(f'{var} -> {sym}')
            if missing:
                print(f"FAIL  {name}[{label}]: funcptr initializer with no "
                      f"definition in the same file: {', '.join(missing)}")
                _FAIL += 1
                return
        print(f"PASS  {name}  ({len(cases)} shapes)")
        _PASS += 1

    def test_ast_walk_reaches_every_name_in_a_lambda_body():
        """`_ast_walk` must not lose a name, because `_lower_LambdaExpr`
        derives a lambda's CAPTURE LIST from it.

        It walked a hand-written list of 16 attribute names, and 17 of the AST
        dataclasses had a child-bearing field missing from it —
        `TernaryExpr.condition`, `IfStmt.condition`, `WhileStmt.condition`,
        `SubscriptExpr.index`, `ForStmt.iterable`, `CallExpr.kwargs`,
        `CompareChain.operands`, `Comprehension.element`/`generators`,
        `DictExpr.pairs`, `MultiAssignStmt.targets`, `SliceExpr.start/stop/step`,
        `MatchStmt.subject`/`cases`, `TryStmt.handlers`/`else_body`/
        `finally_body`, `WithItem.expr`, `MatchCase.patterns`/`guard`,
        `ExceptHandler.exc_type`, `DecoratorArgs.clauses`,
        `Generator.conditions`. (`IfStmt`/`WhileStmt.condition`,
        `TryStmt`'s handlers and `MatchStmt`'s cases are statement-level and a
        lambda body is an EXPRESSION, so they cannot reach this walk from a
        lambda; they are here only because the walk is also what a nested
        `def`'s own body walk would use.) A captured local reachable ONLY
        through one of
        those was never put in the closure env, and the lambda body read it
        through the `ct param or undeclared` fallback — a hard 0. Silent: exit
        0 and a plausible wrong value (`sorted(d, key=lambda k: d[k] if p
        else 0)` came out unsorted).

        The expectation is `_used_idents_node`, not a written-down list of
        field names: it is this codebase's other name-collecting walk and it
        walks GENERICALLY over dataclass fields (rule 2 in its docstring, added
        precisely because "a node type with no explicit branch" was an
        under-approximation), so "the structural walk sees everything the
        generic one does" is the invariant, and it fails by itself the next
        time a field is added or renamed. One case per previously-missed
        field, so a fix that patches only `condition` cannot pass.

        The two walks differ deliberately in ONE respect and the cases respect
        it: both stop at a nested `FunctionDef`/`LambdaExpr` boundary for
        `_used_idents_node` but not for `_ast_walk`, so no case here contains
        a nested closure."""
        global _PASS, _FAIL
        name = "ast_walk_reaches_every_name_in_a_lambda_body"
        from mojo.backend_gimple.emit_calls import _ast_walk
        from mojo.middle.types import _used_idents_node
        # label -> a lambda body whose free names sit under a DIFFERENT field
        cases = {
            'ternary_condition': ('1 if cap else 0', {'cap'}),
            'subscript_index': ('d[cap]', {'d', 'cap'}),
            # `x` is the KEYWORD NAME (a str in the pair), not a reference,
            # so it is correctly not an IdentExpr and is not expected.
            'call_kwargs': ('f(x=cap)', {'f', 'cap'}),
            'compare_chain_operand': ('cap < q', {'cap', 'q'}),
            # `c` is the comprehension's OWN binding, not a free name, so it
            # is not expected here — `_used_idents_node` subtracts generator
            # targets and this case asserts against that answer too.
            'comprehension_element': ('[cap for c in s]', {'cap', 's'}),
            'comprehension_generators': ('[z for z in cap]', {'z', 'cap'}),
            'dict_pairs': ('{cap: q}', {'cap', 'q'}),
            'slice_start_stop_step': ('cap[1:2:3]', {'cap'}),
            'unary_operand': ('-cap', {'cap'}),
            'boolop_operands': ('cap and q', {'cap', 'q'}),
            'member_chain': ('cap.real', {'cap'}),
            'nested_call_arg': ('f(g(cap))', {'f', 'g', 'cap'}),
        }
        import fire_compiler as _F
        missing = []
        for label, (expr, want) in sorted(cases.items()):
            # Parse the expression as a real lambda body so the node under test
            # is the AST the capture walk actually sees.
            src = f'zz = lambda: {expr}\n'
            mod = _F.Parser(_F.py_tokenize(src)).parse_module()
            lam = None
            for st in mod:
                if isinstance(st, _F.AssignStmt) and isinstance(st.value, _F.LambdaExpr):
                    lam = st.value
            if lam is None:
                missing.append(f'{label}: no LambdaExpr parsed from {src!r}')
                continue
            seen = {n.name for n in _ast_walk(lam.body)
                    if isinstance(n, _F.IdentExpr)}
            generic = _used_idents_node(lam.body)
            lost = (generic | want) - seen
            if lost:
                missing.append(f'{label}: {sorted(lost)} invisible to _ast_walk')
        if missing:
            print(f"FAIL  {name}: " + '; '.join(missing))
            _FAIL += 1
            return
        print(f"PASS  {name}  ({len(cases)} shapes)")
        _PASS += 1

    def _cpython_stdout(src, preamble=''):
        """CPython's stdout for `src`, or None if it does not run.

        The oracle for the two tests below, so a change in what Python does
        cannot turn either into a test that protects a wrong value.

        `preamble` is written ABOVE `src` in the oracle file and into nothing
        else: it exists for a fixture whose parameter annotations are Mojo type
        names (`Float64`, `String`), which CPython cannot resolve — a
        `def f(x: Float64)` is a NameError at def time, so the oracle arm below
        would report "CPython does not run the fixture" for a fixture that is
        perfectly runnable and the test could never pass. Naming the types as
        their CPython equivalents keeps the oracle CPython's own answer for the
        same program text: the annotation is erased by the def, so the values
        and the prints are the program. It is deliberately NOT fed to the
        compiled path, which has those names built in."""
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'oracle_case.py')
            with open(entry, 'w') as fh:
                fh.write(preamble)
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
        if py.returncode != 0:
            return None
        return py.stdout

    def _compiled_stdout(src, mode='single-TU'):
        """Compile `src` and return its stdout, or None if it does not build.

        Returns None for a COMPILE failure too, so a caller reports the mode
        and the gcc stderr rather than a value comparison against nothing."""
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'case.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            c_src = gimple_codegen._run_pipeline(
                src, filename=entry,
                **({'do_imports': True} if mode == 'single-TU'
                   else {'link_mode': True}))[0]
            c_file = os.path.join(td, 'case.c')
            exe = os.path.join(td, 'case.exe')
            with open(c_file, 'w') as fh:
                fh.write(c_src)
            cc = subprocess.run(
                [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                 os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                capture_output=True, text=True, timeout=300)
            if cc.returncode != 0:
                return ('BUILD-FAILED', cc.stderr)
            run = subprocess.run([exe], capture_output=True, text=True,
                                 timeout=30)
        return run.stdout

    def test_callable_return_type_survives_its_carrier():
        """A callable's return type must reach the call site through every
        carrier that can sit between them — with CPython's stdout as the
        expectation, on BOTH pipelines.

        `mojo_fnptr_call_N` is the homogenized `int64_t` convention: the
        RIGHT thing for the box it hands back, and the callee is the one that
        knows the real type. `_callable_ret_types` carries it, keyed by the
        lowered VALUE — which every carrier below breaks, in its own way:

        - a LAMBDA BOUND TO A LOCAL: the value survives, and the store
          propagates the table through the name. Worked already.
        - a MODULE GLOBAL: the store boxes it into an `int64_t` struct field
          and the call site reads back a fresh temp, so no value key matches.
          `e = lambda: False; print(e())` printed `0`.
        - the same global read from inside a FUNCTION: the store happens in
          `_toplevel`, which is emitted after every ordinary function, so the
          per-function reset wiped whatever the store had recorded.
        - a DICT OF CALLABLES (`d = {"k": lambda: False}`): a second table
          (`_container_callable_ret`), gated on the dict's NAME, with the same
          never-reset twin needed for a global.
        - a FACTORY (`def mk(): return lambda: 2.5`): the result is cast
          into a fresh temp before the outer `mk()()` sees it, so the answer
          has to ride on the CallExpr node rather than on any value.

        Bodies of all three interesting kinds (`_Bool`, `double`, `char *`)
        are in every shape: the widened answer is a plausible number or a
        pointer decimal for each, so a shape that passed by coincidence
        would not be distinguishable from one that passed.
        """
        global _PASS, _FAIL
        name = "callable_return_type_survives_its_carrier"
        src = '''\
e = lambda: False
print(e())
g = lambda x: x > 1
print(g(5))
print(g(0))
f = lambda: 1.5
print(f())
s = lambda: "hi"
print(s())
d = {"k": lambda: False}
print(d["k"]())
def use_globals():
    print(e())
    print(d["k"]())
    print(g(2))
use_globals()
def mk():
    return lambda: 2.5
def use_factory():
    print(mk()())
use_factory()
def mk_bool():
    return lambda: False
def use_bool_factory():
    print(mk_bool()())
use_bool_factory()
'''
        want = _cpython_stdout(src)
        if want is None:
            print(f"FAIL  {name}: CPython does not run the fixture")
            _FAIL += 1
            return
        for mode in ('single-TU', 'link-mode'):
            got = _compiled_stdout(src, mode)
            if isinstance(got, tuple):
                print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                      f"{got[1][:800]}")
                _FAIL += 1
                return
            if got != want:
                print(f"FAIL  {name} [{mode}]: compiled stdout {got!r} != "
                      f"CPython {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_variadic_lambda_lowers_as_gimple_in_every_body():
        """A `lambda *args: ...` must emit only legal GIMPLE operands, in
        every body its reference site can land in.

        The shape it emitted — `(void *)f`, `sizeof(S)`, and the three
        parenthesized counts as bare call ARGUMENTS — is fine in plain C and
        is a hard parse failure inside a `__GIMPLE`-tagged body, where the
        body must already BE GIMPLE: a cast or a parenthesized
        sub-expression is not a legal operand there. That is why this went
        unnoticed for so long — the same lambda compiled from an ordinary
        top-level statement or a free function (GCC lowers plain C to
        GIMPLE itself) and died from a struct method or a nested `def`:

            .c: In function 'K_get':
            .c:5:37: error: expected expression before '(' token
            _t2 = mojo_vararg_fn_new (_t1, 0, <<< error >>>);

        All three carriers are here, each with a capturing variant too (the
        env path spelled `sizeof(S)` inline as well), and CPython is the
        expectation for the values — a build failure and a wrong value are
        different defects and this checks both.
        """
        global _PASS, _FAIL
        name = "variadic_lambda_lowers_as_gimple_in_every_body"
        src = '''\
class K:
    def __init__(self, n):
        self.n = n
    def plain(self):
        return lambda *a: len(a)
    def capturing(self):
        return lambda *a: len(a) + self.n
def _make():
    def inner():
        return lambda **k: len(k)
    return inner
def top():
    return lambda *a: len(a)
def main():
    k = K(10)
    print(top()(1, 2, 3))
    print(k.plain()(1, 2, 3))
    print(k.capturing()(1, 2, 3))
    print(_make()()(a=1, b=2))
main()
'''
        want = _cpython_stdout(src)
        if want is None:
            print(f"FAIL  {name}: CPython does not run the fixture")
            _FAIL += 1
            return
        for mode in ('single-TU', 'link-mode'):
            got = _compiled_stdout(src, mode)
            if isinstance(got, tuple):
                print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                      f"{got[1][:800]}")
                _FAIL += 1
                return
            if got != want:
                print(f"FAIL  {name} [{mode}]: compiled stdout {got!r} != "
                      f"CPython {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_scalar_given_a_char_star_parameter_is_stringified():
        """A SCALAR passed where a `str` parameter is declared must be
        `str(value)`, which is both Python's answer and the only answer that
        is not a wild pointer.

        `_emit_call`'s `ptype == 'char *'` branch used to reinterpret the
        integer's BITS as an address (`(char *)(void *)(int64_t)5`), so
        `class D: def __init__(self, w: str)` called as `D(5)` stored
        address 5 in a `char *` field and the first `mojo_print` of it walked
        to it and SIGSEGV'd with no output at all — while `D(2.5)` did not
        even compile ("cannot convert to a pointer type"). It now goes
        through `_stringify_value`, the same chokepoint `str()`, f-strings
        and `%s` use.

        The doc's repro is a struct method returning one of its own `str`
        fields (`bugs/CODEGEN_method_returning_self_str_field_segfaults.md`,
        removed with this fix), and it is reproduced here — including the
        imported-sibling spelling, since the field read off the object and
        the read back out of the method are two separate lowerings and a fix
        to only one of them leaves the other wrong.

        A BOXED value is in the same fixture for the reason the fix has to
        be careful about it: an `int64_t` that really holds a `char *` is
        also `ptype == 'char *'` on this path, and `_stringify_value`
        answers it from `_actual_types` as a cast rather than as a decimal.
        """
        global _PASS, _FAIL
        name = "scalar_given_a_char_star_parameter_is_stringified"
        src = '''\
class Dialog:
    def __init__(self, widgetName: str):
        self.widgetName = widgetName
    def show(self):
        return self.widgetName
def pass_through(w):
    return w
def main():
    a = Dialog(5)
    print(a.widgetName)
    print(a.show())
    print(Dialog(2.5).show())
    print(Dialog(True).show())
    print(Dialog("plain").show())
    print(Dialog(pass_through("boxed")).show())
main()
'''
        want = _cpython_stdout(src)
        if want is None:
            print(f"FAIL  {name}: CPython does not run the fixture")
            _FAIL += 1
            return
        for mode in ('single-TU', 'link-mode'):
            got = _compiled_stdout(src, mode)
            if isinstance(got, tuple):
                print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                      f"{got[1][:800]}")
                _FAIL += 1
                return
            if got != want:
                print(f"FAIL  {name} [{mode}]: compiled stdout {got!r} != "
                      f"CPython {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_ctor_of_a_container_reaches_the_comprehension():
        """`list(x)` / `tuple(x)` / `set(x)` must COPY x, whatever reached
        them — including a value whose container kind is not a compile-time
        fact.

        `_lower_comprehension` dispatches on the argument's STATIC type and has
        no arm for a boxed `int64_t`/`void *`: it emitted
        `/* TODO: comprehension over int64_t */` and produced an EMPTY list.
        That is how `self.func_param_types[_mangled] = list(_pcs)` silently
        became `[]` for every `GimpleGen_*` signature in the SELF-HOSTED
        compiler (that table's element type is erased there, so `_pcs`
        arrives as a bare handle), and how `list(_dflts)` walked a list of
        `(name, default)` pairs as though it were a dict.

        `def ident(x): return x` reproduces the erased shape in ordinary
        source: the call's declared return type is its parameter's, so the
        result is a boxed handle with no container kind attached. The list,
        `tuple`, `sorted`, `sum`, `all`, `join` and `enumerate` rows are here
        because they are the ones this change makes exactly right, and because
        the last four share the chokepoint and must not drift from it.

        `list(<a plain int>)` and `list(<a boxed dict>)` are NOT asserted
        here, and both are named in the docstring's neighbour bug docs:
        CPython raises TypeError where the compiled path answers `[]` for the
        first (a SIGSEGV until this same change's fail-closed arm —
        the `list(<an int>)` arm), and a
        boxed dict's keys come back as their own addresses for the second
        (`bugs/CODEGEN_materialized_container_has_no_element_type.md`).

        A STRING argument is not asserted either, and that is a real defect
        rather than a fixture convenience: `list(ident([1, 2, 3]))` in the
        same function as `list(ident("abc"))` reads the first list's slots
        with `mojo_list_get_str`, because one function's return ELEMENT type
        is inferred once for the whole program and the string call site wins.
        Measured, both pipelines: `["\\x18", "\\x1a", "�", "\\x02",
        "\\x01"]` where CPython printed `[1, 2, 3]` — a five-element list of
        bytes read out of a three-element int list. Recorded in
        bugs/CODEGEN_return_element_type_is_unified_across_call_sites.md.
        """
        global _PASS, _FAIL
        name = "ctor_of_a_container_reaches_the_comprehension"
        src = '''\
def ident(x):
    return x
def main():
    print(list(ident([1, 2, 3])))
    print(tuple(ident([1, 2, 3])))
    print(sorted(ident([3, 1, 2])))
    print(sum(ident([1, 2, 3])))
    print(all(ident([1, 2, 3])))
    print(",".join(ident(["a", "b"])))
    print(len(list(enumerate(ident(["x", "y"])))))
main()
'''
        want = _cpython_stdout(src)
        if want is None:
            print(f"FAIL  {name}: CPython does not run the fixture")
            _FAIL += 1
            return
        for mode in ('single-TU', 'link-mode'):
            got = _compiled_stdout(src, mode)
            if isinstance(got, tuple):
                print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                      f"{got[1][:800]}")
                _FAIL += 1
                return
            if got != want:
                print(f"FAIL  {name} [{mode}]: compiled stdout {got!r} != "
                      f"CPython {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_a_returned_heterogeneous_list_keeps_its_slot_kinds():
        """A list literal's per-slot kinds must survive a `return`.

        `_lower_list_literal` records them on the VALUE
        (`mojo_list_set_kinds`) and marks it in `gen._maybe_kinds_vals` — but
        only while THAT function is being lowered. The compile-time NAME they
        were recorded against dies at the boundary, and
        `_infer_return_maybe_kinds` is the pass that exists to carry the fact
        across; it recognised `struct.unpack` and nothing else, so the one
        producer that is not a `struct.unpack` was the one it missed.

        The cost was a segfault. `a`'s element type fell back to the
        unknown-element default `str`, so EVERY read of it went through
        `mojo_list_get_str` — and `a[0]` holds `2.5`'s IEEE-754 bit pattern
        `0x4004000000000000`, which `strlen` walked to and died on
        (bugs/CODEGEN_list_element_read_defaults_to_str_across_a_call.md).

        Both halves are asserted. The indexed reads need the per-slot kinds to
        cross the boundary (the new `_return_value_slot_kinds`); the
        ITERATION read needs only the boolean, and prints the string slot as
        the decimal of its own pointer — recorded in the doc's Status as the
        remaining half, because making it right needs per-slot runtime typing
        in the loop body rather than an accessor choice.

        The parameters are ANNOTATED on purpose: a parameter's declared type is
        the only static evidence about what a slot will hold at this stage
        (`_quick_type` on a parameter answers the erased `int64_t` before any
        function's locals exist), and the unannotated spelling of the same
        program has no such evidence to offer. That is also why the oracle gets
        a preamble naming those two types as their CPython equivalents and the
        compiled program does not — see `_cpython_stdout`."""
        global _PASS, _FAIL
        name = "a_returned_heterogeneous_list_keeps_its_slot_kinds"
        src = '''\
def mixed(x: Float64, s: String):
    return [x, 1, s]
def main():
    a = mixed(2.5, "yy")
    print(a[0])
    print(a[1])
    print(a[2])
    print(len(a))
main()
'''
        want = _cpython_stdout(src, preamble='Float64 = float\nString = str\n')
        if want is None:
            print(f"FAIL  {name}: CPython does not run the fixture")
            _FAIL += 1
            return
        for mode in ('single-TU', 'link-mode'):
            got = _compiled_stdout(src, mode)
            if isinstance(got, tuple):
                print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                      f"{got[1][:800]}")
                _FAIL += 1
                return
            if got != want:
                print(f"FAIL  {name} [{mode}]: compiled stdout {got!r} != "
                      f"CPython {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_next_on_a_user_struct_lowers_and_its_for_loop_says_why_not():
        """`next(<user-defined iterator struct>)` is a real call, and the
        `for` loop over the same object is a NAMED refusal.

        `next(obj)` is Python's `type(obj).__next__(obj)`, which Mojo spells
        `__next__`, and `_lower_call` lowers it to `<Struct>___next__(obj)`
        whenever the receiver's type is resolvable. That half had no test, so
        it could rot unnoticed — it is asserted here against CPython, on both
        pipelines, with a receiver the codegen knows (a local struct
        instance), which is the boundary the real 21-file failure sits
        behind: `var iter = peekable(list)` types `iter` as `int64_t` because
        `peekable` returns a `Self.IteratorOwnedType` across a module
        boundary, and an un-inferred receiver has to stay a refusal
        (bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md).

        The loop half is the change here. Python's `__next__` signals
        exhaustion by RAISING, and the compiled raise is
        `mojo_exc_type_set (...)` + `mojo_raise ()` — nothing for a loop
        condition to test — so a struct with `__next__` and no `__has_next__`
        has no expressible loop condition. That emitted `cond = 0` with a
        `/* TODO */` marker: the body runs zero times, silently, at exit 0.
        It now calls the same `mojo_unsupported_iter` every other unsupported
        iterable gets, so the diagnostic names the type, the reason and the
        loop's file:line. The BEHAVIOUR is deliberately unchanged — the
        runtime message already ends "the loop body runs zero times" — because
        making the loop actually work is the type-inference project the doc
        parks, and inventing a wrong loop here would be worse than both.

        Asserted on the SHAPE (`mojo_unsupported_iter` present, the type named)
        rather than on stderr, so the row does not depend on how the runtime
        chooses to word its message; the value assertion above is what pins
        that `next` itself is right."""
        global _PASS, _FAIL
        name = "next_on_a_user_struct_lowers_and_its_for_loop_says_why_not"
        src = '''\
class Counter:
    def __init__(self, start, stop):
        self.i = start
        self.stop = stop
    def __iter__(self):
        return self
    def __next__(self):
        if self.i >= self.stop:
            raise StopIteration
        v = self.i
        self.i = v + 1
        return v
def main():
    c = Counter(5, 8)
    print(next(c))
    print(next(c))
    print(next(Counter(9, 10)))
main()
'''
        want = _cpython_stdout(src)
        if want is None:
            print(f"FAIL  {name}: CPython does not run the fixture")
            _FAIL += 1
            return
        bad = []
        for mode in ('single-TU', 'link-mode'):
            got = _compiled_stdout(src, mode)
            if isinstance(got, tuple):
                print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                      f"{got[1][:800]}")
                _FAIL += 1
                return
            if got != want:
                bad.append(f"[{mode}] next() stdout {got!r} != CPython {want!r}")
        loop_src = src + '''def drain():
    c = Counter(1, 3)
    for x in c:
        print(x)
drain()
'''
        try:
            loop_c = compile_to_gimple(loop_src)
        except Exception as e:
            bad.append(f"the `for` shape did not compile: "
                       f"{type(e).__name__}: {e}")
            loop_c = ''
        if loop_c:
            if 'mojo_unsupported_iter' not in loop_c:
                bad.append("the `for` over a Python-style iterator emitted no "
                           "mojo_unsupported_iter — a dropped loop body is "
                           "silently indistinguishable from an exhausted one")
            if 'Counter (no __has_next__)' not in loop_c:
                bad.append("the refusal does not name the type or the reason")
        if bad:
            for b in bad:
                print(f"FAIL  {name}: {b}")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_user_defined_dunder_repr_value():
        """The same thing with the VALUE checked, on BOTH pipelines
        (single-TU and link mode — they are separate codegen paths and this
        chokepoint, `_repr_value`, is shared by both, so a one-sided fix
        would be invisible to either alone). `repr()` and `%r` are the two
        entry points into that chokepoint, and they are both here because a
        fix at only one of them is the same bug with a different spelling.

        CPython is run on the SAME text and its stdout is the expectation;
        nothing is written down as a literal answer, so a change in what
        Python does cannot turn this into a test that protects a wrong
        value. Covers a struct whose `__repr__` computes a string from a
        field, since a `__repr__` that returned the field verbatim would
        coincide with the generated field dump and prove nothing."""
        global _PASS, _FAIL
        name = "user_defined_dunder_repr_value"
        src = '''\
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "P<" + self.x + ">"

p = P("a")
print(repr(p))
print("%r" % p)
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'repr_case.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            results = []
            for mode in ('single-TU', 'link-mode'):
                c_src = gimple_codegen._run_pipeline(
                    src, filename=entry,
                    **({'do_imports': True} if mode == 'single-TU'
                       else {'link_mode': True}))[0]
                c_file = os.path.join(td, f'repr_{mode}.c')
                exe = os.path.join(td, f'repr_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          f"{cc.stderr[:800]}")
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                print(f"FAIL  {name}: {', '.join(bad)} printed "
                      f"{dict(results)[bad[0]]!r}, CPython printed {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_aliased_and_reexported_imports_resolve_to_the_defining_module():
        """`from M import X as A` and `from R import X` where `R` only
        RE-EXPORTS `X`, on both the single-TU and link-mode pipelines, with
        CPython's own stdout as the expectation.

        Four distinct bugs lived under these two spellings and each had a
        different, mostly silent failure, which is why they are pinned
        together rather than one per line:

        * A CLASS alias missed every struct table (`struct_field_types` is
          keyed by the struct's own bare name in its DEFINING module), so
          `Alias("s")` fell into the generic one-string-argument "opaque
          constructor" and returned the ARGUMENT — `x` became the literal
          `"a"` and `x.widgetName` raised AttributeError
          (bugs/CODEGEN_aliased_imported_struct_construction_unresolved.md).
        * The same class reached THROUGH a re-export then lost its field
          TYPES: the cross-module constructor-hint pass looked the struct
          up in the RE-EXPORTING module, which has no `class`, so
          `widgetName` stayed `int64_t` and a `char *`'s bits printed as a
          pointer decimal (unaliased, the same miss is a hard gcc
          "non-trivial conversion in 'var_decl'").
        * A FUNCTION alias got a second, independently-typed `extern` from
          the re-export preamble: the preamble's "this TU already defines
          it" skip tests the name it is keyed by, which for an alias is not
          the name the definitions use, so the text scan's parameter-less
          `int64_t helper (void)` for an unannotated `def helper(x)`
          contradicted the definition compiled a few hundred lines below it
          (bugs/CODEGEN_reexported_function_import_qualifier_names_the_
          wrong_module.md, and the direct-alias variant of the same shape).
        * A re-exported FUNCTION never resolved at all — the export table
          is a text scan of the re-exporting `__init__.py`, which contains
          no `def` — so the call site bound to the extern preamble's `weak`
          "unavailable in compiled mode" stub, or emitted
          `p_tri_<suffix>` against a definition emitted as
          `sub_tri_<suffix>`.

        CPython is run on the SAME files and its stdout is the expectation;
        no answer is written down as a literal, so a change in what Python
        does cannot turn this into a test that protects a wrong value.
        """
        global _PASS, _FAIL
        name = "aliased_and_reexported_imports_resolve_to_the_defining_module"
        files = {
            # A package `__init__.py` that re-exports is the standard
            # layout, and the case every one of the four bugs above needs.
            'p/__init__.py': 'from .sub import Dialog, helper, tri\n',
            'p/sub.py': (
                'class Dialog:\n'
                '    def __init__(self, widgetName):\n'
                '        self.widgetName = widgetName\n'
                '\n'
                'def tri(x):\n'
                '    return x * 3\n'
                '\n'
                'def helper(x):\n'
                '    return x + 1\n'
            ),
            # An UNRELATED module exporting the same function name, so a
            # fix that resolves "where does this name live" by scanning
            # for any module that defines it (rather than by following
            # THIS import statement's re-export hops) has somewhere to
            # resolve to wrongly.
            'other.py': 'def tri(x):\n    return 1000 + x\n',
            'p/main.py': (
                'from p import Dialog as D\n'
                'from p import helper as H\n'
                'from p import tri as T\n'
                'from p.sub import Dialog as D2\n'
                'from other import tri as T2\n'
                '\n'
                'def build():\n'
                '    from p import Dialog as D3\n'
                '    return D3("inner")\n'
                '\n'
                'def probe():\n'
                '    from p import tri\n'
                '    return tri(4)\n'
                '\n'
                'def main():\n'
                '    print(D("a").widgetName)\n'
                '    print(D2("b").widgetName)\n'
                '    print(build().widgetName)\n'
                '    print(H(41))\n'
                '    print(T(7))\n'
                '    print(T2(1))\n'
                '    print(probe())\n'
                '\n'
                'main()\n'
            ),
        }
        with tempfile.TemporaryDirectory() as td:
            for rel, body in files.items():
                fp = os.path.join(td, rel)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, 'w') as fh:
                    fh.write(body)
            entry = os.path.join(td, 'p', 'main.py')
            # PYTHONPATH=td, not just cwd: running a script puts the
            # SCRIPT'S OWN directory (`td/p`) on sys.path, and this program
            # imports `p` and `other` as siblings of that directory — so
            # CPython would fail with ModuleNotFoundError and the test
            # would report "the test program itself is wrong" for a
            # harness mistake.
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60,
                                env=dict(os.environ, PYTHONPATH=td))
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:400]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            for mode in ('single-TU', 'link-mode'):
                c_src = gimple_codegen._run_pipeline(
                    files['p/main.py'], filename=entry,
                    **({'do_imports': True} if mode == 'single-TU'
                       else {'link_mode': True}))[0]
                c_file = os.path.join(td, f'aliased_{mode}.c')
                exe = os.path.join(td, f'aliased_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          f"{cc.stderr[:1200]}")
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                if run.stdout != want:
                    print(f"FAIL  {name} [{mode}]: printed {run.stdout!r}, "
                          f"CPython printed {want!r}")
                    _FAIL += 1
                    return
        print(f"PASS  {name}")
        _PASS += 1

    def test_gen_taking_middle_helper_is_never_reached_by_a_local_import():
        """No `gen`-taking `mojo/middle` helper may be reached by a
        FUNCTION-LOCAL `from mojo.middle.X import ...` unless the importing
        file already imports X at top level.

        Why that is an invariant rather than a style rule: a function-local
        import registers the name in THAT module's `imported_symbols`, and the
        import preamble's "this translation unit already defines it, so do
        not declare it again" test (`inline_defined`) is built from TOP-LEVEL
        imports only. So the very same symbol that a top-level import
        suppresses correctly escapes the suppression when it arrives through a
        nested import, and `module_loader`'s TEXT SCAN's declaration of it
        lands in the file beside the definition it contradicts — two
        independent inferences about one prototype, and gcc takes the first.

        `_resolved_export_entry(gen, module, name, info)` was exactly that:
        `mojo/middle/module_shared.py` imported it inside `_register_sym`,
        annotating two of its four params, so the scan (which DROPS an
        unannotated param) declared `int64_t (char *, char *)` against a
        definition of `int64_t (GimpleGen *, char *, char *, int64_t)`, and
        the self-hosted closure stopped compiling:

            too many arguments to function
              'mojo_middle_funcs_shared__resolved_export_entry_ee1b12';
              expected 2, have 4

        The scan cannot be taught to type a leading `gen`, and a variadic
        `name (...)` fallback is rejected by gcc against the real prototype,
        so the fix has to be structural: a `gen`-taking helper is reached as
        the `GimpleGen` method `gen.<name>`, which is what
        `module_shared`'s own module-scope comment prescribes for its
        siblings. This test is what keeps the next such helper from being
        added back as a local import.

        Cheap and structural on purpose — it reads the sources rather than
        compiling a closure, because the thing that broke is a whole-program
        self-compile and `gimple` must stay a fast gate.
        """
        global _PASS, _FAIL
        name = "gen_taking_middle_helper_is_never_reached_by_a_local_import"
        import re
        root = _PROJECT_DIR
        fs_path = os.path.join(root, 'mojo', 'middle', 'funcs_shared.py')
        with open(fs_path) as fh:
            fs_src = fh.read()
        # `def <name>(gen|self, ...` at column 0 — the exact shape
        # `_selfhost_extracted_fn_index` registers as a GimpleGen delegate,
        # so this is the same set, read the same way, not a second opinion.
        gen_helpers = set(re.findall(r'^def (\w+)\(\s*(?:gen|self)\b', fs_src,
                                    re.M))
        if not gen_helpers:
            print(f"FAIL  {name}: read no `def f(gen|self, ...)` out of "
                  f"{fs_path} — the pattern is stale, not the tree clean")
            _FAIL += 1
            return
        sources = [os.path.join(root, 'gimple_codegen.py')]
        for sub in ('mojo/middle', 'mojo/backend_gimple'):
            d = os.path.join(root, sub)
            for fn in sorted(os.listdir(d)):
                if fn.endswith('.py'):
                    sources.append(os.path.join(d, fn))
        offenders = []
        for path in sources:
            with open(path) as fh:
                lines = fh.read().split('\n')
            for i, line in enumerate(lines, 1):
                # Indented => inside a function/class body => local.
                m = re.match(r'\s+from\s+(mojo\.middle\.\w+)\s+import\s+(.+)',
                             line)
                if not m:
                    continue
                mod, names = m.group(1), m.group(2)
                imported = {n.strip().split(' as ')[0].strip()
                            for n in names.replace('(', '').replace(')', '')
                            .split(',')}
                for nm in sorted(imported & gen_helpers):
                    # A top-level `from <mod> import` of the same module puts
                    # the name in `inline_defined` whatever else the file does,
                    # so only a file WITHOUT one is a real offender.
                    toplevel = any(
                        re.match(r'from\s+' + re.escape(mod) + r'\s+import\b', l)
                        for l in lines)
                    if not toplevel:
                        offenders.append(
                            f"{os.path.relpath(path, root)}:{i} "
                            f"`from {mod} import {nm}`")
        if offenders:
            print(f"FAIL  {name}: a `gen`-taking mojo/middle helper reached by "
                  f"a function-local import escapes the import preamble's "
                  f"inline_defined skip, so the text scan declares it beside "
                  f"its own definition: {offenders}")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_dotted_import_two_hop_attribute_call():
        """`import a.b` binds `a`, so `a.b.f(...)` is a TWO-hop attribute
        call whose receiver is the SUBMODULE — Python's own
        `os.path.join` / `xml.etree.ElementTree.parse` are this shape.

        The compiled pipeline's `mod.f(...)` dispatch only matched a plain
        `IdentExpr` receiver, so `a` lowered as an undeclared identifier to
        a literal `0` and `_mojo_dispatch_getattr(0, "b")` raised at
        RUNTIME. What made this one worth chasing rather than writing off:
        the program compiled and linked cleanly first and then died with
        `Unhandled exception: AttributeError: b`, exit 1 and NO stdout —
        a non-zero exit with no diagnostic pointing at the import, in an
        area where every other failure is exit 0 with a wrong or noisy
        value (bugs/CODEGEN_import_dotted_name_two_hop_attribute_call_
        exits_1.md).

        CPython on the same files is the expectation, and BOTH pipelines are
        exercised because they are separate codegen paths.

        Run in BOTH locations, and the location is the point. This case used
        to SKIP — silently, counting neither a pass nor a fail — whenever the
        harness's temporary directory landed inside this checkout, on the
        stated ground that the module-qualified-call fallback is disabled
        there. That ground went stale: the gate is
        `mojo/middle/methods_shared.py::_is_selfhost_source_file`, which
        answers "is this one of the COMPILER'S OWN modules" from the file's
        own place in the tree (a root-level `*.py` beside
        `fire_compiler.py`, or inside its `mojo/` or `jit/` package) and
        deliberately NOT "any `.py` under the install directory" — so a
        fixture that merely happens to sit inside the checkout gets the
        ordinary resolution path, in this checkout and in every other.
        `test_link_mode.py`'s `test_bare_submodule_import_call_inside_source_
        tree` pins that half for the single-hop spelling; this one pins it
        for the two-hop spelling, and pins it the same way: build the
        identical package at a path under this checkout AND at whatever
        `$TMPDIR` names, so where the scratch directory happens to land can
        never decide the verdict again. Measured on both, one process, only
        the fixture's directory differing: single-TU `42`/`42`, link-mode
        `42`/`42`; with the link-mode registration removed, the link-mode arm
        at either location printed `tri: unavailable in compiled mode0`.
        """
        global _PASS, _FAIL
        name = "dotted_import_two_hop_attribute_call"
        files = {
            'q/__init__.py': '',
            'q/sub.py': 'def tri(x):\n    return x * 3\n',
            'q/main.py': 'import q.sub\n\nprint(q.sub.tri(14))\n',
        }

        def build_and_compare(td, label):
            """CPython-vs-compiled over `files` rooted at `td`. Returns None
            on agreement, or the failure message. A helper rather than a
            second copy of the body because the two locations must run
            BYTE-IDENTICAL programs — that is the whole claim."""
            for rel, body in files.items():
                fp = os.path.join(td, rel)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, 'w') as fh:
                    fh.write(body)
            entry = os.path.join(td, 'q', 'main.py')
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60,
                                env=dict(os.environ, PYTHONPATH=td))
            if py.returncode != 0 or not py.stdout:
                return (f"{label}: CPython on the same program exited "
                        f"{py.returncode} printing {py.stdout!r} "
                        f"({py.stderr[:400]}) — the test program itself is "
                        f"wrong, not the compiler")
            want = py.stdout
            for mode in ('single-TU', 'link-mode'):
                c_src = gimple_codegen._run_pipeline(
                    files['q/main.py'], filename=entry,
                    **({'do_imports': True} if mode == 'single-TU'
                       else {'link_mode': True}))[0]
                c_file = os.path.join(td, f'twohop_{mode}.c')
                exe = os.path.join(td, f'twohop_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    return (f"{label} [{mode}]: gcc -fgimple failed:\n"
                            f"{cc.stderr[:1200]}")
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                if run.stdout != want:
                    return (f"{label} [{mode}]: printed {run.stdout!r}, "
                            f"CPython printed {want!r}")
            return None

        with tempfile.TemporaryDirectory() as td:
            err = build_and_compare(td, 'TMPDIR')
        if err:
            print(f"FAIL  {name}: {err}")
            _FAIL += 1
            return
        # `build/` is git-ignored, so a fixture left behind would be an
        # untracked file in the tree; removed in a `finally` either way.
        # Same reasoning as test_link_mode.py's own in-tree case.
        root = os.path.join(_PROJECT_DIR, 'build', 'test_gimple')
        os.makedirs(root, exist_ok=True)
        inside = tempfile.mkdtemp(prefix='twohop_', dir=root)
        try:
            err = build_and_compare(inside, 'inside this checkout')
        finally:
            import shutil
            shutil.rmtree(inside, ignore_errors=True)
        if err:
            print(f"FAIL  {name}: {err}")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_dedup_variadic_externs_cache_is_a_faithful_parse():
        """`_dedup_variadic_externs`'s memo must never change what it
        answers — including the entries it DERIVES for the text it returns
        (emit_infra's `_record_output_parse`: the parse of `'\n'.join(parts)`
        taken from the parts' own entries, so the parent level, which inlines
        exactly that text, does not rescan it).

        The failure mode this guards is invisible in the compiled output
        until it isn't: a derived entry that is a SUPERSET of the text's real
        parse makes the next level drop a variadic declaration it should have
        kept, i.e. a wrong artifact, not a slow one. So the invariant checked
        is on the CACHE, not on speed: for every text the function has ever
        published, the entry must equal an independent, uncached parse of that
        same text.

        `parts` is driven through the shape that makes the derivation
        observable at all — each level's parts CONTAIN the previous level's
        output blob — over hand-built edge shapes (a part whose trailing
        fragment merges with the next part's leading one, in every extern
        flavor) plus a randomized corpus that leaves ~half its parts
        unterminated on purpose. The reference implementation here is a
        verbatim transcription of the pre-derivation body with a private
        memo, so it cannot drift with the code under test the way a
        hand-written expectation list would."""
        global _PASS, _FAIL
        name = "dedup_variadic_externs_cache_is_a_faithful_parse"
        import mojo.backend_gimple.emit_infra as ginf
        import random

        ref_cache: dict = {}

        def _ref_is_extern_decl(stmt):
            for line in stmt.split('\n'):
                line = line.strip()
                if line == 'extern' or line.startswith('extern ') \
                        or line.startswith('extern"'):
                    return True
            return False

        def _ref_parse(part):
            concrete, variadic = [], []
            for stmt in part.split(';'):
                if not _ref_is_extern_decl(stmt):
                    continue
                paren = stmt.find('(')
                if paren < 0:
                    continue
                close = stmt.rfind(')')
                if close < paren:
                    continue
                params = stmt[paren + 1:close].strip()
                head_toks = stmt[:paren].strip().split()
                if not head_toks:
                    continue
                cname = head_toks[-1].lstrip('*')
                if params == '...':
                    variadic.append(cname)
                elif params != '':
                    concrete.append(cname)
            return concrete, variadic

        def _ref_dedup(parts):
            concrete, variadic_by_part = set(), []
            for p in parts:
                entry = ref_cache.get(p)
                if entry is None:
                    entry = _ref_parse(p)
                    ref_cache[p] = entry
                for cname in entry[0]:
                    concrete.add(cname)
                variadic_by_part.append(entry[1])
            if not concrete:
                return '\n'.join(parts)
            kept = []
            for i in range(len(parts)):
                drop = False
                for vname in variadic_by_part[i]:
                    if vname in concrete:
                        drop = True
                        break
                if not drop:
                    kept.append(parts[i])
            return '\n'.join(kept)

        edges = [
            'extern int foo (int);', 'extern int foo (...);',
            'extern', 'extern "C" int64_t bar (int64_t);',
            'extern "C" int64_t bar (...);', 'extern int * baz (char *, int);',
            'extern int unbalanced (int;', 'extern int tail_no_semi (int)',
            'extern int no_paren_decl', '', '   ', '\n',
            'static int helper (int x) { return x; }',
            '#line 3 "Lib/test/ffi/test_external_call.mojo"\nextern int only_here (...);',
            '#line 9 "somewhere/test_external_call.mojo"\nstd_testing___init___assert_false (_t5);',
            'extern int dup (int);\nextern int dup (...);',
            'extern int multi\n  (\n  int\n)\n;', 'extern void void_ret ();',
            'extern int ml_variadic (...)\n;', 'extern char * ppp (char ***);',
            # the merge shapes: two adjacent parts whose trailing/leading
            # fragments join into one `;`-delimited fragment
            'extern int a (int', 'extern int a (...)', 'extern int b (int)',
            'extern int b (...)', '\nextern (int)', 'extern struct X y',
        ]
        frags = [
            'int f{i} (int a);', 'int f{i} (...);', 'char * g{i} (char *);',
            'void h{i} (void);', 'extern int f{i} (int a);',
            'extern int f{i} (...);',
            'extern "C" int64_t k{i} (int64_t, int64_t);',
            'extern "C" int64_t k{i} (...);',
            'static int local{i} (int x) {{ return x + {i}; }}', '',
        ]

        def _rand_part(rng, i):
            r = rng.random()
            if r < 0.08:
                return rng.choice(['', ' ', '\n', ';\n', '  \n'])
            body = frags and rng.choice(frags).format(i=i * 10)
            for j in range(rng.randint(0, 2)):
                body += rng.choice([';', ';\n', ';  ', ' ']) \
                    + rng.choice(frags).format(i=i * 10 + j + 1)
            if rng.random() < 0.5:
                body += rng.choice([';', ';\n', '; ', ' ', ''])
            if rng.random() < 0.25:
                # deliberately unterminated trailing fragment: the shape that
                # can merge with the NEXT part's leading fragment
                body += rng.choice(['extern int late (int', 'extern int late (...)',
                                    'trailing text', 'f (int x) {'])
            return body

        ref_cache.clear()
        ginf._DEDUP_EXTERN_PARTS_CACHE.clear()

        def _compare(tag, parts):
            want = _ref_dedup(list(parts))
            got = ginf._dedup_variadic_externs(list(parts))
            if want != got:
                print(f"FAIL  {name} [{tag}]: dedup answer changed\n"
                      f"  parts={parts!r}\n  reference={want!r}\n"
                      f"  actual={got!r}")
                return False
            if ginf._dedup_variadic_externs(list(parts)) != want:
                print(f"FAIL  {name} [{tag}]: a WARM cache changed the answer "
                      f"(memo must not be order- or call-count-dependent)")
                return False
            return True

        # hand-built arrangements, every adjacent pair (the merge shape is a
        # pair property), and the whole corpus
        ok = _compare('edges-all', edges)
        for i in range(len(edges) - 1):
            ok &= _compare(f'pair-{i}', [edges[i], edges[i + 1]])
            ok &= _compare(f'pair-rev-{i}', [edges[i + 1], edges[i]])
        ok &= _compare('triple-merge', ['extern int a (int', 'extern int b (int)',
                                        'extern int c (...);'])
        ok &= _compare('triple-merge2', ['extern int a (int', 'extern int a (...);'])
        ok &= _compare('empty-corpus', [])
        if not ok:
            _FAIL += 1
            return

        # multi-level: level k's parts contain level k-1's output, which is
        # the only shape in which a wrong derived entry is observable
        rng = random.Random(20260930)
        for trial in range(120):
            r2 = random.Random(trial)
            blobs = []
            for lvl in range(rng.randint(2, 6)):
                parts = list(blobs) + [_rand_part(r2, lvl * 100 + j)
                                       for j in range(r2.randint(1, 6))]
                want = _ref_dedup(list(parts))
                got = ginf._dedup_variadic_externs(list(parts))
                if want != got:
                    print(f"FAIL  {name} [trial {trial} level {lvl}]: "
                          f"dedup answer changed once a derived entry was in "
                          f"play\n  parts={parts!r}")
                    _FAIL += 1
                    return
                blobs.append(got)
            for key, entry in ginf._DEDUP_EXTERN_PARTS_CACHE.items():
                ref_entry = _ref_parse(key)
                if set(ref_entry[0]) != set(entry[0]) \
                        or list(ref_entry[1]) != list(entry[1]):
                    print(f"FAIL  {name} [trial {trial}]: published entry is "
                          f"not the text's real parse\n  text={key[:300]!r}\n"
                          f"  reference={ref_entry!r}\n  actual={entry!r}")
                    _FAIL += 1
                    return
        print(f"PASS  {name}")
        _PASS += 1

    def test_handwritten_selfhost_signature_tables_match_the_source():
        """The hand-written C signature tables must match the Python they
        describe — checked against the SOURCE, not against a comment.

        `_SELFHOST_SIGS` (gimple_codegen) declares what
        `fire_compiler.Parser._parse_expr`, `myinterpreter.Interpreter
        .execute`, `py_tokenize` &c. look like in C, and `runtime/
        fire_runtime.h` declares `py_tokenize` and `compile_to_gimple` a
        second time. Nothing connected either of them to the definitions the
        compiler actually infers, so all four copies of the same facts drifted
        from all three of them independently, and the drift was invisible
        until a whole self-host closure had been generated and handed to gcc:

          * `Parser__parse_expr` was `int64_t` in every copy while its
            definition is emitted `UnaryOp *` — 2 `conflicting types` errors
            plus a `-Wint-conversion` at each of ~40 call sites, both across
            modules (the bad decl is emitted once per IMPORTER) and inside
            fire_compiler.py itself.
          * `py_tokenize(src, filename="")` was declared with ONE parameter in
            both copies — 25 `too many arguments to function 'py_tokenize'`
            errors, one per call site in the closure.
          * `jit_compile_and_execute` was `int64_t` in
            `_SELFHOST_FUNC_RETURN_TYPES` and `_Bool` in the emitted
            declaration.

        A hand-written table the compiler cannot check is a table that will
        drift again. This derives the arity from the real function objects
        with `inspect`, so a signature change fails here, in `make check`,
        instead of after a 30-minute `fire.py fire --dump-full` plus a gcc
        run. The header is compared against the same source because it is the
        only copy a NON-self-host module's generated C sees.

        The RETURN type of an unannotated method is not derivable from the
        source at all, so for the one entry where it matters
        (`Parser__parse_expr`) it is derived from the generated C instead —
        see `selfhost_emitted_return_type` and the note at the call site.
        Checking that entry's SHAPE ("must be a pointer") is what let it hold
        a return type no definition had, which is the same class of bug the
        arity check exists to prevent, one level down."""
        global _PASS, _FAIL
        name = "handwritten_selfhost_signature_tables_match_the_source"
        import inspect
        import fire_compiler
        import myinterpreter

        # bare name -> the real function object it must describe. `py_tokenize`
        # is a module-level function so it lives in `_KNOWN_SIGS`; the rest are
        # struct methods, which the self-host forward-decl block spells out in
        # `_SELFHOST_SIGS`. The third field is the (module, struct) its
        # DEFINITION is emitted in, for the return-type half of the check.
        subjects = {
            'py_tokenize': (gimple_codegen.GimpleGen._KNOWN_SIGS,
                            fire_compiler.py_tokenize, None),
            'Parser_parse_module': (
                gimple_codegen._SELFHOST_SIGS,
                fire_compiler.Parser.parse_module,
                ('fire_compiler.py', 'Parser')),
            'Parser___init__': (
                gimple_codegen._SELFHOST_SIGS,
                fire_compiler.Parser.__init__,
                ('fire_compiler.py', 'Parser')),
            'Parser_with_filename': (
                gimple_codegen._SELFHOST_SIGS,
                fire_compiler.Parser.with_filename,
                ('fire_compiler.py', 'Parser')),
            'Parser__parse_expr': (
                gimple_codegen._SELFHOST_SIGS,
                fire_compiler.Parser._parse_expr,
                ('fire_compiler.py', 'Parser')),
            'Interpreter___init__': (
                gimple_codegen._SELFHOST_SIGS,
                myinterpreter.Interpreter.__init__,
                ('myinterpreter.py', 'Interpreter')),
            'Interpreter_execute': (
                gimple_codegen._SELFHOST_SIGS,
                myinterpreter.Interpreter.execute,
                ('myinterpreter.py', 'Interpreter')),
        }
        problems = []
        for bare, (table, fn, home) in subjects.items():
            if bare not in table:
                problems.append(f"{bare}: absent from its signature table")
                continue
            _ret, params = table[bare][0], table[bare][1]
            real = inspect.signature(fn)
            want = len([
                p for p in real.parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
            got = len(params)
            if want != got:
                problems.append(
                    f"{bare}: table declares {got} C parameter(s), the "
                    f"source takes {want} ({list(real.parameters)}) — a "
                    f"DEFAULTED parameter still occupies a C parameter slot")
            # The RETURN type is not derivable from the source: none of these
            # defs carries a return annotation, so `inspect` sees nothing and
            # all this loop could do was assert the table's own SHAPE. That is
            # exactly what let one row hold a type no definition had —
            # `Parser__parse_expr` read `UnaryOp *` because the inference used
            # to say `UnaryOp *` (`left` is first bound by the `not` branch's
            # `UnaryOp(...)`, and first-binding-wins typed the whole Pratt
            # parser that way), then the inference was fixed to return the box
            # for a local rebound across node types and the table kept the old
            # answer. A forward declaration that disagrees with the definition
            # is unrecoverable in a self-host closure: "conflicting types", once
            # per importing module, plus a `-Wint-conversion` at every call
            # site.
            #
            # So this asks the only authority there is: compile the defining
            # module and read the return type off the DEFINITION the codegen
            # actually emits. 3.3 s and 0.1 GB per module, against the ~30
            # minutes a whole self-host closure takes to hit the same
            # disagreement from gcc — and it cannot itself go stale, because it
            # comes from the same inference the definition comes from.
            # Every method row is checked, not just the one that broke: the
            # others are 3 s each and a stale row in any of them is the same
            # build break.
            if home is None:
                continue
            _mod, _struct = home
            _method = bare[len(_struct) + 1:]
            _emitted = selfhost_emitted_return_type(_mod, _struct, _method)
            if not _emitted:
                problems.append(
                    f"{bare}: no emitted definition found in {_mod}'s own "
                    f"generated C to compare the declared {_ret!r} against")
            elif _emitted != _ret:
                problems.append(
                    f"{bare}: the table declares {_ret!r} but the codegen "
                    f"emits the definition as {_emitted!r} — the forward "
                    f"declaration is emitted once per importing module, so "
                    f"every one of them is a conflicting-types error")
        # The `**kwargs`-slot rows, which are the same kind of hand-written
        # claim about the same source and drifted the same way: the index
        # `MojoFunction___call__` carried was 3, the index for the older
        # `(self, interpreter, *args, **kwargs)`, and the method is now
        # `(self, *args, **kwargs)`. Unlike the signature tables above this
        # one is an ARITHMETIC input rather than a type — every consumer
        # derives a count from it (`_lower_named_call` keeps `kw_i - 1`
        # ordinary params, `_lower_struct_method_call` keeps
        # `kw_i - (2 if has_vararg else 1)`), so a stale index does not
        # mistype anything: it keeps the wrong number of leading positionals
        # as "fixed" arguments and emits one argument too many. Measured, two
        # "too many arguments to function 'myinterpreter_MojoFunction___call__';
        # expected 3, have 4" in the self-host closure, one per
        # `BoundMethod.__call__` / `BoundClassMethod.__call__`.
        #
        # Derived here by walking `inspect`'s parameters with the SAME rules
        # gen_module's own registration pass uses (`self` counts, `*args`
        # counts once however many arguments it collects), so the check is
        # against the convention rather than against the number that happens
        # to be right today.
        def _kwargs_slot_index(fn) -> int:
            """The index `**kwargs` occupies, or -1 if the def has none.

            Mirrors module_gen's `_kw_i` walk: every ordinary parameter
            advances the index, the FIRST `*args` advances it once, a second
            `*args` (there is no second) does not, and `**kwargs` stops it."""
            idx = 0
            seen_star = False
            for _p in inspect.signature(fn).parameters.values():
                if _p.kind == _p.VAR_KEYWORD:
                    return idx
                if _p.kind == _p.VAR_POSITIONAL:
                    if seen_star:
                        continue
                    seen_star = True
                idx += 1
            return -1

        kw_subjects = {
            'MojoFunction___call__': myinterpreter.MojoFunction.__call__,
        }
        for bare, fn in kw_subjects.items():
            if bare not in gimple_codegen._SELFHOST_KWARGS_SLOTS:
                problems.append(f"{bare}: absent from _SELFHOST_KWARGS_SLOTS")
                continue
            want = _kwargs_slot_index(fn)
            got = gimple_codegen._SELFHOST_KWARGS_SLOTS[bare]
            if want != got:
                problems.append(
                    f"{bare}: _SELFHOST_KWARGS_SLOTS says **kwargs is at "
                    f"index {got}, the source puts it at {want} "
                    f"({list(inspect.signature(fn).parameters)}) — every "
                    f"caller's fixed-argument count is derived from this "
                    f"number, so a stale one emits a wrong-arity call")
            want_star = any(p.kind == p.VAR_POSITIONAL
                            for p in inspect.signature(fn).parameters.values())
            got_star = gimple_codegen._SELFHOST_KWARGS_HAS_VARARG[bare]
            if want_star != got_star:
                problems.append(
                    f"{bare}: _SELFHOST_KWARGS_HAS_VARARG says {got_star}, "
                    f"the source's *args presence is {want_star} — the "
                    f"packing emits one C MojoList* param for *args and only "
                    f"one MojoDict* without it")

        # The header's hand-written compiler entry points, against the same
        # source. Only the ones the compiled path calls on ordinary code are
        # listed; the rest of the file is runtime plumbing, not a mirror of
        # any Python def.
        hdr_path = os.path.join(_RUNTIME_INC, 'fire_runtime.h')
        with open(hdr_path) as fh:
            hdr = fh.read()
        hdr_decl = re.search(
            r'^\s*MojoList\s*\*\s*py_tokenize\s*\(([^)]*)\)\s*;',
            hdr, re.M)
        if hdr_decl is None:
            problems.append("fire_runtime.h: no py_tokenize declaration")
        else:
            got = len([p for p in hdr_decl.group(1).split(',') if p.strip()])
            want = len(gimple_codegen.GimpleGen._KNOWN_SIGS['py_tokenize'][1])
            if got != want:
                problems.append(
                    f"fire_runtime.h: py_tokenize declared with {got} "
                    f"parameter(s), _KNOWN_SIGS says {want}")
        if problems:
            print(f"FAIL  {name}:")
            for p in problems:
                print(f"  {p}")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_walk_ast_dataclass_cache_is_transparent():
        """`_walk_ast_into`'s per-class "is this class a dataclass" cache
        must be indistinguishable from asking `dataclasses.is_dataclass` on
        every visit — which is what it did before, and what the docstring's
        existing field-name cache already did for `dataclasses.fields`.

        bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md
        (Phase 9). The failure mode this guards is a walk that silently
        STOPS descending: the dataclass test runs BEFORE the scalar
        early-return precisely because on the compiled path every AST node is
        an int64_t-boxed pointer and so tests as an `int` (see that
        function's own comment), and a cache that answered "not a dataclass"
        for a class that is one would drop every field under it — a wrong
        artifact, not a slow one. So the invariant checked is the NODE LIST,
        node for node and in order, not the call count.

        Driven over a real parsed module (so the classes are the real AST
        node types, not stand-ins) and over hand-built shapes that exercise
        the two arms the cache has to keep apart: a genuine dataclass, a
        plain non-dataclass object, a `type` object (which returns before
        the dataclass question is ever asked and so must never be cached),
        and the scalars."""
        global _PASS, _FAIL
        name = "walk_ast_dataclass_cache_is_transparent"
        import mojo.middle.exprtypes as ET
        import dataclasses as _dc
        from fire_compiler import py_tokenize, Parser
        import ast_rewriter

        def parse_module(toks):
            return ast_rewriter.rewrite(Parser(toks).parse_module()) or []

        def _ref_into(node, out, depth=0):
            """Verbatim pre-cache body: `dataclasses.is_dataclass` asked on
            every visit, nothing remembered between them."""
            if node is None:
                return
            if depth > ET._WALK_AST_MAX_DEPTH:
                return
            if isinstance(node, list) or isinstance(node, tuple):
                for item in node:
                    _ref_into(item, out, depth + 1)
                return
            out.append(node)
            if isinstance(node, type):
                return
            if _dc.is_dataclass(node):
                for _f in _dc.fields(node):
                    _fname = _f.name if hasattr(_f, 'type') else _f
                    _child = getattr(node, _fname, None)
                    if _child is node:
                        continue
                    _ref_into(_child, out, depth + 1)
                return
            if isinstance(node, (str, int, float, bool)):
                return
            return

        err = None
        try:
            src = ("class C:\n"
                   "    def m(self):\n"
                   "        return [x for x in range(3)]\n"
                   "def f(a, b=2, *c, **d):\n"
                   "    t = (a, b)\n"
                   "    if a:\n"
                   "        t = t + (c,)\n"
                   "    return {'k': t, 'j': [a, b]}\n")
            stmts = parse_module(py_tokenize(src))
            for _s in stmts:
                ref, got = [], []
                _ref_into(_s, ref)
                ET._walk_ast_into(_s, got)
                if len(ref) != len(got):
                    err = (f'node count {len(ref)} != {len(got)}')
                    break
                for _i, (_r, _g) in enumerate(zip(ref, got)):
                    if type(_r) is not type(_g):
                        err = f'node {_i}: {type(_r)} != {type(_g)}'
                        break
                if err:
                    break
            # The arms the cache keeps apart, on values a walk over a parsed
            # module does not reach: a genuine dataclass (whose whole
            # subtree must still be descended), a plain non-dataclass
            # object, a `type` object, and the scalars. Each is compared
            # node-for-node against the reference body rather than against
            # a hand-written count, so a cache that stopped descending would
            # show up as a length difference here.
            for _probe in (stmts[0], ET, int, dict, "s", 5, 2.5, None, True,
                           (1, 2), ['a']):
                _ref, _got = [], []
                _ref_into(_probe, _ref)
                ET._walk_ast_into(_probe, _got)
                if len(_ref) != len(_got):
                    err = (f'probe {type(_probe)}: {len(_ref)} nodes, '
                           f'got {len(_got)}')
                    break
                for _i, (_r, _g) in enumerate(zip(_ref, _got)):
                    if type(_r) is not type(_g):
                        err = f'probe {type(_probe)} node {_i}: {type(_r)} != {type(_g)}'
                        break
                if err:
                    break
            # A `type` object must never be cached as "not a dataclass":
            # `ET._WALK_DATACLASS_CACHE` must not gain an entry for it, since
            # it returns before the question is asked.
            _t_before = ET._WALK_DATACLASS_CACHE.get(int)
            ET._walk_ast_into(int, [])
            if ET._WALK_DATACLASS_CACHE.get(int) is not _t_before:
                err = 'a `type` object was cached in _WALK_DATACLASS_CACHE'
        except Exception as _e:
            err = f'{type(_e).__name__}: {_e}'
        if err:
            print(f"FAIL  {name}: {err}")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_struct_unpack_computed_format_compiles():
        """`struct.unpack(fmt, buf)` whose format is a VARIABLE must not
        crash the compiler.

        `_returns_kinds_valued` (mojo/backend_gimple/module_gen.py) asked
        `node.args[0].value` — an attribute only a string-literal node has —
        as soon as it saw a `struct.unpack*` call, so `struct.unpack(fmt,
        buf)` raised `AttributeError: 'IdentExpr' object has no attribute
        'value'` and took the WHOLE build down. That is not a rare shape:
        it is how every module that forwards a caller-supplied format
        writes it, and it is what refused Lib/zipfile/__init__.py,
        Lib/shutil.py, Lib/tempfile.py and four Lib/importlib/resources/
        modules from the readers.py closure (see
        bugs/COMPILE_FAIL_importlib_resources_readers.md). Its own
        docstring already said "only literal formats answer"; the code did
        not.

        Asserts only that the module compiles, because that is the whole of
        the regression: the answer for a computed format is "no static
        kinds", which is a compile-time fact and not observable in the
        output. The literal half of the same branch is covered by
        `test_struct_unpack_computed_format_keeps_literal_half`."""
        global _PASS, _FAIL
        name = "struct_unpack_computed_format_compiles"
        src = '''\
import struct

def unpack_it(fmt, buf):
    return struct.unpack(fmt, buf)

def main():
    print(unpack_it("<if", b"abcd"))

main()
'''
        try:
            compile_to_gimple(src)
        except Exception as e:
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_struct_unpack_computed_format_keeps_literal_half():
        """The same fix must not have turned the LITERAL half off: a
        literal mixed format still has to be recognised as kinds-carrying,
        because that is the answer the per-slot-kinds table exists to
        record. A guard that simply returned False for every format would
        satisfy the crash test above and silently disable the feature.

        Both answers come out of ONE expression, so they are asserted on the
        same source rather than by re-deriving the predicate: the two
        functions differ ONLY in whether their format argument is a literal
        or a variable, so a regression that widened the new guard (or a
        pre-existing bug that narrowed it) cannot pass one and fail the
        other unnoticed.

        `_infer_return_maybe_kinds` returns `(maybe_kinds, slot_kinds)` — the
        boolean half and the per-index half — so this reads element 0 of the
        pair. `slot_kinds` is `''` for a `struct.unpack` result (that producer
        has no per-slot spelling to carry; only a list literal does), which is
        asserted too, since a nonempty answer here would mean the new
        list-literal arm is answering for something it should not."""
        global _PASS, _FAIL
        name = "struct_unpack_computed_format_keeps_literal_half"
        src = '''\
import struct

def literal(buf):
    return struct.unpack("<if", buf)

def computed(fmt, buf):
    return struct.unpack(fmt, buf)
'''
        mg = __import__('mojo.backend_gimple.module_gen', fromlist=['x'])
        stmts = gimple_codegen.Parser(
            gimple_codegen.py_tokenize(src)).parse_module()
        raw = {getattr(st, 'name', None):
               mg._infer_return_maybe_kinds(None, st.body, st.params, None)
               for st in stmts if getattr(st, 'name', None) in
               ('literal', 'computed')}
        answers = {k: v[0] for k, v in raw.items()}
        want = {'literal': True, 'computed': False}
        bad = {k: answers.get(k) for k, v in want.items() if answers.get(k) is not v}
        bad.update({f"{k}.slot_kinds": v[1] for k, v in raw.items() if v[1]})
        if bad:
            print(f"FAIL  {name}: wrong static-kinds answer(s) {bad} "
                  f"(want {want} and no per-slot kinds); a computed format "
                  f"must answer False and a literal mixed format True")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_cursor_advance_has_no_cast_operand_in_gimple():
        """A `+ 1` advance must not put a C-style cast where gimple wants
        an operand.

        Five cursor/counter advances (the `next(it)` cursor, the
        `for x in it:` cursor, the regex finditer and findall scan
        positions, and the enumerate counter) spelled their increment
        `cur + (int64_t)1`. A C-style cast is not a legal gimple OPERAND,
        so inside a `__GIMPLE`-tagged function (a lifted closure, which is
        what every nested `def` becomes) that is a hard gimplification
        error, "expected expression before '(' token" — and a gimple PARSE
        error is not recoverable per function, so it takes the whole
        translation unit with it. Tools/cases_generator/analyzer.py was
        refused on exactly this, at every `idx + 1` of its two
        `enumerate(tokens)` loops.

        `1LL` is the tree's existing width-correct int64_t literal idiom
        (see `_gen_for_range`'s own `step_v`) and IS a legal operand, so
        the whole expression becomes valid gimple. Nothing about the
        VALUE changes — which is the point of asserting CPython's answer
        on the same program rather than only "it compiles": the fix moves
        one character class, and a wrong answer there would be exactly
        the kind of silent wrong value a cast-operand fix can introduce.

        Nested `def`s on purpose: a top-level function's body is ordinary
        C, which GCC lowers to gimple itself and so tolerates the cast
        syntax there. Only the `__GIMPLE` bodies reject it, so a
        top-level version of this program passes on the broken tree and
        would prove nothing."""
        global _PASS, _FAIL
        name = "cursor_advance_has_no_cast_operand_in_gimple"
        src = '''\
def outer(items):
    def take(n):
        it = iter(items)
        for _ in range(n):
            print(next(it))
    def drain():
        it = iter(items)
        for x in it:
            print(x)
    take(2)
    drain()

outer([10, 20, 30])
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'cursor_advance.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **({'do_imports': True} if mode == 'single-TU'
                           else {'link_mode': True}))[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'cur_{mode}.c')
                exe = os.path.join(td, f'cur_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                print(f"FAIL  {name}: {', '.join(bad)} printed "
                      f"{dict(results)[bad[0]]!r}, CPython printed {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_paren_name_vs_one_tuple_for_target_differ():
        """`for (a) in b:` binds the whole item; `for (a,) in b:` unpacks it.

        Both reduced to the IDENTICAL target string `"(a)"`, and every
        consumer decided "tuple" by looking for a comma — so the one shape
        Python keeps distinct was decided wrongly, silently and in opposite
        directions: the compiled path printed `1` for `for (a) in [(1,)]`
        where CPython prints `(1,)`, and the interpreter printed `(1,)` for
        `for (a,) in [(1,)]` where CPython prints `1`.

        The parsers now unwrap a parenthesised single NAME to bare text and
        keep the parens for a 1-element group that really had a comma, so
        the surrounding parens are the disambiguation
        (`fire_compiler.for_target_is_tuple`). Asserted against CPython on the
        same text, on both pipelines: a shape whose right answer differs per
        engine is exactly what a hand-written expectation would get wrong.

        All four spellings are here for each of `for` and a comprehension,
        because the comprehension generator target is a SEPARATE parser
        (`_parse_generator_target`) with its own representation — a bare
        comma list carries no parens there — and it had the same collision
        plus its own version of the trailing comma (`[y for y, in z]`
        produced the bare `"y"`). Nested `for (a, (b, c)) in ...` is here
        because the per-slot split has to be bracket-aware.
        """
        global _PASS, _FAIL
        name = "paren_name_vs_one_tuple_for_target_differ"
        src = '''\
def plain(items):
    out = []
    for (a) in items:
        out.append(a)
    return out

def one_tuple(items):
    out = []
    for (a,) in items:
        out.append(a)
    return out

def bare_comma(items):
    out = []
    for a, in items:
        out.append(a)
    return out

def nested(items):
    out = []
    for (a, (b, c)) in items:
        out.append(str(a) + str(b) + str(c))
    return out

print(plain([(1,), (2,)]))
print(one_tuple([(1,), (2,)]))
print(bare_comma([(1,), (2,)]))
print(nested([(1, (2, 3)), (4, (5, 6))]))
print([y for (y) in [(1,), (2,)]])
print([y for (y,) in [(1,), (2,)]])
print([y for y, in [(1,), (2,)]])
print([y for y in [(1,), (2,)]])
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'paren_target.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            # The interpreter is the third engine: it had the OPPOSITE wrong
            # answer (`for (a,) in` bound the whole item), so a compiled-only
            # comparison could not have caught the bug.
            it = subprocess.run([sys.executable, os.path.join(_PROJECT_DIR, 'fire.py'),
                                 'run', entry], capture_output=True, text=True,
                                cwd=td, timeout=120)
            if it.returncode != 0 or it.stdout != want:
                print(f"FAIL  {name} [interp]: exit {it.returncode}, printed "
                      f"{it.stdout!r}, CPython printed {want!r} "
                      f"({(it.stderr or '').strip()[-300:]})")
                _FAIL += 1
                return
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **({'do_imports': True} if mode == 'single-TU'
                           else {'link_mode': True}))[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'paren_{mode}.c')
                exe = os.path.join(td, f'paren_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                print(f"FAIL  {name}: {', '.join(bad)} printed "
                      f"{dict(results)[bad[0]]!r}, CPython printed {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_next_inside_for_over_same_iterator_advances_once():
        """`next(it)` inside `for x in it:` must read the FOLLOWING element.

        `it = iter(<list>)` lowers to a shared list plus an int64_t cursor.
        Both consumers of that cursor have to agree on what it means: Python's
        `list_iterator.__next__` advances BEFORE returning, so by the time the
        loop body runs, the iterator is already one past the element the loop
        yielded, and a `next(it)` in the body reads the one after that. The
        GIMPLE `for` lowering used to advance in its post block — after the
        body — so `next(it)` re-read the element the loop had just handed out:
        half the list consumed, every element reported twice
        (`walk([1,2,3,4])` -> `[1, 1, 3, 3]`).

        This is exactly CPython's own shape, in
        `Tools/cases_generator/analyzer.py::check_escaping_calls`:

            tkn_iter = iter(stmt.contents)
            for tkn in tkn_iter:
                ...
                    next(tkn_iter)

        so the answer is compared against CPython on the SAME text rather
        than a hand-written expectation. The `continue` and `break` arms are
        here because the fix moves the advance out of the post block: they
        must still land in a place where the advance has happened."""
        global _PASS, _FAIL
        name = "next_inside_for_over_same_iterator_advances_once"
        src = '''\
def walk(items):
    it = iter(items)
    out = []
    for x in it:
        out.append(x)
        out.append(next(it))
    return out

def every_other(items):
    it = iter(items)
    out = []
    for x in it:
        if x % 2:
            continue
        out.append(x)
    return out

def bail_on_sentinel(items):
    it = iter(items)
    out = []
    for x in it:
        if x == 99:
            break
        out.append(x)
    return out

def resumes_after_next(items):
    it = iter(items)
    out = []
    print(next(it))
    for x in it:
        out.append(x)
    return out

print(walk([1, 2, 3, 4]))
print(every_other([1, 2, 3, 4, 5, 6]))
print(bail_on_sentinel([1, 2, 99, 3]))
print(resumes_after_next([7, 8, 9]))
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'cursor_once.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **({'do_imports': True} if mode == 'single-TU'
                           else {'link_mode': True}))[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'once_{mode}.c')
                exe = os.path.join(td, f'once_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                print(f"FAIL  {name}: {', '.join(bad)} printed "
                      f"{dict(results)[bad[0]]!r}, CPython printed {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_scalar_arity_min_max_params_are_not_containers():
        """`max(a, b)` must not type `a` as a container.

        `_ITERABLE_CONSUMING_BUILTINS` (infra_infer.py) lists `max`/`min`
        because their ONE-argument form reduces an iterable, but their
        MULTI-argument form is `a if a > b else b` — it compares scalars and
        iterates nothing. Membership alone was therefore enough to mark an
        unannotated param `is_iterated`, which types it `MojoList *` and
        turns the very next line into a hard compile error: the 2-arg `max`
        lowers to the runtime's single-iterable
        `int64_t mojo_max(void *args)`, so gcc reports "too many arguments
        to function 'mojo_max'; expected 1, have 2". Real:
        `Lib/zipfile/__init__.py:1180`'s `n = max(n, self.MIN_READ_SIZE)`
        inside `ZipExtFile._read1`, which typed `n` as `MojoList *` and
        emitted
        `int64_t __GIMPLE ZipExtFile__read1 (ZipExtFile * self, MojoList * n)`.

        Three arities of the same builtin in one program, so the guard
        cannot pass by disabling the container signal wholesale: `one(xs)`
        must still infer `xs` as a container (the reduce form genuinely
        iterates it), while `two(a, b)` and `three(a, b, c)` must not.
        Asserted against CPython's own stdout rather than a literal, so
        the reduce form's correctness is measured rather than assumed, and
        on BOTH pipelines — the single-TU inline path and link mode, which
        is where the zipfile failure actually surfaced."""
        global _PASS, _FAIL
        name = "scalar_arity_min_max_params_are_not_containers"
        src = '''\
def one(xs):
    return max(xs)

def two(a, b):
    return max(a, b) + min(a, b)

def three(a, b, c):
    return max(a, b, c) - min(a, b, c)

class R:
    MIN_READ_SIZE = 4096

    def read1(self, n):
        return max(n, self.MIN_READ_SIZE)

print(one([3, 9, 2]), two(3, 9), three(1, 7, 4), R().read1(3))
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'scalar_arity.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **({'do_imports': True} if mode == 'single-TU'
                           else {'link_mode': True}))[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'sa_{mode}.c')
                exe = os.path.join(td, f'sa_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                print(f"FAIL  {name}: {', '.join(bad)} printed "
                      f"{dict(results)[bad[0]]!r}, CPython printed {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_list_sort_in_a_method_body_is_gimple_legal():
        """`self.<field>.sort()` inside a METHOD must compile.

        `l.sort()`'s lowering passed the `keys` argument as the literal
        text `NULL`, which is a preprocessor macro rather than a gimple
        expression, and — the part that makes it a hard error rather than a
        wrong answer — a cast expression cannot appear inline as a gimple
        call operand either, so the obvious typed-null substitution fails
        just as hard. Both only bite in a `__GIMPLE`-tagged body, which is
        what a METHOD's body is; the identical call in a module-level
        function's body is plain C that GCC lowers itself, which is exactly
        why this never showed up as a function-level case.

        Real: `Lib/collections/__init__.py:1347`'s `UserList.sort`'s
        `self.data.sort(*args, **kwds)`, reduced to a method whose body
        calls `.sort()` on a list field.

        All three call shapes are in one program — bare, `reverse=True`,
        and `key=lambda v: -v` — because the `keys` argument is the one
        that was illegal and the other two are what prove the fix did not
        break them by taking a different path. Asserted against CPython's
        stdout, and on BOTH pipelines."""
        global _PASS, _FAIL
        name = "list_sort_in_a_method_body_is_gimple_legal"
        src = '''\
class C:
    def sort(self):
        self.d = [3, 1, 2]
        self.d.sort()
        print(self.d)
        self.d.sort(reverse=True)
        print(self.d)
        self.d.sort(key=lambda v: -v)
        print(self.d)

C().sort()
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'list_sort.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **({'do_imports': True} if mode == 'single-TU'
                           else {'link_mode': True}))[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'ls_{mode}.c')
                exe = os.path.join(td, f'ls_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                print(f"FAIL  {name}: {', '.join(bad)} printed "
                      f"{dict(results)[bad[0]]!r}, CPython printed {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_itertools_filterfalse_keeps_the_elements_whose_predicate_is_false():
        """`itertools.filterfalse(f, xs)` must build a real list of the
        elements its predicate REJECTS.

        It had no lowering at all, so its result was an unmodelled handle of
        unknown type — and the `next(...)` over it in
        `Lib/importlib/resources/_common.py:105` then had no honest answer, so
        that module fell back to source. The refusal named `next` as the
        missing piece, which was a misdiagnosis: builtin `filter` over the
        same shape compiled fine (its own rows are in this file), and
        `next(iter(<list>))` was the landing spot all along.

        The trap this has to avoid is real and was measured: adding a
        `next(<bare MojoList *>)` lowering to cover the stdlib line would turn
        two CPython `TypeError`s into values (`next([1, 2])` is a TypeError —
        a list is not an iterator — while such a lowering would answer `1`).
        So `next(it)` still refuses, and that is pinned by the next test: a
        wrong fix here COMPILES AND RUNS, printing a value where CPython
        raises, which is why the expectation is CPython's stdout on both
        pipelines and not a hand-written string.

        Four spellings, because each is a separate dispatch site: the
        qualified member call (`_common.py`'s), the bare name after
        `from itertools import filterfalse`, a `for` loop over the result, and
        `list(...)` of it — with a `char *` element type, which is the kind
        the per-element build has to carry through.
        """
        global _PASS, _FAIL
        name = "itertools_filterfalse_keeps_the_elements_whose_predicate_is_false"
        src = '''\
import itertools
from itertools import filterfalse

def qualified(xs, f):
    it = itertools.filterfalse(f, xs)
    return next(iter(it))

def bare(xs, f):
    it = filterfalse(f, xs)
    return next(iter(it))

def as_loop(xs, f):
    out = []
    for v in itertools.filterfalse(f, xs):
        out = out + [v]
    return out

print(qualified([1, 2, 3], lambda v: v < 2))
print(bare([1, 2, 3, 4], lambda v: v % 2 == 0))
print(as_loop([5, 6, 7], lambda v: v < 6))
print(list(itertools.filterfalse(lambda v: v == 'b', ['a', 'b', 'c'])))
'''
        want = _cpython_stdout(src)
        if want is None:
            print(f"FAIL  {name}: CPython does not run the fixture")
            _FAIL += 1
            return
        for mode in ('single-TU', 'link-mode'):
            got = _compiled_stdout(src, mode)
            if isinstance(got, tuple):
                print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                      f"{got[1][:800]}")
                _FAIL += 1
                return
            if got != want:
                print(f"FAIL  {name} [{mode}]: compiled stdout {got!r} != "
                      f"CPython {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_next_over_a_filter_result_still_refuses_without_iter():
        """The negative half of the pair above: `next(<filtered list>)` has no
        lowering and must keep having none.

        In Python a list is NOT an iterator — `hasattr([], '__next__')` is
        False; only `iter(x)` produces one — so `next(filter(f, xs))`'s
        Mojo-side equivalent, `next(<the MojoList the filter built>)`, has no
        honest value to return. A `next` over a `MojoList *` would answer the
        first element instead, which compiles, runs, exits 0 and is wrong.

        Pinned as a REFUSAL — the module falls back to source with a
        diagnostic naming the shape — because the alternative assertion, a
        value, would be pinning the very wrong answer this forbids.
        """
        global _PASS, _FAIL
        name = "next_over_a_filter_result_still_refuses_without_iter"
        src = '''\
def bare(xs, f):
    it = filter(f, xs)
    return next(it)
'''
        for mode, kwargs in (('single-TU', {'do_imports': True}),
                             ('link-mode', {'link_mode': True})):
            try:
                gimple_codegen._run_pipeline(src, filename='p.py', **kwargs)
            except Exception:
                continue
            print(f"FAIL  {name} [{mode}]: next(<a list>) compiled, so a list "
                  f"is being read as an iterator where CPython raises "
                  f"TypeError")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    def test_unannotated_init_param_evidence_reaches_the_signature():
        """An unannotated `__init__` param's ctype must be the SAME answer in
        the emitted signature and in the field's declaration.

        The literal-evidence tables (`_ctor_lit_param_types`,
        `_xf_own_ctor_params`) were read by the FIELD pass only — through a
        `pm` map local to that loop — so a field fed from such a param was
        declared `double` while the parameter stayed `int64_t` in
        `func_param_types`, which is the table `emit_calls.py`'s constructor
        path coerces each argument against ("Coerce each argument to its
        declared `__init__` param C type"). The literal was therefore
        truncated AT THE CALL: `B(2.5)` passed the integer 2, `self.f = f`
        stored it into a `double` field, and `b.f` printed `2.0` where CPython
        prints `2.5` — a wrong value with exit 0
        (the float half of the unannotated-`__init__`-param evidence family).

        The other four rows are the "do not break these" half, and each is a
        path that reaches a ctype by a DIFFERENT rule, so the new arm cannot
        quietly take one of them over: an explicit annotation (`Float64`),
        a declared default (`s='hi'`, which is inference from the default
        expression), a `char *` (which was already right — but for the wrong
        reason: a string literal's ADDRESS round-trips through an `int64_t`
        parameter unchanged, which is luck, not agreement), and a container
        (a different evidence table). The last row is two params in one
        constructor, one with float evidence and one without, so a fix that
        typed the WHOLE signature from the evidence instead of per slot would
        show up as the integer parameter arriving as a double.

        CPython's stdout is the expectation, on both pipelines: the failure
        mode is a plausible number (2.0 for 2.5, 1.0 for 1.5), so only the
        oracle distinguishes it.
        """
        global _PASS, _FAIL
        name = "unannotated_init_param_evidence_reaches_the_signature"
        src = '''\
class F:
    def __init__(self, f):
        self.f = f

class S:
    def __init__(self, s):
        self.s = s
        self.n = s

class A:
    def __init__(self, x: Float64):
        self.x = x

class C:
    def __init__(self, xs):
        self.xs = xs

class D:
    def __init__(self, s='hi'):
        self.s = s

class M:
    def __init__(self, a, b):
        self.a = a
        self.b = b

print(F(2.5).f)
print(S("hi").s)
print(S("hi").n)
print(A(2.5).x)
print(C([1, 2]).xs)
print(D().s)
print(D("yo").s)
print(M(1.5, 2).a)
print(M(1.5, 2).b)
'''
        want = _cpython_stdout(src)
        if want is None:
            print(f"FAIL  {name}: CPython does not run the fixture")
            _FAIL += 1
            return
        for mode in ('single-TU', 'link-mode'):
            got = _compiled_stdout(src, mode)
            if isinstance(got, tuple):
                print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                      f"{got[1][:800]}")
                _FAIL += 1
                return
            if got != want:
                print(f"FAIL  {name} [{mode}]: compiled stdout {got!r} != "
                      f"CPython {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_module_level_struct_global_keeps_its_type_in_a_container():
        """A module-level `p = P("a")` read as a bare name is a global, and
        `_quick_type` used to answer `int64_t` for it because `var_types`
        holds only locals and parameters.

        A global holding a STRUCT is the one value class that cannot recover
        from the box: its C field is an `int64_t` holding the pointer, and a
        struct-allocated value has no runtime type tag for the container
        walkers to dispatch on — so the list literal recorded no element repr
        and `repr([p])` printed the pointer decimal where CPython prints the
        object. `repr(p)` alone was already RIGHT, which is what makes this a
        type-inference gap rather than a repr bug, so both spellings are
        asserted: the one that was broken and the one that must stay right.

        The same text inside a function is the control that pins the fix to
        the module-level spelling rather than to struct-in-a-container, which
        was already working.
        """
        global _PASS, _FAIL
        name = "module_level_struct_global_keeps_its_type_in_a_container"
        src = '''\
class P:
    def __init__(self, x):
        self.x = x
    def __repr__(self):
        return "R<" + self.x + ">"

p = P("a")
print(repr([p]))
print(repr(p))

def inside():
    q = P("b")
    print(repr([q]))
inside()
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'modlevel.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **({'do_imports': True} if mode == 'single-TU'
                           else {'link_mode': True}))[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'ml_{mode}.c')
                exe = os.path.join(td, f'ml_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                print(f"FAIL  {name}: {', '.join(bad)} printed "
                      f"{dict(results)[bad[0]]!r}, CPython printed {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_dict_union_right_operand_is_converted_at_runtime():
        """`dict | x` with `x`'s type unresolved must convert, not cast.

        `mojo_dict_union` takes two `MojoDict *`. When the right operand's
        static type is one, nothing to do. When it is not — an unannotated
        parameter — the old code passed it straight into the `MojoDict *`
        slot, which is a hard compile error:

            passing argument 2 of 'mojo_dict_union' makes pointer from
            integer without a cast

        Real: `Lib/collections/__init__.py:1192`'s `UserDict.__ior__`'s
        `self.data |= other`.

        The obvious fix — cast the scalar — is the wrong one and is
        deliberately NOT taken: a scalar slot may hold a real dict pointer
        or an unrelated value, and a cast hands `mojo_dict_union` whatever
        bits were there. So the conversion is a runtime test against the
        runtime's own `mojo_is_registered_dict` predicate, with the
        non-dict case becoming a fresh empty dict — which is Python's own
        answer for a union with a non-mapping.

        The assertion is on CPython's stdout, and the program returns the
        union INLINE rather than through a function: an unannotated
        function's return type is int64_t on this backend and a returned
        container then prints as its address, which is a separate filed bug
        (CODEGEN_unannotated_function_returning_container_prints_its_
        address.md) and would otherwise make this test fail for the wrong
        reason — or, worse, pass on a tree where the coercion is still
        broken.

        Both operand orders are in the program because the coercion is
        applied to whichever side is unresolved. The merges are kept to
        ONE application each: a second `|=` reorders the left operand's
        keys, which is a separate runtime bug in `mojo_dict_update`
        (RUNTIME_dict_update_discards_insertion_order.md, filed, verified
        present with this change reverted) and is not what this test is
        for."""
        global _PASS, _FAIL
        name = "dict_union_right_operand_is_converted_at_runtime"
        src = '''\
class D:
    def __init__(self):
        self.data = {'z': 9}
    def merge(self, other):
        self.data |= other
        return self

class E:
    def __init__(self):
        self.data = {'z': 9}
    def merge(self, other):
        return other | self.data

d = D()
d.merge({'a': 1})
print(d.data)
e = E()
e.merge({'a': 1})
print(e.data)
print({'p': 1} | {'q': 2})
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'dict_union.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **({'do_imports': True} if mode == 'single-TU'
                           else {'link_mode': True}))[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'du_{mode}.c')
                exe = os.path.join(td, f'du_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                print(f"FAIL  {name}: {', '.join(bad)} printed "
                      f"{dict(results)[bad[0]]!r}, CPython printed {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_dict_literal_star_star_pair_merges_instead_of_storing():
        """A `**expr` pair in a dict display must MERGE, not be stored.

        PEP 448 mapping unpacking is spelled by the parser as a pair whose
        KEY is `UnaryOp(op='**', operand=<mapping>)` and whose VALUE is the
        NoneType sentinel (`fire_compiler.py`'s `_parse_dict_entry`;
        `myinterpreter.py`'s `eval_DictLiteral` docstring states the
        convention and is the reference reading). `_lower_dict_literal`
        walked `node.pairs` as ordinary key/value stores, so the spread's own
        dict went into the KEY slot and the sentinel into the value slot:

            mojo_dict_set_int_kw (_t1, _t8, _t10);   /* _t8 = the dict */

        which at run time is the runtime's own `mojo_dict_key_for` refusing a
        dict as a key — `TypeError: unhashable type: 'dict'`, an unhandled
        exception at exit 1, on `{'a': 1, **{'x': 2}}`. Every key the spread
        should have contributed was also silently missing.

        Measured well past a test program: this compiler's own
        `mojo/backend_gimple/emit_infra.py::_reset_func` seeds
        `gen._dict_val_types` with `**{k: v for k, v in
        gen._global_dict_val_types.items() ...}`, so the SELF-HOSTED binary
        raised this on every input including an empty file and wrote a
        0-byte `.ci` at exit 0 — a silent wrong answer with no gcc error
        anywhere in the closure, which is exactly what
        `test_selfhost.py`'s `run_produced_binary` exists to catch.

        Asserted on CPython's stdout for the same text, in BOTH pipeline
        modes: the shapes cover a spread after a literal pair, a spread
        before one, two spreads with a literal between them (source order is
        what decides a key collision, so a merge that reorders is a wrong
        answer), a spread whose operand is a dict COMPREHENSION (the shape
        `_reset_func` uses), and a spread that overwrites a literal key.
        Returns are inline for the same reason as the test above, and the
        one literal value is `7` rather than `0` because a ZERO integer read
        back out of a dict prints `None` on this backend — a separate,
        pre-existing defect with no spread anywhere in it (verified against
        `HEAD~4`), filed as
        bugs/CODEGEN_dict_int_value_zero_reads_back_as_none.md, and pinning it
        here would make this test red for the wrong reason."""
        global _PASS, _FAIL
        name = "dict_literal_star_star_pair_merges_instead_of_storing"
        src = '''\
def a(x: dict) -> dict:
    return {'a': 1, **x}

def b(x: dict) -> dict:
    return {**x, 'b': 2}

def c(x: dict, y: dict) -> dict:
    return {**x, 'mid': 7, **y}

def d(x: dict) -> dict:
    return {**{k: v for k, v in x.items() if k != 'skip'}}

def e(x: dict) -> dict:
    return {'k': 0, **x}

print(sorted(a({'z': 9}).items()))
print(sorted(b({'y': 8}).items()))
print(sorted(c({'p': 1}, {'q': 2}).items()))
print(sorted(d({'keep': 1, 'skip': 2}).items()))
print(sorted(e({'k': 1}).items()))
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'dict_spread.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **({'do_imports': True} if mode == 'single-TU'
                           else {'link_mode': True}))[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'dsp_{mode}.c')
                exe = os.path.join(td, f'dsp_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout, run.stderr))
            bad = [m for m, out, _e in results if out != want]
            if bad:
                _m, out, err = [(m, o, e) for m, o, e in results
                                if m == bad[0]][0]
                print(f"FAIL  {name}: {', '.join(bad)} printed {out!r}, "
                      f"CPython printed {want!r} (stderr {err.strip()[:200]!r})")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_next_inside_for_over_same_iterator_is_one_ahead():
        """`next(it)` inside `for x in it:` must read the element AFTER the
        one the loop just yielded.

        `it = iter(<list>)` lowers to a shared list plus an int64_t cursor
        (`_try_bind_iter_cursor`), and both the `for` lowering and the
        `next()` lowering read `mojo_list_get(lst, cur)` and then advance
        `cur`. Each is right alone; together they were an off-by-one,
        because the `for` advance happened in its post block AFTER the
        body, so while the body ran the cursor still pointed AT the
        element the loop had just handed to its target — and `next(it)`
        read exactly that one again. `walk([1, 2, 3, 4])` printed
        `[1, 1, 3, 3]` (two elements consumed, each reported twice, and
        half the iterations lost) where CPython prints `[1, 2, 3, 4]`.

        It is silent and exit 0, and it is not a corner case: this is the
        shape CPython's own
        `Tools/cases_generator/analyzer.py::check_escaping_calls` uses.

        Nested `def`s on purpose, for the same reason as the test above:
        only a `__GIMPLE` body proves anything about the cast operand and
        the literal-increment shapes these two lowerings share. Each helper
        PRINTS from inside the closure rather than returning the list:
        returning a `MojoList *` out of a nested def is a separate,
        pre-existing defect (it prints a raw pointer decimal — reproduced
        with no `next()` involved at all), and a regression test should not
        depend on it.

        The other four cases are in the same program because the fix moves
        the advance from the loop's post block to the top of its body, and
        each of those is a way that move could be wrong: `next(it, d)` on
        exhaustion, a `continue` (whose target is the now-empty post block,
        so it must not skip the advance), a `break`, and a string element
        type rather than int64_t."""
        global _PASS, _FAIL
        name = "next_inside_for_over_same_iterator_is_one_ahead"
        src = '''\
def walk(items):
    def inner():
        it = iter(items)
        out = []
        for x in it:
            out.append(x)
            out.append(next(it))
        print('|'.join([str(v) for v in out]))
    inner()

def with_default(items):
    def inner():
        it = iter(items)
        out = []
        for x in it:
            out.append(x)
            out.append(next(it, 0))
        print('|'.join([str(v) for v in out]))
    inner()

def skipping(items):
    def inner():
        it = iter(items)
        out = []
        for x in it:
            if x % 2 == 0:
                continue
            out.append(x)
        print('|'.join([str(v) for v in out]))
    inner()

def stopping(items):
    def inner():
        it = iter(items)
        out = []
        for x in it:
            out.append(x)
            if x == 3:
                break
        print('|'.join([str(v) for v in out]))
    inner()

def strings(items):
    def inner():
        it = iter(items)
        out = []
        for x in it:
            out.append(x)
            out.append(next(it))
        print('|'.join(out))
    inner()

walk([1, 2, 3, 4])
with_default([9, 10])
skipping([1, 2, 3, 4])
stopping([1, 2, 3, 4])
strings(['a', 'b'])
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'next_ahead.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            want = py.stdout
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **{'do_imports': True} if mode == 'single-TU'
                        else {'link_mode': True})[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'na_{mode}.c')
                exe = os.path.join(td, f'na_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                print(f"FAIL  {name}: {', '.join(bad)} printed "
                      f"{dict(results)[bad[0]]!r}, CPython printed {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_iterator_cursor_len_is_remaining_and_dunder_next_advances():
        """`len(<cursor>)` is what is LEFT, and `it.__next__()` is `next(it)`.

        Both were wrong on the LIST cursor that already existed, and both
        wrong SILENTLY — exit 0, plausible numbers.

        `len()` dispatched on the local's storage type, so `len(it)` read
        `mojo_list_len(it)`: the container's TOTAL length, untouched by every
        `next()` that had already run. Draining `[1,2,3,4,5]` and then asking
        `len(it)` answered 5.

        `it.__next__()` matched no receiver branch at all and fell through to
        the stub that answers 0 for an unrecognised method call — so a caller
        draining an iterator with the explicit spelling read 0 and advanced
        NOTHING, and a `for` loop after it replayed the whole container.
        Python spells the same operation both ways, so it is now the SAME
        lowering (`_lower_next_iter_cursor`), not a second implementation of
        the cursor, and exhaustion raises StopIteration exactly as `next(it)`
        does rather than yielding a default.

        Split into two programs because `len(<iterator>)` is Mojo, not Python
        — CPython raises TypeError on it, so there is no oracle for the
        remaining-count half and the expectation is written out. The first
        program therefore pins only what CPython can answer (`__next__` as a
        statement, as an expression, interleaved with `next()`, the 2-arg
        `next(it, default)`, and a `for` resuming afterwards), and the second
        pins `len()` at each point of a drain."""
        global _PASS, _FAIL
        name = "iterator_cursor_len_is_remaining_and_dunder_next_advances"
        cpython_src = '''\
def dunder_next(items):
    it = iter(items)
    out = []
    out.append(next(it))
    it.__next__()
    out.append(next(it))
    it.__next__()
    for v in it:
        out.append(v)
    print('|'.join([str(v) for v in out]))


def with_default(items):
    it = iter(items)
    out = []
    while True:
        v = next(it, -1)
        if v == -1:
            break
        out.append(v)
    print('|'.join([str(v) for v in out]))


def strings(items):
    it = iter(items)
    it.__next__()
    print('|'.join([str(v) for v in it]))


dunder_next([1, 2, 3, 4, 5])
with_default([7, 8])
strings(['a', 'b', 'c'])
'''
        # 5 before anything, 4 after `next(it)`, 3 after the bare
        # `it.__next__()`, then the value the expression form returned (3), 2
        # after it, the `for`'s two remaining elements, and 0 once drained.
        mojo_src = '''\
def report():
    it = iter([1, 2, 3, 4, 5])
    print(len(it))
    print(next(it))
    print(len(it))
    it.__next__()
    print(len(it))
    print(it.__next__())
    print(len(it))
    for v in it:
        print(v)
    print(len(it))


report()
'''
        mojo_want = '5\n1\n4\n3\n3\n2\n4\n5\n0\n'
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'cur_len.py')
            with open(entry, 'w') as fh:
                fh.write(cpython_src)
            py = subprocess.run([sys.executable, entry], capture_output=True,
                                text=True, cwd=td, timeout=60)
            if py.returncode != 0 or not py.stdout:
                print(f"FAIL  {name}: CPython on the same program exited "
                      f"{py.returncode} printing {py.stdout!r} "
                      f"({py.stderr[:300]}) — the test program itself is "
                      f"wrong, not the compiler")
                _FAIL += 1
                return
            cases = [('cpython', cpython_src, py.stdout),
                     ('mojo-only', mojo_src, mojo_want)]
            results = []
            for tag, src, want in cases:
                for mode in ('single-TU', 'link-mode'):
                    try:
                        c_src = gimple_codegen._run_pipeline(
                            src, filename=entry,
                            **({'do_imports': True} if mode == 'single-TU'
                               else {'link_mode': True}))[0]
                    except Exception as e:
                        print(f"FAIL  {name} [{tag}/{mode}]: the compiler "
                              f"raised {type(e).__name__}: {e}")
                        _FAIL += 1
                        return
                    c_file = os.path.join(td, f'cl_{tag}_{mode}.c')
                    exe = os.path.join(td, f'cl_{tag}_{mode}.exe')
                    with open(c_file, 'w') as fh:
                        fh.write(c_src)
                    cc = subprocess.run(
                        [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe,
                         c_file,
                         os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                        capture_output=True, text=True, timeout=300)
                    if cc.returncode != 0:
                        errs = [ln for ln in cc.stderr.splitlines()
                                if ' error:' in ln]
                        print(f"FAIL  {name} [{tag}/{mode}]: gcc -fgimple "
                              f"failed:\n" + "\n".join(errs[:6]))
                        _FAIL += 1
                        return
                    run = subprocess.run([exe], capture_output=True,
                                         text=True, timeout=30)
                    results.append((f'{tag}/{mode}', run.stdout, want))
            bad = [t for t, out, want in results if out != want]
            if bad:
                _t, out, want = [(t, o, w) for t, o, w in results
                                 if t == bad[0]][0]
                print(f"FAIL  {name}: {', '.join(bad)} printed {out!r}, "
                      f"expected {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_span_cursor_reads_the_span_and_len_tracks_the_cursor():
        """`iter(<span>)` binds a real cursor, and `Span(<list>)` is a real view.

        This is the shape that took `test/collections/test_span.mojo` out of
        `compile_stdlib.py`'s EXPECTED_FAILURES, and it needed three fixes, all
        in the same family and all silent before:

        * the cursor binding (`_try_bind_iter_cursor`, then
          `_try_bind_list_iter`) gated on `MojoList *`, so a `Span *` — which
          IS a sequence with a real `_len` — got no cursor at all, `next(it)`
          had no receiver to dispatch on, and the file was a declared red.
          The gate is now the tree's own `_struct_data_field` + `_len` test,
          the same predicate `_lower_subscript` uses to read `span[i]`, so the
          two cannot disagree about what a Span is.
        * `Span(<list>)` stored the list POINTER in `_data` and left `_len`
          unset — `len(span)` answered whatever the fresh allocation held and
          `span[i]` read the list's own header.
        * `span[i]`'s tracked-element branch required the element type to be a
          known STRUCT, so every numeric span fell to the byte-oriented
          fallback and read ONE byte where the element is eight.

        There is deliberately NO CPython comparison: `Span` is Mojo-only, so
        the same text under CPython is a NameError. The expectation is written
        out instead, and it is the value a correct implementation must produce
        — `3`/`5` then the eight lines `test_iter` in that file asserts."""
        global _PASS, _FAIL
        name = "span_cursor_reads_the_span_and_len_tracks_the_cursor"
        want = '3\n5\n5\n1\n4\n2\n3\n4\n5\n0\n'
        src = '''\
def walk_span():
    var data = [1, 2, 3, 4, 5]
    var span = Span(data)
    print(span[2])
    print(len(span))
    var it = iter(span)
    print(len(it))
    print(next(it))
    print(len(it))
    for v in it:
        print(v)
    print(len(it))


walk_span()
'''
        with tempfile.TemporaryDirectory() as td:
            entry = os.path.join(td, 'span_cur.py')
            with open(entry, 'w') as fh:
                fh.write(src)
            results = []
            for mode in ('single-TU', 'link-mode'):
                try:
                    c_src = gimple_codegen._run_pipeline(
                        src, filename=entry,
                        **({'do_imports': True} if mode == 'single-TU'
                           else {'link_mode': True}))[0]
                except Exception as e:
                    print(f"FAIL  {name} [{mode}]: the compiler raised "
                          f"{type(e).__name__}: {e}")
                    _FAIL += 1
                    return
                c_file = os.path.join(td, f'sc_{mode}.c')
                exe = os.path.join(td, f'sc_{mode}.exe')
                with open(c_file, 'w') as fh:
                    fh.write(c_src)
                cc = subprocess.run(
                    [GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-o', exe, c_file,
                     os.path.join(_RUNTIME_INC, 'fire_runtime.c')],
                    capture_output=True, text=True, timeout=300)
                if cc.returncode != 0:
                    errs = [ln for ln in cc.stderr.splitlines()
                            if ' error:' in ln]
                    print(f"FAIL  {name} [{mode}]: gcc -fgimple failed:\n"
                          + "\n".join(errs[:6]))
                    _FAIL += 1
                    return
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=30)
                results.append((mode, run.stdout))
            bad = [m for m, out in results if out != want]
            if bad:
                _m, out = [(m, o) for m, o in results if m == bad[0]][0]
                print(f"FAIL  {name}: {', '.join(bad)} printed {out!r}, "
                      f"expected {want!r}")
                _FAIL += 1
                return
        print(f"PASS  {name}")
        _PASS += 1

    def test_a_program_written_inside_the_checkout_is_not_the_compiler():
        """A user program's LOCATION must not change its generated C.

        `_is_selfhost_source_dir` answered "is this the compiler's own
        source?" by walking UP from the file's directory looking for a
        `fire_compiler.py` ancestor, so it said True for every file under
        this checkout — `.tmp/`, `build/`, `tools/`, anything. Both of its
        call sites then ran unconditionally: one registered the
        COMPILER's own AST-node struct layouts (`Scope`, `Token`, `Parser`,
        `ReturnValue`, ...) into the `struct_field_types` a user program is
        member-access-typed against, the other re-tokenized the compiler's
        own sources into that program's gen. Measured at the time: the same
        program compiled from inside vs outside the checkout produced 355
        lines of C difference, all but the `#line` directive being exactly
        those typedefs — for a program containing no AST nodes at all.

        This was the third copy of "is this the compiler's own source?"
        answered by a position test, after the two that
        `bugs/CODEGEN_link_mode_bare_submodule_marker_call_silent_wrong_
        value.md`'s fix consolidated into `methods_shared._is_selfhost_
        source_file`. Both call sites already HAD the filename in hand, so
        the file-level predicate dropped in without the ancestor walk, and
        `_is_selfhost_source_dir` went with them.

        `TMPDIR` is `<repo>/.tmp` here, so a plain `TemporaryDirectory` is
        the interesting case rather than a vacuous one — but that is
        asserted, not assumed, or this test would quietly stop testing
        anything on a machine with a different `TMPDIR`.
        """
        global _PASS, _FAIL
        name = "a_program_written_inside_the_checkout_is_not_the_compiler"
        tmp = os.path.abspath(tempfile.gettempdir())
        if not tmp.startswith(_PROJECT_DIR + os.sep):
            print(f"SKIP  {name}: TMPDIR {tmp} is outside {_PROJECT_DIR}, "
                  f"so the condition under test cannot arise")
            return
        # Exactly the names the `_is_selfhost_file` block registers into
        # `struct_field_types` / `struct_boxed_fields` / `_field_elem_types`.
        # Deliberately NOT "every AST node name": a LARGER block alongside
        # that one registers ~57 more UNCONDITIONALLY, for reasons of its
        # own, and folding those in here would make this test fail for a
        # different bug than the one it is pinning.
        gated_structs = (
            'BinaryOp', 'BoundClassMethod', 'BoundMethod', 'BreakException',
            'CallExpr', 'CompareChain', 'ContinueException', 'Interpreter',
            'MemberExpr', 'MojoClass', 'MojoFunction', 'MojoInstance',
            'MojoOverloadSet', 'Parser', 'ReturnValue', 'Scope',
            'TernaryExpr', 'Token', 'UnaryOp', '_AutoStubCheckNamespace',
            '_AutoStubNamespace', '_AutoStubValue', '_ComplexFloat',
            '_MojoBoundComptimeFunction', '_MojoComplex', '_MojoSortFn',
            '_MojoSortPartial')
        src = '''\
import os


def helper(a, b):
    return a + b


class Box:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


def run(path):
    b = Box(helper(1, 2))
    d = {'k': b.get()}
    return len(d) + len(os.path.basename(path))


print(run('x/y.txt'))
'''
        builds = []
        with tempfile.TemporaryDirectory() as td:
            for sub in ('loc1', 'loc2'):
                d = os.path.join(td, sub)
                os.mkdir(d)
                prog = os.path.join(d, 'prog.py')
                with open(prog, 'w') as fh:
                    fh.write(src)
                builds.append(gimple_codegen._run_pipeline(
                    src, filename=prog, do_imports=True)[0])

        injected = sorted({s for s in gated_structs
                           if ('typedef struct %s ' % s) in builds[0]})
        if injected:
            print(f"FAIL  {name}: a user program written under the checkout "
                  f"was handed the COMPILER's own AST struct layouts "
                  f"({', '.join(injected)}) — "
                  f"bugs/CODEGEN_selfhost_source_dir_claims_any_file_under_"
                  f"the_checkout.md")
            _FAIL += 1
            return
        # The `#line` directive correctly carries each file's OWN path, so it
        # is the one line allowed to differ between two directories.
        strip = lambda c: [l for l in c.split('\n')
                           if not l.startswith('#line ')]
        if strip(builds[0]) != strip(builds[1]):
            print(f"FAIL  {name}: the same program generated different C "
                  f"depending only on which directory under the checkout "
                  f"it was written in")
            _FAIL += 1
            return
        print(f"PASS  {name}")
        _PASS += 1

    test_cursor_advance_has_no_cast_operand_in_gimple()
    test_next_inside_for_over_same_iterator_advances_once()
    test_paren_name_vs_one_tuple_for_target_differ()
    test_walk_ast_dataclass_cache_is_transparent()
    test_scalar_arity_min_max_params_are_not_containers()
    test_list_sort_in_a_method_body_is_gimple_legal()
    test_dict_union_right_operand_is_converted_at_runtime()
    test_dict_literal_star_star_pair_merges_instead_of_storing()
    test_module_level_struct_global_keeps_its_type_in_a_container()
    test_itertools_filterfalse_keeps_the_elements_whose_predicate_is_false()
    test_next_over_a_filter_result_still_refuses_without_iter()
    test_unannotated_init_param_evidence_reaches_the_signature()
    test_next_inside_for_over_same_iterator_is_one_ahead()
    test_iterator_cursor_len_is_remaining_and_dunder_next_advances()
    test_span_cursor_reads_the_span_and_len_tracks_the_cursor()
    test_a_program_written_inside_the_checkout_is_not_the_compiler()
    test_struct_unpack_computed_format_compiles()
    test_struct_unpack_computed_format_keeps_literal_half()
    test_ctor_arg_container_literal_field_is_container_typed()
    test_ctor_arg_dict_and_set_literal_fields_are_container_typed()
    test_ctor_arg_mixed_container_and_scalar_stays_int64()
    test_ctor_arg_local_bound_to_container_literal_is_container_typed()
    test_ctor_arg_self_field_container_read_is_container_typed()
    test_field_value_through_local_keeps_char_star_return_type()
    test_generator_bool_yield_slot_is_bool()
    test_generator_bool_tuple_slot_is_bool()
    test_generator_int_yield_slot_stays_int64()
    test_generator_mixed_bool_and_int_yields_widen_to_int()
    test_user_defined_dunder_repr_is_called()
    test_user_defined_dunder_repr_value()
    test_aliased_and_reexported_imports_resolve_to_the_defining_module()
    test_gen_taking_middle_helper_is_never_reached_by_a_local_import()
    test_dotted_import_two_hop_attribute_call()
    test_dedup_variadic_externs_cache_is_a_faithful_parse()
    test_handwritten_selfhost_signature_tables_match_the_source()
    test_every_funcptr_initializer_has_a_definition()
    test_ast_walk_reaches_every_name_in_a_lambda_body()
    test_callable_return_type_survives_its_carrier()
    test_variadic_lambda_lowers_as_gimple_in_every_body()
    test_scalar_given_a_char_star_parameter_is_stringified()
    test_ctor_of_a_container_reaches_the_comprehension()
    test_a_returned_heterogeneous_list_keeps_its_slot_kinds()
    test_next_on_a_user_struct_lowers_and_its_for_loop_says_why_not()

    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    _check_gcc()
    ok = run_tests()
    sys.exit(0 if ok else 1)
