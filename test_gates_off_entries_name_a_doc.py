import json
import os
import unittest


class TestGatesOffEntriesNameADoc(unittest.TestCase):
    def test_off_entries_name_existing_doc_and_worker(self):
        with open("tools/gates.json", encoding="utf-8") as f:
            cfg = json.load(f)
        for pattern, entry in cfg.get("off", {}).items():
            doc = entry.get("doc")
            worker = entry.get("worker")
            self.assertTrue(doc, f"off entry {pattern!r} has empty doc")
            self.assertTrue(
                os.path.exists(doc),
                f"off entry {pattern!r} doc does not exist: {doc}",
            )
            self.assertTrue(worker, f"off entry {pattern!r} has empty worker")

    def test_a_verified_job_is_not_silently_off(self):
        """The two formal jobs re-enabled on 2026-11-18 stay inside the gate.

        `formal-sweep-truth` and `formal-sys` were removed from the
        recover-land OFF entry after both were re-run green on this tree
        (`test_formal_sweep_truth.py` 145 tests OK, `test_formal_sys.py`
        PASS=13 FAIL=0). A later pattern that matched either again would turn
        a verified job off with nothing failing and no doc saying so, which is
        the state the re-enable existed to end.
        """
        import re
        with open("tools/gates.json", encoding="utf-8") as f:
            cfg = json.load(f)
        off = [re.compile(p) for p in cfg.get("off", {})]
        for job in ("formal-sweep-truth", "formal-sys"):
            matching = [p.pattern for p in off if p.match(job)]
            self.assertEqual(
                matching, [],
                f"{job} is matched by OFF entry(ies) {matching}; it is green on "
                f"this tree (2026-11-18), and turning a job off needs a doc and "
                f"its own evidence rather than a silent regex")


if __name__ == "__main__":
    unittest.main()
