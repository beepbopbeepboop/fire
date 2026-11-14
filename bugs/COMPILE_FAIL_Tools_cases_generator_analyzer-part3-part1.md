# COMPILE_FAIL_Tools_cases_generator_analyzer-part3-part1: module-scope `globals()` in the compiled path

Part 1 of 2 of `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer-part3.md`
(which is part 3 of the original `COMPILE_FAIL_Tools_cases_generator_analyzer.md`).

## Goal

Make the compiled path support the one module-scope `globals()` idiom that
blocks the analyzer binary. `Tools/cases_generator/lexer.py` (CPython 3.14.6,
lines 76-78) does:

```python
operators = {op: pattern for op, pattern in globals().items() if op == op.upper()}
for op in operators:
    globals()[op] = op
```

Compiled, `globals()` lowers to a weak `globals: unavailable in compiled mode`
stub that returns nothing, so `operators` is empty. Every analyzer run then
prints that line and raises `Unhandled exception:` with no message and exits 1
(measured on the current tree: build exit 0 with zero `error:` lines, binary
exit 1 on every input, including `/dev/null`).

## Current state (measured 2026-11-13, HEAD `89284bb85`)

* `python3 fire.py build -o .tmp/ca/analyzer-bin .tmp/ca/cases_generator/analyzer.py`
  under `tools/memslot.py --gb 8`: **exit 0**, zero `error:` lines, peak 0.6 GB.
  The build-time CAUGHT_IN_MAIN_LOOP and undefined-runtime lines are in part 2.
* `.tmp/ca/analyzer-bin` on `/Users/mrs/net/Python-3.14.6/Python/bytecodes.c`:
  stdout empty, stderr `globals: unavailable in compiled mode` then
  `Unhandled exception:`, exit 1. CPython prints 2892 lines, exit 0.
* The parts landed before this one: part1 (`1cd5648e3`, positional class
  patterns via `__match_args__`) and part2 (`7ff70b5a8`, sibling struct
  identity). The `str()/repr()` None-guard (`b00e6669e`) is in.

## Acceptance

* `python3 test_module_globals_compiled.py` prints `PASS`. The test is written
  and currently fails with the stub output (empty dict, the `globals:` line).
* A module-scope `globals()` read (`.items()`/`.keys()` over the names bound
  earlier in the module) yields the same dict CPython gives.
* The rebinding loop `globals()[op] = op` over that dict has the same effect on
  later module-level reads (`ASSIGN` becomes the string `"ASSIGN"`), as in CPython.
* No `globals: unavailable` stub is emitted for a module-scope `globals()` in
  the closure of a program this part's test builds.
* Interpreter (`fire.py run`) output of the same program is unchanged.

## Done when

`python3 test_module_globals_compiled.py` exits 0 and prints
`PASS  module-scope globals() matches CPython in the compiled path`. The test
builds the program through `tools/memslot.py --gb 8` (a few seconds, under 1 GB).

## Plan (files, ordering, the decision that is yours to make)

1. Find where a `globals()` call is lowered: `gimple_codegen.py` (grep for
   `unavailable in compiled mode` and for the `globals` builtin name). The stub is
   the fallback for an unknown builtin; the module-scope case needs its own
   lowering before the fallback.
2. **Decision — the write side.** The read side is static: at module scope the
   compiler already knows which names are bound before the call. The write side
   `globals()[op] = op` takes its name from a runtime value. The bounded
   answer: when the loop iterates over a dict built from `globals()` in the same
   module, the key set is the compile-time set of those names, so the loop can
   be expanded to one module-level rebinding per key. If the iterable is not
   provably that set, refuse the construct with a clear diagnostic at compile
   time (not a stub), and say so in the commit. Do not generalize to arbitrary
   runtime name binding in this part; that is a different, larger project.
3. Add the read/write lowering, keeping one implementation of the module-scope
   name table (no parallel copy of the interpreter's own namespace logic).
4. Run `python3 test_module_globals_compiled.py` (the Done-when test). Then the
   interpreter's own check for the same program: `python3 fire.py run` on the
   test's program source, compared to its CPython output.
5. Run the targeted existing tests for the touched codegen path (for example
   `python3 test_match_class_pattern_positional.py`) so the change is not
   silently regressing the part1/part2 work.

Stop rule: if step 2 cannot be bounded to a compile-time key set, do not widen
it. Commit the refusal diagnostic plus this doc's Status with the exact reason,
and report `PARTIAL`.

## Out of scope

* The rest of the analyzer's runtime (undefined entry points, StaticTuple) — part 2.
* `fire.py run` sibling-import path (`import lexer` fails in the interpreter
  today; that is a separate interpreter gap, not this part).
* Any other `Tools/cases_generator` file.
