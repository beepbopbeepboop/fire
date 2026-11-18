#!/usr/bin/env python3
"""Regression pin for the DROP decision on the LAND gate-formal-doc-truth-2 bug (its doc was deleted).

The doc asked whether the finished branch `work/bug-gate-formal-doc-truth-2`
(tip 73cbb4d6f, 3 commits, 1195 behind master) should land. Assessed
2026-11-17 (findings recorded in the doc's Status before the drop): every
commit is already on master, so the decision was DROP — land nothing,
delete the doc.

  * de7c6f5d2, "parser: terminate a bracket-default sub-stream with EOF"
    (a bracket-parameter default ending in a STRING left the implicit-
    concatenation loop in `_parse_primary` spinning forever: 35 GB of
    footprint, 90 GB of swap), landed on master as d7067e347 with its
    regression test (test_new_syntax_parsing.py::test_string_default_ends_
    its_sub_stream; 157 passed, 0 failed, measured 2026-11-17).
  * 1da620e5e, "memcap/memslot: measure phys_footprint, not RSS" (macOS
    compresses and swaps cold dirty pages out of RSS, so no RSS ceiling
    ever fired), landed on master as 9fe0a5c51 (edcdda146 re-measured the
    suite's memory classes for it); the branch tip's tools/procrun.py,
    tools/memcap.py and test_procrun.py are byte-identical to master's
    (22 tests passed, measured 2026-11-17).
  * 73cbb4d6f, "formal-doc-truth: re-sync the ABI census and re-enable
    both census jobs", is superseded: master re-synced the same drift in
    51ce6283b and has since moved further — FORMAL.md publishes 947 entry
    points / 435 word-shaped (45.9%) against the branch's 932 / 426
    (45.7%), and the ladder rungs have passed the branch's 822 rung
    (822 -> 826 -> 829 -> ...). Both jobs are registered in tools/suite.py
    without a disabled= marker, and their test files pass on master
    (test_formal_doc_truth.py PASS=454 FAIL=0, test_runtime_header_scan.py
    84 passed 0 failed, measured 2026-11-17).

Landing the tip would REGRESS the census (947 -> 932), re-add the stale
822 ladder rung and the pre-932 quoted figures, and lose 1195 commits of
master's other work in tools/suite.py and fire_compiler.py (5 files
conflict). The branch's own deletions of the gate docs are stale:
the rthdrscan gate bug is retired on master (6cd1368ca), and
the formal-doc-truth gate bug was re-filed (b3fe558b2) when the gate went
red again on another branch — that red was tracked in its own doc, deleted
with its fix, which this decision leaves alone. The branch tip stays in
refs/archive/work/bug-gate-formal-doc-truth-2, so dropping it loses
nothing.

This pin holds the decision's end-state facts, so a red means the DROP
was wrong in a way worth re-deciding:

1. the landing doc stays deleted — its existence means "the decision is
   pending"; this test FAILED while the doc was in the tree and passes
   from the drop commit (its own commit);
2. the parser's bracket-default sub-stream still terminates with an EOF
   token inside `_parse_bracket_param_default` (de7c6f5d2's fix is on
   master);
3. procrun still measures phys_footprint via proc_pid_rusage
   (1da620e5e's fix is on master);
4. the formal-doc-truth and rthdrscan jobs stay registered without
   disabled= (73cbb4d6f's goal, achieved on master by newer re-syncs; a
   red census job is fixed or declared with a live bug doc, never
   switched off silently).

Named for the per-bug pin family (test_suite.py's _DECLARED_BY_RULE), so
it runs by `python3 test_regress_land_gate_formal_doc_truth_2.py` without
a suite registration.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# The sentence the fix added inside _parse_bracket_param_default
# (d7067e347 on master).
PARSER_EOF_MARKER = "The span is a sub-stream: terminate it with an EOF token"


def _read(relpath):
    with open(os.path.join(HERE, relpath), encoding='utf-8') as f:
        return f.read()


def test_land_doc_is_deleted():
    doc = os.path.join(HERE, 'bugs', 'LAND-gate-formal-doc-truth-2.md')  # deliberate: pins that this doc stays deleted
    assert not os.path.exists(doc), (
        'the land doc exists — the DROP decision for '
        'work/bug-gate-formal-doc-truth-2 is undone. The branch is '
        'superseded by master (see the docstring) and belongs to the drop '
        'commit, not the tree')


def test_parser_bracket_default_sub_stream_terminates_with_eof():
    src = _read('fire_compiler.py')
    m = re.search(r"def _parse_bracket_param_default\(self\):.*?(?=\n    def )",
                  src, re.S)
    assert m is not None, (
        '_parse_bracket_param_default is gone from fire_compiler.py')
    assert PARSER_EOF_MARKER in m.group(0), (
        'the bracket-default sub-stream no longer ends in an EOF token — '
        'the pre-fix `_parse_primary` loop spins forever on a STRING-ending '
        'default (35 GB of footprint; de7c6f5d2, landed as d7067e347)')


def test_procrun_measures_phys_footprint():
    src = _read('tools/procrun.py')
    assert 'def footprint_kb(' in src, (
        'tools/procrun.py no longer carries footprint_kb — memcap/memslot '
        'would read RSS again, which macOS compresses and swaps out of '
        'sight (1da620e5e, landed as 9fe0a5c51)')
    assert 'proc_pid_rusage' in src, (
        'footprint without proc_pid_rusage: the libproc read and its '
        'None-never-0 fallback discipline are documented in procrun.py')


def _job_block(name):
    text = _read('tools/suite.py')
    m = re.search(r"test\('" + re.escape(name) + r"'.*?(?=\ntest\()", text, re.S)
    assert m is not None, f'{name} is not registered in tools/suite.py'
    return m.group(0)


def test_census_jobs_are_registered_and_not_disabled():
    for name in ('formal-doc-truth', 'rthdrscan'):
        block = _job_block(name)
        assert 'disabled=' not in block, (
            f'{name} carries disabled= again — the branch this doc assessed '
            're-enabled exactly these two jobs because they had been '
            'switched off while red (an enabled-green job or a declared '
            'red with a live bug doc; never a silent switch-off)')


if __name__ == '__main__':
    tests = (test_land_doc_is_deleted,
             test_parser_bracket_default_sub_stream_terminates_with_eof,
             test_procrun_measures_phys_footprint,
             test_census_jobs_are_registered_and_not_disabled)
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f'PASS  {fn.__name__}')
        except AssertionError as e:
            failures += 1
            print(f'FAIL  {fn.__name__}: {e}')
    print(f'\n{len(tests) - failures} passed, {failures} failed, {len(tests)} checks')
    sys.exit(1 if failures else 0)
