#!/usr/bin/env python3
"""Regression: reading `N.SOME_CONTAINER_GLOBAL` off a module alias whose
owner is still MID-COMPILE must load the owner's globals-struct field, not
stub to literal 0.

Shape (the import cycle that makes the owner mid-compile): `a.py` imports
`b.py` at the top; `b.py` imports `a.py` and its function computes
`{'constrained'} | N._COMPTIME_TYPE_FUNCS`. `b` is compiled from `a`'s own
import processing, so `a`'s globals struct (registered at the END of `a`'s
`gen_module_impl`) does not exist yet when the read is lowered.

Before the fix `_lower_MemberExpr`'s `submod.GLOBAL` arm asked
`_module_global_field_type('a', '_COMPTIME_TYPE_FUNCS')`, got None, and
fell through every arm to the generic unresolved-module-attribute stub:

    _t = 0;  /* class attr N._COMPTIME_TYPE_FUNCS — UNRESOLVED import ... */

`mojo_set_union` guards NULL, so this compiled and ran and the union was
silently just the literal set — measured on the self-host closure as
`unknown_decl_check.py`'s `_COMPILE_TIME_INTRINSICS` losing `type_of` /
`__type_of`, so a compiled `fire`/`mojoc` refused real Mojo source the
interpreter accepted.

Fix: `_gmh_pending_module_global_field_type` (mojo/backend_gimple/
module_gen.py), called from that MemberExpr arm — the `submod.GLOBAL`
counterpart of `_lower_IdentExpr`'s `_imp_pending`. It answers only when
the owner is an ANCESTOR on the compile stack, its own source binds the
name at module level, and that declaration is provably a container (whose
field convention is the boxed `int64_t` word).

Run:  python3 test_gimple_module_global_pending_owner.py
"""
import os
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

FILES = {
    'a.py': (
        'import b as B\n'
        'def _mk() -> Set[String]:\n'
        "    return {'type_of', '__type_of'}\n"
        '_COMPTIME_TYPE_FUNCS = _mk()\n'
        'def uses() -> Bool:\n'
        '    return B.has_type_of()\n'
    ),
    'b.py': (
        'import a as N\n'
        'def has_type_of() -> Bool:\n'
        # The union is computed at CALL time on purpose: the owner's own
        # module-level assignment is registered before this expression would
        # run at RUNTIME, but the ownership question this pins is settled at
        # COMPILE time (`a` is mid-compile while `b` is lowered).
        "    _ALL = {'constrained'} | N._COMPTIME_TYPE_FUNCS\n"
        "    return 'type_of' in _ALL\n"
    ),
    'entry.py': (
        'import a as A\n'
        'def main():\n'
        '    print(A.uses())\n'
        'main()\n'
    ),
}


def main():
    failures = []
    scratch = os.path.join(HERE, '.tmp',
                           'test_gimple_module_global_pending_owner')
    os.makedirs(scratch, exist_ok=True)
    work = tempfile.mkdtemp(prefix='pendowner_', dir=scratch)
    try:
        for rel, body in FILES.items():
            with open(os.path.join(work, rel), 'w') as f:
                f.write(body)
        entry = os.path.join(work, 'entry.py')
        with open(entry) as f:
            entry_src = f.read()
        c_src = compile_to_gimple(entry_src, do_imports=True,
                                  filename=entry)
        if 'UNRESOLVED import' in c_src:
            failures.append('generated C still stubs the imported module '
                            'global (UNRESOLVED import)')
        if '_a_globals._COMPTIME_TYPE_FUNCS' not in c_src:
            failures.append('generated C does not read the owner\'s '
                            '_a_globals._COMPTIME_TYPE_FUNCS field')
        c_file = os.path.join(work, 'out.c')
        with open(c_file, 'w') as f:
            f.write(c_src)
        exe = os.path.join(work, 'out.exe')
        link = subprocess.run(
            [find_gcc(), '-fgimple', f'-I{RUNTIME}', '-o', exe, c_file,
             os.path.join(RUNTIME, 'fire_runtime.c')],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if link.returncode != 0:
            failures.append('gcc failed: ' + link.stderr.strip()[-800:])
        else:
            run = subprocess.run([exe], capture_output=True, text=True,
                                 timeout=RUN_TIMEOUT_S)
            if run.returncode != 0 or run.stdout.strip() != 'True':
                failures.append(
                    f'expected "True", got rc={run.returncode} '
                    f'stdout={run.stdout!r} stderr={run.stderr!r}')
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        for f in failures:
            print('FAIL  module_global_pending_owner:', f)
        return 1
    print('PASS  module_global_pending_owner')
    return 0


if __name__ == '__main__':
    sys.exit(main())
