# TEST: bugs/hard/README.md does not index CODEGEN_simd_and_array_values_erase_to_int64-part4.md

Found 2026-11-12 while verifying a master merge.

- Ran: `python3 -m unittest test_dangling_doc_refs` (on master's tree, and on the merged tree, identical here).
- Saw: `HardIndexIsTrue.test_every_hard_doc_is_indexed` fails:
  `['CODEGEN_simd_and_array_values_erase_to_int64-part4.md'] != []`.
- Expected: every `.md` in `bugs/hard/` has a row in `bugs/hard/README.md` (the index the test reads).
- Cause: the doc was moved `bugs/mid/` -> `bugs/hard/` on master, but the index row was not added.

Next step: add a row for `CODEGEN_simd_and_array_values_erase_to_int64-part4.md` to `bugs/hard/README.md`
in the same format as its sibling rows, then re-run `python3 -m unittest test_dangling_doc_refs`.
Not fixed here: the doc's owning claim is the simd/array codegen bug family, not this merge branch.
