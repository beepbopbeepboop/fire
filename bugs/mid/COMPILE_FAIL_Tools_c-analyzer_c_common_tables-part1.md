# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — part 1: foreign-callable signature table and param typing for defaults

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (SPLIT). This part does NOT fix the bug end-to-end.

## Scope

Introduce the foundation for callable-valued parameters whose default is a known foreign/C-implemented callable (recommended decision (A) in the parent doc), starting with `csv.reader`.

Concrete work:
1. Add a table/registry of known foreign callables that the emitter can represent. At minimum include `csv.reader` with enough signature/shape information for downstream typing: the callable ctype and the iterator element type it yields (`list[str]` / row shape as representable in this compiler), as needed by later steps.
2. In `mojo/middle/infra_infer.py` `_infer_param_types` (~:265), when a parameter has a default whose value resolves to a name in that foreign-callable table, bind the parameter to that callable's ctype (the `_CPP_CALLABLE_CTYPE`-family signature the table gives) instead of the `int64_t` fallback.
3. Keep `mojo/middle/types.py` `_cpp_lambda_ctype` (lambda-literal classification only, ~:2472) unchanged for this case; defaults on `def` parameters are typed by `_infer_param_types`, not by `_cpp_lambda_ctype` (parent doc 2026-10-30 correction).

This part does **not** require implementing the `for`-over-call-through-callable-param branch in `cpp_core.py`, runtime iteration for `csv.reader`, or compiling `read_table`/`tables.py` end-to-end.

## Acceptance

- A narrow test or declared-param/type dump shows that a `def` parameter defaulted to a tabled foreign callable (e.g. `def f(..., _get_reader=csv.reader)` / the `read_table`-like signature) is inferred/bound as a callable with the table's signature, not as `int64_t`. This addresses the measured root cause that the parameter is not recognised as callable at all (parent 2026-10-02/2026-10-30 notes).
- The existing refusal behavior/tests for **untabled** callable-valued parameters remain intact (no regression): unknown foreign callable defaults/callees must still be refused by name rather than miscompiled.
- No whole-closure compile, self-host build, or full gate; verify with the narrowest covering test/command only (wrap any compile in `python3 tools/memslot.py --gb 8 --label <what> -- <cmd>` per project rules).

## References

- Parent doc: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (esp. 2026-10-30 correction, decision (A), implementation plan step 1/2, and 2026-10-02 note that `_get_reader` is currently `int64_t`).
- Key sites: `mojo/middle/infra_infer.py` `_infer_param_types`, `mojo/middle/types.py` `_cpp_lambda_ctype` (do not repurpose), foreign-callable table location chosen here.
