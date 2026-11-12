# TEST: test_formal_imports.py "the largest swept file is classified in a bounded time" fails under machine load

Status: OPEN. Filed 2026-11-12 by the reviewer of `bugs/TEST_formal_imports_host_module_tables_drifted_from_hostmods.md`
(whose five host-module rows all pass; that doc is deleted). This failure is NOT one of those five.

## What was run

    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py

Result: `formal imports: PASS=94 EXPECTED=0 SKIP=0 FAIL=1`. The one FAIL:

    FAIL  the largest swept file is classified in a bounded time
          [arm64] .../stdlib/std/python/bindings.mojo took 199s, over this case's 120s bound.

Commit 587e71dc6 recorded the same case at 149s against the same 120s bound, "while other lanes were loading the machine".

## Expected

`BOUNDED_BUILD_S = 120` (test_formal_imports.py ~line 995). The comment there measures `bindings.mojo` at 3.2 s on
arm64 and x86-64 (2026-10-03, idle tree). The bound is meant to be 40x below the guard, not a performance budget.

## Why this is open

Two readings, and they need different fixes:

1. **Load only.** Other lanes were running; the classification is fine and the wall-clock bound is the wrong instrument.
   Then the case should not be a stopwatch on a shared machine.
2. **Real slowdown.** The file went from 3.2 s to 150-200 s even under load, which is a 40-60x factor, larger than
   contention normally costs. That would be a classifier regression (or the import-chain walk) and should be bisected.

Nothing measured so far separates these: every reading was taken while the machine was loaded.

## Exact next step

1. On an idle machine (or with `nice`/no other lane running), time the case's own command alone:
   `time python3 test_formal_imports.py` and read the `bindings.mojo` line. If it is near 3 s, reading 1 holds.
2. If it is still well over 120 s when idle, reading 2 holds: bisect the classifier on
   `std/python/bindings.mojo` (the file is 1,997 lines; the deepest import closure in the sweep).
3. Only if reading 1 holds: keep the case's assertion that the file gets a verdict, but stop treating the wall-clock
   number as a pass/fail on a shared machine (report it, or run the case in an idle slot), so load alone cannot fail it.

The case also reads `bindings.mojo` from a stdlib checkout beside this tree (`_stdlib_dir()`), so on a machine without
that sibling it SKIPs rather than running; the timing result above depends on which checkout was found.
