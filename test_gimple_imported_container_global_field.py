#!/usr/bin/env python3
"""Regression: a module-level container global imported through a
module-attribute binding (`_X = N._X`) must keep the SAME C field spelling
as its defining module — the boxed `int64_t` word — in the importing
module's struct, and the shared `_global_c_decl_types` entry must never
turn into the raw semantic pointer.

Symptom this pins (bootstrap-stage2-cc, gate red 2026-11-18): the definer
(`fire_compiler.py:3740`'s `_COMPTIME_TYPE_FUNCS = frozenset({...})`) froze
its struct field as the boxed `int64_t` word; the importer
(`ownership_check.py:163`'s `_COMPTIME_TYPE_FUNCS = N._COMPTIME_TYPE_FUNCS`)
declared its mirror field from the read's SEMANTIC answer `MojoSet *` and
wrote that raw pointer into the SHARED bare-name-keyed
`_global_c_decl_types` between the two modules' field-freezes. All three
seams then disagreed: the definer's store re-typed its RHS `MojoSet *`
against its frozen `int64_t` field, the import store met the inverse, and
the mirror's own `in` read loaded a pointer into the boxed-word slot the
set-membership lowering expects.

The module order is the production one on purpose: the OWNER's pass starts
first, its import walk reaches the IMPORTER, and the importer's declaration
scan runs while the owner's scan/freeze has NOT yet run — the
`_module_global_field_type` triple is absent, so the branch answers from
the owner's convention (plain containers box to `int64_t`; dispatch tables
stay raw). A flat 2-file repro compiles the owner first, finds the triple,
and does not exercise that fallback.

Run:  python3 test_gimple_imported_container_global_field.py
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
    # Owner: a plain set-literal module global (the definer's
    # `frozenset({...})` shape) plus an import of the importer, which pulls
    # the importer in during the owner's OWN pass — before the owner's
    # declaration scan — so the owner's `_module_globals` triple does not
    # exist yet when the importer's scan answers the mirror's field type.
    'aa.py': (
        '_X = {\'a\', \'b\'}\n'
        'import bb\n'
    ),
    # Importer: the module-attribute import of the owner's global, and a
    # module-level `in` use of its mirror (the gate's third seam).
    'bb.py': (
        'import aa as N\n'
        '_X = N._X\n'
        '\n'
        'def use(x):\n'
        '    return x in _X\n'
    ),
    # Entry: imports both so the root's compile loop takes them in sorted
    # order (aa first — the owner starts its pass first).
    'main.py': (
        'import aa\n'
        'import bb\n'
        '\n'
        'def main():\n'
        '    print(bb.use("a"))\n'
        '\n'
        'main()\n'
    ),
}


def main():
    failures = []
    with tempfile.TemporaryDirectory() as td:
        for rel, body in FILES.items():
            fp = os.path.join(td, rel)
            with open(fp, 'w') as fh:
                fh.write(body)
        entry = os.path.join(td, 'main.py')
        c_src = gimple_codegen._run_pipeline(
            FILES['main.py'], filename=entry, do_imports=True)[0]

        # 1. The importer's mirror field must be the boxed word, not the
        #    raw container pointer the pre-fix branch declared from the
        #    read's semantic answer.
        if re.search(r'MojoSet \* _X\s*;', c_src):
            failures.append(
                'importer declared the mirror global as a raw `MojoSet *` '
                'field instead of the owner\'s boxed `int64_t` word')
        if len(re.findall(r'(?m)^\s*int64_t _X\s*;', c_src)) < 2:
            failures.append(
                'expected BOTH modules\' structs to declare the boxed '
                '`int64_t _X;` field')

        # 2. gcc on the unit: no pointer/integer seam conversions.
        c_file = os.path.join(td, 'imported_container_global.c')
        with open(c_file, 'w') as fh:
            fh.write(c_src)
        cc = subprocess.run(
            [build_config.find_gcc(), '-fgimple', '-fsyntax-only', '-Os', '-g',
             '-ftrivial-auto-var-init=zero', f'-I{RUNTIME_INC}', c_file],
            capture_output=True, text=True, timeout=120)
        if 'int-conversion' in cc.stderr or 'makes pointer from integer' in cc.stderr \
                or 'makes integer from pointer' in cc.stderr:
            failures.append('gcc: ' + cc.stderr.strip()[:800])
        elif cc.returncode != 0:
            failures.append('gcc -fsyntax-only failed: ' + cc.stderr.strip()[:800])

    if failures:
        for f in failures:
            print('FAIL  imported_container_global_field:', f)
        return 1
    print('PASS  imported_container_global_field')
    return 0


if __name__ == '__main__':
    sys.exit(main())
