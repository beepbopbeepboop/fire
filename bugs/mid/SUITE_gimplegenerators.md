# SUITE_gimplegenerators: make check failure

**Status:** PARTIAL (2026-11-11, bug-mid-suite-gimplegenerators-8955, on top of work/fix-merge-bug-mid-suite-gimplegenerators-6583)
`python3 tools/memslot.py --gb 8 --label gimplegenerators -- python3 test_gimple_generator_runner.py`
still exits 1 with 3 failures in a full run (453 passed, 3 failed):
- `received_or_str_operand_cpp`: compiled prints a leading `\x01` before the first `z` (`1\n\x01z\nd\nd\n-5\n2\n` vs `1\nz\nd\nd\n-5\n2\n`). CPP coroutine tagged-word/string `or` path emits `mojo_str_cat((char*)(<tagged-word-int64>), "z")` when the truthy branch is the received tagged string word, so the boxed word is passed as a `char *` instead of its string payload.
- `cpp_for_over_callable_param_walks_and_globs`: compiled printed empty output in the full run (`CPython '12\n12\n', compiled ''`) but passed when this test function was run in isolation afterward; possible order/state sensitivity remains.
- `cpp_fsutil_iter_files_walk_tree_glob_tree`: compiled printed empty output in the full run (`CPython '12\n29\nTrue\n0\n', compiled ''`); related callable-param iteration over `os.walk`/`glob`/recursive generator helpers in cpp coroutine context.

Earlier commits on this branch addressed dirent tagged-word yields, mgco await resume, cpp str-loop casts, cpp dyn-call arg packing, ggc shadow/variadic callable packing/escaping self, and merged master cpp_core dyn-call conflicts. Dangling ref to this doc in `bugs/mid/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4.md` was rewritten (no doc path citation).

## Done when

`python3 tools/memslot.py --gb 8 --label gimplegenerators -- python3 tools/suite.py gimplegenerators` passes (the `gimplegenerators` check job exits 0). Quick focused repro for the current deterministic failure: running `test_gimple_generator_runner.test_generator_matches_cpython("received_or_str_operand_cpp", test_gimple_generator_runner._RECEIVED_OR_STR_SRC, test_gimple_generator_runner._RECEIVED_OR_STR_SRC)` under `coro.pinned('cpp')` must PASS.
