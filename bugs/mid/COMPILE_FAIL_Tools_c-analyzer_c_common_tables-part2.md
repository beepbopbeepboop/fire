# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py — part 2: `with <call through a tabled foreign callable>(...) as <name>:` in a plain compiled generator body

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (SPLIT). This part does NOT fix the bug end-to-end.

Class argument: mid, not easy — this needs a runtime-backed manager model (a real `open(...)` entry point honoring `newline=''`, a handle binding for the alias, and a close/exit on the normal path) wired through the cpp emitter's plain-generator `with` arm, not a predicate widening.

## Goal

A compiled generator (plain, non-async, cpp C++20-coroutine path) lowers

```python
with <tabled foreign callable>(...) as <name>:
```

instead of refusing with

```
`with <context manager> as <name>:` over a manager this codegen does not model is not supported in a compiled generator body: the manager expression is never evaluated, so the bound name would be uninitialised
```

The current trigger is `read_table`'s

```python
if isinstance(infile, str):
    with _open(infile, newline='') as infile:
```

(tables.py:91-92), where `_open=open` is a default-valued callable parameter. Measured 2026-11-12 on this tree: `MOJO_DEBUG=1` names this exact refusal for `read_table` in pass 1 and both retry passes. The refusal is DELIBERATE — binding a name to a value that is never computed miscompiles the body — so this part must genuinely EVALUATE the manager expression (call the runtime entry point once) and bind the alias to the runtime object it produces, then emit the exit/close on the normal completion path.

## Scope

1. Recognition: `_cpp_with_stmt`'s plain-synchronous arm (`mojo/backend_gimple/cpp_core.py`, the section headed `--- synchronous with handling (existing behavior) ---`, ~line 8587) calls `_cpp_with_guard_type_name` (`mojo/backend_gimple/cpp_async.py:195`); the manager `_open(infile, newline='')` resolves to the name `_open`, which is in no recognized set, so the arm reaches `if item.alias is not None:` and raises `_UnsupportedGeneratorShape`. Give the tabled foreign callables a manager model for this arm.
2. Mechanism options (decide, implement one):
   a. Extend `_FOREIGN_CALLABLES` (`mojo/middle/types.py`, ~line 2697) and `_RUNTIME_CALLABLE_VALUES` (`mojo/middle/calls_shared.py`, ~line 450) for `open` with a return ctype (a file handle) plus a sibling table/entry for its context-manager protocol — mirroring how `csv.reader` was tabled (commits 373cf8633, 4cb02b8c1, 7e6a8ac5c).
   b. Or a dedicated intrinsic-guard case beside the `tempfile.TemporaryDirectory` branch in the same function, narrowly for `open(...)`.
   Recognize the parameter's DEFAULT (`_open=open` — a call through a callable-valued parameter whose tabled default is `open`), not every identifier spelled `_open`.
3. Runtime: the ordinary GIMPLE path already lowers builtin `open` to `mojo_open_file(char *) -> int64_t` (`gimple_codegen.py:859`, `runtime/fire_runtime.c` ~line 11263, declared `fire_runtime.h:2317`) with `mojo_close(MojoFileHandle)` ready (`fire_runtime.c:963/1101`, `fire_runtime.h:2306-2317`); the richer `MojoFileHandle mojo_open(char *, char *)` exists too (`fire_runtime.c:944/1082`). A lowering must honor the `newline=''` keyword argument — do NOT silently drop it (read the file's lines verbatim; if the chosen entry point cannot express `newline=''`, implement that mode or refuse by name rather than change semantics). Check what the Mojo stdlib re-exports before adding a new entry point.
4. Lowering: evaluate the manager ONCE before the body; bind the alias (`infile` in the trigger — the recursive `read_table(infile, ...)` then sees a non-`str`, which is the intended branch); emit the body; call the close/exit on the normal path. This arm has no exception handling of its own — match the structure of the intrinsic `tempfile.TemporaryDirectory` guard for where the exit goes, and if prompt exit on an exception-unwinding path is not achievable in this narrow model, say so in the part's Status update rather than drop the close silently.
5. Keep the refusal for managers that stay unmodeled — an untabled callable default, or a manager name with no entry, keeps today's refusal text byte-for-byte.
6. The alias must bind the handle for real; do not declare an uninitialised `int64_t` "placeholder" as before this change (that was the miscompile being prevented).
7. Out of scope: making the BOUND file object iterable (`strutil._iter_significant_lines` doing `for line in bound` over a `mojo_open_file` handle) — that is part 3. This part's proof is the narrow regression below.

## Acceptance

- The regression named in Done when passes; the `with <context manager> as <name>:` refusal no longer fires for the tabled-`open` shape in pass 1 or the retry passes (`MOJO_DEBUG=1` on the build command in the parent doc's Status 2026-11-12 entry); the untabled-manager negative half still refuses by name.
- No `make gate`, no whole-closure compile; the single regression plus the `MOJO_DEBUG=1` observation is the verification.

## Done when

Add `_regression_with_tabled_open_in_generator` to `test_gimple_generator_runner.py` — a compiled generator (cpp coroutine path) doing `with open(<path>) as f:` under the cpp path, exercised through the runner's CPython-comparison convention (the file contents read/bound object behaves as CPython's), plus the untabled negative half (an untabled manager default still yields the current refusal text, mirroring `_regression_read_table_callable_reader_untabled_refusal`). Then:

```
python3 tools/memslot.py --gb 8 --label gen-runner -- python3 -c "import test_gimple_generator_runner as t; t._regression_with_tabled_open_in_generator()"
```

passes.

## References

- Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md` (Status 2026-11-12 entry).
- Sites: `mojo/backend_gimple/cpp_core.py` — `_cpp_with_stmt` (the plain-synchronous arm; the `tempfile.TemporaryDirectory` intrinsic guard ~line 8599 shows where a modeled manager is special-cased), `mojo/backend_gimple/cpp_async.py` — `_cpp_with_guard_type_name` (~line 195), `mojo/middle/types.py` — `_FOREIGN_CALLABLES` (~line 2697), `mojo/middle/calls_shared.py` — `_RUNTIME_CALLABLE_VALUES` (~line 450), `runtime/fire_runtime.c` / `fire_runtime.h` — `mojo_open_file`, `mojo_open`, `mojo_close`, `MojoFileHandle`.
- Reproducer: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py:91-101`; copy `c_analyzer/` and `c_common/` into `.tmp/ca/` for builds.
- Out of scope (part 3): iteration over the bound handle, and the end-to-end `tables.py` build.
