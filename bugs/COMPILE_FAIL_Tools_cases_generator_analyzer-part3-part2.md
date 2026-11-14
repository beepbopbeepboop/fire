# COMPILE_FAIL_Tools_cases_generator_analyzer-part3-part2: analyzer binary runs and matches CPython on bytecodes.c

Part 2 of 2 of `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer-part3.md`
(which is part 3 of the original `COMPILE_FAIL_Tools_cases_generator_analyzer.md`).
Part 1 (the module-scope `globals()` support in the compiled path) makes the
`globals()` use in `lexer.py` work; this part owns
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

## Status (2026-11-13, measured on master `89ed58ab8`, before part 1)

Landed in this lane (the end-to-end run itself is still blocked on part 1):

1. **The 5 undefined entry points: root-caused and the report fixed.** Four of
   the five are NOT undefined — their bodies ARE in the dylib, under a
   differently-hashed overload suffix: the source scan hashes the signature's
   param types as parsed from source, codegen hashes the LIVE inferred types,
   and the two disagree, so the cross-check found neither the expected symbol
   nor the raw name and classified the entry "declared with no definition in
   this dylib" (a false claim — measured: the entry names
   `std_collections_string_string_ord_9f63a2`, the dylib defines
   `std_collections_string_string_ord_d719e0`; same shape for `ascii`, `atol`
   [defined as `..._string_mojo_atol_e253d6`], and `standardize_string_slice`
   [defined as `..._parsing_integers_standardize_string_slice_d719e0`]). This
   is the export-table side of the suffix group in
   `bugs/mid/CODEGEN_stdlib_dylib_lazy_undefined_refs.md` (the codegen fix
   itself is that lane's). The fix landed here is the cross-check itself:
   `build_stdlib_dylib.classify_export_entries` — the ONE classifier behind
   the three call sites (build, runtime_export_entries, optional units), which
   carried three copies of the check — now reports a suffix-mismatched
   definition as misresolved and NAMES the definition that exists. The build
   line went from `2049 of 2054 ... (0 misresolved, 5 undefined)` / `declared
   with no definition in this dylib: standardize_string_slice, ord, ascii,
   atol, py_tokenize` to `(4 misresolved, 1 undefined)` / `declared with no
   definition in this dylib: py_tokenize` (advertised count unchanged: 2049).
   `py_tokenize` is the one genuinely undefined entry: a `fire_runtime.h`
   declaration satisfied by the self-hosted compiler image, not the runtime
   (fire_runtime.h's own comment). Regression: `test_export_table_suffix_mismatch.py`
   (pins the invariant in both states; fails before — the old logic puts all
   four in `undefined` and the report half FAILs on the pre-fix build log —
   passes after; `test_runtime_dylib.py` 130/130).
2. **Reachability (acceptance item 3): none of the five is reached on the
   `bytecodes.c` path — provable, not just unreachable-at-runtime.** The
   compiled analyzer's binary has 217 undefined symbols; ZERO of them is any
   of the five (raw or mangled). Its 190 dylib-resolved symbols are ALL
   runtime-C: `re` lowers to `mojo_re_compile/_exec/_call`,
   `itertools.zip_longest` (analyzer.py:376) lowers to a plain index loop over
   the two lists, `dataclasses` to the runtime's class-registration machinery,
   and the only three non-`mojo_` names (`int_read`/`int_write`/
   `char_replace_impl`) are `fire_runtime.c` functions. The execution never
   enters a `_std_` Mojo module object. The one dylib-INTERNAL reference to a
   missing symbol is `_mojo_atol` (plain), called from `StringSpan.__int__`
   (`string_span.mojo:928`) and `_cpython.mojo:288`'s version parsing — neither
   reachable from the analyzer (it imports `re`, `dataclasses`, `itertools`,
   `typing`, `collections.abc`, `lexer`, `parser`, none of which call into
   those objects); that reference belongs to the lazy-undefined-refs lane.
3. **The `StaticTuple` CAUGHT line: explained, with evidence (harmless).**
   Reproduced by compiling `std/simd.mojo` fresh through the dylib's own job
   (`_compile_module_job`, `use_cache=False`): exactly the two
   `CAUGHT_IN_MAIN_LOOP: cannot materialize instantiation of generic
   'StaticTuple': its bracket arguments` lines, and the module still compiles
   (`error=None`, object produced) — a caught, non-fatal refusal from
   `emit_calls.py`'s materialization guard. `std/simd.mojo` is the only stdlib
   module that brackets `StaticTuple` with a parameter-dependent (non-
   converging) argument (lines 2647, 2917). The line appears in an analyzer
   build only when `std/simd.mojo` is recompiled inside `build_stdlib()` (a
   CAS hit prints nothing) — the doc's measurement was such a build. The
   analyzer's binary references no simd symbol, so the affected SIMD methods
   are not on this input's path.
4. **Re-measured the Done-when test at this HEAD: build exit 0, zero
   `error:` lines; the binary still exits 1 with `Unhandled exception:` —
   the part 1 blocker, unchanged by the work above.**

## Remaining (the part 1 blocker)

* `test_analyzer_build.py` cannot pass until part 1 (module-scope `globals()`
  in the compiled path, claim `bug:COMPILE_FAIL_Tools_cases_generator_analyzer-part3-part1`,
  a separate worker's lane) lands: the analyzer imports `lexer`, whose
  module-scope `globals()` table-building is what the binary dies on.

## Exact next step (once part 1 is on master)

1. Re-run `python3 test_analyzer_build.py` (wrapped in
   `tools/memslot.py --gb 8`). It must print
   `PASS  analyzer.py builds and matches CPython`.
2. If the binary runs but diverges, follow the Plan step 2 (first differing
   `cmp` line of stdout, work back to the producer) — nothing in this doc
   predicts a divergence, and the reachability evidence above says the five
   entry points will not be the cause.
3. Close per the Plan step 4: `git rm` the original
   `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md` and this part's
   parent `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer-part3.md`,
   remove their rows from `bugs/hard/README.md`, delete
   `docs/cases-generator-analyzer-plan.md`, then
   `python3 tools/dangling_doc_refs.py --ratchet` in the same commit.

## Out of scope

* The module-scope `globals()` lowering itself — part 1.
* Link-mode sibling resolution and the `fire.py run` sibling-import path
  (`import lexer` fails in the interpreter today).
* Other `Tools/cases_generator` files (`cwriter.py`, `plexer.py`, ...).
