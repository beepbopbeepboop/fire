"""The coroutine triage jobs must not be turned OFF in tools/gates.json.

GATE_recover_land_remainder-part1: async-void-return, coro,
coro-detached-async, and coro-future-await are verified green (with the
documented coro-future-await known failure outside this triage) and were
removed from the recover-land OFF entry. Pin that they stay on.
"""
import json
import re
import unittest

CORO_JOBS = (
    "async-void-return",
    "coro",
    "coro-detached-async",
    "coro-future-await",
)


def load_off():
    with open("tools/gates.json", encoding="utf-8") as f:
        return json.load(f).get("off", {})


class TestCoroJobsNotOff(unittest.TestCase):
    def test_coro_jobs_not_turned_off(self):
        off = load_off()
        for job in CORO_JOBS:
            matches = [pattern for pattern in off if re.search(pattern, job)]
            self.assertEqual(
                [],
                matches,
                "%s is turned OFF by %r" % (job, matches),
            )


if __name__ == "__main__":
    unittest.main()
