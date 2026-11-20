#!/usr/bin/env python3
"""Regression: a `from M import name` inside a CLASS/STRUCT METHOD body must
pull M into the translation unit, so the function-scoped import preamble's
extern has a definition to link against.

Symptom this pins (bootstrap-stage2-cc, 2026-11-18): `elaborate.py`'s
`Elaborator.elaborate_generic_struct` method does
`from mojo.middle.comptime_fn import resolve_struct_aliases`, and the
do_imports closure collector (`_collect_import_modules_rec` in
mojo/middle/module_shared.py) recursed into function bodies, if/try/loop
blocks but never into a `StructDef`'s methods. gcc compiled the call site
against the extern the import preamble declares, and the whole-closure build
failed at LINK with `_mojo_middle_comptime_fn_resolve_struct_aliases_37bd8e`
undefined. A compile-only check cannot see this: the extern is a valid
declaration.

Run:  python3 test_gimple_class_method_import_inlined.py
"""
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import build_config  # noqa: E402
import gimple_codegen  # noqa: E402

RUNTIME_INC = os.path.join(_HERE, 'runtime')

FILES = {
    'b.py': (
        'def get_set() -> Set[String]:\n'
        '    return {"type_of", "__type_of"}\n'
    ),
    'a.py': (
        'class C:\n'
        '    def m(self) -> Bool:\n'
        '        from b import get_set\n'
        '        s = get_set()\n'
        '        return "type_of" in s\n'
        '\n'
        'def main():\n'
        '    print(C().m())\n'
        '\n'
        'main()\n'
    ),
}


def main():
    failures = []
    with tempfile.TemporaryDirectory() as td:
        for rel, body in FILES.items():
            with open(os.path.join(td, rel), 'w') as fh:
                fh.write(body)
        entry = os.path.join(td, 'a.py')
        c_src = gimple_codegen._run_pipeline(
            FILES['a.py'], filename=entry, do_imports=True)[0]

        c_file = os.path.join(td, 'class_method_import.c')
        with open(c_file, 'w') as fh:
            fh.write(c_src)
        exe = os.path.join(td, 'class_method_import.exe')
        link = subprocess.run(
            [build_config.find_gcc(), '-fgimple', f'-I{RUNTIME_INC}',
             '-o', exe, c_file, os.path.join(RUNTIME_INC, 'fire_runtime.c')],
            capture_output=True, text=True, timeout=180)
        if link.returncode != 0:
            if 'undefined' in link.stderr or 'Undefined symbols' in link.stderr:
                failures.append('callee not inlined (link): '
                                + link.stderr.strip()[-800:])
            else:
                failures.append('gcc link failed: ' + link.stderr.strip()[:800])
        else:
            run = subprocess.run([exe], capture_output=True, text=True,
                                 timeout=60)
            if run.returncode != 0 or run.stdout.strip() != 'True':
                failures.append(
                    f'expected "True", got rc={run.returncode} '
                    f'stdout={run.stdout!r} stderr={run.stderr!r}')

    if failures:
        for f in failures:
            print('FAIL  class_method_import_inlined:', f)
        return 1
    print('PASS  class_method_import_inlined')
    return 0


if __name__ == '__main__':
    sys.exit(main())
