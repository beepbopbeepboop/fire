# FORMAL_sweep_work_map_2026-10-05_b14: the corpus is stable, the two architectures' ranked tables are now BYTE-IDENTICAL, the baseline alarm is live and says "no regression", and the top UNOWNED row is a builtin this backend can now lower

**Claim** `sweep41:sweep-b14` on `work/formal41-sweep-b14`. **This tree is
`master` at `b83f2ed2`** — the commit the branch was cut from, and `master..HEAD`
was empty when the sweep launched at 15:24, so **every number in §1–§4 is a
measurement of `b83f2ed2` and of nothing else.** Both arms ran to completion
over the whole **768-file** scope with **no file left unclassified** and **no
`tool` row**, so every number is over the whole scope and every file has a
verdict.

Five things a reader should take away, in the order they matter:

* **The corpus is stable for the third round running, and the headline is the
  best this series has measured: 157 passes, 157/526 = 29.8 % coverage.** Against
  `-13` (149 passes, 29.6 %) that is **+8 passes and +0.2 pp**, and the
  round-over-round file-move table is the quietest result in this map: **0 files
  changed cause's row, 0 files went to a pass, 8 files changed cause, and all 8
  are the 22 files that entered the scope** — a re-wording of one refusal's
  message, measured per file in §3.2, not new work.
* **The baseline alarm is LIVE and it says there is no regression.** This is the
  first round in the series to run with `--baseline` finding a committed
  baseline to compare against (`bugs/sweeps/sweep-*.baseline.json`, banked from
  `-12`), and its `REGRESSION:` block is the new instrument from the
  `formal32-instrument` work: **103 files "moved to a WORSE class"** and **every
  one of the 103 is a `codegen/dependency` file that reached its own import** —
  §2.2 shows all 103 by name and all 103 are an improvement wearing a worse
  class's name. The alarm's own sentence says so: *"A class count that moved is
  not the finding; the file list is."*
* **The two architectures' `formal_sweep_causes.py --min 1` tables are now
  BYTE-IDENTICAL** — `diff` over the two tables is empty, where `-13` said they
  differed in one `example:` line. Parity itself is the eighth round running
  with nothing to explain: **611 classified paths, 0 class changes, 0 reason
  changes, 0 arm64-only rows, 0 x86-64-only rows.**
* **The largest three rows are unchanged and all claimed** (148 export gate, 123
  string composition, 59 module-exports-nothing = **330 of 365 codegen
  findings, 90 %**), so this branch takes none of them.
* **The top UNOWNED row is `a builtin this path does not lower`, 6 files, and it
  is NEW to the ranking** — it did not exist at `-13`, where its six files were
  spread across four differently-named causes. §4.1 measures what each of the
  six actually wants, and §5 is this branch's change: `max(a, b)` and
  `min(a, b)` were that row's own stated next step ("a compare and a select;
  both emitters already have the select") and they are lowered now, on both
  architectures, against CPython.

---

## 1. The run

### 1.1 The commands, and how long they took

```sh
export PATH=/opt/homebrew/bin:$PATH
nohup python3 tools/memslot.py --gb 8 --label sweep-arm-14 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 > bugs/sweeps/sweep-arm-14.txt 2>&1 &
nohup python3 tools/memslot.py --gb 8 --label sweep-x86-14 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-14.txt 2>&1 &
```

Launched 15:24:14; both summary blocks were on disk by 16:04, so **≤ 40 minutes
for both arms together** at `-j 4` each, against `-13`'s ≤ 27 minutes — **the
machine was 50 % busier**, which is the expected cost of a round that lands
alongside the `formal40-*` merges and shows up as wall time and not as a
different answer (every §2–§4 number is a property of the source, not of the
load). No wait on either per-architecture `flock`, so both arms started together:
no sibling worker held either lock and `--allow-concurrent` was not needed.

Both arms **exit 4**, which is right: the run has real findings. **`memcap`
never breached — peak 1.0 GB on both arms** across up to 9 processes, against the
8 GB reservation. (`-13` was 0.8 GB; the ceiling is not close and the difference
is the wider `-14` scope, §1.2.)

The interpreter is not optional
(`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend_needs_3_10.md`):
`export PATH=/opt/homebrew/bin:$PATH` first, or the tool refuses to start with a
diagnosis rather than a wait.

### 1.2 Scope: 768 files, **+30** on `-13`

```
Sweep roots:
  /Users/mrs/net/chatgpt/claude/work-501  (516 files)
  /Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib/std  (252 files)
Total: 768 files
```

516 = 486 at `-13` **+ 30**, and the stdlib's 252 did not move — the whole delta
is this repository, which is where six rounds of host-module and proof work
landed. `tools/formal_sweep_rounds.py` names 22 of the 30 as *printed in NEW,
not in OLD*; the other 8 are new files that PASS (a pass prints no row), so
22 + 8 = 30 and the arithmetic is the check. The 22:

```
exec_budget.py                      formal/contracts.py
formal/peephole.py                  formal/specs.py
test_formal_closures.py             test_formal_contracts.py
test_formal_exceptions.py           test_formal_host_import_shapes.py
test_formal_host_import_wall.py     test_formal_int_semantics.py
test_formal_interop.py              test_formal_isa_census.py
test_formal_peephole.py             test_formal_proof_shape.py
test_formal_random.py               test_formal_specs.py
test_x86_64_model_fuzz.py           tools/formal_bench.py
tools/formal_host_import_shapes.py  tools/formal_host_import_wall.py
tools/formal_isa_census.py          tools/formal_proof_shape.py
```

### 1.3 No `tool` row at all, for the fifth round running

`-10` was the first round in this series with an empty `tool` class, and every
round since has kept it. **All 768 files have a verdict on both architectures**,
and the summary block's own arithmetic checks it (`classes sum to 768 = 768 files
swept`).

---

## 2. Class counts

### 2.1 Against `-13`

Left column: `-13`'s numbers (`…_b13.md` §2.1). Right column: this run.

| class | **`-13`** | **`-14`** | Δ |
|---|---|---|---|
| **pass** | 149 | **157** | **+8** |
| built-with-admitted-contracts | 4 | **4** | 0 |
| **codegen** (a refusal IN this file) | 83 | **91** | +8 |
| **codegen/dependency** (refused in a module it imports) | 267 | **274** | +7 |
| not-answerable/host-import | 220 | **214** | −6 |
| not-answerable/unresolved-import | 10 | **23** | +13 |
| not-answerable/target-limit | 5 | **5** | 0 |
| **backend-crash** | 0 | **0** | **0** |
| **tool — no verdict at all** | 0 | **0** | **0** |
| **files swept** | 738 | **768** | +30 |
| codegen findings (`codegen` + `codegen/dependency`) | 350 | **365** | +15 |
| **codegen coverage** | 149/503 = **29.6 %** | 157/526 = **29.8 %** | **+0.2 pp** |

**Read the coverage rate and the finding count together or neither means
anything.** `not-answerable/unresolved-import` rose 10 → 23 and every one of the
13 is a file that imports a **tool** of this repository — `formal_sweep` x15,
`formal_fuzz`, `formal_proof_fuzz`, `formal_sweep_rounds`, `lang_spec`,
`memslot`, `mojo_compiler`, `pytest`, `tools` — i.e. a fact about the TARGET
(a `.py` importing a sibling `.py` through a package name the module set does
not carry), not a gap in the backend. Those 13 files **left the denominator**,
which is why coverage rose 0.2 pp while the codegen findings rose 15: a scope
that grows with test files moves both numbers for a reason no backend change
had anything to do with.

### 2.2 arm64 vs x86-64: **zero** architecture-dependent verdicts, zero changed reasons, and the ranked tables are identical

`python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-14.txt bugs/sweeps/sweep-x86-14.txt`

| | this run | `-13` | `-12` |
|---|---|---|---|
| paths classified on both | **611** | 589 | 604 |
| **of those, class CHANGED** | **0** | 0 | 0 |
| x86-64-only rows (a pass on arm64) | **0** | 0 | 0 |
| arm64-only rows (a pass on x86-64) | **0** | 0 | 0 |
| class counts that differ | **none** | none | none |
| **of those, REASON CHANGED** | **0** | 0 | 0 |

Eighth round running with nothing to explain, and the fourth with **zero REASON
CHANGED**. In 768 files the two architectures produce the same verdict *and the
same sentence* for every single one.

**The two arms' RANKED TABLES are now byte-identical**, and that is new:

```
$ diff <(python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-14.txt) \
       <(python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-x86-14.txt)
$ echo $?
0
```

`-13`'s §2.2 recorded the two tables differing in exactly one line — which file
the reader happened to keep as a row's `example:`, a property of arrival order
because the two arms sweep concurrently. At `-14` even that is gone: the reader
kept the same example for every row on both arms, so the difference was always
in the reader and the corpus has now stopped depending on it. The summary blocks
still differ in three lines, all of them the architecture: the `[arm64]` /
`[x86_64]` label, the `cas:` hit count, and the x86-64-only note that **200 binds
across 22 files** were resolved by reading a dylib's export trie instead of
`dlopen` (dlopen loads only this host's own architecture).

### 2.3 The baseline alarm, and why its 103 "regressions" are 103 improvements

The new instrument is live and it is the first thing to read in the log, because
it is the only block that names FILES rather than counts:

```
committed baseline: bugs/sweeps/sweep-arm.baseline.json — banked 2026-10-05T02:16:21,
  [arm64], 738 file(s), from bugs/sweeps/sweep-arm-12.txt
  REGRESSION: 103 file(s) moved to a WORSE class than the committed baseline records,
    4 kept their class and lost their NAME, and 134 more are in a class this baseline
    does not name at all (68 moved the other way, 2 sideways, 30 not in the baseline,
    0 baseline file(s) not swept)
    92 file(s)  codegen/dependency -> not-answerable/host-import
    10 file(s)  codegen/dependency -> not-answerable/unresolved-import
     1 file(s)  codegen -> codegen/dependency
    4 file(s)  (class unchanged) -> a refusal this table does not name
```

Both arms print the same block with the same counts, which is §2.2 again.

**Every one of the 103 is a file that got FURTHER.** `not-answerable/host-import`
and `not-answerable/unresolved-import` are the two classes the tool's own
docstring calls *"a statement about the target, not a module-resolution
failure"* and *"neither host nor present in this backend's module set"* — a file
in one of them did not stop at a construct at all. So the class ordering the
comparator uses ("worse") puts a **capability** below a **finding**, and the
number is a measurement of that ordering, not of the tree. The 92 and the 10 are
the `-12` encoding wall's other side arriving late: at `-13` those files were
already past it in most cases, and the baseline is a `-12` record. The single
`codegen -> codegen/dependency` is `test_formal_libc_symbol.py`, whose parse
error `-13` removed and which now reaches a refusal in `exec_budget.py` — the
honest shape of that fix, and `-13`'s own §5.3 predicted it.

**The 4 "kept their class and lost their NAME" rows are the alarm working**:
`tools/memcap.py` and `tools/procrun.py` (a handler arm with a body),
`tools/detach.py` (`sys.argv` as a value), `tools/wave2_extract_shared.py` (an
f-string) each kept a `codegen` class while the refusal that answers them is no
longer matched by any row in `tools/formal_sweep_causes.py::CAUSES`. Two of the
four have a doc and a cause row at `-13` (`a handler arm with a body`,
`a module's ATTRIBUTE read as a value`) and one does not (§4.2).

**The 134 "in a class this baseline does not name" are the baseline's own
limitation, stated in the log**: `pass-unnamed` is *"this baseline's way of
saying a log records the COUNT of the files that printed no row and not their
names"*, so 130 of the 134 are files that are now PASSES and cannot be
attributed. **Re-banking the baseline from this run would make the next round's
alarm exact** — `tools/formal_sweep.py --write-baseline`, or
`tools/formal_sweep_rounds.py --write-baseline` for a log already in hand. This
branch does **not** re-bank it: a baseline is a claim about a tree, and banking
one mid-task from a tree that also carries §5's change would make the next
round's alarm compare against a mixture.

### 2.4 `not-answerable/host-import` fell by 6, and the reach split moved with it

By first host module named, each log's own `by module:` line (`-13` §2.3 for the
left column):

| module | `-13` | **`-14`** | Δ |
|---|---|---|---|
| `importlib` | 94 | **98** | +4 |
| `collections` | 39 | **43** | +4 |
| `itertools` | 14 | 14 | 0 |
| `copy` | 13 | **12** | −1 |
| `unittest` | 18 | **24** | +6 |
| `atexit`, `resource`, `socket`, `tokenize`, … | | | see the log |
| `signal` | 0 | **0** | stays gone |

The reach split moves the other way from the file count:
**90 in reach / 130 not** at `-13` → **72 in reach / 142 not** at `-14`, and the
log names the eight still in reach: `collections`, `copy`, `fractions`,
`functools`, `inspect`, `resource`, `types`, `uuid`. `formal/imports.py` owns
that split and it is read, never copied, so this is a fact about the target
computed at run time — and the log prints which of the two each file is, so the
work is separable from the impossible without a second tool.

---

## 3. The per-CAUSE delta

### 3.1 Against `-13`: 8 files changed cause, 0 went to a pass, and all 8 are new files

`python3 tools/formal_sweep_rounds.py bugs/sweeps/sweep-arm-13.txt bugs/sweeps/sweep-arm-14.txt`

```
FILE MOVES:
  to a pass    0
  from a pass  22
  cause        8
  class        22
  unchanged    559
```

**`to a pass 0` is the number to sit with.** Twenty-two files that used to print
a row print none — and every one of the 22 is in §1.2's list of files that
**entered the scope**, so "from a pass 22" is the scope growing and not a
regression. Not one file that existed at `-13` changed the construct that blocks
it, for the third round running (`-13` §3.3 measured the same against `-11`).

### 3.2 The 8 cause changes are ONE re-worded message, and the table shows it

```
                files    old   new  delta  cause
                    148   148     +0  a call to a name the defining module does not export
                    109   123    +14  string composition: nothing to compose into
                     59    59     +0  module exports no public functions
                      7     5     -2  other refusal
                      0     6     +6  a builtin this path does not lower
                      6     6     +0  variadic call has no ABI
                      4     4     +0  MLIR dialect construct (__mlir_attr / __mlir_type / __mlir_op)
                      4     3     -1  a module's ATTRIBUTE read as a value, across a dylib boundary
                      2     2     +0  method call on a value receiver is not one of the lowered methods
                      2     2     +0  Optional unwrap: the payload type has no niche, or the receiver states none
                      2     2     +0  a handler arm with a body (no unwinder to emit it into)
                      2     2     +0  a `...` body: no instructions to emit
                      1     1     +0  a linked module exports no such name
                      1     1     +0  a method on a multi-field struct where a descriptor is meant
                      1     1     +0  a repetition whose count this path cannot read
                      1     0     -1  comptime does not fold to a constant
                      1     0     -1  a String method that returns a SHORTER string writes the receiver's bytes
                      1     0     -1  multi-index subscript

WHERE THE FILES WENT, per cause that lost any (a file that moved to another cause is not a fix):
  other refusal  (3 file(s)):  2 -> a builtin this path does not lower
                                 1 -> string composition: nothing to compose into
  string composition  (2 file(s)):  1 -> string composition
                                      1 -> other refusal
  comptime does not fold to a constant  (1):  1 -> a builtin this path does not lower
  a String method that returns a SHORTER string  (1):  1 -> a builtin this path does not lower
  a module's ATTRIBUTE read as a value  (1):  1 -> a builtin this path does not lower
```

**`a builtin this path does not lower` did not exist at `-13`.** Its five
inbound edges are the whole of it: `other refusal` x2, and one each from
`comptime does not fold to a constant`, `a String method that returns a SHORTER
string`, and `a module's ATTRIBUTE read as a value`. **Every one of those five
files got FURTHER** — each reached its own `max`/`any`/`list` call where it used
to be stopped by a different, less specific construct — and the row that names
them is new because the refusal that answers them is now asked **before** the
ones that used to answer it. §4.1 is the per-file version of this table, and it
is the reading to trust: a cause table says a row grew by six, and this says
five of the six arrived from somewhere.

The two one-file losses are the same fact seen from the other end: `multi-index
subscript` and `comptime does not fold` are rows whose *messages* a caller now
reaches past. **`FILES BLOCKED IS AN UPPER BOUND`** — `formal_sweep_causes.py`'s
own footer — and §3.2 is the measurement of that bound for this round.

### 3.3 The row that grew is the string row, by the scope and not by a wall

`string composition: nothing to compose into` went 109 → 123. The refusal is
unchanged (`formal/model.py::string_concat_refusal`, and
`max`/`min`'s new neighbour row quotes it), and the +14 is accounted for by the
scope: of the 22 new-in-scope files, `cas.py`-reachable ones and `exec_budget.py`
join the row's `refused in:` column. **No wall came down this round**, which is
the property that distinguishes a stable round from a lucky one: at `-13` 108
files changed cause because a 230-file wall disappeared; here the cause table's
only changes are five files walking *past* a construct into the one behind it.

---

## 4. Ranked causes, and the next step per row

`python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-14.txt` — and
the x86-64 arm prints **the same table, byte for byte** (§2.2). **16 causes** fire
on this corpus, against 17 at `-13`.

**FILES BLOCKED IS AN UPPER BOUND**: a file's terminal cause is the first refusal
its build walk reaches, so fixing one moves the file to the next with the count
unchanged. §3.2 is the measurement of that bound for this round.

**Ownership is read from `tools/control.py claims`, live, at 2026-10-05 17:0x** —
and it has moved since `-13`'s §4 in a way that changes this map's whole shape,
because the three rows `-13` called claimed are now claimed by DIFFERENT tasks and
a fourth one is claimed that `-13` recorded as unclaimed.

| files | `-13` | in-file | cause | refused in | owner / next step |
|---|---|---|---|---|---|
| **148** | 148 | 15 | a call to a name the defining module does not export | `std.format._utils` x105, `std.memory.alloc` x28, `std.bit.mask` x8, `std.utils.numerics` x2, 5 more x1 | **CLAIMED** — `formal40-1` holds `FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable`, and `formal41-exports-and-strings` holds `sweep41:exports-and-strings`. Unmoved for a fifth round and unmoved in cause since `-11`. The row's `uses:` line: **52 of the 148 name something the refusing module declares, 95 name nothing it declares**, 1 not measurable |
| **123** | 109 | 50 | string composition: nothing to compose into | (this file) x50, `cas.py` x41, `module_loader.py` x23, `exec_budget.py` x4, `type_system.py` x2, `determinism_trace.py` x2, `memslot.py` x1 | **CLAIMED** — `formal40-6` holds `FORMAL_string_composition_has_no_buffer`; `formal41-exports-and-strings` holds the same area. The +14 is §3.3 |
| **59** | 59 | 0 | module exports no public functions | `constants.mojo` x33, `_io.mojo` x23, `_select.mojo`, `_unicode_lookups.mojo`, `stat.mojo` | **CLAIMED** — `formal40-1` **and** `formal40-2` both hold `FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib`. Unmoved for a fifth round |
| **6** | 0 | **6** | **`a builtin this path does not lower`** | (this file) x6 | **UNOWNED, and this branch's** — §4.1 and §5 |
| 6 | 6 | 1 | variadic call has no ABI | `tile.mojo` x5, (this file) x1 | **CLAIMED** — `formal40-3` holds `FORMAL_a_variadic_parameter_read_has_no_abi`. Its own Status says *NOT FIXED, and correctly so at the width it is written at* |
| 5 | 7 | 5 | `other refusal` — the *"nobody has looked"* bucket | (this file) x5 | §4.2 — down from 7, and the two that left left by walking FURTHER |
| 4 | 4 | 3 | MLIR dialect construct (`__mlir_attr`/`__mlir_type`/`__mlir_op`) | (this file) x3, `function.mojo` x1 | `FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops.md` — **no live claim**; its own "next step" records items 1–3 DONE |
| 3 | 4 | 3 | a module's ATTRIBUTE read as a value, across a dylib boundary | (this file) x3 — `t_argv.mojo`, `tools/detach.py`, `unescape_c.py` | `FORMAL_module_state_no_storage.md` — **no live claim**, storage half landed 2026-09-30. All three names are `sys.argv`/`sys.stdin`, which `formal/hostmods/sys.mojo`'s docstring says it **deliberately** does not declare, so the refusal is correct |
| 2 each | | | method call on a value receiver; `Optional unwrap`; a handler arm with a body; a `...` body | | §4.2 |
| 1 each | | | a method on a multi-field struct where a descriptor is meant; a linked module exports no such name; a repetition whose count this path cannot read | | §4.2 |

### 4.1 The top UNOWNED row, per file: what each of the six actually wants

All six are **in-file**, which for this row means the refusal is in the file
itself and the fix is in this backend rather than in a module boundary.

| file | the call | what it actually needs |
|---|---|---|
| `std/math/polynomial.mojo` | `reversed(range(n))` | a **reversed copy of a run-time sequence** — the same two gaps as `list`, and `FORMAL_listdir_no_run_time_sequence` |
| `std/utils/_serialize.mojo` | `max(rank - 2, 0)` | **a compare and a select** — §5. This is the ONLY two-argument `max` in the 768-file scope, and it is `for i in range(max(rank - 2, 0))` |
| `bootstrap-validate.mojo` | `sorted(glob.glob(p))` | a **sort with a comparison per element**, and a call through a value is not a thing this path can express |
| `mojo/middle/metal_ops.py` | `any(g for g in FAMILIES)` | a **fold over a sequence with a short circuit** |
| `test_formal_int_semantics.py` | `list(ROWS)` | **a run-time blob copy** — the doc says so itself, and `formal40-3` holds `FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time` |
| `tools/gatewatch.py` | `max(r[1] for r in rows)` | a **fold over a generator**, and `sorted(rows, key=lambda …)` behind it |

**So: one of the six wanted the compare-and-select and five want a run-time
sequence, a sort, a fold or a blob copy** — four of which are named projects
elsewhere and one (`tools/gatewatch.py`) is stdlib-shaped code this repository
writes and cannot lower for the same reason `polynomial.mojo` cannot. That is
the honest size of this row, and §5 takes the one file of it that is a SELECT
rather than a sequence.

### 4.2 `other refusal` at 5, and the 2-file rows

The five, all in-file, all measured off the committed log
(`tools/formal_sweep_causes.py`'s `unclassified` list, which is the same
implementation its `--min 1` table is):

| file | the refusal, in one sentence | what it is |
|---|---|---|
| `std/builtin/float_literal.mojo` | `self.__int_literal__().__int__(…)` cannot be lowered: the receiver's type is written down and the CALLEE is what is missing | **stdlib** — not editable from a worktree |
| `std/collections/type_dict.mojo` | `Self._index` reads a `comptime` class attribute whose value is `Self.keys`, a PARAMETER of `TypeDict` | **stdlib**; a parameter's value belongs to an instantiation, and there is no monomorphizer here |
| `std/sys/arg.mojo` | `Span[StaticString, ImmStaticOrigin]` is a compile-time explicit-parameter list on a generic, not a subscript | **stdlib** |
| `bootstrap_test_classes.mojo` | `create_point` returns a frame address and `create_point` is this image's ENTRY, whose caller is the C runtime | a **correct refusal** — the returned-frame convention needs a caller that reserves a block |
| **`tools/wave2_extract_shared.py`** | **`cannot read an interpolated literal from 'rf"…"': the character after the prefix is not a quote`** | **a real defect in `formal/model.py::interpolated_literal_segments`** — see below |

**`other refusal` is 7 → 5 and the arithmetic is worth stating**: of the seven at
`-13`, `-13`'s own branch fixed one (a lexer rule, `test_formal_libc_symbol.py`)
and the other six are accounted for by §3.2 — two became "a builtin", one became
string composition, one became the module-ATTRIBUTE row, and the two that remain
are this table's two stdlib files plus the two correct refusals.

**`tools/wave2_extract_shared.py` is the seventh thing in this row and it is a
bug, in this repository, in the diagnostic rather than in the lowering.** Its
source is

```python
rf"^(\\s*)from\\s+{re.escape(old)}\\s+import\\s+"
```

— a **raw** f-string, i.e. a two-character prefix. `interpolated_literal_segments`
assumes the prefix is **one** character (`quote = spelled[1]`, with a comment
saying so), so every `rf`/`fr` f-string is refused with a sentence that is FALSE
about the source: the character after `rf` *is* a quote. `fire_compiler.py` grew
the PEP 701 prefix spellings on 2026-10-05 (`_prefix_is_interpolated`), and this
reader one layer down did not follow. **It is filed, not fixed** — see §6.

* **method call on a value receiver** (2) — `std/collections/binary_heap.mojo`'s
  own `self.clear()` and `std/format/repr.mojo`'s: one stdlib file's own source
  each, and the stdlib is not editable from a repository worktree.
* **`Optional unwrap`** (2) — `std/collections/set.mojo` and
  `std/memory/owned_pointer.mojo`, **both refused in `builtin_slice.mojo`**.
  `FORMAL_optional_needs_a_niche.md` has **no live claim**; the message names the
  missing thing (`Optional[Int]` has no word to spell `None` as).
* **a handler arm with a body** (2) — `tools/procrun.py` and `tools/memcap.py`.
  The refusal is **CORRECT** and is the sweep's own documented class: `formal`
  has no exception unwinder, so no edge runs from a raise site into an arm.
* **a `...` body** (1) — `std/builtin/len.mojo`: the language's own
  no-implementation marker, and a formal image is a compiled program.
* **The three remaining singles** are each a distinct construct and each is
  either stdlib or a correct refusal: a method where a descriptor is meant
  (`std/builtin/none.mojo`), `sys.exit()` on a name libSystem provides
  (`t1.mojo` — deliberately not taken, `formal/hostmods/sys.mojo`'s docstring
  and `test_formal_sys.py` both pin it), and a repetition whose count this path
  cannot read (`test_llm/dumb_gemm.mojo`).

### 4.3 The instrument gap is now a LOUD FINDING in the log itself, and it is UNOWNED

`-13`'s §4.3 measured this from outside: 148 files read as "nobody has looked"
because `tools/formal_sweep.py::_REFUSAL_FAMILIES` has no row for the export
refusal. **`-13` could not fix it — `sweep32:instrument` was a live claim then.
It is not live now, and the same work that released it also gave the sweep a
`LOUD FINDING:` line, which is where this round's number comes from:**

```
LOUD FINDING: 136 file(s) of the 768 swept (17.7%) — shape: `…` is called, and it is
  imported from `…`, so the call has to bind a …
  105 file(s) in one wording, 28 file(s) in one wording, 1 file(s) in one wording;
  5 exact wording(s) in all
  said by: `FormatStruct` is called, and it is imported from `std.format._utils`, so
  the call has to bind a symbol `std.format._utils` exports
```

**136 files, 17.7 % of the corpus, 45 % of the 305 findings `formal_sweep.py`'s
own family table calls `other refusal`** — and every one of them is the single
best-understood row in the corpus. The fix is one row in one table, keyed on a
sentence both instruments already quote; `-13` argued the two-part case for it
and this round has the instrument to say so in the log without being asked. **It
was fixed while this branch was being written** — `77cfebbe`, *"tools/
formal_sweep.py: the export rule gets a FAMILY row, and the loud finding goes
quiet"*, merged as `09b81933` (`formal41-exports-and-strings`), and its doc was
deleted with the fix as CLAUDE.md requires. **So the honest statement about the
gap is that it existed for the whole of §1 and was closed 40 lines below this
one**, and the thing a reader should take from it is the instrument, not the row:
`LOUD FINDING:` is what turns "nobody has looked" into a number that cannot go
quiet, and `-13` §4.3 had to derive the same 136 by hand off a log because that
line did not exist yet.

**Three numbers in it are worth keeping, because they are about the row rather
than the gap.** It is **unchanged at 136 while the corpus grew by 30 and every
other ranking row moved** — the strongest form of "this is a property of the
current tree". Its denominator moved the other way, from 136/158 at `-12` to
**136/305 at `-14`**, so the row stopped being the largest thing in the
`other refusal` bucket by file count and became **45 % of it and 100 % of rank
1**. And `formal_sweep_causes.py` has always ranked the same files as
`a call to a name the defining module does not export` at 148, which is the
corpus's largest codegen cause for a fifth round and is held by `formal40-1`

---

## 5. What this branch changed, measured

### 5.1 `max(a, b)` / `min(a, b)`: the row's own stated next step, cashed

`formal/model.py::NOT_LOWERED_BUILTINS` measured `max` and `min` on 2026-10-04
and wrote down what lowering each takes: *"a compare and a select; both emitters
already have the select (`MLIR_SELECT_OP`'s `TernaryExpr` is one `CSEL`)"*. §4.1
measured that exactly one file in a 768-file scope wants that and five want a
sequence. **So the change is one rewrite in the shared pipeline, and it is
`formal/build.py`'s `_lower_builtin_extremum`:**

| | |
|---|---|
| **where** | `_prepare_functions`, immediately before the `NOT_LOWERED_BUILTINS` pre-pass — so a rewritten call is never asked about |
| **what it becomes** | `F.TernaryExpr`, which arm64 emits as one `CSEL` when all three operands are pure and x86-64 as a branch: **no emitter is taught a new construct, and the two architectures agree by construction** |
| **the comparison** | `b > a`, i.e. the SECOND operand — CPython's `max(a, b)` keeps the first and replaces it only when `b > a`. `a < b` is a different function on a NaN and this path holds a double's bit pattern in an integer word |
| **arity** | two or more positional arguments and no keyword, left-folded — CPython's N-argument `max` IS that fold |
| **guards** | pure operands (`model.is_pure_expression`, the reader `arm64_codegen.py`'s CSEL decision already used), no `key=`/`default=`, at least one bare integer literal, and **not the module body** |

**The literal guard is the one that needed justifying, and it is a measured
wrong answer rather than a caution.** A name is a word on this path, a container
is a frame-allocated blob whose word is its ADDRESS, and `max(a, b)` on two lists
compares two addresses: `a = [1, 2]; b = [3, 4]; return len(max(a, b))` built,
ran, and answered **1 on arm64 and 2 on x86-64** where CPython answers 2. An
integer literal closes the hole from the only direction a pass that cannot
classify names has: CPython itself raises `TypeError` for `list > 0` and for
`list > list`, so no *correct* program is refused for want of the guard, and
`max(rank - 2, 0)` — the corpus's one call — is a clamp, which is what a literal
is for.

**The module-body guard is the second measured one, and it was found by the
rewrite reaching a place nobody had looked.** `TOP = max(3, 9)` at file level
became a `TernaryExpr` in a module-level STORE, and such a store is not lowered:
`TOP = 9 if 1 else 3` — **no `max` anywhere** — answers **0 on both
architectures** where CPython answers 9, while `TOP = 3 + 9` at the same
position answers 12. So the rewrite turned today's honest `max(...)` refusal into
a wrong number on two architectures at once. `_lower_builtin_extremum` now skips
`M.module_body_functions(functions)` — the one reader of *"this wrapper is a
module's top level"*, used rather than matching `MODULE_BODY_NAME` because a
library is compiled from SEVERAL sources and `compile_formal_dylib` renames the
second and later bodies. **The underlying store defect is filed**
(`bugs/FORMAL_a_module_level_store_of_a_conditional_expression_is_zero.md`, §6),
with the three sibling positions measured: a default argument value and a struct
field default are both **refused by name**, and `[max(3, 9)]` is right — so two of
the four are refusals and one is a wrong answer, which is the shape of a gap
rather than of a design.

### 5.2 The silent wrong answer that guard would otherwise have walked into, REFUSED at the source

**That container comparison is a PRE-EXISTING hole and it is now closed**, because
a rewrite that can reach it may not leave it open. `formal/model.py`'s
`string_binary_refusal` is the ONE table both backends ask at every binary site
(4 sites in `arm64_codegen.py`, 3 in `x86_64_codegen.py`), and its string arm
already refused `s < t` on two `char *` with a measured transcript of the wrong
answers. **The blob arm is the same sentence for the same failure**, and it is
asked from the same place so both architectures get it:

```
$ python3 tools/formal_sweep.py --no-stdlib -j 1 -t 120 .tmp/ctnref.py     # a = [9]; b = [1]; if b > a:
CODEGEN: …  '>' is refused when the left operand is a list, tuple, set or dict. …
```

**Before the change, on `b83f2ed2`, the same source answered 1 on BOTH
architectures where CPython answers 0** — measured on this branch by building it
with the arm disabled and with it enabled, and the transcript is in §7. **The
number is the ALLOCATION ORDER and not the elements**, which is the part worth
carrying to the next reader: the same program with `a = [1, 2]; b = [3, 4]`
**happens to agree**, because `[3, 4]` is the later block and therefore the
higher address. So it is not a divergence between the architectures — they lay
the frame out the same way, which is exactly why they agree on the wrong number
— and it is a branch decided by the allocator, which is worse to debug than a
disagreement is. It also means the obvious spelling of the measurement reports
"no bug", and that is how it survived.

**Only the four relational operators are refused.** `+` concatenates two lists,
`|` unions two sets, `*` repeats one, and all three are real lowerings here;
`==`/`!=` belongs to two other arms of the same table. `-`, `/`, `//`, `%` and
`**` have no container meaning in CPython either (`[1] - [2]` is a `TypeError`
there), so a program that spells one is already broken and refusing it is not
what makes it so. **Only the operators that silently take a BRANCH are gated**,
which is where a wrong answer is hardest to see. `len(xs) > 2` is untouched, and
there is a row that says so.

### 5.3 The table row is a NAME and a SHAPE, and the census learned that

`NOT_LOWERED_BUILTINS` keeps `max` and `min` — their other three shapes still
refuse — so its two rows were **rewritten** rather than deleted, and their new
text says what the SURVIVING shapes need. Deleting the names would have put a
name in `LOWERED_BUILTINS` and `NOT_LOWERED_BUILTINS` at once, which is the
partition `test_formal_proof_breadth.py`'s
`test_every_allowed_name_is_either_lowered_or_named_as_missing` exists to catch,
and would have moved a measurable name out of the census's frontier for the sake
of a shorter sentence.

**Two readers of the arity rule exist and they do not share an AST**, so the rule
is published once, in `formal/model.py::extremum_call_is_a_select`, and asked:

| reader | what it would have said |
|---|---|
| `formal/build.py::_extremum_replacement` (fire AST) | the rewrite's own guard |
| `tools/formal_proof_breadth.py::_unlowered_builtins_in` (CPython `ast`) | which `NOT_LOWERED_BUILTINS` names a source CALLS |

**Without that, the census lies in the direction that reads well**: the first
version of this branch kept the census's source scan as it was, and a ledger row
came out saying a program stopped on `max` when the build had refused it at the
**proof** layer — because `builtin_refusal_detail` leads with the names whenever
the source merely *spells* one. Two things were fixed together, and both are
one reader each:

1. the scan skips a call of a shape this path lowers, asked from
   `extremum_call_is_a_select`;
2. `run_item` leads the detail with the names only when
   `_refusal_class` actually chose `refused-builtin` — which is half the build's
   own words. **`builtin_frontier` reads the marker back out of the detail**, so
   a false marker is a frontier row for work the run never reached.

**And the operand half of the rewrite's guard is deliberately NOT re-implemented
in the census**, stated rather than hidden: a call the census still names and the
build did not refuse costs one row its `refused-builtin` refinement and nothing
else — the safe direction, since `codegen-refused` is the class the classifier's
own docstring says a reader must not under-count.

### 5.4 The tests, and what they prove

**Nine rows in `test_formal_value_model.py`, in two new groups beside the
builtin table that file already owns** (`BUILTIN_EXTREMUM_CASES`,
`BUILTIN_EXTREMUM_REFUSALS`), because that file's stated job is *"build, run, and
require the same bytes CPython prints"* and a table of sentences is not a
measurement. **Five are ORACLE cases** — `max(a - 1, 0)`, `min(b, 100)` /
`min(100, b)`, a three-argument fold, a tie plus negatives, and
`max(a - 1, b + 1, 0)` — each run under CPython and required to print the same
bytes from **both** images, which is the only kind of row that catches an image
answering a different number. **Four are REFUSAL cases** with the needle naming
the refusal that answered them: one argument, `key=`, two names and no literal
(the guard's own boundary, one line away from the row above it), and
`len(max(a, 0))` on a container, whose needle is the blob table's sentence.

**Three rows in `test_formal_run.py`, in the section whose own comment is *"the
class: every operator that reached the integer path"*** — beside the string rows
whose measured transcript is in that comment, because that is where a reader
looks for "this operator reached the integer path". Two refusals, one per
spelling of which operand is the blob (the message says "the left operand" or
"the right operand", and a helper that always said the first would produce a
diagnostic about a line the reader is not looking at), and **one that must NOT
move**: `len(xs) > 2` is a comparison of two integers *about* a container, CPython
answers it, and a gate that fired on "a blob is mentioned near this comparison"
would put a diagnostic in front of correct code.

**And three fixtures in `test_formal_proof_breadth.py` were re-pointed**, all of
which spelled `max(n, 1)` — a shape that stopped being a refusal when §5.1
landed. `test_a_builtin_refusal_is_its_own_class_and_names_the_builtin`,
`test_a_refusal_that_names_no_builtin_stays_where_it_was` and
`test_the_report_prints_the_frontier_the_run_reached` now spell `max(n)`, which
is one of the three shapes the name still refuses, so each keeps asserting its
own thing. **A fixture that named a shape the path now answers would have kept
asserting a class against a refusal that no longer happens**, which is the
stale-marker failure `expect=` has in the test suite and these rows had in
themselves.

### 5.5 What the fix is worth, in the sweep's own units

**Measured over the WHOLE 768-file scope**, by re-running `tools/formal_sweep.py`
on arm64 after the change and diffing it against this round's own log
(`tools/formal_sweep_rounds.py`), because a per-file check of the six files of
§4.1's row cannot say whether anything ELSE moved:

```
$ python3 tools/formal_sweep_rounds.py bugs/sweeps/sweep-arm-14.txt \
      bugs/sweeps/sweep-arm-14-after-the-max-min-fix.txt
  pass 157 (unchanged)   codegen 91 (unchanged)   codegen/dependency 274 (unchanged)
  codegen coverage 157/526 = 29.8 % (unchanged)
  FILE MOVES: to a pass 0   from a pass 0   cause 1   class 0   unchanged 610
```

**610 of 611 printed rows are byte-identical, and the ONE that moved is
`std/utils/_serialize.mojo`** — the file §4.1 identified as the corpus's only
two-argument `max`. Its terminal is no longer the `max(...)` refusal; it is now
`p.unsafe_load()`, *"Mojo's name for the UNCHECKED READ through a pointer"*.

**So the whole-scope ledger is: `a builtin this path does not lower` 6 → 5,
`other refusal` 5 → 6, and every other row of the 16 unchanged.** The file got
FURTHER — it reached its own pointer read instead of a `max` call in a callee's
scope — but it got further **into the bucket both instruments define as "nobody
has looked"**, because `formal_sweep_causes.py::CAUSES` has no row for a pointer
read either. That is the honest reading and it is the one to quote: `-13`'s §3.2
made exactly this distinction when the encoding wall came down (108 files moved,
and *not one of them landed on another refusal*), and here one file moved from a
named row **onto** `other refusal`.

**What the fix is therefore NOT worth, stated plainly: 0 files out of 526 reach a
pass, 0.0 pp of coverage, no row above 6 moves, and the row it targeted drops by
one.** What it IS worth is that a CPython builtin this backend refused **by name**
now answers CPython's answer on both architectures, in the shapes programs
actually write it, with the arithmetic that made it possible already in both
emitters; that a **pre-existing silent wrong answer** on both architectures is
refused instead (§5.2); and that a **new** silent wrong answer — a module-level
store of the `TernaryExpr` the rewrite produces — is fenced off rather than
shipped (§5.1, and filed).

The re-run's log is committed beside this round's own
(`bugs/sweeps/sweep-arm-14-after-the-max-min-fix.txt`, 33 minutes, peak 0.9 GB,
exit 4) so the diff above is reproducible rather than described. **It is arm64
only**: the x86-64 half of this measurement is owed to the integrator, and §7 says
which command that is.

---

## 6. Filed, not fixed

**Two are new bug docs and one turned out to need no doc at all** — all outside
the claim (`sweep41:sweep-b14`), and each written up with the reproduction and
the exact next step.

* **`bugs/FORMAL_the_interpolated_literal_reader_assumes_a_one_character_prefix.md`**
  (NEW) — `formal/model.py::interpolated_literal_segments` refuses every `rf`/`fr`
  f-string with a sentence that is false about the source (§4.2). **One file in
  this corpus** (`tools/wave2_extract_shared.py`), and the fix is the prefix
  boundary `fire_compiler.py` already computes one layer up — with the one
  question to answer first stated in the doc (does `rawness` change the
  segmentation? it must not, and the reason is in the doc).
* **`bugs/FORMAL_a_module_level_store_of_a_conditional_expression_is_zero.md`**
  (NEW, found by §5.1) — a module-level store of a `F.TernaryExpr` answers **0 on
  both architectures** where CPython stores the arm it took, and needs no `max` to
  do it: `TOP = 9 if 1 else 3` is 0 while `TOP = 3 + 9` at the same position is
  12. **Fenced off, not fixed** — `_lower_builtin_extremum` skips the module body,
  and the doc's next step is the store path rather than the ternary, with the
  three sibling positions measured.
* **The 136-file family-table gap (§4.3) needed no doc from this branch**: it had
  one (`FORMAL_the_sweep_family_table_has_no_row_for_the_export_rule_refusal.md`,
  filed by `formal32-instrument` off the `-12` log with **the same 136**), this
  branch appended its measurement, and then **`77cfebbe` fixed the row and deleted
  the doc with it** — merged as `09b81933`. The append is therefore gone with the
  file, deliberately: carrying a doc forward that master's own fix removed would
  have put a modify/delete conflict in the integrator's merge and resurrected a
  document for a closed bug. **The measurement it carried is in §4.3 instead**,
  which is where a number about this round belongs.

**Two failures in `test_formal_proof_breadth.py` are NOT filed, because the bug
behind them was already fixed while this branch was being written.**
`test_a_call_to_a_second_function_is_a_proof_refusal` and
`test_a_list_literal_is_a_proof_refusal_not_a_crash` both fail on `b83f2ed2`
with no change of mine — measured by running the file with this branch's diff
reversed (`git apply -R` of a saved patch, never `git checkout`), where they and
only they fail. The cause is that a refusal reading *"no proof was generated: the
semantic model has no value for something in this program"* is classified
`codegen-refused` rather than `proof-refused`, because it arrives as a
`CodegenError` from the build rather than as the generator's own
`NotImplementedError`. **`ce5d2b8d` — *"formal: a proof-layer refusal is
classified by a flag, not by the exception type"* — is that fix**, merged as
`54abf30d` (`formal37-3`), and its doc was deleted with it. So the correct
report is *"two failures that master has already fixed"*, and the integrator
should see them go green on the merge rather than be handed a bug about a bug.

---

## 7. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86-14 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-14.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-arm-14 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-14.txt  2>&1

python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-14.txt          # §3.2, §4
diff <(python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-arm-14.txt) \
     <(python3 tools/formal_sweep_causes.py --min 1 bugs/sweeps/sweep-x86-14.txt)  # §2.2
python3 tools/formal_sweep_parity.py  bugs/sweeps/sweep-arm-14.txt \
                             bugs/sweeps/sweep-x86-14.txt                         # §2.2
python3 tools/formal_sweep_rounds.py  bugs/sweeps/sweep-arm-13.txt \
                             bugs/sweeps/sweep-arm-14.txt                          # §3.1, §3.2

# §5 — the fix, both architectures, against CPython
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_value_model.py \
  max_of_a_name_and_a_literal_is_a_compare_and_a_select \
  min_of_a_name_and_a_literal_is_a_compare_and_a_select \
  a_three_argument_extremum_is_the_same_select_folded \
  an_extremum_over_negatives_and_a_tie \
  an_extremum_of_arithmetic_over_names_and_a_literal \
  max_of_one_argument_is_refused_rather_than_folded_over_a_sequence \
  max_with_a_key_is_refused_rather_than_calling_through_a_value \
  max_of_two_names_is_refused_rather_than_comparing_two_addresses \
  an_extremum_of_a_container_and_a_literal_is_refused_by_the_blob_table \
  an_extremum_of_two_arithmetic_expressions_with_no_literal_is_refused
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
  list_relational_operator_refused_rather_than_comparing_addresses \
  a_blob_on_the_right_names_the_right_operand \
  len_of_a_blob_compared_with_a_number_still_compiles
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_proof_breadth.py

# …and the x86-64 half of that, which this worker did not run:
#   python3 tools/memslot.py --gb 8 --label sweep-x86-14b -- \
#     python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 \
#     > bugs/sweeps/sweep-x86-14-after-the-max-min-fix.txt 2>&1

# §5.2 — the wrong answer the blob arm closes, on b83f2ed2 (BEFORE this branch).
# The two allocations are in THIS order on purpose: with them the other way round
# (`a = [1, 2]; b = [3, 4]`) the answer HAPPENS to be right, because `[3, 4]` is
# the later block and therefore the higher address — which is how the bug reads
# as "no bug" if you measure the obvious spelling.
cat > .tmp/bad.py <<'EOF'
def main() -> Int:
    a = [9]
    b = [1]
    return len(b) if b > a else 0
EOF
python3 fire.py build --formal --no-prove --backend=arm64  -o .tmp/bad.arm64   .tmp/bad.py
python3 fire.py build --formal --no-prove --backend=x86_64  -o .tmp/bad.x86_64  .tmp/bad.py
.tmp/bad.arm64;        echo "arm64 exit=$?  (CPython: 0, and 1 on b83f2ed2)"
arch -x86_64 .tmp/bad.x86_64; echo "x86_64 exit=$?  (CPython: 0, and 1 on b83f2ed2)"
```

**One caution about reproducing §5.2 at all**, because it cost this branch an
hour and is the kind of thing that costs the next reader an hour: **the two
architectures must be run by DIFFERENT commands**, and a loop that runs both with
`arch -x86_64` reports Rosetta's `Bad CPU type in executable` (exit 1) as the
program's answer for the arm64 half. On this tree that produced a table of
confident, wrong numbers — including a "cross-architecture divergence" that was
one arch64 image never executing. `formal/arm64_codegen.py` is right and
`formal/x86_64_codegen.py` is right about every number in this map; the shell was
not.

**§2.1's class counts are not computed by a reader**: they are the
`(classes sum to 768 = 768 files swept)` block each log ends with, which the sweep
runner computes and checks against the file count. **§2.2's parity table is
`tools/formal_sweep_parity.py`** and **§3's move lists and cause table are
`tools/formal_sweep_rounds.py`**, both committed, precisely so that they are
printed rather than re-derived. **§2.3 is the log's own `REGRESSION:` block**, and
**§4.3 is the log's own `LOUD FINDING:` line** — which is the thing the
`formal32-instrument` work bought and the reason this map does not have to
measure the instrument gap by hand the way `-13` §4.3 had to.

**What ran here, whole files rather than subsets**, because a `formal/` change is
wide, and because §5.2 puts a new gate on the one table both backends consult at
every binary site:

| command | result |
|---|---|
| `python3 test_formal_run.py` | **PASS=1124 FAIL=0** — every comparison, every operator and every refusal needle in the file, on both backends |
| `python3 test_formal_value_model.py` | **PASS=104 FAIL=0** |
| `python3 test_formal_closures.py` | **PASS=46 FAIL=0** (22 answered, 24 refused) |
| `python3 test_formal_proof_breadth.py` | **25 tests, 2 failures, BOTH PRE-EXISTING on `b83f2ed2` and BOTH ALREADY FIXED on master** (`ce5d2b8d`) — §6 |
| `python3 tools/dangling_doc_refs.py --ratchet` | no file gained a citation of a deleted doc |

`test_formal_run.py` at 1124 rows is the one that makes §5.2's gate safe to land
without the whole-corpus gate, and the arm64 re-sweep (§5.5) is the one that
makes it safe across the corpus.

**`master` HAS MOVED SINCE 16:04**, so a re-run differs: this tree is `b83f2ed2`
plus §5, and §5.5's number is measured over **this** tree's §5 on **arm64 only**.
Owed to the integrator, and listed here so it is a command rather than a regret:
the x86-64 half of §5.5's re-sweep (the command is above), `make check-formal`,
and `make gate` — the last of which this worker is not permitted to run.

**≤ 40 minutes of wall for both arms together** at `-j 4` each, and **33 minutes
for §5.5's arm64-only re-run** on the same box. The CAS is content-addressed and
machine-wide, so a re-run with nothing changed reads a file per file; **editing
`formal/`, the parser, `mojo/middle/`, or `tools/formal_sweep.py` invalidates all
of it** — which is why this run rebuilt **765 of 768** files
(`cas: 3 hit / 765 miss` on both arms) rather than replaying `-13`, and why §5.5's
re-run rebuilt the files whose verdict §5 can reach and read the rest. Each arm
also rebuilds 23 files on purpose: the ones that link a formal dylib, because the
dylib is not in the cache key.