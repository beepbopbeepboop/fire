# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — part 3: `csv.reader` runtime/iterator and end-to-end `tables.py` compile

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (SPLIT). This part completes the file-level fix for `tables.py` given parts 1-2.

Depends on: part 1 (foreign-callable table + param typing) and part 2 (`_cpp_for_stmt`/typing support for iterating a call through a tabled callable-valued param).

## Scope

Provide the concrete runtime/representation for `csv.reader` as a tabled foreign callable and make `Tools/c-analyzer/c_common/tables.py` compile end-to-end.

Concrete work:
1. Implement the runtime iterator/row representation for `csv.reader` (iterator of rows / `list[str]` element shape the table promises) in `runtime/` and wire it into emission/build so compiled code can obtain and iterate rows from the tabled `csv.reader` callable (including the default `_get_reader=csv.reader` path in `read_table`).
2. Ensure `fix_row(row)` / `tuple(fix_row(row))` and element access over the produced row type are correctly typed and lowered (finishing any residual from part 2 for this concrete element shape).
3. Handle any remaining `read_table` eligibility/lowering constraints needed for this file (e.g. kwonly/coroutine eligibility noted in parent) so the module-level blocker is removed.
4. Flip `_regression_read_table_callable_reader` in `test_gimple_generator_runner.py` from a refusal pin to a stdlib-output comparison against CPython ground truth (via the tree's usual mechanism, e.g. `tools/mojo` as noted in parent), and add/keep a refusal regression for an **untabled** callable so unknown callees remain honestly refused.
5. Verify the target: `Tools/c-analyzer/c_common/tables.py` (from Python-3.14.6 sources as in the parent doc) builds. Note: `c_analyzer/__init__.py` and `c_common/fsutil.py` share the same callable-valued-parameter/foreign-callable blocker family; this part may reuse the table/runtime mechanism for `csv.reader` but is scoped to landing `tables.py` unless extending is trivial and separately verified.

## Acceptance

- `tables.py`'s module-level compile/build failure tracked by the parent doc is resolved (targeted build succeeds). `read_table` compiles and, on the covered case, produces output matching CPython ground truth.
- `_regression_read_table_callable_reader` (or its successor) asserts correct behavior for the tabled `csv.reader` case; an untabled callable still yields a named refusal (no silent wrong behavior).
- No whole-closure compile, self-host build, or full gate in the worker; run only the narrowest verification for this change (wrap any compile in `python3 tools/memslot.py --gb 8 --label <what> -- <cmd>`). If a heavier suite is required, record it as NOT DONE for the integrator.

## References

- Parent doc: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (plan step 5, runtime/iterator need, shared blockers with `c_analyzer/__init__.py` and `c_common/fsutil.py`).
- Key sites: `runtime/`, `mojo/backend_gimple/cpp_core.py`, `mojo/backend_gimple/coro.py`, `test_gimple_generator_runner.py`, foreign-callable table from part 1.
