# PERF: the cold `lib/*.olean` build is 9.0 GB, and it is the whole `lib/` not one module

**Status: open, measured 2026-10-09, nothing fixed here.** This doc exists because
the measurement it records is the one that sizes `prooflib`'s class and one other
job's, and because the number the tree carried (7.8 GB) turns out to be a
different quantity from the one a class has to cover.

## What was measured, and how

`prooflib` is the registry step that builds `lib/*.olean` once so 16 proof jobs do
not each build it. On a warm tree it costs **0.06 GB**: `ensure_library` finds every
stamp current and returns. That is the measurement a `--no-cache` run of the job
records, and it is why this job had no peak worth having — its class was the
standing guess.

The class has to cover the BUILD, so the build is what was measured. The same
`ensure_library` call, against a private copy of `lib/*.lean` under `.tmp/` with its
own empty `GMOJO_HOME` (so the content-addressed store misses and every module
really elaborates), polled with `procrun.tree_rss` at 50 ms:

    **9.0 GB across up to 5 procs, 281 s for all eight modules.**

Nothing in the repo's `lib/` and nothing in the shared cas was written to; the
sources were copied and the throwaway cas is per-run.

## Why 7.8 GB and 9.0 GB are both true

`formal/lean.py` records 7.8 GB, and `formal-sweep-truth`'s and `prooflib`'s
`memwhy` inherited it. That figure is **one `lean` elaborating the largest module
alone** (`lib/ProofLib.lean`, ~90 s). This measurement is **the whole run**: the
same `lean`, plus the Python driver half, plus the other seven modules. So the
class is sized from 9.0, not 7.8, and both numbers stay in the tree with their
subjects attached rather than one replacing the other.

That gap is the reason this is a doc and not a table edit. `class_for_peak(9.0)`
is `module` (24 GB covers 1.5x9.0 = 13.5; `small` (8) does not), so the class is
unchanged — but `formal-sweep-truth` records a **1.5 GB warm peak** and calls
`ensure_library` itself, so the ratchet would assign it `tiny` (4 GB) from a
number that is not what the job can need. Hence `CLASS_ABOVE_PEAK` in
`tools/suite.py`: the exception is a named list with the unmeasured cost in it, not
a quiet divergence, because a ratchet with no exceptions shrinks a class onto a
warm-tree reading and the resulting RESOURCE verdict says nothing about the output.

## The debt

9.0 GB is over twice the 3-4 GB line in `PERF_memory_over_4gb_is_a_bug.md`, and
unlike the self-hosted columns in that doc this one is NOT the compiler: it is
Lean's elaborator over `lib/`, reached through our own `formal/lean.py`. The line
in that doc that matters here is that a 4 GB ceiling is not a tighter policy but a
red suite — measured, at `-M 4096` the `ProofLib` build fails with "(kernel)
excessive memory consumption detected". So the debt is real and the obvious cheap
fix (cap Lean lower) is known to break the build.

## Next step

Not attempted, and the reason is worth recording: the honest fix is to make
`lib/` smaller, not to make Lean use less memory on it, and every candidate I can
name is a change to what the proofs are proved *from*, which is the formal
workers' area and not a performance change at all. Concretely, the next thing worth
measuring is per-module: which of the eight modules carries the 9.0 GB, since
`ProofLib` is documented as the largest but the run's 5-process tree includes the
driver and a module may overlap. That is a ~5 min run using the same private-copy
harness, and it would say whether the debt is one module or the shape of all eight.