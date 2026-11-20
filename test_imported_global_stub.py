#!/usr/bin/env python3
"""Done-when test for the imported module-level GLOBAL half of the
`bootstrap-stage1-transitive` closure's weak-stub residue (GATE
red_recover-land 2026-11-02, part 5 part 1).

A `from M import TABLE` where `TABLE` is a module-level DICT/SET global is
NOT a function: every read is lowered through the DEFINING module's
`<mod>__mojo_global_get_<name>` accessor, registered by
`_emit_imported_global_accessors`. The export entry carries a
`c_return_type` but no `signature`, so `_gmp_emit_imported_symbol_stubs`
also emitted a weak `int64_t TABLE (...)` "unavailable in compiled mode"
stub for it — dead code in the `.ci`, and one of the closure's
`CLOSURE_INCOMPLETE` stub classes (`_EXPR_DISPATCH`, `_STMT_DISPATCH`, the
aliased `_SIGNED`/`_UNSIGNED`/`_FLOAT`/`_BIN_OPS`/`_CMP_OPS`).

The fixture is the compiler's own shape: `generated_dispatch.py` defines the
tables, `types.py` re-exports one under an alias (`as _GD_SIGNED`) and one
bare, and the consumer imports the bare one and reads both through calls.
The test requires zero `unavailable in compiled mode` in the emitted C, then
builds that C and requires the binary's stdout to equal CPython's.

The fixture MUST live inside a checkout (under `build/`, git-ignored): the
sibling-module resolution path this exercises is keyed on the importing file
being one of the compiler's own `.py` siblings, and a `$TMPDIR` outside the
tree takes the generic branch instead.

Run: python3 test_imported_global_stub.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'fire_runtime.c')

DISPATCH_SRC = """\
_SIGNED: dict = {
    'int8': 1,
    'int16': 2,
}

_EXPR_DISPATCH: dict = {
    'add': 'plus',
    'sub': 'minus',
}
"""

OWNER_SRC = """\
STRING_GLOBAL = 'hello-owner'
"""

TYPES_SRC = """\
from generated_dispatch import _SIGNED as _GD_SIGNED, _EXPR_DISPATCH


def pick(op):
    return _EXPR_DISPATCH.get(op, 'nope')


def rank(x):
    return _GD_SIGNED.get(x, 0)


def banner():
    # Function-scoped sibling import of a module-level DICT global: the
    # import binds inside the body, not at module scope, and the name must
    # still read the defining module's accessor, not a stub.
    from generated_dispatch import _EXPR_DISPATCH
    return _EXPR_DISPATCH.get('add', 'none')
"""

CONSUMER_SRC = """\
from types import _EXPR_DISPATCH, banner, pick, rank


def label():
    from owner import STRING_GLOBAL
    return STRING_GLOBAL


def main():
    print(pick('add'))
    print(pick('zzz'))
    print(rank('int16'))
    print(sorted(_EXPR_DISPATCH))
    print(banner())
    print(label())


main()
"""


def _write_tree(td: str) -> str:
    for rel, src in (
            ('generated_dispatch.py', DISPATCH_SRC),
            ('owner.py', OWNER_SRC),
            ('types.py', TYPES_SRC),
            ('consumer.py', CONSUMER_SRC),
    ):
        with open(os.path.join(td, rel), 'w') as f:
            f.write(src)
    return os.path.join(td, 'consumer.py')


def _cpython_stdout(td: str, root: str) -> str:
    env = dict(os.environ)
    env['PYTHONPATH'] = td + (os.pathsep + env['PYTHONPATH']
                              if env.get('PYTHONPATH') else '')
    r = subprocess.run([sys.executable, root], capture_output=True, text=True,
                       cwd=td, env=env, timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def _build_and_run(ci: str, td: str) -> str:
    gcc = find_gcc()
    c_path = os.path.join(td, 'consumer.ci')
    with open(c_path, 'w') as f:
        f.write(ci)
    c_o = os.path.join(td, 'consumer.o')
    rt_o = os.path.join(td, 'fire_runtime.o')
    exe = os.path.join(td, 'consumer.exe')
    r = subprocess.run([gcc, '-O0', '-fgimple', '-x', 'c',
                        f'-I{RUNTIME_DIR}', '-c', '-o', c_o, c_path],
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    assert r.returncode == 0, r.stderr + '\n---\n' + ci
    r = subprocess.run([gcc, '-O0', f'-I{RUNTIME_DIR}', '-c', '-o', rt_o,
                        RUNTIME_C],
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([gcc, '-o', exe, c_o, rt_o], capture_output=True,
                       text=True, timeout=COMPILE_TIMEOUT_S)
    assert r.returncode == 0, r.stderr + '\n---\n' + ci
    r = subprocess.run([exe], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def test_imported_global_has_no_function_stub():
    import gimple_codegen
    root = os.path.join(HERE, 'build', 'test_imported_global_stub')
    os.makedirs(root, exist_ok=True)
    td = tempfile.mkdtemp(prefix='probe_', dir=root)
    try:
        root_file = _write_tree(td)
        expected = _cpython_stdout(td, root_file)
        assert expected == ('plus\nnope\n2\n[\'add\', \'sub\']\n'
                              'plus\n' 'hello-owner\n'), expected
        with open(root_file) as f:
            ci = gimple_codegen.compile_to_gimple(
                f.read(), do_imports=True, filename=root_file)
        # An imported global's reads go through its accessor; nothing may
        # have emitted a callable weak stub for it.
        assert 'unavailable in compiled mode' not in ci, '\n'.join(
            ln for ln in ci.splitlines()
            if 'unavailable in compiled mode' in ln)
        assert 'unavailable' not in ci
        # The accessor path itself is still what the reads use — the stub
        # must be gone because the real lowering exists, not because reads
        # stopped resolving.
        assert '__mojo_global_get__EXPR_DISPATCH' in ci, ci
        assert '__mojo_global_get__SIGNED' in ci, ci
        # The function-scoped import of the same global, compiled as its own
        # module (do_imports=False: the `fire dylib` / closure-dump shape, where
        # the defining module is NOT inlined), must read the accessor too: the
        # bug there was an `extern int64_t _EXPR_DISPATCH (...)` declaration
        # plus a `_funcptr__EXPR_DISPATCH` pointer, not a call to the accessor.
        with open(os.path.join(td, 'types.py')) as f:
            sep = gimple_codegen.compile_to_gimple(
                f.read(), do_imports=False,
                filename=os.path.join(td, 'types.py'))
        assert '_funcptr__EXPR_DISPATCH' not in sep, sep
        assert 'extern int64_t _EXPR_DISPATCH' not in sep, sep
        assert 'generated_dispatch__mojo_global_get__EXPR_DISPATCH' in sep, sep
        # The FUNCTION-SCOPED sibling import is the case this pin adds: the
        # read must resolve the defining module's accessor too, not a stub.
        assert '__mojo_global_get_STRING_GLOBAL' in ci, ci
        assert 'STRING_GLOBAL (...)' not in ci, ci
        assert _build_and_run(ci, td) == expected
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    test_imported_global_has_no_function_stub()
    print('PASS')
