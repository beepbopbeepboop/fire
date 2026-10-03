# FORMAL_sweep_memcap_death_is_filed_as_codegen: a build whose wrapper died is published to the CAS as a backend gap

**Class:** instrument defect (`tools/formal_sweep.py` + `tools/procrun.py`).
**Effect:** a machine fact enters the `codegen` class — the class whose count is
a gap in the backend, the class that fails a run, and the class
`tools/formal_sweep_causes.py` ranks — **and is written to the CAS**, so every
later sweep replays it until the cache key changes. **Seen:** 6 files per
architecture in the `-6` sweep of 2026-10-02 (§"What was run").

## What was run

Three sweeps of this repository + the stdlib on 2026-10-02, all with the
per-file memory ceiling on (`-M`, default 4 GB), logs in
`bugs/sweeps/sweep-{arm,x86}-6.txt` and in the predecessor's tree as described in
`bugs/FORMAL_sweep_work_map_2026-10-02_b6.md` §1.

## What was seen

Six lines per architecture, of class **`codegen`**:

```
CODEGEN: ../new-modular/Mojo/stdlib/std/bit/__init__.mojo        (memcap: __init__.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/bit/bit.mojo             (memcap: bit.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/bit/mask.mojo            (memcap: mask.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/builtin/_format_float.mojo (memcap: _format_float.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/builtin/_startup.mojo     (memcap: _startup.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/builtin/anytype.mojo      (memcap: anytype.mojo -- ceiling 4.0 GB across the process tree)
```

`std/bit/__init__.mojo` appears in two separate runs with different `-j`
(`-j 10 -t 600` and `-j 6 -t 120`), and `std/benchmark/memory.mojo` in the
x86-64 `-j 6` run, so it is not one unlucky invocation.

**The same files get real verdicts in the other architecture's run**, which is
what makes this a fact about the machine rather than about the files. Diffing
the two arms' classified lines (paths and classes, messages stripped) gives 10
file/architecture pairs where exactly one arm produced a `memcap:` row:

```
only in the arm64 log                      only in the x86-64 log
  bit/bit.mojo            (memcap)            benchmark/bencher.mojo     (memcap)
  bit/mask.mojo           (memcap)            benchmark/benchmark.mojo   (memcap)
  builtin/_format_float.mojo (memcap)         benchmark/compiler.mojo   (memcap)
  builtin/_startup.mojo   (memcap)            benchmark/memory.mojo     (memcap)
  builtin/anytype.mojo    (memcap)            benchmark/quick_bench.mojo (memcap)
  benchmark/bencher.mojo  (real verdict)      bit/mask.mojo             (real verdict)
  benchmark/compiler.mojo (real verdict)      builtin/_format_float.mojo (real verdict)
  benchmark/memory.mojo   (real verdict)      builtin/_startup.mojo     (real verdict)
  benchmark/benchmark.mojo (timeout)          builtin/anytype.mojo      (real verdict)
  benchmark/quick_bench.mojo (timeout)        bit/bit.mojo              (timeout)
```

`bit/mask.mojo` is a `memcap` row on arm64 and a real `codegen/dependency`
verdict on x86-64 **in the same run, minutes apart**, and the whole
`benchmark/` cluster is the mirror image. A file does not use 4 GB on one
architecture and 0.1 GB on the other; a machine under pressure does whatever it
does to whichever build is running when it happens.

The captured detail is `tools/memcap.py`'s **banner** — `memcap: <label> --
ceiling 4.0 GB across the process tree` — which is the first thing it prints and
normally never the last. A build memcap kills for memory prints two more lines
before it dies (`tools/memcap.py:88-92`):

```
memcap: BREACH  2.7 GB > 0.4 GB ceiling (673%), 1 procs -- killing memcap-probe
memcap: peak observed before the kill: 2.7 GB
```

and the tool recognises exactly that (`tools/formal_sweep.py:2249` →
`procrun.memcap_verdict` → `_MEMCAP_BREACH = 'memcap: BREACH'`,
`tools/procrun.py:188`). Neither `BREACH` nor `memcap: done` is present here, so
`mem_killed` is false, the run falls through to the silent-death fallback at
`tools/formal_sweep.py:2398`, and the banner — the only line there is — becomes
the file's "refusal".

**The files are not memory hogs.** Same tree, same flags, same 4 GB ceiling,
private `GMOJO_HOME` so nothing is shared with the live sweep:

```
$ time GMOJO_HOME=$PWD/.tmp/gmojo-exp python3 tools/memcap.py --limit-gb 4 \
    --label mask.mojo -- python3 fire.py build --formal --no-prove \
    --backend=arm64 -o .tmp/exp-mask.bin ../new-modular/Mojo/stdlib/std/bit/mask.mojo
real 3m37.9s   user 0m56.0s   sys 0m15.8s
memcap: mask.mojo -- ceiling 4.0 GB across the process tree
memcap: done, peak 0.1 GB across up to 1 procs (ceiling 4.0 GB), child exit 1
build: mask.mojo imports 'std.sys.info', which cannot be built either: _assembly.mojo: inlined_assembly: __mlir_op is an MLIR dialect construct…
```

0.1 GB peak, 56 s of CPU, and a real refusal on stderr. Note what the same
command prints when the kill path *does* fire — `BREACH`, the peak, and then
`memcap: done … child exit 1` — which is the shape the sweep is written against.

## What was expected

`tools/formal_sweep.py --help`, on `-M`:

> every build runs under `tools/memcap.py`, a file that exceeds it is killed and
> classified `tool`/`memory-killed` WITH its measured peak

and, on `tool`:

> timeout, unreadable file, or an internal exception in the sweep or the build
> driver — **no verdict about the source was reached at all**

A run whose wrapper died before it could report has reached no verdict about the
source either. It is the same fact as a timeout, arrived at by a different road,
and the tool already has the vocabulary for it (`CAUSE_MEMORY` and its siblings
at `tools/formal_sweep.py:486`).

## Why the silent-death fallback is not the answer here

`tools/formal_sweep.py:2401-2407` argues the fallback at length, and the argument
is sound for what it was written for:

> No message at all still counts as the build's own verdict: with no traceback
> there is no evidence of a crash, and a silent death is far more often a
> refusal whose message went to stdout. The fallback is deliberately the finding
> side (a codegen row: exit 1, printed, in the denominator) — a crash we cannot
> see must not be able to hide, and a false FAIL only sends someone to look.

The gap is that "no message" is not one state. It is three:

| what the output holds | what happened | class it deserves |
|---|---|---|
| the build's own refusal | the backend refused a construct | `codegen` (correct today) |
| `memcap: BREACH …` | the ceiling fired | `tool`/`memory-killed` (correct today) |
| `memcap: <banner>` and nothing else | **the wrapper died before it could account for the run** | `tool`, cause of its own — misfiled as `codegen` |

The third row is distinguishable with no new information: `tools/memcap.py`
prints its banner before it starts anything (`tools/memcap.py:72`) and always
prints `BREACH`, `done`, `interrupted` or `WATCHDOG FAILED` afterwards, so a
captured output whose only memcap line is the banner is a wrapper that was killed
mid-run. That is a fact about the machine, and today it is filed as a fact about
the source **and written to the CAS** (`tools/formal_sweep.py:2419`), which is
worse than the misclassification: it survives the run that observed it.

What killed the wrapper is **not established here**. `tools/control.py guard`
(`--limit-gb 55 --total-gb 90`) SIGKILLs the largest processes in any worker
worktree once their sum passes its budget, and it was running throughout; that
is a candidate, not a conclusion, and this doc does not claim it.

## The exact next step

1. **`tools/procrun.py::memcap_verdict`** — return a third state instead of a
   `(breached, peak)` pair, or a small sibling predicate beside it: a
   `memcap:` banner present with **no** `BREACH` and **no** `done` line means the
   wrapper died. Keep the existing contract (`breached` must stay memcap's own
   words, never exit code 125 — its docstring is right about that) and keep
   `peak_gb = None`, because no peak was measured.
2. **`tools/formal_sweep.py::run_one`** — a third branch next to the existing
   `if proc.mem_killed:` at line 2385, returning a `tool` verdict with a new
   `CAUSE_WRAPPER_DEATH` next to `CAUSE_MEMORY` (`tools/formal_sweep.py:486`).
   The detail should name the wrapper and the fact: it is a machine failure, not
   a verdict, and it is not a *memory* verdict (nothing was measured against the
   ceiling).
3. **`test_formal_sweep_truth.py`** — the classifier tests already live there
   (the `-M` cases from the 2026-10-02 x86-a map). Three cases: banner-only →
   `tool`; `BREACH` + peak → `tool`/`memory-killed` **with the peak in the
   detail** (unchanged); a build's own refusal with no memcap line at all →
   `codegen` (unchanged). The second and third are the regression guards for the
   existing behaviour.
4. **Cost to expect:** `tools/formal_sweep.py`'s own bytes are in every cache key
   (`_criteria_id`), so this invalidates the CAS for every sweep on the machine
   and the next sweep rebuilds. That is the tool working as designed — a rule
   change must take effect — and it is worth saying out loud in the commit
   message, because it is the price of the fix and the next person will otherwise
   think the cache broke.

Until this lands, a reader of any sweep log should treat a `codegen` line whose
detail starts with `memcap:` as a `tool` row, and should know that the CAS is
serving it as a finding.