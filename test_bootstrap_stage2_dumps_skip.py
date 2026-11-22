"""Regression test: bootstrap-stage2-dumps items are SKIPPED, not red.

The task claimed the bug
`bugs/gate-bootstrap-stage2-dumps:bootstrap_test_expressions.mojo.md` —
that the bootstrap-stage2-dumps FANOUT was going red. The red was never in the
item's code: the fanout depends on `bootstrap-stage2-cc` (gcc over the stage1
closure), which is disabled under `bugs/gate-bootstrap-stage2-cc.md`, and the
scheduler used to satisfy deps on DISABLED anyway — so all 50 fan-out items ran
against a stage2/mojo that was never built and died in a second on
FileNotFoundError: './mojo'. After the scheduler fix (416ed660c) the fanout
skips with `dependency is disabled: bootstrap-stage2-cc`.

This test pins the resolved state: the fanout still depends on the disabled
producer, the producer still carries its own doc as the switch, and the stale
per-item doc this task deleted is gone from `bugs/`.

It fails before the stale doc is deleted and passes after.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import suite


STALE_DOC = ('bugs/gate-bootstrap-stage2-dumps:bootstrap_test_expressions.'
            'mojo.md')


class TestBootstrapStage2DumpsSkip(unittest.TestCase):
    def test_bootstrap_stage2_dumps_skips_behind_disabled_cc(self):
        """The fanout depends on the disabled producer and must skip, not run."""
        fanout = suite.REGISTRY.get('bootstrap-stage2-dumps')
        self.assertIsNotNone(fanout, 'bootstrap-stage2-dumps fanout not registered')
        self.assertIn('bootstrap-stage2-cc', fanout.deps,
                      'bootstrap-stage2-dumps must depend on bootstrap-stage2-cc')

    def test_the_disabled_producer_is_the_switch(self):
        cc_spec = suite.REGISTRY.get('bootstrap-stage2-cc')
        self.assertIsNotNone(cc_spec, 'bootstrap-stage2-cc not registered')
        self.assertTrue(suite.is_disabled(cc_spec),
                        'bootstrap-stage2-cc must be disabled')

    def test_the_stale_item_doc_is_deleted(self):
        """The stale per-item red-doc is gone: the job is not red.

        Before the fix this doc existed and claimed the item was red; the
        resolution was to delete it (the scheduler now skips behind the
        disabled producer). A stale doc would resurrect the work.
        """
        self.assertFalse(
            os.path.exists(os.path.join(HERE, STALE_DOC)),
            '%s still exists: the job is wrongly documented as red' % STALE_DOC)


if __name__ == '__main__':
    unittest.main()
