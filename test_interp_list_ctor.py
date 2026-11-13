#!/usr/bin/env python3
"""Regression: the interpreter's `List(...)` constructor.

The bug (INTERP_list_ctor_wraps_its_iterable, filed 2026-11-13):
`myinterpreter.py`'s `_MojoListType.__call__` was a positional-variadic
construction — `list(args)` — so a single iterable argument was WRAPPED as
one element (`List([1, 2])` answered `[[1, 2]]`) and the `length=`/`fill=`
keyword forms were ignored (`List(length=3, fill=7)` answered `[]`), while
the compiled path (fixed first, 66c1d6a9b; pinned by test_gimple.py's
gate_stdlib_syntax_bare_list_constructor) answered `[1, 2]` and `[7, 7, 7]`.
The two engines disagreed on the same program.

The doc names the direct Python-level check of `_MojoListType` as the
cheapest regression (no compiled path), so this file is two layers:

1. The constructor itself, called as Python calls it — the three forms the
   doc names (`([1, 2])`, `(length=3, fill=7)`, `(1, 2, 3)`) plus the
   wrap-vs-copy distinction, the `fill_with` form, and the pre-existing
   behaviours the fix must not disturb (`copy=`, `capacity=`, the
   `__list_literal__` desugaring marker, a lone non-iterable).
2. The doc's own repro run end-to-end through `python3 fire.py run`, which
   reaches the constructor through the interpreter's scope
   (`self.scope.define('List', _MojoListType())`) exactly as user code does —
   including a `fill_with` given as a Mojo `lambda`, which the constructor
   must invoke like any other value call.
"""
import os
import subprocess
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')
from myinterpreter import _MojoListType


class Tally:
    def __init__(self):
        self.npass = 0
        self.nfail = 0

    def check(self, name, actual, want):
        if actual == want:
            self.npass += 1
            print(f'PASS  {name}')
        else:
            self.nfail += 1
            print(f'FAIL  {name}: got {actual!r}, want {want!r}')


def test_direct_constructor(tally):
    """The doc's named cheapest regression: call the constructor directly."""
    # The doc's spelling `_MojoListType()([1, 2])` is instance + call: the
    # class is not itself callable, its INSTANCE is (`scope.define('List',
    # _MojoListType())` hands user code exactly this one).
    L = _MojoListType()
    # The three forms the doc names.
    tally.check('List([1, 2]) copies, does not wrap', L([1, 2]), [1, 2])
    tally.check('List(length=3, fill=7) fills', L(length=3, fill=7), [7, 7, 7])
    tally.check('List(1, 2, 3) is the variadic form', L(1, 2, 3), [1, 2, 3])
    # The copy half of `List(<iterable>)`: mutating the result must not
    # touch the argument — the pre-fix behaviour also failed this, because
    # it returned a list whose ONE element WAS the argument.
    src = [1, 2]
    copy = L(src)
    copy.append(3)
    tally.check('List(<list>) is a copy (arg untouched)', src, [1, 2])
    tally.check('List(<list>) carries the elements', copy, [1, 2, 3])
    # Every iterable kind the doc names, each matched against `list(...)`,
    # its own definition of "the copy in the container's iteration order".
    tally.check('List((1, 2)) copies a tuple', L((1, 2)), list((1, 2)))
    tally.check('List({1, 2}) copies a set', L({1, 2}), list({1, 2}))
    tally.check('List(<dict>) copies a dict (its keys)',
                L({'a': 1, 'b': 2}), list({'a': 1, 'b': 2}))
    tally.check('List(range(3)) copies a range', L(range(3)), list(range(3)))
    tally.check('List("ab") copies a str', L("ab"), list("ab"))
    tally.check('List(b"ab") copies bytes (its ints)',
                L(b"ab"), list(b"ab"))
    # `length=` without a filler builds nothing; the fill is used once and
    # copied, never re-evaluated.
    tally.check('List(length=3) alone is empty', L(length=3), [])
    tally.check('List(length=0, fill=7) is empty',
                L(length=0, fill=7), [])
    # A non-callable filler is an honest error, not a silent empty list.
    try:
        L(length=2, fill_with=5)
        tally.check('List(length=, fill_with=<non-callable>) refuses',
                    'raised', 'no error')
    except TypeError:
        tally.npass += 1
        print('PASS  List(length=, fill_with=<non-callable>) refuses')
    # The pre-existing behaviours the fix must not disturb.
    tally.check('List() is empty', L(), [])
    tally.check('List(5) still wraps a lone non-iterable', L(5), [5])
    tally.check('List(copy=...) still copies that value',
                L(copy=[9, 8]), [9, 8])
    tally.check('List(capacity=...) still builds nothing', L(capacity=4), [])
    tally.check('the __list_literal__ marker is dropped, values kept',
                L(1, 2, 3, __list_literal__=None), [1, 2, 3])
    tally.check('List(__list_literal__=None) is the empty literal',
                L(__list_literal__=None), [])


def test_end_to_end(tally):
    """The doc's repro, through `python3 fire.py run`, plus the `fill_with`
    form as a Mojo `lambda` (a MojoFunction the constructor must invoke
    like any other value call) and the copy-vs-alias distinction visible
    in user code."""
    source = textwrap.dedent('''\
        def main():
            var a = List([1, 2])
            print(a)
            print(a * 3)
            var b = List(length=3, fill=7)
            print(b)
            var c = List(1, 2, 3)
            print(c)
            var d = List(a)
            d.append(3)
            print(a)
            print(d)
            var e = List(length=3, fill_with=lambda i: i * 2)
            print(e)
    ''')
    want = ('[1, 2]\n'
            '[1, 2, 1, 2, 1, 2]\n'
            '[7, 7, 7]\n'
            '[1, 2, 3]\n'
            '[1, 2]\n'
            '[1, 2, 3]\n'
            '[0, 2, 4]\n')
    with tempfile.TemporaryDirectory(prefix='mojo_list_ctor_') as wd:
        path = os.path.join(wd, 'prog.mojo')
        with open(path, 'w') as f:
            f.write(source)
        r = subprocess.run([sys.executable, MOJO, 'run', path],
                           capture_output=True, text=True, timeout=120,
                           cwd=HERE)
    if r.returncode != 0:
        tally.nfail += 1
        print(f'FAIL  interp end-to-end: exit {r.returncode}: '
              f'{r.stderr.strip()[:300]}')
        return
    if r.stdout != want:
        tally.nfail += 1
        print(f'FAIL  interp end-to-end: printed {r.stdout!r}\n'
              f'      want {want!r}')
        return
    tally.npass += 1
    print('PASS  interp end-to-end: the doc repro, fill_with, and the '
          'copy semantics all agree with the compiled path')


def main():
    print('=' * 68)
    print('INTERP LIST CONSTRUCTOR — _MojoListType.__call__')
    print('=' * 68)
    tally = Tally()
    test_direct_constructor(tally)
    test_end_to_end(tally)
    print()
    print(f'Results: {tally.npass} passed, {tally.nfail} failed')
    sys.exit(0 if tally.nfail == 0 else 1)


if __name__ == '__main__':
    main()
