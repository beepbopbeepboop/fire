#!/usr/bin/env python3
"""Regression test: an `enumerate` tuple-unpack target already typed `char *`
by an earlier use keeps its boxed-slot store on the variable the body reads.

Bug: bug:CODEGEN_unpack_loop_var_unified_to_char_star_loses_slot_store_cast.
In `_gen_for_enumerate`'s tuple-target branch (mojo/backend_gimple/
emit_loops.py) the write target was captured with `gen._cname(vname)` BEFORE
`_declare_var(vname, pair_elem, force=...)`, and `force` is true whenever the
name is already typed something else. That force call mints a fresh
`_shadowN_<name>` C identifier and re-points `_c_names` at it, so the store
kept writing the ORIGINAL variable. With an earlier `a = "seed"` (`char *`)
and a pair list whose slot type is only the `int64_t` default, the generated C
was:

    char * a;
    int64_t _shadow1_a;
    ...
    _t10 = mojo_list_get_int (_t8, 0);
    a = _t10;                 /* error: char * <- int64_t [-Wint-conversion] */
    ...
    print(..., _shadow1_a);   /* the body reads the never-assigned shadow */

gcc -fgimple rejects it. The fix captures the C name after the declaration.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from build_config import find_gcc  # noqa: E402
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S  # noqa: E402
from gimple_codegen import compile_to_gimple  # noqa: E402

RUNTIME = ROOT / 'runtime'

# `pairs` is a parameter, so its pair slots carry only the int64_t storage
# default; the earlier `a = "seed"` is what types the target `char *` before
# the loop (the whole-function-unification shape of the doc's instance).
SRC = '''def main(pairs):
    a = "seed"
    for i, (a, b) in enumerate(pairs):
        if a.startswith("a"):
            print(i, a)
main([("a", "1"), ("c", "2")])
'''


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        py = subprocess.run([sys.executable, '-c', SRC], capture_output=True,
                            text=True, timeout=RUN_TIMEOUT_S)
        if py.returncode != 0 or py.stdout != '0 a\n':
            print(f'FAIL: CPython on the fixture exited {py.returncode} '
                  f'printing {py.stdout!r} ({py.stderr[:400]}) — the fixture '
                  f'itself is wrong, not the compiler')
            return 1
        want = py.stdout

        c_text = compile_to_gimple(SRC)
        if not c_text or not c_text.strip():
            print('FAIL: compile_to_gimple produced no C')
            return 1

        # Non-vacuity: the forced rename must actually have happened, and the
        # slot stores must go to that shadow (not to the old `char * a`).
        m = re.search(r'int64_t (_shadow\d+_a);', c_text)
        if not m:
            print('FAIL: no int64_t shadow for `a` in the generated C — the '
                  'fixture did not exercise the force-rename path; the test '
                  'is vacuous')
            return 1
        shadow = m.group(1)
        if not re.search(r'\b' + re.escape(shadow) + r' = \w+;', c_text):
            print(f'FAIL: the unpack store does not write the shadow '
                  f'`{shadow}` the body reads')
            return 1

        c_file = os.path.join(td, 'main.c')
        exe = os.path.join(td, 'main')
        with open(c_file, 'w') as fh:
            fh.write(c_text)
        cc = subprocess.run(
            [find_gcc(), '-fgimple', '-Os', '-g',
             '-ftrivial-auto-var-init=zero', '-I', str(RUNTIME),
             '-o', exe, c_file, str(RUNTIME / 'fire_runtime.c')],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if cc.returncode != 0:
            print(f'FAIL: gcc -fgimple -Os -g -ftrivial-auto-var-init=zero '
                  f'rejected the C:\n{cc.stderr[:2000]}')
            return 1

        p = subprocess.run([exe], capture_output=True, text=True,
                           timeout=RUN_TIMEOUT_S)
        if p.returncode != 0 or p.stdout != want:
            print(f'FAIL: compiled program exited {p.returncode} printing '
                  f'{p.stdout!r}; CPython prints {want!r} '
                  f'({p.stderr[:400]})')
            return 1

    print(f'PASS: the enumerate unpack store writes the `{shadow}` shadow '
          f'the body reads; gcc accepts it and the program prints {want!r}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
