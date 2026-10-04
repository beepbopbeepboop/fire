# FORMAL_sweep_work_map_2026-10-04_b11: a fresh, complete sweep of this repository and the stdlib, both architectures

**Claim** `sweep24:sweep-b11` on `work/formal24-sweep-b11`. **This tree is
`master` at `65b88dab`** — the commit the branch was cut from, and the tree both
arms ran against (`master..HEAD` was `0 0` when the sweep launched at 09:17).
**`master` has since moved 7 commits, two of which touch files this sweep
sweeps** (`mojo/backend_gimple/emit_exprs.py`, `mojo/middle/module_shared.py`),
so a re-run on today's master is expected to differ and every number below is a
measurement of `65b88dab` and not of the merge. Both arms ran to completion over
the whole **722-file** scope with **no file left unclassified**, so every number
here is over the whole scope and every file has a verdict.

Five things a reader should take away, in the order they matter:

* **Coverage fell 31.1 % → 28.8 % and the codegen findings rose 308 → 354, and
  neither is a regression.** 41 files left `not-answerable/host-import` — real
  capability, host-module models landing — which moved them INTO the denominator
  and onto the refusal standing behind the wall that had just come down. What
  they landed on is **a five-day-old refusal with no row in either ranking
  instrument**: 115 findings are an f-string literal or a `+` on two strings
  (§3.1, §5). The rate is a worse measure of this round than the count of
  host-import files that left the class.
* **The largest unowned row in the corpus emptied two rows behind it, and 54
  files went DARK rather than getting fixed.** The handler-arm row went
  **30 → 1** with **29 files dark**; the module-ATTRIBUTE row went **30 → 4**
  with **25 dark** and 1 actually passing. Both are the same sentence: the
  interpolated-literal refusal is asked over a module's whole body **before any
  emitter runs**, so a module with an f-string never reaches the
  construct-level refusals (§3.2). `FILES BLOCKED IS AN UPPER BOUND` arriving as a
  blind spot rather than as a caveat.
* **The two architectures are the same sweep, exactly, for the fifth round
  running, and this is the first with nothing left to explain.** All **577**
  classified paths have the same class on x86-64, there is **no x86-64-only row**,
  **no arm64-only row**, and — new this round — **not one classified path has a
  changed REASON** (§2.2). `-10`'s single REASON CHANGED was an architecture's
  own name inside a mangled dylib filename; there is no such case left.
* **`module exports no public functions` grew 33 → 59 and the bare-template-call
  row fell 170 → 148, and NONE of the 23 files that left the second row was
  fixed** — 21 went dark behind the first and 2 behind the new f-string refusal
  (§3.3). That is the same trap `-10` recorded for the 43-file Optional row, one
  layer along, and it is why the round's biggest row is not a fix.
* **This branch's change is in the two instruments that RANK refusals, not in
  the backend** (§5), and it is measured: `other refusal` 121 → **6**, and the
  new row is **rank 2 of 17 at 115 files** with the same number on both
  architectures. It converts **0 files to passes**, and §5.3 says why that is the
  measurement rather than a disappointment: 0 of 9 files sampled behind the row
  reach `pass`, so what the row needed was to be *named*, not lowered.

---

## 1. The run

### 1.1 The commands, and how long they took

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86-11 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-11.txt 2>&1 &
python3 tools/memslot.py --gb 8 --label sweep-arm-11 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-11.txt  2>&1 &
```

Launched 09:17:34 local; both summary blocks were on disk by 09:43:23, so
**≤ 26 minutes for both arms together** at `-j 4` each — eight concurrent builds
on an eighteen-core box that started the run at **load 8.8**. No wait on either
per-architecture `flock` (`formal_sweep.py` keeps one per arch, plus a separate
`cas/formal-imports/<arch>/`), which is why both arms started together: no
sibling worker held either lock, and `--allow-concurrent` was not needed and
would have been the wrong answer anyway (it is for two sweeps of the SAME
architecture, which share the module-dylib output directory).

Both arms **exit 1**, which is right: the run has real findings, and each log's
`memcap:` line says `child exit 1`. **`memcap` never breached — peak 0.7 GB
across up to 9 processes** against the 8 GB reservation, on either arm.

The interpreter is not optional
(`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend_needs_3_10.md`):
`export PATH=/opt/homebrew/bin:$PATH` first, or the tool refuses to start with a
diagnosis rather than a wait.

### 1.2 Scope: 722 files

This worktree's own **470** `*.py`/`*.mojo` plus the **252** under
`../new-modular/Mojo/stdlib/std`. The repository has grown from 458 to 470 since
`-10`, and that is the whole of the scope delta: **12 files added, every one of
them accounted for below** (§2.3).

### 1.3 No `tool` row at all, for the second round running

`-10` was the first round in this series with an empty `tool` class, and this one
keeps it: **all 722 files have a verdict on both architectures.** There is no
second sweep to fold in and no reading of the table that flatters the rate.

---

## 2. Class counts

### 2.1 Against `-10`

Left column: `-10`'s summary block (`…_b10.md` §2.1). Right column: this run.

| class | **`-10`** | **`-11`** | Δ |
|---|---|---|---|
| **pass** | 141 | **145** | **+4** |
| built-with-admitted-contracts | 4 | 4 | 0 |
| **codegen** (a refusal IN this file) | 80 | **84** | **+4** |
| **codegen/dependency** (refused in a module it imports) | 228 | **270** | **+42** |
| not-answerable/host-import | 244 | **203** | **−41** |
| not-answerable/unresolved-import | 8 | 11 | +3 |
| not-answerable/unresolved-extern | 0 | 0 | 0 |
| not-answerable/system-module-call | 0 | 0 | 0 |
| not-answerable/target-limit | 5 | 5 | 0 |
| **backend-crash** | 0 | 0 | **0** |
| **tool — no verdict at all** | 0 | **0** | **0** |
| **files swept** | 710 | **722** | +12 |
| **codegen coverage** | 141/453 = **31.1 %** | 145/503 = **28.8 %** | **−2.3 pp** |

**354 of the 710 files carried a codegen verdict** at `-10` (`80 + 228`); **354 of
the 722 carry one now** (`84 + 270`). The count is IDENTICAL and the rate is not,
which is the whole point of printing both: **46 of the 354 are files that were
`not-answerable/host-import` a week ago**, and a file that stops being a fact
about the target and becomes a finding is worth counting as progress even though
the rate falls.

**`not-answerable/host-import` fell by 41, and that is the round's real
capability gain.** By first host module named, the movers:

| module | `-10` | `-11` | reading |
|---|---|---|---|
| `glob` | 17 | **0** | a `formal/hostmods/glob.mojo` model |
| `cas` | 9 | **0** | not a host module — these files import `cas`, which was refused through `glob`/`zlib` |
| `formal.imports` | 7 | **0** | same, one level along |
| `driver` | 6 | **0** | same |
| `types` | 10 | 6 | −4 |
| `test_formal_json` | 4 | **0** | same |
| `zlib` | 3 | **0** | a hostmod model |
| `py314_cache` | 3 | **0** | same |
| `resource`, `monomorphize` | 2 each | **0** | same |

The classes that are neither "no verdict" nor coverage, with this run's counts:
`not-answerable/host-import` **203** (75 import a module a Mojo-side
implementation could in principle provide, 128 need a host process or a kernel
object — by module `importlib x90`, `collections x29`, `unittest x16`,
`itertools x14`, `copy x13`, `signal x7`); `not-answerable/unresolved-import`
**11** (**four are this sweep's own tools and its own causes tool**, plus
`lang_spec`, the pre-rename `mojo_compiler`, `pytest`, `tools` and
`formal_template_call_census`); `not-answerable/target-limit` **5**
(`mojo_sqlite3_open` in the five `test_sqlite3*.mojo` files);
`built-with-admitted-contracts` **4** (`formal/hostmods/{concurrent/futures,
ctypes,subprocess,threading}.mojo`, in the denominator and never as passes).

### 2.2 arm64 vs x86-64: **zero** architecture-dependent verdicts, and zero changed reasons

`python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-11.txt bugs/sweeps/sweep-x86-11.txt`
— the repository's own instrument for this:

| | this run | `-10` |
|---|---|---|
| paths classified on both | **577** | 569 |
| **of those, class CHANGED** | **0** | 0 |
| x86-64-only rows (a pass on arm64) | **0** | 0 |
| arm64-only rows (a pass on x86-64) | **0** | 0 |
| class counts that differ | **none** | none |
| **of those, REASON CHANGED** | **0** | **1** |

The `-10` map explains that last cell in full: the one REASON CHANGED was an
architecture's own name inside a mangled dylib path
(`std_sys_compile.….ff1d99a6d0db.arm64.dylib` vs `.x86_64.dylib`), which the
tool deliberately does not fold because the name is part of the filename. **This
round that case does not arise at all.** In 722 files the two architectures
produce the same verdict *and the same sentence* for every single one.

### 2.3 The per-file delta `-10` → `-11`: 49 of 565 common paths changed class

| | arm64 | x86-64 |
|---|---|---|
| paths classified by `-10` | 569 | 569 |
| paths classified by `-11` | 577 | 577 |
| common paths | **565** | **565** |
| **class CHANGED** | **49** | **49** |
| new non-pass rows (the scope grew by 12) | 12 | 12 |
| **paths that left the non-pass set (now passing)** | **4** | **4** |

| move | n | reading |
|---|---|---|
| `not-answerable/host-import` → `codegen/dependency` | **38** | a host-module model landed; the file now reaches the refusal behind the wall that came down |
| `not-answerable/host-import` → `codegen` | 6 | same, and the refusal is in the file itself |
| `not-answerable/host-import` → `not-answerable/unresolved-import` | 3 | same, one layer further out |
| `codegen` → `codegen/dependency` | 2 | a refusal landed in front (`std/math/uutils.mojo`, `test_cli_usage_text.py`) |

**The four paths that left the non-pass set** are `build_mojo_cli.py`,
`test_myinterpreter_simple.py`, `test_phase2_parser.py` and
`test_phase2_parser_simple.py`. `build_mojo_cli.py` is the interesting one: it
was the **`stat.S_IXUSR`** file — a module-level CONSTANT read from an imported
module, which is the one shape of the module-ATTRIBUTE row that is not a
variable — so the module-state work closed that reading and the row fell 30 → 4.
The other three are host-import rows that simply stopped being refused, and the
sweep prints nothing for a pass, so "absent from the log" is how a pass reads.

**The 12 new rows** are all accounted for: nine `not-answerable/host-import`
(five new census tools under `tools/` — `formal_field_walk_differential`,
`formal_hprior_census`, `formal_returnless_census`, `formal_template_call_census`,
`formal_untyped_param_subscript_census` — and four `test_formal_*` files beside
them, all of which import `ast`/`re`/`pathlib`/`pytest`, a fact about the target
rather than a gap in the backend), two `codegen/dependency` (`test_formal_glob.py`
and `test_formal_shlex.py`, both behind `cas.py:451`) and one `codegen`
(`test_formal_optional.py`).

---

## 3. The per-CAUSE delta is where this round happened: **146 of 565**

Class counts move 49 files. Of the **565** paths both rounds classified, **47
changed CLASS into one of the two codegen classes** — a file that was
`not-answerable/host-import` is a new codegen finding, so its cause is new by
construction — and **99 kept a codegen verdict while their CAUSE changed**. Three
of the four biggest moves are the same sentence.

| move | n | from → to |
|---|---|---|
| **a refusal landed IN FRONT of them** | **69** | handler arm x29, module ATTRIBUTE x25, `other refusal` x6, frame-address x3, bare-template-call x2, and four singletons → **string composition** (§3.1, §3.2) |
| **the export gate released them into a NAMED row** | **26** | bare-template-call x21, bracketed specialization x3, MLIR x1, a module-level name x1 → `module exports no public functions` (§3.3) |
| the host-import wall came down and the file reached the refusal behind it | 47 | a class move, §2.3 |
| `Optional unwrap` came BACK | 2 | 0 → 2 (§3.4) |
| `other refusal` → the bare-template-call row | 1 | |
| the module-ATTRIBUTE row → **a pass** | 1 | `build_mojo_cli.py` |
| | **146** | |

### 3.1 `other refusal` is 14 → 121, and **114 of the 121 are one construct that had no row**

| | `-10` | **`-11`, as swept** | **`-11`, with §5's row** |
|---|---|---|---|
| rank 1 | 170 `a call to a name the defining module does not export` | 148 (same) | 148 (unchanged) |
| **rank 2** | 33 `module exports no public functions` | **121 `other refusal`** | **115 `string composition: nothing to compose into`** |
| rank 3 | 30 a module's ATTRIBUTE read as a value | 59 `module exports no public functions` | 59 (unchanged) |
| rank 4 | 30 a handler arm with a body | 30 a handler arm with a body | 30 (unchanged) |
| rank 5 | 7 `variadic call has no ABI` | 6 (same) | 6 (unchanged) |
| **`other refusal`** | **14** | **121** | **6** |
| causes that fire on this corpus (of 63 in the table) | 20 | 16 | **17** |
| causes printed at `--min 3` | 9 | 6 | **7** |

**`other refusal` is the bucket `tools/formal_sweep_causes.py`'s own module
docstring defines as *"nobody has looked"*, and it held 121 of this corpus's 354
findings — 94 % of them one sentence.** `formal/model.py`'s
`interpolated_literal_refusal`: *"an f-string literal on line N is refused on this
path: its value is its INTERPOLATED text, and this path has no buffer to compose
one in."* It is five days old — the refusal landed 2026-10-03 in `9b40c019`
(*"an f-string literal is REFUSED, not printed as its own spelling"*), replacing
a wrong-but-exit-0 answer — and it had **no row in either instrument**, so the
largest unowned construct in the tree was reported as a shrug.

Grouped by the module that refused (`uses:` is the tool's own column: how many of
the blocked files name anything that module declares):

| refusing module | files | `uses:` | reading |
|---|---|---|---|
| `(this file)` | **45** | — | in-file refusals; 44 f-strings + 1 `+` |
| `cas.py` | **40** | **3 of 40** (`_hash`, `_inst_hash`, `_list_py_files`) | 37 are closure behind one repo file |
| `module_loader.py` | **21** | 0 of 21 | closure |
| `memslot.py` | 5 | 0 of 5 | closure |
| `type_system.py` | 2 | 0 of 2 | measured 0 |
| `determinism_trace.py` | 2 | 0 of 2 | closure |
| **114** | | | **all one sentence, over 114 distinct source lines in 114 files** |

**Two literals are 63 of the 114, and both are copy-pasted helpers sitting at the
same line number in every copy** — which is what a duplicated block looks like:

| files | the literal | where it is written |
|---|---|---|
| **41** | `f"{platform.system()}/{platform.machine()}"` | **line 451** of 41 repo files: `toolchain_fingerprint`, copied whole |
| **22** | `f'/Users/mrs/net/chatgpt/claude/{checkout}/{rel}'` | **line 108** of 22 repo files |
| 7 | `f"--backend={backend}"` | 7 files, 7 lines |
| 6 | `f'ledger-{name}.json'` | 6 files |
| 3 | `f"{_iota} {h}\n"` | `determinism_trace.py` + 2 |
| 3 | `f"int64_t<opaque->{self.base}*>"` | `type_system.py` + 2 |
| 32 | 31 further literals, one file each | |

The interpolated fields across all 114 are **48 distinct expressions in 199
places**: 99 are a bare name or attribute, 100 contain a call, index, slice or
conversion. **0 of the 114 interpolate nothing**, which kills the cheap half of
the feature before anyone tries it.

The other **6** files in the bucket are §4's singles, and each is a distinct
construct: `float_literal.mojo`'s by-name `self.__int_literal__().__int__(…)`,
`type_dict.mojo`'s `comptime` class attribute read off a type PARAMETER,
`std/sys/arg.mojo`'s `Span[StaticString, ImmStaticOrigin]` read as a subscript,
`_serialize.mojo`'s `p.unsafe_load()` (an ADD pointer read, refused because the
result is a bare address), `bootstrap_test_classes.mojo`'s `create_point`
returning a frame address **as this image's ENTRY**, and `bootstrap-validate.mojo`'s
`sources` read again after the call that made it. The seventh,
`test_relaxed_imports.mojo`'s `+` on two strings, is the one file §5's row
absorbs, being the same missing buffer.

### 3.2 Two rows emptied behind the new refusal, and **54 files went dark**

| row | `-10` | `-11` | what happened to the files that left it |
|---|---|---|---|
| a handler arm with a body | **30** | **1** | **29 DARK** — every one now refused on an f-string |
| a module's ATTRIBUTE read as a value | **30** | **4** | **25 DARK**, and **1 passes** (`build_mojo_cli.py`) |
| `frame address passed where a value is wanted` | 3 | **0** | 3 dark (`type_system.py` and 2 through it) |
| a slot holding a frame address is rebound | 1 | **0** | 1 dark (`regex_compile.py`) |
| a module-global container has no initializer | 1 | **0** | 1 dark (`tools/dataclass_reflection_sites.py`) |
| a linked module exports no such name | 2 | **1** | 1 dark (`tools/detrace_diff.py`) |

**The mechanism is one line of `formal/model.py`.** `refuse_interpolated_literals`
is asked over the **whole module body** (`iter_nodes`, recursing through function
bodies) from `formal/build.py::_prepare_functions` — before any emitter runs —
because, as its own comment says, *"a construct this path cannot represent should
be declined by name rather than answered by whichever reader happened to see it
first."* That is the right decision and it has this price: **a module with an
f-string never reaches a handler-arm refusal, a module-ATTRIBUTE refusal, a
frame-lifetime refusal or anything else.** 54 files moved one refusal further on
because a refusal landed in front of them, and in any table that counts rows that
reads exactly like a fix.

**This is the answer to "did any row go dark rather than get fixed" for this
round: yes — two rows, 54 files, all of them to one sentence.**

### 3.3 The bare-template-call row fell 170 → 148, and **none of the 23 that left it was fixed**

| move | n |
|---|---|
| `a call to a name the defining module does not export` → `module exports no public functions` | **21** |
| … → f-string composition | 2 |
| … → joined the row | 1 |

**None of the 23 was fixed.** `module exports no public functions` grew 33 → 59
over the same move, `constants.mojo` 13 → 33 and `_io.mojo` 17 → 23. This is
`-10` §2.4's trap one layer along: that round emptied the export gate in front of
the 43-file Optional row and the row "read as solved"; this round emptied it in
front of 21 files of the 148-file row. The construct is unmoved and still refused —
`FormatStruct` is 105 of the 148 now (it was 111 of the 170), `dealloc` 28,
`is_negative` 8. Its owner is unchanged: `formal23-1`, holding
`FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable`.

### 3.4 `Optional unwrap` came back: 0 → 2

`-10` recorded this row's 43 files emptying into the unclassified bucket and said
so loudly. **Two of them are back**: `std/collections/set.mojo` and
`std/memory/owned_pointer.mojo`, which at `-10` sat behind
`builtin_slice.mojo`'s "slice returns a frame address" and now reach the Optional
refusal themselves. Small, and the reading is the one `-10` already wrote down:
a row that empties because the wall in front of it came down says nothing about
the construct.

---

## 4. Ranked causes, and the next step per row

`python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-11.txt` — and
the x86-64 arm prints the same table with the same numbers, which follows from
§2.2. The `-10` column is the same tool over `sweep-arm-10.txt`.

**FILES BLOCKED IS AN UPPER BOUND**: a file's terminal cause is the first refusal
its build walk reaches, so fixing one moves the file to the next with the count
unchanged. §5.3 measures that bound for this round's largest unowned row.

| files | `-10` | in-file | cause | refused in | owner / next step |
|---|---|---|---|---|---|
| **148** | 170 | 15 | a call to a name the defining module does not export | `std.format._utils` x105, `std.memory.alloc` x28, `std.bit.mask` x8, … | **claimed** (`formal23-1`); 22 of the files it lost went dark behind the row below, §3.3 |
| **115** | — | 45 | **string composition: nothing to compose into** | (this file) x45, `cas.py` x40, `module_loader.py` x21, `memslot.py` x5, … | **§5 + `FORMAL_string_composition_has_no_buffer`** — ceiling measured at 0 passes |
| **59** | 33 | 0 | a module that exports nothing cannot be a dylib | `constants.mojo` x33, `_io.mojo` x23, … | **claimed** (`formal16-2`); `-10` §4.1 measured the constants-only family as permanent and nothing has changed it |
| **30** | 30 | 25 | a handler arm with a body (no unwinder to emit it into) | (this file) x25, `memslot.py` x5 | a refusal that is **CORRECT**, not a gap — and it is also the wall behind 45 of the 115 above. Its doc was deleted with the fix that established that; the claim `formal8-5` still carries its name |
| **6** | 7 | 1 | variadic call has no ABI | `tile.mojo` x5, (this file) x1 | **claimed by a doc, no claim**: `FORMAL_a_variadic_parameter_read_has_no_abi.md`, filed by the `-10` round. `-10` §4.4 measured that a variadic parameter's value is **not knowable** and that the cheap lowering answers wrong-but-exit-0, so it is a variadic ABI shared by both emitters AND `lib/ProofLib.lean` |
| **6** | 14 | 6 | other refusal | (this file) x6 | §3.1's last paragraph: seven distinct constructs, one file each |
| **4** | 5 | 3 | MLIR dialect construct | (this file) x3, `function.mojo` x1 | its doc's own Status says what is left is one file's own terminal, and the doc is **unowned** since `formal19-4` landed (the `-10` map recorded it as that branch's) |
| **4** | 30 | 4 | a module's ATTRIBUTE read as a value | (this file) x4 (`sys.argv` x3, `sys.stdin` x1) | `FORMAL_module_state_no_storage.md`, **UNOWNED** — `-10` recorded it as `formal19-4`'s and that branch has landed and released the claim. It is an ABI project (§(2): an exported slot, a relocation the loader honours, a lifetime story in the proof) |
| 2 each | | | method call on a value receiver; `Optional unwrap` | | §4.1 |
| 1 each | | | 7 further single-file causes | | §4.2 |

**Ownership, read from `tools/control.py claims` rather than from the `-10` map,
because two of the claims it recorded have since been RELEASED by their branches
landing:** the 148-file bare-template-call row is claimed (`formal23-1`), the
59-file export-gate row is claimed (`formal16-2`), and the 30-file handler-arm
row is a refusal that is correct and therefore has nothing to work on. **The rows
whose owners `-10` named and that are now UNOWNED are the 6-file variadic row (a
doc, no claim), the 4-file MLIR row (a doc, no claim) and the 4-file
module-ATTRIBUTE row (a doc, no claim, and a project)** — and §5's row, which is
this branch's.

### 4.1 The two 2-file rows

* **method call on a value receiver** (`std/collections/binary_heap.mojo`'s own
  `self.clear()`, `std/builtin/float_literal.mojo`'s `write_repr_to`): one stdlib
  file's own source each, and the stdlib is not editable from a repository
  worktree. Same as `-10` §4.6.
* **`Optional unwrap`**: the 2 files of §3.4, and
  `FORMAL_stdlib_optional_needs_a_representation` is **claimed** (`formal16-7`).
  Nothing here.

### 4.2 The single-file causes

Seven of them, each one file's own source or one stdlib module's own source:
`multi-index subscript`, a `` `...` `` body standing where the lowering needs
instructions, a method on a multi-field struct where a descriptor is meant,
`comptime` not folding to a constant, a `String` method that returns a SHORTER
string (`mlir.py`, and `LENGTH_DEPENDENT_METHODS` names the fix's shape), a
repetition whose count this path cannot read, and `t1.mojo`'s `sys.exit()` — a
call into a linked module that does not export the name, **deliberately not
taken**, because `formal/hostmods/sys.mojo`'s own docstring and `test_formal_sys.py`
both pin `doc/ABI.md`'s rule that a C library name like `exit` is provided by
libSystem and declines to advertise it. **None is a shared-backend patch.**

---

## 5. What this branch changed, measured

Three commits on top of `master` at `65b88dab`: this map and the two logs, the
row below, and the one bug doc it points at. **The change is in the two
instruments that RANK refusals, not in the backend**: the corpus's largest
unowned cause had no row in either, so the queue could not prioritise it.

### 5.1 The fix, in both tables

`formal/model.py`'s interpolated-literal refusal is asked over a module's whole
body and is the FIRST refusal a module with an f-string reaches, and
`tools/formal_sweep_causes.py` had no row for it while
`tools/formal_sweep.py`'s own by-family breakdown filed it under `other refusal`.
Both are keyed on different things — what a fix would have to CHANGE versus the
shape of the message — so **both** needed the row, and adding one without the
other leaves the log's own breakdown still reporting 115 findings as unclassified.

**THE MARKER IS THE FACT, NOT THE ADVICE.** `"no buffer to compose one in"` is
what is missing; the sentence beside it in the same message — *"Print the parts as
separate operands, or build the text with `+` once that is lowered"* — is wrong
about `print`, which inserts a separator between its operands, so following it
produces a wrong-but-exit-0 answer. **A fix deletes that sentence**, so keying on
it would have taken 115 files silently back to `other refusal` the day one lands.

**TWO WORDINGS, ONE CAUSE, two alternatives.** The interpolated literal and
`'+' on two strings` share no clause, and they are one row because
`formal/model.py` says in both messages that they are one missing buffer — with
`LENGTH_DEPENDENT_METHODS` as its third spelling. Three rows would read as three
projects.

### 5.2 The effect on the ranking, measured

| | **`-11` as swept** | **`-11` with §5.1's row** |
|---|---|---|
| rank 1 | 148 `a call to a name the defining module does not export` | 148 (unchanged) |
| **rank 2** | **121 `other refusal`** | **115 `string composition: nothing to compose into`** |
| rank 3 | 59 `module exports no public functions` | 59 (unchanged) |
| `other refusal` | 121 | **6** |
| causes that fire on this corpus (of 63 in the table) | 16 | **17** |
| the log's own `codegen/dependency by family`, `other refusal` | **277** | **162** |

**Every construct this corpus reaches now has a name in the table a planner reads,
and so does every family in the log's own breakdown that this corpus can reach.**
The same numbers print on the x86-64 arm, which follows from §2.2.

### 5.3 The ceiling, measured — and why 0 passes is the answer and not a shortfall

**The row is 115 files and 0 of them are one edit away from `pass`.** Measured by
building nine files with the `f` prefix stripped from a **scratch copy**
(`.tmp/ceiling/`, never committed) so the refusal is gone and the next one is
visible — the rewrite is semantically wrong on purpose, because the question is
what stands BEHIND the row:

| file | files it blocks | what it lands on with the f-strings gone |
|---|---|---|
| `cas.py` | 40 | a **handler arm with a body** (`except OSError`, line 131) — a refusal that is **correct**: `formal` has no unwinder, so every statement in an arm would be absent from the program that runs |
| `module_loader.py` | 21 | `os.environ` as a **module attribute** — `FORMAL_module_state_no_storage.md` §(2), an ABI project |
| `tools/memslot.py` | 5 | a **handler arm with a body** (line 507) — correct, as above |
| `type_system.py` | 2 | a frame address passed where a value is wanted (`isinstance()`), `FORMAL_known_limits.md` |
| `determinism_trace.py` | 2 | `os.environ.get()` — a call **through a value**, the value-model half of the same doc |
| `tools/md2html.py` | in-file | a **handler arm with a body** (line 366) — correct |
| `formal/elf.py` | in-file | a container built in a frame and read after the call that made it — frame lifetime |
| `test_formal_glob.py`, `test_formal_stat.py` | in-file | still `cas.py:451` — their own f-strings were never their terminal |

**0 of 9 reach `pass`, and not one lands on another missing buffer.** 45 of the
115 are behind the handler-arm refusal, which is correct on purpose, and 23 are
behind module state, which is a project. So the honest reading of this row is
**"the top priority to know about, not the top one to implement"** — and the
fix's value is that a planner reading this map now sees 115 files, 114 lines, 48
field expressions and 41 copies of one line, instead of 121 files and a shrug.

Also measured and recorded as **not** the fix, in the doc rather than here:
0 of the 114 literals interpolate nothing; deduplicating the 41 copies of line 451
buys 0 files, because the refusal is asked over a module's body and the one
remaining copy still refuses all 41; and the refusal's own advice is wrong (§5.1).

### 5.4 The tests, and what they prove

* **both tables' new rows are reachable from a real message** —
  `check_cause_table` asserts `classify_message(sample) == label` for every
  sample, so a marker that matches nothing fails here rather than reading as a
  cause that blocks nothing; and it asserts every label in `CAUSES` is reached by
  at least one sample, which is the dead-marker check;
* **nothing shadows either row** — both tables are first-match lists, so a row
  placed after a broader one is dead code that fails silently. They sit with the
  other string rows;
* **AND the samples are BUILT, not copied**, which is the part this file's own
  docstring says a hand-copy cannot do. Every other sample in
  `test_refusal_taxonomy.py` is a hand-copy of a message: reword the message and
  the marker still matches the stale copy, `check_cause_table` still passes, and
  the sample becomes a sample of a sentence nothing emits. These two are produced
  by **calling** `formal.model.interpolated_literal_refusal` and
  `formal.model.string_concat_refusal`, so a reword fails the test instead of
  quietly emptying a row — and if either refusal stops being reachable the pair
  **raises** rather than outliving it, which is that file's docstring point 3.

```console
$ python3 test_refusal_taxonomy.py
refusal taxonomy: PASS (257/257 checks, 43 families, 63 causes)
$ python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-11.txt | head -3
files in-file  cause
    148      15  a call to a name the defining module does not export
    115      45  string composition: nothing to compose into
```

`test_formal_sweep.py` was run too, since it owns the family table's consumers:
**124 tests, 1 failure, identical with and without this branch's diff** — it was
`TestDyldProbe.test_a_bind_name_that_itself_begins_with_an_underscore_resolves`
failing its own FIXTURE precondition, measured on `master` at `3c3516db` and
proved pre-existing here by reverting the diff and re-running. Fixed since
(2026-10-04): the precondition is now asked of the binds the fixture's imported
library exports rather than of every bind on the link line, and the file is
124/124 green. Its doc is deleted with that fix.

---

## 6. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86-11 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-11.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-arm-11 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-11.txt  2>&1

python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-11.txt            # §2, §4
python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-x86-11.txt            # §4, the same table
python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-11.txt \
                             bugs/sweeps/sweep-x86-11.txt                            # §2.2
python3 test_refusal_taxonomy.py                                                      # §5.1, §5.4
```

**§2.1's class counts are not computed by a reader**: they are the
`(classes sum to 722 = 722 files swept)` block each log ends with, which the
sweep runner computes and checks against the file count, so quoting them is
reading them. **§2.3, §3.1's grouping and §3.2/§3.3's per-cause path sets are two
runs compared**, which no committed tool does: they are
`formal_sweep_causes.py::rank` over each log (which peels every chain to its
terminal message with the sweep's own `_split_chain` / `_terminal_reason`) plus a
set difference on the printed `CLASS: path` lines. `.tmp/analyze11.py` is that
computation, **scratch and not committed** (`.tmp/` is git-ignored, and
`…_b7.md`/`…_b8.md`/`…_b9.md`/`…_b10.md` each described their scratch the same
way).

**The HOST-IMPORT half of that closing judgement is closed (2026-10-05).** The
"second tool rather than a fourth description of one" it asks for is
`tools/formal_host_import_wall.py`, with `test_formal_host_import_wall.py` pinning
its readers; the three documents that described the walk now read it, and
`bugs/FORMAL_the_host_import_wall_is_at_its_honest_floor.md` §0 carries the
re-measurement it enabled — including that this doc's own host-import row was
undercounted by 4 of 203 lines, all four of them the no-tier wording. The
`.tmp/analyze11.py` above is the part that is still scratch, and it is a different
measurement: two LOGS compared, rather than one tree's closures walked. **§5.3's ceiling is nine single-file builds**, one command each, listed in
`bugs/FORMAL_string_composition_has_no_buffer.md` §1; the inputs are scratch
copies in `.tmp/ceiling/` and the whole point is that they are semantically wrong.

`…_b10.md` §6 ends on the right judgement and it is still the right one: *"the
honest reading of that is that §2.3/§2.4's scratch should have become a second
tool rather than a fourth description of one."* **It still has not for the log-comparison half** (the
`.tmp/analyze11.py` above), and this is
the second map to repeat that judgement — which is itself the argument for it.
The closure-walk half it also names did become a tool.

**≤ 26 minutes of wall for both arms together** at `-j 4` each, on a box at load
8.8 — against `-10`'s 86 minutes, whose difference was 16 minutes of `flock` wait
and a higher load. The CAS is content-addressed and machine-wide, so a re-run with
nothing changed reads a file per file; **editing `formal/`, the parser,
`mojo/middle/`, or `tools/formal_sweep.py` invalidates all of it** — which is why
this run rebuilt **719 of 722** files (`cas: 3 hit / 719 miss` on both arms). Each
arm also rebuilt **20**/**21** files on purpose: the ones that link a formal dylib,
because the dylib is not in the cache key.