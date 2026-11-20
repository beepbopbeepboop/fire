#!/usr/bin/env python3
"""Regression: `from M import C` for a CLASS must bind the class in EVERY
scope where the class's module is not re-inlined by this compile.

Two measured shapes on `bootstrap-stage2-cc`:

* ANCESTOR STILL MID-COMPILE — `x.py` (root) defines `class C` and imports
  `b.py`; `b.py`'s function does `from x import C; return C(3).get()`.
  `b` is compiled from `x`'s own import processing, so `x`'s struct pass
  (which registers the layout) has not run yet. Before the fix the import
  was registered as an imported FUNCTION: the call site emitted `C (3)`
  against the class's own `typedef struct C` in the same translation unit —
  a hard gcc error (`expected expression before 'C'`) — or, with a weak
  stub, a silently wrong value.
* SIBLING-SUBTREE COMPILED — `entry.py` imports `mid.py` and `reader.py`;
  `mid.py` does a top-level `from mod import C`, which compiles `mod.py` in
  MID's subtree; `reader.py`'s function does the same import. The layout is
  shared, but this gen's per-module method tables are not, so `C(3).get()`
  went through the dynamic `mojo_obj_call1` dispatch and printed `0`.
* The module-scope spelling of the same sibling shape (`from mod import C`
  at the top of two modules, only the first of which compiles `mod`) is the
  same bug in `_register_sym` and must print both values.

Fix: `_note_struct_import_alias` (mojo/middle/funcs_shared.py) treats the
UNALIASED spelling as a class binding too, confirming it against the named
module's own source and publishing the defining module's REAL parsed
StructDef + method signatures into this gen
(`_publish_imported_class` in mojo/backend_gimple/emit_funcs.py, driven
before the struct/inference passes by
`_gmp_publish_body_class_imports`). The module-scope path
(`_register_sym`) publishes method signatures even when the layout is
already in the shared table.

Run:  python3 test_gimple_class_import_cross_module.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc                       # noqa: E402
from gimple_codegen import compile_to_gimple            # noqa: E402

RUNTIME = os.path.join(HERE, 'runtime')
COMPILE_TIMEOUT_S = 180
RUN_TIMEOUT_S = 30

CLS = (
    'class C:\n'
    '    def __init__(self, v):\n'
    '        self.v = v\n'
    '    def get(self) -> Int:\n'
    '        return self.v\n'
)

CASES = [
    (
        'ancestor_mid_compile',
        {
            'x.py': (
                'import b as B\n'
                + CLS
                + 'def use() -> Int:\n'
                '    return B.f()\n'
                'def main():\n'
                '    print(use())\n'
                'main()\n'
            ),
            'b.py': (
                'def f() -> Int:\n'
                '    from x import C\n'
                '    return C(3).get()\n'
            ),
        },
        'x.py',
        '3\n',
    ),
    (
        'sibling_compiled_function_scope',
        {
            'mod.py': CLS,
            'mid.py': (
                'from mod import C\n'
                'def make() -> Int:\n'
                '    return C(7).get()\n'
            ),
            'reader.py': (
                'def f() -> Int:\n'
                '    from mod import C\n'
                '    return C(3).get()\n'
            ),
            'entry.py': (
                'import mid\n'
                'import reader\n'
                'def main():\n'
                '    print(reader.f())\n'
                'main()\n'
            ),
        },
        'entry.py',
        '3\n',
    ),
    (
        'sibling_compiled_module_scope',
        {
            'mod.py': CLS,
            'areader.py': (
                'from mod import C\n'
                'def a() -> Int:\n'
                '    return C(1).get()\n'
            ),
            'zmid.py': (
                'from mod import C\n'
                'def z() -> Int:\n'
                '    return C(2).get()\n'
            ),
            'entry.py': (
                'import areader\n'
                'import zmid\n'
                'def main():\n'
                '    print(areader.a())\n'
                '    print(zmid.z())\n'
                'main()\n'
            ),
        },
        'entry.py',
        '1\n2\n',
    ),
]


def build_and_run(name, files, entry, work):
    """Compile `entry` (importing the sibling `files`) and run it.
    Returns (generated C, stdout, gcc stderr)."""
    for rel, body in files.items():
        with open(os.path.join(work, rel), 'w') as f:
            f.write(body)
    entry_path = os.path.join(work, entry)
    with open(entry_path) as f:
        entry_src = f.read()
    c_src = compile_to_gimple(entry_src, do_imports=True, filename=entry_path)
    c_file = os.path.join(work, 'out.c')
    with open(c_file, 'w') as f:
        f.write(c_src)
    exe = os.path.join(work, 'out.exe')
    link = subprocess.run(
        [find_gcc(), '-fgimple', f'-I{RUNTIME}', '-o', exe, c_file,
         os.path.join(RUNTIME, 'fire_runtime.c')],
        capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    if link.returncode != 0:
        return c_src, None, link.stderr
    run = subprocess.run([exe], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT_S)
    return c_src, run.stdout, ''


def main():
    failures = []
    scratch = os.path.join(HERE, '.tmp',
                           'test_gimple_class_import_cross_module')
    os.makedirs(scratch, exist_ok=True)
    work = tempfile.mkdtemp(prefix='classxmod_', dir=scratch)
    try:
        for name, files, entry, expected in CASES:
            case_dir = os.path.join(work, name)
            os.makedirs(case_dir, exist_ok=True)
            c_src, got, stderr = build_and_run(name, files, entry, case_dir)
            if got is None:
                failures.append(f'{name}: gcc failed: {stderr.strip()[-800:]}')
                continue
            if 'unavailable in compiled mode' in c_src:
                failures.append(f'{name}: generated C contains an '
                                '"unavailable in compiled mode" stub')
            if got != expected:
                failures.append(f'{name}: expected {expected!r}, got {got!r}')
            # The constructor must be lowered, never a bare call to the
            # class name (the typedef makes that a gcc hard error).
            if re.search(r'^\s*_\w+ = C \(\d', c_src, re.M):
                failures.append(f'{name}: class name lowered as a function '
                                'call')
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        for f in failures:
            print('FAIL  class_import_cross_module:', f)
        return 1
    print('PASS  class_import_cross_module')
    return 0


if __name__ == '__main__':
    sys.exit(main())
