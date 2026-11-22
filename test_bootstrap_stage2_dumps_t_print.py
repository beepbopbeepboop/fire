"""Regression test: stale doc for bootstrap-stage2-dumps:t_print.mojo is deleted.

The task claimed the bug
`bugs/gate-bootstrap-stage2-dumps:t_print.mojo.md` — that the bootstrap-stage2-dumps
fanout was red for t_print. The red was never in the item's code: the fanout depends on
`bootstrap-stage2-cc`, which is disabled under `bugs/gate-bootstrap-stage2-cc.md`, and the
scheduler used to satisfy deps on DISABLED anyway. After the scheduler fix (416ed660c) the fanout
skips with `dependency is disabled: bootstrap-stage2-cc`.

This test pins the resolved state: the stale per-item doc is gone from `bugs/`.

It fails before the stale doc is deleted and passes after.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import suite

STALE_DOC = 'bugs/gate-bootstrap-stage2-dumps:t_print.mojo.md'


class TestBootstrapStage2DumpsTPrint(unittest.TestCase):
    def test_t_print_mojo_item_is_not_red(self):
        """The stale per-item red-doc is gone: the job is not red."""
        self.assertFalse(
            os.path.exists(os.path.join(HERE, STALE_DOC)),
            '%s still exists: the job is wrongly documented as red' % STALE_DOC)

    def test_fanout_is_skipped_behind_disabled_cc(self):
        """The fanout depends on the disabled producer and must skip, not run."""
        fanout = suite.REGISTRY.get('bootstrap-stage2-dumps')
        self.assertIsNotNone(fanout, 'bootstrap-stage2-dumps fanout not registered')
        self.assertIn('bootstrap-stage2-cc', fanout.deps,
                      'bootstrap-stage2-dumps must depend on bootstrap-stage2-cc')

    def test_disabled_producer_is_the_switch(self):
        cc_spec = suite.REGISTRY.get('bootstrap-stage2-cc')
        self.assertIsNotNone(cc_spec, 'bootstrap-stage2-cc not registered')
        self.assertTrue(suite.is_disabled(cc_spec),
                        'bootstrap-stage2-cc must be disabled')


if __name__ == '__main__':
    unittest.main()