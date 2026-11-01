# TEST_dangling_doc_refs_ratchet_red_on_master: `doc-refs --ratchet` fails on files nobody touched

**Area:** TEST (`tools/dangling_doc_refs.py`, `tools/dangling_refs_baseline.py`).
Found 2026-11-01 while deleting `bugs/CODEGEN_a_padded_zip_longest_struct_slot_is_a_null_dereference.md`.

## What I ran, and what I saw

    python3 tools/dangling_doc_refs.py --ratchet

    ratchet: 2 file(s) cite MORE deleted docs than tools/dangling_refs_baseline.py allows:
      formal/arm64_proof_gen.py: 3 (baseline 0) — FORMAL_integer_overflow_at_run_time_is_still_untrapped.md
      test_formal_call_proof_gen.py: 3 (baseline 0) — FORMAL_integer_overflow_at_run_time_is_still_untrapped.md

Both files are byte-identical to master (`git diff master -- formal/arm64_proof_gen.py test_formal_call_proof_gen.py` is empty),
so this red is not caused by any branch change.

## What I expected

The ratchet is green on master, or it names only what the branch changed.

## Why it looks wrong

`bugs/formal/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md` EXISTS
(it is listed in `bugs/OPEN_WORK.md`). The two files cite it by bare stem, and the
checker reports the citation as dangling against a baseline of 0. Either the
bare-stem resolver does not search `bugs/formal/`, or the doc was moved into
`formal/` after the baseline was written. Not yet determined which.

## Next step

1. Read `tools/dangling_doc_refs.py`'s bare-stem resolution and confirm whether it
   searches `bugs/**`.
2. If the resolver is wrong, fix the resolver and add a test to `test_suite.py`.
3. If the citation is stale, rewrite the two citations to name the bug, then
   `python3 tools/dangling_doc_refs.py --ratchet` must exit 0.
