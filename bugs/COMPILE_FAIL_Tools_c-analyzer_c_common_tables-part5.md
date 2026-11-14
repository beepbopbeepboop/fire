# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — part 5: a call through a callable-valued parameter whose argument is a generator-handle local, in a compiled generator body

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (SPLIT). This part fixes ONE named residual shape measured 2026-11-13; it does NOT add a new subsystem.

Sister: `COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part4.md` (the `parse_table` tuple-`for`-over-a-module-qualified-generator shape). `COMPILE_FAIL_Tools_c-analyzer_c_common_tables-part3.md` is the end-to-end closer that depends on both.

## Measured shape (2026-11-13, this tree)

The second of the two named refusals in `python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py` (see part 4 for the run; peak 0.2 GB, child exit 1):

    read_table: a call through the callable-valued parameter '_get_reader' passes an argument whose C type is not statically a word, string or container.

The site is c_common/tables.py:115, in `read_table` (cpp C++20-coroutine path):

    lines = strutil._iter_significant_lines(infile)      # :102
    ...
    for row in _get_reader(lines, delimiter=sep or '\t'):  # :115
        yield tuple(fix_row(row))

- `lines` is a compiled-generator HANDLE local: a module-qualified call to `strutil._iter_significant_lines` (c_common/strutil.py:37 — A3-lowered, no kwonly params), resolved at the assignment by `_cpp_resolve_generator_call_api` / `_cpp_emit_generator_start_expr` and tracked in `_cpp_generator_var_api`;
- `_get_reader` is the callable-valued parameter (default `csv.reader` — the tabled foreign callable of part 2's world, commits 4cb02b8c1 / 7e6a8ac5c), so the call is packed by the DYNAMIC call path.

## Why it is refused today

`cpp_core._cpp_dyn_call_expr` (cpp_core.py:1875) packs a call through a callable-valued parameter into a positional `MojoList *` + keyword `MojoDict *` for `mojo_dyn_call`. Its argument loop (cpp_core.py:1906-1937; the kwarg twin at :1938-1962) admits only `int64_t` / `char *` / `MojoList *` / `MojoDict *` / `MojoSet *` / `double` — a generator handle's C type is none of those, so it raises the refusal at :1927. The handle is a perfectly good iterable at RUNTIME (a `csv.reader` takes any iterable of strings); the emitter just has no way to hand it over yet.

## Goal

Materialize the handle argument, then pack the materialization:

1. In `_cpp_dyn_call_expr`, when an argument (or kwarg) expression is a generator-handle local — an `IdentExpr` tracked in `gen._cpp_generator_var_api` (the same predicate the `for x in <handle>` branch at cpp_core.py:9466-9525 and the `next()` case at :4670 use) — first emit a fresh `MojoList *` and drive the handle to exhaustion over the identical `{base}_resume`/`{base}_value` protocol that branch uses, appending each value as the handle's registered `value_ctype` (here `char *` lines: `mojo_list_append_str`; the exhaustion-vs-exception disambiguation that branch already does is NOT needed for materialization — a real exception SHOULD propagate out of the call, so do not swallow it).
2. Pack the fresh list as a container argument (the `MojoList *` slot already admitted at :1922); the csv.reader tabled runtime iterates a `MojoList *` of strings, so the tabled for-loop branch (cpp_core.py:9337-9360) consumes the result unchanged.
3. Apply the same materialization to the KWARG path (:1952), so `_get_reader(lines=lines)` cannot reach the second refusal message.
4. Keep the named refusal for arguments whose static ctype is a NON-handle unknown (the `:1927` message stays for genuinely unrepresentable arguments — no silent widening).

Guardrails: a handle argument in an expression the emitter cannot resolve as a handle (no `_cpp_generator_var_api` entry, e.g. an inlined call) must still refuse by name rather than guess; do NOT touch part 4's shape (the `for`-loop routing in `parse_table`); no new runtime — the materialization reuses the existing handle-drive loop and the existing list appendors. If the csv.reader runtime cannot iterate a list of strings (measure; it should — part 2's regression feeds it a list), STOP and file a fresh part.

## Acceptance

- The Done-when regression below passes: the fixture BUILDS, runs, and its stdout matches CPython on the same files (the rows csv.reader parses OUT OF the materialized handle come out right).
- Re-run the parent's build (`Done when` of part 3): `MOJO_DEBUG=1` no longer reports the `_get_reader` argument shape in `read_table`; the only remaining refusal, if any, is part 4's.
- The suite's `gimplegenerators` job (`python3 test_gimple_generator_runner.py`) stays green — in particular `_regression_read_table_callable_reader` (list argument) and `_regression_read_table_callable_reader_untabled_refusal` must not regress.
- No whole-closure compile, no `make gate`; the integrator runs the gate over the landing.

## Done when

```
python3 tools/memslot.py --gb 8 --label tables-part5 -- python3 -c "import test_gimple_generator_runner as t; t._regression_tables_callable_param_generator_handle_arg()"
```

prints `PASS  tables_callable_param_generator_handle_arg` (file: `test_gimple_generator_runner.py`; on the 2026-11-13 tree it FAILs with the refusal quoted above). Measured 2026-11-13: the same fixture with `lines = entries` (a list, no handle) already compiles and matches CPython, so the regression is red only for this shape. When it passes, wire the call into `run_tests()` in the same commit.

## References

- Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (Status 2026-09-30: the foreign-A3-generator handle machinery, commit 93eacde6; 2026-10-29/30: the callable-valued-parameter plan).
- Sites: `mojo/backend_gimple/cpp_core.py` (`_cpp_dyn_call_expr` :1875, the handle-drive `for` branch :9466-9525, the tabled-callable for branch :9337-9360, `_cpp_generator_var_api`), the csv.reader runtime entry from 7e6a8ac5c.
- Real sources: `.tmp/ca/c_common/tables.py` (:84-116 `read_table`), `.tmp/ca/c_common/strutil.py` (:37-42 `_iter_significant_lines`), copied per the parent doc's Scope step 1.
