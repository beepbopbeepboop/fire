# FORMAL_sweep_work_map_2026-10-04_b10: a fresh, complete sweep of this repository and the stdlib, both architectures

**Claim** `sweep20:sweep-b10` on `work/formal20-sweep-b10`. **This tree is `master` at
`3c3516db`**, the commit this branch was cut from; `master` has since moved 27 commits
further (`c82499a4`), so every number below is over that tree and the scope is 13 files
smaller than a re-run on today's `master` would be (§1.2). Both arms ran to completion over
the whole 710-file scope with **no file left unclassified**, so every number here is over the
whole scope and every file has a verdict.

Four things a reader should take away, in the order they matter:

* **The largest cause in the corpus became invisible, and the per-edge export gate is what made
  it so.** `formal/imports.py::library_free_edges` emptied the 166-file
  `module exports no public functions` row, and **170 files moved out of a NAMED row into
  `other refusal`** — the bucket this repository's own instrument documents as *nobody has
  looked* (§3). **170 of the 184 files in that bucket are one construct** (§3.1), and
  **`tools/formal_sweep_causes.py` has no row for it**, so the queue cannot prioritise the
  biggest thing in front of it. That row is what §5 adds.
* **The 43-file Optional row did not get fixed; it went dark.** `Optional unwrap: None and a
  value are one word` was **43 files at `-9` and 0 at `-10`**, and **every one of the 43 is
  now in the unclassified bucket** (§2.4). The construct is unmoved and still refused; what
  changed is the refusal *in front of* it. A row emptying because the wall behind it was
  removed is `FILES BLOCKED IS AN UPPER BOUND` catching a planner, and it is the mirror image
  of what `-9` §4.1 recorded for `binary_heap.mojo`.
* **The two architectures are the same sweep, exactly, for the fourth round running.** All
  **569** classified paths have the same class on x86-64, there is **no x86-64-only row** and
  **no arm64-only row** (§2.2). The x86-64 backend is not where the remaining coverage is.
* **Coverage rose 30.2 % → 31.1 % and the codegen findings fell 311 → 308** on a scope 13
  files larger (§2.1). Three of the four files that left the non-pass set are the three
  `…_b9.md` §4.1 said the export-gate rule would build (`std/_gpu/host/__init__.mojo`,
  `std/compile/__init__.mojo`, `std/os/path/__init__.mojo`) — **the prediction held** — and the
  fourth is `std/algorithm/backend/cpu/map.mojo`, whose `value with no representation` row
  emptied with it. **No `backend-crash` anywhere and no `tool` row at all**, the first round
  in this series with neither (§1.3).

---

## 1. The run

### 1.1 The commands, and how long they took

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86-10 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-10.txt 2>&1 &
python3 tools/memslot.py --gb 8 --label sweep-arm-10 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-10.txt  2>&1 &
```

**The x86-64 arm started at 00:03:43 and the arm64 arm at 00:19:36** — a sixteen-minute gap
that is worth stating rather than hiding, because it is the arm64 `flock` doing its job and
because the log's first line records it. `formal_sweep.py` keeps a separate
`cas/formal-imports/<arch>/` **and** a separate per-architecture `flock`, and at 00:03 two
sibling workers held the arm64 lock (labels `s20osio` over `std/os`+`std/io`+`std/python`
and `sw20-arm64` over `std/collections`+`std/memory`+`std/algorithm`). `--allow-concurrent`
is the tool's own escape hatch and it is the **wrong** answer for two sweeps of the SAME
architecture — they share the module-dylib output directory and the ledger, so a reader in one
sweep can see the other's half-written manifest, which is what a `json.decoder.JSONDecodeError`
in the `tool` class is. So the arm64 arm went through a waiter that polls the tool's own lock
(`.tmp/run_arm10.sh`, scratch) and launched the moment it was free, at 00:19:36. Its first
log line is that waiter's, which is why `sweep-arm-10.txt` does not begin with `memcap:`.

**51 minutes for the x86-64 arm and 35 for the arm64 one**, at `-j 4` each — eight concurrent
builds on an eighteen-core box that started the run at **load 21** with nineteen users. That
load is the whole difference from `-9`, and it is the measurement behind `…_b8.md` §1.1's
"`-t` is a CPU budget divided by the load, so it has to be sized against the machine":
**`-9` ran its first quarter at load 60-97 and left 14 files with no verdict; the same
`-t 120` on a box at load ~20 answered all 710.** §1.3 has the numbers.

Both arms **exit 1**, which is right: the run has real findings, and the `memcap:` line each
log ends with says so (`child exit 1`). `memcap` never breached — peak **0.7 GB** across 9 and
10 processes against the 8 GB reservation.

The interpreter is not optional (`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend_needs_3_10.md`):
`export PATH=/opt/homebrew/bin:$PATH` first, or the tool refuses to start with a diagnosis
rather than a wait.

### 1.2 Scope: 710 files

This worktree's own **458** `*.py`/`*.mojo` plus the **252** under
`../new-modular/Mojo/stdlib/std`. The repository has grown from 445 to 458 since `-9`, and
that is the whole of the scope delta: **13 files added between `55951ba3` (the `-9` tree) and
`3c3516db`, of which 12 are non-pass and exactly one passes on arrival** —
`formal/examples/bittest.mojo`. **Nine of the twelve are new census tools**
(`tools/{formal_proof_fuzz,formal_unstated_base_subscript_census,elab_fail_census,undef_import_census,repro_indexlist,dumpc,linkcheck}.py`,
`test_formal_{proof_fuzz,frame_field_census,x86_64_call_tree}.py`), and **eleven of the twelve
land in `not-answerable`** on arrival — a tool that imports `ast`, `re`, `pathlib` or `pytest`
is a fact about the target, not a gap in the backend, so the scope growing by 13 files moved
the denominator's host-import class by 10 and the rate not at all. A reader comparing this
scope with `-9`'s should read that sentence before reading the rate.

### 1.3 No `tool` row at all, for the first time in this series

`-9` finished with **14 files it could not answer** — every one of them the largest stdlib
module, every one of them a `timeout` at `-t 120`, and every one of them needing a second
sweep at `-t 420` before `-9`'s table could be read (`…_b9.md` §1.3). **This round has an
empty `tool` class**, so there is no second sweep to fold in and no reading of the table that
flatters the rate: **all 710 files have a verdict, on both architectures.**

All **14** of `-9`'s unanswerable files are answered here, and none of them is a pass:

| `-9`'s unanswerable file | `-10` class | terminal cause |
|---|---|---|
| `std/collections/{list,optional,span}.mojo`, `std/collections/string/{string,string_span}.mojo`, `std/format/_utils.mojo`, `std/io/io.mojo`, `std/math/math.mojo`, `std/python/{_cpython,bindings}.mojo` | `codegen/dependency` | the export gate's row, then the unclassified bare call (§3) |
| `std/ffi/__init__.mojo`, `std/memory/pointer.mojo`, `std/os/path/path.mojo`, `std/simd.mojo` | **`codegen`** — in-file, one edge further on than `-9`'s retry measured | §3's rows |

That last row is the finding and not a rounding error: **`-9`'s retry classified all 14 as
`CODEGEN/DEPENDENCY`, and four of them are now refused in their own source.** A file's class
is the FIRST refusal its build walk reaches, so a fix in front of a file moves it from
`codegen/dependency` to `codegen` with nothing about the file changing — which is the same
property `FILES BLOCKED IS AN UPPER BOUND` states, showing up in the class column this time.

---

## 2. Class counts

### 2.1 Against `-9`

Left column: `-9`'s **answered** table (`…_b9.md` §2.1's middle pair — its own summary plus the
14 timeouts re-answered at `-t 420`), which is the only `-9` figure comparable with a run that
has no `tool` row. Right column: this run, which needs no folding.

| class | **`-9` answered** | **`-10`** | Δ |
|---|---|---|---|
| **pass** | 136 | **141** | **+5** |
| built-with-admitted-contracts | 4 | 4 | 0 |
| **codegen** (a refusal IN this file) | 63 | **80** | **+17** |
| **codegen/dependency** (refused in a module it imports) | 248 | **228** | **−20** |
| not-answerable/host-import | 234 | 244 | +10 |
| not-answerable/unresolved-import | 7 | 8 | +1 |
| not-answerable/unresolved-extern | 0 | 0 | 0 |
| not-answerable/system-module-call | 0 | 0 | 0 |
| not-answerable/target-limit | 5 | 5 | 0 |
| **backend-crash** | 0 | 0 | **0** |
| **tool — no verdict at all** | 0 | **0** | **0** |
| **files swept** | 697 | **710** | +13 |
| **codegen coverage** | 136/451 = **30.2 %** | 141/453 = **31.1 %** | **+0.9 pp** |

**308 of the 710 files carry a codegen verdict** (`80 + 228`), against 311 in `-9`, on a scope
13 files bigger. **`backend-crash` is 0 and `tool` is 0** — a crash is never cached, so it
costs a build per arm per sweep until it is gone, and a `tool` row is a file the sweep says
nothing about, which is not the same as a file it has cleared.

The classes that are neither "no verdict" nor coverage, with this run's counts:

| class | n | what it is |
|---|---|---|
| `not-answerable/host-import` | 244 | imports a CPython module with no Mojo source. **123 import a module a Mojo-side implementation could in principle provide** and 121 need a host process, an embedded interpreter or a kernel object. By module: `importlib x54`, `glob x51`, `zlib x29`, `collections x24`, `unittest x13`, `copy x11`, `itertools x11`, `types x10`, `signal x7`, `random x5`. In reach and therefore work: `collections, copy, datetime, functools, glob, inspect, itertools, random, resource, shlex, types, uuid`. Not in any rate |
| `not-answerable/unresolved-import` | 8 | `formal_fuzz`, `formal_proof_fuzz`, `formal_sweep`, `formal_sweep_causes`, `lang_spec`, `mojo_compiler`, `pytest`, `tools` — **four are this sweep's own tools and its own causes tool**, which import each other; `lang_spec` is imported by `fe_reader.py` and in no module set; `mojo_compiler` is the pre-rename name of `fire_compiler` and exists only as an import |
| `not-answerable/target-limit` | 5 | `mojo_sqlite3_open` in the five `test_sqlite3*.mojo` files |
| `built-with-admitted-contracts` | 4 | `formal/hostmods/{concurrent/futures,ctypes,subprocess,threading}.mojo` build but rest on declared assumptions about a host this image does not have; counted in the denominator, never as passes |

### 2.2 arm64 vs x86-64: **zero** architecture-dependent verdicts

`python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-10.txt bugs/sweeps/sweep-x86-10.txt`
— the repository's own instrument for this, which `…_b7.md` §2.5 exists because an earlier map
computed it by hand with a script nobody could run again:

| | this run |
|---|---|
| paths classified on both | **569** |
| **of those, class CHANGED** | **0** |
| x86-64-only rows (a pass on arm64) | **0** |
| arm64-only rows (a pass on x86-64) | **0** |
| class counts that differ | **none** |
| **of those, REASON CHANGED** | **1** |

`-8`, `-9` and this one have no x86-64-only row; `-8`'s
`formal/hostmods/os/_syscalls.mojo` `$INODE64` (the x86-64 libSystem ABI spelling, unsuffixed
on arm64) was fixed at `-8` and stays fixed. **In 710 files the two architectures produce the
same verdict for every single one.**

**The one REASON CHANGED is the architecture's own name inside a filename**, and it is worth
quoting rather than summarising because it is the only sentence in which the two machines
disagree at all:

```
../new-modular/Mojo/stdlib/std/collections/_asan_annotations.mojo  (codegen/dependency)
    arm64: __init__.mojo: std_sys_compile.f2586d6943af.ff1d99a6d0db.arm64.dylib re-exports compile_info …
    x86_64: __init__.mojo: std_sys_compile.f2586d6943af.ff1d99a6d0db.x86_64.dylib re-exports compile_info …
```

Same file, same construct, same refusal — and the tool reports it because it folds architecture
LABELS to `<arch>` but deliberately leaves an architecture name that is **part of a file name**
alone, since that file is the key. So this is the parity instrument being conservative about a
mangled dylib path, not a divergence in what the backend can lower.

### 2.3 The per-file delta `-9` → `-10`: 19 of 557 common paths changed class

| | arm64 | x86-64 |
|---|---|---|
| paths classified by `-9` (retry folded in) | 561 | 561 |
| paths classified by `-10` | 569 | 569 |
| common paths | **557** | **557** |
| **class CHANGED** | **19** | **19** |
| new non-pass rows (the scope grew by 13; 12 of the 13 are non-pass) | 12 | 12 |
| **paths that left the non-pass set (now passing)** | **4** | **4** |

| move | n | reading |
|---|---|---|
| `codegen/dependency` → `codegen` | **18** | the `with open(…) as …` fix and the per-edge export gate landing: a file whose first refusal was one level down is now refused in its own source |
| `codegen/dependency` → `not-answerable/host-import` | 1 | `test_module_cache.py`, which grew an `import itertools`. A file's first obstacle moves when the file changes; this is not the backend regressing |

**The four paths that left the non-pass set** are `std/_gpu/host/__init__.mojo`,
`std/compile/__init__.mojo`, `std/os/path/__init__.mojo` and
`std/algorithm/backend/cpu/map.mojo`. **The first three are the three `-9` §4.1 named in
advance** — "**BUILT** | **3** | `std/_gpu/host/__init__.mojo`, `std/compile/__init__.mojo`,
`std/os/path/__init__.mojo`" — so the per-edge export-gate rule did what the map said it would,
and it is worth recording that a map's prediction surviving a round is rarer than it should be.
The fourth is not in any map: `std/algorithm/backend/cpu/map.mojo` was `codegen` at `-9` with
**"a value with no representation on this path"** (a call through a **function value**), and
that row is now **0 files** across the corpus — §3's table has the row at `-9` 2 and at `-10` 0.

### 2.4 The per-CAUSE delta is where this round happened: **212 of 306**

Class counts move 19 files. **Causes move 212**, and the direction is one place:

| move | n | from → to |
|---|---|---|
| **the export gate released them into the UNCLASSIFIED bucket** | **125** | `module exports no public functions` → `other refusal` |
| **the Optional row's whole corpus went dark** | **43** | `Optional unwrap` → `other refusal` |
| the `with` fix handed them to module state | 23 | `a with` → `a module's ATTRIBUTE` |
| `tile.mojo`'s row moved one row out | 5 | `a bracketed specialization` → `variadic call has no ABI` |
| the `with` fix, the rest | 4 | `a with` → `other refusal` |
| the export gate, onto a named row | 3 | `module exports no public functions` → `MLIR dialect construct` |
| `tile.mojo`'s row, into the bucket | 2 | `a bracketed specialization` → `other refusal` |
| seven singletons | 7 | `a with` → a linked module exports no such name, and → a module-global container with no initializer; `value has no representation` → variadic ABI; `struct construction: arity` → unclassified; `module-level name` → unclassified; the export gate → a module-level name, and → a multi-index subscript |
| | **212** | |

**170 of those 212 (80 %) move INTO `other refusal`,** and that is the round's headline. Read
the other direction too: **`Optional unwrap` went 43 → 0 and none of its 43 files was fixed.**
All 43 are in the unclassified bucket, one refusal layer further out, because the export gate
stopped refusing the module they import first. That is `FILES BLOCKED IS AN UPPER BOUND`
arriving as a planner's trap rather than as a caveat: **a documented, claimed, 43-file row
(`FORMAL_stdlib_optional_needs_a_representation`, `formal16-7`) reads as solved in this
table, and it is not.** Nothing about `builtin_slice.mojo`'s `self.step.or_else()` moved.

### 2.5 The CAS was cold, and that is the cost of a moving tree

`cas: 31 hit / 679 miss / 0 not cached` on arm64 and `3 hit / 707 miss` on x86-64. **706 of
710 files were rebuilt from scratch**, because `tools/formal_sweep.py`'s own bytes are in every
cache key (`_criteria_id`) and `cas.formal_fingerprint()` covers `formal/**`, the parser and the
middle tier. A re-run with nothing changed reads a file per file; **editing anything under
`formal/`, the parser, `mojo/middle/`, or `tools/formal_sweep.py` invalidates the whole
sweep.** The 31 arm64 hits are files another arm64 sweep on this machine had already built
under the same fingerprint.

---

## 3. Ranked causes

`python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-10.txt` — and the x86-64
arm prints the same table with the same numbers, which follows from §2.2. The `-9` column is
the same tool over `sweep-arm-9.txt` with `sweep-arm-9-retry.txt` folded in, which is the only
way to read a `-9` that had a `tool` class.

**FILES BLOCKED IS AN UPPER BOUND**: a file's terminal cause is the first refusal its build
walk reaches, so fixing one moves the file to the next with the count unchanged.

| files | `-9` | in-file | cause | refused in | owner / next step (§4) |
|---|---|---|---|---|---|
| **184** | 8 | 27 | **`other refusal`** — see below: **170 of the 184 are ONE construct with no row in the table** | (this file) x27, `std.collections` x13, `std.collections.string.string_span` x11, `std.builtin.rebind` x9, `std.os` x8, `std.ffi` x8, `std.memory` x7 | **§5 — FIXED on this branch** |
| **33** | 166 | 0 | a module that exports nothing cannot be a dylib | `_io.mojo x17`, `constants.mojo x13`, `_select.mojo x1`, `_unicode_lookups.mojo x1`, `stat.mojo x1` | `FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib`, **claimed** (`formal16-2`); the 30 that stay are the constants-only family §4.1 |
| **30** | 5 | 10 | a module's ATTRIBUTE read as a value, across a dylib boundary | `module_loader.py x20` (`os.path`), (this file) x10 (`sys.argv x6`, `stat.S_IXUSR`, `os.environ`, `sys.executable`, `sys.stdin`) | `FORMAL_module_state_no_storage`, **claimed** (`formal19-4`); a project, §4.2 |
| **30** | 30 | 25 | a handler arm with a body (no unwinder to emit it into) | (this file) x25, `memslot.py x5` | `FORMAL_except_arm_is_never_emitted`, **claimed** (`formal8-5`); a refusal that is CORRECT, §4.3 |
| **7** | 1 | 2 | variadic call has no ABI | `tile.mojo x5`, (this file) x2 | **unowned and undocumented** — filed as `FORMAL_a_variadic_parameter_read_has_no_abi.md`, §4.4 |
| **5** | 2 | 3 | MLIR dialect construct (`__mlir_attr` / `__mlir_type` / `__mlir_op`) | (this file) x3, `function.mojo x2` | `FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops`, **claimed** (`formal19-4`) |
| **3** | 10 | 0 | a bracketed specialization of a callee this unit does not compile | `random.mojo x3` | `FORMAL_stdlib_tile_row…`, **claimed** (`formal16-7`); 5 of its 10 files moved to the row above |
| **3** | 3 | 1 | frame address passed where a value is wanted | `type_system.py x2`, (this file) x1 | `FORMAL_known_limits.md` §(isinstance); a value-model decision, §4.5 |
| 2 each | | | method call on a value receiver; a linked module exports no such name | (this file) x2 each | §4.6 |
| 1 each | | | 10 further single-file causes | | §4.7 |

### 3.1 The 184-file `other refusal` row is 170 files of ONE construct

`other refusal` is the bucket `tools/formal_sweep_causes.py`'s own module docstring defines as
*"nobody has looked"*, and it was 8 files at `-9`. Grouping its terminal messages by the symbol
the refusal names (`.tmp/` scratch, the tool's own `_split_chain` / `_terminal_reason` /
`_refuser`):

| files | the call the build could not bind | where it is written |
|---|---|---|
| **111** | `FormatStruct(writer, "Allocation")` | `std/format/_utils.mojo:287`, against `struct FormatStruct[T: Writer, o: MutOrigin]`. **68 of the 111 are `std/memory/alloc.mojo`'s own `alloc.mojo:450`** — and `alloc.mojo` is in nearly every stdlib file's closure |
| **29** | `dealloc(allocation^)` | `std/memory/alloc.mojo:99` against its own `:904` |
| **13** | `is_negative(value)` | `std/bit/log2_floor.mojo` |
| **6** | `PhiloxRandom(seed)` | `std/random` |
| **3** | `align_up(x)` | `std/math` |
| **2 each** | `Path(…)`, `os.environ.get()` | repo files and `determinism_trace.py`'s closure |
| 1 each | `keep`, `strided_load`, `stat`, `isnan`, `_isnan`, `now` | |
| **170** | **all of the above, and every one of them the same sentence**: *"`X` is called, and it is imported from `M`, so the call has to bind a symbol `M` exports. That module does not export it, and the reason is `doc/ABI.md`'s export rule…"* | |
| 14 | fourteen other constructs, each its own row or its own file | §4.7 |

**170 files, 14 distinct symbols, 64 distinct modules the call is written in, 79 distinct
(symbol, module) call sites.** The largest single site is **13 files** (`FormatStruct` called
from `std/collections`), and `FormatStruct` alone is **111 of the 170** — so the row is one
construct repeated across the stdlib rather than one bad line, and a worker should read it as
"the inference `formal/monomorph.py::demands` does not do" rather than as a list of 79 edits.
The biggest sites, measured:

| files | symbol | the call is written in |
|---|---|---|
| 13 | `FormatStruct` | `std/collections` |
| 11 | `FormatStruct` | `std/collections/string/string_span` |
| 9 | `FormatStruct` | `std/builtin/rebind` |
| 8 | `dealloc` | `std/os` |
| 8 | `dealloc` | `std/ffi` |
| 7 | `FormatStruct` | `std/memory` |
| 6 | `FormatStruct` | the swept file itself |
| 5 | `FormatStruct` | `std/format/_utils` |

**`tools/formal_sweep_causes.py` has no row for that sentence.** It is 170 files — **55 % of
every codegen finding in 710 files, from one construct and one sentence** — and the ranking
instrument reports it as *unclassified*. Its fix is `formal19-1`'s claim
(`FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`, 123 files measured
on the `-9` tree; 170 on this one), and **this branch does not touch that construct.** §5 is
about the row, not the construct.

### 3.2 The 14 files in the bucket that are not that sentence

`std/builtin/float_literal.mojo`'s `self.__int_literal__().__int__(…)` (dispatch is BY NAME and
the callee is not a bare name); `std/collections/type_dict.mojo`'s `comptime` class attribute
read off a type PARAMETER; `std/sys/arg.mojo`'s `Span[StaticString, ImmStaticOrigin]` read as a
subscript rather than a compile-time parameter list; `std/utils/_serialize.mojo`'s
`p.unsafe_load()`; `bootstrap_test_classes.mojo`'s `create_point` returning a frame address
that the returned-frame convention has no caller for; `formal/elf.py`'s own
`struct.pack(9 arguments against 6 parameters)`; `mojo/backend_gimple/device_glue.py`'s
iterating a `char *`; `determinism_trace.py` + 2 through it + `test_coro_runtime.py`'s
`os.environ.get()` (a call through a **function-valued** module attribute — §4.2's value-model
half); `std/collections/{set,owned_pointer}.mojo` through `builtin_slice.mojo`'s `slice returns
a frame address`; `std/collections/_asan_annotations.mojo`'s re-export of `compile_info`. Each
is one file's own source, one stdlib module's own source, or a value-model question with a doc.

### 3.3 The `uses:` column is NOT MEASURED on the top row, and that is the finding

| refusing module | blocks | files that name anything it declares | reading |
|---|---|---|---|
| `std.format._utils`, `std.memory`, `std.collections`, `std.collections.string.string_span`, `std.builtin.rebind`, `std.os`, `std.ffi`, … | 170 | **`not measured` — every one of them** | the chain names a module by dotted path and `formal_sweep_causes.py` resolves a refuser by **basename**, which is ambiguous in this tree (`std.collections` is both a stdlib package and a hostmod; `.` is a relative import). The tool says so rather than picking one — correct, and a real limit |
| `module_loader.py` | 20 | **0** | closure; the refusal is about the module's own body |
| `tile.mojo` | 5 | **5** (`tile`) | **work** — every blocked file uses it |
| `_io.mojo` | 17 | **0** | closure, and it cannot be otherwise: the module declares no name the export rule could exclude |
| `builtin_slice.mojo` | 2 | **0** (`slice`) | closure |
| `determinism_trace.py` | 2 | **0** | closure |

**So the 170 cannot be sized by `uses:` in this round, and the number to read instead is
§3.1's: 79 distinct (symbol, module) call sites, largest 13.** That is a weaker statement than
the `binary_heap.mojo` row of `-9` §3.1 could make (162 of 163 named nothing it declares) and
it is the tool's honest limit rather than a gap in it: `_resolve_refuser` looks the basename up
in a module index built from *paths*, so a dotted chain name cannot be resolved and the row
says `not measured` instead of inventing a 0. **A worker should not read "not measured" as
"closure"** — for `tile.mojo` the same column says 5 of 5 and the row really is work.

---

## 4. Next step per cause, and the ceilings that are measured

Ordered by files blocked. **Every row above 7 files is claimed, measured here to be closure, or
is §5.**

### 4.1 The 33-file export-gate row is the constants-only family, and it is permanent

`_io.mojo` (17) and `constants.mojo` (13) declare **no function and no type at all — only
module-level constants**, which are inlined at their use site and cross no boundary. There is
no boundary symbol for any edge, so the per-edge rule of §5's neighbour
(`formal/imports.py::library_free_edges`) has nothing to decide: every edge into these modules
*does* bind something, and that something is a constant.
`FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md` is the doc and `formal16-2` holds
the claim. **Nothing here.** The other three files of the row are a `_`-prefixed private
(`_select.mojo`), a `_unicode_lookups.mojo` that declares no name at all, and a `stat.mojo`
whose basename is ambiguous in this tree (a stdlib package *and* a hostmod).

### 4.2 The 30-file module-attribute row is `os.path` and `sys.argv`, and it is a project

`FORMAL_module_state_no_storage` (**claimed**, `formal19-4`) is the right document.
`-9` §5.2 predicted this row would go from 5 files to 29 with the `with` fix landed, and
**measured 30** — 23 files moved `with` → module ATTRIBUTE in §2.4 and 7 were already there.
`os.path` through `module_loader.py`'s one line is 20 of the 30 and **0 of those 20 name
anything `module_loader.py` declares**, so it is closure; the other 10 are the file's own
`sys.argv x6`, `stat.S_IXUSR`, `os.environ`, `sys.executable`, `sys.stdin`. The refusal points
at the doc rather than at a missing container, which is the property that makes it worth not
"fixing": an exported slot, a command line, and a value-model question (`os.environ` is a
FUNCTION on this path, so `.get()` on it is a call through a value — 4 more files).

### 4.3 The 30-file handler-arm row is a refusal that is CORRECT

`formal` has no exception unwinder: a `raise` flushes the enclosing `finally` clauses and
exits, so no edge runs from a raise site into an arm and every statement in an arm's body would
be absent from the program that runs. It is in the taxonomy because "refused on purpose" and
"nobody has looked" are different answers, and its number is a census rather than a target.
`FORMAL_except_arm_is_never_emitted`, claimed by `formal8-5`. Nothing here.

### 4.4 The 7-file variadic row is unowned, undocumented, and NOT fixable narrowly

`std/algorithm/backend/tile.mojo` reads its own `*tile_size_list` (5 files blocked, all 5
naming `tile`, so **work**), and `formal/x86_64_decode.py` spreads `**kw` into a construction
(1 file). `formal/build.py::_refuse_variadic_reads` refuses the read by name, and **the refusal
is right**: the caller side already passes the fixed parameters and drops the rest, so a
variadic parameter's value is *not knowable* — `def f(x, *rest): return len(rest)` called
`f(1, 2, r)` must answer 1, and the only cheap lowering (the read is the empty sequence, since
every extra argument is dropped) answers 0. **That is a wrong-but-exit-0 answer, which is the
one thing this backend does not emit.** The fix is a variadic ABI shared by both emitters AND
`lib/ProofLib.lean`, and the argument for why that is a project rather than a patch is written
down in the doc this branch filed. **No claim existed; that was the gap.**

### 4.5 `isinstance()` on a multi-field struct — 3 files

`type_system.py` passes a Type frame address to `isinstance()`, which is lowered as an
operation on a VALUE. The refusal is right about the program and its repair is a value-model
decision: either `isinstance` learns a frame-receiver form, or a multi-field struct grows a
value form. Both are larger than three files, and 0 of the 3 name anything `type_system.py`
declares — they are closure. Recorded in `FORMAL_known_limits.md`.

### 4.6 The remaining 2-file rows

* **method call on a value receiver** (`std/collections/binary_heap.mojo`'s own `self.clear()`,
  `std/builtin/float_literal.mojo`'s `write_repr_to`): one stdlib file's own source each, and
  the stdlib is not editable from a repository worktree.
* **a linked module exports no such name** (`runtime/stdlib_wrapper.mojo`,
  `tools/wave1_move_shared.py`, `tools/wave2_move_shared.py`, all through `sys.exit(…)` /
  `pathlib.Path`): `formal/hostmods/sys.mojo` has no `exit` and its own docstring says why —
  `doc/ABI.md`'s export rule declines to advertise a C library symbol and `exit` is one.
  **Deliberately not taken**: it would reverse a decision `sys.mojo`'s docstring and
  `test_formal_sys.py` both pin.

### 4.7 The single-file causes

Ten of them, each either one file's own source, one stdlib module's own source, or a
value-model question with a doc (§3.2 lists all of them). **None is a shared-backend patch.**

---

## 5. What this branch changed, measured

One commit on top of `master` at `3c3516db`, and it is **in the ranking instrument, not in the
backend**: the corpus's largest cause had no row, so the queue could not prioritise it.

### 5.1 The fix: `tools/formal_sweep_causes.py` gets a row for the corpus's largest construct

`other refusal` was **8 files at `-9` and 184 at `-10`**, and **170 of the 184 are one
sentence** — a call to a name the defining module does not export (§3.1). The table's own
comment on the `==` row says what a construct that large sitting in that bucket means: *"not a
rounding error in a reader's judgement; it is the tool declining to do the one job it exists
for."* `…_b9.md` §5.1 fixed the same defect for the `with`, in the same commit as its fix.

**The row is placed next to the two other callee rows, above the `is passed to` pair, and its
marker is a clause that is load-bearing rather than incidental.** `formal/model.py`'s
`imported_callee_refusal` opens every such message with *"`X` is called, and it is imported
from `M`, so the call has to bind a symbol `M` exports"* — and *"`That module does not export
it`"* is the fact the whole message exists to state. **Both survive the reword on
`work/formal19-1`, which is the branch that owns the construct's fix** (its `master..work/formal19-1`
diff of the message was read before this row was written: it drops "spell it as
`name[<a type>](…)`" and says the bare call is correct source, and keeps both clauses). A
marker keyed on the clause that is going away would have taken 170 files silently back to
`other refusal` the day that branch lands, which is the failure mode the table's comments
warn about twice.

**Two samples, not one**, because `classify_message` sees only the message and one sample is
one proof its marker matches: the two are the row's two ends — the stdlib's own
`FormatStruct(writer, "Allocation")` and a repo file's `now()` through `time` — and both are
cut from `formal/model.py`'s own f-string rather than from a sweep log, so they cannot drift
from the sentence they classify.

### 5.2 The fix's effect on the ranking, measured

The same command over the same log, before and after:

| | `-10` as swept | **`-10` with §5.1's row** |
|---|---|---|
| rank 1 | 184 `other refusal` (170 of them one construct) | **170 `a call to a name the defining module does not export`** |
| rank 2 | 33 `module exports no public functions` | 33 (unchanged) |
| rank 3 | 30 `a module's ATTRIBUTE read as a value` | 30 (unchanged) |
| rank 4 | 30 `a handler arm with a body` | 30 (unchanged) |
| rank 5 | 7 `variadic call has no ABI` | 7 (unchanged) |
| `other refusal` | 184 | **14** |
| causes that fired (of 20 in the table) | 19 | **20** |
| causes printed at `--min 3` | 8 | **9** |

**Every one of the 20 causes in the table now fires on this sweep** (`19 of 19` before), and
the largest row in the corpus is the one a reader should look at first, with its owner in §3's
table. The **14** residual `other refusal` files are §3.2's list, and every one of them is a
distinct construct.

**This fix converts 0 files to passes, and that is the measurement rather than a
disappointment** — `…_b9.md` §5.2 says the same about the `with`. What it buys is that the sweep
now reports the truth about where the corpus actually stops, and that a queue reading this map
sees 170 files, 14 symbols and 79 call sites, instead of 184 files and a shrug.

### 5.3 The tests, and what they prove

`test_refusal_taxonomy.py` is the file that exists for this, and it is what a change to
`CAUSES` has to pass:

* **the two new samples classify to the new row** — `check_cause_table` asserts
  `classify_message(sample) == label` for every sample, so a marker that matches nothing fails
  here rather than reading as a cause that blocks nothing;
* **the new row is reachable from a real message** — the same function asserts every label in
  `CAUSES` is classified by at least one sample (or is in `NO_ARM64_SAMPLE`), which is the
  dead-marker check;
* **nothing shadows it** — the table is a first-match list, so a row placed after a broader one
  is dead code that fails silently. The new row sits with the other callee rows and before the
  `is passed to` pair, and `test_refusal_taxonomy.py`'s precedence section is what would catch
  a move.

```console
$ python3 test_refusal_taxonomy.py
refusal taxonomy: PASS (219/219 checks, 38 families, 61 causes)
$ python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-10.txt | head -3
files in-file  cause
  170      18  a call to a name the defining module does not export
   33       0  module exports no public functions
```

**61 causes where there were 60**, and the 219 checks are the file's own count (it asserts its
own arithmetic), so the two new samples and the new row are both accounted for rather than
merely added.

**The one thing this change cannot prove, stated rather than implied:** the row now says **170
files** on this log, and it will say something else on every other log ever taken. That is the
tool working — a sweep log is an artifact and the table reads the old ones too — and it is why
the samples are cut from `formal/model.py`'s f-string rather than from a log: a reword of that
f-string that broke the marker would fail `test_refusal_taxonomy.py` instead of quietly moving
a column.

---

## 6. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
# §1.1: the x86-64 arm, and the arm64 arm behind the same flock the tool takes
python3 tools/memslot.py --gb 8 --label sweep-x86-10 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-10.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-arm-10 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-10.txt  2>&1

python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-10.txt            # §3
python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-x86-10.txt            # §3, the same table
python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-10.txt \
                             bugs/sweeps/sweep-x86-10.txt                    # §2.2
python3 test_refusal_taxonomy.py                                           # §5.1, §5.3
python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-10.txt   # §3, §5.2
```

**§2.1's class counts are not computed by a reader**: they are the `(classes sum to 710 = 710
files swept)` block each log ends with, which the sweep runner computes and checks against the
file count, so they are the authority and quoting them is reading them. **§2.3 and §2.4's
per-file and per-CAUSE deltas are two runs compared**, which no committed tool does: they are
`formal_sweep_causes.py::rank` over each log (which peels every chain to its terminal message
with the sweep's own `_split_chain` / `_terminal_reason`) plus a set difference on the printed
`CLASS: path` lines, with `sweep-arm-9-retry.txt` folded into the `-9` side — a retry sweep's
verdict REPLACES the `tool` verdict the first pass could not reach, because "no verdict" is not
a class of its own. `.tmp/analyze10.py` is that computation, **scratch and not committed**
(`.tmp/` is git-ignored, and `…_b7.md`/`…_b8.md`/`…_b9.md` each described their scratch the
same way). `…_b7.md` §2.5's reason for `tools/formal_sweep_parity.py` existing — "computed by
hand, with a scratch script nobody could run again" — is the reason §2.2 above cites the tool
instead, and **the honest reading of that is that §2.3/§2.4's scratch should have become a
second tool rather than a fourth description of one.**

**86 minutes of wall for both arms together**, 51 of them the x86-64 arm and 35 the arm64 one,
the difference being the sixteen minutes it waited for the arm64 lock (§1.1). The CAS is
content-addressed and machine-wide, so a re-run with nothing changed reads a file per file;
**editing `formal/`, the parser, `mojo/middle/`, or `tools/formal_sweep.py` invalidates all of
it** — which is why this run rebuilt 706 of 710.

Both arms exit 1 (real findings; each log's `memcap:` line says `child exit 1`). `memcap` never
breached: peak **0.7 GB** across 9 and 10 processes against the 8 GB reservation, on either arm.