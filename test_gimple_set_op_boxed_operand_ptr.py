#!/usr/bin/env python3
"""Regression: a set-typed loop local bound from a dict-items unpack and
used in a set operation (`kinds - {None}`) must keep its boxed WORD — the
boxed-operand arm of `_lower_binary_tail` must not unbox a pointer word as
a `double`.

Symptom this pins (bootstrap-stage2-cc, `mojo/middle/coro.py:6387` in
`_scan_callsite_param_kinds`): a dict-items pair loop reads BOTH slot
values BOXED (`mojo_list_get_boxed` — the slot's kind is a run-time fact),
so a slot that stores a container pointer hands back the raw pointer word
tagged with its pointer kind in `_actual_types`. The set-difference
`kinds - {None}` then hit the boxed-operand arm's `else` case, which
unboxed the word with `mojo_box_double` — reading a 64-bit pointer as an
IEEE-754 double — and gcc refused the double->pointer conversion
(`invalid types in conversion to integer`). The fix skips that unbox when
the word's RECORDED kind is a pointer: lossless, because
`mojo_box_double` of a non-box answers `(double)v` anyway for arithmetic
consumers, and the container-kind resolution recovers the pointer kind
from `_actual_types` for the operator.

Run:  python3 test_gimple_set_op_boxed_operand_ptr.py
"""
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import build_config  # noqa: E402
import gimple_codegen  # noqa: E402
from exec_budget import COMPILE_TIMEOUT_S  # noqa: E402

RUNTIME_INC = os.path.join(_HERE, 'runtime')

SRC = (
    'def merge_holes(kinds) -> set:\n'
    '    return kinds\n'
    '\n'
    'def classify(slot):\n'
    '    for pname, kinds in slot.items():\n'
    '        kinds = merge_holes(kinds)\n'
    '        if (None in kinds or len(kinds - {None}) > 1):\n'
    '            pass\n'
    '\n'
    'def main():\n'
    '    print("ok")\n'
    '\n'
    'main()\n'
)


def main():
    failures = []
    with tempfile.TemporaryDirectory() as td:
        entry = os.path.join(td, 'repro.py')
        with open(entry, 'w') as fh:
            fh.write(SRC)
        c_src = gimple_codegen._run_pipeline(
            SRC, filename=entry, do_imports=False)[0]

        # 1. The set-difference must still be lowered (the fix must not
        #    suppress the operation), and it must NOT route the boxed
        #    pointer word through `mojo_box_double`: in this unit the only
        #    `mojo_box_double` the pre-fix arm emitted was the buggy one.
        if 'mojo_set_difference' not in c_src:
            failures.append('the set-difference lowering is missing entirely')
        if 'mojo_box_double' in c_src:
            for i, line in enumerate(c_src.splitlines(), 1):
                if 'mojo_box_double' in line:
                    failures.append(
                        f'boxed pointer word unboxed as a double at '
                        f'generated line {i}: {line.strip()}')
                    break

        # 2. gcc on the unit: no conversion errors.
        c_file = os.path.join(td, 'set_op_boxed.c')
        with open(c_file, 'w') as fh:
            fh.write(c_src)
        cc = subprocess.run(
            [build_config.find_gcc(), '-fgimple', '-fsyntax-only', '-Os', '-g',
             '-ftrivial-auto-var-init=zero', f'-I{RUNTIME_INC}', c_file],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if cc.returncode != 0:
            failures.append('gcc -fsyntax-only failed: ' + cc.stderr.strip()[:800])

    if failures:
        for f in failures:
            print('FAIL  set_op_boxed_operand_ptr:', f)
        return 1
    print('PASS  set_op_boxed_operand_ptr')
    return 0


if __name__ == '__main__':
    sys.exit(main())
