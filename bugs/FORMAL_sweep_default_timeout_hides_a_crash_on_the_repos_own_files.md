# FORMAL_sweep: the default `-t 30` turned a real backend crash into a non-finding, and the repo's own files are as large a unit as the stdlib's

**Area:** FORMAL (`tools/formal_sweep.py`, the `-t` default and its help text).
**Status: OPEN — a default that suppressed a finding this repository's own test
suite was already reporting. NOT FIXED HERE: the value is a judgement about what
the common case costs, and the sweep is being run concurrently by six other
workers right now, so changing a default under them is not mine to do. Filed by
the `sweep:repo-b` worker, which is the first slice to be made of the
repository's own top-level files rather than the stdlib.**

## What I ran

```
$ python3 tools/memslot.py --gb 8 --label sweep -- \
      python3 tools/formal_sweep.py -j 2 --no-stdlib --allow-concurrent \
      gimple_codegen.py generated_dispatch.py imports.py mlir.py \
      module_loader.py module_spec_gen.py monomorphize.py myinterpreter.py
  ...
  TOOL: imports.py  (timeout (> 30s))
```

At `-t 600`, the same file on the same tree, with nothing else changed:

```
  BACKEND-CRASH: imports.py  (the backend raised: AttributeError: 'str' object
                                  has no attribute 'name')
```

`AttributeError: 'str' object has no attribute 'name'` is a **compiler defect**,
not a coverage limit, and it was the same defect
`test_dataclasses_formal.py`'s corpus case was failing on for `formal/build.py`
the whole time (now fixed, in `7b1f2643`). So the default timeout was not
merely slow on this file — it was **hiding a crash that another suite in this
repository was already reporting**, and the only reason this slice found it is
that it re-ran with a bigger `-t`.

## What I expect

A file that is slow to build is `tool`/timeout. A file that **crashes** is
`backend-crash`, and the sweep says so on every path that reaches the build. At
30 s the build never reaches the census that raises, so the class is decided by
which bound the run happened to hit first, and the crash is simply not in the
ledger.

That ordering is not a bug in itself — a timeout has to be able to stop a build,
and no default is a substitute for `-t`. What is a bug is the **default**: it is
tuned for the population the tool's own `--help` describes ("the much larger
stdlib modules" is the one escape it offers), and the repository's own files are
a second population with a structurally different reason to be slow.

## Why the repo's own files are not the same population

A stdlib module imports a few stdlib modules. A repository-root `.py` imports
**the repository's other root `.py` files**, so one file's build is the sum of
its import closure's builds. Measured on this slice:

| file | lines | verdict at `-t 30` | at `-t 900` |
|---|---|---|---|
| `imports.py` | 185 | timeout | **backend-crash** |
| `module_spec_gen.py` | 399 | `codegen/dependency` | `codegen/dependency` |
| `mlir.py` | 344 | `codegen` | `codegen` |
| `generated_dispatch.py` | 135 | `pass` | `pass` |
| `gimple_codegen.py` | 5 645 | timeout | timeout |
| `myinterpreter.py` | 5 572 | timeout | timeout |

`imports.py` is **185 lines** and takes over 30 s, while `generated_dispatch.py`
at 135 lines passes inside it. Line count is not the predictor; **closure
depth** is — `imports.py` imports `cas`, which imports `subprocess`, and the
build walks the whole thing before it can refuse anything. A slice made of
repo-root files therefore has a different cost distribution from a slice made of
stdlib files, at every file size.

## The next step

1. **Do not silently change the default** — six workers are sweeping
   concurrently and a default that moves under them changes what their
   denominators mean. The safe change is the *reported* one: when a run's
   `tool` count is non-zero, print the **fraction of the scope it reached** next
   to the class counts, so a `tool` row is read as "this file is unknown at this
   `-t`" rather than as "this file is not a finding". The summary already says
   "a too-small `-t` is the usual cause"; it does not say how much of the scope
   that costs.
2. **A per-closure default, not a per-file one.** The honest predictor is the
   size of the file's import closure, which `_imports_digest` already computes
   for the CAS key. A `-t` proportional to closure size would put `imports.py`
   above the bound and `generated_dispatch.py` below it for the right reason,
   and it is the only version of this that does not make the two largest files
   in the repository unanswerable (§3).
3. **The slice convention is worth writing down regardless**, because six
   workers are choosing flags independently right now: the repo-b map
   (`bugs/FORMAL_sweep_work_map_2026-10-02_repo-b.md` §1) settled on `-t 900`,
   which classifies 6 of its 8 files and still leaves the two largest
   unclassified. If repo-a and repo-c used a different `-t`, their coverage
   numbers are not comparable and the comparison between slices is an artefact
   of the flags.

## §3 — the part that is not a timeout problem

`gimple_codegen.py` (5 645 lines) and `myinterpreter.py` (5 572 lines) time out
at `-t 30`, at `-t 900`, and — as of this writing — are still running at
`-t 5400`. Both are **CPU-bound, not memory-bound**: the whole 8-file sweep
peaked at **0.3 GB** across 6 processes, and memcap's 4 GB per-file ceiling was
never approached.

So for those two the answer is not a bigger number. Either

* **a finer unit** — construct coverage is a property of a file's *functions*,
  and the sweep's unit is a file; or
* **a profile** — 5 645 lines taking > 900 s against a 344-line file taking
  under 600 s is not a constant factor, and the AST-walk-per-pass shape in
  `formal/build.py` is the first thing to look at.

Both are recorded in the repo-b work map with the same numbers, so a reader who
wants them has the measurement rather than the question.