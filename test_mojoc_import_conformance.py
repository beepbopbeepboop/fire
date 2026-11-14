#!/usr/bin/env python3
"""Regression: a conformance failure against a `.mojoc` import is reported.

Modular's `test/mojo-tool/run/import_mojoc_conformance_error.mojo` precompiles
a package, deletes its sources, and builds a consumer that instantiates the
imported struct with a type that does not satisfy its trait bound. It expects
the ordinary conformance diagnostic:

    error: 'Container' parameter 'T' has 'Marked' type, but value has type 'AnyStruct[NotMarked]'

This tree's `.mojoc` artifact (`mojo/middle/mojoc_artifact.py`) stored struct
bracket parameters but no trait requirement records, and no import path
checked an instantiation against a stored bound: the instantiation fell
through to the plain-constructor path and compiled silently. The check now
reuses the source path's conformance checker on the artifact's trait records
(`mojo/middle/mojoc_conformance.py`), at the same point a source-defined
generic struct would have been checked.

Part 1 of `bugs/mid/DIAGNOSTICS_mojoc_imports-part1.md`.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gimple_codegen import compile_to_gimple

ROOT = os.path.join(HERE, '.tmp', 'mojoc_import_conformance')

# Verbatim from modular's inputs/precompiled_conformance/pkg: the consumer
# never materializes DefaultHelper's declaration, only the default alias.
PKG = {
    '__init__.mojo': 'from .container import Container\n',
    'container.mojo': (
        'from .helper import Helper, default_helper\n'
        '\n'
        '\n'
        'trait Marked:\n'
        '    def marked(self):\n'
        '        ...\n'
        '\n'
        '\n'
        'struct Container[T: Marked, H: Helper = default_helper]:\n'
        '    var value: Int\n'
        '\n'
        '    def __init__(out self):\n'
        '        self.value = 0\n'),
    'helper.mojo': (
        'from .impl import DefaultHelper\n'
        '\n'
        '\n'
        'trait Helper:\n'
        '    def help(self):\n'
        '        ...\n'
        '\n'
        '\n'
        'comptime default_helper = DefaultHelper[4]\n'),
    'impl.mojo': (
        'from .helper import Helper\n'
        '\n'
        '\n'
        '@fieldwise_init\n'
        'struct DefaultHelper[n: Int](Copyable, Helper, Movable):\n'
        '    var x: Int\n'
        '\n'
        '    def help(self):\n'
        '        pass\n'),
}

CLIENT = (
    'from pkg import Container\n'
    '\n'
    '\n'
    '@fieldwise_init\n'
    'struct NotMarked(Copyable, Movable):\n'
    '    var value: Int\n'
    '\n'
    '\n'
    'def main():\n'
    '    _ = Container[NotMarked]()\n')

CLIENT_CONFORMING = (
    'from pkg import Container\n'
    '\n'
    '\n'
    '@fieldwise_init\n'
    'struct Good(Copyable, Movable):\n'
    '    var value: Int\n'
    '\n'
    '    def marked(self):\n'
    '        pass\n'
    '\n'
    '\n'
    'def main():\n'
    '    _ = Container[Good]()\n')

EXPECTED = ("error: 'Container' parameter 'T' has 'Marked' type, "
            "but value has type 'AnyStruct[NotMarked]'")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def _fixture(name):
    """A fresh fixture root with the modular package precompiled into `deps`
    and its sources deleted."""
    base = os.path.join(ROOT, name)
    if os.path.exists(base):
        shutil.rmtree(base)
    src = os.path.join(base, 'src', 'pkg')
    deps = os.path.join(base, 'deps')
    os.makedirs(deps, exist_ok=True)
    for fn, text in PKG.items():
        _write(os.path.join(src, fn), text)
    out = os.path.join(deps, 'pkg.mojoc')
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, 'fire.py'), 'precompile', src,
         '-o', out],
        capture_output=True, text=True)
    assert r.returncode == 0, f'precompile failed:\n{r.stdout}\n{r.stderr}'
    shutil.rmtree(os.path.join(base, 'src'))
    return base, deps, out


def _compile_consumer(deps, text, name):
    path = os.path.join(deps, name)
    _write(path, text)
    return compile_to_gimple(text, do_imports=True, filename=path)


def test_artifact_carries_the_trait_requirement():
    """The bound check is only possible because the record stores Marked's
    required method, next to Container's bracket-parameter bound text."""
    from mojo.middle import mojoc_artifact
    _base, deps, out = _fixture('record')
    art = mojoc_artifact.load_artifact(out)
    container = art['structs']['Container']
    params = {p['name']: p for p in container['bracket_params']}
    assert params['T']['type'] == 'Marked', params
    assert params['H']['type'] == 'Helper', params
    assert params['H']['default'] == 'default_helper', params
    marked = art['structs']['Marked']
    assert marked['kind'] == 'trait', marked
    assert [m['name'] for m in marked['methods']] == ['marked'], marked
    assert mojoc_artifact.resolve_import('pkg', 'Container', [deps]) is not None


def test_imported_struct_conformance_error_is_reported():
    _base, deps, _out = _fixture('violation')
    try:
        _compile_consumer(deps, CLIENT, 'main.mojo')
    except RuntimeError as e:
        text = str(e)
        assert EXPECTED in text, text
        return
    raise AssertionError(
        'a non-conforming type argument to an imported .mojoc struct '
        'compiled silently')


def test_link_mode_build_reports_it_too():
    """`fire.py build` (driver.compile_program, link mode) is the path the
    modular RUN line takes: it must fail the same way, not link a program
    whose call silently degraded to a stub."""
    _base, deps, _out = _fixture('link_mode')
    path = os.path.join(deps, 'main.mojo')
    _write(path, CLIENT)
    import driver
    try:
        driver.compile_program(path, CLIENT,
                               output=os.path.join(deps, 'main'), run=False)
    except Exception as e:
        assert EXPECTED in str(e), e
        return
    raise AssertionError('link-mode build accepted a non-conforming .mojoc '
                         'struct instantiation')


def test_conforming_imported_struct_is_not_rejected():
    _base, deps, _out = _fixture('conforming')
    # The positive control must not be refused by the new check. (A `.mojoc`
    # carries no struct body to monomorphize, so a conforming instantiation
    # takes the pre-existing fall-through, which is not this bug's subject.)
    try:
        _compile_consumer(deps, CLIENT_CONFORMING, 'main.mojo')
    except RuntimeError as e:
        assert EXPECTED not in str(e), e


def test_live_sources_win_over_a_stale_mojoc():
    """A `.mojoc` artifact beside a real package must never shadow its
    sources: the source import path is unchanged (it compiles this
    consumer without the new check)."""
    _base, deps, out = _fixture('sources_win')
    pkg = os.path.join(deps, 'pkg')
    for fn, text in PKG.items():
        _write(os.path.join(pkg, fn), text)
    assert os.path.exists(out)
    _compile_consumer(deps, CLIENT, 'main.mojo')


if __name__ == '__main__':
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('all tests passed')
