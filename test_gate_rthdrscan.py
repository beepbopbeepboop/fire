#!/usr/bin/env python3
"""Regression pin for bug:gate-rthdrscan — the `rthdrscan` gate job.

The bug: the gate's rthdrscan job was red because `runtime/fire_runtime.h`
gained declarations that no rung of the census ladder in
`test_runtime_header_scan.py` accounted for, so every quoted figure in the
tree (FORMAL.md, the `formal/` docstrings) drifted from the live scan — and
the job was then switched off with `disabled='bugs/gate-rthdrscan.md'` rather
than fixed.

The fix (earlier on this branch, `10b735c35`): the 822 -> 826 rung, `--fix`
rewriting the quoted figures, the `disabled=` removed from the job's
registration, and this doc deleted. Deleting the doc while the job was not
verified green is what bug-gate-rthdrscan-3 is about; the doc was restored
with a `## Done when` section until the named test passed, and is deleted in
the commit that deletes it. This pin holds the two end-state facts that must
not drift back:

1. the `rthdrscan` registration in tools/suite.py stays in the registry and
   carries no `disabled=` — a red job is fixed or declared, never switched
   off silently;
2. bugs/gate-rthdrscan.md stays deleted — its existence means "the job is
   red", so its presence next to a green job would make the queue lie.

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
    m = re.search(r"test\('rthdrscan'.*?desc=", text, re.S)
    assert m is not None, 'rthdrscan is not registered in tools/suite.py'
    assert "disabled=" not in m.group(0), (
        'rthdrscan carries disabled= again — see bugs/gate-rthdrscan.md '
        '(the job is either fixed and enabled, or declared with a live bug doc)')


def test_gate_rthdrscan_doc_is_deleted():
    assert not os.path.exists(os.path.join(HERE, 'bugs', 'gate-rthdrscan.md')), (
        'bugs/gate-rthdrscan.md exists — the queue still says the rthdrscan '
        'job is red; delete it in the commit where the named test passes')


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
