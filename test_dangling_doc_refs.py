#!/usr/bin/env python3
"""Tests for `tools/dangling_doc_refs.py --stale-verdicts`.

The checker reports a `bugs/` doc whose per-stem verdict-table row claims
something a fresh run does not produce (the instrument gap
`--stale-verdicts` closes: a verdict row that was never re-measured against a
fresh run).

The test's real job is the NEGATIVE CONTROL: a table with a deliberately
wrong row must be flagged, and a matching row must not, or the checker can
never fail and is not a checker. The freshness-of-truth half is exercised
with a stub `measure`, because running Lean per row is a manual campaign,
not a unit test.
"""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import dangling_doc_refs as d

TABLE = """
| — | `keeps` | `lean-rejected` | the one that agrees | some owner |
| — | `flips` | `PASS` | a present-tense claim | — |
| — | `flips2` | `lean-rejected` | another | — |
| — | `oldrow` | was `lean-rejected` | history, skipped | — |
| — | `unmeasured` | not measured | skipped | — |
| — | `varies` | **PASS (2026-10-05)** | a dated PASS claim | — |
"""


# The stems the fixture's "ledger" knows; `verdict_claims` only reads a row whose
# stem the ledger has, which is the one parser both the committed-ledger report
# and this fresh-run mode share.
LEDGER = {s: ('lean-rejected', None, False) for s in
          ('keeps', 'flips', 'flips2', 'oldrow', 'unmeasured', 'varies')}


class StaleVerdictRows(unittest.TestCase):
    def test_a_deliberately_wrong_row_is_the_one_reported(self):
        with tempfile.TemporaryDirectory() as td:
            doc = os.path.join(td, 'FORMAL_fixture.md')
            with open(doc, 'w') as f:
                f.write(TABLE)
            stub = {'keeps': 'fail', 'flips': 'fail', 'flips2': 'pass',
                    'varies': 'pass'}
            rows = d.stale_verdict_rows([doc], lambda s: stub[s], LEDGER)
            self.assertEqual(
                [(r[2], r[3], r[4]) for r in rows],
                [('flips', 'pass', 'fail'),
                 ('flips2', 'fail', 'pass')])

    def test_a_matching_row_is_not_reported(self):
        with tempfile.TemporaryDirectory() as td:
            doc = os.path.join(td, 'FORMAL_fixture.md')
            with open(doc, 'w') as f:
                f.write(TABLE)
            stub = {'keeps': 'fail', 'flips': 'pass', 'flips2': 'fail',
                    'varies': 'pass'}
            self.assertEqual(d.stale_verdict_rows([doc], lambda s: stub[s], LEDGER),
                             [])

    def test_verdict_claims_skips_historical_rows(self):
        claims = list(d.verdict_claims(TABLE, LEDGER))
        self.assertEqual(
            sorted((s, c) for _n, s, c in claims),
            [('flips', 'proved'), ('flips2', 'lean-rejected'),
             ('keeps', 'lean-rejected'), ('varies', 'proved')])


    def test_stale_baseline_entries_reports_file_with_zero_citations(self):
        """Regression for MERGE_formal58: stale_baseline_entries must see
        a file whose citations were all fixed (absent from by_file)."""
        synth = {'a.py': [('X.md', 1)], 'b.py': [('Y.md', 1), ('Z.md', 2)],
                 'c.py': [], 'd.py': [('W.md', 3)]}
        synth = {rel: cites for rel, cites in synth.items() if cites}
        led = {'a.py': 1, 'b.py': 1, 'c.py': 2, 'd.py': 4}
        result = d.stale_baseline_entries(synth, led)
        self.assertEqual(result, {'c.py': (0, 2), 'd.py': (1, 4)})
        self.assertIn('c.py', result)
        self.assertEqual(result['c.py'], (0, 2))

    def test_deleted_bug_doc_specific_citations_rewritten(self):
        _, by_doc, by_file = d.find()
        # The two citations this bug named must be rewritten by symptom,
        # not by deleted doc path (see the deleted bug doc for context).
        gone = {('test_formal_hashlib.py', 'FORMAL_arm64_lsl_imm_is_wrong_for_'
                 'every_amount_above_8.md'),
                ('test_formal_run.py', 'FORMAL_arm64_lsl_imm_is_wrong_for_every_'
                 'amount_above_8.md')}
        still = [f'{f}: {n}' for f, n in sorted(gone)
                 if any(n == d for _, d in by_file.get(f, ()))]
        self.assertEqual(still, [],
                         f'still cited by deleted doc path: {still}; '
                         'rewrite by symptom (commit or doc name)')


# The hard-bug index is hand-maintained prose, so nothing but these two checks
# ever compares it with the directory it indexes. Both were false at once on
# 2026-10-29: nine of the names it cited were deleted docs, and three live docs
# had no row at all.
HARD = os.path.join(HERE, 'bugs', 'hard')
HARD_INDEX = os.path.join(HARD, 'README.md')
DOC_NAME = re.compile(r'(?<![\w.-])([A-Za-z0-9_][A-Za-z0-9_.-]*\.md)(?![\w-])')


def _index_names():
    with open(HARD_INDEX) as f:
        return set(DOC_NAME.findall(f.read()))


class HardIndexIsTrue(unittest.TestCase):
    def test_every_doc_the_index_names_exists(self):
        homes = (HARD, os.path.join(HERE, 'bugs'), HERE)
        missing = sorted(n for n in _index_names()
                         if not any(os.path.exists(os.path.join(h, n)) for h in homes))
        self.assertEqual(missing, [])

    def test_every_hard_doc_is_indexed(self):
        on_disk = {f for f in os.listdir(HARD)
                   if f.endswith('.md') and f != 'README.md'}
        self.assertEqual(sorted(on_disk - _index_names()), [])


if __name__ == '__main__':
    unittest.main()
