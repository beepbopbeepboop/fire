# `test_suite.py` self-test: `bugs/OPEN_WORK.md` is stale after the arm64 land

**Found by:** the `bug:gate-rthdrscan` lane (2026-11-14), running
`python3 test_suite.py` — a file this lane touched, so it ran the whole file.
**Not caused by that lane:** no `formal/` document is added or deleted by this
branch, and `bugs/OPEN_WORK.md` is unmodified.

## What I ran

    python3 tools/memslot.py --gb 8 --label testsuite -- python3 test_suite.py
    python3 tools/formal_doc_index.py --check

## What I saw

    - formal doc index: OPEN_WORK.md's generated block is current: FAIL
      formal doc index: the block in bugs/OPEN_WORK.md is stale — a document
      was added or deleted, or an area or a title moved. Run
      `python3 tools/formal_doc_index.py --write`.
       --- OPEN_WORK.md
       +++ generated
       -### `formal/arm64_proof_gen` — 4 documents, — claimed
       +### `formal/arm64_proof_gen` — 3 documents, — claimed
       ...
       -**5 documents, — claimed.**
       +**4 documents, — claimed.**

The tree has three `formal/arm64_proof_gen` documents
(`FORMAL_arm64_instruction_coverage-part2`, `-part3`, and
`hard/FORMAL_svc_exit_handling_incomplete`); the generated block still says
four. Master's merge `d3ec70ee7` ("integrate
bug-formal-arm64-instruction-coverage-pa") deleted part 1 of the
`FORMAL_arm64_instruction_coverage` doc and did not regenerate the
index, so `python3 tools/formal_doc_index.py --check` is red on master as it
stands. That check is part of `test_suite.py`, i.e. the gate.

## What I expected

The generated block in `bugs/OPEN_WORK.md` names the document set the tree
actually has, which is what `test_suite.py`'s "formal doc index" check
requires.

## Exact next step

    python3 tools/formal_doc_index.py --write
    python3 tools/formal_doc_index.py --check
    python3 test_suite.py

and commit the regenerated block. Nothing else should move: the command
rewrites only the generated region of `bugs/OPEN_WORK.md`. (Whoever owns the
`formal/arm64_proof_gen` area may want to confirm the part-1 deletion was
intended; the index regeneration does not depend on the answer.)
