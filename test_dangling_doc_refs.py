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


class StaleVerdictRows(unittest.TestCase):
    def test_a_deliberately_wrong_row_is_the_one_reported(self):
        with tempfile.TemporaryDirectory() as td:
            doc = os.path.join(td, 'FORMAL_fixture.md')
            with open(doc, 'w') as f:
                f.write(TABLE)
            stub = {'keeps': 'fail', 'flips': 'fail', 'flips2': 'pass',
                    'varies': 'pass'}
            rows = d.stale_verdict_rows([doc], lambda s: stub[s])
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
            self.assertEqual(d.stale_verdict_rows([doc], lambda s: stub[s]),
                             [])

    def test_verdict_claims_skips_historical_rows(self):
        claims = list(d.verdict_claims(TABLE))
        self.assertEqual(
            sorted((s, c) for _n, s, c in claims),
            [('flips', 'pass'), ('flips2', 'fail'), ('keeps', 'fail'),
             ('varies', 'pass')])


if __name__ == '__main__':
    unittest.main()
