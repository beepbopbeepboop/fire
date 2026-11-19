#!/usr/bin/env python3
"""Pin: `a.b.f(...)` where `a.b` is a MODULE the module `a` imported must
lower as a call to `b`'s own `f`, not as a method call on `a`'s opaque
module marker.

Python makes a module attribute a module object whenever the module itself
did `import pkg.mod as name` (or `from pkg import mod`), so
`a.name.f(...)` reaches `f` in that module. This is the shape the
self-host closure's own source uses in `mojo/backend_gimple/
emit_resolve.py`:

    import gimple_codegen

    stmts, _ss_meta = gimple_codegen.gimple_gen_coro.lower(...)
    gimple_codegen.gimple_gen_coro.register(temp_gen, _ss_meta)

because `gimple_codegen.py` does `import mojo.middle.coro as
gimple_gen_coro`. Neither the submodule branch (`pkg/mod.py` does not
exist: the attribute is a module the base module imported) nor the
single-hop module branch (the receiver is `gimple_codegen.gimple_gen_coro`,
not a module alias of the file being compiled) could resolve it, so the
call fell through to the generic scalar-receiver dispatch:

    _t4 = string_lower (_t3);                    /* `lower` matches str.lower */
    _t8 = _t6;  /* int64_t.register() stubbed */ /* everything else */

both exit-0 silent wrong answers, and the weak `lower` / `mojo_register`
stubs the whole-closure dump counted.

Three fixtures, each built from the emitted C and compared with CPython:

  1. the ordinary package shape (`import pkg.hub as hub; hub.alias.lower`)
     — the generic two-hop branch;
  2. the compiler's own hub shape (`import gimple_probe_hub as
     gimple_codegen; gimple_codegen.gimple_gen_coro.lower`) at a path
     under this checkout, which is the self-host hub-strip branch. The
     `gimple_` module names are what makes that branch's "is this one of
     this compiler's sibling modules" predicate recognize the fixture;
     the branch itself is the one the closure takes;
  3. `from pkg3 import leaf` in a hub module, then `hub.leaf.tri(...)` —
     the `from ... import submodule` spelling of the same binding.

A direct check at the end is the exact closure source shape
(`gimple_codegen.gimple_gen_coro` -> `mojo.middle.coro`) plus a
from-imported CLASS (`Parser`), which must NOT resolve as a module.

Fixtures 2 and 3 must be moved by hand only if that predicate or the
import spelling changes; they are answering the same question for the same
source shape.

Run: python3 test_module_attr_module_call.py
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

PACKAGE_FILES = {
    'pkg/__init__.py': '',
    'pkg/leaf.py': 'def lower(x):\n    return x + 1\n\n'
                   'def register(y):\n    return y * 2\n',
    'pkg/hub.py': 'import pkg.leaf as alias\n',
    'main.py': 'import pkg.hub as hub\n\n'
               'def main():\n'
               '    print(hub.alias.lower(41))\n'
               '    print(hub.alias.register(21))\n\n'
               'main()\n',
}

HUB_FILES = {
    'gimple_probe_leaf.py': 'def lower(x):\n    return x + 1\n\n'
                            'def register(y):\n    return y * 2\n',
    'gimple_probe_hub.py': 'import gimple_probe_leaf as gimple_gen_coro\n',
    'gimple_codegen_client.py':
        'import gimple_probe_hub as gimple_codegen\n\n'
        'def main():\n'
        '    print(gimple_codegen.gimple_gen_coro.lower(41))\n'
        '    print(gimple_codegen.gimple_gen_coro.register(21))\n\n'
        'main()\n',
}

FROM_IMPORT_FILES = {
    'pkg3/__init__.py': '',
    'pkg3/leaf.py': 'def tri(x):\n    return x * 3\n',
    'pkg3/hub.py': 'from pkg3 import leaf\n',
    'main.py': 'import pkg3.hub as hub\n\n'
               'def main():\n'
               '    print(hub.leaf.tri(14))\n\n'
               'main()\n',
}


def _write_tree(td: str, files: dict) -> None:
    for rel, body in files.items():
        path = os.path.join(td, rel)
        os.makedirs(os.path.dirname(path) or td, exist_ok=True)
        with open(path, 'w') as f:
            f.write(body)


def _cpython_stdout(td: str, entry: str) -> str:
    env = dict(os.environ)
    env['PYTHONPATH'] = td + (os.pathsep + env['PYTHONPATH']
                              if env.get('PYTHONPATH') else '')
    r = subprocess.run([sys.executable, entry], capture_output=True,
                       text=True, cwd=td, env=env, timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def _build_and_run(ci: str, td: str) -> str:
    gcc = find_gcc()
    c_path = os.path.join(td, 'prog.ci')
    with open(c_path, 'w') as f:
        f.write(ci)
    c_o = os.path.join(td, 'prog.o')
    rt_o = os.path.join(td, 'fire_runtime.o')
    exe = os.path.join(td, 'prog.exe')
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


def _check(name: str, files: dict, entry_rel: str, root: str,
           expected: str) -> None:
    import gimple_codegen
    os.makedirs(root, exist_ok=True)
    td = tempfile.mkdtemp(prefix='probe_', dir=root)
    try:
        _write_tree(td, files)
        entry = os.path.join(td, entry_rel)
        assert _cpython_stdout(td, entry) == expected, name
        with open(entry) as f:
            src = f.read()
        ci = gimple_codegen.compile_to_gimple(
            src, do_imports=True, filename=entry)
        assert 'unavailable in compiled mode' not in ci, (
            name + ': ' + '\n'.join(
                ln for ln in ci.splitlines()
                if 'unavailable in compiled mode' in ln))
        # The two wrong lowerings the unresolved receiver produced: `lower`
        # matching str.lower, and `register` falling to the scalar-receiver
        # stub. Their absence is what makes the value assertion meaningful
        # rather than accidental.
        assert 'string_lower' not in ci, name + ': routed `lower` to str.lower'
        assert 'register() stubbed' not in ci, name + ': register was stubbed'
        assert _build_and_run(ci, td) == expected, name
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_compiler_hub_attribute_resolves():
    """The exact source shape the closure uses resolves to the module that
    defines `lower`/`register`, and a non-module attribute does not."""
    import gimple_codegen
    g = gimple_codegen.GimpleGen(do_imports=True)
    g._current_filename = os.path.join(
        HERE, 'mojo', 'backend_gimple', 'emit_resolve.py')
    assert g._module_attr_module('gimple_codegen', 'gimple_gen_coro') \
        == 'mojo.middle.coro'
    # `Parser` is a from-imported CLASS, not a submodule: `M.Parser.attr(...)`
    # is not a module attribute read and must keep the old fallback.
    assert g._module_attr_module('mojo.middle.types', 'Parser') is None


def test_module_attr_module_call():
    test_compiler_hub_attribute_resolves()
    root = os.path.join(HERE, 'build', 'test_module_attr_module_call')
    _check('package-alias', PACKAGE_FILES, 'main.py', root, '42\n42\n')
    _check('hub-alias', HUB_FILES, 'gimple_codegen_client.py', root, '42\n42\n')
    _check('from-imported-submodule', FROM_IMPORT_FILES, 'main.py', root,
           '42\n')


if __name__ == '__main__':
    test_module_attr_module_call()
    print('PASS')
