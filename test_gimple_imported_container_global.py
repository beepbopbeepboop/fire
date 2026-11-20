#!/usr/bin/env python3
"""Regression: a module-level global initialized from an IMPORTED module's
container global (`import owner as N; K = N.K`) must be declared the SAME C
way the owning module declares it -- a boxed `int64_t` word -- not as the raw
`MojoSet *` pointer.

Symptom this pins (bootstrap-stage2-cc, 2026-11-18): in the whole-closure
self-host translation unit `ownership_check.py`'s
`_COMPTIME_TYPE_FUNCS = N._COMPTIME_TYPE_FUNCS` was declared
`MojoSet * _COMPTIME_TYPE_FUNCS` while `fire_compiler.py`'s own declaration --
and the shared `_global_c_decl_types` every read/store path consults -- was
the boxed `int64_t`. gcc reported three errors at the seams: the owner's
`frozenset(...)` store ("assignment to 'int64_t' from 'MojoSet *'"), the
importer's store ("assignment to 'MojoSet *' from 'int64_t'") and the `in`
read ("assignment to 'int64_t' from 'MojoSet *'").

The declaration scan's module-attribute arm (`_gscan_declare_global` in
mojo/backend_gimple/module_gen.py) copied the owner's SEMANTIC pointer type
into the field and into `_global_c_decl_types`; every other container
declaration path in the same scan boxes to `int64_t` and keeps the semantic
type in `_global_var_types`. This test compiles the two-module shape and
requires gcc to accept it and the program to actually test membership.

Run:  python3 test_gimple_imported_container_global.py
"""
import os
import re
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import build_config  # noqa: E402
import gimple_codegen  # noqa: E402

RUNTIME_INC = os.path.join(_HERE, 'runtime')

FILES = {
    # The annotation on `_mk`'s return is what makes the owner's semantic
    # type a real `MojoSet *` before the reading module is scanned -- the
    # exact ordering the self-host closure has, where fire_compiler.py is
    # compiled before ownership_check.py's module-level store.
    'owner.py': (
        'def _mk() -> Set[String]:\n'
        '    return {"type_of", "__type_of"}\n'
        '\n'
        '_COMPTIME_TYPE_FUNCS = _mk()\n'
    ),
    'reader.py': (
        'import owner as N\n'
        '\n'
        '_COMPTIME_TYPE_FUNCS = N._COMPTIME_TYPE_FUNCS\n'
        '\n'
        'def uses(x: String) -> Bool:\n'
        '    return x in _COMPTIME_TYPE_FUNCS\n'
        '\n'
        'def main():\n'
        '    print(uses("type_of"))\n'
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
        entry = os.path.join(td, 'reader.py')
        c_src = gimple_codegen._run_pipeline(
            FILES['reader.py'], filename=entry, do_imports=True)[0]

        # One C spelling: the boxed word in BOTH modules' globals structs.
        n_boxed = len(re.findall(r'^\s*int64_t _COMPTIME_TYPE_FUNCS;', c_src, re.M))
        if n_boxed != 2:
            failures.append(
                'expected both module fields boxed as `int64_t`; found '
                f'{n_boxed} (raw pointer fields: '
                f'{len(re.findall(r"MojoSet [*] _COMPTIME_TYPE_FUNCS;", c_src))})')

        c_file = os.path.join(td, 'imported_container_global.c')
        with open(c_file, 'w') as fh:
            fh.write(c_src)
        cc = subprocess.run(
            [build_config.find_gcc(), '-fgimple', '-fsyntax-only', '-Os', '-g',
             '-ftrivial-auto-var-init=zero', f'-I{RUNTIME_INC}', c_file],
            capture_output=True, text=True, timeout=120)
        if 'int-conversion' in cc.stderr or 'makes pointer from integer' in cc.stderr:
            failures.append('gcc: ' + cc.stderr.strip()[:800])
        elif cc.returncode != 0:
            failures.append('gcc -fsyntax-only failed: ' + cc.stderr.strip()[:800])
        else:
            # The type agreement above is only half the claim: the boxed
            # field must still carry the OWNER's set through the store, so
            # the membership test answers True.
            exe = os.path.join(td, 'imported_container_global.exe')
            link = subprocess.run(
                [build_config.find_gcc(), '-fgimple', f'-I{RUNTIME_INC}',
                 '-o', exe, c_file, os.path.join(RUNTIME_INC, 'fire_runtime.c')],
                capture_output=True, text=True, timeout=180)
            if link.returncode != 0:
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
            print('FAIL  imported_container_global:', f)
        return 1
    print('PASS  imported_container_global')
    return 0


if __name__ == '__main__':
    sys.exit(main())
