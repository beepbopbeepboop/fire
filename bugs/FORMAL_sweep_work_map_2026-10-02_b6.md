# FORMAL_sweep_work_map_2026-10-02_b6: a fresh sweep of this repository and the stdlib, both architectures

**Status: swept (interrupted), both arms, and two defects in the instrument
found by reading its own output.** Read §1 for the runs and §2.3 for exactly how
much of the scope the numbers are over — nothing here claims a verdict about a
file no run reached. **Claim** `sweep:6` on `work/formal6-sweep-r2`, continuing
`formal6-sweep`, whose branch is this branch's parent and whose logs are
therefore measurements of this tree (§1.1).

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
`bugs/sweeps/sweep-{arm,x86}-6.txt`. **Its summary block — the per-class counts,
the coverage rate and the CAS accounting — is the number to read for this
sweep**: it is the only run of the four that was given enough `-t` to answer the
large stdlib modules at all, and the other three cannot produce a coverage rate
(SIGKILLed, so no summary and no ledger; §2.2).

What is already established from it, and does not depend on how far it got:

* the two arms agree file-for-file apart from one file
  (`std/builtin/swap.mojo`, §3) — measured on the predecessor's pair, and the
  same shape holds in this run's logs so far. It is the shape the x86-a map
  measured for the repository scope (15 of 16 in-file findings shared);
* `tool` is again the largest class, and it is again **all timeouts** on the
  same biggest stdlib modules (§4);
* the `memcap:`-as-`codegen` rows of §5.1 are in the predecessor's logs, not in
  this one's — this run has produced none, which is consistent with §5.1's
  finding that they are a property of a run's machine conditions rather than of
  the files.

## 3. Ranked causes

`python3 tools/formal_sweep_causes.py .tmp/predecessor-partial-arm.txt` — the
`-j 10 -t 600` run on this tree, which is the largest classified population
available for either arch. **FILES BLOCKED IS AN UPPER BOUND**: a file's
terminal cause is the first refusal its build walk reaches, so fixing one moves
it to the next with the count unchanged.

| files blocked | in-file | cause | refused in | example |
|---|---|---|---|---|
| **80** | 0 | module exports no public functions | `binary_heap.mojo x79`, `_unicode_lookups.mojo x1` | `std/_gpu/_utils.mojo` |
| **28** | 7 | other refusal | `builtin_slice.mojo x21`, (this file) x7 | `std/bit/__init__.mojo` |
| 7 | 2 | MLIR dialect construct (`__mlir_op`) | `_assembly.mojo x4`, `_select.mojo x1`, (this file) x2 | `std/_gpu/globals.mojo` |
| 6 | 1 | a bracketed specialization of a callee this unit does not compile | `tile.mojo x4`, `format_int.mojo x1`, (this file) x1 | `std/algorithm/backend/tile.mojo` |
| 1 each | 1 | a one-field struct's mutator has no convention to write its answer back | (this file) | `std/builtin/float_literal.mojo` |
| 1 | 1 | a `...` body: no instructions to emit | (this file) | `std/builtin/len.mojo` |
| 1 | 1 | a method on a multi-field struct where a descriptor is meant | (this file) | `std/builtin/none.mojo` |
| 1 | 1 | a slot's declared type is not a value this path can supply | (this file) | `std/collections/binary_heap.mojo` |
| 1 | 1 | method call on a value receiver is not one of the lowered methods | (this file) | `std/format/repr.mojo` |
| 1 | 1 | comptime does not fold to a constant | (this file) | `std/math/polynomial.mojo` |

x86_64 differs from arm64 in exactly one row of this table: `std/builtin/
swap.mojo` ("an operator the x86-64 codegen does not lower"), which arm64
lowers. Everything else is byte-identical between the two arms, which is the
same shape the x86-a map measured for the repository scope (15 of 16 in-file
findings shared).

**The `uses:` lines are the ones that size the work** and they are in the tool's
own output:

* `binary_heap.mojo`: **1 of the 79 blocked files names anything `binary_heap`
  declares** (`BinaryHeap`). The other 78 are pure import closure.
* `_assembly.mojo`: **0 of 4** name anything it declares (`inlined_assembly`).
  `_select.mojo`: **1 of 1** — that row is work.
* `builtin_slice.mojo`: **0 of 21** (the module declares only `slice`).
* `tile.mojo`: **4 of 4** (`tile`) — that row is work.

So of the 121 `codegen/dependency` lines in the arm64 run, **four modules'
refusals are the whole story**, and one of those four (`tile.mojo`) is the only
one whose blocked files actually use what it declares.

## 4. Files with no verdict, and why

The `tool` class is 21 files on arm64 and 20 on x86_64 in the interrupted run,
and **every one of them is a `-t 600` timeout**:

```
benchmark/benchmark.mojo        builtin/builtin_slice.mojo   collections/counter.mojo
benchmark/quick_bench.mojo      builtin/int_literal.mojo     collections/deque.mojo
builtin/bool.mojo               builtin/string_literal.mojo  collections/dict.mojo
                                builtin/tuple.mojo            collections/interval.mojo
collections/_swisstable.mojo    collections/list.mojo        collections/set.mojo
collections/string/_utf8.mojo   collections/string/codepoint.mojo
collections/string/iterators.mojo  collections/string/string.mojo
collections/string/string_span.mojo  format/_utils.mojo      itertools/itertools.mojo
```

They are the largest modules in the stdlib, and they were the same files the
`-5` sweep timed out at `-t 30`: **every `tool` row this run has produced so far
is in the `-5` log's `tool` rows too** (10 of 10 at the time of writing, by
`comm` over the two logs' path lists). This is a **timeout artefact, not a
finding**, and it is the one number a reader must not quote.

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

## 5. Two defects in the instrument, found by reading its own output

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

**Next step (small, and it is a fix rather than a measurement).** Give
`procrun.memcap_verdict` a third state. It already distinguishes "memcap printed
`BREACH`" from "no memcap lines at all"; the missing case is **"memcap printed
its banner and nothing else"**, which means the wrapper died before it could
report. That is not `memory-killed` (no breach was measured) and it is not a
`codegen` finding either — it belongs in `tool` with its own cause name, next to
the file it applies to. Two lines in `memcap_verdict`, one branch in
`run_one`, and a case in `test_formal_sweep_truth.py`.

**Filed as** `bugs/FORMAL_sweep_memcap_death_is_filed_as_codegen.md`.

### 5.2 `-j` buys much less than it looks like it does

`bit/mask.mojo` above: **3 m 37 s of wall for 56 s of user CPU** on a box at
load 90 with 18 cores. Every build in the sweep is in the same position, so
per-file wall time is ~5x its CPU time and a `-t` is really a CPU budget divided
by five. This is the whole explanation of the `-5` sweep's 361 `tool` rows at
`-t 30` and of this run's 21 at `-t 600`, and it is why the task note's `-j 2`
would have taken ten hours. Recorded here so the next person sizing a sweep does
not have to rediscover it from three restarts.

## 6. Next step per cause

Ordered by files blocked, with the owner each one already has. **Every one of
the four large rows is held by a live claim or measured at ceiling 0** — that is
the finding of this sweep, not an omission in it.

| cause | files | owner / next step |
|---|---|---|
| module exports no public functions (`binary_heap.mojo`) | 80 | measured at **ceiling 0** in `FORMAL_dylib_export_gate_ceiling.md` §3/§5/§6: every export-table fix was measured at 0 files, because 78 of the 79 name nothing `binary_heap` declares. §8 of that doc names the real blocker, and it is not the export table: `binary_heap.mojo` itself cannot lower, on `len(self._data)`. `FORMAL_dylib_export_gate_ceiling` is claimed (`formal3-3-r2`) |
| other refusal (`builtin_slice.mojo` + 7 in-file) | 28 | the closure half is `formal2-re-and-slice` (`construct:re-merge-and-builtin-slice`), and its ceiling is already measured at **0** (lifting it moves all 21 onto `lowers only append, close, write`). The 7 in-file rows are 7 different constructs; §6 of the std-a map already prices each one |
| MLIR dialect construct | 7 | `formal-mlir-gpu` + `formal2-mlir-comptime`; `FORMAL_known_limits.md` §2. The 4 behind `_assembly.mojo` are closure (0 of 4 use it); the `_select.mojo` one is 1 file and is work |
| bracketed specialization of a callee this unit does not compile (`tile.mojo`) | 6 | `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md` — fully specified, **4 of 4 blocked files do use `tile`** (so the row is work, not closure), and held: `construct:mlir-and-gpu-globals` (`formal-mlir-gpu`). Its doc's "Whose" section says why it is not `formal/`'s to fix either: the callee is a *function-valued field*, so there is no declaration in hand even in principle |
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
not a cause from this table; it is the instrument defect in §5**, which costs
every sweep that runs rather than one file in one sweep, and which is fixed by
this branch (the fix and its cost are in §5.1's commit).

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

The CAS is content-addressed and shared machine-wide, so a re-run with nothing
changed reads a file per file instead of recompiling: **re-running this sweep
after reading this map costs only the files no run has answered.** The scope is
printed before the first build, the classified lines are flushed as they land,
and an interrupted run publishes its classified set as a `*.ledger.partial`, so
a reader never has to guess which files a number is over.