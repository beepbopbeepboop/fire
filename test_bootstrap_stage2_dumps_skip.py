"""Regression test: bootstrap-stage2-dumps items are SKIPPED, not red.

The fanout depends on `bootstrap-stage2-cc` (gcc over the stage1 closure), which
is disabled under `bugs/gate-bootstrap-stage2-cc.md`, so `stage2/mojo` is never
built. Before the scheduler fix (`416ed660c`) a disabled dependency counted as
satisfied, so all fifty fanout items ran against the missing binary and died in
a second on `FileNotFoundError: './mojo'` — one red producer filed as fifty
per-item docs (`bootstrap_test_edge_cases.mojo`, `bootstrap_test_classes.mojo`,
`bootstrap_test_expressions.mojo`, ...). After the fix the fanout skips with
`dependency is disabled: bootstrap-stage2-cc (bugs/gate-bootstrap-stage2-cc.md
is the switch)`.

This pins the resolved state on the REAL registry, without spawning anything:
the fanout still depends on the disabled producer, that producer still carries
its own doc as the switch, a disabled dep is not a satisfied dep (so the whole
fanout is blocked rather than run), and the per-item docs that were cleared are
gone from `bugs/`. The mechanism itself — a dependent, and every item of a
fanout dependent, SKIPs naming the doc — is pinned on a synthetic registry by
`test_suite.py::test_a_disabled_test_is_registered_but_never_runs`; this file
is the estate half, so it names the real edges rather than a Sandbox.

Adding a per-item doc for this fanout is not a fix: the item's red is the
producer's. When one is cleared, add it to DELETED_DOCS so the deletion cannot
be undone silently.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import suite


PRODUCER = 'bootstrap-stage2-cc'
PRODUCER_DOC = 'bugs/gate-bootstrap-stage2-cc.md'
FANOUT = 'bootstrap-stage2-dumps'

# Per-item gate docs this fanout produced at c0182fd3 and that are now deleted:
# the item was never the bug, the disabled producer was. Each entry is asserted
# absent, so a re-filed doc fails here rather than resurrecting the work.
DELETED_DOCS = [
    'bugs/gate-bootstrap-stage2-dumps:bootstrap_test_expressions.mojo.md',
    'bugs/gate-bootstrap-stage2-dumps:bootstrap_test_classes.mojo.md',
]


class TestBootstrapStage2DumpsSkip(unittest.TestCase):
    def setUp(self):
        self.fanout = suite.REGISTRY.get(FANOUT)
        self.assertTrue(self.fanout is not None, '%s not registered' % FANOUT)
        self.producer = suite.REGISTRY.get(PRODUCER)
        self.assertTrue(self.producer is not None, '%s not registered' % PRODUCER)

    def test_bootstrap_stage2_dumps_skips_behind_disabled_cc(self):
        """The fanout depends on the disabled producer and must skip, not run."""
        self.assertIn(PRODUCER, self.fanout.deps,
                      '%s must depend on %s' % (FANOUT, PRODUCER))
        self.assertTrue(suite.is_disabled(self.producer),
                        '%s must stay disabled' % PRODUCER)
        self.assertEqual(self.producer.disabled, PRODUCER_DOC,
                         'the producer\'s doc is the switch')

    def test_a_disabled_producer_is_not_a_satisfied_dependency(self):
        """`DISABLED` is not a verdict a dependent can run on.

        This is the root cause: with `DISABLED` in `DEP_SATISFIED` the scheduler
        read the doc'd-off producer as satisfied and released all fifty items
        into a `stage2/mojo` that was never built.
        """
        self.assertNotIn(suite.DISABLED, suite.DEP_SATISFIED)
        blocked = {d: suite.DISABLED for d in self.fanout.deps}
        self.assertFalse(all(blocked[d] in suite.DEP_SATISFIED
                             for d in self.fanout.deps),
                         'a disabled producer would satisfy the fanout')
        detail = suite.dep_block_detail(self.fanout.deps, blocked)
        self.assertIn('dependency is disabled: %s' % PRODUCER, detail)
        self.assertIn(PRODUCER_DOC, detail,
                      'every item\'s skip must name the doc that is the switch')

    def test_every_fanout_item_is_reached_by_that_skip(self):
        """A fanout expands per item, so the item is the unit that must be covered."""
        items = list(self.fanout.items() if callable(self.fanout.items)
                     else self.fanout.items)
        self.assertGreater(len(items), 10,
                           'the fanout must still be the fifty-file corpus')
        # `bootstrap_test_classes.mojo` is the item this file was extended for;
        # `bootstrap_test_edge_cases.mojo` the one it landed for.
        for item in ('bootstrap_test_classes.mojo',
                     'bootstrap_test_edge_cases.mojo'):
            self.assertIn(item, items, '%s must be one of the fanout items' % item)

    def test_the_cleared_item_docs_stay_deleted(self):
        """A per-item doc here claims an item defect that does not exist."""
        for doc in DELETED_DOCS:
            self.assertFalse(
                os.path.exists(os.path.join(HERE, doc)),
                '%s still exists: the job is wrongly documented as red' % doc)


if __name__ == '__main__':
    unittest.main()
