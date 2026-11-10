# SUITE_gimplegenerators: make check failure

**Status:** PARTIAL — investigated and partially fixed on branch `work/bug-mid-suite-gimplegenerators-3555` (2026-11-10).

Job `gimplegenerators` (`python3 test_gimple_generator_runner.py`) failed (exit 1).
Initial run on this tree: **423 passed, 27 failed**. After earlier fixes on this branch lineage:
**440 passed, 10 failed**. After prior round (dynamic-call arg/kw packing in cpp for-loops):
**444 passed, 6 failed**. After this round's fixes (mgco await/async-for resume send uses `mojo_box_none()`,
and cpp for-loop string-element reads cast correctly when target pre-declared as int64_t): **449 passed, 1 failed**
(focused repros + full `python3 tools/memslot.py --gb 8 --label gimplegenerators -- python3 test_gimple_generator_runner.py`).

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

5. **`cpp_core.py` (C++ coroutine path): for-loops over calls through callable parameters/locals built
   `mojo_dyn_call` invocations by flattening every argument (including keyword values) into the
   positional list and appending all values as `int64_t`, losing keyword binding and truncating
   float arguments.** Replaced those manual packings with `_cpp_dyn_call_expr(...)` so positional and
   keyword arguments are packed separately and doubles are appended/tagged correctly for the runtime
   signature path. Fixed `cpp_for_over_callable_param_walks_and_globs`,
   `cpp_fsutil_iter_files_walk_tree_glob_tree`, and
   `cpp_generator_double_param_called_by_keywords`. (`received_or_str_operand_cpp` also passes in
   current focused runs; the earlier wrong-output failure was not reproduced in isolation.)

6. **`mojo/middle/coro.py`: mgco await/async-for drive loops resumed child coroutines with
   `__mojo_gen_resume(..., 0)` instead of `mojo_box_none()`.** `__mojo_gen_resume` rejects a
   non-None send value on a just-started generator/coroutine, so passing `0` (not equal to boxed
   None) raised "can't send non-None value to a just-started generator" and produced empty output.
   Fixed both `_await_drive_stmts` and `_async_for_drive_stmts` to pass `mojo_box_none()`. Fixed
   `star_args_coroutine_await_packs`, `star_args_async_method_aexit_shape`,
   `star_args_async_generator_for_packs`, and `async_for_over_nonparking_await`.

7. **`cpp_core.py` (C++ coroutine path): for-loop string-element reads into a pre-declared
   `int64_t` target assigned `char*` directly.** When iterating lists/slices whose elements are
   read via `mojo_list_get_str`, targets already declared as `int64_t` must receive
   `(int64_t)(intptr_t)mojo_list_get_str(...)` (later string uses cast back through intptr_t in
   this model). Added casts in indexed list iteration, zip iteration, dict iteration, and similar
   string-element paths. Fixed `generator_os_fwalk_fd_relative_walk` (fd-relative `_fwalk` compile
   error: `mojo_list_get_str` result assigned to `int64_t`).

## Still failing (1) — next step

- `generator_closing_a_tagged_dir_iterator_then_list`: dir iterator entries printed as pointer
  addresses (`['43...', '43...']`) instead of names — tagged dir-iterator element boxing/printing.
  The cpp coroutine generator `_iterdir` yields `mojo_dirent_name(entry)` as `/*Y:int*/` (raw char*
  word) so collected list elements become plain ints/addresses. Needs proper string/word tagging or
  boxing for `DirEntry.name`/`mojo_dirent_name` yields in the cpp generator yield/value-kind system
  (and compatible handling with the `fsencode(...)` bytes branch) so `list()` sees string elements.
