"""The gimple codegen triage jobs must not be turned OFF in tools/gates.json.

The recover-land gimple triage: gimplegenerators, gimplerunner, globcompiled,
linkmode and modcache are verified green on current HEAD and were removed from
the recover-land OFF entry.  Each has its own regression test in this tree, but
a passing test that the gate skips is not coverage: this pins that no OFF
pattern matches them again.

It also pins the two-state rule of the gimplerunner gate doc filed red on
2026-11-19 from a gate round and green on master at 286243b91 (the tip the
branch it named had itself reached): `test_gimple_runner.py` there is 638
passed, 0 failed.  A gate doc's existence IS the claim that its job is red, so
the queue must not say that once the job is green -- and the job must stay
enabled, with the case that was its last red still defined and invoked rather
than deleted to make the run green.
"""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GIMPLERUNNER_DOC = os.path.join(HERE, "bugs", "gate-gimplerunner" + ".md")
GIMPLERUNNER_LAST_RED = "c_accessor_helpers_emitted_once_across_modules"

GIMPLE_JOBS = (
    "gimplegenerators",
    "gimplerunner",
    "globcompiled",
    "linkmode",
    "modcache",
)


def load_off():
    with open("tools/gates.json", encoding="utf-8") as f:
        return json.load(f).get("off", {})


class TestGimpleJobsNotOff(unittest.TestCase):
    def test_gimple_jobs_not_turned_off(self):
        off = load_off()
        for job in GIMPLE_JOBS:
            matches = [pattern for pattern in off if re.search(pattern, job)]
            self.assertEqual(
                [],
                matches,
                "%s is turned OFF by %r" % (job, matches),
            )


class TestGimplerunnerGateIsGreen(unittest.TestCase):
    """The gate doc is a switch: deleted == the job is green on master."""

    def test_gimplerunner_doc_is_deleted(self):
        self.assertFalse(
            os.path.exists(GIMPLERUNNER_DOC),
            "the gimplerunner gate doc exists -- the queue still says the "
            "gimplerunner job is red. It is green on master (638 passed, 0 "
            "failed); the doc belongs only to a tree where that is not so.",
        )

    def test_gimplerunner_job_stays_enabled(self):
        with open(os.path.join(HERE, "tools", "suite.py"),
                  encoding="utf-8") as f:
            text = f.read()
        # From the registration to the next top-level `test(` call, so a
        # marker written after `desc=` is still seen.
        m = re.search(r"test\('gimplerunner'.*?(?=\ntest\()", text, re.S)
        self.assertIsNotNone(
            m, "gimplerunner is not registered in tools/suite.py")
        self.assertNotIn(
            "disabled=", m.group(0),
            "gimplerunner carries disabled= -- a red gate job is fixed or "
            "tracked by a live bug doc, never switched off silently.")

    def test_gimplerunners_last_red_case_still_runs(self):
        """Deleting the failing case would turn the job green by shrinking it.

        `c_accessor_helpers_emitted_once_across_modules` was the one case the
        retired `expect=` marker still named; it must stay both defined and
        invoked in the runner that the gate job actually executes.
        """
        with open(os.path.join(HERE, "test_gimple_runner.py"),
                  encoding="utf-8") as f:
            text = f.read()
        self.assertIn("def test_%s(" % GIMPLERUNNER_LAST_RED, text,
                      "the case that was gimplerunner's last red is gone")
        self.assertIn("test_%s()" % GIMPLERUNNER_LAST_RED, text,
                      "the case is defined but no longer invoked, so the "
                      "gimplerunner job would pass without running it")


if __name__ == "__main__":
    unittest.main()
