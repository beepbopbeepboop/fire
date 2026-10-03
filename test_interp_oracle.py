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
import subprocess
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')
TIMEOUT = 120

# name -> source. Valid Mojo AND valid Python; `main()` is appended by the
# runner, so the programs must define it and must not call it themselves.
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
}


def _run(argv, cwd):
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           errors='replace', timeout=TIMEOUT, cwd=cwd)
    except subprocess.TimeoutExpired:
        return None, 'TIMEOUT', f'timed out after {TIMEOUT}s'
    return r.stdout, r.returncode, r.stderr


def check(name, source):
    """Run one program through both engines; return (ok, detail)."""
    with tempfile.TemporaryDirectory(prefix='mojo_oracle_') as wd:
        body = source if source.rstrip().endswith('main()') else source + '\nmain()\n'
        # The SAME text is both the Mojo source and the Python source: the
        # whole point is that this subset means the same thing to both.
        path = os.path.join(wd, 'prog.py')
        with open(path, 'w') as f:
            f.write(body)
        cpy_out, cpy_rc, cpy_err = _run([sys.executable, path], wd)
        mojo_out, mojo_rc, mojo_err = _run([sys.executable, MOJO, 'run', path], HERE)
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


def main():
    print('=' * 68)
    print('INTERPRETER ORACLE — myinterpreter vs CPython')
    print('=' * 68)
    npass = nfail = 0
    for name, source in CORPUS.items():
        ok, detail = check(name, textwrap.dedent(source))
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
