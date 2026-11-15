#!/usr/bin/env python3
"""The giant lowering functions have no movable `if` arms left.

`tools/extract_arm.py` moves one top-level `if` arm of a giant function into
its own top-level function and replaces it with a call.  It refuses an arm
that reads a name the parent has not bound on every path, binds a name the
parent reads later, or calls a nested function; a remaining `NO` arm is the
tool's own verdict that the arm cannot be moved, not a todo.

This pins the done state of the 2026-11-14/15 split (GIR.md, "Stage 6, arms
of the giant functions"): a fresh arm added to one of these functions, or one
of the already-extracted arms inlined back, makes this test fail.  The split
itself was verified by comparing generated C for a dump corpus byte for byte;
this test is the cheap shape check that state was not undone.

    python3 test_gimple_arms_extracted.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(ROOT, 'tools', 'extract_arm.py')
BACKEND = os.path.join(ROOT, 'mojo', 'backend_gimple')

# (file, function) rows of GIR.md's "Stage 6, arms of the giant functions".
PARENTS = [
    ('emit_methods.py', '_lower_dict_method'),
    ('emit_calls.py', '_lower_subscript'),
    ('emit_exprs.py', '_lower_IdentExpr'),
    ('emit_calls.py', '_lower_call'),
    ('emit_calls.py', '_lower_named_call'),
    ('emit_exprs.py', '_lower_MemberExpr'),
    ('emit_exprs.py', '_lower_binary_tail'),
    ('emit_methods.py', '_lower_struct_method_call'),
]

_TOTAL = re.compile(r'^(\d+) lines can be moved$')


def list_arms(path: str, parent: str):
    """(movable_line_count, unexpected_lines) from `extract_arm.py --list`.

    25 lines is the floor the bug doc measured the table with; the tool's
    default is 30, which would hide the 26-line `fromkeys` arm.
    """
    p = subprocess.run(
        [sys.executable, TOOL, '--list', path, parent, '25'],
        capture_output=True, text=True)
    if p.returncode != 0:
        return None, [f'{parent}: --list exited {p.returncode}: '
                      + (p.stderr or p.stdout).strip().split('\n')[-1]]
    lines = p.stdout.strip().split('\n')
    m = _TOTAL.match(lines[-1]) if lines else None
    if not m:
        return None, [f'{parent}: no "N lines can be moved" line: {lines[-1:]!r}']
    # Every remaining arm must be one the tool REFUSED ("NO (...)"), which is
    # the doc's other accepted end state; an unmarked line is an arm that can
    # still be moved and that the total should have counted.
    odd = [l for l in lines[:-1] if ' NO (' not in l]
    return int(m.group(1)), odd


def main() -> int:
    failures = []
    checks = 0
    for filename, parent in PARENTS:
        path = os.path.join(BACKEND, filename)
        checks += 1
        if not os.path.exists(path):
            failures.append(f'{filename}: file is gone')
            continue
        total, odd = list_arms(path, parent)
        if total is None:
            failures.extend(odd)
        elif total != 0:
            failures.append(f'{filename}: {parent} still has {total} movable '
                            f'line(s)')
        elif odd:
            failures.append(f'{filename}: {parent}: '
                            + '; '.join(odd[:3]))
    for f in failures:
        print(f'FAIL: {f}')
    print(f'{checks - len(failures)}/{checks} passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
