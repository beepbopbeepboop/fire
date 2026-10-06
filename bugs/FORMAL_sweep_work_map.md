# FORMAL_sweep_work_map: the formal sweep series — the current census, the measurements that outlived their round, and the index of the twenty rounds it replaces

**This is the ONE home for the formal sweep series.** It replaces twenty
per-round work maps, which between them were 8 676 lines and grew by ~500 lines
per round while every open item in them was filed as its own document — so the
queue this index is supposed to summarise grew faster than the work it described.
Every doc name it replaces is listed in **§3, THE ROUND INDEX**, with the base
commit, the scope, and the one measurement that round contributed; a citation to
a round written anywhere in this tree is a citation to a row of that table.

The split, and why it is this split:

* **§1 is a measurement of ONE commit** (`86af1b44`, 738 files, both
  architectures) and every number in it is over that commit and nothing else.
  `master` has moved many times since; a re-sweep differs and §5 says how to
  price it.
* **§2 is what the earlier rounds established and still holds** — the facts that
  are not about a round: what the coverage rate measures, why a row can empty
  without anything being fixed, what a `-t` value buys, and the composition
  findings per slice that no later round re-measured.
* **§3 is the index**, one row per superseded round, with the section numbers
  other files cite. It exists so that a citation of a round is answerable, and
  `test_suite.py::test_a_deleted_bug_doc_is_not_still_cited` is what keeps a
  round tag and an index row in step.

**Claim** `project38:docs-consolidation` on
`work/formal38-docs-consolidation`. **Nothing in this document is a new
measurement** — it is the consolidation of twenty documents into one, and every
number is attributed to the round that took it. What is asserted here that the
rounds did not assert is §2's list, which is the part that was true of all of
them and had been written down twenty times.

---

## 1. The current census

`master` at **`86af1b44`**, both arms run to completion over the whole
**738-file** scope (this worktree's own 486 `*.py`/`*.mojo` plus the 252 under
`../new-modular/Mojo/stdlib/std`), **no file left unclassified** and **no `tool`
row**. Launched 01:53; both summary blocks on disk by 02:20 — **≤ 27 minutes
for both arms together** at `-j 4` each. `memcap` never breached: peak **0.8 GB**
on both arms across up to 9 processes, against an 8 GB reservation.

### 1.1 Class counts, against the round before

| class | `-12` | `-13` | Δ |
|---|---|---|---|
| **pass** | 131 | **149** | **+18** |
| built-with-admitted-contracts | 2 | **4** | +2 |
| **codegen** (a refusal IN this file) | 42 | **83** | **+41** |
| **codegen/dependency** (refused in a module it imports) | 430 | **267** | **−163** |
| not-answerable/host-import | 115 | **220** | **+105** |
| not-answerable/unresolved-import | 10 | **10** | 0 |
| not-answerable/target-limit | 5 | 5 | 0 |
| not-answerable/system-module-call | 0 | 0 | 0 |
| **backend-crash** | **0** | **0** | **0** |
| **tool — no verdict at all** | **0** | **0** | **0** |
| files swept | 735 | 738 | +3 |
| codegen findings | 472 | **350** | −122 |
| **codegen coverage** | 131/605 = **21.7 %** | **149/503 = 29.6 %** | **+8.0 pp** |

### 1.2 arm64 vs x86-64: the same sweep, exactly, for the seventh round running

`python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-13.txt bugs/sweeps/sweep-x86-13.txt`

| | this run | `-12` | `-11` |
|---|---|---|---|
| paths classified on both | **589** | 604 | 577 |
| **of those, class CHANGED** | **0** | 0 | 0 |
| x86-64-only rows (a pass on arm64) | **0** | 0 | 0 |
| arm64-only rows (a pass on x86-64) | **0** | 0 | 0 |
| **of those, REASON CHANGED** | **0** | 0 | 0 |

The two arms' `formal_sweep_causes.py --min 1` tables differ in exactly **one**
line — `_gpu/globals.mojo` against `_gpu/_utils.mojo` as rank 1's `example:` —
and that is a property of the reader, not of the backend: the arms sweep
concurrently, rows arrive in a different order, and `rank()` keeps the first
example it saw. The summary blocks differ in exactly three lines and all three
are the architecture (the `[arm64]`/`[x86_64]` label, the `cas:` hit count, and
the x86-64-only note that 200 binds across 22 files were resolved by reading a
dylib's export trie instead of `dlopen`).

**The x86-64 backend is not where the remaining coverage is.** Seven rounds,
zero architecture-dependent verdicts, and three of those rounds also zero
changed REASONS. Every claim below is a claim about both backends.

### 1.3 What moved, per CAUSE — 108 files changed cause, 18 went to a pass, and the wall is the whole of it

`python3 tools/formal_sweep_rounds.py bugs/sweeps/sweep-arm-12.txt bugs/sweeps/sweep-arm-13.txt`

| move | n | from → to |
|---|---|---|
| **a wall came down in front of them** | **108** | the encoding row → string composition ×103, module ATTRIBUTE ×2, handler arm ×2, `other refusal` ×1 |
| **to a pass** | **18** | the encoding row → **pass** — all 18 hostmods |
| entered the scope | 3 | not in `-12` at all → a row in `-13` |
| from a pass | 3 | the three new files |
| **a file that got fixed for a reason of its own** | **0** | — |

```
                     files    old   new  delta  cause
  a non-ASCII string: BYTES where CPython has CHARACTERS   230 -> 0   -230
  a call to a name the defining module does not export     148 -> 148   +0
  string composition: nothing to compose into                6 -> 109  +103
  module exports no public functions                         59 -> 59    +0
```

**The 230-file encoding wall is at ZERO, and none of its 230 files landed on
another encoding refusal** — the check that distinguishes removing a wall from
moving it, and `tools/formal_sweep_causes.py` run over the `-13` log has **no
row for `a non-ASCII string` at all**, not even at `--min 1`, so this is
measured by the instrument rather than by reading a class table. Per file, the
230 were 229 `codegen/dependency` and 1 `codegen` at `-12`, and they went to:
**102** `not-answerable/host-import` (they reached their own import, which is a
fact about the target), **66** `codegen/dependency`, **42** `codegen`, **2**
`built-with-admitted-contracts` (`ctypes`, `threading`), **18** `pass`.

**Against `-11`, the result to sit with: 0 files changed cause in two rounds of
work.** Passes 145 → 149, coverage 28.8 % → 29.6 %, and `cause 0`. That is not
an absence of work; it is a measurement that rounds 12 and 13 landed on rows
that were already named and already owned.

### 1.4 Ranked causes, and the next step per row

`python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-13.txt` —
17 causes fire on this corpus. **FILES BLOCKED IS AN UPPER BOUND**: a file's
terminal cause is the first refusal its build walk reaches, so fixing one moves
the file to the next with the count unchanged.

Ownership is read from `tools/control.py claims`, **not** from an earlier round's
map, because the answer moves: a round recorded three rows as claimed by workers
whose claims have since been released, which is a different fact from never
having been looked at.

| files | `-12` | `-11` | in-file | cause | refused in | owner / next step |
|---|---|---|---|---|---|---|
| **148** | 148 | 148 | 15 | a call to a name the defining module does not export | `std.format._utils` ×105, `std.memory.alloc` ×28, `std.bit.mask` ×8, `std.utils.numerics` ×2, 5 more ×1 | **`FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`**, live claim. **Unmoved for a fourth round**; the row's own `uses:` line measures that **52 of the 148 name something the refusing module declares, 95 name nothing it declares** (pure closure) and **1 is not measurable** — the chain names that module by basename only and the basename is ambiguous here |
| **109** | 6 | 115 | 43 | string composition: nothing to compose into | (this file) ×43, `cas.py` ×40, `module_loader.py` ×21, `type_system.py` ×2, `determinism_trace.py` ×2, `memslot.py` ×1 | **`FORMAL_string_composition_has_no_buffer.md`**, live claim. The +103 is §1.3's wall, not new work |
| **59** | 59 | 59 | 0 | module exports no public functions | `constants.mojo` ×33, `_io.mojo` ×23, `_select.mojo`, `_unicode_lookups.mojo`, `stat.mojo` | **`FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md`**, live claim. Unmoved for a fourth round; `-11` measured the constants-only family as permanent |
| **7** | 6 | 6 | **7** | **`other refusal`** — the *"nobody has looked"* bucket | (this file) ×7 | §1.5 |
| **6** | 6 | 6 | 1 | variadic call has no ABI | `tile.mojo` ×5, (this file) ×1 | **`FORMAL_a_variadic_parameter_read_has_no_abi.md`** — no live claim. Its own Status says *NOT FIXED, and correctly so at the width it is written at*, so the row is a correct refusal and the repair is a calling-convention change that both backends **and the Lean proof** share |
| **4** | 4 | 4 | 3 | MLIR dialect construct (`__mlir_attr`/`__mlir_type`/`__mlir_op`) | (this file) ×3, `function.mojo` ×1 | **`FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops.md`** — no live claim; its §"The next step" records items 1–3 DONE and says what remains is one file's terminal, which §1.5 measures as another row |
| **4** | 2 | 4 | 4 | a module's ATTRIBUTE read as a value, across a dylib boundary | (this file) ×4 — `t_argv.mojo`, `tools/detach.py`, `tools/gatewatch.py`, `unescape_c.py` | **`FORMAL_module_state_no_storage.md`** — no live claim; the storage half landed 2026-09-30. All four names are `sys.argv`/`sys.stdin`, which `formal/hostmods/sys.mojo`'s own module docstring says it **deliberately** does not declare, so the refusal is correct and closing it is that doc's ABI project |
| 2 each | | | | method call on a value receiver; `Optional unwrap`; a handler arm with a body | | §1.6 |
| 1 each | | | | **7** further single-file causes | | §1.6 |

### 1.5 `other refusal` at 7: the top unowned row, and what each of the seven is

All seven are in-file; the bucket's definition is in
`tools/formal_sweep_causes.py`'s module docstring.

| file | the refusal, in one sentence | what it is |
|---|---|---|
| `std/builtin/float_literal.mojo` | `self.__int_literal__()` used as a receiver for `__int__(…)`, and that is an `IntLiteral` another module declares | **stdlib** — not editable from a worktree |
| `std/collections/type_dict.mojo` | `Self._index` reads a `comptime` class attribute whose value is a **parameter** of `TypeDict`, and a parameter's value belongs to an instantiation | **stdlib** |
| `std/sys/arg.mojo` | `Span[StaticString, ImmStaticOrigin]` is a compile-time explicit-parameter list on a generic, not a subscript | **stdlib** |
| `std/utils/_serialize.mojo` | `p.unsafe_load()` as an **argument**: it reads at an offset from the receiver, which is a different construct from the same call as a statement | **stdlib** |
| `bootstrap-validate.mojo` | a container returned by a function is read again after a call | had a claimed doc, since released; the refusal has a doc and no row in either ranking instrument, so it reads as *"nobody has looked"*. Same defect shape as §1.7, one file |
| `bootstrap_test_classes.mojo` | `create_point` returns a frame address and `create_point` is the image's ENTRY, whose caller is the C runtime and passes no such word | a **correct refusal** — the returned-frame convention needs a caller that reserves a block |
| **`test_formal_libc_symbol.py`** | **`parse error: …:483:23: unterminated string literal`** | **a defect in this repository's own lexer** — FIXED on the round that measured it; see below |

**So: of the top unowned row, four are not this worktree's to edit, one is
already owned, one is right, and one was a bug.** That last one was a
single-quoted f-string whose replacement field spans a line, which CPython
accepts and this front end refused — **the only file in the entire 738-file
scope where the two disagree about whether a file is a program**. Its fix is
`fire_compiler.py::_scan_string_end` learning three things (a brace-aware scan
that honours `{{`/`}}`, a nested literal as the delimiter inside a field, and a
`pending_pad` collapse so a literal crossing a line can reach the token stream),
plus `_prefix_is_interpolated` as the single answer to "is this literal
interpolated", and it is pinned by 21 `LITERALS` rows and 3 `PROGRAMS` rows in
`test_string_literal_lexing.py` (76 → 101 checks) and by
`check_multiline_fstring_line_numbers`. **It was worth 0.0 pp of coverage and 1
file out of 503, and the file did not become a pass** — it landed on the
module-exports-nothing row of rank 3, which is the better outcome and the
smaller one.

### 1.6 The 2-file and 1-file rows

* **method call on a value receiver** — `std/collections/binary_heap.mojo`'s own
  `self.clear()` and `std/format/repr.mojo`'s: one stdlib file's own source
  each, and the stdlib is not editable from a repository worktree.
* **`Optional unwrap`** — `std/collections/set.mojo` and
  `std/memory/owned_pointer.mojo`, **both refused in `builtin_slice.mojo`**, the
  same two files `-11` §3.4 recorded as this row coming back.
  `FORMAL_optional_needs_a_niche.md` has a live claim.
* **a handler arm with a body** — `tools/procrun.py` and `tools/memcap.py`. **The
  refusal is CORRECT** and is the sweep's own documented class: `formal` has no
  exception unwinder, so no edge runs from a raise site into an arm, and an arm
  whose body is `ReturnStmt` would be absent from the program that runs.
  `FORMAL_a_try_handler_arm_is_still_never_emitted.md` sizes the real work: 5
  functions in 3 files in this tree have a `TryStmt`, and **exactly one has a
  call-free body**, so emitting the arms and routing a same-function `raise`
  moves **0 files**.
* **The seven single-file causes.** Every one is a distinct construct; five are
  stdlib (`std/benchmark/compiler.mojo`'s tuple-index subscript,
  `std/builtin/len.mojo`'s `` `...` `` body, `std/builtin/none.mojo`'s method
  where a descriptor is meant, `std/math/polynomial.mojo`'s non-folding
  `comptime`, `test_llm/dumb_gemm.mojo`'s repetition whose count cannot be read)
  and two are in this repository: `mojo/middle/metal_ops.py`'s
  `c_ctype.rstrip()` returning a SHORTER string (`LENGTH_DEPENDENT_METHODS`
  names the fix's shape), and `t1.mojo`'s `sys.exit()` — **deliberately not
  taken**, because `formal/hostmods/sys.mojo`'s docstring and
  `test_formal_sys.py` both pin `doc/ABI.md`'s rule that a C library name like
  `exit` comes from libSystem.

### 1.7 The instrument gap: **148 files read as "nobody has looked"**

`tools/formal_sweep_causes.py::CAUSES` has a row for the export refusal. The
sweep's **own by-family breakdown** does not: `tools/formal_sweep.py::
_REFUSAL_FAMILIES` has **60 rows**, **12 of which fire on this corpus**, and none
of them is this one. So the log's own summary line reports

```
codegen/dependency by family: std.collections: other refusal x13, …  (55 modules, 136 findings)
codegen by family: other refusal x27
```

— **163 findings in the bucket both tools define as *"nobody has looked"*, of
which 148 are the single best-understood row in the corpus.** Re-classifying the
log's own 163 with `CAUSES`: 148 export-rule, 4 module ATTRIBUTE, 2
`Optional unwrap`, 2 handler arm, 1 a linked module exports no such name, 1 a
repetition whose count this path cannot read, and **5 genuinely unexamined**.

**This is a two-part argument and both halves are needed**, made for the
encoding refusal at `-12` and repeated here for the next row down: the two
tables are keyed on different things — what a fix would have to **CHANGE**
(`CAUSES`) versus the **shape of the message** (`_REFUSAL_FAMILIES`, for a tool
that must classify a shape it has never seen) — so both need the row, and
neither is a rounding error in a reader's judgement. The exact next step, the
marker to quote and where to place it, is
`FORMAL_the_sweep_family_table_has_no_row_for_the_export_rule_refusal.md`, which
owns it and is the one document in this series a fix should not need to
re-derive.

**While the row stands, the loud finding is correct and the corpus is red for
it.** An unclassified shape over the honesty bar exits 4 on purpose.

---

## 2. What the earlier rounds established, and still holds

Everything here is a fact about the corpus or the instrument rather than about a
round, and each of these was measured at least twice. This is the section that
the twenty deleted documents could not be: each of them carried its own copy.

### 2.1 The coverage rate is the wrong thing to watch; the class counts are not

**A file's terminal cause is the FIRST refusal the build walk reaches**, so a
module is typically behind a stack of two to four. Fixing one moves the file to
the next and the count of the row you fixed goes down by zero. Two consequences,
both measured repeatedly:

* **A row emptying is not a row fixed.** `Optional unwrap` was **43 files at
  `-9` and 0 at `-10`**, and every one of the 43 was still refused, in the
  unclassified bucket: the construct is unmoved and the refusal *in front of* it
  changed. The `module exports no public functions` row emptied 166 → 0 for the
  same reason.
* **The rate can FALL while the work lands.** `-11` lost 2.3 pp of coverage and
  gained 41 files out of `not-answerable/host-import` — real capability, host
  module models landing — which moved them into the denominator and onto the
  refusal standing behind the wall that had just come down.

**So the number to watch is the count of host-import files that LEFT the class,
and the per-CAUSE delta** (`tools/formal_sweep_rounds.py`), not the percentage.
`tools/formal_sweep_causes.py` prints a `uses:` column, and it is what sizes a
row: of the 165 files behind `binary_heap.mojo` at `-8`, **1 named anything it
declares**; of the 148 export-rule files now, **52 name something the refusing
module declares and 95 name nothing it declares** (pure closure). A row that is
95 % closure is not 148 files of work.

### 2.2 A round that fixes nothing is a real, publishable result

`-13` against `-11`: `to a pass 0`, `from a pass 12`, `cause 0`, `class 15`, and
all 15 are the 16 new files in the scope. Two rounds, sixteen new files, four
more passes, and **not one file in the corpus changed the construct that blocks
it**. Reporting that is what lets the next reader see that rounds 12 and 13
landed on rows that were already named and already owned, instead of
rediscovering it.

### 2.3 The sweep instrument's four defects, all found by reading its own output

Every one of these was a **silent wrong classification**, and every one is now
fixed in `tools/formal_sweep.py` — recorded because the shape recurs whenever the
instrument changes:

| defect | what it did | the fix |
|---|---|---|
| a build killed at the per-file memory ceiling was filed as `codegen` | a resource fact reported as a semantic one | `procrun.memcap_verdict` / `memcap_wrapper_died` are read FIRST, and a memory kill outranks every reading of the message; a dead WRAPPER is a distinct class from a breach |
| the SIGTERM drain did not drain, and the summary never arrived | an interrupted run printed nothing, so its log looked like a short scope | the handler cancels what has not started and refuses to start a build once the signal has arrived; the summary is printed after the pool drains |
| `--allow-concurrent` produced torn `manifest.json` reads | a `json.decoder.JSONDecodeError` filed as a `tool` class | `formal/build.py`'s `_write_json_atomic`; measured 0 of 12 792 torn reads after the fix |
| `unknown` and `system-module-call` were not classes the classifier could produce | 18 files re-filed on a change to the classifier, and no number faked | both are now produced, and `-8` onwards is the first round with neither |

**`other refusal` is the fifth defect and it is the one that is still open**: the
bucket means *nobody has looked*, and it has twice held the largest row in the
corpus (170 files at `-10`, 163 findings now). §1.7.

### 2.4 The sweep's own three refusals, and why each one is right to fail loudly

* **The interpreter is not optional.** The bare `python3` on this host is 3.9.6
  and the backend needs 3.10+; run under it, the same sweep reports **every file
  as `backend-crash`** with one repeated line, i.e. "no file was built at all",
  reported as the worst class in the tool. `tools/formal_sweep.py` now refuses to
  start on an interpreter that cannot import the backend (exit 2, before the
  scope is announced), with two cases in `test_formal_sweep_truth.py`. The
  diagnosis has its own doc: `INFRA_bare_python3_is_3_9_and_the_formal_backend_
  needs_3_10.md`.
* **A timeout says raise `-t`, and these were not slow files.** `-6` at
  `-t 600` left **33 files** with no verdict; `-7` at `-t 120` answered every one
  of the 668. A per-file `tool`/timeout row is a statement about the timeout, not
  about the backend, and `tool` is in no rate and no cache — so a headline
  computed over a run with `tool` rows is a headline over the files the run
  happened to reach. **Read the `files swept` line before any rate.**
* **A loud unclassified shape exits 4.** By design. The rank-1 row reading
  `other refusal` with an example file and no next step is exactly what a round
  gets diagnosed from, after the fact, by reading a work map.

### 2.5 `-j` buys much less than it looks like it does

`-j 8` reached 154 files in 1 h 38 m against `-j 4`'s 42 files in the same
window on the same scope. The parallelism that exists is in the **build**, and a
single `binary_heap.mojo`-closure file measures over two minutes of wall on its
own. Size the scope and the timeout first; treat `-j` as a latency knob.

### 2.6 The composition of each slice — no later round re-measured these

The per-slice maps of 2026-09-30 and 2026-10-02 were the only rounds that looked
at *why* a slice's coverage number was what it was, and the answers are about
the corpus rather than about a round:

* **The repository's own `g`–`m` files (8 files, 13 692 lines): 33.3 % coverage
  and half of the slice is import closure this target cannot have.** Four of the
  seven classified files are refused before codegen reaches their constructs, by
  four host imports — `ctypes` (an FFI), `subprocess` (a process), `tempfile` (a
  temporary directory), `importlib` (an interpreter to drive). **0 of the 4
  import a module a Mojo-side implementation could in principle provide**, so none
  is one inversion away from answerable and no amount of codegen work moves the
  number. `monomorphize.py` had been refused three times in one session, each
  time by the next thing in its closure, without its own constructs ever being
  measured. **Do not spend effort on those rows.**
* **The 165-file `binary_heap.mojo` row has TWO walls and codegen was only the
  first.** Its own verdict (`pop(mut self) -> Self.T`) was a receiver-ABI
  question, and it was fixed; 0 of 165 moved, because wall two is the export
  gate and no codegen work on that file touches it. Behind the gate is
  `std/algorithm/backend/tile.mojo`'s bracketed-specialization row, claimed.
  **Read the chain before the file**: `tools/formal_chain_probe.py` measures the
  link the sweep reports only the terminal of, which is how a 165-file row turns
  out to be one stdlib edit this worktree cannot make.
* **`std/` minus the two earlier slices: 118 files, and 70 of them are ONE
  documented dead end** (`binary_heap.mojo: module exports nothing`, ceiling
  measured at 0 by lifting the refusal). The three largest *actionable* causes
  in that slice were a compiler CRASH, a FALSE refusal, and a missed type name —
  all three fixed, which is the shape of a slice that is not a coverage problem.
* **x86-64 on this repository's own sources: 15 of 16 in-file findings are arm64
  findings with byte-identical messages**, and the one that is not already had a
  doc, a claim and a measured next step.
* **A `uses:` census is the only thing that tells closure from work**, and it has
  to be asked for: 21 of 25 files behind `re.mojo`'s `pend` named nothing it
  declares, 162 of 165 behind `binary_heap.mojo` named nothing it declares, 40
  of 43 behind `builtin_slice.mojo` named nothing it declares. The row's real
  size is the number in the second column.

### 2.7 The round-over-round comparator is a TOOL, and must stay one

`-10` and `-11` each said in the same words that the class-count and per-file
comparison should have become a tool rather than a fourth prose description of
one. It is `tools/formal_sweep_rounds.py`, and it prints `to a pass / from a
pass / cause / class / unchanged` plus both directions of "where the files
went", per cause that lost any and per cause that gained. **Per-class counts are
not computed by a reader**: they are the `(classes sum to N = N files swept)`
block each log ends with, which the sweep runner computes and checks against the
file count.

### 2.8 What a re-sweep costs, and what invalidates it

* **≤ 27 minutes of wall for both arms together** at `-j 4` each.
* The CAS is content-addressed and machine-wide, so a re-run with nothing changed
  reads a file per file. **Editing `formal/`, the parser, `mojo/middle/`, or
  `tools/formal_sweep.py` invalidates all of it** — which is why a round that
  changes the instrument rebuilds essentially the whole scope (`cas: 3 hit / 735
  miss` on arm64).
* Each arm also rebuilds ~24 files **on purpose**: the ones that link a formal
  dylib, because the dylib is not in the cache key.

---

## 3. THE ROUND INDEX

Twenty rounds, 2026-09-30 → 2026-10-05, all of them superseded. **The first
column is the round's TAG, and the tag is how a citation spells it** — "the `b9`
round of `bugs/FORMAL_sweep_work_map.md` §4.1" is the whole citation, and it
resolves into §3.1 below. The second column is the document the round was, which
no longer exists and which nothing in this tree cites any more.

Each row gives the base commit the numbers are a measurement of, the scope, and
what the round established. The logs are committed under `bugs/sweeps/`, so every
number below is re-derivable from them.

| tag | was | date | base | scope | what it established |
|---|---|---|---|---|---|
| `2026-09-30` | `…_2026-09-30.md` | 09-30 | — | repo slices, arm64 | the first measured-**ceiling** table: `FILES BLOCKED IS AN UPPER BOUND` and per-row ceilings, several of them 0 |
| `2026-09-30_r2` | `…_2026-09-30_r2.md` | 09-30 | — | repo slices, arm64 | the dylib export-gate family at **38 files / 9 terminal modules**, the ninth being `binary_heap.mojo` alone at 35 |
| `2026-10-01` | `…_2026-10-01.md` | 10-01 | — | repo slices, arm64 | arm64 vs x86-64 on one tree: **7 files arm64-only, 0 x86-64-only**, and not a backend difference |
| `b3` | `…_2026-10-01_b3.md` | 10-01 | — | **630 files, BOTH architectures, one tree** | the first same-tree architecture comparison, and the instrument's two splits of the `other refusal` bucket |
| `b6` | `…_2026-10-02_b6.md` | 10-02 | `4384e756` | 652 | four instrument defects found (§2.3); 33 files unanswered at `-t 600` |
| `b7` | `…_2026-10-02_b7.md` | 10-02 | `e7fbe6ef` | **668, both arms complete** | **zero `tool` rows**; the two architectures the same sweep to one file; four `backend-crash` rows fixed |
| `repo-a` | `…_2026-10-02_repo-a.md` | 10-02 | — | 29 (`a`–`f`) | `formal/model.py`'s CFG entry edges were the one cause worth a fix |
| `repo-b` | `…_2026-10-02_repo-b.md` | 10-02 | — | 8 (`g`–`m`) | one CRASH and one WRONG refusal fixed; §2.6's composition finding |
| `repo-c` | `…_2026-10-02_repo-c.md` | 10-02 | — | 211 (`n`–`z`, `tools/`, `formal/`) | `formal/hostmods/` 14/15 → **16/16** |
| `std-a` | `…_2026-10-02_std-a.md` | 10-02 | — | 94 (`builtin`,`collections`,`memory`,`algorithm`,`bit`) | three fixes; the four largest causes all owned elsewhere or at ceiling 0 |
| `std-b` | `…_2026-10-02_std-b.md` | 10-02 | — | 40 (`os`,`pathlib`,`io`,`format`,…) | three fixes; **the export gate is not this slice's constraint** — satisfying it moves 0 files here |
| `std-c` | `…_2026-10-02_std-c.md` | 10-02 | — | 118 (the rest of `std/`) | §2.6's 70-file dead end; CRASH + FALSE refusal + missed type name, all fixed |
| `x86-a` | `…_2026-10-02_x86-a.md` | 10-02 | — | 392 (repo, x86-64) | two x86-64 codegen fixes; §2.6's "15 of 16 are arm64 findings" |
| `x86-b` | `…_2026-10-02_x86-b.md` | 10-02 | — | **42 of 252** (stdlib, x86-64) | three causes closed; the run did **not** complete, and the doc said so |
| `b8` | `…_2026-10-03_b8.md` | 10-03 | `17ddeaec` | **679, both arms complete** | the run is CLEAN — no `tool`, no `backend-crash`, no `unknown`, no `system-module-call`; first round whose coverage **fell** while capability landed (§2.1) |
| `b9` | `…_2026-10-03_b9.md` | 10-03 | `55951ba3` | **697, both arms complete** | the 163-file row measured as ONE stdlib file refusing at the export gate with its ceiling another row; the 30-file handler-arm row was sitting in `other refusal` |
| `b10` | `…_2026-10-04_b10.md` | 10-04 | `3c3516db` | **710, both arms complete** | the per-edge export gate emptied the 166-file row **into** `other refusal`, and 170 of the 184 were one construct — which is why `CAUSES` got a row |
| `b11` | `…_2026-10-04_b11.md` | 10-04 | `65b88dab` | **722, both arms complete** | two rows emptied **behind** a five-day-old refusal with no row in either instrument, and **54 files went dark** |
| `b12` | `…_2026-10-04_b12.md` | 10-04 | `77b24183` | **735, both arms complete** | a **229-file regression named**: six lines of em-dash prose in a docstring refused every `s[i]` in a module 229 files import |
| `b13` | `…_2026-10-05_b13.md` | 10-05 | `86af1b44` | **738, both arms complete** | the wall is at ZERO and none of its 230 files landed on another encoding refusal; **§1 of this document** |

### 3.1 Section numbers other files cite, and what each carried

A citation of the form *"the `b9` round, §4.1"* resolves here. This table is the
reason §3 exists rather than a list of twenty dead filenames.

| round | § | what it carried |
|---|---|---|
| `2026-09-30` | §3 | the measured-ceiling table; `FILES BLOCKED` is an upper bound |
| `2026-09-30` | §3.1 | row 2, `L[T]()` at 41 files, **measured ceiling 0** — fixed, and 0 of the 41 changed class |
| `2026-09-30` | row 8 | `callee has no definition on this path`, 12 files in the sweep's scope and 41 over all roots, **measured ceiling 0** for every arm. The row's own document is deleted because that is what it concluded; `test_refusal_taxonomy.py::_no_def_callee_arm_checks` is what it left behind, and `formal/model.py::EMITTER_BUILTINS` / `_frame_param_contract` / `_export_frame_contract` are the three changes |
| `2026-09-30_r2` | §3.2 | the export-gate family at 38 files / 9 terminal modules |
| `2026-10-01` | §4 | arm64 vs x86-64 on one tree: 7 / 0 / 106 / 510 |
| `b3` | §2 | the ranked-cause table this series' later rounds kept the shape of; `uses:` sizes a row |
| `b3` | §4 | **56 files x86-64-only, all 56 one construct** (the register-argument count); the tool now reports 57 |
| `b6` | §2.3 | the interrupted run: 154 files classified of the 187 reached, both arms SIGTERMed after 1 h 38 m |
| `b7` | §2.5 | arm64 vs x86-64: 542 classified on both, 0 class changes, one x86-64-only file and it is a fact about the host |
| `b7` | §3 | the ranked causes over 668 files, both arms identical |
| `b7` | §3.1 | the `uses:` table: `binary_heap.mojo` blocks 163 of which **1** names anything it declares; `builtin_slice.mojo` 43 of which **3** |
| `b7` | §3.2 | the 47 in-file refusals by shape, and the 16 one-file causes |
| `b7` | §5 | next step per cause; **every row above 10 files was claimed or measured to be closure** |
| `b7` | §6 | the largest unowned row — a dylib has no entry point for a module's top-level code. **CLOSED 2026-10-03**: the load-time initializer now exists in both object writers |
| `repo-c` | §4.5 | `regex_compile.py`: a frame address and a value assigned to the same field name — builds, runs, **SIGSEGV 139** on both |
| `b8` | §3.1 | the `uses:` table again, unchanged: 163/1 and 43/3 |
| `b8` | §4.1 | the 165-file row has TWO walls and codegen is the first |
| `b8` | §4.2 | the 20-file row's next wall, measured by lifting its own check: `os.environ` |
| `b9` | §2.2 | arm64 vs x86-64: 561 classified on both, 0 class changes, 0 x86-64-only rows |
| `b9` | §3 | the ranked causes over 697 files, both arms identical |
| `b9` | §4.1 | the 163-file row is one stdlib file at the export gate and its ceiling is `tile.mojo`'s row — **8-in-10 land there**, measured on 10 files, not projected |
| `b10` | §2.4 | the per-CAUSE delta: **212 of 306**, and 125 of them the export gate releasing files into `other refusal` |
| `b10` | §3 | the ranked causes over 710 files; `other refusal` is the rank-1 row |
| `b10` | §3.1 | the 184-file `other refusal` row is 170 files of ONE sentence |
| `b10` | §4.4 | the 7-file variadic row: **the refusal is RIGHT** — the caller passes the fixed parameters and drops the rest |
| `b10` | §5.1 | the fix: `CAUSES` gets a row for the corpus's largest construct, "the change is in the ranking instrument, not in the backend" |
| `b11` | §2.1, §2.3 | coverage **fell** 31.1 → 28.8 % while 41 files left `host-import`; 49 of 565 common paths changed class |
| `b11` | §3 | the per-CAUSE delta: **146 of 565**, and 114 of the new `other refusal` are one construct that had no row |
| `b11` | §6 | the commands |
| `b12` | §1 | the commands and the wall clock |
| `b12` | §3.2 | the mechanism is a docstring, and it is six lines of prose |
| `b12` | §3.4 | where the 236 `other refusal` files came from, and 229 of them are one wall |
| `b12` | §4.2 | the seven single-file causes, each a distinct construct |
| `b12` | §5.2 | the fix in BOTH ranking instruments — the two-part argument |
| `b13` | §5 | the lexer's multi-line f-string rule and what the fix was worth (0.0 pp of coverage, 1 file, and the file did not become a pass) — **now §1.5 of this document** |

---

## 4. What is NOT here, and where it went

**Every open item the twenty rounds filed has its own document**, which is the
reason those documents could be deleted rather than merged: a reader who starts
at a refusal follows it to the refusal's own doc, not to a census that measured
it three rounds ago. The two exceptions are named:

* `FORMAL_the_sweep_family_table_has_no_row_for_the_export_rule_refusal.md` —
  §1.7's next step in full. **Not** folded in here on purpose: it is a
  five-line change to one table with a marker to quote, and a map that carries
  another document's next step is how the twenty became twenty.
* `FORMAL_known_limits.md` — the audit of which refusals in the residue are
  **true limits** rather than gaps, which is a different axis from ranking by
  files blocked. It is the counterpart to §2.6 and it is not superseded by it.

**The per-slice rounds also fixed things and recorded the pins.** Those pins are
in the test files and the fixes are in the tree; the rounds' `## What landed`
sections are a changelog, and `git log` is the changelog.

---

## 5. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-N.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-arm -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-N.txt  2>&1

python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-N.txt   # §1.4
python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-x86-N.txt  # §1.4, same table
python3 tools/formal_sweep_parity.py  bugs/sweeps/sweep-arm-N.txt \
                             bugs/sweeps/sweep-x86-N.txt                  # §1.2
python3 tools/formal_sweep_rounds.py  bugs/sweeps/sweep-arm-N-1.txt \
                             bugs/sweeps/sweep-arm-N.txt                   # §1.3
python3 tools/formal_host_import_wall.py                                 # §1.4's host rows
python3 tools/formal_chain_probe.py <file>                               # §2.6's chain
python3 tools/formal_template_call_census.py                            # §1.4's `uses:`
python3 test_formal_sweep_truth.py                                      # the instrument's own checks
```

**Both arms exit 1, and that is right**: the run has real findings, and each
log's `memcap:` line says `child exit 1`. **A re-sweep is the only way to price
anything that was behind a wall** — §1.3 is the honest statement of what that
costs: this document says where the 230 went, not what is behind each of them.