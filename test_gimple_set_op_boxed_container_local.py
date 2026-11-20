#!/usr/bin/env python3
"""Regression: a set-typed loop target whose element type the codegen could
not name must still be lowered as the boxed container WORD for a set
operation, not as a boxed SCALAR.

Symptom this pins (bootstrap-stage2-cc, 2026-11-18): in
`mojo/middle/coro.py`'s `_scan_callsite_param_kinds._classify` the loop target
`kinds` (`for pname, kinds in slot.items():`, where the dict value type was
lost so the target is the boxed word) lowered `None in kinds` correctly via
`_get_actual_type` -> `(MojoSet *)kinds`, but `kinds - {None}` -- the set
difference on the same line -- first ran the "boxed operand" arm, which reads
a `_boxed_vals` word as a boxed SCALAR:
`mojo_box_double(kinds)` cast to `MojoSet *`, a hard gcc "invalid types in
conversion to integer". The binary-operator path and the `in` path disagreed
on one variable's spelling.

`_lower_binary_tail` now recovers the container kind (`_resolve_container_kind`,
the same recovery `_lower_in_dispatch` uses) before the boxed-operand arms.

Run:  python3 test_gimple_set_op_boxed_container_local.py
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

SRC = '''
def classify(seen: Dict[String, Dict[String, Set[String]]]) -> Int64:
    resolved = 0
    for gname, slot in seen.items():
        for pname, kinds in slot.items():
            kinds = _merge_list_holes(kinds)
            if None in kinds and len(kinds - {None}) > 1:
                resolved = resolved + 1
            if len(kinds - {None}) > 0:
                resolved = resolved + 2
    return resolved

def _merge_list_holes(kinds: Set[String]) -> Set[String]:
    return kinds

def main():
    d = {}
    inner = {}
    inner["a"] = {"x", "y"}
    d["g"] = inner
    print(classify(d))

main()
'''


def main():
    failures = []
    with tempfile.TemporaryDirectory() as td:
        entry = os.path.join(td, 'set_op.py')
        with open(entry, 'w') as fh:
            fh.write(SRC)
        c_src = gimple_codegen._run_pipeline(
            SRC, filename=entry, do_imports=True)[0]

        # The wrong spelling, named so a reintroduction reads clearly.
        if re.search(r'mojo_box_double \(kinds\)', c_src):
            failures.append('`kinds - {None}` boxes the set word as a double')

        c_file = os.path.join(td, 'set_op.c')
        with open(c_file, 'w') as fh:
            fh.write(c_src)
        cc = subprocess.run(
            [build_config.find_gcc(), '-fgimple', '-fsyntax-only', '-Os', '-g',
             '-ftrivial-auto-var-init=zero', f'-I{RUNTIME_INC}', c_file],
            capture_output=True, text=True, timeout=120)
        if 'invalid types in conversion' in cc.stderr:
            failures.append('gcc: ' + cc.stderr.strip()[:800])
        elif cc.returncode != 0:
            failures.append('gcc -fsyntax-only failed: ' + cc.stderr.strip()[:800])
        else:
            # The difference must still answer the set difference: one inner
            # set of two non-None members contributes the 0-or-1 branch plus
            # the two of the second -> 2.
            exe = os.path.join(td, 'set_op.exe')
            link = subprocess.run(
                [build_config.find_gcc(), '-fgimple', f'-I{RUNTIME_INC}',
                 '-o', exe, c_file, os.path.join(RUNTIME_INC, 'fire_runtime.c')],
                capture_output=True, text=True, timeout=180)
            if link.returncode != 0:
                failures.append('gcc link failed: ' + link.stderr.strip()[:800])
            else:
                run = subprocess.run([exe], capture_output=True, text=True,
                                     timeout=60)
                if run.returncode != 0 or run.stdout.strip() != '2':
                    failures.append(
                        f'expected "2", got rc={run.returncode} '
                        f'stdout={run.stdout!r} stderr={run.stderr!r}')

    if failures:
        for f in failures:
            print('FAIL  set_op_boxed_container_local:', f)
        return 1
    print('PASS  set_op_boxed_container_local')
    return 0


if __name__ == '__main__':
    sys.exit(main())
