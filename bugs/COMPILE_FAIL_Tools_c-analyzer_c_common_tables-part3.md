# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — part 3: end-to-end `tables.py` build after the parse_table and read_table shape fixes

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (SPLIT). This part closes the file-level bug; it does NOT add new subsystems.

Depends on: part 1 (mixed-scalar tuple literal at the raise-message position, fixed 2026-11-13) and part 2 (`with` over a tabled foreign callable, fixed 2026-11-13 and its bug doc deleted) — both landed — AND the two shapes the 2026-11-13 measurement below found, filed as `COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part4.md` (parse_table's tuple-`for` over a module-qualified delegated generator call with a kwarg) and `COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part5.md` (read_table's generator-handle argument to the call through `_get_reader`). It also builds on the csv.reader foreign-callable table/runtime work already on master (commits 373cf8633, 4cb02b8c1, 7e6a8ac5c — the previous split's parts 1-3, all fixed and deleted).

## Status 2026-11-13 — re-measured: parts 1+2 are gone; the two new residuals are filed as parts 4 and 5

`python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py` (sources copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`) still fails (peak 0.2 GB, child exit 1), and `MOJO_DEBUG=1` reports exactly TWO refusals — the 2026-11-12 pair (part 1's raise-message tuple, part 2's `with` over a tabled open) is GONE:

    parse_table: a tuple `for` target (line, filename) over this iterable is not supported in a compiled generator/coroutine body: only a `for` over enumerate(), a literal list of tuples, a dict .items(), or a container global unpacks per slot.
    read_table: a call through the callable-valued parameter '_get_reader' passes an argument whose C type is not statically a word, string or container.

They are filed as part 4 and part 5 (red regressions committed in `test_gimple_generator_runner.py`, verified against the tree in the same round). This part now runs the build AFTER parts 4 and 5 land and re-splits any residual that then appears.

## Goal

`Tools/c-analyzer/c_common/tables.py` compiles and builds through this compiler's cpp C++20-coroutine path — the two generator functions (`parse_table`, `read_table`) and their bodies correctly lowered — or the remaining shape is named honestly and filed as a fresh part, not worked around.

## Scope

1. Reproduce: `mkdir -p .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer .tmp/ca/` then build (see Done when).
2. Check the preconditions first: the two 2026-11-13 refusals (part 4's `parse_table` shape, part 5's `read_table` shape) must be GONE from the `MOJO_DEBUG=1` output. If one or both are still there, parts 4/5 have not landed — work them (their docs carry the exact sites and the red regressions) rather than re-doing their scope here.
3. If the build then rejects a NEW shape, file it as a fresh part (`COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part6.md` or later) naming the shape, the site, and a red regression of its own — do not let part 3 become the whole project again. The pre-measurement candidate list is superseded by the 2026-11-13 measurement; do not pre-fix shapes the diagnostics have not surfaced.
4. Update the parent doc's Status with the outcome (what builds, what refuses and why). If the end-to-end build succeeds, the file-level bug is done; note it there (the parent doc itself is NOT to be deleted by this part — the replan protocol keeps it).

## Acceptance

- `python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py` exits 0; `MOJO_DEBUG=1` shows no `parse_table` or `read_table` refusal for the shapes parts 1/2/4/5 fixed, and no refusal at all for the file.
- `_regression_read_table_callable_reader` and the part-4/part-5 red regressions (once wired into `run_tests()`) pass; an untabled default still refuses by name.
- No whole-closure compile, no `make gate`; only the build above and the existing regressions.

## Done when

```
mkdir -p .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer .tmp/ca/ && python3 tools/memslot.py --gb 8 --label tables-build -- python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py
```

exits 0 (no `Error building` line; the binary runs).

## References

- Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (Status entries 2026-09-30 … 2026-11-13).
- Depends on: part 4 and part 5 (this round's measurement), on top of fixed-and-deleted parts 1 and 2.
- Sites: `mojo/backend_gimple/cpp_core.py` (`_cpp_for_stmt`, yield machinery, `_cpp_raise_stmt`, `_cpp_dyn_call_expr`), `mojo/backend_gimple/emit_resolve.py` (`publish_a3_generators`), `mojo/middle/infra_infer.py`, `.tmp/ca/c_common/tables.py` and `.tmp/ca/c_common/strutil.py` (copied sources).
