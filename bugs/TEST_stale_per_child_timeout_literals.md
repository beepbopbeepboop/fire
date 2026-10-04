# TEST_stale_per_child_timeout_literals: 217 per-child wall clocks are still literals

## Status

**Partly landed 2026-10-04.** Two things changed, and the second is the one
that makes the rest mechanical.

* `test_formal_sweep.py` (7 sites) and `test_formal_libc_symbol.py` (1, which
  also had its own file-local `BUILD_TIMEOUT = 300` / `RUN_TIMEOUT = 60`) are
  converted. Each site is classified where it is called, and the two in the
  sweep file that are **not** a child budget — the `communicate()` windows after
  a SIGTERM, and `codesign` — are named (`SIGTERM_DRAIN_S`, `SIGTERM_REAP_S`)
  with the reason at the declaration rather than forced into a constant that
  does not describe them. Both files re-run green
  (`test_formal_sweep.py` 124 tests OK; `test_formal_libc_symbol.py` 10/10).

* **Step 3 of "the next step" — the widening — is done, as a ratchet.**
  `test_suite.py`'s budget check now also asks the other direction, over every
  test file rather than only the importers, and
  `STALE_PER_CHILD_BUDGETS` is the census it compares against: a file that is
  converted loses its row (or the stale count fails), and a file that grows a
  literal fails until it is added with its count. `BUDGET_IS_THE_SUBJECT` holds
  the two files where a literal IS the subject (`test_memslot.py`,
  `test_suite.py`), each with its reason, and a row asserts the exemption list
  and the walk still agree — so an exemption cannot outlive the need.

  Measured with this tree's predicate (a `timeout=` KEYWORD off the AST, over
  both file spellings, derived trees skipped): **207 sites over 57 files**,
  after the 8 above, and after `test_formal_proof_breadth.py` grew two more
  sites of its existing `timeout=60` shape (`work/formal25-6`) and its census row
  moved 3 -> 5 with them. The file count did not move: a file that gains a
  literal is a file already in the table. That is smaller than the 217/63 below for two measurable
  reasons: a grep counts `timeout=NN` occurrences that are not call keywords,
  and it walks `build/` and the other derived trees.

**Still to do, and it is per-file reading in the owning area's lane:** the
remaining 54 rows, cheapest first, `test_gimple.py` (51) first — it alone is a
quarter of the residue. Each row is the same four steps: read each `timeout=`,
decide which of `COMPILE_TIMEOUT_S` / `LINK_TIMEOUT_S` / `RUN_TIMEOUT_S` /
`SWEEP_TIMEOUT_S` the child is, name the site where the answer is "none of
these", add the import, delete the literals, and delete the file's row here in
the same commit. The census is the checklist and the check now enforces that it
and the tree agree.

## Original status

Open. Census measured 2026-10-03 on `99cdb9b7` with python3 3.14.

**This is the residue of a fix that is now half-landed, not a new proposal.**
`exec_budget.py` exists to replace per-child wall clocks that were sized for
"much more than a tiny program needs" and were therefore firing on a loaded
machine, where a timeout inside a test file is reported as an ordinary FAIL —
that is, as a compiler bug. Its docstring already names the mechanism that let
the defect spread: *"A literal is how this defect spread across 29 files in the
first place, and a reader has no way to tell a deliberate 5-second budget from a
stale one."*

Four files have adopted `exec_budget` and `test_suite.py`'s
`test_no_stale_per_child_budget_is_left_as_a_literal` keeps them honest. The
other 63 files still spell theirs out.

## What was measured

    $ grep -rn "timeout=[0-9]\+" --include=test_*.py . | wc -l
    217
    $ grep -rln "timeout=[0-9]\+" --include=test_*.py . | wc -l
    63

By file, the ten largest:

| count | file |
|---|---|
| 37 | `test_gimple.py` |
| 11 | `test_gimple_async_runner.py` |
| 9 | `test_metal_codegen.py` |
| 9 | `test_formal_admitted.py` |
| 8 | `test_suite.py` |
| 8 | `test_memslot.py` |
| 7 | `test_formal_sweep.py` |
| 6 | `test_formal_argparse.py` |
| 5 | `test_transitive_closure_capture.py` |
| 5 | `test_nested_async_generic.py` |

**Not all 217 are the defect, and the census deliberately does not pretend
otherwise.** At least two kinds are legitimate and must stay:

* `test_memslot.py` and `test_suite.py` — a budget is the SUBJECT. `p.wait(
  timeout=10)` there is testing that admission refuses an over-budget request
  within a known window, and the sandbox jobs deliberately use small budgets so
  they finish in a self-test. Changing them to `RUN_TIMEOUT_S` would make the
  self-test take hours and would destroy what it asserts.
* a literal that is deliberately much larger than any sibling in the same file
  (`test_gimple.py` mixes `timeout=300` for a multi-module `fire.py build` with
  `timeout=30` for the next step) — sometimes that spread is the bug and
  sometimes it is correct.

What makes the distinction possible per site is which KIND of child it is, and
that is a judgement about the argv, not a regex. `test_gimple.py:7334`'s
`timeout=300` on a `fire.py build` and `test_gimple.py:7338`'s `timeout=30` on
the produced executable are the same job and two different budgets; the mapping
that `exec_budget.py`'s three constants encode is `COMPILE_TIMEOUT_S` /
`LINK_TIMEOUT_S` / `RUN_TIMEOUT_S`, and applying it is per-file reading.

## Why the estate check stops where it does

`test_suite.py`'s `test_no_stale_per_child_budget_is_left_as_a_literal` walks
only the files that IMPORT `exec_budget`. That is not a convenience: in that set
"literal" is unambiguously wrong, because the file has already declared that its
budgets are shared. Widening the check to files that have not opted in needs the
per-site judgement above, and a rule that flagged 63 files on its first day is a
rule nobody runs — the same argument `test_every_test_file_is_registered` makes
about its own excuse list.

Widening it is also the only way the check gets its anti-rot. Right now a file
can avoid it forever by not importing `exec_budget`, which is exactly what
`test_gimple_runner.py` had done (ten literals, no import) while its sibling
`test_gimple_generator_runner.py` had the import and four literals anyway.

## The next step

Per file, in the owning area's lane, and cheapest first — these are ordered by
count, so `test_gimple.py` alone is a sixth of the residue:

1. For each file, read each `timeout=<int>` and decide which of
   `COMPILE_TIMEOUT_S` / `LINK_TIMEOUT_S` / `RUN_TIMEOUT_S` / `SWEEP_TIMEOUT_S`
   the child is. Record any site where the right answer is "none of these, and
   here is why" as a comment at the site, so the next reader does not have to
   re-derive it.
2. Add the import, delete the literals.
3. Only then widen the estate check — and when it is widened, expect it to need
   an exemption list for the files in the "deliberate" paragraph above, which is
   the cost that made the narrow version the right first step.
4. `MEMSLOT`/job timeouts in `tools/suite.py` are a DIFFERENT mechanism and are
   not in this census. `DEFAULT_JOB_TIMEOUT_S` (3600 s) is the one hang detector
   that can be trusted to be labelled, and a job that exceeds it is already a red
   run; see `exec_budget.py`'s "Why the fix is layering and not forgiveness".

## What the fix looks like when it is done

The four files already converted are the worked example:
`test_gimple_runner.py` (10), `test_gimple_generator_runner.py` (4),
`test_module_cache.py` (9) and `test_runner.py` (1) — 24 sites, and two of them
needed more than a substitution:

* `test_gimple_runner.py`'s RSS probe runs CPython *around* a compiled child, so
  its outer budget has to EXCEED the inner one's or the outer kills the wrapper
  and the inner budget is unreachable (`RUN_TIMEOUT_S` and `RUN_TIMEOUT_S + 120`);
* `test_gimple_runner.py`'s five package helpers take a `timeout=` parameter
  threaded through compile+run, whose default has to be the COMPILE budget,
  because every use of it inside them is a compile or a CPython reference run
  and never a compiled program's run.

Neither is visible in `grep`. That is the argument for doing this per file
rather than with a substitution script.