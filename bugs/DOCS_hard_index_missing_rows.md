# DOCS: `bugs/hard/README.md` is missing rows for five landed hard docs

**Job:** `doc-refs-stale-verdicts` (`python3 test_dangling_doc_refs.py`), a
`check` member. Found while re-verifying `SUITE_self_test_red`; nothing this
branch touched is involved — the five docs below landed on master after the
index was last updated (`7879788ef` is the last README commit before ours).

Reproduce:

    python3 tools/memslot.py --gb 8 --label docrefs-tests -- python3 test_dangling_doc_refs.py

Result: `FAILED (failures=1)`, `HardIndexIsTrue.test_every_hard_doc_is_indexed`:

    AssertionError: Lists differ: ['CODEGEN_stdlib_dylib_lazy_undefined_refs[189 chars].md'] != []
    - 'CODEGEN_stdlib_dylib_lazy_undefined_refs.md'
    - 'COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4-part2.md'
    - 'FORMAL_arm64_instruction_coverage.md'
    - 'FORMAL_svc_exit_handling_incomplete.md'
    - 'GATE_red_recover-land_2026-11-02.md'

## Expected

`bugs/hard/README.md` is the hand-maintained index of `bugs/hard/*.md`, and
`test_dangling_doc_refs.py`'s `test_every_hard_doc_is_indexed` requires the
index to name every doc in the directory. Each of the five docs above is on
disk and named by no row.

## Status

Not fixed here: every one of the five is another lane's bug doc (the claims
`fix-replan-codegen-stdlib-dylib-lazy-undefined-refs`,
`fix-gate-red-recover-land-2026-11-02-par-{1,2,3,4}` and the
`COMPILE_FAIL_Tools_cases_generator_analyzer`/`FORMAL_*` lanes own them), and
the index row belongs with the doc that landed. This is an integration
transient on master, not a defect in the check.

## Next step

Add one row per missing doc to the table in `bugs/hard/README.md` (the same
`| \`<doc>.md\` | see doc | workers |` shape as its neighbours), then run

    python3 tools/memslot.py --gb 8 --label docrefs-tests -- python3 test_dangling_doc_refs.py

and delete this doc when it is green. If a doc is deleted instead of fixed,
remove it from this list rather than adding a row.
