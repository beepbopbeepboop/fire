# The `module` class (24 GB) vs. what a `bootstrap-stage*-dumps` item peaks at

## Status

ANSWERED, and not in the direction this doc feared — 2026-09-30, by a
measurement through the real instrument. Kept rather than deleted, because the
answer refutes the 30-43 GB figure this doc was built on and that refutation is
itself unexplained; the class is fixed either way.

**Measured:** each `bootstrap-stage2-dumps` item peaks at **0.5 GB**. The whole
python closure dump (`bootstrap-stage1-transitive`, the same source set in one
process) peaks at **1.1-1.2 GB**, measured twice, on 2026-09-29 and
2026-09-30. So `module` (24) was never below the workload — it was ~48x it, and
the danger was never the ceiling but the reservation, because a class is also
the gigabytes a job takes out of the machine-wide budget before it starts.

The classes are now assigned from those measurements (commit `2ab8edea`): the
three `bootstrap-stage*-dumps` fanouts and the three transitive dumps are
`tiny` (4 GB), so a 45-item fanout runs 24 wide instead of 4. See
`tools/suite.py`'s `MEASURED_PEAK_GB` and `python3 tools/suite.py --list`.

## What is believed, and where the belief came from

`tools/suite.py`'s `MEMCLASS` gave `module` = 24 GB, and `module` was the
class of all three `bootstrap-stage*-dumps` fanouts, each of which is one
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

If one item really did peak at 30-43 GB, **24 GB is below the workload and
every one of those 141 items is killed by its own ceiling** — which is what
`memcap.py` does with a breached ceiling (SIGKILL, exit 125) and what
`tools/suite.py` then reports as `RESOURCE`.

## What is still open

The 30-43 GB figure. It cannot be an RSS peak of a per-file `--dump` on this
tree, because the whole-closure dump of the same sources measures 1.1-1.2 GB
through the same wrapper, and the 2026-09-29 log shows the fanout items
completing in 0.3-0.4 s each. Three candidates, none confirmed:

* it was a **footprint** (`phys footprint`) reading rather than summed RSS —
  `memcap` sums RSS, and the two differ by however much of a process is mapped
  file pages, which for a python process importing a 180-module closure is a
  lot;
* it was the **python** side (`bootstrap-stage1-dumps`, `fire.py --dump`) and
  not the compiled one, on a tree state where the python per-file dump carried
  the self-hosting pre-pass that `BLOW.md` §0 measures at 15-30 GB per call;
* the number came from summing several processes' RSS into one figure, which is
  what `procrun.tree_rss` explicitly over-reports when a tree shares pages.

The next step, if someone cares enough to close it: reproduce the original
observation with a per-item `MEMORY:` line to read the peak off, on the python
fanout rather than the compiled one, and record it in
`MEASURED_PEAK_GB`. If it does not reproduce, delete the 30-43 GB sentence from
`tools/suite.py`'s admission comment, which is where a reader will otherwise
keep finding it.


## Why it was not obvious before that round

Until the memory work, `build_cmd` guarded its whole wrapping block with
`isinstance(spec, Spec)`, so a `Fanout` fell through it entirely: the class
was validated at registration, printed by `--list`, and applied to nothing.
The three fanouts ran with a **bare argv** (which is how the collapse was
noticed — the log had no `memcap.py` in it) and they produced real verdicts.

They are wrapped now, because wrapping them is the whole point, which is what
made this class load-bearing and worth measuring at all. And the number does a
second job: a `module` item reserved 24 GB of the 96 GB machine-wide budget, so
the ledger admitted four at a time while each of the four could reach 43 GB —
4 x 43 = 172 GB on a 128 GB box. **A reservation is only as good as the number
in it**, and that, not the ceiling, is what the measurement settles: 0.5 GB
measured, 4 x 0.5 = 2 GB, and the sweep now runs 24 wide because the number in
the ledger is a measurement instead of a shape.

## What was run, to get there

Nothing heavy — the light-worker rule forbids it, and this is a measurement
question only a real compile can answer. The gate that produced the numbers:

    python3 tools/suite.py gate          # 2026-09-30, master 86d862f

and the light commands that read them back:

    python3 tools/suite.py --list                     # peak + class per job
    python3 tools/suite.py --dry-run native          # 3 tests, 3 jobs, -j18
    python3 tools/suite.py smoke -j2                  # peak 0.5 GB of an 8 GB ceiling

`build/suite.log`'s `MEMORY:` table is the instrument for this question, and it
is now also the input to the next round of class assignment: the run log prints
`CLASS TOO SMALL` when a job's own peak does not fit its class, and
`PEAK DRIFT` when a run contradicts the peak recorded in `tools/suite.py`.

## The next step, exactly

Not a class any more — a sentence. Reproduce the 30-43 GB observation, or
delete it:

    MEMSLOT_BUDGET_GB=96 python3 tools/suite.py -j1 bootstrap-stage1-dumps

(the PYTHON side, since the compiled side is the one measured at 0.5 GB), and
read each item's peak off the `MEMORY:` table. If nothing comes near 30 GB,
delete the "each observed between 30 and 43 GB" sentence from `tools/suite.py`'s
admission comment and from `procrun`'s history, and this doc goes with it.
