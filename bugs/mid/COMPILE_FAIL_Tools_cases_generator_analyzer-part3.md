# COMPILE_FAIL_Tools_cases_generator_analyzer-part3: analyzer.py builds and matches CPython on real input

Part 3 of 3 of `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md`.

## Goal

Close the original doc: `python3 fire.py build` of
`Python-3.14.6/Tools/cases_generator/analyzer.py` exits 0 with no `error:`
lines, the binary runs, and its analysis output on a real `bytecodes.c` is
byte-identical to CPython running the same analyzer. This part owns the
end-to-end acceptance; the code fix is part2 (sibling struct layout); the
parenthesized ternary is already landed (b00e6669e). Part1 is an independent correctness fix on the
class-pattern path and does not gate the build.

## Current state (measured 2026-11-11, HEAD `d210765a2`)

```sh
mkdir -p .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/cases_generator .tmp/ca/
python3 tools/memslot.py --gb 8 --label analyzer-build -- \
    python3 fire.py build -o .tmp/ca/analyzer-bin .tmp/ca/cases_generator/analyzer.py
```

Exit 1 in **15.3 s**, peak 0.1-0.6 GB across two runs (well inside 8 GB).
26 `error:` lines on the 2026-11-12 re-run (27 on the 2026-11-11 measurement; the
two `analyzer.py:194` ones are gone with b00e6669e):

| family | count | part that fixes it |
|---|---|---|
| sibling `IfStmt`/`ForStmt`/`WhileStmt` layout (`has no member named if_/body/for_/header/while_`, plus the constructor int64-vs-MojoList assignments) | 22 in `parsing.py` + 3 misattributed to `plexer.py` | part2 |
| `analyzer.py:194:10: expected expression before '(' token` (reported twice, same site) | 2 | landed, b00e6669e |

Two things the original doc's older entries name are **already fixed in this
tree** and must not be re-investigated as if open:

* the `var_decl` error at `analyzer.py:723` — the build now emits only a
  `variable '_t147' set but not used` warning there, no error. Family A is gone.
* the class-pattern refusal (`case parser.InstDef(name):`) — the compiled path
  now lowers it. Its semantics are part1's subject; it is not a build blocker.

There is no `link-mode` stubbing in this build: the generated single `.ci`
contains `parsing.py`'s functions inline, which is why its errors surface in
this unit. The command is the inline/`do_imports` path, not the silently
stubbing link path the old entry describes.

## Plan

1. **Preconditions.** Confirm part2's change is present (the sibling typedef
   carries `if_`/`body`) and that b00e6669e (the `str()`/`repr()` None guard as
   control flow, not `(... ? ... : ...)`) is in the tree. If part2 is not landed,
   stop and report it rather than duplicating its fix here.
2. **Re-run the build command above.** Require exit 0 and no `error:` line.
   If a new error family appears, root-cause it here:
   * if it is a small, self-contained lowering defect (same size as the b00e6669e ternary fix),
     fix it in this part with a regression test;
   * if it is a new architectural family (another same-bare-name table, a
     refused construct, link-mode policy), file a new doc for it, commit that,
     and report `PARTIAL` rather than silently widening this part.
3. **Run the real input.** From the copied directory:

   ```sh
   <tmp>/analyzer-bin /Users/mrs/net/Python-3.14.6/Python/bytecodes.c > compiled.txt
   (cd <tmp>/cases_generator && python3 analyzer.py \
       /Users/mrs/net/Python-3.14.6/Python/bytecodes.c > cpython.txt)
   cmp compiled.txt cpython.txt
   ```

   The doc's 2026-08-25 entry recorded byte-identical output (2892 lines:
   Uops/Instructions/Families/Pseudos) on exactly this input. `analyzer.py`
   reads only its argv filenames, so the copied directory and the real
   `bytecodes.c` are enough.
4. **Close the original doc** in the same commit that makes this green:
   `git rm bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md`; remove
   its row from `bugs/hard/README.md`; delete the stale
   `docs/cases-generator-analyzer-plan.md` (a three-step plan that claims
   fixing `_gen_stmt_MatchStmt` alone is enough — it is not); run
   `python3 tools/dangling_doc_refs.py --ratchet` and rewrite/remove the
   citations it names rather than adding to the baseline.

## Acceptance

* Build: exit 0, zero `error:` lines, reported peak under the 8 GB reservation.
* Run: the compiled analyzer's stdout on `Python/bytecodes.c` is
  byte-identical to `python3 analyzer.py` on the same file, and the binary
  exits 0.
* `python3 test_match_class_pattern_positional.py` and the part1/part2
  regression tests still pass.
* Self-host: the integrator's `make gate` is the confirmation that the part2
  identity change did not alter the compiler's own struct set. This part does
  not run the whole-closure/bootstrap chain itself.

## Done when

`python3 test_analyzer_build.py` exits 0. The file is on disk; it builds through
its own memslot wrapper, and on the 2026-11-12 tree it fails at the build step
(exit 1, 26 error lines, first `plexer.py:292:5: ... 'ForStmt' has no member named 'header'`).

The test:

1. locates the CPython source tree (`$PYTHON_SRC` or
   `/Users/mrs/net/Python-3.14.6`); if `Tools/cases_generator/analyzer.py` or
   `Python/bytecodes.c` is absent, prints a clear `SKIP` line and exits 0 (the
   part is not proven on that machine, but the test is honest about it);
2. copies `Tools/cases_generator/` under the project's `.tmp/` (never `/tmp`)
   and runs the memslot-wrapped build command above with
   `subprocess.run`, asserting exit 0 and no `error:` in the output;
3. runs the compiled binary and CPython's analyzer on `Python/bytecodes.c` and
   asserts identical stdout and both exit 0;
4. on success prints `PASS: analyzer.py builds and matches CPython`.

It fails on the current tree at step 2 (build exit 1, 26 error lines). Expected cost
on this machine: ~20 s and <1 GB, i.e. the same size as the `gimple` test.

## Out of scope

* The class-pattern binding correctness (part1) — independent of this build.
* Link-mode sibling resolution and the `fire.py run` sibling-import path.
* Any other `Tools/cases_generator` file (`cwriter.py`, `plexer.py`, ...):
  their own docs own those, and this part only requires the analyzer build.
