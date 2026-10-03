# FORMAL_sweep_work_map_2026-10-02_b6: a fresh sweep of this repository and the stdlib, both architectures

**Status: both arms swept, both stopped short, three defects in the instrument
found by reading its own output, and the most consequential of them fixed on this
branch.** Read §1 for the runs and §2.3 for exactly how much of the scope the
numbers are over — nothing here claims a verdict about a file no run reached.

* **§5.1 — a machine fact filed as a backend gap, and published to the CAS.**
  Fixed here (`6febd26e`); filed as
  `bugs/FORMAL_sweep_memcap_death_is_filed_as_codegen.md`.
* **§5.2 — what `-t` and `-j` are worth on a loaded box**, measured, because the
  `-5` baseline's 361 `tool` rows and this run's 20 are the same fact.
* **§2.3 — the SIGTERM drain does not drain**: a signalled sweep keeps building
  the whole rest of its scope and reports only what it had classified when the
  signal arrived. Filed as
  `bugs/FORMAL_sweep_sigterm_drains_the_whole_scope.md`, **not fixed here** — it
  changes the interruption contract, and this branch already changes a
  classification rule.

**Claim** `sweep:6` on `work/formal6-sweep-r2`, continuing `formal6-sweep`,
whose branch is this branch's parent and whose logs are therefore measurements of
this tree (§1.1).

## 1. The run

### 1.1 What was inherited

`formal6-sweep` (work-248, branch `work/formal6-sweep`, now `superseded`) was
restarted by the controller after stalling 26 minutes with no CPU. Everything it
had reached this branch as commit `66d47489` ("WIP snapshot by controller"), and
that commit is **two log files and nothing else** — no source change — so its
tree content is identical to `master` (`4384e756`) and its partial logs are
measurements of this tree. Those two files are the output of its **`-j 10 -t
600`** run, cut off at 134 classified lines (arm64) and 133 (x86-64) when the
controller snapshotted them; this run's logs overwrite those two paths, which is
what the task asks for, and §2.2 lists every run's classified count so nothing is
lost but the snapshot itself.

It also left **two live sweeps of its own, one hour in, 20 build processes
between them, and nothing reading them**:

```
$ ps -o pid,ppid,lstart,command -p 49952,49955,49956
  PID  PPID STARTED             ELAPSED COMMAND
49952     1 Fri Oct  2 16:35:30 2026  01:00:44 bash .tmp/run_sweep6.sh
49955 49952 Fri Oct  2 16:35:30 2026  01:00:44 python3 tools/formal_sweep.py -j 10 -t 600
49956 49952 Fri Oct  2 16:35:30 2026  01:00:44 python3 tools/formal_sweep.py -j 10 -t 600 --arch x86_64
```

Load average was **86-90 on 18 cores** while they ran. Their completed verdicts
were already in the shared CAS (content-addressed, no path in the key — see
`cas.formal_build_key`), so nothing they finished was wasted; I took ownership
rather than restarting from zero: one `SIGTERM` each (the tool's handler drains,
prints what it classified, exits 3), a second (which the handler turns into the
default disposition), then `SIGKILL` on the **40 orphaned `memcap`/`fire.py`
children** the dead pool left behind — still allocating, with no parent left to
publish or classify anything they produced.

### 1.2 The commands

```sh
# .tmp/run_sweep6.sh, run from the worktree root, nohup'd
python3 tools/memslot.py --gb 8 --label sweep-arm-6 -- \
  python3 tools/formal_sweep.py -j 8 -t 600 > bugs/sweeps/sweep-arm-6.txt 2>&1 &
python3 tools/memslot.py --gb 8 --label sweep-x86-6 -- \
  python3 tools/formal_sweep.py -j 8 -t 600 --arch x86_64 > bugs/sweeps/sweep-x86-6.txt 2>&1 &
```

Both arms at once is right and is the predecessor's argument too:
`formal_sweep.py` keeps a separate `cas/formal-imports/<arch>/` **and** a
separate per-architecture lock, so the two arms share nothing.

**`-j 8 -t 600`, not the `-j 2 -t 120` the task note suggests.** Those numbers
are right on an idle machine and wrong on this one, and the predecessor measured
why before it stalled: at `-j 2 -t 120` it classified **1 file per 28 s** (~5 h
per arm, ~10 h for the pair), and at `-j 6 -t 120` **29 of the first 42 files
timed out**. Per-file *wall* time here is set by how much CPU the scheduler
gives one build, not by `-j`: a single `bit/mask.mojo` build measured here took
**3 m 37 s wall for 56 s of user CPU** (§5.2), i.e. the machine was running every
process at about a fifth of a core. So `-j` buys aggregate throughput and the
timeout has to be sized to the measured wall, not to the worker count.

**No `--allow-concurrent`.** Nobody held either arch lock when I started, and
holding it is what makes a same-arch sweep from another worker fail **loudly**
(exit 2) instead of racing us for `cas/formal-imports/<arch>/` — the race the
x86-a map measured as 8 silent wrong answers.

**The interpreter is not optional** (`bugs/INFRA_bare_python3_is_3_9_and_the_
formal_backend_needs_3_10.md`): `export PATH=/opt/homebrew/bin:$PATH` first. The
tool now refuses to start on an interpreter that cannot import the backend.

### 1.3 Scope

**652 files**: this worktree's own 400 `*.py`/`*.mojo` plus the 252 under
`../new-modular/Mojo/stdlib/std`. The `-5` baseline swept **644** (392 repo +
252 stdlib): the repository grew by 8 files between 10:15 and now, and that is
the whole of the scope delta. It matters for §2 — the two runs' denominators are
not the same population.

### 1.4 How long a full sweep of this scope is, measured

The scope is walked in sorted order, so a run's progress is readable off its
own output: this run reached `../new-modular/Mojo/stdlib/std/math/__init__.mojo`
— file **145 of the stdlib's 252** — **68 minutes** after it started, with 142
non-pass files classified on the arm64 arm and 143 on x86_64.

| | measured | projected for the full 652-file scope |
|---|---|---|
| the stdlib half (252 files) | 145 files in 68 min | **~2 h** |
| the whole scope (652 files) | — | **~4-6 h per arm**, ~8 h of wall clock with both arms at once |

The repository's own 400 files come second (absolute paths sort
`.../new-modular` before `.../work-249`) and are heavier per file, not lighter,
so the upper half of that range is the honest one.

**This is why the b6 sweep was cut short, and it is the single most reusable
number here:** a fresh sweep of this scope on both architectures is a multi-hour
job on a loaded box, not a session-length one. That is what the formal4 batch
worked around by splitting the same scope into nine claimed slices
(`sweep:repo-a/b/c`, `sweep:std-a/b/c`, `sweep:x86-a/b`), and it is why this map's
numbers are over the part of the scope that was reached (§2.3) rather than over
all of it. It also means the CAS is what makes the work add up rather than
restart: every file answered by any of the four runs is a file read on the next
one.

## 2. Class counts

### 2.1 The `-5` baseline (10:15 today, `-t 30`, 18 workers)

| class | arm64 | x86_64 |
|---|---|---|
| pass | 116 | 105 |
| codegen (a refusal IN this file) | 38 | 39 |
| codegen/dependency | 47 | 53 |
| not-answerable/host-import | 77 | 74 |
| not-answerable/unresolved-import | 1 | 1 |
| not-answerable/unresolved-extern | 1 | 2 |
| not-answerable/target-limit | 3 | 3 |
| **tool — no verdict at all** | **361** | **367** |
| **codegen coverage** | **116/201 = 57.7 %** | **105/197 = 53.3 %** |

**The baseline answered 44 % of its scope.** Every count in it is a count over
the files that happened to finish inside 30 s of a loaded machine, and its `tool`
row is 56 % of the sweep. That is the single most important fact for reading §2.3:
a `codegen/dependency` count that goes up between the two runs is mostly a
statement about how many more files got an answer, not about the backend.

### 2.2 What the `-6` runs are over

Three interrupted runs on this tree before this one, all classified a large
part of the scope and none reached all of it:

| run | flags | classified | of which `tool` | where its output is |
|---|---|---|---|---|
| predecessor, first attempt | `-j 2 -t 120` | 12 | 4 | `.tmp/sweep-arm-6-j2-partial.txt` in its tree |
| predecessor, second | `-j 6 -t 120` | 43 arm / 36 x86 | 29 / 30 | `.tmp/arm6-j6-partial.txt`, `.tmp/x86-6-j6-partial.txt` in its tree |
| predecessor, third — **the one the snapshot commit holds** | `-j 10 -t 600` | 148 arm / 149 x86 | 21 / 20 | `bugs/sweeps/sweep-*-6.txt` at `66d47489` (a snapshot of it at 134/133 classified) |
| **this run** | `-j 8 -t 600` | §2.3 | §2.3 | `bugs/sweeps/sweep-{arm,x86}-6.txt` |

The `-j 6 -t 120` row is where the predecessor's own measurement in §1.2 comes
from — **29 of its 43 classified arm64 files were timeouts** — and it is why the
`-j 10 -t 600` run existed. All four runs are on the same tree, and the `tool`
rows name the same biggest stdlib modules every time: **every `tool` row this
run produced is also a `tool` row in the `-5` baseline** (10 of 10 when
checked), so the timeout set is a property of those files and this machine, not
of a run.

A run that is SIGKILLed prints no summary, so for the predecessor's runs the
**pass count is not recoverable**: the tool prints one line per NON-pass file and
nothing else, and the partial ledger is published by the SIGTERM/SIGINT handler,
which a SIGKILL cannot run. Their counts are therefore over the classified
*failures* only, which is the conservative direction for every `codegen` row and
useless for the coverage rate.

### 2.3 This run

The `-j 8 -t 600` run is the one whose logs are at
`bugs/sweeps/sweep-{arm,x86}-6.txt`. Both arms were stopped with `SIGTERM` after
1 h 38 m, having classified **154 files each** and reached `std/os/` — stdlib
file ~175 of 252. **Neither arm printed its summary**, and the reason is a defect
in the tool, filed as
`bugs/FORMAL_sweep_sigterm_drains_the_whole_scope.md`: every file is submitted
to the pool up front, so `ThreadPoolExecutor.shutdown(wait=True)` on the way out
of the signal handler does not cancel — it drains the queue. The run stopped
*printing* at once and went on *building* (13 children, every one of them
younger than the signal), and it needed a second `SIGTERM` to die. So the
classified lines are in the log and the summary is not.

**What the two logs hold** (every line is a NON-pass file; the tool prints
nothing for a pass):

| class | arm64 | x86_64 |
|---|---|---|
| codegen (a refusal IN this file) | 10 | 11 |
| codegen/dependency | 124 | 124 |
| tool — no verdict (all `-t 600` timeouts) | 20 | 19 |
| **classified non-pass, total** | **154** | **154** |
| pass | **<= 33** (see below) | **<= 33** |
| **files never reached** | **498** | **498** |

**The pass count is not recoverable from this run, and the bound is the honest
way to say it.** The tool prints a line per NON-pass file and nothing else, so
the only place a run's passes exist is the summary and the ledger — and this run
lost both to the drain defect above (the summary is printed by the handler that
the defect makes unreachable, and the partial ledger is published by the same
one). What *is* known: the sweep reached the first ~187 files of the sorted
scope and printed 154 non-pass verdicts, so **at most 33 of the 187 passed**. For
scale, the `-5` baseline's answered files passed at 116/283 = 41 %, which would
put the real number near 16; that is an extrapolation from a different run on a
different tree and is not offered as this run's figure.

**The two arms are the same sweep with one file different.** Comparing the two
logs path-for-path, three lines differ in the whole 154:

| file | arm64 | x86_64 |
|---|---|---|
| `std/builtin/swap.mojo` | lowers it | **`codegen`**: an operator the x86-64 codegen does not lower |
| `std/collections/string/_utf8.mojo` | **`tool`** (timeout) | `codegen/dependency` |
| `std/os/_linux_x86.mojo` | `codegen/dependency` | **not reached** |

151 lines are identical. This is the shape the x86-a map measured for the
repository scope (15 of 16 in-file findings shared, the 16th an x86-64-only ABI
fact), so **the x86-64 machine subset is not where the remaining coverage is**:
one file in this slice, and it is owned (`FORMAL_x86_64_formal_backend_gaps`).

### 2.4 What moved against the `-5` baseline, file by file

**Not computed, and why that is a real gap rather than an omission.** A
per-file `-5` → `-6` comparison needs the `-6` side's classes for files that
PASSED, which is exactly what this run did not record (§2.3), and it needs the
`-5` side's per-file classes, which its log does not contain either — that run
published no ledger (it was the first for its arch+scope, so `report_history`
printed "nothing to compare against") and its scope is 644 files against a tree
that has since gained 8, so even the ledger key cannot be reconstructed. The
class-count comparison in §2.1/§2.3 and the cause ranking in §3 are therefore the
whole of the delta this sweep can support, and a run that completes (§1.4) would
give the rest: the tool's own ledger exists for exactly that.

## 3. Ranked causes

`python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-6.txt` —
**this run's own log**, over the 134 `codegen` + `codegen/dependency` lines it
classified. **FILES BLOCKED IS AN UPPER BOUND**: a file's terminal cause is the
first refusal its build walk reaches, so fixing one moves it to the next with the
count unchanged.

| files blocked | in-file | cause | refused in | example |
|---|---|---|---|---|
| **89** | 0 | module exports no public functions | `binary_heap.mojo x88`, `_unicode_lookups.mojo x1` | `std/_gpu/host/_builtin_targets.mojo` |
| **23** | 1 | other refusal | `builtin_slice.mojo x22`, (this file) x1 | `std/benchmark/__init__.mojo` |
| 9 | 2 | MLIR dialect construct (`__mlir_op`) | `_assembly.mojo x6`, (this file) x2, `_select.mojo x1` | `std/_gpu/globals.mojo` |
| 7 | 1 | a bracketed specialization of a callee this unit does not compile | `tile.mojo x4`, `format_int.mojo x2`, (this file) x1 | `std/algorithm/backend/tile.mojo` |
| 1 | 1 | a one-field struct's mutator has no convention to write its answer back | (this file) | `std/builtin/float_literal.mojo` |
| 1 | 1 | a `...` body: no instructions to emit | (this file) | `std/builtin/len.mojo` |
| 1 | 1 | a method on a multi-field struct where a descriptor is meant | (this file) | `std/builtin/none.mojo` |
| 1 | 1 | a slot's declared type is not a value this path can supply | (this file) | `std/collections/binary_heap.mojo` |
| 1 | 1 | method call on a value receiver is not one of the lowered methods (`write_repr_to`) | (this file) | `std/format/repr.mojo` |
| 1 | 1 | comptime does not fold to a constant | (this file) | `std/math/polynomial.mojo` |

The x86-64 arm is the same table — **88 / 23 / 10 / 7** on the first four rows,
the +1 on MLIR being `std/builtin/swap.mojo` (§2.3) — and the same six one-file
rows. **128 of the arm64 run's 134 lines are four modules' refusals.**

The predecessor's interrupted run (§2.2) ranked the same four causes at
80 / 28 / 7 / 6 over a smaller classified population; nothing moved between the
two runs except the counts, which grow with coverage.

**The `uses:` lines are the ones that size the work**, and they are in the tool's
own output:

* `binary_heap.mojo`: **1 of the 88 blocked files names anything `binary_heap`
  declares** (`BinaryHeap`). The other 87 are pure import closure — they import
  `std.collections`, which re-exports it.
* `builtin_slice.mojo`: **1 of 22** (the module declares only `slice`).
* `_assembly.mojo`: **0 of 6** name anything it declares (`inlined_assembly`).
  `_select.mojo`: **1 of 1** — that row is work.
* `tile.mojo`: **4 of 4** (`tile`) — work. `format_int.mojo`: 1 of 2.

So of the 89 files the biggest row blocks, **88 do not use the thing that blocks
them**, and the one that does is `binary_heap.mojo` itself, which is refused for
a different reason entirely (§6). That is why the row's measured value is 0 in
`FORMAL_dylib_export_gate_ceiling.md`, and why re-deriving it here with a bigger
denominator gives the same answer.

## 4. Files with no verdict, and why

**The `tool` class is 20 files on arm64 and 19 on x86_64, and every one of them
is a `-t 600` timeout.** The x86-64 list is the arm64 list minus
`collections/string/_utf8.mojo`, which that arm answered (§2.3):

```
benchmark/benchmark.mojo        builtin/bool.mojo             collections/list.mojo
benchmark/quick_bench.mojo      builtin/int_literal.mojo      collections/set.mojo
bit/bit.mojo                    builtin/string_literal.mojo   collections/string/_utf8.mojo
collections/_swisstable.mojo    builtin/tuple.mojo            collections/string/iterators.mojo
collections/counter.mojo        collections/deque.mojo        collections/string/string.mojo
collections/dict.mojo           collections/interval.mojo     format/_utils.mojo
                                itertools/itertools.mojo      memory/memory.mojo
```

They are the largest modules in the stdlib, and they are the same files the `-5`
sweep timed out at `-t 30`: **every `tool` row this run produced is in the `-5`
log's `tool` rows too** (`comm` over the two logs' path lists), so the timeout
set is a property of those files and of this machine, not of a run. The
predecessor's `-t 600` run timed out on 21 of the same files (§2.2). This is a
**timeout artefact, not a finding**, and it is the one number a reader must not
quote.

**What one of them actually costs, and what it turns out to be**, measured here
on the same file with a private `GMOJO_HOME` (so nothing of the sweep's is
involved) and no `-t` at all:

```
$ python3 tools/memcap.py --limit-gb 4 --label dict.mojo -- \
    /usr/bin/time -p python3 fire.py build --formal --no-prove --backend=arm64 \
    -o .tmp/exp-dict.bin ../new-modular/Mojo/stdlib/std/collections/dict.mojo
real 1914.14        # 31.9 minutes of wall
user 455.35         # 7.6 minutes of CPU
memcap: done, peak 0.1 GB across up to 3 procs (ceiling 4.0 GB), child exit 1
build: dict.mojo imports 'std.builtin.rebind', which cannot be built either:
  builtin_slice.mojo: StridedSlice___init__ returns a frame address, so it
  cannot be compiled into a dylib: …
```

Three things in one measurement:

* **the wall/CPU ratio is 4.2x**, which is §5.2 and the reason `-t` has to be
  sized against this box rather than against the file;
* `-t 600` buys about 143 s of CPU here and this file needs **455 s**, so it is
  unanswerable at `-t 600` on this machine and would answer at about `-t 1900`;
* **it is not a pass.** Its verdict is `codegen/dependency`, behind
  `builtin_slice.mojo`'s returned-frame refusal — i.e. one of the 21 `tool`
  files belongs to §3's second row, and the `tool` class is not merely "files
  that would pass". Anyone quoting a coverage rate off this run must re-sweep
  these first, or state the rate over the files that were answered and stop
  there.

## 5. Defects in the instrument, found by reading its own output

### 5.1 A build that hit the per-file memory ceiling is filed as `codegen`

**What the tool promises.** `tools/formal_sweep.py --help`, on `-M`:

> every build runs under `tools/memcap.py`, a file that exceeds it is killed and
> classified `tool`/`memory-killed` WITH its measured peak

and the code that does it is `formal_sweep.py:2385`, keyed on
`procrun.memcap_verdict`, whose breach test is the literal string
`'memcap: BREACH'` (`tools/procrun.py:188`).

**What the run printed.** Six lines per architecture, of class `codegen` — the
class whose count **is** a gap in the backend, the class that fails a run, and
the class `formal_sweep_causes.py` ranks:

```
CODEGEN: ../new-modular/Mojo/stdlib/std/bit/__init__.mojo  (memcap: __init__.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/bit/bit.mojo       (memcap: bit.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/bit/mask.mojo      (memcap: mask.mojo -- ceiling 4.0 GB across the process tree)
CODEGEN: ../new-modular/Mojo/stdlib/std/builtin/_format_float.mojo  (memcap: _format_float.mojo -- ceiling 4.0 GB ...)
CODEGEN: ../new-modular/Mojo/stdlib/std/builtin/_startup.mojo       (memcap: _startup.mojo -- ceiling 4.0 GB ...)
CODEGEN: ../new-modular/Mojo/stdlib/std/builtin/anytype.mojo        (memcap: anytype.mojo -- ceiling 4.0 GB ...)
```

(`std/benchmark/memory.mojo` in the x86-64 `-j 6` attempt. `bit/__init__.mojo`
reproduced in two different runs with different `-j`, so it is not a one-off.)

**Why it is a defect and not a judgement call.** The captured detail is
`memcap.py`'s **banner** — the first line it prints, `memcap: <label> -- ceiling
…`. A build that memcap killed prints `memcap: BREACH …` and
`memcap: peak observed before the kill: …` as well, and then
`procrun.memcap_verdict` sees the breach. Here there is no `BREACH` line and no
`memcap: done` line, which means the wrapper died before it could account for
the run: whatever killed it (an external watchdog, a wrapper death, a kill of
the tree) **is not a verdict about the source**, and the tool's own comment on
the fallback it takes instead says so:

> No message at all still counts as the build's own verdict … The fallback is
> deliberately the finding side (a codegen row …) — a crash we cannot see must
> not be able to hide, and a false FAIL only sends someone to look.

The fallback is right for a build that printed nothing; it is wrong when the one
line it does find is the **wrapper's own banner**, because that line is evidence
that the run was under the ceiling wrapper and that the wrapper never reported
an outcome. Worse, the misclassified verdict is **published to the CAS**
(`formal_sweep.py:2419`, `cas.publish(key, ".result", …)`): a machine fact is now
a cached `codegen` finding that every later run replays until the key changes.

**The files are not 4 GB builds.** Reproduced with a private `GMOJO_HOME` (so
nothing is shared with the live sweep), the same argv and the same 4 GB ceiling:

```
$ time GMOJO_HOME=$PWD/.tmp/gmojo-exp python3 tools/memcap.py --limit-gb 4 \
    --label mask.mojo -- python3 fire.py build --formal --no-prove \
    --backend=arm64 -o .tmp/exp-mask.bin ../new-modular/Mojo/stdlib/std/bit/mask.mojo
real 3m37.9s   user 0m56.0s   sys 0m15.8s
stdout: memcap: mask.mojo -- ceiling 4.0 GB across the process tree
        memcap: done, peak 0.1 GB across up to 1 procs (ceiling 4.0 GB), child exit 1
stderr: build: mask.mojo imports 'std.sys.info', which cannot be built either: _assembly.mojo: inlined_assembly: __mlir_op is an MLIR dialect construct…
```

**0.1 GB peak**, 56 s of CPU, and a real refusal (the `_assembly.mojo` MLIR row,
§3). So the 4 GB was a property of that run's machine conditions, not of the
file — and the file's true verdict was sitting in that run's output, unread.

**The fix, landed on this branch** (`6febd26e`). `procrun.memcap_wrapper_died()`
is the third state `memcap_verdict` did not have — banner present, no outcome
line — sharing one definition of "memcap reported something" with the breach
reader rather than adding a second parser. `run_one` files it as
`tool`/`wrapper-died`: its own cause name, because the two machine causes are
told apart by *evidence* (a breach is memcap saying the ceiling fired; this is
memcap saying nothing) and a reader told "killed at the 4 GB ceiling" about a
build that was never measured against it goes looking for a memory bug that is
not there. Not cached, for the reason a timeout is not. The same branch stops a
silent death's `detail` from being memcap's `done … child exit -9` line, which
`BuildRun`'s docstring already promised nothing downstream could do. Five cases
in `test_formal_sweep.py::TestWrapperDied`.

**What it costs, said out loud:** `tools/formal_sweep.py`'s own bytes are in
every cache key (`_criteria_id`), so this invalidates the CAS for every sweep on
the machine and the next sweep rebuilds. That is the tool working as designed —
a rule change must take effect — and it is the price of the fix.

**Filed as** `bugs/FORMAL_sweep_memcap_death_is_filed_as_codegen.md` (the doc is
kept, not deleted: the fix landed, and the six rows it misfiled are still in the
CAS under the pre-fix key, which the invalidation retires).

### 5.2 The SIGTERM drain does not drain, and the summary never arrives

**Filed as** `bugs/FORMAL_sweep_sigterm_drains_the_whole_scope.md`, **not fixed
here.** In one paragraph, because §2.3 lives with the consequence: every file is
submitted to the pool before the first is classified, and
`ThreadPoolExecutor.shutdown(wait=True)` — which is what leaving the `with` block
runs — does not cancel, so a signalled sweep keeps building every remaining file
in its scope while printing nothing, and the summary and the partial ledger are
printed only when that finishes. Measured here: signalled, it went on spawning
builds for another ten minutes, needed a second `SIGTERM`, and produced no
summary at all. The doc carries the code, the `ps` evidence and the one-line fix
(`shutdown(wait=False, cancel_futures=True)` before the early return).

### 5.3 `-j` buys much less than it looks like it does

Two measurements, both on this box at load 90 with 18 cores:

| build | wall | CPU | ratio |
|---|---|---|---|
| `std/bit/mask.mojo` (§5.1) | 3 m 37 s | 56 s | **3.9x** |
| `std/collections/dict.mojo` (§4) | 31 m 54 s | 7 m 35 s | **4.2x** |

Every build in the sweep is in the same position, so per-file wall time is ~4x
its CPU time and a `-t` is really a CPU budget divided by four. This is the whole
explanation of the `-5` sweep's 361 `tool` rows at `-t 30` and of this run's 20
at `-t 600`, and it is why the task note's `-j 2 -t 120` would have taken ten
hours: at that `-t` a build gets ~30 s of CPU, and half the corpus needs more. Recorded here so the next person sizing a sweep does
not have to rediscover it from three restarts.

## 6. Next step per cause

Ordered by files blocked, with the owner each one already has. **Every one of
the four large rows is held by a live claim or measured at ceiling 0** — that is
the finding of this sweep, not an omission in it.

| cause | files | owner / next step |
|---|---|---|
| module exports no public functions (`binary_heap.mojo`) | 89 | measured at **ceiling 0** in `FORMAL_dylib_export_gate_ceiling.md` §3/§5/§6: every export-table fix was measured at 0 files, because 87 of the 88 name nothing `binary_heap` declares. §8 of that doc names the real blocker, and it is not the export table: `binary_heap.mojo` itself cannot lower, on `len(self._data)`. `FORMAL_dylib_export_gate_ceiling` is claimed (`formal3-3-r2`) |
| other refusal (`builtin_slice.mojo` + 1 in-file) | 23 | the closure half is `formal2-re-and-slice` (`construct:re-merge-and-builtin-slice`), and its ceiling is already measured at **0** (lifting it moves all 22 onto `lowers only append, close, write`). The in-file row is `std/benchmark/__init__.mojo`; the other six in-file rows this sweep found are in the six one-file causes below, and §6 of the std-a map prices each one |
| MLIR dialect construct | 9 | `formal-mlir-gpu` + `formal2-mlir-comptime`; `FORMAL_known_limits.md` §2. The 6 behind `_assembly.mojo` are closure (**0 of 6** use it); the `_select.mojo` one is 1 file and is work; the 2 in-file rows are `builtin/type_aliases.mojo` (`Never`) and `origin/__init__.mojo` (`AnyOrigin`) |
| bracketed specialization of a callee this unit does not compile (`tile.mojo`) | 7 | `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md` — fully specified, **4 of 4 blocked files do use `tile`** (so the row is work, not closure), and held: `construct:mlir-and-gpu-globals` (`formal-mlir-gpu`). Its doc's "Whose" section says why it is not `formal/`'s to fix either: the callee is a *function-valued field*, so there is no declaration in hand even in principle |
| one-field struct's mutator (`float_literal.mojo`) | 1 | refused by name and already pinned (`model.receiver_writeback_name`, `test_formal_run.py`'s `one_field_mutator_with_a_return_value_is_refused`); a value-model decision |
| a `...` body (`len.mojo`) | 1 | **a stdlib source edit** — `write the function, or declare it as a trait method`. Not actionable from a repository worktree at all (§7) |
| a method on a multi-field struct where a descriptor is meant (`none.mojo`) | 1 | the receiver-position family, `FORMAL_frame_receiver_handoff.md` §6-§13. **Not** the 24-file "receiver at argument position 0" row, which `formal-receiver-novalue` holds |
| a slot's declared type is not a value this path can supply (`binary_heap.mojo`) | 1 | the value-model question premise (B2) — see `formal/model.py:16876` for what the premise is and is not. The doc says **measure a ceiling before implementing**, and the probe it names is a stdlib edit |
| method call on a value receiver (`repr.mojo`, `write_repr_to`) | 1 | re-measured on this tree, and the refusal names why it is not a table entry: "this backend lowers only append, close, write (on a file descriptor) and the string methods count, endswith, find, lstrip, startswith — the receiver is a name on this path, and `write_repr_to` is not one of those methods of those receivers, so **adding it to either table would be a guess about what it means on `int`**". It needs a `repr` model, i.e. `FORMAL_string_value_model`'s question asked about a non-string. Unowned, no doc, and **not one file of cheap work** |
| comptime does not fold (`polynomial.mojo`) | 1 | same shape as `type_dict.mojo`'s `Self._index` (std-a §6 row 3): a non-literal `comptime` binding, one file each, family size is a `grep` away |
| x86-64 only: an operator the x86-64 codegen does not lower (`swap.mojo`) | 1 | `FORMAL_x86_64_formal_backend_gaps` (claimed `formal3-10-r2`) |

**So the honest bottom line of this sweep: there is no unowned codegen row, at
any size, that is cheap.** The four large rows are claimed or measured at
ceiling 0; the seven in-file rows are seven one-file constructs, each of which
is claimed, is a stdlib edit no repository worktree can make (§7), or — the only
one with neither a doc nor a claim, `repr.mojo` — needs a `repr` model before it
can be lowered at all. **The next unit of unowned work in this area is therefore
not a cause from this table; it is the instrument defects in §5**, which cost
every sweep that runs rather than one file in one sweep. §5.1's is fixed on this
branch (commit and cost in §5.1); §5.2's is filed with its one-line fix and left
alone here, because it changes the interruption contract.

## 7. A note on what a worker can and cannot fix here

**Most of the stdlib-facing rows need a change to the stdlib, which is outside
every repository worktree** (`../new-modular/Mojo/stdlib/std` is a separate
checkout). `len.mojo`'s `...` body and the `binary_heap.mojo` probe the
export-gate doc asks for are both of this kind. A worker whose worktree is the
compiler repository cannot make them, and a work map that lists them as "next
steps" without saying so sends the next reader to look for a fix that is not
there. The fix for the *closure* rows, by contrast, is in `formal/`, which is
why those are the ones worth queueing.

## 8. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-arm-6 -- \
  python3 tools/formal_sweep.py -j 8 -t 600 > bugs/sweeps/sweep-arm-6.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-x86-6 -- \
  python3 tools/formal_sweep.py -j 8 -t 600 --arch x86_64 > bugs/sweeps/sweep-x86-6.txt 2>&1 &

python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-6.txt    # §3
python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-x86-6.txt
```

**Size it before starting** (§1.4): the full 652-file scope is ~4-6 h per arm
with both arms at once on a loaded box. Nine slices with claims
(`sweep:repo-a/b/c`, `sweep:std-a/b/c`, `sweep:x86-a/b`) is the shape that fits a
session, and the CAS is what makes slicing free of duplication.

**Stopping one is not a matter of sending it a signal** (§5.2): the pool drains
the whole queue, so a `SIGTERM` needs a second one, and the run publishes neither
its summary nor its ledger. Budget for that before you plan to read the output.

The CAS is content-addressed and shared machine-wide, so a re-run with nothing
changed reads a file per file instead of recompiling: **re-running this sweep
after reading this map costs only the files no run has answered** — and after
this branch's `tools/formal_sweep.py` change (§5.1) it costs all of them, because
that file's own bytes are in every key. That is the price of the fix, stated once
here so nobody has to infer it from a cache that stopped hitting.

The scope is printed before the first build and the classified lines are flushed
as they land, so a reader never has to guess which files a number is over; the
one thing a stopped run does not leave behind is the summary, which is why §2.3
is built from the log.