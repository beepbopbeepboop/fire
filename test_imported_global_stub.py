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
The test requires zero `unavailable in compiled mode` in the emitted C except
the one documented weak stub the util preamble now carries in every TU (the
predeclared prelude `sort`, 00ba62d61), then builds that C and requires the
binary's stdout to equal CPython's.

A second test covers the SEPARATE-compile shape (`do_imports=False`, the
`fire dylib` per-module form): a function-scoped `from module_loader import
STDLIB_PATH` of an unannotated scalar `.py` global must read the defining
module's `char *` accessor, not an `extern int64_t STDLIB_PATH (...)` +
`_funcptr_` read. A third pins the `.py` scalar-global export rule in
`module_loader.py` directly.

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


def _residue_lines(c: str, needle: str) -> list:
    """The `needle` lines of an emitted `.ci` that are NOT the documented
    predeclared prelude `sort` weak stub. Since 00ba62d61 the util preamble
    carries that one honest weak definition in EVERY TU (step 1 of
    bugs/mid/CODEGEN_prelude_sort_is_not_resolved.md: `sort: unavailable in
    compiled mode`), so a blanket string scan sees it whether or not the
    fixture calls `sort`. Anything else carrying the stub marker is
    imported-symbol residue this test exists to keep out."""
    return [ln for ln in c.splitlines()
            if needle in ln
            and 'sort: unavailable in compiled mode' not in ln]

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
        # have emitted a callable weak stub for it. (The preamble's one
        # documented prelude-`sort` weak stub is not residue: see
        # `_residue_lines`.)
        assert not _residue_lines(ci, 'unavailable in compiled mode'), \
            '\n'.join(_residue_lines(ci, 'unavailable in compiled mode'))
        assert not _residue_lines(ci, 'unavailable')
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


STDLIB_SRC = """\
def locate():
    # Function-scoped import of a module-level STRING global from a compiler
    # sibling: `module_loader.py` has `STDLIB_PATH = _find_stdlib_path()`, an
    # unannotated RHS whose callee is annotated `-> str`. This is the measured
    # shape from cas._stdlib_fingerprint (cas.py).
    from module_loader import STDLIB_PATH
    return STDLIB_PATH
"""


def test_function_scoped_str_global_reads_accessor_not_stub():
    # Red before the fix: the importer had no export for `STDLIB_PATH`, so the
    # separate compile declared `extern int64_t STDLIB_PATH (...)` and read it
    # through `_funcptr_STDLIB_PATH` -- the weak "unavailable in compiled mode"
    # stub in the closure dump. The defining module's `char *` accessor exists
    # (`module_loader__mojo_global_get_STDLIB_PATH`), so reads must use it.
    import gimple_codegen
    root = os.path.join(HERE, 'build', 'test_imported_global_stub')
    os.makedirs(root, exist_ok=True)
    td = tempfile.mkdtemp(prefix='probe_', dir=root)
    try:
        path = os.path.join(td, 'types.py')
        with open(path, 'w') as f:
            f.write(STDLIB_SRC)
        sep = gimple_codegen.compile_to_gimple(
            STDLIB_SRC, do_imports=False, filename=path)
        assert '_funcptr_STDLIB_PATH' not in sep, sep
        assert 'extern int64_t STDLIB_PATH' not in sep, sep
        assert not _residue_lines(sep, 'unavailable in compiled mode'), \
            '\n'.join(_residue_lines(sep, 'unavailable in compiled mode'))
        assert 'module_loader__mojo_global_get_STDLIB_PATH' in sep, sep
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_py_str_literal_global_is_read_through_accessor():
    # Before the fix, a compiler-module `NAME = 'x'` (no annotation) was left
    # unexported, so an importer declared nothing for it and read
    # `(int64_t)0` -- a silent NULL where the string belongs. `cas.ABI_VERSION`
    # is the real instance: the definer's accessor is `char *`.
    import gimple_codegen
    src = ('from cas import ABI_VERSION\n\n'
           'def f(x):\n'
           '    return ABI_VERSION\n')
    root = os.path.join(HERE, 'build', 'test_imported_global_stub')
    os.makedirs(root, exist_ok=True)
    td = tempfile.mkdtemp(prefix='probe_', dir=root)
    try:
        path = os.path.join(td, 'uses.py')
        sep = gimple_codegen.compile_to_gimple(
            src, do_imports=False, filename=path)
        assert '(int64_t)0' not in sep, sep
        assert 'extern char * cas__mojo_global_get_ABI_VERSION (void);' in sep, sep
        assert '_t1 = cas__mojo_global_get_ABI_VERSION ();' in sep, sep
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_py_scalar_global_scanner_types_only_what_the_definer_types():
    # The `.py` export scan (module_loader.py) types a `NAME[: ANN] = RHS`
    # global exactly as the DEFINING module's accessor is typed, or leaves it
    # unexported. Its own compile is not run here (the scan is gated to the
    # compiler's directory); the rule is pinned directly.
    import module_loader as ml
    assert ml._ml_scalar_global("STDLIB_PATH = _find_stdlib_path()") == \
        ['STDLIB_PATH', '', '_find_stdlib_path()']
    assert ml._ml_scalar_global("NAME: str = 'x'") == ['NAME', 'str', "'x'"]
    # Not a plain scalar assignment: a union annotation, `==`, a `def`, a
    # tuple target. None of these may be exported.
    assert ml._ml_scalar_global("NAME: str | None = None") == []
    assert ml._ml_scalar_global("NAME == 1") == []
    assert ml._ml_scalar_global("def f():") == []
    assert ml._ml_scalar_global("A, B = 1, 2") == []
    exports = {
        '_find_stdlib_path': {'c_return_type': 'char *'},
        '_n': {'c_return_type': 'int64_t'},
    }
    # Unannotated: only a whole-RHS call to a same-file def with a pointer,
    # `char *` or `double` return qualifies.
    assert ml._ml_py_global_ctype('', '_find_stdlib_path()', exports) == 'char *'
    assert ml._ml_py_global_ctype('', '_n()', exports) == ''
    assert ml._ml_py_global_ctype('', 'undefined()', exports) == ''
    # A whole-RHS plain string literal is `char *` in the defining module too
    # (its accessor is `char *`); the importer must read it that way.
    assert ml._ml_py_global_ctype('', "'x'", exports) == 'char *'
    assert ml._ml_py_global_ctype('', '"x"', exports) == 'char *'
    assert ml._ml_py_global_ctype('', "'a' + b", exports) == ''
    assert ml._ml_py_global_ctype('', "'a' 'b'", exports) == ''
    assert ml._ml_py_global_ctype('', "'it''s'", exports) == ''
    assert ml._ml_py_global_ctype('', "'\\n'", exports) == ''
    # Annotated: the defining module's own accessor types.
    assert ml._ml_py_global_ctype('str', "'x'", {}) == 'char *'
    assert ml._ml_py_global_ctype('int', '1', {}) == 'int'
    assert ml._ml_py_global_ctype('bool', 'True', {}) == 'int'
    assert ml._ml_py_global_ctype('float', '1.0', {}) == 'double'
    assert ml._ml_py_global_ctype('list[int]', '[]', {}) == ''


if __name__ == '__main__':
    test_imported_global_has_no_function_stub()
    test_function_scoped_str_global_reads_accessor_not_stub()
    test_py_scalar_global_scanner_types_only_what_the_definer_types()
    test_py_str_literal_global_is_read_through_accessor()
    print('PASS')
