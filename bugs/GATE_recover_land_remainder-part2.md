# Doc-refs jobs triage (replan part 2 of 5)

## Goal

Verify the doc-refs related jobs are green on current HEAD and remove them from the OFF entry in `tools/gates.json`. This includes `doc-refs` and `doc-refs-stale-verdicts`.

## Acceptance

- `tools/dangling_doc_refs.py --ratchet` passes (no file gained a citation of a deleted doc).
- `python3 test_dangling_doc_refs.py` passes (the stale-verdicts test passes after adding the original doc to the hard index).
- The OFF entry regex in `tools/gates.json` no longer matches either of the doc-refs job names.

## Done when

File: `tools/suite.py` (registry entry for the doc-refs jobs; each job is the test).

Command: `python3 tools/dangling_doc_refs.py --ratchet && python3 test_dangling_doc_refs.py`

This runs both the ratchet and the stale-verdicts test sequentially, verifying they pass and the OFF entry is narrowed accordingly.