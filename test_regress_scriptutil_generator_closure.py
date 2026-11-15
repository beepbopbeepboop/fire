#!/usr/bin/env python3
"""Regression: a compiled generator that mixes a tuple yield with callables
and `yield from <opaque word iterator>` (the `_iter_filenames` shape).

The generator below is a small copy of `Tools/c-analyzer/c_common/
scriptutil.py`'s `_iter_filenames`/`chain` structure:

  * `yield "a", 1, check, True` — a tuple yield whose `check` slot holds a
    zero-argument lambda. A `MojoList *` slot is a WORD, so the lambda must
    be a plain function pointer there (not a `std::function` object), and
    the consuming tuple-unpack must be able to CALL it.
  * `items = src["src"]` then `yield from items` — `items` is an opaque
    `int64_t` word (a boxed list pointer read out of a dict), while this
    generator's own promise is `MojoList *` because of the tuple yield
    above. The three sites used to "disagree", so the generator was refused
    with "every `yield` must carry a value, and all values must agree on
    one scalar type". The word iterator's elements ARE the tuple lists the
    other site yields, so the delegation now co_yields each word as
    `MojoList *` and the consumer tuple-unpacks it normally.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')

SRC = (
    'def outer(src):\n'
    '    check = (lambda: True)\n'
    '    items = src["src"]\n'
    '    yield "a", 1, check, True\n'
    '    yield from items\n'
    '\n'
    '\n'
    'def main():\n'
    '    rows = {"src": [("b", 20, 7, 1), ("c", 30, 7, 1)]}\n'
    '    for s, n, chk, flag in outer(rows):\n'
    '        if n == 1:\n'
    '            print(s, n, 1 if chk() else 0, 1 if flag else 0)\n'
    '        else:\n'
    '            print(s, n, chk, 1 if flag else 0)\n'
    '\n'
    '\n'
    'main()\n'
)


def main() -> int:
    with tempfile.TemporaryDirectory(dir=os.path.join(HERE, '.tmp')) as tmp:
        src = os.path.join(tmp, 'scriptutil_generator_closure.py')
        out = os.path.join(tmp, 'out_scriptutil_generator_closure')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(SRC)
        r = subprocess.run(
            [sys.executable, FIRE, 'build', '-o', out, src],
            cwd=HERE, capture_output=True, text=True, timeout=180,
        )
        if r.returncode != 0:
            print('FAIL: build refused the tuple/word-iterator generator closure')
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
        run = subprocess.run([out], capture_output=True, text=True, timeout=30)
        if run.returncode != 0:
            print('FAIL: built binary failed')
            print('stdout:', (run.stdout or '')[-400:])
            print('stderr:', (run.stderr or '')[-400:])
            return 1
        got = (run.stdout or '').strip().splitlines()
        expect = (want.stdout or '').strip().splitlines()
        if got != expect:
            print('FAIL: wrong output')
            print('got: ', got)
            print('want:', expect)
            return 1
        if expect != ['a 1 1 1', 'b 20 7 1', 'c 30 7 1']:
            print('FAIL: reference output is not the expected shape:', expect)
            return 1
        print('PASS: tuple/word-iterator generator closure works')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
