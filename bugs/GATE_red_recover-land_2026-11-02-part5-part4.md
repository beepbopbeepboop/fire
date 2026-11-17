# Retire GATE_red_recover-land_2026-11-02 umbrella doc and ratchet refs (replan part 4 of 5)

## Goal

Once parts 1–3 are complete, delete the umbrella doc `bugs/hard/GATE_red_recover-land_2026-11-02.md` in the same change set as the final gate re-enable, and fix any citations named by `python3 tools/dangling_doc_refs.py --ratchet` so the ratchet passes.

Rewrite citations to name the bug/symptom or the fixing commit as appropriate, or delete sentences whose only content was the path. Keep the part docs that remain relevant (this replan's parts and any other still-open parts under `bugs/`).

## Acceptance

- `bugs/hard/GATE_red_recover-land_2026-11-02.md` does not exist.
- `python3 tools/dangling_doc_refs.py --ratchet` exits 0 after any needed citation fixes.
- No OFF gate entry continues to name the deleted umbrella doc.

## Done when

File: `tools/dangling_doc_refs.py` (the ratchet command is the test)
Command: `python3 tools/dangling_doc_refs.py --ratchet`
