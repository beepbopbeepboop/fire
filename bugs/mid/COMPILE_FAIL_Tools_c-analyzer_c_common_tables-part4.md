# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — part 4: a tuple-target `for` over a module-qualified call to a foreign module's compiled generator (with a keyword argument) in a compiled generator body

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (SPLIT). This part fixes ONE named residual shape measured 2026-11-13; it does NOT add a new subsystem.

Sister: `COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part5.md` (the `read_table` generator-handle-as-call-argument shape). `COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part3.md` is the end-to-end closer that depends on both.

## Measured shape (2026-11-13, this tree)

`python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py` (sources copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` per the parent doc) still fails (peak 0.2 GB, child exit 1) with EXACTLY two named refusals; the part-1 (mixed-scalar raise message, f864d028d) and part-2 (`with` over a tabled open, a912f5987) shapes are gone. This part is the first of the two:

    parse_table: a tuple `for` target (line, filename) over this iterable is not supported in a compiled generator/coroutine body: only a `for` over enumerate(), a literal list of tuples, a dict .items(), or a container global unpacks per slot.

The site is c_common/tables.py:166, in `parse_table` (cpp C++20-coroutine path — the kwonly `default=NOT_SET` keeps it off the A3 stack-switch pass):

    for line, filename in strutil.parse_entries(entries, ignoresep=sep):

- the callee `strutil.parse_entries` is a generator in a FOREIGN module (c_common/strutil.py:11; kwonly `ignoresep` → it too is cpp-path), called with a KEYWORD argument (`ignoresep=sep`);
- the loop target is a TUPLE `(line, filename)`, and the yielded tuples carry a None slot (`yield item, None`) that the body reads (`if filename:`).

## Why it is refused today

`_cpp_for_stmt`'s tuple-target dispatch for delegated generators (cpp_core.py ~:10024) is gated by `_cpp_iterable_is_delegatable_generator_call` (`mojo/backend_gimple/cpp_async.py:214`), which accepts only a bare `name(...)` (in `_all_generator_names`/`_generator_api`) or a `self`/`cls` method call. A module-qualified `<module>.<name>(...)` returns False, so the loop falls through to the generic emitter, where `_cpp_refuse_unpacking_target` (cpp_core.py:9210) refuses the comma-joined target. The callee itself is resolvable: `cpp_core._cpp_resolve_generator_call_api`'s MemberExpr branch (cpp_core.py:2010-2020) already looks `<module>.<gen>` up in the whole-program `_generator_home_api`, and BOTH backends register there — the cpp units at module_gen.py:13906 (keyed by `_func_qualifier`) and the A3 publication at emit_resolve.py:486-508 (`publish_a3_generators`, first-writer-wins).

## Goal

Extend the existing machinery so the shape compiles and runs, in order:

1. `cpp_async._cpp_iterable_is_delegatable_generator_call`: accept a module-qualified `CallExpr` whose callee resolves through `cpp_core._cpp_resolve_generator_call_api` (the `_generator_home_api` entry must exist, so an unresolvable callee keeps falling through to the current honest refusal — never guess).
2. `cpp_core._cpp_for_generator_delegate`: add a module-qualified branch that resolves the callee the same way and drives the sub-generator over the identical `{base}_start/_resume/_value/_destroy` protocol, registering the four-symbol extern "C" preamble via `_cpp_xmod_generator_refs` (the same machinery the expression sites use via `_cpp_emit_generator_start_expr`, cpp_core.py:2024), and unpacks a tuple target per slot from the callee's registered `tuple_slot_ctypes` (the producer-side convention `_cpp_yield_tuple` already emits).
3. Keyword arguments: `_cpp_emit_generator_start_expr` already appends kwargs positionally with trailing-default padding (cpp_core.py:2046-2054); keep that ordering (here `ignoresep` is the callee's last parameter, so positional-last is correct) and do NOT pre-mutate the call node in a way the retry passes would see twice.

Guardrails: keep every existing refusal intact (unresolvable callee, non-tuple-yielding callee under a tuple target, `for/else`); do NOT touch part 5's shape (the `_cpp_dyn_call_expr` argument packing in `read_table`); no new runtime, no new lowering subsystem — if the fix turns out to need one, STOP and file a fresh part exactly like part 3's scope says.

## Acceptance

- The Done-when regression below passes: the fixture BUILDS, runs, and its stdout matches CPython on the same files (the tuple slots — including the None slot the body reads — come out right, not merely the loop count).
- Re-run the parent's build (`Done when` of part 3): `MOJO_DEBUG=1` no longer reports the `parse_table` tuple-`for`-target shape; the only remaining refusal, if any, is part 5's.
- The suite's `gimplegenerators` job (`python3 test_gimple_generator_runner.py`) stays green — in particular the existing delegated-`for` regressions (the dis.py tuple-target case, `foreign_a3_generator_handle_next` / `_for_loop`) must not regress.
- No whole-closure compile, no `make gate`; the integrator runs the gate over the landing.

## Done when

```
python3 tools/memslot.py --gb 8 --label tables-part4 -- python3 -c "import test_gimple_generator_runner as t; t._regression_tables_module_qualified_tuple_for()"
```

prints `PASS  tables_module_qualified_tuple_for` (file: `test_gimple_generator_runner.py`; on the 2026-11-13 tree it FAILs with the refusal quoted above). When it passes, wire the call into `run_tests()` next to `_regression_raise_mixed_tuple_literal_in_generator` in the same commit.

## References

- Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (Status entries 2026-09-30 … 2026-11-13; the foreign-handle machinery is the 2026-09-30 entry, commit 93eacde6).
- Sites: `mojo/backend_gimple/cpp_async.py` (`_cpp_iterable_is_delegatable_generator_call`), `mojo/backend_gimple/cpp_core.py` (`_cpp_for_stmt` tuple dispatch, `_cpp_for_generator_delegate`, `_cpp_resolve_generator_call_api`, `_cpp_emit_generator_start_expr`, `_cpp_refuse_unpacking_target`), `mojo/backend_gimple/module_gen.py` (the cpp `_generator_home_api` registration), `mojo/backend_gimple/emit_resolve.py` (`publish_a3_generators`).
- Real sources: `.tmp/ca/c_common/tables.py` (:153-183 `parse_table`), `.tmp/ca/c_common/strutil.py` (:11-34 `parse_entries`), copied per the parent doc's Scope step 1.
