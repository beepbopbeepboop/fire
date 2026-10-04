# FORMAL_sweep_work_map_2026-10-03_b9: a fresh, complete sweep of this repository and the stdlib, both architectures

**Claim** `sweep17:sweep-b9` on `work/formal17-sweep-b9`. This tree is `master` at
`55951ba3` plus this branch's one commit (§5). Both arms ran to completion over the whole
697-file scope, and the 14 files the first pass could not answer inside its timeout were
re-answered on the same tree (§1.3), so **every number below is over the whole scope and
every file has a verdict.**

Four things a reader should take away, in the order they matter:

* **Coverage rose, and the finding count barely moved.** Passes went **131 → 136** and the
  coverage rate **29.6 % → 30.2 %** (§2.1). Four of the five new passes are files that
  arrived with the 18 new files in scope and passed on arrival; the fifth is a stdlib
  module whose own construct got lowered (`std/sys/debug.mojo`, §2.3). **The codegen
  findings went 308 → 311 on a scope 18 files larger** — that is +3, against **+23** for
  `-7` → `-8`, and it is the first round in this series in which the rate rose and the
  finding count stayed within a few files of the round before.
* **The two architectures are the same sweep, exactly.** All **561** classified paths have
  the same class on x86-64, there is **no x86-64-only row**, and the 14 re-answered files
  classify identically path-for-path. **The x86-64 backend is not where the remaining
  coverage is**, for the third round running.
* **The refusal `…_b8.md` §4.2 measured as the wall behind its 20-file row is GONE.**
  `One parameter, two kinds of value across call sites` fires on **zero** files in 697,
  and the module-attribute row fell from 12 files to 5. That is the load-time-initializer
  and module-slot work landing, and it means the row that took its place is a **different
  construct** — which is the finding, and it is the one this branch fixed.
* **The largest unowned codegen row is 163 files and its next wall is another row's
  project.** The 163-file row is one stdlib module refusing at the export gate, 162 of the
  163 files name nothing it declares, and lifting its refusal moves every one of them onto
  `tile.mojo`'s bracketed-specialization row — **measured, on 10 files, not projected**
  (§4.1), and that row is claimed. **Neither is a patch, and that is the finding.** The row
  this branch DID close is the **third-largest in the corpus, 30 files, one construct**
  (`with open(…) as f:`, §5) — unowned, and it was sitting in the causes table's
  `other refusal` bucket, which is the bucket that means *nobody has looked*.

---

## 1. The run

### 1.1 The commands, and how long they took

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-arm-9 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-9.txt  2>&1 &
python3 tools/memslot.py --gb 8 --label sweep-x86-9 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-9.txt 2>&1 &
```

Both arms at once, as in every earlier map: `formal_sweep.py` keeps a separate
`cas/formal-imports/<arch>/` **and** a separate per-architecture `flock`, so the two arms
share nothing. **75 minutes of wall for both arms together** (launched 14:59:31, both
`DONE` at 16:14), at `-j 4` each — eight concurrent builds on an eighteen-core box that
started the run at **load 90** with nineteen users and fell to load 4 by the last third.

**That load is the whole story of this round's wall time, and it is worth stating because
`-t` is a wall-clock bound per file, not a CPU budget.** The first 25 minutes ran at load
60-97 and the sweep managed 213 files; the last 25 minutes ran at load 4-32 and it managed
557. Same `-j`, same `-t`, same tree. `…_b8.md` §1.1 says "`-t` is a CPU budget divided by
the load, so it has to be sized against the machine", and this round is the measurement
behind that sentence: **the same `-t 120` answered 96 % of the scope at load 4 and 82 % of
it at load 90.**

Both arms **exit 1**, which is right: the run has real findings. `memcap` never breached —
peak **0.7 GB** across 9 processes against the 8 GB reservation, on either arm.

The interpreter is not optional (`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend_needs_3_10.md`):
`export PATH=/opt/homebrew/bin:$PATH` first, or the tool refuses to start with a diagnosis
rather than a wait. It got the lock on the first attempt on both architectures; the retry
wrapper (`.tmp/run_sweep9.sh`, scratch) exists because another worker may hold either one,
and `--allow-concurrent` is still the wrong answer for two sweeps of the SAME architecture.

### 1.2 Scope: 697 files

This worktree's own **445** `*.py`/`*.mojo` plus the **252** under
`../new-modular/Mojo/stdlib/std`. The repository has grown from 427 (`-8`'s count) to 445
across the `formal16` merges, and that is the whole of the scope delta: **14 of the 18 new
files are non-pass and 4 pass on arrival.**

### 1.3 Fourteen files got no verdict, and the tool named the fix

`-8` was the first round in this series with an empty `tool` class, and this one has
**14 files in it** — all of them the same thing:

```
TOOL: ../new-modular/Mojo/stdlib/std/collections/list.mojo  (timeout (> 120s, stdlib population))
… 13 more, every one of them `timeout (> 120s, stdlib population)`
```

They are the largest stdlib modules (`std/math/math.mojo`, `std/simd.mojo`,
`std/collections/string/string.mojo`, `std/python/bindings.mojo`, …), they all timed out
during the load-90 first quarter of the run, and **all 14 had a codegen verdict at `-8`**,
so this is not a regression in the backend — it is 14 files this run says *nothing* about,
and "nothing" is not "cleared". The sweep says so itself and prints the command:

```
re-answer the 14 stdlib file(s) with a larger -t: python3 tools/formal_sweep.py --arch arm64 -t 240
```

which is what §1.1's `-t 120` was too small for. So they were re-answered, on the same tree,
at `-t 420`, with `paths` as the scope (which **wins** over the roots, so the re-sweep covers
exactly those 14 and nothing else):

```sh
python3 tools/memslot.py --gb 8 --label sweep-arm-9-retry -- \
  python3 tools/formal_sweep.py -j 4 -t 420 $(grep '^TOOL' bugs/sweeps/sweep-arm-9.txt | awk '{print $2}') \
  > bugs/sweeps/sweep-arm-9-retry.txt 2>&1
```

and the x86-64 twin. **All 14 answer `CODEGEN/DEPENDENCY`, identically on both
architectures, and the `tool` class is empty once they are folded in.** §2.1 gives both
sets of numbers — the run's own summary, which is what the runner certifies sums to 697,
and the same table with the 14 folded in, which is the comparison `-8` deserves. Both logs
are committed; the re-sweep's causes are in §2.3.

**A re-sweep is not a re-run.** The CAS is content-addressed, so a re-sweep with nothing
changed reads a file per file — this one rebuilt all 14 (`cas: 0 hit / 14 miss`), because
the 14 paths were answered under a *different* key: a timeout is never cached (§1.4's
neighbour, `formal_sweep.py`'s own comment), so the re-sweep's key is the first one those
paths have ever had.

---

## 2. Class counts

### 2.1 Both readings of this run, and the comparison with `-8`

Left pair: the run's own summary, which sums to 697 and which the runner checks. Right pair:
the same table with the 14 timeouts of §1.3 answered. **The middle column is the one to
compare with `-8`,** because `-8` had no `tool` row and comparing against a run that says
nothing about 14 files flatters the rate.

| class | `-8` arm64 | `-9` arm64 as run | **`-9` arm64 answered** | Δ vs `-8` | `-8` x86-64 | **`-9` x86-64 answered** | Δ |
|---|---|---|---|---|---|---|---|
| **pass** | 131 | 136 | **136** | **+5** | 131 | **136** | **+5** |
| built-with-admitted-contracts | 4 | 4 | **4** | 0 | 4 | **4** | 0 |
| **codegen** (a refusal IN this file) | 60 | 63 | **63** | **+3** | 60 | **63** | **+3** |
| **codegen/dependency** (refused in a module it imports) | 248 | 234 | **248** | **0** | 248 | **248** | **0** |
| not-answerable/host-import | 225 | 234 | **234** | **+9** | 225 | **234** | **+9** |
| not-answerable/unresolved-import | 6 | 7 | **7** | +1 | 6 | **7** | +1 |
| not-answerable/unresolved-extern | 0 | 0 | **0** | 0 | 0 | **0** | 0 |
| not-answerable/system-module-call | 0 (rule live) | 0 | **0** | 0 | 0 | **0** | 0 |
| not-answerable/target-limit | 5 | 5 | **5** | 0 | 5 | **5** | 0 |
| **backend-crash** | 0 | 0 | **0** | 0 | 0 | **0** | 0 |
| **tool — no verdict at all** | **0** | **14** | **0** | **0** | **0** | **0** | **0** |
| **files swept** | 679 | 697 | **697** | +18 | 679 | **697** | +18 |
| **codegen coverage** | 131/443 = 29.6 % | 136/437 = 31.1 % | **136/451 = 30.2 %** | **+0.6 pp** | 131/443 = 29.6 % | **136/451 = 30.2 %** | **+0.6 pp** |

**311 of the 697 files carry a codegen verdict** (`63 + 248`), against 308 in `-8`, on a
scope 18 files bigger. **No `backend-crash` anywhere**, for the third round running: that
is the one class a sweep cannot leave behind, because a crash is never cached, so it costs
a build per arm per sweep until it is gone.

The classes that are neither "no verdict" nor coverage, with this run's counts:

| class | n | what it is |
|---|---|---|
| `not-answerable/host-import` | 234 | imports a CPython module with no Mojo source. **118 import a module a Mojo-side implementation could in principle provide** and 116 need a host process, an embedded interpreter or a kernel object. By module: `importlib x54`, `glob x50`, `zlib x27`, `collections x22`, `copy x11`, `unittest x11`, `itertools x10`, `types x10`, `signal x7`. `datetime`, `functools`, `html`, `posixpath`, `shlex` and `textwrap` have left the in-reach list since `-8`. Not in any rate |
| `not-answerable/unresolved-import` | 7 | `formal_fuzz`, `formal_sweep`, `formal_sweep_causes`, `lang_spec`, `mojo_compiler`, `pytest`, `tools` — **three are this sweep's own tools**, which import each other; `lang_spec` is imported by `fe_reader.py` and in no module set; `mojo_compiler` is the pre-rename name of `fire_compiler` and exists only as an import |
| `not-answerable/target-limit` | 5 | `mojo_sqlite3_open` in the five `test_sqlite3*.mojo` files |
| `built-with-admitted-contracts` | 4 | `formal/hostmods/{concurrent/futures,ctypes,subprocess,threading}.mojo` build but rest on declared assumptions about a host this image does not have; counted in the denominator, never as passes |

### 2.2 arm64 vs x86-64: **zero** architecture-dependent verdicts

| | main run | the 14 re-answered |
|---|---|---|
| paths classified on both | **561** | **14** |
| **of those, class CHANGED** | **0** | **0** |
| x86-64-only rows | **0** | **0** |
| arm64-only rows | **0** | **0** |

Computed path-for-path from the two logs' printed lines (`.tmp/analyze9.py`, two regexes,
a `Counter` and a set difference). `-8` and `-7` each had one x86-64-only row and this one
has none, for the third round running: **`formal/hostmods/os/_syscalls.mojo`'s `$INODE64`**
(the x86-64 libSystem ABI spelling, unsuffixed on arm64) was fixed at `-8` and stays fixed.
Worth knowing before anyone spends time on "the x86-64 backend is behind": **in 697 files the
two architectures produce the same verdict for every single one.**

### 2.3 The per-file delta `-8` → `-9`: 20 of 547 common paths changed class

| | arm64 | x86-64 |
|---|---|---|
| paths classified by `-8` | 548 | 548 |
| paths classified by `-9` | 561 | 561 |
| common paths | **547** | **547** |
| **class CHANGED** | **20** | **20** |
| new non-pass rows (the scope grew by 18 files; 14 of the 18 are non-pass) | 14 | 14 |
| paths that left the non-pass set (**now passing**) | **1** | **1** |

| move | n | reading |
|---|---|---|
| `not-answerable/host-import` → `codegen` | **5** | **host-module work landing**: four of the five are the handler-arm row (§3), the fifth is `test_comptime_parity.py`, whose only remaining obstacle is the `with` this branch fixed (§5) |
| `codegen/dependency` → `tool` | **14** | **the timeouts of §1.3**, all re-answered in §1.3 and all landing in the codegen classes again |
| `codegen` → `not-answerable/host-import` | 1 | `test_formal_receiver_position.py`, which grew an `import inspect` since `-8`. A file's first obstacle moves when the file changes; this is not the backend regressing |

**The one path that left the non-pass set** is `../new-modular/Mojo/stdlib/std/sys/debug.mojo`:
it was refused in-file at `-8` and now **builds and passes on both architectures**. That is
the `__mlir_op`-as-a-statement case (`bugs/FORMAL_known_limits.md` §2.2's one exception,
"a TRAP used as a statement lowers"), so the round's only in-file stdlib gain is a construct
getting lowered rather than a file getting lucky.

**Read the two absolute numbers, not the deltas.** `-8`'s own warning (`…_b6.md` §2.1)
stands: 5 files moved INTO the codegen classes and 1 moved out, which is hostmod work making
files report the truth about the next thing that stops them. That is progress, and the rate's
job is to fall while it happens; this round the rate rose because the hostmod work landed
*and* nothing new was refused in this repository's own files.

### 2.4 The CAS was cold, and that is the cost of a moving tree

`cas: 3 hit / 694 miss / 0 not cached` on arm64, and the same shape on x86-64. **691 of 697
files were rebuilt from scratch**, because `tools/formal_sweep.py`'s own bytes are in every
cache key (`_criteria_id`) and `cas.formal_fingerprint()` covers `formal/**`, the parser and
the middle tier — and ~100 formal branches landed since `-8`. A re-run with nothing changed
reads a file per file; **editing anything under `formal/`, the parser, `mojo/middle/`, or
`tools/formal_sweep.py` invalidates the whole sweep.** That is also why §5's re-sweep of 30
files is a measurement in its own right and not a cache read.

---

## 3. Ranked causes

`python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-9.txt` — and the x86-64
arm prints the same table with the same numbers, which follows from §2.2.

**FILES BLOCKED IS AN UPPER BOUND**: a file's terminal cause is the first refusal its build
walk reaches, so fixing one moves the file to the next with the count unchanged. **Two of
the rows below have that ceiling measured, not projected, and it is stated in the row.**

| files | in-file | cause | refused in | owner / next step (§4) |
|---|---|---|---|---|
| **157** (+9 of the 14 re-answered = **163**) | 0 | a module that exports nothing cannot be a dylib | `binary_heap.mojo x154` (+9), `_select.mojo x1`, `_unicode_lookups.mojo x1`, `stat.mojo x1` | **unowned**; next wall measured at §4.1 |
| **41** (+2 = **43**) | 0 | Optional unwrap: `None` and a value are one word, with no tag | `builtin_slice.mojo x41` (+2) | `FORMAL_stdlib_optional_needs_a_representation`, **claimed** (`formal16-7`) |
| **30** | 9 | a `with` over a value this build cannot type | `module_loader.py x19`, (this file) x9, `determinism_trace.py x2` | **unowned, and FIXED on this branch** (§5) |
| **30** | 25 | a handler arm with a body (no unwinder to emit it into) | (this file) x25, `memslot.py x5` | `FORMAL_except_arm_is_never_emitted`, **claimed** (`formal8-5`) |
| **10** | 1 | a bracketed specialization of a callee this unit does not compile | `tile.mojo x4`, `random.mojo x3`, `format_int.mojo x2` (+2), (this file) x1 | `FORMAL_stdlib_tile_row…`, **claimed** (`formal16-7`) |
| **8** | 8 | other refusal | (this file) x8 | §4.6 |
| **5** | 5 | a module's ATTRIBUTE read as a value, across a dylib boundary | (this file) x5 | `FORMAL_module_state_no_storage`, unowned; project. §4.4 |
| **3** | 1 | frame address passed where a value is wanted | `type_system.py x2`, (this file) x1 | §4.5 |
| 3 each | | a linked module exports no such name; MLIR dialect construct | | §4.7 |
| 2 each | | value with no representation; a module-level name of another module; a `...` body | | §4.6 |
| 1 each | | 8 further single-file causes | | §4.7 |

**The `-8` map's 20-file "one parameter, two kinds of value across call sites" row is
GONE — zero files in 697.** That refusal was `module_loader.py`'s module-level
`_module_loader = ModuleLoader()` disagreeing with itself across call sites, and the
load-time-initializer and module-slot lifetime work absorbed since `-8` answered it. It was
the row `-8` §4.2 measured as having `os.environ` behind it, and both halves of that
measurement are now history: **`os.environ` as a module attribute is down to 5 files from
12**, and the wall behind the row is a `with` (§5) rather than module state.

**The `-8` map's 165-file "a one-field struct's mutator has no convention to write its
answer back" row is also gone, and not because it was fixed.** `binary_heap.mojo`'s
`BinaryHeap.pop()` now lowers; what the 163 files hit instead is the **export gate** on the
same file, which `-8` §4.1 named as "the second wall behind this row" and `formal/monomorph.py`
was built to answer (§4.1 measures where that answer stops). **That is the tool working**: a
cause row that empties because the refusal it named is gone, onto a cause that is bigger and
about a different thing.

### 3.1 The `uses:` column is what sizes each row

| refusing module | blocks | files that name anything it declares | reading |
|---|---|---|---|
| `binary_heap.mojo` | 154 (+9) | **1** (`BinaryHeap`) | 153 are closure — they import `std.collections`, which re-exports it |
| `builtin_slice.mojo` | 41 (+2) | **1** (`slice`) | 40 are closure |
| `module_loader.py` | 19 | **0** | closure; the refusal is about the module's own body |
| `determinism_trace.py` | 2 | **0** | closure |
| `memslot.py` | 5 | **0** | closure |
| `tile.mojo` | 4 | **4** (`tile`) | **work** — every blocked file uses it |
| `type_system.py` | 2 | **0** | closure; the module declares no name the export rule could exclude |
| `random.mojo` / `format_int.mojo` / `stat.mojo` / `time.mojo` | 3 / 4 / 1 / 1 | **not measured** | the chain names a module by basename and that basename is ambiguous in this tree (`random.mojo` and `stat.mojo` are both a stdlib package and a hostmod; `time.mojo` and `ab_filelist.py` are both a stdlib package and a repo tool). The tool says so rather than picking one — correct, and a real limit on these rows |

**So of the 163 files the top row blocks, 162 name nothing `binary_heap.mojo` declares.**
One file has to lower first, and §4.1 measures what happens when it does.

### 3.2 The 63 in-file refusals, by shape

The sweep's own `codegen by family` line: other refusal 53, method call on a value 3, MLIR
construct 2, cannot be lowered 1, comptime does not fold 1, frame address where a value is
wanted 1, string method needing a length 1, unimplemented intrinsic 1. The causes tool
splits the 53 "other refusal" and finds **30 of them are one construct — the `with` of §5,
which is 21 files through `module_loader.py`'s single line and 9 in the file's own source.**
The remaining 8 are `float_literal.mojo`'s dispatched `self.__int_literal__().__int__(…)`,
`none.mojo`'s method on a multi-field struct where a descriptor is meant, `len.mojo`'s `...`
body, `type_dict.mojo`'s `comptime` class attribute read off a type PARAMETER,
`polynomial.mojo`'s `comptime` that does not fold, `time.mojo`'s module-level
`CompilationTarget`, `map.mojo`'s call through a function VALUE, and `module_attr.py`'s own.

**Every one of the nine in-file `with` sites is `with open(…) as …`** — modes `'r'`, `'w'`,
`'a'`, `'rb'`, and none at all — in `build_mojo_cli.py`, `determinism_trace.py`,
`formal/elf.py`, `module_loader.py`, `test_comptime_parity.py`, `test_silent_noop_iter.py`,
`tools/ci_line.py`, `tools/dataclass_reflection_sites.py` and `tools/detrace_diff.py`.

---

## 4. Next step per cause, and the ceilings that are measured

Ordered by files blocked. **Every row above 10 files is either claimed, or measured here to
be closure or to have a project behind it — which is the finding, not an omission.**

### 4.1 The 163-file row is one stdlib file refusing at the export gate, and its ceiling is another row

Terminal, on both architectures, byte-identical:

```
binary_heap.mojo: formal dylib has no public functions: binary_heap.mojo exports
nothing under doc/ABI.md's rules: it declares only the generic struct template(s)
BinaryHeap, and the template itself is not a boundary symbol. Its INSTANTIATIONS are
— `formal/monomorph.py` compiles each one an importer asks for into this module's own
library as a concrete `BinaryHeap_Int`, under this module's qualifier — so this
message means nothing asked for one …
```

`…_b8.md` §4.1 called this the second wall behind its 165-file row, said the repair was the
monomorphizer project, and said **"do not start it for this row."** `formal/monomorph.py`
exists now, demand-driven, and it is why the 165 became 163 rather than 0: the module has
instantiations available and nobody asks for one, because **the only importer that binds
anything in it is `std/collections/__init__.mojo`'s re-export, and a template name is not a
symbol.**

**So the remaining wall is a decision, not a project, and it was measured rather than
argued.** Lifting the refusal — treating a module nobody binds a concrete name from as "no
library needed", which is what `formal/imports.py::build_module_dylib` would have to decide —
was probed on **10 of the 163 files** (`.tmp/probe_export_gate.py`, which returns `None` for a
module the export gate refuses and prints each skip, so the number is a count of refusals
lifted rather than an assertion that one was). Every one of the 10 moved off the row, and
**every one landed on the same other row**:

```
[probe] SKIPPED .binary_heap (binary_heap.mojo) for consumer std.collections
build: <file> imports '<X>', which cannot be built either: tile.mojo:
workgroup_function[…](…) calls a name this unit does not compile, so the brackets
cannot be bound …
```

8 of 10 on `tile.mojo`'s bracketed specialization, 2 on `builtin_slice.mojo`'s Optional
unwrap. **`tile.mojo`'s row is 4 files today because `binary_heap.mojo` masks it, and
`FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value` is claimed
(`formal16-7`).** So fixing this row moves 0 of the 163 and hands 8-in-10 of them to a
claimed row — which is the same lesson `FORMAL_binary_heap_mojo_after_the_len_value.md`
records, and the reason this row is a measurement in this map and not a patch.

**What would actually make it work, in order, and none of it is a light worker's row:**
(a) `build_module_dylib` decides per EDGE whether the importing module binds any **concrete**
name of the dependency, and skips the library when it does not — the demand-driven closure
that `monomorph.py` already is for instantiations; (b) the re-export of a **template** in
`std/collections/__init__.mojo` should not force a library at all, which is the same fact one
level up; (c) nothing in either emitter moves either way, because there is no code to emit.
Note that (a) reverses a deliberate, documented and *pinned* decision —
`test_formal_imports.py::test_a_module_with_no_boundary_symbol_is_refused` exists to fail if a
template-only module ever builds, and its docstring says why ("the only way to make it build is
to publish the template under its base name, and that is a run-time wrong answer rather than a
build error"). Whoever takes this row has to answer that test, not route around it.

#### §4.1 ANSWERED 2026-10-04, on `work/formal18-export-gate`: (a) and (b) are one rule, and it moves 3 files

`formal/imports.py::library_free_edges` decides it per edge and both decision sites act on it
(`build_module_dylib` for a dependency, `_resolve_imports` for the program's own imports), and
`doc/ABI.md` §Generics now carries the rule under "When a module dylib is built at all". The
test above was **answered, not routed around**: it is restated as two — one that a program
importing a template and calling nothing builds, runs, and produces **no library at all** for
the module, and one that a BARE call to one of those names is still refused, naming the call
and the spelling that would bind. The export-set pin is untouched and still says a template is
never published under its base name, so the property the old test existed to protect is intact;
what changed is that a module nobody binds a concrete name from is no longer refused for
having no boundary symbol.

**All 163 re-measured**, one `fire.py build --formal --no-prove` per file (`--no-prove`, so no
lean runs; the two architectures produce the same refusal, §2.2's standing measurement):

| verdict | files | terminal cause |
|---|---|---|
| **BUILT** | **3** | `std/_gpu/host/__init__.mojo`, `std/compile/__init__.mojo`, `std/os/path/__init__.mojo` |
| moved off the gate, still refused | 128 | **121 a bare call to a name the defining module cannot export**; 7 something else |
| still at the gate | 32 | `std/sys/_io.mojo` (17) and a `constants.mojo` (13) — "declares no function and no type at all, only module-level constants" — plus 2 misfiled by the probe's own regex, which are bare calls too |

**So the map's prediction holds and its destination row was one layer too far out.** The probe
above lifted the refusal for *every* module the gate refused and so also removed the refusal a
bare call gets; with the gate fixed and the bare call still refused, the first thing a build
meets is the bare call. It is 121 of the 128, and it is **one feature**: a call whose type
arguments are INFERABLE from its arguments, spelled `FormatStruct(writer, "Allocation")`
(68 files, `std/memory/alloc.mojo:450` against `std/format/_utils.mojo:287`'s
`struct FormatStruct[T: Writer, o: MutOrigin]`), `dealloc(allocation^)` (29, `alloc.mojo:99`
against its own `:904`), `is_negative(value)` (12), `PhiloxRandom(seed)` (6), `align_up(x)` (3),
three singles. `std/memory/alloc.mojo` carries the first two and is in nearly every stdlib
file's closure, which is why those two rows are large and why they do not overlap in the FILE
list — the walk stops at the first refusal.

The doc is **`FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`**, and
the part of it that matters beyond the count is that `imported_callee_refusal`'s next step —
"spell it as `widen[<a type>](…)`" — is **wrong about correct Mojo** for all 121.

The 32 that stay at the gate are the **constants-only** family this map's §4.1 called
permanent, and they are still permanent: `_io.mojo` and `constants.mojo` declare no function
and no type, so there is no boundary symbol for any edge, and the importer needs their VALUES
out of a `__DATA` a dylib would have had to publish
(`FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md` §3's wall 1½ — claimed, and not
this row's to answer).

### 4.2 The 43-file Optional row is a value-model decision, and it is claimed

`std/builtin/builtin_slice.mojo`'s `self.step.or_else()`, one line, 43 files. `None` and a
value are one 64-bit word here, so the unwrap cannot answer "which of the two is this" without
a niche, a discriminant or a tag word — **one representation change shared by both backends
and by the Lean model.** `bugs/FORMAL_stdlib_optional_needs_a_representation.md` is the doc and
`formal16-7` holds the claim. Nothing here.

### 4.3 The 30-file handler-arm row is a refusal that is CORRECT, and it is claimed

`formal` has no exception unwinder: a `raise` flushes the enclosing `finally` clauses and
exits, so no edge runs from a raise site into an arm and every statement in an arm's body
would be absent from the program that runs. It is in the taxonomy because "refused on purpose"
and "nobody has looked" are different answers, and its number is a census rather than a target.
`FORMAL_except_arm_is_never_emitted`, claimed by `formal8-5`. Nothing here.

**And it is the wall behind most of §5's row**, which is the connection worth stating: 4 of
the 5 files that moved `host-import → codegen` in §2.3 are this row, so the fix in §5 moved 30
files *onto* it rather than past it.

### 4.4 The 5-file module-attribute row is `sys.argv`/`sys.executable`, and it is a project — and §5.2 makes it 29

`FORMAL_module_state_no_storage` (unowned) is the right document and its own Status is current:
the remainders are an **exported slot**, a **command line**, and the value-model question, and
`formal/hostmods/sys.mojo`'s docstring says the same about `argv` specifically — the entry stub
loads the test input into X0 and calls the entry function, so the process's command line is gone
before the first statement runs. This row was **12 files at `-8` and is 5 now**: `os.environ`
(6 files) and `os.environ`-adjacent names have been answered since, which is why the row's names
are now `argv x4, stdin x1`. **Nothing here is a patch**, and the refusal points at the doc
rather than at a missing container, which is the property that makes it worth not "fixing".

**It is also the row §5's fix hands 24 files to**, so with that fix landed the row is **29
files** — the largest unowned codegen row in the corpus, and the queue's next decision.

### 4.5 `isinstance()` on a multi-field struct — 3 files

```
a Type frame address is passed to isinstance(), which is lowered as an operation on a
VALUE: it wants the object itself, and on this path a multi-field struct has no value form
```

The refusal is right about the program (`type_system.py` really does pass a frame address
where a value belongs) and its repair is a value-model decision: either `isinstance` learns a
frame-receiver form, or a multi-field struct grows a value form. Both are larger than three
files, and 0 of the 3 name anything `type_system.py` declares — they are closure.

### 4.6 The remaining 2-file and 3-file rows

* **a value with no representation** (`map.mojo` + one in-file): `map.mojo`'s is a FUNCTION
  value — `func` is a call through a VALUE rather than through a function of this unit — and a
  formal value is one 64-bit word with a home in a register, a spill slot, a receiver's frame
  or a folded constant. **A first-class function is the value model's next shape, not a patch.**
* **a linked module exports no such name** (`runtime/stdlib_wrapper.mojo`,
  `tools/wave1_move_shared.py`, `tools/wave2_extract_shared.py`, all `sys.exit(…)`):
  `formal/hostmods/sys.mojo` has no `exit`, and its own docstring says why — `doc/ABI.md`'s
  export rule declines to advertise a C library symbol and `exit` is one.
  `FORMAL_module_state_no_storage` §(3) records that the rule is half the cause and the missing
  function is the other half. **Deliberately not taken**: it would reverse a decision
  `sys.mojo`'s docstring and `test_formal_sys.py` both pin, for three files.
* **MLIR dialect construct** ×2 (`type_aliases.mojo`'s `Never`, one other): the row
  `FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops` owns; two are
  `FORMAL_known_limits.md` §2.1.
* **a `...` body**, **a module-level name of another module** (`time.mojo`'s
  `CompilationTarget`), **comptime does not fold** (`polynomial.mojo`): each is one file's own
  source, and two of the three are stdlib edits that cannot be made from a repository worktree.

### 4.7 The single-file causes

`std/builtin/float_literal.mojo`'s `self.__int_literal__().__int__(…)` (a method call lifted
by NAME from a non-name callee — dispatch here is by name, so the lift has nothing to lift);
`std/builtin/none.mojo`'s method on a multi-field struct where a descriptor is meant;
`std/builtin/len.mojo`'s `...` body; `std/math/polynomial.mojo`'s `comptime`; `std/simd.mojo`'s
module-level `CompilationTarget` (behind `time.mojo`); `std/collections/type_dict.mojo`'s
`comptime` class attribute read off a type PARAMETER; `std/collections/binary_heap.mojo`'s own
`self.clear()` (a method call on a value); `tools/dataclass_reflection_sites.py`'s module-global
container; and one more. Each is either a value-model question with a doc, a stdlib edit, or one
file's own source. **None is a shared-backend patch.**

---

## 5. What this branch changed, measured

One commit, `b0ad85b7`, on top of `master` at `55951ba3`. **It is landed AFTER the sweep
above was taken**, so the sweep's numbers are the numbers of the tree the fix landed on and
the fix's own sweep-visible effect is measured separately, on the 30 files it names.

### 5.1 The fix: `with open(…) as f:` is the context-manager protocol, and the protocol is two calls

The third-largest row in the corpus, **30 files, every one of them one line of the shape
`with open(…) as …`**, and unowned. It was refused by `formal/model.py`'s
`refuse_unlowerable_with`, which says a `with` is `__enter__` binding the name and `__exit__`
running on the way out, and that the only value this path can enter and exit is a **framed
struct that declares both dunders**. `open(...)` is not a struct construction, so the refusal
was right about the mechanism and wrong about the file — and `with open(` is in **192** of this
repository's own files, so it is the most common statement in the corpus.

**The root cause is that the type was treated as unanswerable when it is already answered.**
`formal/model.py::BUILTIN_FUNCTIONS` says `open` lowers to the C library's `open(2)`, so its
value on this path is a **file descriptor** — one word, already the receiver `f.write(…)` and
`f.close()` lower on (`BUILTIN_VALUE_METHODS`, guarded by `VALUE_METHOD_RECEIVERS`). A
descriptor's `__enter__` returns the descriptor and its `__exit__` closes it, which is
`close(2)` on the same word. So `RESOURCE_CONTEXT_MANAGERS` states the protocol for a value
whose representation is already decided, as **two names rather than a rule per builtin**, and
`formal/build.py::_one_with_item` emits the **same `try`/`finally` shape** the struct arm emits
— which is why the exit call still runs on an early `return` out of the body, the property the
struct rows have been pinning since the dropped-`finally` defect. **Neither emitter is
touched**: `open` and `close` each already have a lowering on both architectures, so the two
cannot disagree about this, and there is nothing arch-dependent in the change at all.

Two things came with it that are not decoration:

* **The alias refusal got its own sentence.** `with EXPR as (a, b)` has no problem with its
  CONTEXT, so reusing the expression's message sent the reader to the wrong half of their own
  line — and telling a reader that "this build cannot answer what type it is" about an
  `open(…)` whose type is now known is exactly the false-about-the-file message this
  repository deletes sentences out of. It opens with the same protocol sentence on purpose, so
  `tools/formal_sweep_causes.py` counts a file refused for the alias beside one refused for the
  context.
* **The causes table had no row for either message**, so all 30 sat in `other refusal` — the
  bucket that means *unclassified*. One row, one sample per wording in
  `test_refusal_taxonomy.py`; 56 causes where there were 55.

### 5.2 The fix's effect on the 30 files, measured by re-sweeping exactly those 30

`bugs/sweeps/` is the committed evidence for the run; the re-sweep is scratch and its numbers
are here:

```sh
python3 tools/memslot.py --gb 8 --label with30 -- \
  python3 tools/formal_sweep.py -j 4 -t 300 $(the 30 paths) > .tmp/with30-arm.txt 2>&1
```

**30 of 30 answered, `class-per-path IDENTICAL` on both architectures, `cas: 0 hit / 30 miss`
(nothing was cached, so this is a measurement and not a replay), and not one of them is still
on the `with` refusal.** Where they went:

| where the 30 went | n | the row it is |
|---|---|---|
| a module's ATTRIBUTE read as a value: `os.path` ×19 (all through `module_loader.py`'s one line), `sys.argv` ×2, `stat.S_IXUSR`, `os.environ`, `sys.executable` | **24** | §4.4 — `FORMAL_module_state_no_storage`, unowned, a project |
| `os.environ.get()` — a call through a **function-valued** module attribute, which is a *different* message and a different question (`os.environ` is a function on this path, so `.get()` on it is a call through a value) | 3 | §4.4's value-model half |
| `struct.pack()` — 9 positional arguments against 6 declared parameters | 1 | `formal/elf.py`'s own source |
| a module-global container that has storage and no initializer | 1 | `tools/dataclass_reflection_sites.py`'s own source |
| `sys.exit()` — a linked module exports no such name | 1 | §4.6, deliberately not taken |
| **still on the `with` refusal** | **0** | |
| **pass** | **0** | |

**So the honest summary of this fix is: it converts 0 files to passes, and that is the
measurement rather than a disappointment.** The `with` was never the wall behind those 30
files; it was a refusal *in front of* the wall, and a file cannot be built with a false
refusal in front of it. What the fix buys is that the sweep now reports the truth about where
those 30 files actually stop, and that `with open(…) as f:` — the most common statement in
this repository — compiles, runs and closes its descriptor on both architectures, which
nothing did before.

**And it hands the queue a sharper top row.** 24 of the 30 converge on ONE line of ONE
module, so with this fix landed the module-state row of §4.4 goes from 5 files to **29**, and
it becomes the largest unowned codegen row in the corpus. It was already a documented project
(`FORMAL_module_state_no_storage` §(2): an exported slot, or a command line); this is the
number for it.

### 5.3 The tests, and what they prove

Three new cases in `test_formal_run.py`'s `BOTH_ARCH_CASES` (built and RUN on **both**
backends, because the lowering is shared and the two `write(2)`/`close(2)` calls are each
emitted by their own backend):

* `with_open_alias_is_a_live_descriptor` — `f.write("hello")` returns **5**, which is
  `write(2)`'s own answer for five bytes and not a constant the test wrote. A lowering that
  bound the alias to anything else would refuse here rather than print a wrong number.
* `with_open_closes_the_descriptor_on_the_fall_through` — observed through the descriptor
  NUMBER rather than through a flag: `open(2)` returns the lowest free descriptor, so a closed
  one makes the next `open` reuse it and `g - f` is **0**. Number-independent (the case does
  not hard-code 3), and unsatisfiable by a lowering that only dropped the call — that prints 1.
* `with_open_closes_the_descriptor_on_an_early_return` — the same observation one edge
  deeper, with `return fd` from inside the block, so the pending return and the `finally`
  cannot be flushed at each other's expense.

And the six pre-existing `with_*` rows still pass, including
`with_on_a_word_is_the_context_manager_protocol_or_a_refusal` — **`with 7 as y` is still
refused**, which is the point: a `with` whose context is a name, a field read or an
unresolvable callee still has no type, and the refusal is unchanged.

---

## 6. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-arm-9 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-9.txt  2>&1 &
python3 tools/memslot.py --gb 8 --label sweep-x86-9 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-9.txt 2>&1 &

# §1.3: answer the files the first pass could not, at a -t the machine can hold
python3 tools/memslot.py --gb 8 --label sweep-arm-9-retry -- \
  python3 tools/formal_sweep.py -j 4 -t 420 $(grep '^TOOL' bugs/sweeps/sweep-arm-9.txt | awk '{print $2}') \
  > bugs/sweeps/sweep-arm-9-retry.txt 2>&1          # …and the --arch x86_64 twin

python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-9.txt          # §3
python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-x86-9.txt
python3 .tmp/analyze9.py bugs/sweeps/sweep-arm-9.txt bugs/sweeps/sweep-x86-9.txt \
                            bugs/sweeps/sweep-arm-8.txt bugs/sweeps/sweep-x86-8.txt   # §2.1-2.3
python3 test_refusal_taxonomy.py                                           # §5.1, the 56th cause
python3 test_formal_run.py with_open_alias_is_a_live_descriptor \
        with_open_closes_the_descriptor_on_the_fall_through \
        with_open_closes_the_descriptor_on_an_early_return                 # §5.3
```

`.tmp/run_sweep9.sh`, `.tmp/analyze9.py`, `.tmp/probe_export_gate.py` and `.tmp/probe47.sh`
are **scratch, not committed** (`.tmp/` is git-ignored, and `…_b7.md`/`…_b8.md` did the
same), so each is described rather than shipped. `analyze9.py` reads each log's summary block
for the class counts — the runner computes them and checks they sum to the file count, so they
are the authority — and each log's printed lines for the path-for-path comparisons.
`probe_export_gate.py` wraps `formal.imports.build_module_dylib`, returns `None` for a module
whose library the export gate refuses, and prints each skip with the module and the consumer
that asked for it, so §4.1's number is a count of refusals lifted rather than an assertion
that one was.

**75 minutes for both arms together at `-j 4 -t 120` (§1.1), and the first quarter of that
was at load 90.** The CAS is content-addressed and machine-wide, so a re-run with nothing
changed reads a file per file; **editing `formal/`, the parser, `mojo/middle/`, or
`tools/formal_sweep.py` invalidates all of it** — which is why this run rebuilt 694 of 697,
and why §5's re-sweep of 30 files is a measurement rather than a cache read.

Both arms exit 1 (real findings). `memcap` never breached: peak **0.7 GB** across 9 processes
against the 8 GB reservation, on either arm.