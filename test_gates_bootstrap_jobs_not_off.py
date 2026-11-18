"""No `tools/gates.json` OFF entry may turn a bootstrap gate job back off.

GATE_red_recover-land_2026-11-02-part5-part3: two OFF entries named the three
bootstrap jobs.  The underscore entry
`^(bootstrap-stage1-transitive|bootstrap-stage2-dumps|bootstrap-stage3-dumps)$`
(documented by the retired `GATE_red_recover-land_2026-11-02` bootstrap-recovery
umbrella) named all three, and the 23-job recover-land entry documented by
bugs/mid/GATE_recover_land_remainder.md also swept in
`bootstrap-stage1-transitive`.  Both are gone in the fix; this pins that state.

The match is `re.search(pattern, job)` because that is exactly how the
integrator decides a job is OFF (`tools/integrate.py:_gate_off_patterns`), so a
pattern that merely *contains* a bootstrap name counts here too.
"""
import json
import re
import unittest

BOOTSTRAP_JOBS = (
    "bootstrap-stage1-transitive",
    "bootstrap-stage2-dumps",
    "bootstrap-stage3-dumps",
)
REMAINDER_DOC = "bugs/mid/GATE_recover_land_remainder.md"
# A job the remainder entry owns for a different backlog and must keep owning
# (acceptance: narrowing the entry may not re-enable the rest of its jobs).
REMAINDER_JOBS_STILL_OFF = ("mojoc", "gimplerunner")


def load_off():
    with open("tools/gates.json", encoding="utf-8") as f:
        return json.load(f).get("off", {})


class TestBootstrapGateJobsNotOff(unittest.TestCase):
    def test_no_off_entry_matches_a_bootstrap_job(self):
        off = load_off()
        for job in BOOTSTRAP_JOBS:
            matches = [pattern for pattern in off if re.search(pattern, job)]
            self.assertEqual(
                [],
                matches,
                "%s is turned OFF by %r" % (job, matches),
            )

    def test_remainder_entry_keeps_its_other_off_jobs(self):
        """Narrowing the 23-job entry to drop bootstrap-stage1-transitive must
        not be done by deleting the whole entry: it still owns the rest."""
        remainder = [pattern for pattern, entry in load_off().items()
                     if entry.get("doc") == REMAINDER_DOC]
        self.assertEqual(
            1,
            len(remainder),
            "the %s OFF entry is missing" % REMAINDER_DOC,
        )
        pattern = remainder[0]
        for job in REMAINDER_JOBS_STILL_OFF:
            self.assertTrue(
                re.search(pattern, job),
                "%s was re-enabled with the bootstrap narrowing" % job,
            )
        self.assertFalse(
            re.search(pattern, "bootstrap-stage1-transitive"),
            "the %s entry still matches bootstrap-stage1-transitive" % REMAINDER_DOC,
        )


if __name__ == "__main__":
    unittest.main()
