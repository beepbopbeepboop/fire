#!/usr/bin/env python3
"""Regression: a FUNCTION-SCOPED non-aliased import bound inside a CLASS
METHOD (`from sub import f` in a method body) must let the import-extern
preamble declare the SAME mangled C name the call site uses, even though
the preamble (`gen_module`'s import-extern stub pass) runs AFTER the
function scope that bound the import has been popped.

Symptom this pins (bootstrap-stage2-cc, `module_loader.ModuleLoader.
_mojo_type_to_c`'s `from mojo.middle.types import param_annotation_ctype`):
the call site, emitted while the function scope is live, hashes the
definer's parameter list and calls `..._9f63a2`; the preamble, running
after the scope pop, found no home binding at any tier (function-scoped
imports record a scope-frame binding only, `record_flat=False`) and
declared the symbol UNSUFFIXED (or left the scanned `(void)` shape), so
gcc reports `implicit declaration of function '..._9f63a2'` at the call
(and `conflicting types` against the definer's suffixed definition
whenever that lands later in the unit). The fix teaches the param half
(`_imported_def_pts`) the same last-resort tier the name half already had:
the symbol's own import entry carries the home module, and the
whole-program store keyed by that qualifier holds exactly the list the
call site hashed while the frame was live.

The import sits in a class METHOD on purpose: the do_imports closure
collector (`_collect_import_modules_rec`) does not recurse into struct/class
bodies, so the defining module is never inlined by the importer — the
definer's own definition cannot precede the call and "declare" the symbol,
which is exactly why the production shape fails while a top-level
function-scoped import in a small TU is masked.

Run:  python3 test_gimple_function_scoped_import_extern.py
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
from exec_budget import COMPILE_TIMEOUT_S  # noqa: E402

RUNTIME_INC = os.path.join(_HERE, 'runtime')

FILES = {
    # The definer: a sibling module reached by a NON-ALIASED import that is
    # scoped to a method body. The parameter is deliberately unannotated:
    # the importer-side text scan drops it (the same scan `module_loader`
    # runs on `param_annotation_ctype(ann)`), so the entry's parameter list
    # is empty and only the whole-program store knows the real one.
    'sub.py': (
        'def f(x) -> String:\n'
        '    return "v" + String(x)\n'
    ),
    'main.py': (
        'class M:\n'
        '    def go(self):\n'
        '        from sub import f\n'
        '        return f(3)\n'
        '\n'
        'def main():\n'
        '    print("ok")\n'
        '\n'
        'main()\n'
    ),
}


def _compile_single_tu(entry_src, entry_path):
    return gimple_codegen._run_pipeline(
        entry_src, filename=entry_path, do_imports=True)[0]


def main():
    failures = []
    with tempfile.TemporaryDirectory() as td:
        for rel, body in FILES.items():
            fp = os.path.join(td, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, 'w') as fh:
                fh.write(body)
        entry = os.path.join(td, 'main.py')
        c_src = _compile_single_tu(FILES['main.py'], entry)

        # The call site inside M.go: the name the call is emitted under.
        m = re.search(r'_t1 = (\w+) \(_t2\)', c_src)
        if not m:
            failures.append('could not find the call to f inside M.go')
        else:
            callee = m.group(1)
            # 1. Some declaration or definition must name the symbol the
            #    call site uses — a suffixed callee with only an unsuffixed
            #    extern (or vice versa) is exactly the pre-fix shape.
            if not re.search(
                    r'(?:extern\s+)?[\w *]+\s*%s\s*\(' % re.escape(callee),
                    c_src):
                failures.append(
                    f'no declaration or definition names the call-site '
                    f'symbol `{callee}`')

        # 2. gcc on the unit: no implicit declaration, no conversions.
        c_file = os.path.join(td, 'import_extern.c')
        with open(c_file, 'w') as fh:
            fh.write(c_src)
        cc = subprocess.run(
            [build_config.find_gcc(), '-fgimple', '-fsyntax-only', '-Os', '-g',
             '-ftrivial-auto-var-init=zero', f'-I{RUNTIME_INC}', c_file],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if 'implicit declaration' in cc.stderr or 'int-conversion' in cc.stderr \
                or 'makes pointer from integer' in cc.stderr:
            failures.append('gcc: ' + cc.stderr.strip()[:800])
        elif cc.returncode != 0:
            failures.append('gcc -fsyntax-only failed: ' + cc.stderr.strip()[:800])

    if failures:
        for f in failures:
            print('FAIL  function_scoped_import_extern:', f)
        return 1
    print('PASS  function_scoped_import_extern')
    return 0


if __name__ == '__main__':
    sys.exit(main())
