# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — part 2: cpp `for` over call-through-callable-param with tabled iterator element type

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (SPLIT). This part does NOT fix the bug end-to-end.

Depends on: part 1 (foreign-callable table exists and callable-valued params with tabled defaults are typed as callable with signature/element info).

## Scope

Teach the cpp backend to lower `for <target> in <call through a callable-valued local/parameter>` when the callee has a foreign-callable table entry that provides the returned iterator's element ctype.

Concrete work (per parent plan, adapted to corrected sites):
1. `mojo/backend_gimple/cpp_core.py` `_cpp_for_stmt`: add a branch after the generator-handle branch and before the generic path for `for <target> in <call through a callable local/param>` whose callee's table entry gives an iterator element ctype. Bind the loop target to that element ctype and provide the element/row access needed for bodies like `fix_row(row)` / `tuple(fix_row(row))`.
2. If the callee/entry is absent or cannot supply an element type, keep refusing by name (preserve the current honest refusal for unknown callees; do not silently miscompile).
3. `mojo/middle/infra_infer.py`: consult the same table as needed so the parameter/call typing is consistent for this path (completing the step 2 intent from the parent plan where it applies to this lowering).
4. Measure `read_table`'s cpp/coroutine eligibility (`coro.py` `_eligible`, kwonly params noted in parent) before declaring the path complete for `read_table`; if ineligible, address or explicitly scope the acceptance to an eligible equivalent shape and record the eligibility finding.

`tables.py` end-to-end compile, `csv.reader` runtime implementation, and flipping the refusal regression to a stdlib-output comparison are out of scope (part 3).

## Acceptance

- A narrow `read_table`-like case (callable-valued param with a tabled foreign default/callee iterated in a `for` in a compiled generator/coroutine body) progresses past the current refusal (`"a \`for\` over a call through the callable-valued local/parameter '_get_reader(...)'..."` / `unsupported for-loop iterable type: CallExpr`) to a typed loop body. The loop target and element access are typed from the table entry (not `int64_t` fallback).
- Untabled/unknown callable callees still produce a named refusal (existing/appropriate regression remains or is added narrowly).
- No whole-closure compile, self-host build, or full gate; verify with the narrowest covering test/command only (wrap any compile in `python3 tools/memslot.py --gb 8 --label <what> -- <cmd>`).

## References

- Parent doc: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (plan steps 2-4, "Quick proof for the next round" / coro eligibility note).
- Key sites: `mojo/backend_gimple/cpp_core.py` `_cpp_for_stmt`, `mojo/middle/infra_infer.py`, `mojo/backend_gimple/coro.py` eligibility as applicable, foreign-callable table from part 1.
