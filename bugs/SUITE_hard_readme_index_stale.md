# `test_dangling_doc_refs.py` is red: five `bugs/hard/` docs have no README row

## Symptom

`python3 test_dangling_doc_refs.py` fails in
`HardIndexIsTrue.test_every_hard_doc_is_indexed`:

    AssertionError: Lists differ: ['CODEGEN_stdlib_dylib_lazy_undefined_refs.md',
    'COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4-part2.md',
    'FORMAL_arm64_instruction_coverage.md',
    'FORMAL_svc_exit_handling_incomplete.md',
    'GATE_red_recover-land_2026-11-02.md'] != []

The test is the registered `doc-refs-stale-verdicts` job. The five docs exist in
`bugs/hard/` but `bugs/hard/README.md` has no row for them. This is a
bookkeeping drift, not a compiler failure: no doc was deleted and no citation is
wrong (`python3 tools/dangling_doc_refs.py --ratchet` is green).

## What I ran

From the work tree on `master` at 4a8b95cab:

    python3 tools/memslot.py --gb 8 --label doc-refs -- python3 -m unittest -v test_dangling_doc_refs

fails only `test_every_hard_doc_is_indexed`; the other six tests pass.

`git log --oneline -- bugs/hard/README.md` shows the README was last updated
before the five docs landed (the newest, `FORMAL_svc_exit_handling_incomplete.md`,
arrived with 4a8b95cab).

## Expected

`bugs/hard/README.md` carries one row per doc in `bugs/hard/`, so the index test
is green.

## Exact next step

Add the missing rows to the table in `bugs/hard/README.md` (alphabetical,
same `see doc | workers` shape as its neighbours), or delete the docs that are
actually closed. The README is hand-maintained; `tools/formal_doc_index.py`
does not own it.

## Done when

`HardIndexIsTrue.test_every_hard_doc_is_indexed` in
`test_dangling_doc_refs.py` is green — every doc in `bugs/hard/` has a README
row — and its sibling `test_every_doc_the_index_names_exists` stays green — no
row names a doc that is gone. Run it as the registered job does:

    python3 tools/memslot.py --gb 8 --label doc-refs -- python3 -m unittest -v test_dangling_doc_refs

Seven rows were missing when this was fixed (the five named above plus
`CODEGEN_selfhost_link_two_unqualified_calls.md` and
`SUITE_silentnoop-part1.md`, which landed after this doc).
