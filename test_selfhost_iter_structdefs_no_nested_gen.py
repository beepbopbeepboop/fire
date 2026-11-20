#!/usr/bin/env python3
"""Pin: `emit_stmts._iter_structdefs` has no nested generator.

`the stage1-transitive closure stub residue (the bootstrap-stage1-transitive job)`'s `_yield_from` row:
the helper used to be a generator `def _yield_from(coll)` nested inside
`_iter_structdefs` (itself a generator) and reading the enclosing `seen` set.
A nested generator that captures an enclosing-scope variable is a shape the
coroutine path cannot compile — it has no capture model for one — so the
imported-module compile (relaxed_imports) skipped it and emitted the weak
`_yield_from: unavailable in compiled mode` stub. Every call under it then
read 0 in the compiled compiler, and the stub sat in the closure dump.

The walk needs no generator at all: `_collect_structdefs` is a module-level
collector that appends as it descends, and `_iter_structdefs` yields the
collected list. This test has three parts:

1. an AST pin that the nested generator (and the capture it needed) is gone
   and that the walk is an ordinary generator over the collector's list;
2. a behaviour check that the walk still visits the same sources, in the same
   order, with the same per-`id` de-duplication;
3. a compile of the REAL current source of both functions as an imported
   sibling module, requiring no `_yield_from` weak stub.

Run: python3 test_selfhost_iter_structdefs_no_nested_gen.py
"""
import ast
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

EMIT_STMTS = os.path.join(HERE, 'mojo', 'backend_gimple', 'emit_stmts.py')


def _module_tree() -> ast.Module:
    with open(EMIT_STMTS, 'r', encoding='utf-8') as f:
        return ast.parse(f.read(), EMIT_STMTS)


def _top_function(tree: ast.Module, name: str):
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    return None


def _has_yield(fn) -> bool:
    return any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(fn))


def _function_source(name: str) -> str:
    with open(EMIT_STMTS, 'r', encoding='utf-8') as f:
        src = f.read()
    tree = ast.parse(src, EMIT_STMTS)
    fn = _top_function(tree, name)
    assert fn is not None, f'{name} is not a module-level function in {EMIT_STMTS}'
    return ast.get_source_segment(src, fn)


def test_walk_is_not_a_nested_generator():
    tree = _module_tree()
    fn = _top_function(tree, '_iter_structdefs')
    assert fn is not None, '_iter_structdefs is gone'
    nested = []
    for child in ast.walk(fn):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not fn:
            if _has_yield(child):
                nested.append(child.name)
    assert not nested, (
        '`_iter_structdefs` defines a nested generator '
        f'({", ".join(nested)}); a nested generator with a captured enclosing '
        'variable is skipped by the coroutine path and becomes the weak '
        '`_yield_from` stub in the closure dump. Use the module-level '
        '`_collect_structdefs` collector instead.')
    assert _top_function(tree, '_collect_structdefs') is not None, (
        'the `_collect_structdefs` collector is missing; `_iter_structdefs` '
        'must not grow its walk back into a nested generator')
    assert _has_yield(fn), '_iter_structdefs is no longer a generator'


def test_collect_order_and_dedupe():
    from fire_compiler import StructDef
    from mojo.backend_gimple.emit_stmts import _iter_structdefs

    a = StructDef('A', [], [])
    b = StructDef('B', [], [])

    class Gen:
        _module_stmts = {'m': {'inner': [a, b]}, 'n': [a]}
        stmts = [b]

    got = list(_iter_structdefs(Gen()))
    assert got == [a, b], f'walk changed: {[s.name for s in got]}'
    assert got[0] is a and got[1] is b


def _write_fixture(td: str) -> str:
    helper = (
        'class StructDef:\n'
        '    pass\n'
        '\n'
        'class _GC:\n'
        '    StructDef = StructDef\n'
        '\n'
        'gimple_ctypes = _GC()\n'
        '\n'
        'def _as_str(x):\n'
        '    if isinstance(x, str):\n'
        '        return x\n'
        '    return str(x)\n'
        '\n'
        + _function_source('_collect_structdefs') + '\n\n'
        + _function_source('_iter_structdefs') + '\n')
    with open(os.path.join(td, 'helper.py'), 'w') as f:
        f.write(helper)
    main = ('from helper import _iter_structdefs\n'
            '\n'
            'def main():\n'
            '    print(len(list(_iter_structdefs(None))))\n'
            '\n'
            'main()\n')
    root = os.path.join(td, 'main.py')
    with open(root, 'w') as f:
        f.write(main)
    return root


def test_real_walk_source_compiles_without_yield_from_stub():
    import gimple_codegen
    root = os.path.join(HERE, 'build', 'test_iter_structdefs_no_nested_gen')
    os.makedirs(root, exist_ok=True)
    td = tempfile.mkdtemp(prefix='probe_', dir=root)
    try:
        main_file = _write_fixture(td)
        ci = gimple_codegen.compile_to_gimple(
            open(main_file).read(), do_imports=True, filename=main_file)
        bad = [ln for ln in ci.splitlines()
               if '__attribute__((weak))' in ln and '_yield_from' in ln]
        assert not bad, (
            'the imported sibling module still emits the skipped-generator '
            'stub for the walk:\n  ' + '\n  '.join(bad))
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    test_walk_is_not_a_nested_generator()
    test_collect_order_and_dedupe()
    test_real_walk_source_compiles_without_yield_from_stub()
    print('PASS')
