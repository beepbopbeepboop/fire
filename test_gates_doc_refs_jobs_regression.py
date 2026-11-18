#!/usr/bin/env python3
"""GATE_recover_land_remainder-part2: the two doc-refs jobs stay registered and ON.

The recover-land OFF entry in `tools/gates.json` (owned by
`bugs/hard/GATE_recover_land_remainder.md`) turned `doc-refs` and
`doc-refs-stale-verdicts` OFF for a backlog. Both are cheap (tiny class, 1.4 s
and 0.9 s measured) and green on the HEAD where part 2 was triaged, so the entry
must no longer match either name.

The match is `re.search(pattern, job)` because that is exactly how the
integrator decides a job is OFF (`tools/integrate.py:_gate_off_patterns`), so a
pattern that merely *contains* a doc-refs name counts here too, and a future
entry that sweeps one back in fails rather than hides.

Both jobs are also pinned as registered in `tools/suite.py`: "not turned OFF"
means nothing if the job is not in the registry at all, and the doc's Done-when
names the registry entry for the doc-refs jobs as the file that carries them.

Without the branch's `tools/gates.json` change, the first test fails on both
names (master's single OFF pattern matches them). If the whole OFF entry were
deleted instead of narrowed, the still-red rest of the backlog would be turned
on; the umbrella doc remains, so that is a separate fix, not part 2's.

Run directly:  python3 test_gates_doc_refs_jobs_regression.py
"""
import ast
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GATES = os.path.join(HERE, "tools", "gates.json")
SUITE = os.path.join(HERE, "tools", "suite.py")

DOC_REFS_JOBS = ("doc-refs", "doc-refs-stale-verdicts")


def load_off():
    with open(GATES, encoding="utf-8") as f:
        return json.load(f).get("off", {})


def registered_test_names():
    """The job names `tools/suite.py` registers with a literal `test('name', ...)`.

    Parsed rather than imported: the registry is a module that reads gate docs
    and refuses to load on an inconsistency, which is a useful property for a
    gate and a bad one for a unit test of one row.
    """
    with open(SUITE, encoding="utf-8") as f:
        tree = ast.parse(f.read(), SUITE)
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "test"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            if isinstance(node.args[0].value, str):
                names.add(node.args[0].value)
    return names


class DocRefsJobsStayOn(unittest.TestCase):
    def test_no_off_entry_matches_a_doc_refs_job(self):
        off = load_off()
        for job in DOC_REFS_JOBS:
            matches = [pattern for pattern in off if re.search(pattern, job)]
            self.assertEqual(
                [],
                matches,
                "%s is turned OFF by %r" % (job, matches),
            )

    def test_both_doc_refs_jobs_are_registered(self):
        registered = registered_test_names()
        missing = [job for job in DOC_REFS_JOBS if job not in registered]
        self.assertEqual(
            [],
            missing,
            "not registered in tools/suite.py: %s" % missing,
        )


if __name__ == "__main__":
    unittest.main()
