# SUITE_gimplegenerators: make check failure

**Status:** PARTIAL — investigated and partially fixed on branch `work/bug-suite-gimplegenerators` (2026-11-07).

Job `gimplegenerators` (`python3 test_gimple_generator_runner.py`) failed (exit 1).
Initial run on this tree: **423 passed, 27 failed**. After fixes below: **440 passed, 10 failed**
(verified with `python3 tools/memslot.py --gb 8 --label gimplegenerators -- python3 test_gimple_generator_runner.py`).

## Root causes fixed

1. **`emit_methods.py`: local `ggc` import shadowing module-level alias in `_lower_method_call`.**
   A `import ... as ggc` inside a `type.__new__` branch made `ggc` a function-local, so the
   generator-method kwargs packing path (`ggc._pack_kwargs_dict`, reached for `**kw` generator
   methods) raised `UnboundLocalError: cannot access local variable 'ggc'`. Fixed by removing the
   local import (module-level `ggc` already imported). Fixed `kwargs_generator_method_packs_keywords`,
   `generator_method_call_pads_nonzero_offset_default`.

2. **`cpp_core.py` (C++ coroutine path): variadic callable locals (`*args`/`**kwargs` lambdas) called
   with raw args instead of packed containers.** In both expression emission (`_cpp_expr` IdentExpr
   call path) and bare-call statement emission, any `_cpp_is_callable_ctype` hit the direct-call path
   and emitted `e(4,5)` even for `std::function<int64_t(MojoList*)>` (`STARARGS`/`KWARGS`/`STAR_KW`),
   causing g++ "no match for call" errors and skipping the existing packing/refusal logic. Excluded
   variadic-family callable ctypes from the direct-call shortcut so the packing branch (and its
   type/refusal checks) runs. Fixed the `cpp_coroutine_starargs/kwargs_lambda_*` compile-failure and
   refusal-expectation cluster and `cpp_coroutine_unpack_*` cases that depended on correct packing.

3. **`cpp_async.py` `_compile_nested_generator_closures`: escaping method nested generator capturing
   `self` compiled with `self` as `int64_t` extra capture instead of refusing.** For a nested
   generator in a method that reads `self` and whose result escapes (`return g()`), `self` cannot be
   supplied to the escaped frame; the old code threaded `self` as `int64_t`, producing broken C++
   (`self.k` on a non-class `int64_t`). Now filters `self` out of extra captures when
   `_generator_result_escapes` is true, letting the generator unit refuse with
   "reads enclosing-scope variable(s) self". Fixed `nested_generator_method_self_escaping_refused`.

4. **`test_gimple_generator_runner.py`:** moved a stray `flag_instance_iter_via_iter_member_alias`
   test call that lived after `if __name__ == '__main__'` into `run_tests()` (it was outside the
   test-runner control flow). Updated `cpp_coroutine_unpack_boxed_source_refused` (now correctly
   compiles: an untyped list parameter's container type is resolved and `*src` forwards as a list
   copy, matching CPython -> `'4\n'`) to `cpp_coroutine_unpack_list_param_source` with a CPython
   oracle.

## Still failing (10) — next steps

- `received_or_str_operand_cpp`: `1 or 'z'`-style tagged `or`/operand result prints `\x01` before
  `z` in compiled output (`1\n\x01z\nd\nd\n-5\n2\n` vs CPython `1\nz\nd\nd\n-5\n2\n`) — tagged
  word/bool-vs-str representation in cpp tagged-operand printing.
- `star_args_coroutine_await_packs`, `star_args_async_method_aexit_shape`,
  `star_args_async_generator_for_packs`: compiled output empty (`''`) — `*args` packing for
  coroutine `await`/async method `__aexit__`/`async for` start calls (A3/coro lowering path),
  not the cpp_core local-call path fixed above.
- `cpp_for_over_callable_param_walks_and_globs`, `cpp_fsutil_iter_files_walk_tree_glob_tree`:
  compiled output empty — `for` over calls through callable parameters (`os.walk`/`glob.iglob`
  defaults) in cpp generator path yields no output.
- `cpp_generator_double_param_called_by_keywords`: compiled output empty for double-parameter
  generator called by keywords (runtime signature/dispatch).
- `async_for_over_nonparking_await`: compiled output empty (`''` vs `'10\n'`).
- `generator_closing_a_tagged_dir_iterator_then_list`: dir iterator entries printed as pointer
  addresses (`['4378841296', '4378841456']`) instead of names — tagged dir-iterator element
  boxing/printing.
- `generator_os_fwalk_fd_relative_walk`: g++ compile error in generated cpp for `_fwalk` (fd-relative
  posix/os.fwalk lowering in cpp coroutine path). Inspect the emitted `.cpp` from a focused repro of
  `generator_os_fwalk_fd_relative_walk` to find the bad member/type emission.
