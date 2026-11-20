#!/usr/bin/env python3
"""Signature diagnostics are anchored at the offending parameter and every
offending declaration is reported (modular's failed_binding_deferrals.mojo and
autoparam_dependency_errors.mojo FileCheck lines).

* A struct binding that violates a `where` clause is reported at the PARAMETER
  that carries it (line:col of `x`), not at the `def`.
* Two bad signatures in one module give two diagnostics, not just the first.
* An inferred-parameter dependency error and a variadic element-type error in
  the same module are both reported.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

BINDING = '''struct CondCopyable[T: Movable & Deinitable](
    Copyable where conforms_to(T, Copyable), Movable
):
    var value: Self.T


struct NeedsCopyablePos[T: Copyable, n: Int](Movable where False) where n > 0:
    pass


def failed_binding[U: Movable & Deinitable](
    x: NeedsCopyablePos[CondCopyable[U], 0]
):
    pass


def successful_binding[U: Movable & Deinitable](
    x: NeedsCopyablePos[CondCopyable[U], 1]
):
    pass
'''

AUTOPARAM = '''struct Pair[a: Int, b: Int](Movable where False):
    pass


struct NeedsPair[a: Int, b: Int, p: Pair[a, b]](Movable where False):
    pass


struct RepeatedDep[c: Int, X: NeedsPair[c, c, _]]:
    pass


def variadic_deps[a: Int, b: Int, *Xs: NeedsPair[a, b, _]]():
    pass
'''


def build(src):
    d = tempfile.mkdtemp(prefix='sig_anchor_')
    p = os.path.join(d, 't.mojo')
    with open(p, 'w') as fh:
        fh.write(src)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build', p,
                        '-o', os.path.join(d, 'out')],
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def test_binding_anchored_at_parameter_and_all_reported():
    rc, out = build(BINDING)
    assert rc != 0, out
    assert re.search(r't\.mojo:12:5: error: violated constraint', out), out
    assert re.search(r't\.mojo:18:5: error: invalid bindings in signature: lacking evidence',
                     out), out


def test_autoparam_and_variadic_both_reported():
    rc, out = build(AUTOPARAM)
    assert rc != 0, out
    assert "'Pair[c, c]' cannot depend on non-inferred parameter 'c'" in out, out
    assert ("element type parameter 'NeedsPair[a, b, p]' must be an 'inferred' "
            "parameter") in out, out


if __name__ == '__main__':
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('PASS', name)
            except AssertionError as e:
                failed += 1
                print('FAIL', name, str(e)[:500])
    sys.exit(1 if failed else 0)
