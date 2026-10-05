#!/usr/bin/env python3
"""The ORACLE's own regression suite: `myinterpreter.py` vs CPython.

Why this file exists
--------------------
`fire.py run` (the interpreter) is this project's documented oracle for "the
compiled path is wrong". Every other parity test in the tree compares the two
ENGINES against each other, which cannot catch a bug they share — and a
shared wrong answer is exactly what an interpreter bug produces. `deco`'s
`cls` binding a first ARGUMENT instead of the class, and `@deco` being
parsed and then never applied at all, were both invisible that way for as
long as they existed: the compiled path was wrong in the same direction, or
(in the decorator case) also ignored the decorator, so the diff was clean.

So this suite closes the loop: each program below is written in the subset of
syntax that is valid Mojo AND valid Python, run through BOTH
`python3 fire.py run` and `python3 <file>`, and required to produce identical
stdout AND an identical exit code. `main()` is called explicitly at the end
because CPython needs it and `fire.py run` synthesises the entry point.

Only shapes the compiled path does not support belong here. A shape BOTH
engines handle belongs in `test_runtime_diff.py`, which additionally proves
the compiled path agrees — a strictly stronger assertion, and putting it here
would throw that away.
"""
import os
import re
import subprocess
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')
TIMEOUT = 120

# name -> source, or name -> {stem: source} for a case that needs SIBLING
# MODULES. Both spellings are the same promise: valid Mojo AND valid Python,
# `main()` appended by the runner, so the program defines `main` and does not
# call it itself. A dict case is written out under BOTH extensions for every
# stem (`i_lib` becomes `i_lib.py` and `i_lib.mojo`) and the program is the
# stem `prog` — one text, two engines, and `import i_lib` resolves to
# `i_lib.py` under CPython and to `i_lib.mojo` under `fire.py run`, which is
# the only reason the dict form can exist at all. The sources are therefore
# annotation-free: `def f(v):` is a Mojo parameter list and a Python one.
CORPUS = {
    # `@classmethod` binds the CLASS. The interpreter had no classmethod
    # support at all: `Paths.who()` returned the raw unbound function, so the
    # call bound the first real ARGUMENT to `cls` — `Paths.gen(5)` made
    # `cls == 5` and `cls.tag` raised "'int' object has no attribute 'tag'".
    # The compiled path passes a receiver correctly, so the two engines
    # disagreed here and the interpreter was the wrong one.
    "classmethod_binds_the_class": '''\
class Paths:
    tag = 7

    @classmethod
    def who(cls):
        return cls.tag

    @classmethod
    def gen(cls, n):
        yield cls.tag
        yield n

def main():
    print(Paths.who())
    print(Paths().who())
    for v in Paths.gen(5):
        print(v)
''',
    # An inherited classmethod rebinds `cls` to the SUBCLASS, and a
    # classmethod generator delegating with `yield from cls.<sibling>` is the
    # exact shape `Lib/importlib/resources/readers.py` needs
    # (`_candidate_paths` doing `yield from cls._resolve_zip_path(...)`).
    "classmethod_inheritance_and_delegation": '''\
class Base:
    tag = "base"

    @staticmethod
    def suffix(p):
        yield p + "!"
        yield p + "?"

class Child(Base):
    tag = "child"

    @classmethod
    def gen(cls, n):
        yield cls.tag
        yield from Base.suffix(str(n))

def main():
    print(Base.tag)
    print(Child.tag)
    for v in Child.gen(1):
        print(v)
''',
    # A plain `@decorator` is `f = deco(f)`, applied BOTTOM-UP. The
    # interpreter parsed `FunctionDef.decorators` and then never read it, so
    # every decorated function was registered raw. Silently wrong, not a
    # refusal: the program ran and returned the undecorated result.
    #
    # Stacked (`@a` over `@b`) and parameterised (`@tag("A")`, which is
    # `tag("A")(f)` — TWO evaluations, not one) are the two spellings a
    # first implementation gets wrong, so both are here.
    "decorators_applied_bottom_up": '''\
def wrap(f):
    def inner(x):
        return f(x) * 2
    return inner

def tag(name):
    def apply(f):
        def inner(x):
            return name + ":" + str(f(x))
        return inner
    return apply

@wrap
def dbl(x):
    return 21

@tag("A")
def one(x):
    return 1

@tag("B")
@wrap
def two(x):
    return 5

def main():
    print(dbl(3))
    print(one(3))
    print(two(3))
''',
    # A decorator on a METHOD, and on a `@staticmethod` method: the receiver
    # binding is keyed by NAME, so replacing the method value must not
    # disturb it.
    "decorators_on_methods": '''\
def deco(f):
    def inner(self, x):
        return f(self, x) * 10
    return inner

def sdeco(f):
    def inner(x):
        return f(x) + 100
    return inner

class C:
    @deco
    def m(self, x):
        return x + 1

    @staticmethod
    @sdeco
    def s(x):
        return x + 2

def main():
    c = C()
    print(c.m(1))
    print(C.s(1))
''',
    # Compile-time-only decorator names must NOT be applied as runtime
    # decorators: `@staticmethod` selects a binding rule, it is not a
    # function to call. Applying it would be a NameError at class-definition
    # time.
    "compile_time_decorators_are_not_applied": '''\
class K:
    @staticmethod
    def s(x):
        return x + 1

    @classmethod
    def c(cls, x):
        return x + 2

def main():
    print(K.s(1))
    print(K.c(1))
    print(K().s(1))
''',
    # `.get()` on a `dict | dict`: the oracle was already right here (Python
    # dicts), but it is in this file because the COMPILED path lost the value
    # type and silently returned the stored pointer's bits — and this case is
    # what a reader consults to see which engine is expected to be right.
    "dict_union_get": '''\
def main():
    a = {"A": "1"}
    b = {"B": "2"}
    m = a | b
    print(m.get("A"))
    print(m.get("B"))
    print((a | b).get("B"))
    print(m.get("A", "dflt"))
''',
    # A USER-DEFINED function handed to a builtin as a CALLBACK. The
    # interpreter's `MojoFunction.__call__` demanded the interpreter as a
    # first POSITIONAL argument, so every caller had to volunteer it —
    # `Interpreter.invoke` does, and a builtin cannot. `sorted([1,2,3],
    # key=lambda a: -a)` therefore ran `_invoke` with the callee's first real
    # ARGUMENT in the interpreter's slot and died with
    # "AttributeError: 'int' object has no attribute 'scope'". `sorted(key=k)`
    # with a `def`, `min`/`max(key=)` (which additionally IGNORED the key
    # entirely), `map(f, xs)`, a `list.sort(key=)`, a generic
    # `f(*args)`, and a `__call__`-on-the-instance callback are all here
    # because they are all the same hole reached from a different direction.
    "user_function_as_a_builtin_callback": '''\
class Callable:
    def __init__(self, n):
        self.n = n

    def __call__(self, a):
        return a + self.n


def by_neg(a):
    return -a


def main():
    print(sorted([1, 2, 3], key=lambda a: -a))
    print(sorted([1, 2, 3], key=by_neg))
    print(sorted([3, 1, 2], key=abs))
    print(min([3, 1, 2], key=lambda a: -a))
    print(max([3, 1, 2], key=lambda a: -a))
    print(min([3, 1, 2]))
    print(max([3, 1, 2]))
    print(list(map(lambda a: a + 1, [1, 2])))
    xs = ["bb", "a", "ccc"]
    xs.sort(key=len)
    print(xs)
    var = lambda *a: len(a)
    print(var(1, 2))
    kw = lambda **k: len(k)
    print(kw(a=1, b=2))
    print(sorted([1, 2, 3], key=Callable(10)))
''',
    # A list/set/dict comprehension is its OWN SCOPE in Python 3: its `for`
    # target binds nothing in the enclosing body, so the trailing `G` in
    # `shadowed` is still the module's 5 and the answer is 6.
    # `eval_Comprehension` evaluated those in the CURRENT scope — its own
    # docstring called it a "known minor fidelity gap" — so this printed 3,
    # and it was the only engine that did: both formal images print 6
    # (`test_formal_globals.py`), which is the direction that matters, because
    # the interpreter is the engine every other parity test treats as the
    # reference.
    #
    # This is in the ORACLE and not in `test_runtime_diff.py` on purpose. The
    # compiled path had the same defect by a different mechanism — it allocated
    # the comprehension's target as a plain local of the enclosing function, so
    # that local shadowed the module global for the rest of the body, and it
    # printed 3 too — which is why an engine-vs-engine case would have sat red
    # here. That half is fixed now (`_compr_bind_target` asks
    # `module_shared.bare_global_read_plan`, the decision `_lower_IdentExpr`
    # makes, whether the target name is already bound) and the compiled spelling
    # is `test_runtime_diff.py`'s
    # `comprehension_target_does_not_shadow_a_module_constant`. This case stays
    # in the oracle anyway: a third opinion is what catches a bug both engines
    # share, and that is not a property of when the case was written.
    #
    # The last arm is the control in the direction that matters: a plain `for`
    # loop's target DOES bind in the enclosing scope (Python has no loop
    # scope), so `execute_ForStmt`'s simplification is correct and must not be
    # "fixed" along with the comprehension.
    "a_comprehension_does_not_shadow_a_module_constant": '''\
G = 5

def shadowed(rows):
    out = [G for G in rows]
    return G + out[0]

def shadowed_set(rows):
    out = {k for k in rows}
    return len(out)

def shadowed_dict(rows):
    out = {k: k for k in rows}
    return len(out)

def shadowed_local():
    t = "outer"
    lst = [t for t in ["c", "d"]]
    return t + str(lst)

def loop_target_still_binds():
    m = 3
    acc = []
    for m in [1, 2]:
        acc = acc + [m]
    return acc + [m]

def main():
    print(shadowed([1, 2]))
    print(shadowed_set([1, 2, 2]))
    print(shadowed_dict(["a"]))
    print(shadowed_local())
    print(loop_target_still_binds())
''',
    # A module object is a LIVE VIEW of the module's scope, and it used to be a
    # `SimpleNamespace` SNAPSHOT of it taken when the module body finished. So a
    # name the module's own code assigns had two homes: `i_lib.get_it()` read
    # the live scope and answered 9, while `i_lib.G` read the copy and answered
    # the value from before `setg` ran — two reads of one module disagreeing
    # inside one program, with no error and no diagnostic, and `G = v` looking
    # like it had done nothing. CPython answers 9 and 9.
    #
    # This is the shape `test_runtime_diff.py` structurally CANNOT see, which is
    # why it is here: that suite compares the two ENGINES, and the compiled
    # path had this bug too (a module global a module writes was published as
    # a constant, `bugs/FORMAL_module_state_no_storage.md` §(2)) — so a
    # diff between them was clean while both were wrong. This case is the third
    # opinion.
    #
    # The last two lines are the directions that had no home at all: an
    # assignment THROUGH the module object (`i_lib.G = 21`, CPython's rule) used
    # to create a fourth home — an attribute on the snapshot that no function
    # ever read — and `hasattr` on a name the module does not have must still be
    # a `False` and not an auto-stubbed 0.
    "module_object_is_a_live_view_of_the_module_scope": {
        'i_lib': '''\
G = 5

def setg(v):
    global G
    G = v

def get_it():
    global G
    return G
''',
        'prog': '''\
import i_lib

def main():
    print(i_lib.get_it())
    i_lib.setg(9)
    print(i_lib.get_it())
    print(i_lib.G)
    i_lib.G = 21
    print(i_lib.get_it())
    print(hasattr(i_lib, "nope"))
''',
    },

    # A SEQUENCE target unpacks a `str` item, and iterating a DICT hands the
    # target a KEY — which is a `str`. So `for k, *vs in {"abc": 1}` prints
    # `a ['b', 'c']` in CPython and the interpreter printed `abc []`: it
    # exempted `str` from the unpack and bound the whole key to `k` with an
    # empty remainder. A wrong answer on the shape this project's OWN dict
    # iteration produces, and a silent one — exit 0 and a plausible line.
    #
    # The rows are the shapes the same exemption was wrong for, measured against
    # CPython 3.14: `for k, v in {"ab": 1}` binds `a b` there and used to bind
    # `k` alone and leave `v` undefined, so the program died later with
    # `NameError: v` at the USE SITE rather than at the statement that failed to
    # bind it. The comprehension is here because it reaches the same binder
    # through a different call site, and `for k in {"abc": 1}` is the CONTROL: a
    # single name does NOT unpack, which is CPython's rule and the one an
    # unconditional `list(value)` would break. `x, y = "ab"` is the same rule on
    # the ASSIGNMENT side, which reaches the same two helpers.
    "a_sequence_target_unpacks_a_string_item": '''\
def main():
    for k, *vs in {"abc": 1}:
        print(k, vs)
    for k, v in {"ab": 1}:
        print(k, v)
    for k in {"abc": 1}:
        print(k)
    for (a,) in {"a": 1}:
        print(a)
    print([(k, vs) for k, *vs in {"abc": 1}])
    print([(k, v) for k, v in {"ab": 1}])
    x, y = "ab"
    print(x, y)
    for k, *vs in [[1, 2, 3]]:
        print(k, vs)
''',
}

# Shapes CPython CANNOT EXPRESS, so the corpus above cannot hold them: a
# bracketed parameter list is Mojo syntax, and `python3 prog.py` is a
# SyntaxError on it. Each program below is run through the interpreter
# ALONE and asserted against its declared semantics (`main()` is still
# appended by the runner, so the programs define it and do not call it).
#
# These are the interpreter's own regressions — bugs/CODEGEN_interpreter_
# evaluates_a_keyword_bracket_call_as_a_subscript.md being the one that
# added the table. The compiled path is deliberately NOT asserted on the
# same programs: it drops a bracketed call to a function with no RUNTIME
# parameters to a literal 0 on every pipeline
# (bugs/CODEGEN_bracket_call_to_a_runtime_paramless_function_is_a_zero.md),
# so a two-engine diff here would be pinning the wrong answer on one side.
#
# name -> (source, expected stdout).
INTERPRETER_ONLY = {
    # A keyword bracket is a CALL's parameter binding, not a subscript. The
    # parser keeps `f[T=Int, y=5]`'s elements in SubscriptExpr.attrs and
    # leaves `index` as the empty-subscript placeholder IntLiteral(0), and
    # the interpreter used to evaluate that placeholder — binding the
    # callee's FIRST comptime parameter to 0 and dropping the rest, so this
    # printed 0 instead of 5.
    "keyword_bracket_binds_comptime_params_by_name": ('''\
def f[T, y=0, *, linux=0]():
    return y

def main():
    print(f[T=Int, y=5]())
''', '5\n'),
    # A parameter the bracket does not supply comes from its DECLARED
    # default (`y=0`), which is why the same program answers 0 rather than
    # None here. Both the keyword and the bare-positional spellings.
    "comptime_param_default_applies_when_the_bracket_omits_it": ('''\
def f[T, y=0, *, linux=0]():
    return y

def main():
    print(f[T=Int]())
    print(f[3, 9]())
''', '0\n9\n'),
    # A bracket that MIXES a keyword and a positional element, with the
    # positional parameter sitting BETWEEN the two keywords: `std/sys/
    # info.mojo`'s platform_map, whose flags std/io/file.mojo ORs into the
    # open(2) call.
    "mixed_keyword_and_positional_bracket_fills_in_order": ('''\
def platform_map[T: DType, operation, *, linux=0, macos=0]():
    print(operation, linux, macos)

def main():
    platform_map[T=Int, "O_APPEND", linux=1024, macos=8]()
''', 'O_APPEND 1024 8\n'),
    # The same binding on a METHOD, where the receiver has to survive it —
    # `Dict.mojo`/`counter.mojo`'s `self.body[f_key=show_k]()`. The bracket
    # used to answer the bound method itself (`BoundMethod.__getitem__`),
    # so every bracketed argument was dropped and the body's `f_key` was
    # None.
    "method_keyword_bracket_binds_comptime_params": ('''\
def show(k):
    print("show", k)

class P:
    def __init__(self, k):
        self.k = k

    def body[f_key](self):
        f_key(self.k)

    def go(self):
        self.body[f_key=show]()

def main():
    P(3).go()
''', 'show 3\n'),
    # An unbindable comptime parameter is an honest error naming it. The
    # bracket is the only place such a parameter's value can come from, so
    # binding None (which is what an unbindable one used to do) is a wrong
    # answer rather than a default.
    "unbindable_comptime_parameter_is_refused_by_name": ('''\
def h[T, U]():
    return 1

def main():
    print(h[T=Int]())
''', 'TypeError'),
    # A call that does not supply a REQUIRED parameter is an arity error, and
    # it used to be a body run with that parameter bound to `None`: the
    # interpreter's own error here was `unsupported operand type(s) for +:
    # 'int' and 'NoneType'`, raised from inside `add`'s body, one call away
    # from the mistake. CPython raises `add() missing 1 required positional
    # argument: 'b'` for the identical text, which is why the interpreter's
    # wording is CPython's (see `MojoFunction._invoke`).
    #
    # There is no bracket in this program on purpose: the bracket was never
    # the defect. It is how the defect was FOUND
    # (`add[2, 5](x)` on a non-generic `add`), and the two cases below are
    # the two halves of it — this one is the root cause, the next is the
    # bracket on top.
    "missing_required_argument_is_an_arity_error": ('''\
def add(a: Int, b: Int) -> Int:
    return a + b

def main():
    print(add(10))
''', 'TypeError'),
    # A specialization item with no declared comptime parameter to bind it is
    # refused rather than dropped. `dict(zip(comptime_params, values))` stops
    # at the shorter side, so both items were discarded, the call went on as
    # `add(x)`, and the root cause above produced the `NoneType` crash. A
    # specialization is a type-level claim, so an item the declaration cannot
    # hold is a program whose own signature refutes it — and CPython refuses
    # the same subscript outright ('function' object is not subscriptable).
    "a_bracket_item_with_no_parameter_to_bind_is_refused": ('''\
def add(a: Int, b: Int) -> Int:
    return a + b

def main():
    print(add[2, 5](10))
''', 'TypeError: add[...] supplies 2 specialization argument'),
    # A sequence target's ARITY is checked, and both refusals are CPython's
    # wording INCLUDING the part that reads like an oversight: a `str` item
    # says `(expected 1)` with no count and a sequence item says
    # `(expected 1, got 2)`. Both measured on CPython 3.14, and the interpreter
    # now reproduces both — it reproduced NEITHER before, because `zip`
    # truncated to the shorter side, so `for a, b in [(1, 2, 3)]` printed `1 2`
    # and `for a, b in [(1,)]` bound `a` and left `b` UNBOUND, dying at the USE
    # SITE with `NameError: b`.
    #
    # These four are here rather than in `CORPUS` because a program CPython
    # raises on exits non-zero there and `check` requires the reference to run,
    # which is the whole reason the value half of this rule is over there.
    # `[(1, 2, 3)]` into two targets: a SEQUENCE item, so the count is in the
    # message. It used to print `1 2` — a wrong answer, exit 0.
    "a_sequence_target_with_too_many_values_is_refused": ('''\
def main():
    for a, b in [(1, 2, 3)]:
        print(a, b)
''', 'ValueError: too many values to unpack (expected 2, got 3)'),
    # The same arity error with ONE target, where the old reading bound `a` to
    # `1` and looped, printing a line per element of the item.
    "a_one_slot_target_over_two_values_is_refused": ('''\
def main():
    for (a,) in [(1, 2)]:
        print(a)
''', 'ValueError: too many values to unpack (expected 1, got 2)'),
    # A `str` item, and CPython omits the count for one: measured the same day,
    # `for a, b in {"abc": 1}` is `(expected 2)` while `for (a,) in [(1, 2)]` is
    # `(expected 1, got 2)`. The `str` arm of the binder is what hands a dict KEY
    # to the target, so this is the arity error for the same shape as the case
    # above it, and the "not enough" arm of the same rule always carries the
    # count (`for a, b in "ab"` is `expected 2, got 1`).
    "a_sequence_target_over_a_string_key_states_no_count": ('''\
def main():
    for k, v in {"abc": 1}:
        print(k, v)
''', 'ValueError: too many values to unpack (expected 2)'),
    # A non-iterable item, which used to be wrapped in a one-element list and so
    # printed `1 2`, `2 2`, `3 2` — three wrong answers out of one loop.
    "a_sequence_target_over_a_scalar_is_refused": ('''\
def main():
    for a, b in [1, 2, 3]:
        print(a, b)
''', 'TypeError: cannot unpack non-iterable int object'),
    # …and the refusal must not fire on a bracket that DOES fit, including
    # through a function VALUE, which is the shape
    # `std/algorithm/backend/tile.mojo`'s `workgroup_function[size](x, y)`
    # reaches the interpreter by: a builtin holding the callable invokes it
    # directly, so this is the same binding with no call site to lean on.
    "a_bracket_that_fits_still_binds_through_a_function_value": ('''\
def widen[x: Int](a: Int, b: Int) -> Int:
    return a * 100 + b + x

def call_it(f, a: Int, b: Int) -> Int:
    return f(a, b)

def main():
    print(widen[3](5, 7))
    print(call_it(widen[3], 5, 7))
''', '510\n510\n'),
}


def _run(argv, cwd):
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           errors='replace', timeout=TIMEOUT, cwd=cwd)
    except subprocess.TimeoutExpired:
        return None, 'TIMEOUT', f'timed out after {TIMEOUT}s'
    return r.stdout, r.returncode, r.stderr


def check(name, source):
    """Run one program through both engines; return (ok, detail).

    `source` is either the program's text or a `{stem: text}` dict of a
    program plus its imported siblings. `prog` is the program either way.
    """
    files = {'prog': source} if isinstance(source, str) else dict(source)
    with tempfile.TemporaryDirectory(prefix='mojo_oracle_') as wd:
        for stem, text in files.items():
            # Only the PROGRAM gets the appended `main()` call: a library that
            # defines no `main` must not grow one, and one that does would have
            # its entry point invoked by the sibling-module loader.
            body = text
            if stem == 'prog' and not text.rstrip().endswith('main()'):
                body = text + '\nmain()\n'
            # The SAME text is both the Mojo source and the Python source: the
            # whole point is that this subset means the same thing to both.
            with open(os.path.join(wd, stem + '.py'), 'w') as f:
                f.write(body)
            with open(os.path.join(wd, stem + '.mojo'), 'w') as f:
                f.write(body)
        path = os.path.join(wd, 'prog.py')
        cpy_out, cpy_rc, cpy_err = _run([sys.executable, path], wd)
        mojo_out, mojo_rc, mojo_err = _run(
            [sys.executable, MOJO, 'run', os.path.join(wd, 'prog.mojo')], HERE)
    if cpy_out is None or mojo_out is None:
        return False, f'{"cpython" if cpy_out is None else "interp"} timed out'
    if cpy_rc != 0:
        # The reference itself must run; if it does not, the program is wrong.
        return False, f'CPython exited {cpy_rc}: {cpy_err.strip()[:400]}'
    if mojo_rc != cpy_rc:
        first = (mojo_err.strip().splitlines() or [''])[-1]
        return False, (f'exit codes differ: cpython={cpy_rc} interp={mojo_rc}'
                       + (f'; interpreter said: {first[:300]}' if first else ''))
    if mojo_out != cpy_out:
        la, lb = cpy_out.splitlines(), (mojo_out or '').splitlines()
        for i in range(max(len(la), len(lb))):
            x = la[i] if i < len(la) else '<missing>'
            y = lb[i] if i < len(lb) else '<missing>'
            if x != y:
                return False, f'stdout line {i + 1}: cpython={x!r} interp={y!r}'
        return False, 'stdout differs'
    return True, 'stdout + exit identical to CPython'


def check_interp_only(name, source, want):
    """Run one CPython-impossible program through the interpreter alone and
    require `want` to appear in its combined stdout+stderr, with either a
    zero exit (a value) or a non-zero one (the named refusal). `want` is a
    substring rather than the whole stream because the refusal case's
    traceback text is not this file's to pin."""
    with tempfile.TemporaryDirectory(prefix='mojo_oracle_') as wd:
        body = textwrap.dedent(source)
        if not body.rstrip().endswith('main()'):
            body = body + '\nmain()\n'
        path = os.path.join(wd, 'prog.py')
        with open(path, 'w') as f:
            f.write(body)
        out, rc, err = _run([sys.executable, MOJO, 'run', path], HERE)
    if out is None:
        return False, 'interpreter timed out'
    both = out + (err or '')
    # A NAMED refusal, whatever its class. This was a `TypeError` test and the
    # next shape that needed it was a `ValueError`, which is why the test is a
    # name pattern rather than a class: the assertion is about the interpreter
    # NAMING what went wrong, not about which exception family this path
    # happens to use. `want` is still CPython's own wording — the comment above
    # each refusal records the measurement it was taken from.
    if re.match(r'^[A-Za-z]*Error', want):
        if rc == 0:
            return False, f'expected a refusal, got exit 0 printing {out!r}'
        if want not in both:
            return False, f'expected {want!r} in the output, got {both.strip()[-300:]!r}'
        return True, f'refused with {want} (exit {rc})'
    if rc != 0:
        return False, f'exited {rc}: {(err or "").strip()[-300:]}'
    if want not in out:
        return False, f'expected {want!r} in stdout, got {out!r}'
    return True, f'stdout contains {want!r}'


def main():
    print('=' * 68)
    print('INTERPRETER ORACLE — myinterpreter vs CPython')
    print('=' * 68)
    npass = nfail = 0
    for name, source in CORPUS.items():
        if isinstance(source, str):
            source = textwrap.dedent(source)
        else:
            source = {stem: textwrap.dedent(text)
                      for stem, text in source.items()}
        ok, detail = check(name, source)
        print(f'{"PASS" if ok else "FAIL"}  {name}: {detail}')
        if ok:
            npass += 1
        else:
            nfail += 1
    print()
    print('-' * 68)
    print('INTERPRETER ONLY — shapes CPython cannot express (no diff available)')
    print('-' * 68)
    for name, (source, want) in INTERPRETER_ONLY.items():
        ok, detail = check_interp_only(name, source, want)
        print(f'{"PASS" if ok else "FAIL"}  {name}: {detail}')
        if ok:
            npass += 1
        else:
            nfail += 1
    print()
    print(f'Results: {npass} passed, {nfail} failed')
    sys.exit(0 if nfail == 0 else 1)


if __name__ == '__main__':
    main()
