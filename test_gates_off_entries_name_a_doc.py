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


if __name__ == "__main__":
    unittest.main()
