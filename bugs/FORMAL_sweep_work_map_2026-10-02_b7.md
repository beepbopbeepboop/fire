# FORMAL_sweep_work_map_2026-10-02_b7: a FRESH, COMPLETE sweep of this repository and the stdlib, both architectures

**Both arms ran to completion over the whole 668-file scope, so every number below
is over the whole scope — not over the part of it a run happened to reach, which is
the caveat that dominates every earlier map in this series** (`…_b6.md` §2.3,
`…_b3.md`, `…_repo-a.md` §1). Three findings a reader should take away:

* **Zero `tool` rows.** Every one of the 668 files got a verdict from a build, on
  both architectures, at `-t 120` — including the **20 files the `-6` runs could
  not answer at `-t 600`** (§2.4). That is the whole delta against `-6`, and not
  one file moved to a worse class.
* **The two architectures are the same sweep.** All **542** files classified on
  arm64 have the **same class** on x86-64, and the x86-64 arm has exactly **one**
  file the arm64 arm does not (`formal/hostmods/os/_syscalls.mojo`, and it is an
  ABI fact about the host, not a gap) (§2.5). **The x86-64 machine subset is not
  where the remaining coverage is.**
* **The four `backend-crash` rows are FIXED on this branch** — one heterogeneous
  dict's two value shapes, one caller that knew about one of them (§3.2). A crash
  is the one class a sweep cannot leave behind: it is never cached, so it costs
  four builds per arm per sweep until it is gone. It is gone.
* **The largest unowned codegen row in the corpus is 16 files, and it is a
  refusal that is CORRECT** — a dylib has no entry point for a module's top-level
  code — so its next step is a load-time initializer in two object writers, gated
  on a four-build measurement nobody has made (§6). The two rows above it are 163
  and 43 files of pure import closure. **Its precondition test is landed and green
  (§6), so nothing about it is blocked on a measurement any more.**

**Claim** `sweep:7` on `work/formal11-sweep`. This tree is `master` at `e7fbe6ef`
("Merge branch 'work/formal8-10'"), which includes the `formal3/4/5` batches.

---

## 1. The run

### 1.1 The commands

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-arm-7 -- \
  python3 tools/formal_sweep.py -j 6 -t 120        > bugs/sweeps/sweep-arm-7.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-x86-7 -- \
  python3 tools/formal_sweep.py -j 6 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-7.txt 2>&1
```

Both arms at once, as in every earlier map: `formal_sweep.py` keeps a separate
`cas/formal-imports/<arch>/` **and** a separate per-architecture `flock`, so the
two arms share nothing. The interpreter is not optional
(`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend_needs_3_10.md`):
`export PATH=/opt/homebrew/bin:$PATH` first, or the tool refuses to start.

**`-j 6 -t 120` was the right size and the reason is worth recording, because
`…_b6.md` §1.4 measured the opposite.** That map projected **4-6 h per arm** from a
run at **load average 90 on 18 cores**. This run, at load 13-40:

| arm | wall | files | classified | cache |
|---|---|---|---|---|
| x86_64 | **23-32 min** | 668 | 543 non-pass + 125 pass | 3 hit / 665 miss |
| arm64 | **<20 min** (its 2nd attempt, §1.2) | 668 | 542 non-pass + 126 pass | 348 hit / 320 miss |

(The ranges are bounds, not averages: each arm was observed alive and then observed
finished, and nothing sampled in between. Both are ~half an hour.)

**A full 668-file sweep of both architectures is half an hour per arm on this box,
not half a day**, and the `-6` map's 361-file `tool` row was a measurement of a
loaded machine rather than of this scope. The x86-64 row is the honest one to
quote: **665 of 668 files were built from scratch** (the CAS was cold for that
arch, because `tools/formal_sweep.py`'s own bytes are in every cache key —
`_criteria_id` — and three commits landed since `-6`), so 665 real builds took 25
minutes at 6 workers, i.e. **~2.2 s of wall per build**. The builds are cheap
because they are *refusals*: the answer to "can this file be built" is usually
reached after one or two module-dylib attempts, and those are cached per module in
`cas/formal-imports/<arch>/`.

### 1.2 The arm64 run was SIGKILLed at 238 files, and the CAS made the restart free

The first arm64 attempt died at **~20 minutes**, with **238 files classified**:

```
memcap: done, peak 0.9 GB across up to 14 procs (ceiling 8.0 GB), child exit -9
```

`peak 0.9 GB` against a `ceiling 8.0 GB` is the whole diagnosis: **memcap did not
kill it.** A breach prints `memcap: BREACH …` plus a measured peak
(`procrun.memcap_verdict` reads that line), and neither is here. `child exit -9` is
a `SIGKILL` from outside the tree, and `control.py guard` is the only thing on this
machine that sends `SIGKILL`s to our trees — its per-process limit is 55 GB, its
total 90 GB, and its runaway wall bound is 120 min, so **none of the three explains
a kill at 0.9 GB and 20 minutes**, and `guard.log` has been empty since 2026-09-29
so its output is not readable either. **Not established**, and said so rather than
guessed at: whoever re-runs a sweep should expect it to die occasionally and
should know that a re-run is cheap.

What the kill cost was **one re-run's wall time and nothing else**, which is the
CAS behaving as documented: the second arm64 attempt (`-7b`, same flags, same log
path) answered the 238 from cache — `348 hit / 320 miss` — and printed the same
verdicts for all of them (§2.4 checks exactly that). The killed log is kept at
`.tmp/sweep-arm-7-killed.txt` as evidence; it is not committed because a partial
log's `tool`-free numbers would be read as a scope.

**Two SIGTERMs would have kept the first run's ledger.** `formal_sweep.py` now
cancels what has not started on a signal (`8097b4d7`, in `master`), so a SIGTERM
prints a summary and publishes a `.ledger.partial`; a `SIGKILL` runs neither, which
is why §2.4 is computed from the two logs' printed lines rather than from ledgers.

### 1.3 Scope

**668 files**: this worktree's own **416** `*.py`/`*.mojo` plus the **252** under
`../new-modular/Mojo/stdlib/std`. The repository has grown from 400 files (the
`-6` run's count) to 416 across the `formal3/4/5` merges, which is the whole of the
scope delta against `-6` and the reason the two runs' denominators differ.

---

## 2. Class counts

### 2.1 This run, both arms, complete

Read off the two summaries; the classes sum to 668 in both, which the runner
checks itself.

| class | arm64 | x86_64 |
|---|---|---|
| **pass** | **126** | **125** |
| built-with-admitted-contracts | 4 | 4 |
| **codegen** (a refusal IN this file) | **47** | **47** |
| **codegen/dependency** (refused in a module this file imports) | **238** | **238** |
| not-answerable/host-import | 241 | 241 |
| not-answerable/unresolved-import | 1 | 1 |
| not-answerable/unresolved-extern | 2 | **3** |
| not-answerable/target-limit | 5 | 5 |
| backend-crash | 4 | 4 |
| **tool — no verdict at all** | **0** | **0** |
| **codegen coverage** | **126/415 = 30.4 %** | **125/414 = 30.2 %** |

**285 of the 668 files carry a codegen verdict, and 163 of those name one module
(§3).** The headline is 30 %, which is a different number from every earlier map in
this series and the reason is §2.4 in one sentence: **this is the first run whose
denominator is the whole scope.**

### 2.2 The `-5` baseline, for the record

`-5` swept **644** files (392 repo + 252 stdlib) at `-t 30`, 18 workers, and
answered **44 %** of its scope. Its logs are **not in this tree** (they were never
committed; `-6`'s map says the run published no ledger either), so the comparison
below is aggregate-only and is quoted from `…_b6.md` §2.1.

| class | `-5` arm64 | `-7` arm64 | Δ | `-5` x86-64 | `-7` x86-64 | Δ |
|---|---|---|---|---|---|---|
| pass | 116 | 126 | **+10** | 105 | 125 | **+20** |
| codegen | 38 | 47 | +9 | 39 | 47 | +8 |
| codegen/dependency | 47 | 238 | **+191** | 53 | 238 | **+185** |
| not-answerable/host-import | 77 | 241 | +164 | 74 | 241 | +167 |
| not-answerable/unresolved-import | 1 | 1 | 0 | 1 | 1 | 0 |
| not-answerable/unresolved-extern | 1 | 2 | +1 | 2 | 3 | +1 |
| not-answerable/target-limit | 3 | 5 | +2 | 3 | 5 | +2 |
| backend-crash | — | 4 | — | — | 4 | — |
| **tool (no verdict)** | **361** | **0** | **−361** | **367** | **0** | **−367** |
| files swept | 644 | 668 | +24 | 644 | 668 | +24 |

**Every row in that table except `tool` is a statement about how many files got an
answer, not about the backend.** `-5` classified 283 files; `-7` classified all
668. A `codegen/dependency` count that rises by 191 while the tool count falls by
361 is the same fact told twice. **Do not read the deltas as regression or as
progress; read the two absolute numbers** — 47 in-file refusals and 238
dependency refusals out of a scope that is now fully answered.

### 2.3 What the `-6` runs left, and what this run says about it

`-6` (`…_b6.md` §2.3) was two interrupted `-j 8 -t 600` runs that reached **187 of
the 652-file scope, none of it this repository's own files**, and lost both
summaries to the drain defect that `8097b4d7` has since fixed. Their logs hold 156
printed lines each (154 non-pass rows by `-6`'s own count; the two extra are
`not-answerable/unresolved-extern`, which `-6`'s table omitted).

### 2.4 The per-file delta `-6` → `-7`: 20 files gained a verdict, 0 lost one

Computed from the two logs' printed lines, path-for-path
(`.tmp/cmp_logs.py`, which is three regexes and a `Counter`):

| | arm64 | x86_64 |
|---|---|---|
| paths classified by `-6` | 156 | 156 |
| paths classified by `-7` | 542 | 543 |
| common paths | **156** | **155** |
| **class CHANGED** | **20** | **19** |
| moved to a WORSE class | **0** | **0** |

**Every one of the 20/19 is `tool` → `codegen/dependency`**, and they are the same
files: `collections/{dict,list,set,deque,counter,interval,_swisstable}.mojo`,
`collections/string/{string,iterators,_utf8}.mojo`, `bit/bit.mojo`,
`builtin/{bool,int_literal,string_literal,tuple}.mojo`,
`benchmark/{benchmark,quick_bench}.mojo`, `format/_utils.mojo`,
`itertools/itertools.mojo`, `memory/memory.mojo`. (`_utf8.mojo` is the one the
x86-64 arm had already answered at `-6`.)

**And they are not passes.** `collections/dict.mojo` at `-7` reads:

```
CODEGEN/DEPENDENCY: …/std/collections/dict.mojo  (build: dict.mojo imports
'std.builtin.rebind', which cannot be built either: builtin_slice.mojo:
StridedSlice___init__ returns a frame address, so it cannot be compiled into a
dylib: …)
```

which is §3's second row. So the `-6` map's warning stands and is now measured
rather than projected: **the 20 files that `-t 600` could not answer are 20 files
that `-t 120` answered in seconds, and every one of the 20 sits behind one of the
two modules that are §3's top two rows** — 12 behind `builtin_slice.mojo`, 8 behind
`binary_heap.mojo`. `…_b6.md` §4 measured `dict.mojo` at 31.9 min wall / 455 s CPU
for exactly this verdict; at 6 workers on this box the same file is answered inside
the 120 s bound. The wall/CPU ratio that map measured (4.2x, at load 90) is the
whole difference: **a `-t` is a CPU budget divided by the load, so it has to be
sized against the machine, and quoting a `-t` without the load is quoting
nothing.**

### 2.5 arm64 vs x86_64: one file, and it is a fact about the host

| | |
|---|---|
| paths classified on both | 542 |
| **of those, class CHANGED** | **0** |
| x86-64-only rows | 1 |

The one:

```
NOT-ANSWERABLE/UNRESOLVED-EXTERN: formal/hostmods/os/_syscalls.mojo  (builds, but
5 import(s) dyld cannot resolve: lstat$INODE64, opendir$INODE64, readdir$INODE64 …
[lstat$INODE64 is not exported by /usr/lib/libSystem.B.dylib])
```

`$INODE64` is the x86-64 libSystem ABI spelling; on arm64 the same calls have
unsuffixed names. The file **builds on both** and is unanswerable on one, for a
reason that is about the host's C library and not about the backend. It is already
in `not-answerable` on both arches, so it moves no number — but it is the *only*
architecture-dependent verdict in 668 files, and it is worth knowing that before
anyone spends time on "the x86-64 backend is behind".

---

## 3. Ranked causes

`python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-7.txt` — and
the x86-64 arm prints the same table with the same numbers. **FILES BLOCKED IS AN
UPPER BOUND**: a file's terminal cause is the first refusal its build walk reaches,
so fixing one moves the file to the next with the count unchanged.

| files | in-file | cause | refused in | example |
|---|---|---|---|---|
| **165** | 0 | module exports no public functions | `binary_heap.mojo x163`, `_unicode_lookups.mojo x1`, `stat.mojo x1` | `std/_gpu/host/_builtin_targets.mojo` |
| **54** | 8 | other refusal | `builtin_slice.mojo x43`, (this file) x8, `arm64.py x3` | `std/benchmark/__init__.mojo` |
| **16** | 0 | **a module whose API is its top-level statements, imported by another** | `module_loader.py x7`, `memslot.py x5`, `x86_64.py x2`, `determinism_trace.py x2` | `build_config.py` |
| **11** | 11 | a module's ATTRIBUTE read as a value, across a dylib boundary | (this file) x11 | `build_mojo_cli.py` |
| 10 | 1 | a bracketed specialization of a callee this unit does not compile | `tile.mojo x4`, `random.mojo x3`, `format_int.mojo x2`, (this file) x1 | `std/algorithm/__init__.mojo` |
| 5 | 4 | MLIR dialect construct (`__mlir_attr` / `__mlir_type` / `__mlir_op`) | (this file) x4, `_select.mojo x1` | `std/builtin/simd_length.mojo` |
| 2 | 2 | method call on a value receiver is not one of the lowered methods | (this file) x2 | `std/format/repr.mojo` |
| 2 | 2 | a String method that returns a SHORTER string writes the receiver's bytes | (this file) x2 | `mlir.py` |
| 2 | 2 | a constructor body that reads `self` is not inlined | (this file) x2 | `module_spec_gen.py` |
| 2 | 2 | a linked module exports no such name (`sys.exit`) | (this file) x2 | `t1.mojo` |
| 1 each | | 16 further single-file causes (§3.2) | | |

**219 of the 285 codegen/dependency lines are TWO rows, and 211 of those 219 are
five MODULES' refusals** (`binary_heap.mojo`, `_unicode_lookups.mojo`, `stat.mojo`,
`builtin_slice.mojo`, `arm64.py`); the other 8 are in-file.

### 3.1 The `uses:` column is what sizes each row, and it is in the tool's output

| refusing module | blocks | files that name anything it declares | reading |
|---|---|---|---|
| `binary_heap.mojo` | 163 | **1** (`BinaryHeap`) | 162 are closure — they import `std.collections`, which re-exports it |
| `builtin_slice.mojo` | 43 | **3** (`slice`) | 40 are closure |
| `module_loader.py` | 7 | **0** | closure |
| `memslot.py` | 5 | **0** | closure |
| `determinism_trace.py` | 2 | **0** | closure |
| `x86_64.py` | 2 | **1** | 1 is closure |
| `tile.mojo` | 4 | **4** (`tile`) | **work** |
| `format_int.mojo` | 2 | **1** | 1 is closure |
| `_select.mojo` | 1 | **1** | **work** |
| `stat.mojo` / `arm64.py` / `random.mojo` / `time.mojo` | 1/3/3/1 | **not measured** | the chain names a module by basename and that basename is ambiguous in this tree (`arm64.py` is both `formal/` and `jit/`; `random.mojo` and `stat.mojo` are both stdlib packages and a hostmod). The tool says so rather than picking one — correct, and a real limit on these four rows. |

**So of the 165 files the top row blocks, 163 name nothing `binary_heap.mojo`
declares and a 164th (`_unicode_lookups.mojo`) declares nothing at all; the single
`stat.mojo` row is the one that could not be measured.** That is the same
conclusion `…_b6.md` §3 reached at 88 files, now with a denominator 1.9x bigger and
the same answer. `binary_heap.mojo` itself is refused for a different reason (§3.2,
"a slot's declared type is not a value this path can supply"), so **the row's real
blocker is one file that has to lower first**.

### 3.2 The 47 in-file refusals, and the 16 one-file causes

The in-file rows, by shape (`codegen by family:` in the summary): other refusal 31,
MLIR construct 4, method call on a value 3, construction with arguments needs
`__init__` 2, string method needing a length 2, comptime does not fold 1, one-field
mutator has no return convention 1, self has two kinds of value across call sites
1, unimplemented intrinsic 1, value with no representation 1. The single-file
causes the tool lists separately include `len()` of a value that has no length
(`unescape_c.py`), a class-level default that cannot be materialized
(`type_system.py`), `field(default_factory=F)` (`formal/x86_64_decode.py`), a
frame-holder slot rebound (`regex_compile.py`), struct construction arity
(`mojo/backend_gimple/device_glue.py`), and `print()` that cannot classify its
argument on the x86-64 path (`test_llm/dumb_gemm.mojo`).

**Four `backend-crash` rows, all one crash — FIXED on this branch, so a re-run will
not reproduce them:**

```
BACKEND-CRASH: detect_real_type_errors.py   (the backend raised: ValueError: too many values to unpack (expected 2, got 3))
BACKEND-CRASH: formal/x86_64_codegen.py     (same)
BACKEND-CRASH: run_type_system_tests.py     (same)
BACKEND-CRASH: test_type_system.py          (same)
```

One direct build located it — `formal/build.py:10307`, in `refuse_none_comparisons`:
`{path: kind for path, (st, kind) in _constant_read_sites(...)}` destructured a
table whose entries are **3-tuples for an enum member** (`struct, kind, accessor`,
added by `5731ca02`) and 2-tuples for every other spelling. `_apply_constant_sites`
knew about both; this caller knew about one, so any file that read an enum member
AND had a `None`-valued constant raised instead of refusing. The fix is one shape
for every producer (`_constant_site`), which is why the two `…_with_two_fields`
guards above it now pass. All four files answer properly on the fixed tree:
`test_type_system.py` → `not-answerable/unresolved-import` (`pytest`),
`detect_real_type_errors.py` and `run_type_system_tests.py` →
`codegen/dependency` behind `type_system.py`'s `Type.origin` default,
`formal/x86_64_codegen.py` → `not-answerable/host-import` (`importlib`). **The
counts in §2.1 are the run's, and they are what the log holds; the class itself is
empty on a re-run.**

---

## 4. Files with no verdict, and why

**There are none: `tool` is 0 on both arms.** Every 668 files were classified by a
build. That is the first complete sweep in this series and it is worth saying what
it costs to arrange:

* `-t 120`, not `-t 30` and not `-t 600`. `-5` at `-t 30` lost 361 files; `-6` at
  `-t 600` still lost 20 (§2.4). **120 s was enough on this box at load 13-40.**
* `-j 6`, not `-j 2`. The task's own note suggested `-j 2`; measured, that is ~5 h
  per arm for this scope on an idle box and much worse on a loaded one. Six workers
  × two arms is twelve builds on eighteen cores.
* **Nothing was left running, and the file the task names as the
  never-terminating one is answered.** `std/python/bindings.mojo`
  (`bugs/FORMAL_bindings_mojo_build_never_terminates.md`) **is** in the scope and
  **did** get a verdict, on both arms:

  ```
  CODEGEN/DEPENDENCY: …/std/python/bindings.mojo  (build: bindings.mojo imports '.',
  which cannot be built either: binary_heap.mojo: formal dylib has no public
  functions: …)
  ```

  The sweep builds `--no-prove`, and this walk fails on the import closure long
  before the point the doc says it hangs, so **on this tree and with this scope the
  non-termination is not reached.** That is a fact about the sweep's build, not a
  refutation of the doc: the sweep is not the thing that reproduces it, and nothing
  here should be read as "that bug is fixed".
* `control.py guard`'s 120-minute runaway bound is the net under any file that does
  hang; the sweep's own `-t` is the mechanism, and it fired zero times.

The classes that are *not* "no verdict" but are also not coverage, with this run's
counts:

| class | n | what it is |
|---|---|---|
| `not-answerable/host-import` | 241 | imports a CPython module with no Mojo source. **42 of the 241 import a module a Mojo-side implementation could in principle provide** (`collections`, `copy`, `functools`, `glob`, `inspect`, `itertools`, `shlex`, `types`) and 199 need a host process, an embedded interpreter or a kernel object. By module: `tempfile x111`, `importlib x48`, `glob x18`, `zlib x15`, `collections x9`, `signal x6`, `types x6`, `copy x5`. Not in any rate |
| `not-answerable/target-limit` | 5 | `mojo_sqlite3_open` in the five `test_sqlite3*.mojo` files — a `mojo_*` runtime entry point this image's link line does not carry |
| `not-answerable/unresolved-extern` | 2 / 3 | builds, but dyld cannot resolve a symbol (`map.mojo`'s `func`; `$INODE64` on x86-64 only) |
| `not-answerable/unresolved-import` | 1 | `fe_reader.py` imports `lang_spec`, which is in no module set |
| `built-with-admitted-contracts` | 4 | `formal/hostmods/{concurrent/futures,ctypes,subprocess,threading}.mojo` build **but rest on declared assumptions about a host this image does not have**; counted in the denominator, never as passes |

---

## 5. Next step per cause

Ordered by files blocked. **Every row above 10 files is either claimed, or
measured here to be closure rather than work** — which is the finding, not an
omission.

| cause | files | owner / next step |
|---|---|---|
| module exports no public functions (`binary_heap.mojo`) | 165 | **the row is 164/165 closure** (§3.1). The real blocker is one file: `std/collections/binary_heap.mojo` is itself refused on `len(self._data)`, "a slot's declared type is not a value this path can supply" — the value-model premise, whose probe is a **stdlib edit** and therefore not makeable from a repository worktree. `FORMAL_dylib_export_loops_and_frame_bounds` (`formal10-2`) is the live claim on the export rule; `FORMAL_dylib_export_gate_ceiling.md` was **deleted** on this tree (`0fbd2874`), so the "ceiling 0" measurement it held is retired with it and re-measuring it is open |
| ″ (superseded 2026-10-03, `work/formal12-binary-heap`) | 165 → **0 of 10 re-measured** | Both halves of this row's premise were wrong in the same direction, so read this rather than the row above. The `len(self._data)` refusal **was a repository-side fix, not a stdlib edit** — three defects (a parser one, a value-model one, a `capacity=` one), and the file no longer refuses on it anywhere. **And the 165 still do not move**: 10 re-swept, 0 moved, terminal cause advanced to `binary_heap.mojo`'s own next construct; and with every codegen refusal in that file bypassed the module-dylib build fails at **this row's own export gate** with the message this row already carried. So the file has TWO walls and codegen was the first. Measurement, the remaining chain in order, and the correction to §3.1/§5's "then they move": `bugs/FORMAL_binary_heap_mojo_after_the_len_value.md`; §1.2 of `FORMAL_known_limits.md` carries the same re-measurement and its 2026-09-30 probe predicted it |
| other refusal (`builtin_slice.mojo`) | 43 closure + 8 in-file | the closure half is `formal10-2`'s `FORMAL_builtin_slice_optional_field_is_a_frame_holder` (a returned frame cannot cross a dylib boundary); the 8 in-file rows are §3.2's list |
| **a module whose API is its top-level statements** | **16** | **unowned and unclaimed — §6, and filed as `bugs/FORMAL_dylib_module_body_has_no_load_time_entry_point.md`.** 1 use in 16. Its precondition test now exists and passes; the work left is a load-time initializer in two object writers, and the doc's item 2 is a four-build measurement of whether that is worth 16 files or 9 |
| a module's ATTRIBUTE read as a value (`sys.argv` ×6, `sys.stderr`, `sys.executable`, `os.environ`, `ast.ClassDef`, `stat.S_IXUSR`) | 11 (all in-file) | `FORMAL_module_state_no_storage` (`formal8-7`); its own Status says the ceiling on folding these reads is 0 of 6, measured per use |
| bracketed specialization of a callee this unit does not compile (`tile.mojo`) | 10 | `FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value` (`formal10-5`); **4 of 4 blocked files use `tile`**, so that half is work; the `random.mojo`/`format_int.mojo` halves are 1 of 3 and 1 of 2 |
| MLIR dialect construct | 5 | `formal-mlir-gpu` / `formal2-mlir-comptime`; `FORMAL_known_limits.md` §2. `_select.mojo` is 1 file and **is** work (1 of 1 use it) |
| method call on a value receiver (`write_repr_to`, `unsafe_load`) | 2 | needs a `repr` model for a non-string receiver; `FORMAL_string_value_model`'s question asked about something else |
| a String method that returns a SHORTER string (`strip`, `rstrip`) | 2 | `FORMAL_string_value_model` (`formal3-8-r2`) — the repo-b map's §5.1 row 1 |
| a constructor body that reads `self` is not inlined | 2 | **unowned, and named unowned by `…_repo-b.md` §5.2**: either split `ModuleSpecGenerator.__init__` into plain `self.<field> = …` plus a `configure()`, or teach the inliner the one extra statement kind the body uses |
| a linked module exports no such name (`sys.exit`) | 2 | `FORMAL_module_state_no_storage`'s export-rule half |
| 16 single-file causes | 1 each | §3.2; each is either a value-model question with a doc, a stdlib edit, or one file's own source |

---

## 6. The largest unowned row, and what it actually needs

`bugs/FORMAL_dylib_module_body_has_no_load_time_entry_point.md`, filed with this
map, with the measurement below. The row in one paragraph:

`formal/build.py` refuses to compile **any** module with top-level statements into
a **dylib**, because a library has no entry point that would run them, and the
refusal's own comment says why it is right: emitting the body would produce a
function nothing calls, so the file would build, link, and do nothing at load. **16
files** are refused this way, by four modules, and **15 of the 16 do not use
anything the refusing module declares** — they are refused for having imported it.

**The row is one project, and it is not the project a first reading of the refusal
suggests.** `model.module_body` already exempts every top-level store the image
holds — a value that folds (`X = 5`) and a name that is a `__DATA` slot whose
initializer the image lays out (`X = ["a","b"]`) — so most of this repository's
modules are not "an API that is its top-level statements". Asking `module_body` the
same question the dylib path asks, per module, gives the whole row in 13
statements:

| module | body | statements |
|---|---|---|
| `determinism_trace.py` | 1 | `_ENABLED = None` |
| `formal/x86_64.py` | 1 | `RETURN_REG = Reg.RAX` |
| `module_loader.py` | 5 | `frozenset({...})`, `os.path.dirname(...)`, `_find_stdlib_path()`, `os.path.join(...)`, `ModuleLoader()` |
| `tools/memslot.py` | 6 | `os.path.dirname(...)`, **four float literals**, `if __name__ == "__main__":` |

**Nine are computed values; four are float constants that are body only because
this path cannot fold a float** — a message defect worth more than its file count
(§5 and the doc). `_MASK`, `_MASK63` and `_iota` in `determinism_trace.py` are all
folded and are **not** body, so that module's 2-file row rests entirely on
`_ENABLED = None`, which is a representation question (`None` is word 0 and one
untagged word cannot say it from the integer 0).

**The precondition is measured, and it holds.** A dylib's `__DATA` already carries
what the image holds: a module with `COUNT = 5` and `NAMES = ["alpha","beta"]`, read
and written from another image, prints `first=5@second=7@width=2@@` and exits 0,
matching CPython — the test added with this map
(`test_formal_cross_module.py::test_a_module_stores_that_the_image_already_holds_cross_the_boundary`,
with a control that a body which must run is still refused). Before it, nothing in
the suite asserted it, so a slot reading `0` where the source says `5` would have
left every case green. **The remaining work is a load-time initializer**
(`__mod_init_func`, in two object writers and two linkers), which is a project and
not a patch — and the doc's item 2 says the cheap measurement that decides whether
it is worth 16 files or 9 is four builds.

---

## 7. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-arm-7 -- \
  python3 tools/formal_sweep.py -j 6 -t 120 > bugs/sweeps/sweep-arm-7.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-x86-7 -- \
  python3 tools/formal_sweep.py -j 6 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-7.txt 2>&1 &

python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-7.txt     # §3
python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-x86-7.txt
```

**Half an hour per arm** (§1.1), not the four-to-six hours `…_b6.md` §1.4 projected:
that projection was a measurement of a box at load 90. **Size a `-t` against the
load, not against the file** — `…_b6.md` §5.2 measured `dict.mojo` at 4.2x wall/CPU
at load 90 and this run answers the same file inside 120 s at load 30.

The CAS is content-addressed and machine-wide, so a re-run with nothing changed
reads a file per file: **re-running this exact sweep costs ~3 files on x86-64 and
~320 on arm64** (the arch whose first attempt was killed), and **editing anything
under `formal/`, the parser, `mojo/middle/`, or any module in a swept file's own
import closure invalidates it** — `tools/formal_sweep.py`'s own bytes are in every
key (`_criteria_id`), which is why the x86-64 arm rebuilt 665 of 668 files.

Both arms exit 1 (real findings). `memcap` never breached: peak **0.9 GB** across
21 processes against the 8 GB reservation, on either arm.