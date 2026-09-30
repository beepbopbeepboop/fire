# The `module` class (24 GB) is below what a `bootstrap-stage*-dumps` item peaks at

## Status

OPEN — a number, not a code defect. The owner has been told and has asked for
the values to stay as they are for now, so nothing here changes them. What is
below is the evidence, because the next real `make gate` will show it and the
explanation should already be written down.

## What is believed, and where the belief came from

`tools/suite.py`'s `MEMCLASS` gives `module` = 24 GB, and `module` is the
class of all three `bootstrap-stage*-dumps` fanouts — `tools/suite.py:858`,
`:890` and `:907` — each of which is one
`{stage1,stage2,stage3}/mojo --dump <one source file>` per item, 47 items each.

The 24 GB figure is described in its own table as "headroom, not a
measurement":

    #   module   a single module of that closure — one `--dump` of one source
    #            file, natively. Growth here is cumulative over the closure
    #            rather than per file (bugs/CODEGEN_bootstrap_resource_blowup.md),
    #            so this is headroom, not a measurement.

Against that, `tools/suite.py`'s admission comment and `test_suite.py`'s
`CLOSURE_CMD_SHAPES` history both record the 2026-09-29 observation:

    the three `bootstrap-stage*-dumps` fanouts ran about thirty items at
    once, each observed between 30 and 43 GB

If one item really does peak at 30-43 GB, then **24 GB is below the workload
and every one of those 141 items is now killed by its own ceiling** — which is
not a hypothetical, it is what `memcap.py` does with a breached ceiling
(SIGKILL, exit 125) and what `tools/suite.py` then reports as `RESOURCE`.

## Why it was not obvious before this round, and why it is now

Until the memory work, `build_cmd` guarded its whole wrapping block with
`isinstance(spec, Spec)`, so a `Fanout` fell through it entirely: the class
was validated at registration, printed by `--list`, and applied to nothing.
The three fanouts ran with a **bare argv** (which is how the collapse was
noticed — the log had no `memcap.py` in it) and they produced real verdicts.

They are now wrapped, because wrapping them is the whole point. So the same
class that was decorative for a year is load-bearing from this commit on, and
if 24 is below the peak, `make gate` reports RESOURCE on those fanouts that it
did not report before.

The reservation makes the same number do a second job. A `module` item
reserves 24 GB of the 96 GB machine-wide budget, so the ledger admits four at
a time — which is the width the owner asked for — but each of the four may
then reach 43 GB, so 4 x 43 = 172 GB on a 128 GB box. **The reservation is
only as good as the number in it**, and this is the one case in the registry
where the number may be below the workload.

## What was run, and what it showed

Nothing heavy — the light-worker rule forbids it, and this is a
measurement question only a real compile can answer. What was run:

    python3 tools/suite.py --dry-run native      # 3 tests, 3 jobs, -j18
    python3 tools/suite.py --list                 # 75 jobs, every one with a class
    python3 tools/suite.py smoke -j2              # peak 0.5 GB of an 8 GB ceiling

`build/suite.log`'s new `MEMORY:` table is the instrument for this question
and it did its job on the only run available here: `suite-self-test` at
0.5 GB, 6% of its ceiling. The three stage-dump fanouts were not run, and
that is exactly the gap.

## The next step, exactly

One command, on an idle machine, through the real ceiling, so the number
comes from the same instrument the gate uses rather than from `ps` on a
collapsing box:

    MEMSLOT_BUDGET_GB=96 python3 tools/suite.py -j1 bootstrap-stage2-dumps

It is 45 items at the `module` class, so the ledger runs them four at a time
and the log records each item's measured peak. Then read the answer off the
log's `MEMORY:` table, which now prints peak, class, ceiling and percentage
for the top 20 jobs:

  * **every item under 24 GB** — the class holds, this is closed, delete this
    doc;
  * **any item over 24 GB** — the class is a debt and the items are being
    killed today. Two things have to be decided together, not one at a time:
    the ceiling (which kills them) and the reservation (which bounds their
    width). Raising `module` alone to fit the peak would admit
    `96 / module` of them, so the width falls exactly as far as the peak
    rises, and on a 96 GB budget a 43 GB class means two at a time — correct,
    and slow. The real fix is the one already written down in
    `bugs/CODEGEN_bootstrap_resource_blowup.md`: the per-file `--dump` should
    not be paying for the whole closure's growth.

Until that measurement exists, the owner should read a `RESOURCE` verdict on
`bootstrap-stage*-dumps` as "the ceiling is under the workload", not as a new
codegen regression.
