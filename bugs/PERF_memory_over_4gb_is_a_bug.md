# A memclass over 4 GB is a bug, not a fact about the workload

## Status

OPEN — a standing standard, with the jobs that currently break it listed
below. This doc exists because `tools/suite.py`'s registry now *requires* a
one-line reason (`memwhy`) from any job over the line, and a required reason
that points nowhere is a required lie. The list here is where each reason's
next step is written down.

The standard is the owner's: **anything over 3-4 GB in this compiler is a
defect, not a property of the thing being compiled.** So a class above 4 GB is
a debt with two possible endings — the job's peak comes down, or the job is
documented as irreducibly big — and "it has always been that class" is not one
of them.

## Why this is a MEMORY doc and not a style one

A class is two things at once, and only one of them is a ceiling:

* a **ceiling**, applied by `tools/memcap.py` to one job's process tree, and
* a **reservation**, taken out of ONE machine-wide budget
  (`tools/memslot.py`, `MEMSLOT_BUDGET_GB`, default 96) before the job is
  spawned.

A class of 55 GB for a job that peaks at 3.7 GB is not a safety margin. It is
55 GB the machine has promised to somebody else, which is why the classes were
reassigned from measured peaks on 2026-09-30 (commit `2ab8edea`; see
`tools/suite.py`'s `MEASURED_PEAK_GB` and the `--list` output) and why a job
over this line now has to say why in the registry.

## The jobs currently over the line

Read off `python3 tools/suite.py --list`, which prints the measured peak, the
class, the ceiling and the ratio for every job that has a measurement.

### Measured over the line

| job | class | measured peak | what it is |
|---|---|---|---|
| `native-dumpfull` | `program` (55) | 31.3 GB | `./mojoc --dump-full` diffed against the reference |
| `ab-native` | `program` (55) | 20.5 GB | python vs native codegen over the A/B corpus |

Both are the same root cause, and it is already localised: the corpora
legitimately trigger this compiler's **self-hosting bootstrap pre-pass** (a real
`do_imports=True` sibling-import compile), and that pre-pass costs ~15-30 GB per
call. See `BLOW.md` §0 "NOT closed" for the measured repro and the hot stack
(`mojo_cstr_region_eq` / `mojo_set_add_int` / `_set_grow`), and
`bugs/CODEGEN_bootstrap_resource_blowup.md` for the upstream accumulator that
never frees (~670M small objects, 58.6 GB / 1.24 T instructions on a real
self-host input).

**The next step for both** is the one in `CODEGEN_bootstrap_resource_blowup.md`:
cross-call caching across the three `_selfhost_*` seed passes within one
process, and a degenerate-hashing check on the tokenizer's `MojoSet` usage.
Neither needs a memory decision from the suite; they need the pre-pass to stop
allocating without bound. When it does, both classes drop to `tiny` and these
two rows disappear from this table — which is the point of the table.

### Over the line with nothing behind it

| job | class | measured peak | what it is |
|---|---|---|---|
| `ab-aside` | `program` (55) | none | `make -jN aside`: per-file python-reference dumps, ~779 files |
| `ab-bside` | `program` (55) | none | `make -jN bside`: the same corpus, native side |
| `prooflib` | `module` (24) | none | `lean -o lib/ProofLib.olean` — 27 MB, ~80 s |

These are unbacked claims rather than measurements, which is the weaker and
more fixable form of the debt:

* the A/B sweep is not in any bucket that records peaks. **The next step** is
  one run of `python3 tools/suite.py -j8 ab` (or `gmake -j20 aside bside`) on
  an idle machine, and the `MEMORY:` table in `build/suite.log` then replaces
  the guess with a number. Note the separate per-process cap in
  `tools/ab_run_one.py` (`module` per file): that one is a per-PROCESS bound,
  and it is deliberately not the same number as this job's aggregate — which is
  also why the aggregate is unbounded by it today (see the bug filed alongside
  this one).
* `prooflib` is the only job in the registry run by an external tool whose
  memory this repo has never measured. One `make gate` records its peak; if it
  is under 4 GB the class drops to `tiny` and the row goes away.

## What is NOT over the line, and why that is the interesting part

Before 2026-09-30, every job below was sized from the shape of its workload
rather than from a measurement, and the `MEMCLASS` comments justified them with
"55.8 GB healthy peak" and "the largest footprint ever observed completing a
self-compile is ~96 GB":

| job | class then | measured peak | over by |
|---|---|---|---|
| `selfhost`, `mojoc` | `stage` (96) | 3.7 GB | 26x |
| `bootstrap-stage2-cc` | `stage` (96) | 1.2 GB | 80x |
| the three `bootstrap-stage*-dumps` fanouts | `module` (24) | 0.5 GB per item | 48x |
| the three `bootstrap-stage*-transitive` dumps | `program` (55) | 1.2 GB | 46x |

A 96 GB class IS the whole machine budget (96 of 96), so a `stage` job queued
every other job on the machine behind it whether or not it was marked `excl` —
and `mojoc`, which was, did the same by definition. A 24 GB class simply
admitted four of a fanout's 45 items at a time, for items that need 0.5 GB
each.

Those are the numbers a **footprint** probe reported, on a tree state days
older. What a ceiling is enforced against — and what `memcap` measures, and
what these classes are now assigned from — is the summed RSS of the process
tree, and the runner's own instrument has now measured the same python
whole-closure dump at 1.1 GB (2026-09-29) and 1.2 GB (2026-09-30).

So the historical numbers are not *refuted* so much as *answered for a
different question*, and the lesson generalises: **a ceiling must be sized from
the measurement of the quantity the ceiling is applied to.** A class copied from
a comment is a class nobody has checked, and on this tree it was 26x too big
for `mojoc` — which is not a near miss, it is a machine that is 26x busier than
it needs to be while other workers' tests queue.

## Keeping this list honest

* `tools/suite.py` fails to start a run whose recorded peak does not fit its
  class? No — it *reports* it: `test_suite.py`'s ratchet checks fail, and the
  run log prints `CLASS TOO SMALL` and `PEAK DRIFT` lines (the second is the
  table going stale, which is how this doc would otherwise become a lie).
* A job added to this table must also carry its `memwhy` in the registry, and
  `--list` prints it next to the number. Two copies, one required.
* When a row is closed, delete the row. When they are all closed, delete this
  doc — and the `memwhy` requirement with it, because then the standard is met
  rather than documented.
