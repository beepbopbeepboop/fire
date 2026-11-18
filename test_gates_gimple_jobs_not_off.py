"""The gimple codegen triage jobs must not be turned OFF in tools/gates.json.

The recover-land gimple triage: gimplegenerators, gimplerunner, globcompiled,
linkmode and modcache are verified green on current HEAD and were removed from
the recover-land OFF entry.  Each has its own regression test in this tree, but
a passing test that the gate skips is not coverage: this pins that no OFF
pattern matches them again.
"""
import json
import re
import unittest

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


if __name__ == "__main__":
    unittest.main()
