#!/usr/bin/env python3
"""Regression: a module-scope name imported from two modules is reported.

Modular's `test/mojo-integration/diagnostics_in_missing_locs_imports.mojo`
precompiles two packages that both declare `Gadget` and `helper`, deletes
their sources, and then imports both names from each. It expects, in order:

    error: import of 'Gadget' is ambiguous
    note: 'Gadget' declared here
    struct Gadget[size: Int]    # note - synthetic signature
    note: 'Gadget' also declared here
    struct Gadget    # note - synthetic signature
    error: import of 'helper' is ambiguous
    ...
    def helper(x: Int) -> Int    # note - synthetic signature
    ...
    struct helper    # note - synthetic signature

Before this, the module-scope pass accepted the file silently: only the
function-body pre-scan knew about the clash, and the declarations of a
deleted package were not printed at all. Both errors come from one run.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

ROOT = os.path.join(HERE, '.tmp', 'mojoc_module_import_ambiguous')

CLASH_A = (
    'struct Gadget[size: Int]:\n'
    '    def __init__(out self):\n'
    '        pass\n'
    '\n'
    '\n'
    'def helper(x: Int) -> Int:\n'
    '    return x\n')

CLASH_B = (
    'struct Gadget:\n'
    '    def __init__(out self):\n'
    '        pass\n'
    '\n'
    '\n'
    'struct helper:\n'
    '    def __init__(out self):\n'
    '        pass\n')

CONSUMER = (
    'from clash_a import Gadget\n'
    'from clash_b import Gadget\n'
    '\n'
    'from clash_a import helper\n'
    'from clash_b import helper\n'
    '\n'
    '\n'
    'def main():\n'
    '    var g = Gadget[4]()\n'
    '    _ = helper(1)\n')

# The ordered lines the diagnostic must contain (FileCheck CHECK order).
EXPECTED_IN_ORDER = [
    "error: import of 'Gadget' is ambiguous",
    "note: 'Gadget' declared here",
    "struct Gadget[size: Int]    # note - synthetic signature",
    "note: 'Gadget' also declared here",
    "struct Gadget    # note - synthetic signature",
    "error: import of 'helper' is ambiguous",
    "note: 'helper' declared here",
    "def helper(x: Int) -> Int    # note - synthetic signature",
    "note: 'helper' also declared here",
    "struct helper    # note - synthetic signature",
]


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def _fixture(name):
    """A fresh root with both packages precompiled into `deps` and their
    sources deleted. Returns the directory holding the artifacts."""
    base = os.path.join(ROOT, name)
    if os.path.exists(base):
        shutil.rmtree(base)
    deps = os.path.join(base, 'deps')
    for pkg, text in (('clash_a', CLASH_A), ('clash_b', CLASH_B)):
        src = os.path.join(base, 'src', pkg)
        _write(os.path.join(src, '__init__.mojo'), text)
        out = os.path.join(deps, pkg + '.mojoc')
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, 'fire.py'), 'precompile', src,
             '-o', out],
            capture_output=True, text=True)
        assert r.returncode == 0, f'precompile failed:\n{r.stdout}\n{r.stderr}'
    shutil.rmtree(os.path.join(base, 'src'))
    return deps


def _compile_consumer(deps, text, name='main.mojo'):
    path = os.path.join(deps, name)
    _write(path, text)
    return compile_to_gimple(text, do_imports=True, filename=path)


def test_ambiguous_module_imports_report_every_conflict_in_order():
    deps = _fixture('ambiguous')
    try:
        _compile_consumer(deps, CONSUMER)
    except RuntimeError as e:
        lines = [ln.strip() for ln in str(e).splitlines()]
        pos = 0
        for want in EXPECTED_IN_ORDER:
            hits = [i for i, ln in enumerate(lines) if ln.endswith(want) or ln == want]
            assert any(i >= pos for i in hits), f'missing or out of order: {want!r}\n{e}'
            pos = min(i for i in hits if i >= pos) + 1
        return
    raise AssertionError('ambiguous module-scope imports compiled without error')


def test_same_name_from_one_module_twice_is_not_ambiguous():
    deps = _fixture('same_module')
    _compile_consumer(deps,
                      'from clash_a import Gadget\n'
                      'from clash_a import Gadget\n'
                      '\n'
                      'def main():\n'
                      '    pass\n')


def main():
    test_ambiguous_module_imports_report_every_conflict_in_order()
    test_same_name_from_one_module_twice_is_not_ambiguous()
    print('ok')


if __name__ == '__main__':
    main()
