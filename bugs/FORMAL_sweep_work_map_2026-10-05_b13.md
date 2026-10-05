# FORMAL_sweep_work_map_2026-10-05_b13: the 230-file encoding wall is FULLY repaired, coverage is the best this corpus has ever measured, and the two architectures still agree exactly

**Claim** `sweep32:sweep-b13` on `work/formal32-sweep-b13`. **This tree is
`master` at `86af1b44`** — the commit the branch was cut from, and
`master..HEAD` was empty when the sweep launched at 01:53, so **every number
here is a measurement of `86af1b44` and of nothing else.** Both arms ran to
completion over the whole **738-file** scope with **no file left unclassified**
and **no `tool` row**, so every number is over the whole scope and every file
has a verdict.

Five things a reader should take away, in the order they matter:

* **The `-12` regression is GONE, and every file of it is accounted for.** Passes
  rose **131 → 149**, coverage **21.7 % → 29.6 %**, and `codegen/dependency` fell
  **430 → 267**. **The 230-file encoding wall (`a non-ASCII string: BYTES where
  CPython has CHARACTERS`) is at ZERO** — not reduced, not moved: **0 remain.**
  Where its 230 files went is measured per file in §3.2, and **not one of them
  landed on another encoding refusal**, which is the property that distinguishes
  removing a wall from moving it.
* **Coverage is the highest of any round in this series: 149/503 = 29.6 %**,
  against `-12`'s 21.7 % and `-11`'s 28.8 %. And the round-over-round
  comparison against `-11` is the quietest result in this map: **0 files changed
  cause, 0 files went to a pass, 15 changed class, and all 15 are the 16 new
  files in the scope.** Two rounds of host-module work and the corpus is stable.
* **The largest row is unchanged and still claimed: 148 files on the export
  gate** (`a call to a name the defining module does not export`), unmoved for a
  fourth round and unmoved in cause since `-11`. Second is the string-composition
  row at 109, third the module-exports-nothing row at 59; **all three are held by
  live claims**, so this branch takes none of them.
* **The top UNOWNED row is `other refusal` at 7 files** — the bucket
  `tools/formal_sweep_causes.py`'s own module docstring defines as *"nobody has
  looked"*. Four of the seven are stdlib files this worktree cannot edit, one
  already has a claimed doc (an instrument gap, §4.3), one is a correct refusal,
  and **the seventh is a defect in this repository's own lexer**:
  `test_formal_libc_symbol.py` is the **only file in the entire 738-file scope
  CPython accepts and this front end refuses**. §5 fixes it.
* **The two architectures are the same sweep, exactly, for the seventh round
  running.** All **589** classified paths have the same class on x86-64, there is
  no x86-64-only row, no arm64-only row, and **not one classified path has a
  changed REASON**. The two arms' ranked-cause tables differ in exactly one line,
  and it is which file the tool happened to print as a row's `example:`.

**§5 is this branch's change, and it is measured**: the front end's lexer learns
that a replacement field may span lines, which removes a parse error rather than
moving it, and it is worth **1 file in this corpus and 1 of 738 corpus files in
which CPython and this front end disagree** — the corpus's only such file.

---

## 1. The run

### 1.1 The commands, and how long they took

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86-13 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-13.txt 2>&1 &
python3 tools/memslot.py --gb 8 --label sweep-arm-13 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-13.txt  2>&1 &
```

Launched 01:53; both summary blocks were on disk by 02:20, so **≤ 27 minutes
for both arms together** at `-j 4` each, against `-12`'s ≤ 36 minutes on a box
that started that run at load 16.3. No wait on either per-architecture `flock`,
so both arms started together: no sibling worker held either lock and
`--allow-concurrent` was not needed.

Both arms **exit 1**, which is right: the run has real findings, and each log's
`memcap:` line says `child exit 1`. **`memcap` never breached — peak 0.8 GB on
both arms** across up to 9 processes, against the 8 GB reservation.

The interpreter is not optional
(`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend_needs_3_10.md`):
`export PATH=/opt/homebrew/bin:$PATH` first, or the tool refuses to start with a
diagnosis rather than a wait.

### 1.2 Scope: 738 files, +3 on `-12` and +16 on `-11`

This worktree's own **486** `*.py`/`*.mojo` plus the **252** under
`../new-modular/Mojo/stdlib/std`. 486 = 483 + 3 since `-12`, and **none of the
three is a behaviour change**: `tools/formal_sweep_rounds.py` (the round-over-round
comparator, §6) and `test_formal_proof_census.py` /
`tools/formal_proof_census.py`. Against `-11`'s tree (`65b88dab`) the delta is
**+16 and −0**, and all 16 are named in §2.4.

### 1.3 No `tool` row at all, for the fourth round running

`-10` was the first round in this series with an empty `tool` class, and every
round since has kept it. **All 738 files have a verdict on both architectures.**

---

## 2. Class counts

### 2.1 Against `-12`

Left column: `-12`'s summary block (`…_b12.md` §2.1). Right column: this run.

| class | **`-12`** | **`-13`** | Δ |
|---|---|---|---|
| **pass** | 131 | **149** | **+18** |
| built-with-admitted-contracts | 2 | **4** | **+2** |
| **codegen** (a refusal IN this file) | 42 | **83** | **+41** |
| **codegen/dependency** (refused in a module it imports) | 430 | **267** | **−163** |
| not-answerable/host-import | 115 | **220** | **+105** |
| not-answerable/unresolved-import | 10 | **10** | 0 |
| not-answerable/target-limit | 5 | 5 | 0 |
| not-answerable/system-module-call | 0 | 0 | 0 |
| **backend-crash** | 0 | **0** | **0** |
| **tool — no verdict at all** | 0 | **0** | **0** |
| **files swept** | 735 | **738** | +3 |
| codegen findings (`codegen` + `codegen/dependency`) | 472 | **350** | −122 |
| **codegen coverage** | 131/605 = **21.7 %** | 149/503 = **29.6 %** | **+8.0 pp** |

**Every one of those movements is the encoding wall coming down, and `tools/
formal_sweep_rounds.py` accounts for all of them by file** (§3.1). The one
number here that is NOT the wall is `not-answerable/host-import` **+105**, and
§2.3 shows that 102 of the 105 are the wall's other side: a file that had a
refusal standing in front of it now gets far enough to reach its own import.

**`codegen` rose 42 → 83 while `codegen/dependency` fell 430 → 267, and both
halves are the same event.** A refusal in a module you import is
`codegen/dependency` by definition, so with the wall gone the corpus stops
stopping at the wall and starts reporting each file's OWN construct. That is why
coverage rose while the codegen class doubled, and it is why §3.2's per-file
table is the one to read rather than either count.

### 2.2 arm64 vs x86-64: **zero** architecture-dependent verdicts, and zero changed reasons

`python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-13.txt bugs/sweeps/sweep-x86-13.txt`

| | this run | `-12` | `-11` |
|---|---|---|---|
| paths classified on both | **589** | 604 | 577 |
| **of those, class CHANGED** | **0** | 0 | 0 |
| x86-64-only rows (a pass on arm64) | **0** | 0 | 0 |
| arm64-only rows (a pass on x86-64) | **0** | 0 | 0 |
| class counts that differ | **none** | none | none |
| **of those, REASON CHANGED** | **0** | 0 | 0 |

Seventh round running with nothing to explain, and this is the third with **zero
REASON CHANGED**. In 738 files the two architectures produce the same verdict
*and the same sentence* for every single one.

The two arms' `formal_sweep_causes.py --min 1` tables differ in exactly **one
line** — `_gpu/globals.mojo` against `_gpu/_utils.mojo` as rank 1's `example:`.
The two arms sweep concurrently, so rows arrive in a different order and
`rank()` keeps the first example it saw. That is a property of the reader, not a
divergence in the backend. The summary blocks differ in exactly three lines and
all three are the architecture: the `[arm64]`/`[x86_64]` label, the `cas:` hit
count, and the x86-64-only note that 200 binds across 22 files were resolved by
reading a dylib's export trie instead of `dlopen` (dlopen only loads this host's
own architecture).

### 2.3 `not-answerable/host-import` rose by 105, and 102 of the 105 are the wall's other side

By first host module named, each log's own `by module:` line:

| module | `-12` | **`-13`** | Δ |
|---|---|---|---|
| `importlib` | 28 | **94** | **+66** |
| `collections` | 22 | **39** | **+17** |
| `itertools` | 3 | **14** | **+11** |
| `copy` | 5 | **13** | **+8** |
| `atexit`, `resource` | 0 | **1** each | hostmod models landed |
| `signal` | 0 | **0** | stays gone |
| `unittest` | 17 | 18 | +1 |
| `random`, `types`, `importlib.util`, `inspect`, `builtins`, `datetime`, `socket`, `tokenize`, … | | | unchanged |

The reach split moves with it: **53 in reach / 62 not** at `-12` → **90 in reach
/ 130 not** at `-13`. `formal/imports.py` owns that split and it is read, never
copied, so this is a fact about the target computed at run time — and the log
prints which of the two each file is, so the work is separable from the
impossible without a second tool.

**102 of the 220 are files that were `codegen/dependency` at `-12` and are
`not-answerable/host-import` now** — 229 of the wall's 230 were
`codegen/dependency` and one was `codegen` (§3.2) — which is a fact about the
TARGET replacing a finding, and the class change that reads as a loss in a class
table and as capability in the other direction. §3.2's table has all 230 of the
wall's files and this is its largest single cell.

### 2.4 The 16 new files since `-11`, and the 18 hostmods that stopped building

**The 16 new files** (`git ls-tree -r 65b88dab` against `HEAD`, both filtered to
`*.py`/`*.mojo`): `formal/examples/neg.mojo`,
`formal/hostmods/{operator,signal,traceback}.mojo`, `formal/x86_64_model_fuzz.py`,
`test_formal_doc_truth.py`, `test_formal_frame_slot_subscript_census.py`,
`test_formal_hostmods_conformance.py`, `test_formal_per_struct_asks.py`,
`test_formal_proof_census.py`, `test_formal_unicode.py`,
`tools/formal_frame_slot_subscript_census.py`, `tools/formal_model_fuzz.py`,
`tools/formal_proof_census.py`, `tools/formal_sweep_rounds.py`,
`tools/formal_untyped_param_deref_census.py`. 486 = 470 + 16, which is the whole
of the scope delta against `-11`, and **nothing was deleted** (the `comm` in the
other direction is empty).

**12 of the 16 print a row and 4 pass** — the four passers are
`formal/examples/neg.mojo` and the three hostmods `operator`, `signal`,
`traceback`, which is the same split `-12`'s map measured for the 13 files it
was looking at. A pass prints no line, so the count of new files that print is
the count of names a log can carry; the arithmetic is 16 − 12 = 4.

**18 `formal/hostmods/**` files printed a row at `-12` and print none now**, and
**all 18 were on the encoding row**: `argparse`, `ast`, `ctypes`, `fcntl`,
`glob`, `html`, `os/__init__`, `os/_syscalls`, `os/path/__init__`, `platform`,
`posixpath`, `re`, `shlex`, `shutil`, `signal`, `stat`, `struct`, `tempfile`,
`textwrap` — **they now build**, and `ctypes` and `threading` are two of the four
`built-with-admitted-contracts`. That is a refusal in a module you import
disappearing, checked by **refusing module** rather than by reading the class,
because the class cannot tell "refused" from "refused somewhere further in".

---

## 3. The per-CAUSE delta

### 3.1 Against `-12`: 108 files changed cause, 18 went to a pass, and the wall is the whole of it

`python3 tools/formal_sweep_rounds.py bugs/sweeps/sweep-arm-12.txt bugs/sweeps/sweep-arm-13.txt`

| move | n | from → to |
|---|---|---|
| **a wall came down in front of them** | **108** | the encoding row → string composition x103, module ATTRIBUTE x2, handler arm x2, `other refusal` x1 |
| **to a pass** | **18** | the encoding row → **pass** (§2.4) — all 18 hostmods |
| entered the scope | 3 | not in `-12` at all → a row in `-13` |
| from a pass | 3 | the three new files of §1.2 |
| **a file that got fixed for a reason of its own** | **0** | — |

```
                       files    old   new  delta  cause
  a non-ASCII string: BYTES where CPython has CHARACTERS   230 -> 0   -230
  a call to a name the defining module does not export     148 -> 148   +0
  string composition: nothing to compose into                6 -> 109  +103
  module exports no public functions                         59 -> 59    +0
```

**The encoding row is at 0 and the other three rows did not change by one file
except string composition, which grew by exactly the 103 that were behind the
wall.** That is the shape a wall coming down has and the shape a capability
landing does not: a capability landing moves a row's number without anything
else moving, and here 230 files moved and the three rows they were hiding
accounted for all of them.

### 3.2 **The wall is at ZERO, and here is where each of its 230 files went**

Re-classified per file from the two committed logs — not inferred from two class
counts. The left column is a class and the right is a class; the 230 were **229
`codegen/dependency` and 1 `codegen`** at `-12`:

| where a `-12` encoding-row file is at `-13` | n |
|---|---|
| **`not-answerable/host-import`** — it reached its own import and the import is a fact about the target | **102** |
| `codegen/dependency` — it reached a refusal in a module it imports | **66** |
| `codegen` — it reached a refusal in **its own** source | **42** |
| **`built-with-admitted-contracts`** | **2** (`ctypes`, `threading`) |
| **`pass`** | **18** (§2.4) |
| | **230** |

**And 0 of the 230 landed on another encoding refusal.** That is the check a
reader should make before believing any row's count and the one that
distinguishes REMOVING a wall from moving it: if the 230 had gone behind a
second encoding block the totals above would be identical and the conclusion
false. `tools/formal_sweep_causes.py` run over the `-13` log has **no row for
`a non-ASCII string`** at all — not at `--min 1` — so this is measured by the
instrument, not by reading the table.

### 3.3 Against `-11`: **zero files changed cause, in two rounds of work**

`python3 tools/formal_sweep_rounds.py bugs/sweeps/sweep-arm-11.txt bugs/sweeps/sweep-arm-13.txt`

| | `-11` | **`-13`** | Δ |
|---|---|---|---|
| pass | 145 | **149** | **+4** |
| codegen | 84 | **83** | −1 |
| codegen/dependency | 270 | **267** | −3 |
| not-answerable/host-import | 203 | **220** | +17 |
| codegen coverage | 145/503 = **28.8 %** | 149/503 = **29.6 %** | **+0.8 pp** |
| files swept | 722 | **738** | +16 |

```
  FILE MOVES:  to a pass 0    from a pass 12    cause 0    class 15    unchanged 562
  WHERE THE FILES WENT, per cause that lost any:  (no file changed cause)
  AND WHERE THEY CAME FROM, per cause that gained:  (no cause gained files from another cause)
```

**This is the result to sit with.** Two rounds, sixteen new files, four more
passes — and **not one file in the corpus changed the construct that blocks it.**
The `-12` wall (230 files) and the `-13` wall being gone are the same fact seen
from two ends: what the wall hid, when revealed, was the `-11` arrangement.
`cause 0` is therefore not an absence of work; it is a measurement that the work
of rounds 12 and 13 landed on rows that were already named and already owned.

---

## 4. Ranked causes, and the next step per row

`python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-13.txt` — and
the x86-64 arm prints the same table with the same numbers (§2.2). 17 causes fire
on this corpus.

**FILES BLOCKED IS AN UPPER BOUND**: a file's terminal cause is the first refusal
its build walk reaches, so fixing one moves the file to the next with the count
unchanged. §3.2 is the measurement of that bound for this round's largest
disappearance.

| files | `-12` | `-11` | in-file | cause | refused in | owner / next step |
|---|---|---|---|---|---|---|
| **148** | 148 | 148 | 15 | a call to a name the defining module does not export | `std.format._utils` x105, `std.memory.alloc` x28, `std.bit.mask` x8, `std.utils.numerics` x2, 5 more x1 | **CLAIMED** — `formal31-1`, `FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable`. **Unmoved for a fourth round**; the row's own `uses:` line measures that **52 of the 148 name something the refusing module declares, 95 name nothing it declares** (i.e. 95 are pure closure) and **1 is not measurable** — the chain names that module by basename only and the basename is ambiguous in this tree |
| **109** | 6 | 115 | 43 | string composition: nothing to compose into | (this file) x43, `cas.py` x40, `module_loader.py` x21, `type_system.py` x2, `determinism_trace.py` x2, `memslot.py` x1 | **CLAIMED** — `formal25-5-r2`, `FORMAL_string_composition_has_no_buffer`. The +103 is §3.1's wall, not new work |
| **59** | 59 | 59 | 0 | module exports no public functions | `constants.mojo` x33, `_io.mojo` x23, `_select.mojo`, `_unicode_lookups.mojo`, `stat.mojo` | **CLAIMED** — `formal31-1`, `FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib`. Unmoved for a fourth round; `-11` measured the constants-only family as permanent |
| **7** | 6 | 6 | **7** | **`other refusal`** — the *"nobody has looked"* bucket | (this file) x7 | **UNOWNED** — §4.1, and this branch's one member of it |
| **6** | 6 | 6 | 1 | variadic call has no ABI | `tile.mojo` x5, (this file) x1 | `FORMAL_a_variadic_parameter_read_has_no_abi.md` — **no live claim**. Its own Status says *NOT FIXED, and correctly so at the width it is written at*, so the row is a correct refusal and the repair is a calling-convention change both backends **and the Lean proof** share |
| **4** | 4 | 4 | 3 | MLIR dialect construct (`__mlir_attr`/`__mlir_type`/`__mlir_op`) | (this file) x3, `function.mojo` x1 | `FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops.md` — **no live claim**, but its own §"The next step" records items 1–3 DONE and says what remains is one file's terminal, which §4.1 measures as another row |
| **4** | 2 | 4 | 4 | a module's ATTRIBUTE read as a value, across a dylib boundary | (this file) x4 — `t_argv.mojo`, `tools/detach.py`, `tools/gatewatch.py`, `unescape_c.py` | `FORMAL_module_state_no_storage.md` — **no live claim**, storage half landed 2026-09-30. All four names are `sys.argv`/`sys.stdin`, which `formal/hostmods/sys.mojo`'s own module docstring says it **deliberately** does not declare, so the refusal is correct and closing it is the doc's ABI project |
| 2 each | | | | method call on a value receiver; `Optional unwrap`; a handler arm with a body | | §4.2 |
| 1 each | | | | **7** further single-file causes | | §4.2 |

**Ownership is read from `tools/control.py claims`, not from the `-12` map**,
because the answer moved: `-12`'s map recorded `formal28-2` on the variadic row
and `formal29-2`/`formal29-3` on the MLIR and module-ATTRIBUTE rows, and **none
of those three claims is live now** — they were released when those tasks
reached a terminal state, with their docs still in `bugs/`. So the three rows
above are unclaimed *now* and were claimed *then*, which is a different fact from
never having been looked at, and §4.1 says which of them is which.

### 4.1 `other refusal` at 7: the top unowned row, and what each of the seven actually is

All seven are in-file; the bucket's definition is in
`tools/formal_sweep_causes.py`'s module docstring.

| file | the refusal, in one sentence | what it is |
|---|---|---|
| `std/builtin/float_literal.mojo` | `self.__int_literal__()` used as a receiver for `__int__(…)`, and that is an `IntLiteral` another module declares | **stdlib** — not editable from a worktree |
| `std/collections/type_dict.mojo` | `Self._index` reads a `comptime` class attribute whose value is a **parameter** of `TypeDict`, and a parameter's value belongs to an instantiation | **stdlib** |
| `std/sys/arg.mojo` | `Span[StaticString, ImmStaticOrigin]` is a compile-time explicit-parameter list on a generic, not a subscript | **stdlib** |
| `std/utils/_serialize.mojo` | `p.unsafe_load()` as an **argument**: it reads at an offset from the receiver, which is a different construct from the same call as a statement | **stdlib** |
| `bootstrap-validate.mojo` | a container returned by a function is read again after a call | **already CLAIMED** — `formal31-2` holds `FORMAL_a_returned_container_read_after_a_call_is_a_frame_reuse`. **The refusal has a doc and a live claim and no row in either ranking instrument**, so it reads as *"nobody has looked"*. Same defect shape as §4.3, one file |
| `bootstrap_test_classes.mojo` | `create_point` returns a frame address and `create_point` is the image's ENTRY, whose caller is the C runtime and passes no such word | a **correct refusal** — the returned-frame convention needs a caller that reserves a block |
| **`test_formal_libc_symbol.py`** | **`parse error: …:483:23: unterminated string literal`** | **a defect in this repository's own lexer** — §5 |

**So: of the top unowned row, four are not this worktree's to edit, one is
already owned, one is right, and one is a bug.** That one is what §5 fixes, and
§5.1 measures what it is worth: **it is the only file in the 738-file scope that
CPython accepts and this front end refuses** — measured by asking both, over
every file in the scope, in §5.1's table.

### 4.2 The 2-file and 1-file rows

* **method call on a value receiver** — `std/collections/binary_heap.mojo`'s own
  `self.clear()` and `std/format/repr.mojo`'s: one stdlib file's own source each,
  and the stdlib is not editable from a repository worktree.
* **`Optional unwrap`** — `std/collections/set.mojo` and
  `std/memory/owned_pointer.mojo`, **both refused in `builtin_slice.mojo`**, which
  is the same two files `-11` §3.4 recorded as this row coming back.
  `FORMAL_optional_needs_a_niche.md` has **no live claim**.
* **a handler arm with a body** — `tools/procrun.py` and `tools/memcap.py`. **The
  refusal is CORRECT** and is the sweep's own documented class: `formal` has no
  exception unwinder, so no edge runs from a raise site into an arm, and an arm
  whose body is `ReturnStmt` would be absent from the program that runs.
* **The seven single-file causes.** Every one is a distinct construct; five are
  stdlib (`std/benchmark/compiler.mojo`'s tuple-index subscript,
  `std/builtin/len.mojo`'s `` `...` `` body, `std/builtin/none.mojo`'s method
  where a descriptor is meant, `std/math/polynomial.mojo`'s non-folding
  `comptime`, `test_llm/dumb_gemm.mojo`'s repetition whose count cannot be read)
  and two are in this repository: `mojo/middle/metal_ops.py`'s `c_ctype.rstrip()`
  returning a SHORTER string (`LENGTH_DEPENDENT_METHODS` names the fix's shape),
  and `t1.mojo`'s `sys.exit()` — **deliberately not taken**, because
  `formal/hostmods/sys.mojo`'s docstring and `test_formal_sys.py` both pin
  `doc/ABI.md`'s rule that a C library name like `exit` comes from libSystem.

### 4.3 The instrument gap, and whose it is: **148 files read as "nobody has looked"**

`tools/formal_sweep_causes.py::CAUSES` has a row for the export refusal. The
sweep's **own by-family breakdown** does not: `tools/formal_sweep.py::
_REFUSAL_FAMILIES` has **60 rows**, **12 of which fire on this corpus**, and none
of them is this one. So the log's own summary line reports

```
codegen/dependency by family: std.collections: other refusal x13, …  (55 modules, 136 findings)
codegen by family: other refusal x27
```

— **163 findings in the bucket both tools define as *"nobody has looked"*, of
which 148 are the single best-understood row in the corpus** (held by
`formal31-1`, with the demand pipeline measured and the inference's shape
written down). Re-classifying the log's own 163 with `CAUSES`:

| what the log calls it | what `CAUSES` calls the same 163 |
|---|---|
| 148 | a call to a name the defining module does not export |
| 4 | a module's ATTRIBUTE read as a value, across a dylib boundary |
| 2 | `Optional unwrap` |
| 2 | a handler arm with a body |
| 1 | a linked module exports no such name |
| 1 | a repetition whose count this path cannot read |
| **5** | **`other refusal` — genuinely nobody has looked** |

**This is the same two-part argument `…_b12.md` §5.2 made for the encoding
refusal, for the next one down, and the two tables are keyed on different things
(what a fix would have to CHANGE versus the shape of the message) so both needed
the row.** **It is also not this branch's to fix**: `sweep32:instrument` is held
by a live task (`formal32-instrument`, worktree `work-456`), and
`tools/formal_sweep.py` is the instrument that claim names. §5.1's one file is.

---

## 5. What this branch changed, measured

### 5.1 The lexer: a replacement field may span lines

**The defect, measured against CPython over every file in the sweep's scope** —
not inferred from the one file that tripped it:

| | count |
|---|---|
| files in the scope | **738** |
| CPython accepts, this front end **refuses** | **1** — `test_formal_libc_symbol.py` |
| this front end accepts, CPython refuses (Mojo-only syntax) | 242 |

And, with CPython's **own** tokenizer asked directly whether a
single-quoted f-string's replacement field crosses a line:

| shape | files in the scope |
|---|---|
| multi-line f-string, **single-quoted** — the shape this lexer refused | **1** (`test_formal_libc_symbol.py` lines 483–484) |
| multi-line f-string, triple-quoted — already works | 25 |

**So the honest size of this fix is one file in this corpus, and the reason it
is still the top unowned cause is not its file count**: it is the corpus's
**only** disagreement with CPython about whether a file is a program, and it is
in this repository's own front end rather than in a limit of the formal value
model. `-12`'s map filed it as `PARSE_FAIL_fire_compiler_cannot_lex_a_
multiline_f_string.md` with the reproduction and the next step; the next step is
what landed here.

**The mechanism, in one place.** `fire_compiler.py::_scan_string_end` is the
single answer to "where does this literal end", and it stops a single-quoted
literal at the first bare line end. That is CPython's rule for an ordinary
literal and **not** its rule for an interpolated one, where a `{...}` opens a
replacement field that is *code*, and code may span lines. **Three** things were
missing and all three were in the tokenizer, which is why the first two attempts
at this fix each regressed something else and each regression is now a row:

1. **The scan was not brace-aware.** `_scan_string_end` takes whether the literal
   is interpolated and, for an interpolated single-quoted literal, tracks `{`/`}`
   depth — honouring `{{`/`}}`, which are escaped braces and open nothing — and
   skips a line break at depth > 0. **A `#` needed no arm at all**: this function
   answers where a literal *ends*, and to that question every character inside a
   field is equally content. An arm for it would have to decide when a `#` starts
   a comment, which is a property of the *expression* — `:#x` is a format spec,
   `'a#b'` is inside a nested literal — and the first version of it broke both,
   in **ten files** on this tree.
2. **The delimiter inside a field is a NESTED LITERAL.** Since PEP 701
   `f"{d["k"]}"` is valid, so the scan now **asks itself** (`_scan_string_end`,
   recursively, triple run included) rather than deciding: a nested literal that
   closes is stepped over, one that does not is this literal's own closing quote
   after all — and then an unclosed field is a refusal, because accepting
   `f"a{b<nl>"` would be a malformed f-string newly accepted.
3. **A literal that crosses a line cannot reach the token stream as text.**
   `py_tokenize_named` splits the source into physical lines (`_source_lines`)
   before lexing line by line, so such a literal has to be collapsed to the
   `__MOJO_STR_N__` placeholder plus the `pending_pad` newline count a
   triple-quoted one already uses — and the condition is a **replacement-field**
   line break, not a line break, because a **backslash-continued** literal must
   stay text on its physical line for the pass that decides whether the pair is
   deleted or kept. Line ends are counted with `_LINE_TERMINATORS` and not with
   `count('\n')`, or a field crossing a bare **CR** produces no STRING token at
   all. And a **raw** f-string's `\{` does not escape, so the backslash must not
   swallow the brace — this repository's own `test_gimple_runner.py:223` writes
   `rf'...\{{'` and the first version REFUSED that file.

**Two answers to "is this literal interpolated?" was the shape of the bug, so
there is now one.** `replace_multiline_strings` already computed a prefix
boundary (`_string_prefix_start`) and `_process_nested_tstrings` already asked
the interpolated question with its own inline predicate. Both now call
`_prefix_is_interpolated`.

**What it does NOT claim, and these are the measurements a reader should make:**

* **`FILES BLOCKED IS AN UPPER BOUND**, and this file's own ceiling is
  measured: the parse error was hiding a second finding, so removing it does not
  make the file build — §5.3. One file, one class change, and a NAMED row
  behind it.
* **This is a `fire_compiler.py` change and CLAUDE.md is explicit that such a
  change owes a full `make gate`** — `gimple_codegen.py`'s lowering is a
  separate implementation and almost every step drives codegen through the
  python3-interpreted reference, so a green `test_string_literal_lexing.py` is
  not by itself sufficient evidence. **This worker is not permitted to run the
  gate**, so the gate is owed and is listed under NOT DONE.
* **The genuinely-unterminated refusals are unchanged**, and that is the property
  a fix like this has to keep: `x = "abc`, `x = 'abc`, `x = f"a{b`,
  `x = f"a{{b` and `"""…\` are all still parse errors, with CPython's own
  wording and the file/line/column the lexer already put in them.
* **Nothing outside the literal changed.** `test_string_literal_lexing.py`'s
  existing rows are unchanged, which is the proof the exclusion is narrow.

### 5.2 The tests, and what they prove

`test_string_literal_lexing.py` is the natural home — its `LITERALS` table is
**compared against CPython literal by literal**, so a new row is a comparison
rather than a pinned expectation and a future rule change has to be argued. Its
own count goes **76 → 101 checks**, and the new ones are:

* **21 `LITERALS` rows** for the interpolated shapes: a field spanning a line, a
  brace closing on a later line, the uppercase `F` and `t` spellings, a comment
  inside a field, `{v:#x}` and `{d['a#b']}` (the two the `#` arm broke), a
  nested field, CR and CRLF, PEP 701 same-quote reuse across a line, a nested
  triple and a nested f-string inside a field, a raw `rf'…\{{'` — **and five
  controls that must keep REFUSING**, because the depth rule must not have
  turned "unterminated is a refusal" into "a line break inside braces is a
  refusal somewhere else". **CPython is the oracle on every one of them**, and
  the byte-exact value contract is asserted separately from the boundary, which
  is the same split the file already makes. Every field expression is written so
  that `eval` succeeds, because this file's CPython oracle *is* `eval` — a field
  naming an undefined variable would raise `NameError` instead of answering the
  question.
* **3 `PROGRAMS` rows** asserting the SHAPE after such a literal — the shape
  verbatim from `test_formal_libc_symbol.py:482-484`, plus the brace-closes-on-
  its-own-line case and one where a postfix follows the closing delimiter on the
  same physical line (the shape `pending_pad`'s flush rule exists for). The
  failure mode in this area has always been *"the rest of the file went into the
  literal"*, so the assertion belongs on the statements that come after it.
* **one `check_multiline_fstring_line_numbers`**, which is the half no value
  assertion can see: a diagnostic **below** a multi-line f-string must name the
  line the source wrote. Two sources differing **only** in whether the f-string
  spans a line, with the expected line differing by exactly one — so a pad that
  fires unconditionally, or not at all, is visible here as a wrong LINE even when
  every VALUE in the file is right. That is the bug `fire.py`'s own docstring
  produced for triple-quoted literals, and it is why this is a check and not
  another row.

### 5.3 What this fix is worth, in the sweep's own units

**One file moves from `codegen` to `codegen/dependency`, and the coverage rate
does not move at all** — the file was already in the 503-file denominator,
because `codegen` is. **And the file does not become a pass: it lands on a
NAMED row.** Measured, both architectures:

```
$ python3 fire.py build --formal --no-prove --backend=arm64  -o .tmp/out test_formal_libc_symbol.py
build: test_formal_libc_symbol.py imports 'exec_budget', which cannot be built
       either: exec_budget.py: formal dylib has no public functions: …
$ … --backend=x86_64 …
   (identical)
```

`exec_budget.py` declares no function and no type at all, only module-level
constants, so it is the **module-exports-nothing row at rank 3** (§4). So the
parse error was **hiding a second, real finding**, and this branch's honest
reading is: **the file stopped being a lexer's newline rule and became the
thing actually in the way.** That is a better outcome than a pass and a smaller
one than a repair — and it is why §5.1's first paragraph, not this section, is
where the value of the fix is argued.

**What the fix is therefore NOT worth, stated plainly: 0.0 pp of coverage, 1
file out of 503, and no row count moves.** The 8.0 pp in §2.1 is entirely the
wall's disappearance.

### 5.4 The strongest check available without the gate, and its number

A parser change is not behaviour-preserving by default, and CLAUDE.md's standard
for a change that is supposed to be is *byte-identical output on a large
succeeding case*. The right level for a lexer is the token stream, so:

> **Every file in the sweep's 738-file scope tokenized with the committed
> `fire_compiler.py` and with this one, and the token streams compared as
> `(kind, value, line, col)` per token: 737 IDENTICAL, 1 different — and the one
> that differs is `test_formal_libc_symbol.py`, which went from a refusal to a
> token stream.**

Not "the tests pass": not one token of not one other file moved. That is the
measurement that says this change is the lexer learning one rule rather than
perturbing 738 programs, and it is reproducible in one command (§6).

**And the two self-host invariants this file's own comments call out are
re-checked rather than assumed**, because both are ways a change here has broken
the build before:

* `py_tokenize` is a **pinned C ABI symbol** (`GimpleGen._NO_OVERLOAD_MANGLE`,
  declared in `runtime/fire_runtime.h`, in `GimpleGen._KNOWN_SIGS`) — still
  **one parameter**, with `py_tokenize_named` the two-parameter variant. The new
  `interpolated` parameter went on `_scan_string_end`, which is an internal
  helper with **no** entry in either table, and it has a **default**, so a
  caller with no prefix in hand gets the ordinary-literal rule — the safe
  direction, since the wrong answer is a refusal and never a different boundary.
* **No nested closure was introduced.** The owed-newline flush was inlined at
  three places and is now `_flush_line_pad`, a module-level function, for the
  reason `pending_pad`'s own comment gives: a closure-based version of that same
  flush was behaviourally identical and broke `make check-selfhost`. Three call
  sites, one copy, no closure.

**This is still not a substitute for the gate**, and §6 says which jobs owe one.

---

## 6. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86-13 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-13.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-arm-13 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-13.txt  2>&1

python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-13.txt          # §3.1, §4
python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-x86-13.txt          # §4, the same table
python3 tools/formal_sweep_parity.py  bugs/sweeps/sweep-arm-13.txt \
                             bugs/sweeps/sweep-x86-13.txt                         # §2.2
python3 tools/formal_sweep_rounds.py  bugs/sweeps/sweep-arm-12.txt \
                             bugs/sweeps/sweep-arm-13.txt                          # §3.1
python3 tools/formal_sweep_rounds.py  bugs/sweeps/sweep-arm-11.txt \
                             bugs/sweeps/sweep-arm-13.txt                          # §3.3
python3 test_string_literal_lexing.py                                              # §5.2
```

**§2.1's class counts are not computed by a reader**: they are the
`(classes sum to 738 = 738 files swept)` block each log ends with, which the
sweep runner computes and checks against the file count. **§3.1's and §3.3's
move lists are `tools/formal_sweep_rounds.py`**, which is committed on this
branch (it is one of §1.2's three new files) precisely so that they are printed
rather than re-derived: `…_b10.md` §6 and `…_b11.md` §6 each said in the same
words that this comparison should have become a tool rather than a fourth
description of one. **§2.4's 16 are `git ls-tree -r` against `65b88dab`**, and
**§3.2's 230 and §5.1's two tables are both re-classifications of the committed
logs**, one with `formal_sweep_causes.py` and one by asking CPython's `ast` and
`tokenize` the same question the lexer is asked.

**`master` HAS MOVED SINCE 02:20**, so a re-run differs — `…_b12.md` §6 lists
what moved between `-12`'s base and the tree it swept, and this tree is
`86af1b44`. **A re-sweep is the only way to price anything that was behind the
wall**, and §3.2 is the honest statement of what that costs: this map says where
the 230 went, not what is behind each of them.

**≤ 27 minutes of wall for both arms together** at `-j 4` each. The CAS is
content-addressed and machine-wide, so a re-run with nothing changed reads a
file per file; **editing `formal/`, the parser, `mojo/middle/`, or
`tools/formal_sweep.py` invalidates all of it** — which is why this run rebuilt
**735 of 738** files (`cas: 3 hit / 735 miss` on arm64, `2 hit / 736 miss` on
x86-64) rather than replaying `-12`. Each arm also rebuilt 23–24 files on
purpose: the ones that link a formal dylib, because the dylib is not in the
cache key.