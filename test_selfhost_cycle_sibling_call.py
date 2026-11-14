#!/usr/bin/env python3
"""Done-when test for the "module-alias call to a sibling module's top-level
function resolves when the caller is compiled first" bug (GATE
red_recover-land 2026-11-02, part 1 — the whole-closure dump's
`CLOSURE_INCOMPLETE`; the parent umbrella doc under `bugs/hard/` names the
remaining parts).

A module-alias call to a top-level function of ANOTHER of this compiler's own
modules must resolve to that function's real mangled symbol regardless of
module generation order, including inside an import cycle. This is the
`emit_infra <-> emit_stmts` / `emit_infra -> emit_calls -> emit_exprs ->
emit_infra` shape the whole-closure dump hits: the caller is compiled before
the defining module, so the member is not in the caller's flat
`func_param_types`/`func_return_types` tables, and the self-host sibling branch
of `_lower_method_call` used to note only the function's HOME module
(`_note_own_func_home`) and re-dispatch the bare name. A bare name is
mangleable only when the SYMBOL itself is registered in `imported_symbols`,
and `import mojo.middle.bb as bb` registers the MODULE, not its members —
so the call lowered to the unqualified bare name and emitted a weak
`...: unavailable in compiled mode` stub that answered 0, exit 0.

The fix registers the member from the defining module's own parsed
FunctionDef (the same `_local_sibling_module_exports` /
`_resolved_export_entry` / `_register_imported_symbol` steps the generic
module-qualified branch already performs, shared through one helper).

The probe writes two mutually-importing `mojo/middle/*` modules plus a root
into a directory under `$TMPDIR`, compiles the root with
`compile_to_gimple(..., do_imports=True)`, and compares the built binary's
stdout against CPython's for the same three files.

Run: python3 test_selfhost_cycle_sibling_call.py
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

AA_SRC = """\
import mojo.middle.bb as bb


def _apriv(x):
    return x + 1


def a_pub(x):
    return x * 2


def a_use(x):
    return bb._bpriv(x)
"""

BB_SRC = """\
import mojo.middle.aa as aa


def _bpriv(x):
    return x + 2


def b_use(x):
    return aa._apriv(x)
"""

ROOT_SRC = """\
import mojo.middle.aa as aa
import mojo.middle.bb as bb


def main():
    print(aa.a_use(2))
    print(bb.b_use(0))
    print(aa.a_pub(4))


main()
"""


def _write_tree(td: str) -> str:
    for rel, src in (
            ('mojo/__init__.py', ''),
            ('mojo/middle/__init__.py', ''),
            ('mojo/middle/aa.py', AA_SRC),
            ('mojo/middle/bb.py', BB_SRC),
            ('root.py', ROOT_SRC),
    ):
        path = os.path.join(td, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(src)
    return os.path.join(td, 'root.py')


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
    c_path = os.path.join(td, 'root.ci')
    with open(c_path, 'w') as f:
        f.write(ci)
    c_o = os.path.join(td, 'root.o')
    rt_o = os.path.join(td, 'fire_runtime.o')
    exe = os.path.join(td, 'root.exe')
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


def test_selfhost_cycle_sibling_call():
    import gimple_codegen
    td = tempfile.mkdtemp(prefix='selfhost_cycle_sibling_',
                          dir=os.environ.get('TMPDIR') or None)
    try:
        root = _write_tree(td)
        expected = _cpython_stdout(td, root)
        assert expected == '4\n1\n8\n', expected
        with open(root) as f:
            ci = gimple_codegen.compile_to_gimple(
                f.read(), do_imports=True, filename=root)
        # No call site may fall back to the weak "unavailable" stub: that
        # stub is what lets the whole-closure dump link and produce a wrong
        # `.ci` (the parent doc's CLOSURE_INCOMPLETE).
        assert 'unavailable in compiled mode' not in ci, ci
        # Both cross-cycle call sites name the DEFINING module's mangled
        # symbol, not the bare name.
        assert 'mojo_middle_aa__apriv_' in ci, ci
        assert 'mojo_middle_bb__bpriv_' in ci, ci
        # A public sibling function keeps its path: one definition only, no
        # `conflicting types` from double registration.
        assert ci.count('mojo_middle_aa_a_pub_') >= 2, ci
        assert _build_and_run(ci, td) == expected
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    test_selfhost_cycle_sibling_call()
    print('PASS')
