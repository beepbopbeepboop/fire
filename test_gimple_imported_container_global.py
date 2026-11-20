#!/usr/bin/env python3
"""Regression: a module-level global initialized from an IMPORTED module's
container global (`import owner as N; K = N.K`) must be declared the SAME C
way the owning module declares it -- one spelling in both globals structs --
and the boxed/raw choice must be the one the owner's own declaration made.

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
into the field and into `_global_c_decl_types` instead of the owner's
DECLARED field spelling. The invariant is ONE spelling, not "always boxed":
a plain container global is boxed `int64_t`, while a dispatch table named in
`dispatch_table_global_ctype` (since 44ba4f915 the three set-valued dispatch
globals `_COMPTIME_TYPE_FUNCS`, `_PURE_ITER_CALLS` and
`_COMPILE_TIME_INTRINSICS` are in that map) is declared RAW `MojoSet *` by
the owner, and the importer must follow. This test compiles the two-module
shape and requires gcc to accept it and the program to actually test
membership.

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

        # One C spelling: the importer's mirror field must carry the owner's
        # declared spelling, whichever convention that is (boxed `int64_t`
        # for a plain container, raw `MojoSet *` for a dispatch table).
        decls = re.findall(
            r'^\s*(int64_t|MojoSet \*) _COMPTIME_TYPE_FUNCS;', c_src, re.M)
        if len(decls) != 2 or len(set(decls)) != 1:
            failures.append(
                'expected BOTH module fields declared with ONE C spelling; '
                f'found {decls!r}')

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
