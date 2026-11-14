# COMPILE_FAIL_Tools_cases_generator_analyzer-part3-part2: analyzer binary runs and matches CPython on bytecodes.c

Part 2 of 2 of `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer-part3.md`
(which is part 3 of the original `COMPILE_FAIL_Tools_cases_generator_analyzer.md`).
Part 1 (`COMPILE_FAIL_Tools_cases_generator_analyzer-part3-part1.md`) makes the
module-scope `globals()` in `lexer.py` work in the compiled path; this part owns
the end-to-end run after it, and closing the original doc.

## Goal

With part 1 landed, the compiled analyzer runs to completion on CPython's
`Python/bytecodes.c` and its stdout is byte-identical to `python3 analyzer.py`
on the same file. Then close the original analyzer doc.

## Current state (measured 2026-11-13, HEAD `89284bb85`, before part 1)

Build (`tools/memslot.py --gb 8`, `fire.py build` of `analyzer.py`): exit 0,
zero `error:` lines. Build-time output this part must account for:

* `CAUGHT_IN_MAIN_LOOP: cannot materialize instantiation of generic 'StaticTuple': its bracket arguments`
  (a caught, non-fatal line — find which module and whether the binary reaches
  that code path).
* `export table: 2049 of 2054 runtime entry points advertised (0 misresolved, 5 undefined)`
  with `declared with no definition in this dylib: standardize_string_slice, ord, ascii, atol, py_tokenize`.
  Each of these is a runtime name the compiled analyzer may call; the ones
  reached on the `bytecodes.c` path are real blockers, the rest are not.

Binary today: exits 1 on any input with `globals: unavailable in compiled mode`
then `Unhandled exception:` (the part 1 blocker). CPython: 2892 lines of
Uops/Instructions/Families/Pseudos on `bytecodes.c`, exit 0.

## Acceptance

* `python3 test_analyzer_build.py` prints `PASS  analyzer.py builds and matches CPython`.
* The compiled binary exits 0 on `Python/bytecodes.c`; stdout `cmp`-identical to CPython.
* The 5 undefined runtime entry points: each is either provably not reached on
  this input (say so with the evidence) or implemented.
* `StaticTuple` caught-line: either explained as harmless with evidence, or fixed.

## Done when

`python3 test_analyzer_build.py` exits 0. It builds `analyzer.py` through
`tools/memslot.py --gb 8`, asserts exit 0 and no `error:` line, runs the binary
and CPython on `bytecodes.c`, and compares stdout. Expected cost ~20 s, < 1 GB.
(The test is already on the tree, written for the original part 3.)

## Plan

1. Start from part 1's landing. Re-run `python3 test_analyzer_build.py`. If it
   fails at the build step, the failure is new and is root-caused here.
2. If the binary runs but diverges, locate the first differing line of
   stdout (`cmp`), then find the code that produced it. Work from the binary,
   not from speculation: the analyzer prints each Uop/Instruction in order.
3. Resolve the 5 undefined entry points by reachability: for each one, find
   its call site in the closure (`grep` the generated `.ci` or `.c` under the
   build output) and state whether the `bytecodes.c` path reaches it. Implement
   only the ones that are reached, in the runtime, with a regression test.
4. Close the original doc in the commit that makes the test green:
   * `git rm bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md`
   * `git rm bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer-part3.md`
     (this part's parent, once the test is green)
   * remove its row from `bugs/hard/README.md`
   * delete `docs/cases-generator-analyzer-plan.md` (it is a stale three-step plan
     that claims fixing `_gen_stmt_MatchStmt` alone is enough — it is not)
   * run `python3 tools/dangling_doc_refs.py --ratchet` and rewrite or remove the
     citations it names; do not add to the baseline.
5. Run the targeted quick tests: `python3 test_match_class_pattern_positional.py`,
   `python3 test_module_globals_compiled.py` (part 1), and the Done-when test.

## Out of scope

* The module-scope `globals()` lowering itself — part 1.
* Link-mode sibling resolution and the `fire.py run` sibling-import path
  (`import lexer` fails in the interpreter today).
* Other `Tools/cases_generator` files (`cwriter.py`, `plexer.py`, ...).
