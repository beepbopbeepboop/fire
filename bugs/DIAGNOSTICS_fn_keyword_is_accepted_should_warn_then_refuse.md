# DIAGNOSTICS: the removed `fn` keyword is accepted; warn now, refuse once the hits are gone

Status: STAGE 1 LANDED (`31d480274`). STAGE 2 (refusal) DROPPED by decision on 2026-11-11 (`6408a0b14`): there is no further work on this item. The warning stays, and the integrator or gate tester handles any hits as testing finds them.

Stage 1: `fire_compiler.py`'s `_warn_fn_keyword` prints `warning: 'fn' has been removed; use 'def' instead` at the keyword of a `fn` DEFINITION (statement, decorated, async). An identifier `fn` is not reported. Pinned by `test_out_param_return_type_diagnostic.py`. The hit inventory below is the record of what stage 2 would have had to migrate; stage 2 is dropped, so it is not a work list.

## What the real compiler does (measured, `tools/mojo build`, 2026-11-11)

    def-less file:  fn f(x: Int) -> Int:
    error: 'fn' has been removed; use 'def' instead

In the toolchain measured here `fn` is already an ERROR, not a warning. Real Mojo refuses it at the keyword, column 1.
Our compiler accepts `fn` silently: `fn f(x: Int) -> Int: return x` compiles.

The project's own note is that `fn` is dead and is going away. This doc is the plan for getting there without breaking
the tests in one step.

## Decided behaviour

1. **Now: warn.** Our compiler emits a warning at every `fn` keyword, at its real location, with the real message:
   `'fn' has been removed; use 'def' instead`. The compile still succeeds, so nothing that works today breaks.
2. **Then: refuse.** Once every hit is gone from the repo and the tests, the warning becomes the real refusal (an error,
   same message, same location). The switch is one commit, and it is the commit that removes the warning path.

## Measured scope of the hits (static, 2026-11-11)

- `.mojo` files in the repo: 18 `fn` definition lines in 18 files (`grep -rn '^[[:space:]]*fn ' --include=*.mojo .`).
- Test fixtures: 630 `^\s*fn ` line-hits inside Python string constants across 51 `test_*.py` files
  (AST/string scan; counts hit instances, not distinct constants).

These are not all the same kind of hit:

- Ordinary fixtures that use `fn` as a plain spelling of `def`. Change them to `def`. This is most of them.
- Fixtures whose point is the `fn` spelling itself. Examples: `test_out_param_return_type_diagnostic.py`, where the
  stage-1 warning is pinned (and which must become the refusal test at stage 2). These keep `fn` and are marked as the
  case that tests the keyword.
- Hits in files that are not Mojo at all (a Python test that quotes Mojo in a docstring). Check each one by hand.

`.mojo` hit list:

```
./test_sqlite3_query.mojo:1:fn main():
./test_sqlite3_min.mojo:1:fn main():
./formal/examples/wide_recv.mojo:5:    fn set_x(self, v: Int):
./formal/examples/wide_recv.mojo:8:    fn get_x(self) -> Int:
./formal/examples/wide_recv.mojo:11:    fn get_y(self) -> Int:
./formal/hostmods/tempfile.mojo:451:    fn __enter__(self) -> str:
./formal/hostmods/tempfile.mojo:465:    fn __exit__(self) -> int:
./formal/hostmods/copy.mojo:2:fn copy(x):
./formal/hostmods/copy.mojo:5:fn deepcopy(x):
./formal/hostmods/contextlib.mojo:103:    fn __enter__(self) -> Int:
./formal/hostmods/contextlib.mojo:107:    fn __exit__(self) -> Int:
./test_fixtures/imports/main.mojo:3:fn main():
./test_fixtures/imports/mymod.mojo:1:fn helper() -> Int:
./test_fixtures/imports/imported_module.mojo:1:fn f() -> Int:
./test_sqlite3_len.mojo:1:fn main():
./test_sqlite3.mojo:1:fn main():
./test_relaxed_imports.mojo:4:fn main():
./test_sqlite3_simple.mojo:1:fn main():
```

Test fixture hit counts (file: `fn`-line instances in string constants):

```
test_ab_native.py: 5
test_async_void_return.py: 2
test_closure_capture_comptime_func_params.py: 4
test_comptime_assert_diagnostic.py: 41
test_comptime_dtype_diagnostic.py: 15
test_comptime_parity.py: 3
test_constrained_diagnostic.py: 31
test_coro_detached_async.py: 2
test_coro_future_await.py: 19
test_coro_nested_async_capture.py: 1
test_formal_call_proof_gen.py: 14
test_formal_frame_len.py: 1
test_formal_frame_method_finder.py: 6
test_formal_fuzz.py: 1
test_formal_imports.py: 6
test_formal_interop.py: 1
test_formal_link_accounting.py: 2
test_formal_match.py: 1
test_formal_metamorph.py: 2
test_formal_per_struct_asks.py: 3
test_formal_proof_fuzz.py: 1
test_formal_run.py: 154
test_formal_sweep.py: 7
test_formal_sweep_truth.py: 1
test_formal_toplevel.py: 1
test_formal_unicode.py: 1
test_formal_with.py: 2
test_gimple.py: 40
test_gimple_async_runner.py: 1
test_gimple_generator_runner.py: 13
test_gimple_runner.py: 154
test_import_missing_module_diagnostic.py: 8
test_inferred_param_dependency_diagnostic.py: 1
test_inferred_where_clause_diagnostic.py: 1
test_linked_list_struct_element_step4.py: 1
test_module_cache.py: 57
test_new_syntax_parsing.py: 1
test_noshim_dumpfull_preexisting_pinned.py: 1
test_out_param_return_type_diagnostic.py: 1
test_ownership_check.py: 1
test_ownership_destruct.py: 1
test_perf_dumpfull_parallel.py: 1
test_re_formal.py: 4
test_regress_async_struct_method_queue.py: 3
test_regress_dyld_path_word_chain.py: 1
test_regress_formal_known_limits_4326.py: 1
test_regress_gimple_five_reds_fixed.py: 3
test_runtime_diff.py: 3
test_sqlite3_runtime.py: 2
test_where_clause_call_site_diagnostic.py: 3
test_x86_64_examples.py: 1
```

**2026-11-11 (this worktree):** Stage 1 remains in place and pinned (`test_out_param_return_type_diagnostic` 16/16
PASS, incl. the `fn` warning/location/identifier cases). Stage 2 was dropped by decision on master (`6408a0b14`), so
the inventory above is a record rather than a work list.

## Done when

`test_out_param_return_type_diagnostic.py`'s `fn` warning cases pass: the statement, decorated, async and method
definition forms each warn at the `fn` keyword, and `def` and an identifier named `fn` do not:

    python3 tools/memslot.py --gb 8 --label fn -- python3 test_out_param_return_type_diagnostic.py

Stage 2 is dropped, so the warning is the decided end state; this doc is deleted in the commit where that test passes.

## How to find the hits, not just the ones a grep finds

A grep finds `fn` at the start of a line. It misses `fn` after a decorator, inside a string built with `+`, in a
`.md` example, or inside code that is generated. So:

1. Turn the warning on, then run the whole test tree and collect every warning, not just the first.
2. Count the warnings by file. Each file's hits are changed in the same commit as the file's test.
3. Anything the warning does not reach (a path that never calls the lexer) is found by the grep above and the
   measured fixture list, not by guessing.

## Fix order

1. Add the warning path to `fire_compiler.py` (the keyword is seen in the parser), using the real message and the
   token's location. A unit test pins the message and location against the measured output.
2. Run the test tree with the warning on and collect the hits. Record the list in this doc.
3. Change each hit to `def` in the commit that owns its test, or mark it as the keyword test.
4. Once the list is empty, switch the warning to a refusal, and delete the warning path in the same commit.

## Related

- `test_out_param_return_type_diagnostic.py`: the `fn` warning, location and identifier cases, now plain assertions
  because the warning is the decided end state.
- `bugs/TEST_out_self_with_return_type_fixtures_are_invalid_mojo.md`: the same family of fixture-validity problem.
