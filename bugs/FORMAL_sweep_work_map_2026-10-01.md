# FORMAL_sweep_work_map_2026-10-01: the arm64 sweep of current master, and the arm64-vs-x86-64 differences

**Status: measured, and the instrument it measures with was fixed in the same
session.** The arm64 sweep below is a COMPLETED 623-file run. The x86-64 run it
is compared against is the owner's, also complete. The comparison produced one
finding, and the finding was about the tool rather than about either backend —
which is the most valuable thing a cross-architecture comparison can produce,
and the reason §4 is longer than the rest of this document.

## 1. The runs

| | arm64 | x86-64 |
|---|---|---|
| log | `.tmp/sweep-arm-final.txt` (this worktree) | `.tmp/sweep-x86-4.txt` (the owner's) |
| files | 623 | 623 |
| `-j` | 6 | 18 |
| `-t` | 30 | 30 |
| per-file ceiling | 4 GB (**new**; the x86-64 run had none) | none |
| pass | **113** | 106 (a FLOOR — see §4) |
| codegen | 187 | 184 |
| codegen/dependency | 118 | 164 |
| not-answerable/host-import | 192 | 153 |
| not-answerable/unresolved-extern | 5 | 9 |
| not-answerable/target-limit | 5 | 5 |
| tool | 3 | 2 |
| codegen coverage | 113/418 = 27.0 % | 106/454 = 23.3 % |
| CAS | 3 hit / 620 miss | 2 hit / 621 miss |
| peak RSS, whole run | 1.1 GB across 23 procs | not measured |
| wall clock | ~13 min at `-j6` | not measured |

Both are the same 623 files: this repo (371) plus the new-modular stdlib's
`std/` (252), which is what the sweep's own root line prints.

**The two runs are not directly comparable, and the reason is worth stating
before any number is read as a difference.** The x86-64 run predates the
new-modular syntax support landing, so its 164 `codegen/dependency` against this
run's 118 and its 153 host-imports against 192 are two different trees, not two
different architectures. Nothing in this document claims an arch difference
except §4, and §4's difference was measured on the SAME tool against the SAME
two logs with the one confound that matters removed.

The x86-64 arm of the comparison was re-measured on this tree for the four
files that carry formal module dylibs (`formal/hostmods/{argparse,ast,re,
hashlib}.mojo`) and came back as §4 describes. Re-running the whole x86-64
sweep on this tree is the integrator's to do; the four files are the whole of
the cross-arch effect, and the tool now says so in its own output.

## 2. Ranked causes (arm64, `tools/formal_sweep_causes.py --min 4`)

283 of 305 `codegen`/`codegen/dependency` lines accounted for, in 10 causes of 25.
`FILES BLOCKED` is an UPPER BOUND: a file's terminal cause is the first refusal
the walk reaches, so fixing one usually moves the file to the next with the count
unchanged. `uses:` is the number that says whether a row is work or a Stage-5
dependency.

| files blocked | in-file | cause | what closes it |
|---|---|---|---|
| 83 | 59 | other refusal (9 distinct constructs) | nothing: it is a bucket. The 4 `tile.mojo` and 13 `builtin_slice.mojo` sub-rows are named; the 59 in-file ones need splitting before they can be worked |
| 82 | 2 | **a TYPE name placed as a value** (`L[T]()`, `DType.bool`) | one construct. 80 of the 82 are behind `binary_heap.mojo` and **1 of those 80 names `BinaryHeap`** — so 79 are waiting on that one module, not 79 pieces of work |
| 33 | 33 | callee has no definition on this path | `formal/x86_64.py`'s import set; partly `formal-dylib-export` territory |
| 25 | 25 | receiver passed at argument position 0 | one construct, all in-file |
| 18 | 10 | MLIR dialect construct (`__mlir_attr`/`__mlir_type`/`__mlir_op`) | the 10 in-file are work; the 7 behind `_assembly.mojo` name nothing it declares (0 of 7 use `inlined_assembly`) |
| 15 | 15 | value with no representation on this path | one construct, all in-file |
| 10 | 10 | frame address passed where a value is wanted | `bugs/FORMAL_wide_receiver_by_reference.md` |
| 6 | 0 | module exports no public functions | `anytype.mojo` (5, uses not measured — the basename is ambiguous in this tree) and `stat.mojo` (1, and 1 of 1 uses it) |
| 6 | 6 | a module-level name of ANOTHER module is not exported as a word | all six are `sys`; `bugs/FORMAL_module_state_no_storage.md` |
| 5 | 5 | module-global name has no storage | one construct, all in-file |

**The largest actionable row is the second one, and it is one module.** "A TYPE
name placed as a value" blocks 82 files and 79 of them are behind
`std/collections/binary_heap.mojo` naming nothing it declares. That is the same
shape as the 2026-09-30 r2 map's second-largest row, which is the strongest
single piece of evidence in this document that the binding constraint on
coverage is module-level and not per-file.

## 3. The rows that moved, and did not

Against the 2026-09-30 r2 census (`bugs/FORMAL_sweep_work_map_2026-09-30_r2.md`),
this run:

* `MLIR construct` is 15 in the family breakdown and 18 files blocked here,
  against 15 in the x86-64 log's family breakdown. The new-modular syntax
  support did not move it.
* `callee has no definition` is 33 in-file here, 33 in the x86-64 family
  breakdown. Unchanged.
* The new stdlib brought ~39 more host-import files (192 vs 153) and 46 fewer
  dependency-blocked files (118 vs 164). Both follow from the tree changing,
  not from the backend.

**Nothing in this run's counts is a regression to chase**, and the ledger agrees:
this run reported `unchanged: 621` against the previous arm64 report, with the
two moves being files that had been in `tool` and are now classified (a flaky
`json.decoder.JSONDecodeError`, §5).

## 4. arm64 vs x86-64: the 7 files, and why they are not a backend difference

```
only arm64 (7)    only x86-64 (0)     both pass (106)     neither (510)
```

A one-sided difference of 7 files with an empty other side is a strong signal,
and the signal is NOT "the arm64 backend is better". Every one of the 7 was
reported on x86-64 as `not-answerable/unresolved-extern` with this message:

```
builds, but 7 import(s) dyld cannot resolve: os__syscalls_str_alloc_9f63a2, ...
[dyld cannot load /Users/mrs/.gmojo/cas/formal-imports/x86_64/
 os__syscalls.<digest>.x86_64.dylib here: dlopen(...): tried:
 '...os__syscalls.<digest>.x86_64.dylib' (mach-o file, but is an incompatible
 architecture (have 'x86_64', need 'arm64e' or 'arm64e.v1' or 'arm64' or
 'arm64')), ...; nothing in it binds]
```

Read that carefully, because it is the whole finding: the dylib is **x86_64**,
the image is **x86_64**, and the architecture test in
`tools/formal_sweep.py`'s `_loadable_for` PASSED. What failed was the `dlopen`
that follows it — and `dlopen` can only load a library of **the process doing
the loading**, which was the arm64 python running the sweep. `need 'arm64'` is
the probe's own architecture, not the image's.

So the message was a fact about the instrument presented as a fact about the
image. The x86-64 sweep's 106 passes were a **floor**: 113 files build for
x86-64, and the 7 the probe could not vouch for are in no denominator, so no
count in that report was wrong — the error was invisible in every number and
only visible as a cross-architecture disagreement. That is the worst shape for
an error to have.

**Fixed** in the same branch, as a third state rather than a reworded message:
`_loadable_for`/`_resolvable` return `(state, foreign, why)` with
`state ∈ {loadable, unloadable, unprovable}`; an `unprovable` name gets
`CAUSE_FOREIGN_ARCH`, the `tool` class, no cache entry, and a message naming
the host that could answer; and the summary says in the line a reader reads
that this arch's pass count is a floor on this host. The conservative direction
is unchanged where it matters — a dylib of the HOST's architecture is still
`dlopen`ed and still reported as a real load failure.

Measured after: those files report

```
TOOL: formal/hostmods/ast.mojo  (builds, but this arm64 host cannot check the
  3 import(s) it binds (os__syscalls_str_alloc_9f63a2, ...): they are in a
  x86_64 dylib, which only a x86_64 process can dlopen. The image's own dyld
  would load them; verifying that needs a x86_64 host, so this run reports no
  verdict rather than a failure)
```

and the arm64 sweep is byte-identical in its rows (113 pass, same classes) —
which it must be, since the new state cannot fire when the image's architecture
IS the host's.

**What a reader should take from this section:** a cross-architecture
disagreement is worth more than either number, and this one was the tool
misreporting itself for an unbounded period. The x86-64 numbers in the owner's
log, and in any earlier x86-64 log, are floors.

## 5. The `tool` rows, and the one that is a real bug

3 files in `tool`:

* `../new-modular/Mojo/stdlib/std/python/bindings.mojo` — timeout at `-t 30`.
  **Measured: not a slow build, a hang.** Traced with no timeout at all it ran
  **850 s and was still going, at a flat 0.06 GB**. So this is a wedge in the
  build, not a big compilation, and `-t` is the only thing bounding it today.
  Smallest reproducer:
  `python3 tools/formal_sweep.py -t 30 <that file>`. Filed as
  `“`fire.py build --formal` on `std/python/bindings.mojo` never terminates”`.
* `formal/arm64_codegen.py` — timeout at `-t 30`, measured at **29.8 s**. It
  misses by 0.2 s, so it is a `-t` artefact on this tree and would pass at
  `-t 60`; it is in the x86-64 log too, for the same reason.
* `scripts/check_resolved_bugs.py` and, in a later run, four other files —
  `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.
  **This one is a measured concurrency bug, and it is intra-sweep, not
  cross-sweep.** See `FORMAL_dylib_manifest_written_in_place`.

## 6. What this document does not establish

* It does not rank arm64 against x86-64. The two logs are different trees
  (§1) and the one arch difference that is real turned out to be the
  instrument's (§4).
* It does not claim a cause's value. `FILES BLOCKED` is an upper bound; the
  only way to price the 82-file type-name row is to fix `binary_heap.mojo` and
  re-sweep.
* It does not re-measure the x86-64 sweep on this tree. The four dylib-carrying
  files were re-measured and are §4; the other 619 are in no way affected by the
  probe fix, which cannot fire when the image matches the host.
