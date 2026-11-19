"""No `tools/gates.json` OFF entry may turn a runtime/utility job back off.

The recover-land OFF entry (bugs/hard/GATE_recover_land_remainder.md) swept in
`runtimediff`, `runtimedylib`, `runtimere`, `silentnoop`, `sqliteruntime` and
`suite-self-test`, and each is green on current HEAD:

    test_runtime_diff.py        69 passed
    test_runtime_dylib.py       130 passed
    test_runtime_re.py          48 engine cases + the compiled program
    test_silent_noop_iter.py    28 passed
    test_sqlite3_runtime.py     66 passed
    test_suite.py               411 passed

They were removed from the pattern; this pins that none of them is named by an
OFF entry again. The match is `re.search(pattern, job)` because that is exactly
how the integrator decides a job is OFF (`tools/integrate.py:_gate_off_patterns`),
so a pattern that merely *contains* a runtime job name counts here too.
"""
import json
import re
import unittest

RUNTIME_JOBS = (
    "runtimediff",
    "runtimedylib",
    "runtimere",
    "silentnoop",
    "sqliteruntime",
    "suite-self-test",
)


def load_off():
    with open("tools/gates.json", encoding="utf-8") as f:
        return json.load(f).get("off", {})


class TestRuntimeGateJobsNotOff(unittest.TestCase):
    def test_no_off_entry_matches_a_runtime_job(self):
        off = load_off()
        for job in RUNTIME_JOBS:
            matches = [pattern for pattern in off if re.search(pattern, job)]
            self.assertEqual(
                [],
                matches,
                "%s is turned OFF by %r" % (job, matches),
            )


if __name__ == "__main__":
    unittest.main()
