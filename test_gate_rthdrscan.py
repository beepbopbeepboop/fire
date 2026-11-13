#!/usr/bin/env python3
"""Regression pin for bug:gate-rthdrscan — the `rthdrscan` gate job.

The bug: the gate's rthdrscan job was red because `runtime/fire_runtime.h`
gained declarations that no rung of the census ladder in
`test_runtime_header_scan.py` accounted for, so every quoted figure in the
tree (FORMAL.md, the `formal/` docstrings) drifted from the live scan — and
the job was then switched off with a `disabled=` marker rather than fixed.

The census side of the fix is master's: the ladder rung 826 -> 829 and the
quoted figures were re-synced on master by 124c89a3d, after the runtime grew
three declarations. What remained on master was the switch-off: the gate
ledger commit 77571e08c put `disabled=` back on the job while it was red, and
nothing took it off again once the census was green. Removing that marker and
deleting the bug doc is the closing change. Verified on master + this commit
(a scratch merge, not this branch alone: this branch's runtime predates the
three declarations, so its own ladder is red until it is integrated).

This pin holds the two end-state
facts that must not drift back:

1. the `rthdrscan` registration in tools/suite.py stays in the registry and
   carries no `disabled=` — a red job is fixed or declared, never switched
   off silently;
2. the bug's doc stays deleted — its existence means "the job is red", so
   the queue must not say that once the job is green (the check builds the
   path; the commit that closed the bug is the one that removed the marker and doc).

Next to `test_runtime_header_scan.py`, whose own checks are the evidence for
the census figures; this file pins only the gate wiring. Not registered in
tools/suite.py.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def test_rthdrscan_job_is_registered_and_not_disabled():
    text = open(os.path.join(HERE, 'tools', 'suite.py'), encoding='utf-8').read()
    # The registration runs from `test('rthdrscan'` to the next top-level
    # `test(` call. Matching only up to `desc=` would miss a `disabled=`
    # argument written after it, which is where the marker lives.
    m = re.search(r"test\('rthdrscan'.*?(?=\ntest\()", text, re.S)
    assert m is not None, 'rthdrscan is not registered in tools/suite.py'
    assert "disabled=" not in m.group(0), (
        'rthdrscan carries disabled= again — see the bug named '
        'bug:gate-rthdrscan (an enabled-green job or a declared red with a '
        'live bug doc; never a silent switch-off)')


def test_gate_rthdrscan_doc_is_deleted():
    doc = os.path.join(HERE, 'bugs', 'gate-rthdrscan.md')
    assert not os.path.exists(doc), (
        'the gate-rthdrscan bug doc exists — the queue still says the '
        'rthdrscan job is red; it belongs to the commit where the named '
        'test passes, not the tree')


if __name__ == '__main__':
    failures = 0
    for fn in (test_rthdrscan_job_is_registered_and_not_disabled,
               test_gate_rthdrscan_doc_is_deleted):
        try:
            fn()
            print(f'PASS  {fn.__name__}')
        except AssertionError as e:
            failures += 1
            print(f'FAIL  {fn.__name__}: {e}')
    print(f'\n{2 - failures} passed, {failures} failed, 2 checks')
    sys.exit(1 if failures else 0)
