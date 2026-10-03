# FORMAL_sweep_work_map_2026-10-03_b8: a fresh, complete sweep of this repository and the stdlib, both architectures

**Claim** `sweep14:sweep-b8` on `work/formal14-sweep-b8`. This tree is `master` at
`17ddeaec` plus this branch's two commits (§2.3). Both arms ran to completion over
the whole 679-file scope at `-t 120`, so every number here is over the whole scope.

Four things a reader should take away, in the order they matter:

* **The run is CLEAN.** Every one of the 679 files got a verdict from a build, on
  both architectures, and there is no `tool` row, no `backend-crash`, and — for the
  first time in this series — **no `unknown` and no `system-module-call`**. Those
  last two were defects in the sweep's own classifier, found by this run and fixed
  on this branch (§2.3, 18 files re-filed and no number faked).
* **The two architectures are the same sweep, exactly.** All **548** classified
  paths have the same class on x86-64, and there is **no x86-64-only row at all**.
  The one architecture-dependent verdict the `-7` map recorded
  (`formal/hostmods/os/_syscalls.mojo`'s `$INODE64`) is **gone**: that file builds
  and passes on both. **The x86-64 machine subset is not where the remaining
  coverage is.**
* **The headline fell and the finding count rose, and the reason is not a
  regression.** Coverage is **131/443 = 29.6 %** against `-7`'s **126/415 = 30.4 %**,
  while the number of files carrying a codegen verdict rose from **285 to 308**.
  26 files moved INTO the codegen classes from `host-import`/`unresolved-extern`/
  `backend-crash` and 7 moved out. **Almost none of that is a codegen fix**: it is
  hostmod work landing (`subprocess`, `ctypes`, `threading`, `concurrent`,
  `collections`, `copy`, `glob`, `itertools`, `types`, …), so files now get *past*
  their import and hit a real construct refusal one level deeper. A file that was
  "a fact about the target" and is now "a gap in the backend" is **progress**, and
  the rate's job is to fall while it happens (§2.4).
* **The largest unowned codegen row is 20 files and its next wall is measured, not
  projected.** The 165-file row has a second wall behind it that is a project
  (§3, row 1); the 20-file row's next refusal was measured by lifting its own check
  and is `os.environ` — another row's project (§3, row 4). **Neither is a patch, and
  that is the finding.** What was fixable in this row IS fixed: the 3-file
  `formal/__init__.py` refusal, which was a docstring being refused as a dylib
  (§2.3).

---

## 1. The run

### 1.1 The commands, and how long they took

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-arm-8 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-8.txt  2>&1
python3 tools/memslot.py --gb 8 --label sweep-x86-8 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-8.txt 2>&1
```

Both arms at once, as in every earlier map: `formal_sweep.py` keeps a separate
`cas/formal-imports/<arch>/` **and** a separate per-architecture `flock`, so the two
arms share nothing. **20 minutes of wall for both arms together** (launched
08:10:53, logs written 08:31:21 and 08:32:06), at `-j 4` each — eight concurrent
builds on an eighteen-core box that was carrying load 14-18 with a dozen other
workers on it. That is the same order as `…_b7.md` §1.1's "-j 6 -t 120, half an
hour per arm", and it confirms that map's correction of `…_b6.md`'s four-to-six
hour projection: **`-t` is a CPU budget divided by the load, so it has to be sized
against the machine.**

The interpreter is not optional
(`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend_needs_3_10.md`):
`export PATH=/opt/homebrew/bin:$PATH` first, or the tool refuses to start.

**The first attempt at both arms refused to start, and that is worth recording
because the message is a refusal rather than a wait.** A sweep takes its
architecture's machine-wide `flock`, and another worker held each of the two
(`.tmp/run_sweep.sh` retries until it gets it; the message is
`another arm64 sweep is already running on this machine`). The flock is
kernel-released, so waiting is always correct — and `--allow-concurrent`, which
the tool also offers, is NOT the right answer here, because two sweeps of the same
architecture share `~/.gmojo/cas/formal-imports/<arch>/` and a reader in one can
see the other's half-written artifact. Both arms started on their first retry,
about 90 s later.

Both arms **exit 1**, which is right: the run has real findings. `memcap` never
breached — peak **0.6 GB** across 11 processes against the 8 GB reservation, on
either arm.

### 1.2 Scope: 679 files

This worktree's own **427** `*.py`/`*.mojo` plus the **252** under
`../new-modular/Mojo/stdlib/std`. The repository has grown from 416 (`-7`'s count)
to 427 across the `formal13` merges, which is the whole of the scope delta and the
reason the two runs' denominators differ.

### 1.3 The CAS was cold, and that is the cost of changing the tool

`cas: 6 hit / 673 miss` on arm64 and `3 hit / 676 miss` on x86-64. **665+ of 679
files were rebuilt from scratch**, because `tools/formal_sweep.py`'s own bytes are
in every cache key (`_criteria_id`) and this branch changed that file. A re-run
with nothing changed reads a file per file; **editing anything under `formal/`, the
parser, `mojo/middle/`, or this tool invalidates the whole sweep.**

---

## 2. Class counts

### 2.1 This run, both arms, complete — and the two arms are identical

Read off the two summaries; the classes sum to 679 in both, which the runner
checks itself.

| class | `-7` arm64 | **`-8` arm64** | Δ | `-7` x86-64 | **`-8` x86-64** | Δ |
|---|---|---|---|---|---|---|
| **pass** | 126 | **131** | **+5** | 125 | **131** | **+6** |
| built-with-admitted-contracts | 4 | 4 | 0 | 4 | 4 | 0 |
| **codegen** (a refusal IN this file) | 47 | **60** | **+13** | 47 | **60** | **+13** |
| **codegen/dependency** (refused in a module it imports) | 238 | **248** | **+10** | 238 | **248** | **+10** |
| not-answerable/host-import | 241 | **225** | **−16** | 241 | **225** | **−16** |
| not-answerable/unresolved-import | 1 | 6 | +5 | 1 | 6 | +5 |
| not-answerable/unresolved-extern | 2 | **0** | −2 | 3 | **0** | −3 |
| not-answerable/system-module-call | 0 (class live) | **0** (class fixed) | 0 | 0 | 0 | 0 |
| not-answerable/target-limit | 5 | 5 | 0 | 5 | 5 | 0 |
| **backend-crash** | **4** | **0** | **−4** | **4** | **0** | **−4** |
| **unknown** | 0 (class live) | **0** (class fixed) | 0 | 0 | 0 | 0 |
| **tool — no verdict at all** | **0** | **0** | 0 | 0 | **0** | 0 |
| **files swept** | 668 | **679** | +11 | 668 | **679** | +11 |
| **codegen coverage** | 126/415 = 30.4 % | **131/443 = 29.6 %** | **−0.8 pp** | 125/414 = 30.2 % | **131/443 = 29.6 %** | **−0.6 pp** |

**308 of the 679 files carry a codegen verdict** (`60 + 248`), against 285 in `-7`.
**The four `backend-crash` rows of `-7` are gone** and the class is empty, which is
the one class a sweep cannot leave behind: a crash is never cached, so it costs four
builds per arm per sweep until it is gone. `…_b7.md` §3.2 recorded them as fixed on
that branch with the diagnosis (`formal/build.py`'s `_constant_read_sites`
destructuring a 3-tuple); this run confirms it with no crash anywhere.

The classes that are neither "no verdict" nor coverage, with this run's counts:

| class | n | what it is |
|---|---|---|
| `not-answerable/host-import` | 225 | imports a CPython module with no Mojo source. **114 import a module a Mojo-side implementation could in principle provide** and 111 need a host process, an embedded interpreter or a kernel object. By module: `importlib x52`, `glob x46`, `zlib x27`, `collections x21`, `copy x10`, `types x10`, `itertools x9`, `unittest x9`, `signal x6`. Not in any rate |
| `not-answerable/unresolved-import` | 6 | `formal_sweep`, `formal_sweep_causes`, `lang_spec`, `mojo_compiler`, `pytest`, `tools` — five of the six are **this sweep's own tools**, which import each other |
| `not-answerable/target-limit` | 5 | `mojo_sqlite3_open` in the five `test_sqlite3*.mojo` files |
| `built-with-admitted-contracts` | 4 | `formal/hostmods/{concurrent/futures,ctypes,subprocess,threading}.mojo` build but rest on declared assumptions about a host this image does not have; counted in the denominator, never as passes |

### 2.2 arm64 vs x86-64: **zero** architecture-dependent verdicts

| | |
|---|---|
| paths classified on both | **548** |
| **of those, class CHANGED** | **0** |
| x86-64-only rows | **0** |
| arm64-only rows | **0** |

Computed path-for-path from the two logs' printed lines (`.tmp/cmp_logs.py`, three
regexes and a `Counter`). `-7` had one x86-64-only row; **this run has none**, and
the row it was is now a **pass on both**:

```
formal/hostmods/os/_syscalls.mojo   -7 x86_64: NOT-ANSWERABLE/UNRESOLVED-EXTERN
                                    (builds, but 5 import(s) dyld cannot resolve:
                                     lstat$INODE64, opendir$INODE64, readdir$INODE64 …)
                                    -8: builds and PASSES on both architectures.
```

`$INODE64` is the x86-64 libSystem ABI spelling; on arm64 the same calls have
unsuffixed names. **It is worth knowing, before anyone spends time on "the x86-64
backend is behind", that in 679 files the two architectures now produce the same
verdict for every single one.**

### 2.3 What this branch changed, measured by the tool rather than by me

`formal_sweep.py` keeps a per-architecture verdict history, and the summary prints
it. Against the previous report on this machine — this session's pre-change tree,
same scope, same `-t` — **both arms report the same three moves and the same 661
unchanged**:

```
verdict history: previous report 2026-10-03T07:00:56 [arm64], 679 files
  codegen/dependency -> not-answerable/host-import: 3
  not-answerable/system-module-call -> codegen: 11
  unknown -> not-answerable/host-import: 4
  unchanged: 661
```

| commit | what | files moved |
|---|---|---|
| `31f20dba` | `_STDLIB_UNCLASSIFIED_MARK`: `formal/imports.py::unresolvable_import_error` has **three** wordings and the classifier knew two, so four files (`tokenize x2`, `plistlib`, `sqlite3`) were filed `unknown`, a class in **no rate** | 4 `unknown` → `not-answerable/host-import` |
| `31f20dba` | `_system_module_call` asked `mod in HOST_MODULES` (which is `UNREACHABLE \| MODELLED \| ADMITTED`), so a **mention** of an admitted module's member read as a **call** into a module with no Mojo source. All eleven rows are one refusal — `except subprocess.TimeoutExpired` with a body — which the class had just hidden from the codegen count. It now asks `host_module_tier()` | 11 `not-answerable/system-module-call` → `codegen` |
| `861192ec` | a package `__init__` that declares **nothing** is a namespace package: `_namespace_library` already emits exactly the right library (a real dylib, an **empty** trie, `kind: "namespace"`) and was reachable only for a package that **re-exports**. `formal/__init__.py` is five lines of docstring and the gate refused it, taking out every file that imports the package | 3 `codegen/dependency` → `not-answerable/host-import` |

**Neither classifier fix changes a coverage rate, by construction**: `unknown` and
`system-module-call` are in neither the numerator nor the denominator, so a file
moving out of one is a file that was **not being counted at all** becoming counted
(or counted as the gap it is). The 11 that became `codegen` **lowered** the rate,
which is the honest direction: the class had been reporting a fact about the target
for a construct refusal, and a construct refusal is a gap.

### 2.4 The per-file delta `-7` → `-8`: 43 of 540 paths changed class, and the direction is a fact becoming a gap

Computed from the two logs' printed lines, path-for-path:

| | arm64 | x86-64 |
|---|---|---|
| paths classified by `-7` | 542 | 543 |
| paths classified by `-8` | 548 | 548 |
| common paths | **540** | **541** |
| **class CHANGED** | **43** | **43** |
| new paths (this tree's 11 new files) | 8 | 8 |
| paths that left the non-pass set (**now passing**) | 2 | 2 |

| move | n |
|---|---|
| `not-answerable/host-import` → `codegen` | **14** |
| `not-answerable/host-import` → `codegen/dependency` | **12** |
| `codegen/dependency` → `not-answerable/host-import` | 5 |
| `not-answerable/host-import` → `not-answerable/unresolved-import` | 4 |
| `codegen` → `not-answerable/host-import` | 2 |
| `backend-crash` → `codegen/dependency` | 2 |
| `not-answerable/unresolved-extern` → `codegen/dependency` | 1 |
| `backend-crash` → `not-answerable/host-import` | 1 |
| `backend-crash` → `not-answerable/unresolved-import` | 1 |
| `not-answerable/unresolved-extern` → `codegen` | 1 |

**26 files moved INTO the codegen classes and 7 moved OUT of them, and the 26 is the
finding.** Read a single one and the mechanism is obvious — `test_formal_value_model.py`
was `host-import` at `-7` and is `codegen` at `-8`, because `subprocess` grew a
`formal/hostmods/` model with `@admitted` contracts, so the file gets past its
import and hits the next construct. **A hostmod landing does not make a file build;
it makes the file report the truth about the next thing that stops it.** That is why
the coverage rate fell while the codegen finding count rose, and it is the same fact
`…_b6.md` §2.1 warned about in the other direction: *do not read the deltas as
regression or as progress; read the two absolute numbers.*

The two paths that **left** the non-pass set, i.e. that now build on **both**
architectures:

* `../new-modular/Mojo/stdlib/std/utils/_select.mojo` — `pop.select` +
  `__mlir_bool__()` are rewritten in the shared pipeline to `a if c else b` and
  `x != 0` (`FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops`'s item 2,
  landed 2026-10-03 by `formal8-7-r2`). It was refused at `-7`; its one dependent,
  `std/builtin/simd_length.mojo`, still is, on its own next construct
  (`pop.cast_to_builtin`, a `_type=` that is a dialect type).
* `stdlib_core.mojo` — no longer refused on `StringRef` having no representation.

---

## 3. Ranked causes

`python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-8.txt` — and
the x86-64 arm prints the same table with the same numbers, which follows from §2.2.

**FILES BLOCKED IS AN UPPER BOUND**: a file's terminal cause is the first refusal
its build walk reaches, so fixing one moves the file to the next with the count
unchanged. **Three of the rows below have that ceiling measured, not projected, and
it is stated in the row.**

| files | in-file | cause | refused in | owner / next step (§4) |
|---|---|---|---|---|
| **165** | 2 | a one-field struct's mutator has no convention to write its answer back | `binary_heap.mojo x163`, (this file) x2 | **project**, two walls. §4.1 |
| **50** | 7 | other refusal | `builtin_slice.mojo x43`, (this file) x7 | 43 = `formal13-3`'s; 7 in-file |
| **27** | 22 | a handler arm with a body (no unwinder to emit it into) | (this file) x22, `memslot.py x5` | `formal8-5`'s. **Newly visible: 11 of the 22 were hidden in `system-module-call` until §2.3** |
| **20** | 1 | one parameter, two kinds of value across call sites | `module_loader.py x19`, (this file) x1 | **unowned**; next wall measured at §4.2 |
| **12** | 10 | a module's ATTRIBUTE read as a value, across a dylib boundary | (this file) x10, `determinism_trace.py x2` | `FORMAL_module_state_no_storage`; project. §4.3 |
| **10** | 1 | a bracketed specialization of a callee this unit does not compile | `tile.mojo x4`, `random.mojo x3`, `format_int.mojo x2`, (this file) x1 | `formal13-6`'s; 4 of 4 use `tile`, so that half is work |
| **3** | 0 | module exports no public functions | `_select.mojo x1`, `_unicode_lookups.mojo x1`, `stat.mojo x1` | §4.4 |
| **3** | 3 | MLIR dialect construct (`__mlir_attr` / `__mlir_type` / `__mlir_op`) | (this file) x3 | `FORMAL_mlir_dialect_refusal_…`; two are `FORMAL_known_limits.md` §2.1 |
| **3** | 1 | frame address passed where a value is wanted | `type_system.py x2`, (this file) x1 | §4.5 |
| 2 each | | value with no representation on this path; method call on a value receiver; a linked module exports no such name | | §4.6 |
| 1 each | | 9 further single-file causes | | §4.7 |

**The `-7` map's 165-file top row was "module exports no public functions". It is
now 3 files, and the 162 that left it did not get fixed — they were re-filed under
their real terminal.** `binary_heap.mojo`'s `len(self._data)` refusal is gone (the
three `formal12-binary-heap` fixes), so the 163 rows that named it moved onto
`BinaryHeap.pop()`, which is the next construct in that file. **That is the tool
working: a cause row that shrinks because the refusal it named is gone, onto a
cause that is bigger and more specific.** Nothing regressed and no file built.

### 3.1 The `uses:` column is what sizes each row

| refusing module | blocks | files that name anything it declares | reading |
|---|---|---|---|
| `binary_heap.mojo` | 163 | **1** (`BinaryHeap`) | 162 are closure — they import `std.collections`, which re-exports it |
| `builtin_slice.mojo` | 43 | **3** (`slice`) | 40 are closure |
| `module_loader.py` | 19 | **0** | closure; the refusal is about the module's own body |
| `memslot.py` | 5 | **0** | closure |
| `tile.mojo` | 4 | **4** (`tile`) | **work** — every blocked file uses it |
| `determinism_trace.py` | 2 | **0** | closure |
| `type_system.py` | 2 | **0** | closure; the module declares no name the export rule could exclude |
| `random.mojo` / `format_int.mojo` / `stat.mojo` | 3 / 2 / 1 | **not measured** | the chain names a module by basename and that basename is ambiguous in this tree (`arm64.py` is both `formal/` and `jit/`; `random.mojo` and `stat.mojo` are both a stdlib package and a hostmod). The tool says so rather than picking one — correct, and a real limit on these rows |

**So of the 165 files the top row blocks, 162 name nothing `binary_heap.mojo`
declares.** One file has to lower first. That is the same conclusion `…_b6.md` §3
reached at 88 files and `…_b7.md` §3.1 at 165, now with a denominator 1.02x bigger
and the same answer.

### 3.2 The 60 in-file refusals, by shape, and the 22 that are one construct

The sweep's own `codegen by family` line: other refusal 47, MLIR construct 3, method
call on a value 3, one-field mutator 2, comptime does not fold 1, frame address where
a value is wanted 1, two-kinds-of-value 1, string method needing a length 1,
unimplemented intrinsic 1. The causes tool splits the 47 "other refusal" and finds
**22 of them are one construct**:

```
mlir.py, module_spec_gen.py, mojo/backend_gimple/spec_gen.py,
test_arm64_emission.py, test_cli_usage_text.py, test_dataclasses_formal.py,
test_formal_comptime_string.py, test_formal_debug_assert.py,
test_formal_frame_len.py, test_formal_list_splat.py,
test_formal_method_param_field.py, test_formal_receiver_position.py,
test_formal_receiver_spelling.py, test_formal_returned_frame.py,
test_formal_specialized_method_call.py, test_formal_value_model.py,
test_formal_x86_64_parity.py, test_native_dumpfull.py,
tools/audit_selfhost_struct_fields.py, tools/bootstrap_verify.py,
tools/memslot.py, tools/tu_grind.py
```

all with `except subprocess.TimeoutExpired as e:` or `except … :` around a body —
`formal8-5`'s `FORMAL_except_arm_is_never_emitted`. **Twenty-two repository files
and one tool, for one missing unwinder**, and the sweep's family line did not have a
name for it until this branch's classifier fix put it where the causes tool could
rank it. That is the argument for the fix in `31f20dba` in one number.

The other 38 in-file rows are 25 distinct shapes; the ones with a doc or a named
owner are `std/format/repr.mojo` and `std/utils/_serialize.mojo` (a method call on a
value receiver: `write_repr_to` is a `Writable` trait method with no body anywhere,
and `unsafe_load` needs a pointee width), `std/collections/binary_heap.mojo` and
`std/builtin/float_literal.mojo` (the one-field mutator, §4.1),
`formal/x86_64_decode.py` (`field(default_factory=F)` — no per-instance storage, and
`FORMAL_sweep_singles_second_half.md` §1 has measured that both repairs are large),
`type_system.py` (§4.5),
`regex_compile.py` (a slot holding a frame address rebound — measured to build, run
and die with SIGSEGV 139 before the refusal), `map.mojo` (`func` is a call through a
VALUE, and a formal value has no representation for a function), and
`module_spec_gen.py` /
`mojo/backend_gimple/spec_gen.py`, whose `__init__`-reads-`self` refusal is **gone**
(the inliner now threads the fresh block's address as the receiver; both files are
on the handler-arm row instead). **`unescape_c.py` is not on this list and its old
row is not closed**: it reaches `sys.stdin` first (a §3 row), and the `len()` of a
value classified as `int` is still standing behind that, which
`bugs/FORMAL_sweep_singles_second_half.md` §4 has measured with a four-line
reproducer on both architectures.

---

## 4. Next step per cause, and the three ceilings that are measured

Ordered by files blocked. **Every row above 10 files is either claimed, or measured
here to be closure or to have a project behind it — which is the finding, not an
omission.**

### 4.1 The 165-file row has TWO walls, and codegen is the first one

Terminal, on both architectures, byte-identical:

```
BinaryHeap.pop() both changes its receiver and returns a value, and a formal
value is one 64-bit word: on this path the word a one-field struct's mutating
method hands back IS the receiver, so there is no second word to return anything
else in …
```

This is a **PREP-time** refusal (`mutating_receiver_return_refusal`), so it preempts
every emitter refusal in the file. `bugs/FORMAL_binary_heap_mojo_after_the_len_value.md`
is the unowned doc and it is right about the shape: the row's real blocker is one
file that has to lower first, and **`pop` is an ABI decision, not an emitter
exercise** — a one-field mutator's single return word is already the receiver, so
the repair is either a second return register on both backends (which is also a Lean
model change) or the method split. The write set overlaps `formal13-5`'s
(`FORMAL_one_field_receiver_rebound_propagates` names `receiver_writeback_name` in
its own Area), so **it is not a light worker's row.**

And behind it is the wall that doc measured: past every codegen refusal in that
file, the module-dylib build fails at the **export gate**, because
`std/collections/binary_heap.mojo` declares only the generic struct template
`BinaryHeap` and `doc/ABI.md` is explicit that a generic is not a single boundary
symbol. So **no amount of codegen work on `binary_heap.mojo` moves any of the 165**,
and the second wall is the monomorphizer project
(`FORMAL_known_limits.md` §1.2 costs it at weeks). **Do not start it for this row.**

### 4.2 The 20-file row's next wall is `os.environ`, measured

**Unowned**, and the top unowned codegen row in the corpus. `module_loader.py`'s
module-level `_module_loader = ModuleLoader()` is a **three-field struct in a
`__DATA` slot**, and the two call sites of `ModuleLoader_load_module` disagree:

```
ModuleLoader_load_module() takes a ModuleLoader receiver at argument 0 — 'self' —
at ModuleLoader_load_module(self, module_name) here, and something that is not a
frame address at ModuleLoader_load_module(_module_loader, module_name).
```

**The root cause is a lifetime fact and it is worth stating precisely, because the
obvious fix is a wrong answer.** The slot holds the **address of a frame the module
body has already returned from** — with the 2026-10-03 load-time initializer the
body now runs at load, constructs the three `dict` fields in its own frame, and
stores that frame's address. `self` (line 1011) is live; `_module_loader` (line
1063) is not. **Teaching the holder fixpoint that a `__DATA` slot of framed-struct
type is a frame address would turn a refusal into a SIGSEGV**, which is why it has
not been done and why the disagreement check is right to fire.

**Measured, both architectures, what is behind it.** With `_check_one_callee`'s
disagreement refusal lifted and nothing else changed (`.tmp/probe_after_two_kinds.py`,
which reports the refusal it lifted so the number is not a guess):

```
[lifted disagreement #1] ModuleLoader_load_module(self, module_name)   (in get_symbol_type)
[lifted disagreement #2] ModuleLoader_load_module_from_path(_module_loader, path)
build: _find_stdlib_path: os.environ reads 'environ' out of the imported module `os` …
```

**So fixing the 20-file row moves 0 of the 20**: the next wall is §3's row 5, whose
own doc (`FORMAL_module_state_no_storage` §(4)) makes it an **exported slot** or a
**command line** — a project. The same lesson `FORMAL_binary_heap_mojo_after_the_len_value.md`
records, and the reason this row is a doc and not a patch.

What would actually make it work, in order: (a) a **static frame in `__DATA`** for a
module-level global whose value is a construction of a multi-field struct — a new
`GlobalSlot` `init` kind plus the field layout in `build_data_image` (which is shared
by both backends, and whose `nested_element` machinery is the precedent); (b) nothing
in either emitter moves, because the read is already a load from the slot. For
`ModuleLoader` specifically every field's initializer is an empty dict, so (a) is
expressible; for a general struct it needs the "every field is itself a static
initializer" rule, which is `static_initializer_refusal_reason`'s existing
`computed_element` boundary moved one level out.

### 4.3 The 12-file row is `sys.argv`/`os.environ`, and it is a project

`FORMAL_module_state_no_storage` (unowned) is the right document and its own Status
is current: the three remainders are an **exported slot**, a **command line**, and the
value-model question, and the module's docstring
(`formal/hostmods/sys.mojo`) says the same thing about `argv` specifically — the
entry stub loads the test input into X0 and calls the entry function, so the process's
command line is gone before the first statement runs. **Nothing here is a patch**, and
the sweep's refusal message points at the doc rather than at a missing container,
which is the property that makes it worth not "fixing".

### 4.4 The 3-file "module exports no public functions" row is three different things

| module | why | next step |
|---|---|---|
| `std/utils/_select.mojo` | every declaration is private (`_select_register_value`) | **work, and 1 of 1 dependent uses it.** A public wrapper (`def select_register_value(...)` that calls the private one) is the same program with a boundary, and it is the row's whole remaining value |
| `std/collections/string/_unicode_lookups.mojo` | declares no function and no type at all — only module-level constants, which are inlined at their use site | a lookup table that crosses a boundary needs a function to index it; that is a stdlib edit, not makeable from a repository worktree |
| `std/stat/stat.mojo` | every public function is a GENERIC template (`S_ISBLK`, `S_ISREG`, …) | the monomorphizer (§4.1's second wall) |

### 4.5 `isinstance()` on a multi-field struct — 3 files, one file's own source

```
a Type frame address is passed to isinstance(), which is lowered as an operation on
a VALUE: it wants the object itself, and on this path a multi-field struct has no
value form …
```

**The refusal is right about the program** (`type_system.py` really does pass a frame
address where a value belongs) and its repair is a value-model decision: either
`isinstance` learns a frame-receiver form, or a multi-field struct grows a value form.
Both are larger than three files, and 0 of the 3 name anything `type_system.py`
declares — they are closure.

### 4.6 The three 2-file rows

* **a value with no representation** (`map.mojo` ×1 + `algorithm/backend/cpu/__init__.mojo` ×1): both newly in this run, both `-7`'s `unresolved-extern`. `map.mojo`'s is a FUNCTION value — `` `func` is a call through a VALUE rather than through a function of this unit `` — and a formal value is one 64-bit word with a home in a register, a spill slot, a receiver's frame or a folded constant. **A first-class function is the value model's next shape, not a patch.**
* **a method call on a value receiver** (`std/format/repr.mojo`'s `value.write_repr_to()`, `std/utils/_serialize.mojo`'s `p.unsafe_load()`): a `Writable` trait method with no body to lower, and a load whose width is its pointee's. Two different value-model questions, both diagnosed, neither a patch.
* **a linked module exports no such name** (`t1.mojo` and `tools/detrace_diff.py`, both `sys.exit(3)`): `formal/hostmods/sys.mojo` has no `exit`, and its own docstring says why — `doc/ABI.md`'s export rule declines to advertise a C library symbol and `exit` is one. `FORMAL_module_state_no_storage` §(3) records that the rule is half the cause and the missing function is the other half. **Deliberately not taken here**: it would reverse a decision `sys.mojo`'s docstring and `test_formal_sys.py` both pin, for two files.

### 4.7 The nine single-file causes

`std/builtin/len.mojo`'s `...` body; `std/builtin/none.mojo`'s method on a multi-field
struct where a descriptor is meant; `std/math/polynomial.mojo`'s `comptime` that does
not fold; `std/simd.mojo`'s module-level `CompilationTarget` not exported as a word
(behind `time.mojo`); `mojo/backend_gimple/device_glue.py`'s `LaunchError` construction
arity; `mojo/middle/metal_ops.py`'s `rstrip` (a `String` method returning a SHORTER
string, `formal13-6`'s `FORMAL_string_value_model`); `regex_compile.py`'s frame slot
rebound (measured: builds, runs, SIGSEGV 139 before the refusal — §3.2);
`test_llm/dumb_gemm.mojo`'s repetition count; and
`tools/dataclass_reflection_sites.py`'s module-global container with storage but no
initializer. Each is either a value-model question with a doc, a stdlib edit, or one
file's own source. **Eight of the nine are in the stdlib or in another worker's
lane; none is a shared-backend patch.**

---

## 5. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-arm-8 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-8.txt  2>&1
python3 tools/memslot.py --gb 8 --label sweep-x86-8 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-8.txt 2>&1 &

python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-8.txt          # §3
python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-x86-8.txt
python3 .tmp/cmp_logs.py bugs/sweeps/sweep-arm-7.txt bugs/sweeps/sweep-arm-8.txt   # §2.4
```

**20 minutes for both arms together** (§1.1). The CAS is content-addressed and
machine-wide, so a re-run with nothing changed reads a file per file; **editing
`formal/`, the parser, `mojo/middle/`, or `tools/formal_sweep.py` invalidates all of
it** — which is why this run rebuilt 673 of 679.

Both arms exit 1 (real findings). `memcap` never breached: peak **0.6 GB** across 11
processes against the 8 GB reservation, on either arm.
