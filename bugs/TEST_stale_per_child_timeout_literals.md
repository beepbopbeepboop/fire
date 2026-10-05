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

* **Six more files landed 2026-10-05 (`work/bugs7-4`), 76 sites, and the census
  now reads 129 over 50 files.** Each classification is the ARGV at the call
  rather than the number, and each file's table is at its import so the reason
  is in the file:

  | file | sites | shapes, and what each became |
  |---|---|---|
  | `test_gimple.py` | 51 | 17 `gcc -fgimple` -> `COMPILE_TIMEOUT_S`; 17 `[exe]` -> `RUN_TIMEOUT_S`; 16 `[sys.executable, entry]` (the CPython oracle) -> `RUN_TIMEOUT_S`; 1 `fire.py run` -> `RUN_TIMEOUT_S`. A quarter of the whole residue, and the file this doc names first. |
  | `test_gimple_async_runner.py` | 11 | 4 `gcc`/`gxx -c` -> `COMPILE_TIMEOUT_S`; 7 `Popen`ed `[exe]` -> `RUN_TIMEOUT_S`. |
  | `test_formal_argparse.py` | 6 | 1 `fire.py build --formal` -> `COMPILE_TIMEOUT_S`; 5 the image or its CPython oracle -> `RUN_TIMEOUT_S`. |
  | `test_comptime_parity.py` | 4 | 1 `fire.py build` -> `COMPILE_TIMEOUT_S`; 1 the executable it produced -> `RUN_TIMEOUT_S`; 2 `fire.py run` -> `RUN_TIMEOUT_S`, that one being an INTERPRETER run rather than a build. |
  | `test_formal_imports.py` | 4 | 3 compiled images -> `RUN_TIMEOUT_S`; 1 `writer.wait(timeout=60)` after a `terminate()` is NOT a child budget and is named `SIGTERM_REAP_S`, the same name and the same wait `test_formal_sweep.py` already records. |
  | `test_struct_formal.py`, `test_re_formal.py` | 2 | Adopted `exec_budget` for `child_exit_reason`, which put them in the widened walk and named their one remaining literal each. |

  Two things that batch turned up and that are worth more than the substitutions:

  * **`test_gimple_async_runner.py`'s three `communicate(timeout=10)` rows were a
    real flake source, not a budget.** They are the rows that assert an ELAPSED
    window (`max_seconds = max(1.0, delay * 5)`), so on a loaded machine the 10 s
    ceiling fired `TimeoutExpired` and took the row down with a traceback
    instead of reporting the timing it exists to measure. `RUN_TIMEOUT_S` is the
    right shape for it — "the child must finish" — and the row's own assertion
    bounds the timing, so nothing is lost and a slow machine stops being a crash.
  * **`test_re_formal.py`'s `timeout=900` was 1.5x `COMPILE_TIMEOUT_S`,** and its
    eight children are eight `fire.py build`s of this repository's OWN source
    (`fire_compiler.py`, `reflect.py`, the `spec_gen.py` / `exprtypes.py` pair).
    Measured on this tree: 0.2, 6.5, 10.7, 10.5, 5.9, 5.5, 2.0, 1.1 s — so 600 is
    ~56x the worst of them and still 6x inside `DEFAULT_JOB_TIMEOUT_S`.

  **Two files left, and named so the next pass does not re-derive them:**

  * **`test_formal_admitted.py` (7 sites).** Three are a compiled image and one
    is a `python3 -c` child, but THREE are not child budgets at all: two
    `pool.submit(…).result(timeout=60)` — a thread/process pool's own window for
    the callable to report where it ran — and one `lock.acquire(timeout=0)`,
    which is `threading.validate_timeout(0)`'s own SUBJECT, the value under test.
    Converting it needs three named constants rather than a substitution, and
    the file also wants `lib/ProofLib.olean`, which a light worker may not build.
  * **`test_metal_codegen.py` (9 sites).** Five are `fire.py --jit`, which is a
    compile AND an execution of a Metal kernel, so `COMPILE_TIMEOUT_S` would
    NARROW 900 to 600 — and the measurement that would justify or refuse that
    needs a machine with a Metal device (`metalgpu` measured 107 s and 0.37 GB
    with one). Take it where such a machine is and decide there; nothing on a
    host without a GPU can.

**Still to do, and it is per-file reading in the owning area's lane:** the
remaining 50 rows, and the two files that need a judgement rather than a
substitution are named above (`test_formal_admitted.py`, `test_metal_codegen.py`).
Cheapest first after those, `test_async_void_return.py`,
`test_async_with_lock_guard.py`, `test_coro_nested_async_capture.py`,
`test_mutable_async_capture.py`, `test_nested_async_generic.py`,
`test_transitive_closure_capture.py` (5 each). Each row is the same four steps:
read each `timeout=`, decide which of `COMPILE_TIMEOUT_S` / `LINK_TIMEOUT_S` /
`RUN_TIMEOUT_S` / `SWEEP_TIMEOUT_S` the child is, name the site where the answer
is "none of these", add the import, delete the literals, and delete the file's
row here in the same commit. The census is the checklist and the check now
enforces that it and the tree agree.

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