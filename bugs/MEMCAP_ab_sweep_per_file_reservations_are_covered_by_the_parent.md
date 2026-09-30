# A `make -j20 aside/bside` under the suite reserves 55 GB and allows 480

## Status

OPEN. Found while assigning memclasses from measured peaks
(`bugs/PERF_memory_over_4gb_is_a_bug.md`); it is a real hole in the admission
arithmetic, in code this session did not change, and it is the same failure
mode as 2026-09-29 — so it is written down rather than left as a note in a
commit message.

## What is believed

`tools/suite.py` admits a `make` job for its memclass and publishes that
reservation to the tree it starts, in `MEMSLOT_HELD` (`memslot.held_env`), so
that a wrapper *inside* the tree does not take a second, contradictory
reservation. That mechanism is `tools/memslot.py`'s `covering()`, and it is
correct for its purpose.

The A/B harness is where the mechanism has the wrong shape:

* `ab-aside` / `ab-bside` are `driver='make'`, `mem='program'`, so the runner
  admits them for **55 GB** and every file's compile inside them inherits that
  reservation;
* each file's compile is wrapped separately by `tools/ab_run_one.py`, which
  asks for its own `memslot.Slot(memlimit('module'))` = **24 GB** and its own
  `memcap --limit-gb 24`;
* `covering(24)` inside a tree holding 55 returns TRUE, so **the per-file
  reservation is served from the parent's 55 and never touches the ledger**.

So the ledger's view of the machine during `make -j20 bside` is a single 55 GB
holder, while the actual allowance is up to twenty concurrent compiles at 24 GB
each — 480 GB of permitted ceiling, of which the machine-wide budget accounts
for 55. The per-file ceilings are the only thing left, and a per-process
ceiling is exactly what 2026-09-29 showed is not a bound: about thirty
processes, each inside its own ceiling, until the box collapsed.

Hand-run `gmake -j20 aside bside` (the documented invocation in the Makefile's
`wholeprogram-help`) has no parent reservation, so each file takes its own
24 GB from the ledger and four run at a time — which is the behaviour the
parent's inheritance silently disables.

## What was run

    python3 tools/ab_run_one.py --help            # read the reservation path
    grep -n 'memslot.Slot' tools/ab_run_one.py    # one slot, per file
    python3 tools/suite.py --list                 # ab-aside/ab-bside: program=55GB
    python3 tools/suite.py --dry-run ab           # 4 tests, 783 jobs

No A/B run: it is a 779-file sweep, and the light-worker rule forbids it. The
argument above is from the code, not from a measurement — which is why the next
step asks for one.

## The next step, exactly

Decide what an aggregate of N per-file reservations inside ONE admitted job
should mean. The three answers, in increasing order of work:

1. **Divide the parent's reservation.** `ab-bside`'s 55 GB is the aggregate
   cap; the fan-out should be admitted once and its children should be told the
   remaining budget rather than each asking for the full per-file class. This
   is the real fix and it generalises: every `make` target that fans out into
   per-file compiles has the same shape.
2. **Make the per-file class a fraction of the parent's**, e.g. `ab_run_one.py`
   asking for `min(module, parent/4)`. Cheap, but it re-derives a number the
   registry already has, which is how the two spellings drift.
3. **Give the fan-out a class equal to the worst per-file peak times the
   width.** Only sound once (1) exists to enforce it, and it needs the
   measurement `ab-aside`/`ab-bside` still do not have.

Until then: prefer the hand-run `gmake -j20 aside bside` (each file reserves for
itself) over `python3 tools/suite.py ab` (one 55 GB reservation covers all of
them), and treat the `ab` bucket as the one place where `-j` is the only thing
bounding memory.

Related: `bugs/PERF_memory_over_4gb_is_a_bug.md` lists `ab-aside`/`ab-bside`
as unmeasured, which is the same hole seen from the class side.
