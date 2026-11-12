# SUITE_gimplegenerators: make check failure

**Status:** PARTIAL (2026-11-12, bug-mid-suite-gimplegenerators-8625)
`python3 tools/memslot.py --gb 8 --label gimplegenerators -- python3 test_gimple_generator_runner.py`
still exits 1 with 2 failures in a full run (454 passed, 2 failed):
- `cpp_for_over_callable_param_walks_and_globs`: compiled printed empty output in the full run (`CPython '12\n12\n', compiled ''`) but passed when this test function was run in isolation afterward; possible order/state sensitivity remains.
- `cpp_fsutil_iter_files_walk_tree_glob_tree`: compiled printed empty output in the full run (`CPython '12\n29\nTrue\n0\n', compiled ''`); related callable-param iteration over `os.walk`/`glob`/recursive generator helpers in cpp coroutine context.

Fixed in this session: `received_or_str_operand_cpp` — CPP coroutine string concatenation was installing numeric None-arith guards on tagged-word `and`/`or` operands, forcing them through an int64_t guard path and losing `_W` char* unboxing, so the raw tagged word pointer was passed to `mojo_str_cat` (leading `\x01`). String-concat `+` paths now skip numeric none-arith guards in `mojo/backend_gimple/cpp_core.py`. Regression: `test_regress_gimple_coro_received_or_str.py`.

Earlier commits on this branch addressed dirent tagged-word yields, mgco await resume, cpp str-loop casts, cpp dyn-call arg packing, ggc shadow/variadic callable packing/escaping self, merged master cpp_core dyn-call conflicts, and dangling doc ref cleanup.

## Done when

`python3 tools/memslot.py --gb 8 --label gimplegenerators -- python3 tools/suite.py gimplegenerators` passes (the `gimplegenerators` check job exits 0). Quick focused repro for the previously deterministic failure: running `test_gimple_generator_runner.test_generator_matches_cpython("received_or_str_operand_cpp", test_gimple_generator_runner._RECEIVED_OR_STR_SRC, test_gimple_generator_runner._RECEIVED_OR_STR_SRC)` under `coro.pinned('cpp')` must PASS.
