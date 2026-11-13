# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — part 1: mixed-scalar tuple literal at a raise-message argument position in a compiled generator body

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (SPLIT). This part does NOT fix the bug end-to-end.

Class argument: mid, not easy — the naive fix (make the element ctypes "agree" by defaulting un-inferrable elements to `int64_t`) hands a `char *` to `mojo_list_append_int` and is exactly the silent-miscompile trap the `_cpp_typed_list_elem` docstring refuses; the raise path additionally treats the message as a `char *` that consumers print and compare (see Scope 3).

## Goal

A compiled generator (cpp C++20-coroutine path) lowers `raise Exc((a, b))` whose message argument is a tuple/list literal whose elements infer DIFFERENT scalar kinds — the current trigger is

```python
raise NotImplementedError((header, line))
```

(`c_common/tables.py:176`, `parse_table`), instead of refusing with

```
a list-literal argument with mixed element types is not supported at a compiled-generator call in a coroutine body
```

Measured 2026-11-12 on this tree: `python3 fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py` (sources copied from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`) still fails, and `MOJO_DEBUG=1` names this exact refusal for `parse_table` in pass 1 and both retry passes (via `mojo/backend_gimple/module_gen.py`'s eligibility loop).

After this part, `parse_table` gets PAST this shape; whatever it refuses on NEXT (if anything) is part 3's territory, not this part's.

## Scope

1. `mojo/backend_gimple/cpp_core.py` — the refusal is raised by `_cpp_list_literal_arg_expr` (~line 2167) through `_cpp_typed_list_elem` (~line 2128) when the elements' inferred scalar kinds disagree. It is reached from `_cpp_expr`'s `ListExpr`/`TupleExpr` arms (~lines 3399-3404) and from `_cpp_raise_stmt` (~line 11251, the exception-message argument — `raise NotImplementedError((header, line))` lowers the tuple as the message).
2. The elements here are NOT nested containers or struct pointers, so the existing `_cpp_boxed_list_literal_expr` (~line 2074) does not cover them; its mixed-scalar analogue is precisely the gap. Decide and implement one honest representation for mixed-scalar literals at this position (e.g. extend the boxed representation, or build a real `char *` message for the raise case). Do NOT default un-inferrable elements to `int64_t` to make the kinds "agree".
3. **Trap:** the raise lowering stores the message as `_MojoCppExc{ (int64_t)tag, msg_cpp, (void *)msg_cpp }` and the catch/pending-rethrow machinery treats `msg_cpp` as a `char *`. A boxed `MojoList *` cast to `char *` there is a wrong-but-exit-0 miscompile whenever the exception message is printed or compared. If the chosen fix boxes the literal, every consumer of a raise message (`_cpp_try_stmt`'s pending-rethrow path, `mojo_exc_msg_get` call sites) must agree on the representation. If instead the fix builds a string message for the non-string raise argument, say so in the commit message and in this part's Status update.
4. Keep the refusal for shapes that stay unsupported — e.g. an element whose ctype cannot be inferred at all keeps its existing refusal text (`an element of a list-literal argument of a compiled-generator call has a value kind that cannot be resolved in a coroutine body`).
5. Add the regression named in Done when. Do NOT flip any existing refusal regression; do NOT touch the untabled-callable refusal pinned by `_regression_read_table_callable_reader_untabled_refusal`.

## Acceptance

- The diagnostic `a list-literal argument with mixed element types is not supported at a compiled-generator call in a coroutine body` no longer fires for the `raise Exc((header, line))` shape — in pass 1 and in both retry passes (visible with `MOJO_DEBUG=1` on the build command above).
- Elements whose ctype cannot be inferred still refuse by name; untabled callable defaults still refuse by name; the csv.reader CPython-comparison regression (`_regression_read_table_callable_reader`) still passes.
- Verification is the one regression below (0.1-0.2 GB, seconds) plus the `MOJO_DEBUG=1` build observation. No `make gate`, no whole-closure compile.

## Done when

Add `_regression_raise_mixed_tuple_literal_in_generator` to `test_gimple_generator_runner.py` — a compiled generator (cpp coroutine path) that raises with a mixed-scalar tuple message and is exercised through the runner's CPython-comparison convention, asserting the compiled binary runs and the raise behaves as CPython's does (or asserting the pre-fix diagnostic is gone, matching the runner's existing style). Then:

```
python3 tools/memslot.py --gb 8 --label gen-runner -- python3 -c "import test_gimple_generator_runner as t; t._regression_raise_mixed_tuple_literal_in_generator()"
```

passes.

## References

- Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (Status 2026-11-12 entry).
- Sites: `mojo/backend_gimple/cpp_core.py` — `_cpp_typed_list_elem`, `_cpp_list_literal_arg_expr`, `_cpp_boxed_list_literal_expr`, `_cpp_expr` (ListExpr/TupleExpr arms), `_cpp_raise_stmt`, `_cpp_try_stmt`; `mojo/middle/exprtypes.py` (`_infer_simple_expr_ctype`, `_UnsupportedGeneratorShape`).
- Reproducer: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:176`; copy `c_analyzer/` and `c_common/` into `.tmp/ca/` for builds.
- Out of scope (tracked by part 3): `parse_table`'s remaining shapes — `yield row, filename` (tuple yield), `strutil.parse_entries(entries, ignoresep=sep)` delegated with a keyword argument and tuple-unpacked loop target.
