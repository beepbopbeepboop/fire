# PERF: any process of ours that takes more than 3-4 GB is a bug

**Standard, set by the project owner 2026-09-29:** nothing we run should need more than
3-4 GB. The 30-51 GB that the self-host chain uses today is far beyond that. It was
tolerated because it worked and delivered results, and the ceilings in `tools/suite.py`
(`MEMCLASS`: small 8, module 24, program 55, stage 96) describe what the code *does*
today, not what is acceptable. Read every number in that table as a debt, not a budget.

The ceilings and `tools/memslot.py`'s reservations exist to keep a runaway from taking the
machine down while these are being paid off. They are not a licence.

## What was measured (this session's gates, `native-dumpfull` peak RSS)

| gate | peak | note |
|---|---|---|
| master, 02:58 | 33.8 GB | baseline |
| round 1 | 30.8 GB | |
| round 4 (landed, master a0c0969) | **27.6 GB** | the state on master now |
| round 3 (rejected) | 44.9 GB | root-level `os/` shadowed CPython's `os` |
| round 5 (aborted) | 51.2 GB | `mojo/middle/coro.py` `_compute_no_wd_forward` |

So the landed state is ~28-34 GB and the excursions to 45-51 GB were regressions the gate
caught. The regressions matter less than the baseline: a healthy 28 GB is 7-9x the standard.

Other measured footprints (same gates):

- `ab-native`, one snippet-sized `mojoc --dump`: **5.7-9.4 GB** each (8.0 and 8.2 GB hit the
  8 GB `small` ceiling and were reported RESOURCE). A snippet compile that needs 8 GB has a
  fixed cost, not a proportional one: the suite's own marker text blames "the self-hosting
  bootstrap pre-pass this corpus legitimately triggers, ~15-30 GB / ~15-25 s per call".
- `stage2/mojo --dump <file>` per source file: **1.2-2.4 GB** resident when healthy (7-65 s);
  **30-43 GB** and not terminating in round 5's coroutine-lowering regression.
- `lean` proof checks: ~1.1-1.7 GB each, but several run at once and they can outlive their
  test for hours.

## Why this is one bug and not many

`bugs/CODEGEN_bootstrap_resource_blowup.md` records the ~192 GB runaway and its attribution.
The self-hosted binary allocates boxed values and never frees them (no garbage collector, no
regions), so any algorithm that re-derives a working set per iteration, per function or per
pass turns into gigabytes: the round-5 regression is exactly that shape, one loop in one
pass, and the pre-pass cost above is the same thing at the whole-closure scale. Fixes that
shrink one allocation site help by the amount of that site; the durable fix is that the
compiler's passes free what they finish with (arena per pass or per function, or a collector).

## Next steps, in order

1. **Record peak RSS for every job** (`tools/suite.py`), so a regression shows up as a number
   in the tally and not as a collapsed machine. In progress (`memcap-coverage-3`).
2. **Leak-hunt on the WORST CASE: the self-hosted compiler compiling the compiler's own source.**
   That is `./mojoc --dump-full fire.py` (or the stage2 binary doing the same; the file the
   project's docs still call `mojo.py` is `fire.py` since the rename). It is the largest input
   we have, the one that peaks at 28-51 GB, and the one every other case is a subset of; a
   snippet or a two-line program is the wrong target because its footprint is dominated by
   fixed cost and hides what grows with the input. Method, proven on another project: run the
   real tool under macOS `leaks` (`leaks --atExit -- ./mojoc --dump-full fire.py`, with
   `MallocStackLogging=1` so each leak carries its allocation stack), then fix everything it
   reports, not only the largest item. Do NOT use mojo (or fire) as the program that hunts
   for leaks; the hunter is `leaks`, the subject is mojo compiling `fire.py`.
   Two cautions specific to this subject:
   - `leaks` reports only *unreachable* memory. A compiler that keeps every intermediate
     value reachable (a global table, a list that is appended to and never cleared, an
     AST/`.ci` cache that outlives its pass) will show few leaks and 30 GB of growth. If the
     leak report is small against the peak, hunt the retention instead: `heap <pid>` /
     `vmmap` at a few points during the run, and `MallocStackLogging` with `malloc_history`
     to see which sites the live bytes came from.
   - This is a whole-closure run: slow under stack logging and a 55 GB-class job today. It is
     the integrator's job to run (one at a time, through `tools/memslot.py`), never a
     worker's; a worker's part is to read the report and fix sites.
3. **Free what a pass has finished with** at the sites found, per pass or per function.
4. **Ratchet the ceilings down** as each drops (55 -> 30 -> ...), and register a regression
   check so it cannot creep back up without a red result. The end state is `small` = 4 GB for
   everything, with any exception carrying its own bug doc.

Verification of any fix here is heavy by nature (it rebuilds the self-host chain), so it is
the integrator's job: `python3 tools/integrate.py --only <task> --jobs mojoc ab-native
native-dumpfull`, with the before/after peaks reported, and the `leaks` report on
`fire.py` attached to the fix.
