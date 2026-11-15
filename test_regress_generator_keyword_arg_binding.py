#!/usr/bin/env python3
"""Regression: a compiled generator call's keyword arguments bind to the
parameter the keyword NAMES, not to the next free C slot.

`_emit_generator_start_call` (the ordinary, non-coroutine lowering every
generator construction in plain code goes through) kept its own copy of the
keyword padding and read the 1:1 name list out of `gen._func_param_names`,
a map that is keyed for ORDINARY functions and never carries a compiled
generator.  `_gen_pnames` was therefore empty on every generator call, the
by-name branch could never run, and the historical "keywords are written in
declaration order in the trailing slots" convention bound them positionally.
A keyword-only signature makes the two orders disagree, so this is a silent
WRONG ANSWER, not a refusal:

  def marks(*, group=5, groups=2): yield groups
  marks(groups=3)              CPython 3   compiled 2  (the default)
  marks(groups=6, group=7)     CPython 6   compiled 7  (swapped slot)

The api entry every generator registration builds already records the
correct list (`param_names`); the fix reads it first.  This test compares the
compiled binary's stdout with CPython's, and pins the expected lines so a
"both wrong the same way" future lowering cannot pass.

Run: `python3 test_regress_generator_keyword_arg_binding.py`   (~12 s, <1 GB)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')

SRC = (
    'def marks(*, group=5, groups=2):\n'
    '    yield groups\n'
    '\n'
    '\n'
    'def tagged(prefix, *, label=1):\n'
    '    yield prefix\n'
    '    yield label\n'
    '\n'
    '\n'
    'def main():\n'
    '    a = marks(groups=3)\n'
    '    print(next(a))\n'
    '    b = marks(groups=6, group=7)\n'
    '    print(next(b))\n'
    '    c = marks(group=7)\n'
    '    print(next(c))\n'
    '    d = tagged("x", label=9)\n'
    '    print(next(d))\n'
    '    print(next(d))\n'
    '    e = marks()\n'
    '    print(next(e))\n'
    '\n'
    '\n'
    'main()\n'
)

EXPECT = ['3', '6', '2', 'x', '9', '2']


def main() -> int:
    os.makedirs(os.path.join(HERE, '.tmp'), exist_ok=True)
    with tempfile.TemporaryDirectory(dir=os.path.join(HERE, '.tmp')) as tmp:
        src = os.path.join(tmp, 'generator_keyword_arg_binding.py')
        out = os.path.join(tmp, 'out_generator_keyword_arg_binding')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(SRC)
        r = subprocess.run(
            [sys.executable, FIRE, 'build', '-o', out, src],
            cwd=HERE, capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0:
            print('FAIL: build refused a keyword-called compiled generator')
            print('stdout:', (r.stdout or '')[-400:])
            print('stderr:', (r.stderr or '')[-1600:])
            return 1
        want = subprocess.run(
            [sys.executable, src], capture_output=True, text=True, timeout=30,
        )
        if want.returncode != 0:
            print('FAIL: CPython could not run the reference program')
            print('stderr:', (want.stderr or '')[-400:])
            return 1
        got = subprocess.run([out], capture_output=True, text=True, timeout=30)
        if got.returncode != 0:
            print('FAIL: built binary failed')
            print('stdout:', (got.stdout or '')[-400:])
            print('stderr:', (got.stderr or '')[-400:])
            return 1
        g = (got.stdout or '').strip().splitlines()
        w = (want.stdout or '').strip().splitlines()
        if w != EXPECT:
            print('FAIL: reference output is not the expected shape:', w)
            return 1
        if g != w:
            print('FAIL: keyword arguments bound to the wrong generator '
                  'parameters')
            print('compiled:', g)
            print('cpython: ', w)
            return 1
        print('PASS: generator keyword arguments bind by name')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
