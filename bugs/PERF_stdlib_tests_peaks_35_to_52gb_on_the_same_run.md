# PERF: `stdlib-tests` measured 34.9 GB and 52.2 GB on two identical runs

**Status: open, measured 2026-10-09. The class is fixed; the spread and the size
are not.** This is the one job in the never-measured 36 whose class went **up**,
and the reason is worth more than the class change: the same 321 files, the same
inputs, the same 2163 s, measured half again as much memory on the second run.

## What was run and what it said

Registered at `small` (8 GB), which it blew straight through:

    $ python3 tools/suite.py --no-cache stdlib-tests
    RESOURCE-CAPPED: peak 8.4 GB   (8.9 s)
    CLASS TOO SMALL: stdlib-tests peaked at 8.4 GB and its small class is 8 GB

    $ MEMLIMIT_GB=96 python3 tools/suite.py --no-cache stdlib-tests
    suite: 0 passed, 1 failed  (2163 s wall, peak 34.9 GB)

Re-run at the `program` (55 GB) class chosen from that number:

    $ python3 tools/suite.py --no-cache stdlib-tests
    suite: 0 passed, 1 failed  (2164 s wall, peak 52.2 GB)
    52.2 GB  stdlib-tests  program  ceiling 55 GB  95% of it

**34.9 GB, then 52.2 GB.** Wall time identical to within a second, so this is not
"the second run did more work". It ran all 321 items both times (checkpoint lines
`[321/321] checkpoint: P=15 F=306`).

## Why the class is `program` and not what the ratchet asks for

`class_for_peak(52.2)` is `stage` (96 GB). That is refused here, and the reason is
a different invariant rather than a preference: 96 GB is the whole machine-wide
ledger (`MEMSLOT_BUDGET_GB`, default 96), so a `stage` job can only ever run
alone, and on any smaller budget it could never be admitted at all — which is
what `test_suite.py`'s admission check ("a class over the budget is a job the
ledger can never admit") exists to catch, and what it caught when `formal` was
first landed at `stage`.

`program` (55 GB) covers the worst observation at 1.05x. That is thin, and it is
recorded as a `CLASS_ABOVE_PEAK` entry rather than hidden: a job running at 95% of
its ceiling is one bad afternoon away from a RESOURCE verdict, and the honest
response to that is to fix the spread, not to reserve the machine.

## The open question: why the spread, and why 35-52 GB at all

Two questions, and the first is the cheap one:

1. **The spread.** 1.5x between runs of a deterministic corpus is not noise in a
   measurement, it is a scheduler. `test_stdlib.py` drives 321 files and its
   parallelism is what decides how many compiler processes are live at once; RSS
   summed over the tree rises with that count. So the peak is a function of `-j`,
   not of the corpus — which means it is not stable enough to size a class from at
   all until the concurrency is pinned. Confirming it is one run at `-j1` against
   one at the default: if the peak tracks the job count, the class should be sized
   from the CONCURRENCY (`jobs x per-file peak`) rather than measured once.
2. **The size.** 35-52 GB to run a stdlib corpus through an interpreter and a JIT
   is the same debt `PERF_memory_over_4gb_is_a_bug.md` is about, and it is not
   Lean's this time — it is this compiler's own per-file compile. The A/B corpus
   already measures `ab-native` at 20.5 GB and `mojoc` at 4.9 GB for a
   whole-closure compile, so a 321-file sweep summing per-file peaks is where the
   arithmetic lands, and it says the per-file peak is the thing to measure.

Do NOT fix this by capping lower: that is the `native-dumpfull` failure mode — a
RESOURCE verdict says nothing about whether the output was right, and this job is
the corpus coverage for the whole stdlib.