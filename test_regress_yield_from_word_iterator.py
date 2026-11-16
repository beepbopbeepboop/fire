#!/usr/bin/env python3
"""Regression: `yield from <opaque word iterator>` inside an escaped generator.

A nested generator that captures a first-class list iterator
(`items = iter(source)` in the enclosing function, then `yield from items`
inside the nested `def`) is hoisted to module level with the capture typed as
an opaque word (`int64_t`). Type inference used to report that `yield from
items` site as `char *` while `yield peeked` reported `int64_t`, so the two
sites "disagreed" and the whole module was refused with

    every `yield` must carry a value, and all values must agree on one scalar type

even though the emitter already knows how to drive an opaque word through the
runtime's dynamic iterable view (`mojo_iter_word`): a list, a first-class list
iterator, a dict/set, a string, or a live generator handle, yielding each
element as a boxed word.

The assertion that matters is the CURSOR one: `peeked = next(items)` advances
the iterator, so `yield from items` must continue after it. Iterating a word as
a bare `MojoList *` from index 0 (the old lowering for this shape) would print
`10` twice; the dynamic view consumes the same position CPython does.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')

SRC = (
    'def peek(source):\n'
    '    items = iter(source)\n'
    '    peeked = next(items)\n'
    '\n'
    '    def chain():\n'
    '        yield peeked\n'
    '        yield from items\n'
    '\n'
    '    for x in chain():\n'
    '        print(x)\n'
    '\n'
    '\n'
    'def main():\n'
    '    peek([10, 20, 30])\n'
    '\n'
    '\n'
    'main()\n'
)


def main() -> int:
    with tempfile.TemporaryDirectory(dir=os.path.join(HERE, '.tmp')) as tmp:
        src = os.path.join(tmp, 'yield_from_word_iter.py')
        out = os.path.join(tmp, 'out_yield_from_word_iter')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(SRC)
        r = subprocess.run(
            [sys.executable, FIRE, 'build', '-o', out, src],
            cwd=HERE, capture_output=True, text=True, timeout=180,
        )
        if r.returncode != 0:
            print('FAIL: build refused the escaped generator')
            print('stdout:', (r.stdout or '')[-400:])
            print('stderr:', (r.stderr or '')[-1200:])
            return 1
        run = subprocess.run([out], capture_output=True, text=True, timeout=30)
        if run.returncode != 0:
            print('FAIL: built binary failed')
            print('stdout:', (run.stdout or '')[-400:])
            print('stderr:', (run.stderr or '')[-400:])
            return 1
        got = (run.stdout or '').strip().splitlines()
        want = subprocess.run(
            [sys.executable, src], capture_output=True, text=True, timeout=30,
        ).stdout.strip().splitlines()
        if got != want:
            print('FAIL: wrong output', got, 'want', want)
            return 1
        if got != ['10', '20', '30']:
            print('FAIL: cursor position lost', got)
            return 1
        print('PASS: yield-from opaque word iterator works')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
