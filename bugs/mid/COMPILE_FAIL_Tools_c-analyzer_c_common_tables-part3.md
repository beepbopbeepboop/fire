# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — part 3: end-to-end `tables.py` build after the parse_table and read_table shape fixes

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (SPLIT). This part closes the file-level bug; it does NOT add new subsystems.

Depends on: part 1 (`bugs/mid/COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part1.md`, mixed-scalar tuple literal at the raise-message position) and part 2 (`bugs/mid/COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part2.md`, `with` over a tabled foreign callable). Also builds on the csv.reader foreign-callable table/runtime work already on master (commits 373cf8633, 4cb02b8c1, 7e6a8ac5c — the previous split's parts 1-3, all fixed and deleted).

## Goal

`Tools/c-analyzer/c_common/tables.py` compiles and builds through this compiler's cpp C++20-coroutine path — the two generator functions (`parse_table`, `read_table`) and their bodies correctly lowered — or the remaining shape is named honestly and filed as a fresh part, not worked around.

## Scope

1. Reproduce: `mkdir -p .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer .tmp/ca/` then build (see Done when).
2. Fix what parts 1+2 leave behind, staying inside the two generator functions and the shared mechanisms they already use. Candidate residuals, in the order the diagnostics will surface them (measure first; do not pre-fix without evidence):
   - `read_table`: the recursion `yield from read_table(infile, ...)` now flows the part-2 bound HANDLE (not a path) into this call; `isinstance(infile, str)` is then False, so the path taken is `strutil._iter_significant_lines(infile)` then `next(lines)`. Iteration over the handle — or its read-all-lines alternative via `mojo_file_read_all` (`runtime/fire_runtime.c` ~lines 1028/1116) iterated as a `MojoList *` — is the likeliest hard residual. Decide one honestly; do not fake the file object.
   - `parse_table`: `yield row, filename` — a TUPLE yield; check the yield-agreement machinery (the tagged-word yields cover scalar words; a tuple yield may need the boxed representation from part 1's world).
   - `parse_table`: `for line, filename in strutil.parse_entries(entries, ignoresep=sep)` — a cross-module generator delegated with a KEYWORD argument (`ignoresep=sep`), tuple-unpacked loop target. Check `_cpp_for_generator_delegate`'s kwargs handling.
   - `read_table`: `fix_row = _normalize_fix_read(fix)` then `tuple(fix_row(row))` — a call through a callable LOCAL holding a closure (capturing `fix`/`markers`); check the declared-callable-local call path. If this shape needs a new subsystem (a closure-capture calling convention for generator bodies), STOP and file a fresh part; do not grow this part into one.
   - `read_table`: `next(lines)` over an A3-lowered foreign generator handle (`strutil._iter_significant_lines`) — should already work via the foreign-A3-generator machinery (commit 93eacde6); verify, don't assume.
3. If any residual is its own feature (new runtime iterator, new lowering subsystem), file it as a fresh part under `bugs/` or `bugs/mid/` and record it here and in the parent doc — do not let part 3 become the whole project again.
4. Update the parent doc's Status with the outcome (what builds, what refuses and why). If the end-to-end build succeeds, the file-level bug is done; note it there (the parent doc itself is NOT to be deleted by this part — the replan protocol keeps it).

## Acceptance

- `python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py` exits 0; `MOJO_DEBUG=1` shows no `parse_table` or `read_table` refusal for the shapes parts 1 and 2 fixed, and no refusal at all for the file.
- `_regression_read_table_callable_reader` (the CPython-comparison regression in `test_gimple_generator_runner.py`) still passes; an untabled default still refuses by name.
- No whole-closure compile, no `make gate`; only the build above and the existing regressions.

## Done when

```
mkdir -p .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common /Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_analyzer .tmp/ca/ && python3 tools/memslot.py --gb 8 --label tables-build -- python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py
```

exits 0 (no `Error building` line; the binary runs).

## References

- Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (Status entries 2026-10-29 … 2026-11-12).
- Depends on: `bugs/mid/COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part1.md`, `bugs/mid/COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part2.md`.
- Sites: `mojo/backend_gimple/cpp_core.py` (`_cpp_for_stmt`, yield machinery, `_cpp_raise_stmt`), `mojo/backend_gimple/emit_resolve.py` (`publish_a3_generators`), `mojo/middle/infra_infer.py`, `.tmp/ca/c_common/tables.py` and `.tmp/ca/c_common/strutil.py` (copied sources).
