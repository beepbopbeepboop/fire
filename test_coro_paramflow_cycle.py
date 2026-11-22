#!/usr/bin/env python3
"""Regression: a pass-through cycle nothing feeds is not a generator source.

`mojo/middle/coro.py`'s `_ParamFlow` answers "is this argument the tagged
generator?" for `_mixed_generator_callee`. A parameter is the generator at
every call site of its callee only if some call site really passes `g(...)`;
a cycle of functions that pass a parameter to each other, with no call from
outside the cycle, carries no value at all. The old cycle branch answered
"ok" for such a cycle, so `a(x)` -> `b(x)` -> `a(x)` made `use(x)` look
generator-derived, although nothing ever passes the generator.

The fixtures parse real source. `gen` is a generator, `use` a boxed consumer
(a `for` over its parameter), and `use` is called with `x` (a pass-through
parameter) and with `3`, so it is mixed exactly when `x` counts as the
generator.

    python3 test_coro_paramflow_cycle.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fire_compiler  # noqa: E402
import mojo.middle.coro as coro  # noqa: E402

_PRELUDE = '''
def gen():
    yield 1

def use(it):
    for v in it:
        print(v)

def a(x):
    use(x)
    return b(x)

def b(x):
    return a(x)
'''

# The cycle {a, b} is never called from outside, so `x` is never the generator.
UNFED = _PRELUDE + '''
def top():
    use(3)
'''

# Same cycle, but `top` feeds it the generator: now `x` IS the generator at
# `use(x)`, and `use` is genuinely mixed (`use(3)` beside it).
FED = _PRELUDE + '''
def top():
    use(3)
    a(gen())
'''


def _parse(src):
    p = fire_compiler.Parser(fire_compiler.py_tokenize(src))
    p._filename = 't.mojo'
    return p.parse_module()


def test_unfed_cycle_is_not_a_generator_source():
    stmts = _parse(UNFED)
    hit = coro._mixed_generator_callee(stmts, 'gen')
    assert hit is None, (
        f"an unfed pass-through cycle {{a, b}} was reported as the generator "
        f"at {hit[0].name}'s parameter {hit[1]} (sites: {len(hit[2])})")


def test_fed_cycle_is_still_a_generator_source():
    stmts = _parse(FED)
    hit = coro._mixed_generator_callee(stmts, 'gen')
    assert hit is not None, "a cycle fed by a(gen()) must still specialize"
    fd, pidx, gen_sites = hit
    assert fd.name == 'use' and pidx == 0, (fd.name, pidx)
    # Only the call inside the cycle, `use(x)`, is the pass-through; the
    # direct `use(3)` is not generator-derived.
    assert [c.args[0].name for c in gen_sites] == ['x'], gen_sites


if __name__ == '__main__':
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS  {name}')
            except AssertionError as e:
                failed += 1
                print(f'FAIL  {name}: {e}')
    sys.exit(1 if failed else 0)
