# FORMAL_sweep_work_map_2026-10-04_b12: a fresh, complete sweep of this repository and the stdlib, both architectures — and a 229-file regression, named

**Claim** `sweep30:sweep-b12` on `work/formal30-sweep-b12`. **This tree is
`master` at `77b24183`** — the commit the branch was cut from, and `master..HEAD`
was empty when the sweep launched at 22:36, so **every number here is a
measurement of `77b24183` and of nothing else.** **`master` has since moved 8
commits, and 5 of them are `formal/` changes plus two test files**, so a re-run
on today's master is expected to differ — §6 says which way and why. Both arms ran
to completion over the whole **735-file** scope with **no file left
unclassified** and **no `tool` row**, so every number is over the whole scope and
every file has a verdict.

Five things a reader should take away, in the order they matter:

* **This round is a REGRESSION, and it is one sentence in one module.**
  Passes fell **145 → 131**, coverage **28.8 % → 21.7 %**, and
  `codegen/dependency` rose **270 → 430**. **229 of the 430 are refused in a
  single module** — `formal/hostmods/os/_syscalls.mojo`, which **passed at `-11`
  and is refused now** — on a refusal that has **no row in either ranking
  instrument**, so the corpus's largest row is `other refusal` at **236 files**,
  the bucket `tools/formal_sweep_causes.py`'s own module docstring defines as
  *"nobody has looked"* (§3.1, §5).
* **The mechanism is a DOCSTRING.** `_syscalls.mojo`'s 31 non-ASCII string
  literals are **31 docstrings and not one value**, and six lines of em-dash
  prose added to them since `-11` made `formal/model.py`'s TEXT ENCODING scan
  refuse every `s[i]`, `len(s)` and `printf("%<w>s", s)` in the module — and so in
  **229 files** whose import closure reaches it, including **106 files that were
  on a named row one round ago** (§3.2, §3.3).
* **Zero files were fixed.** `to a pass` is **0**. All **244** files that moved
  did one of five things: **13** entered the scope, **18** were hostmods that
  **built at `-11`** and stopped building, **110** had a refusal land in front of
  them, **101** crossed into a codegen class (**100 in `_syscalls.mojo`**) and
  **6** crossed the other way. This is the third round running to record that
  shape, and the first where the wall is one edit old and one predicate wide.
* **The host-module work landed and it is real: 88 files left
  `not-answerable/host-import`, and 99 of them became codegen findings** —
  `importlib 90 → 28`, `itertools 14 → 3`, `copy 13 → 5`, `signal 7 → 0`, and
  `argparse`/`ast`/`fcntl`/`glob`/`html`/`platform`/`posixpath`/`re`/`shlex`/
  `shutil`/`stat`/`struct`/`tempfile`/`textwrap` models all landed (§2.3).
  **100 of the 101 files that crossed into a codegen class are on the
  `_syscalls.mojo` wall**, which is why the coverage rate fell while the
  capability rose — so §2 prints both, and §5 removes the wall they landed on.
  **The capability and the regression are the same files** (§3.4).
* **The two architectures are the same sweep, exactly, for the sixth round
  running.** All **604** classified paths have the same class on x86-64, there
  is no x86-64-only row, no arm64-only row, and **not one classified path has a
  changed REASON** (§2.2). The two arms' ranked-cause tables differ in exactly
  one line, and it is which file the tool happened to print as a row's example.

**§5 is the branch's own change, and it is measured**: the model no longer
publishes a docstring as a non-ASCII string value, which **removes the wall
behind all 229 of the row's files** rather than moving it — §5.3 measures 8 of
them building, 4 landing on rows this map already names, and all 6 sampled of
the 106 dark files returning to the row `-11` measured them on — and the refusal
that built the wall has a row in **both** ranking instruments instead of being
236 files of `other refusal`.

---

## 1. The run

### 1.1 The commands, and how long they took

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86-12 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-12.txt 2>&1 &
python3 tools/memslot.py --gb 8 --label sweep-arm-12 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-12.txt  2>&1 &
```

Launched 22:36:51; both summary blocks were on disk by 23:12, so **≤ 36 minutes
for both arms together** at `-j 4` each — eight concurrent builds on an
eighteen-core box that started the run at **load 16.3** and ended above 19.
`-11`'s 26 minutes was at load 8.8, so the difference is the machine, not the
tool. No wait on either per-architecture `flock` (`formal_sweep.py` keeps one per
arch, plus a separate `cas/formal-imports/<arch>/`), so both arms started
together: no sibling worker held either lock and `--allow-concurrent` was not
needed and would have been the wrong answer anyway.

Both arms **exit 1**, which is right: the run has real findings, and each log's
`memcap:` line says `child exit 1`. **`memcap` never breached — peak 0.9 GB
(arm64) and 0.8 GB (x86-64) across up to 16 and 17 processes** against the 8 GB
reservation, on either arm.

The interpreter is not optional
(`bugs/INFRA_bare_python3_is_3_9_and_the_formal_backend_needs_3_10.md`):
`export PATH=/opt/homebrew/bin:$PATH` first, or the tool refuses to start with a
diagnosis rather than a wait.

### 1.2 Scope: 735 files, +13

This worktree's own **483** `*.py`/`*.mojo` plus the **252** under
`../new-modular/Mojo/stdlib/std`. The repository has grown from 470 to 483 since
`-11`, and **all 13 new files are accounted for** (§2.4). Nine of the 13 print a
row and four pass; only 3 of the 9 are codegen findings, and all 3 are on the
regression's wall — which is why a +13 scope is not what moved this round.

### 1.3 No `tool` row at all, for the third round running

`-10` was the first round in this series with an empty `tool` class and `-11`
kept it. **All 735 files have a verdict on both architectures.**

---

## 2. Class counts

### 2.1 Against `-11`

Left column: `-11`'s summary block (`…_b11.md` §2.1). Right column: this run.

| class | **`-11`** | **`-12`** | Δ |
|---|---|---|---|
| **pass** | 145 | **131** | **−14** |
| built-with-admitted-contracts | 4 | 2 | −2 |
| **codegen** (a refusal IN this file) | 84 | **42** | **−42** |
| **codegen/dependency** (refused in a module it imports) | 270 | **430** | **+160** |
| not-answerable/host-import | 203 | **115** | **−88** |
| not-answerable/unresolved-import | 11 | 10 | −1 |
| not-answerable/target-limit | 5 | 5 | 0 |
| not-answerable/system-module-call | 0 | 0 | 0 |
| **backend-crash** | 0 | **0** | **0** |
| **tool — no verdict at all** | 0 | **0** | **0** |
| **files swept** | 722 | **735** | +13 |
| codegen findings (`codegen` + `codegen/dependency`) | 354 | **472** | +118 |
| **codegen coverage** | 145/503 = **28.8 %** | 131/605 = **21.7 %** | **−7.2 pp** |

**`codegen` fell 84 → 42, and that is not a fix either — it is the wall.** Of the
42 files the sweep now calls `codegen`, **40 were `codegen` at `-11`**, one was
`not-answerable/host-import` and one passed; so the class did not shrink by
fixing anything, it shrank because a refusal landed in front of 42 files *in
modules they import* and a refusal in a module you import is `codegen/dependency`
by definition. §3.4's 100 class-crossings are the same event seen from the other
side.

**`built-with-admitted-contracts` fell 4 → 2, and that IS the host-module work
landing — and losing two modules.** The four are
`formal/hostmods/{concurrent/futures,ctypes,subprocess,threading}.mojo`, and
`concurrent/futures` and `subprocess` still build on their declared contracts
while **`ctypes` and `threading` are now `codegen/dependency`, both refused in
`_syscalls.mojo`**. A module that built under an admission now does not build at
all, which is a regression wearing the costume of a reclassification.

### 2.2 arm64 vs x86-64: **zero** architecture-dependent verdicts, and zero changed reasons

`python3 tools/formal_sweep_parity.py bugs/sweeps/sweep-arm-12.txt bugs/sweeps/sweep-x86-12.txt`

| | this run | `-11` |
|---|---|---|
| paths classified on both | **604** | 577 |
| **of those, class CHANGED** | **0** | 0 |
| x86-64-only rows (a pass on arm64) | **0** | 0 |
| arm64-only rows (a pass on x86-64) | **0** | 0 |
| class counts that differ | **none** | none |
| **of those, REASON CHANGED** | **0** | 0 |

Sixth round running with nothing to explain, and this is the second with **zero
REASON CHANGED** — `-10`'s single one was an architecture's own name inside a
mangled dylib filename, and `-11` recorded that the case no longer arises. In
735 files the two architectures produce the same verdict *and the same sentence*
for every single one.

The two arms' `formal_sweep_causes.py --min 3` tables are byte-identical except
for **one line**: which file each tool happened to print as a row's `example:`.
The two arms sweep concurrently, so rows arrive in a different order and
`rank()` keeps the first example it saw. That is a property of the reader, not a
divergence in the backend.

### 2.3 `not-answerable/host-import` fell by 88, and that is the round's real capability gain

By first host module named:

| module | `-11` | `-12` | Δ |
|---|---|---|---|
| `importlib` | 90 | **28** | **−62** |
| `collections` | 29 | 22 | −7 |
| `unittest` | 16 | 17 | +1 |
| `itertools` | 14 | **3** | −11 |
| `copy` | 13 | **5** | −8 |
| `signal` | 7 | **0** | −7 |
| `random` | 5 | 8 | +3 |
| `importlib.util` | 4 | 5 | +1 |
| `inspect` | 4 | 5 | +1 |
| `atexit`, `glob`, `re`, `shlex`, `stat`, `textwrap`, `struct`, `tempfile`, `html`, `posixpath`, `argparse`, `ast`, `fcntl`, `platform`, `shutil`, `plistlib`, `pwd` | 0 | **0** | hostmod models landed |

The reach split moves with it: **75 in reach / 128 not** at `-11` → **53 in reach
/ 62 not** at `-12`. `formal/imports.py` owns that split and it is read, never
copied, so this is a fact about the target computed at run time.

**Every file that left this class became a codegen finding, and 100 of the 101
are on the regression's wall.** Measured per file rather than inferred from two
class counts:

| crossed INTO a codegen class | n | refused in |
|---|---|---|
| `not-answerable/host-import` → `codegen/dependency` | **98** | `_syscalls.mojo` |
| `not-answerable/host-import` → `codegen` | **1** | (this file) |
| `built-with-admitted-contracts` → `codegen/dependency` | **2** | `_syscalls.mojo` |
| | **101** | **100 in `_syscalls.mojo`** |

**and 6 crossed the other way**, which §2.4 lists. A file that stops being a fact
about the target and becomes a finding is capability arriving; §3.4 is the bill
for it, and the two are the same 99 files.

### 2.4 The 13 new files, and the 19 hostmods that stopped building

**The 13 new files** (`formal_sweep.py`'s own `find_source_files`, diffed
against `git ls-tree 65b88dab`): `formal/examples/neg.mojo`,
`formal/hostmods/{operator,signal,traceback}.mojo`, `formal/x86_64_model_fuzz.py`,
`test_formal_doc_truth.py`, `test_formal_frame_slot_subscript_census.py`,
`test_formal_hostmods_conformance.py`, `test_formal_per_struct_asks.py`,
`test_formal_unicode.py`, `tools/formal_frame_slot_subscript_census.py`,
`tools/formal_model_fuzz.py`, `tools/formal_untyped_param_deref_census.py`.
483 = 470 + 13, which is the whole of the scope delta. **Nine of the 13 print a
row and four pass; 3 of the 9 are codegen findings and all 3 are on the wall.**

**Of the 27 files that print a row now and printed none at `-11`, 13 are the new
files above and 14 were files that existed and are printed now.** A pass prints
no line, so for 14 of them the only way a log can say what happened is that the
row appeared; §3.4's partition is where those 14 are counted. And the same is
true one layer out — **19 `formal/hostmods/**` files that existed at `65b88dab`
build now and are refused now, and 18 of the 19 are refused in
`_syscalls.mojo`**, the nineteenth being `_syscalls.mojo` itself:

| | n | at `-11` |
|---|---|---|
| refused in `_syscalls.mojo` now, that **passed** at `-11` | **16** | a pass, printed nothing |
| refused in `_syscalls.mojo` now, that was `built-with-admitted-contracts` | **2** | `ctypes.mojo`, `threading.mojo` |
| refused in itself | **1** | `_syscalls.mojo` |

The 18 are `argparse`, `ast`, `ctypes`, `fcntl`, `glob`, `html`, `os/__init__`,
`os/path/__init__`, `platform`, `posixpath`, `re`, `shlex`, `shutil`, `stat`,
`struct`, `tempfile`, `textwrap`, `threading` — checked by **refusing module**,
not by reading the class, because the class cannot tell "refused" from "refused
somewhere further in".

**And 6 files changed class the other way**, which no previous map recorded
because no previous map had a tool that could print it: `codegen/dependency →
not-answerable/host-import` ×2, `not-answerable/unresolved-import →
not-answerable/host-import` ×2, `codegen → not-answerable/host-import` ×1, and
`not-answerable/host-import → not-answerable/unresolved-import` ×1. Those are
files a landed hostmod model made *answerable* in the sense that the refusal
moved one layer further out — a reclassification, not a regression, and worth
seeing in a table rather than inferred from two class counts.

---

## 3. The per-CAUSE delta: **244 of 604 files moved, and 0 of them got fixed**

Class counts move 244 files. In the vocabulary of *causes* —
`tools/formal_sweep_causes.py`'s per-file label, keyed on what a fix would have to
CHANGE — **110 files changed cause**, 107 crossed a class and 27 entered the
scope. **Not one of the 244 got fixed.** Three of the four biggest numbers are
one sentence.

| move | n | from → to |
|---|---|---|
| **a refusal landed IN FRONT of them** | **110** | string composition x106, module ATTRIBUTE x2, handler arm x1, `other refusal` x1 → **`other refusal`** (§3.2) |
| **entered the scope** (13 files, 9 of which print) | **13** | not in `-11` at all → a row in `-12` |
| **a hostmod that built at `-11` stopped building** | **18** | `formal/hostmods/**` → `_syscalls.mojo` (§2.4, §3.2) |
| **crossed INTO a codegen class** | **101** | `host-import` x99, admitted x2; **100 in `_syscalls.mojo`** (§2.3) |
| **crossed the other way** | **6** | into `not-answerable/*` (§2.4) |
| **a file that got fixed** | **0** | — |

### 3.1 `other refusal` is 6 → 236, and **229 of the 236 are one module**

| | `-11` | **`-12`** |
|---|---|---|
| rank 1 | 148 `a call to a name the defining module does not export` | **236 `other refusal`** |
| rank 2 | 115 `string composition: nothing to compose into` | 148 (same) |
| rank 3 | 59 `module exports no public functions` | 59 (same) |
| rank 4 | 6 `variadic call has no ABI` | 115 `string composition: nothing to compose into` |
| rank 5 | 4 MLIR dialect construct | 6 (same) |
| rank 6 | 4 a module's ATTRIBUTE read as a value | 6 (same) |
| **`other refusal`** | **6** | **236** |
| causes that fire on this corpus | 17 | **17** |

Grouped by the module that refused (`uses:` is the tool's own column):

| refusing module | files | `uses:` | reading |
|---|---|---|---|
| **`_syscalls.mojo`** | **229** | **0 of 229** name anything it declares (`_put_le64`, `_put_time`) | **closure — see §3.2** |
| `(this file)` | 7 | — | six distinct constructs, named at the end of §4.2, plus `_syscalls.mojo`'s own |

**`other refusal` is the bucket `formal_sweep_causes.py`'s module docstring
defines as *"nobody has looked"*.** It held 6 of `-11`'s 354 findings and holds
**236 of `-12`'s 472 — 50 % of every codegen finding in the corpus** — and the
reason it grew by 230 is that the refusal that caused it has **no row in
`CAUSES` and no row in `tools/formal_sweep.py`'s `_REFUSAL_FAMILIES`**. Both are
keyed on different things — what a fix would have to CHANGE versus the shape of
the message — so **both** needed the row, which is the same two-part argument
`…_b11.md` §5.1 made for the f-string refusal three days ago. §5 does it.

### 3.2 The mechanism is a docstring, and it is six lines of prose

`formal/hostmods/os/_syscalls.mojo` **existed at `65b88dab` and PASSED there**;
`git log 65b88dab..HEAD -- formal/hostmods/os/_syscalls.mojo` shows three
commits landing since, one of them a merge of `work/formal26-hostmods-wave4`,
and the diff adds **6 lines of docstring prose containing em-dashes**. The module
has **31 non-ASCII string literals and every one of them is a docstring** —
measured, by asking the repository's own scanner:

```
$ python3 -c '… M.non_ascii_strings_in(I.module_statements(path))'
non-ascii literals: 31
   'The value of the kernel string MIB `name`, or `""` if there is no such.\n\n…'
   "Field `field` of `uname(3)`, in a `malloc`'d copy the caller owns.\n\n…"
   …
```

Not one of the 31 is a value: they are function docstrings whose prose contains
an em-dash or a `§`. And `formal/model.py`'s TEXT ENCODING block publishes every
non-ASCII literal in a unit into `_NON_ASCII_STRINGS`, then
`string_element_refusal` answers every `s[i]` with

> *This image holds a string literal that is not ASCII, so some string in it can
> have a character `base + 1` walks into.*

…because its own docstring says the condition that clears it is *"no literal with
a byte >= 0x80 anywhere means no string in the image can have one"*. And a
docstring's bytes cannot be such a string, because **nothing can name it**:
`__doc__` is on `model._UNRESOLVED_NAME_ALLOWED`, so a read of `f.__doc__` is
materialised from that table rather than read out of the literal, and no other
spelling binds it. The scan was counting a value that is not a value, and the
counting is *conservative in the direction that costs 229 files*.

Reproduced in eight lines, with no hostmod involved:

```
$ cat .tmp/ascii/t_doc.mojo
"""A module docstring with an em-dash — and a section sign §."""

def first(s: String) -> Int:
    """A function docstring — with prose."""
    return s[0]

$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/ascii/t_doc .tmp/ascii/t_doc.mojo
build: s[0] is refused on a string whose text is not ASCII. […]
memcap: done, peak 0.0 GB (ceiling 8.0 GB), child exit 1
```

**And it is not that a docstring is dropped — it is that it is unreachable**,
which is the distinction the fix turns on. Measured: a FUNCTION docstring's
bytes *do* reach the image (`ZZFNDOCPROBEZZ` appears once in a built image whose
module docstring's `ZZDOCSTRINGPROBEZZ` appears zero times), so "it is not
emitted" would be the wrong argument. The right one is reachability, and
`publish_non_ascii_strings`'s own docstring already argues it in the correct
terms: *"a string one module interns is a value another module can hold"*. A
docstring is not one.

**The bill for this, per module, is in the log's own breakdown** — which is why
this was findable at all:

```
codegen/dependency by family: _syscalls.mojo: other refusal x229, …
```

229 of the 430 `codegen/dependency` findings — **53 %** — are one module.

### 3.3 **106 files went dark**, and they are the whole of a named row

`tools/formal_sweep_rounds.py`'s from→to matrix, verbatim:

```
WHERE THE FILES WENT, per cause that lost any (a file that moved to
another cause is not a fix):
  string composition: nothing to compose into  (106 file(s)):
        106 -> other refusal
  a module's ATTRIBUTE read as a value, across a dylib boundary  (2 file(s)):
          2 -> other refusal
  other refusal  (1 file(s)):
          1 -> other refusal
  a handler arm with a body (no unwinder to emit it into)  (1 file(s)):
          1 -> other refusal
```

**All 106 are refused in `_syscalls.mojo`** — checked by refusing module, not by
the destination label, because `other refusal` is the destination for all of them
and a reader needs to know it is one module and not 106 different constructs.

So: the string-composition row — the corpus's **rank 2** row at 115 files, the
subject of `…_b11.md` §5 and of `FORMAL_string_composition_has_no_buffer` —
fell **115 → 6**, and **not one of the 109 that left it was fixed**. 106 went
behind the docstring wall, 2 behind the same one by way of module state, and 1
was re-wrapped by `platform.mojo`'s own refusal. **This is the answer to "which
rows went dark rather than getting fixed" for round 12: one row, 109 files, one
module.**

### 3.4 The other direction: where the 236 came from, and 229 of them are one wall

```
AND WHERE THEY CAME FROM, per cause that gained (a refusal landing in
front of a row moves files INTO the row in front):
  other refusal  (+110):
        106 <- string composition: nothing to compose into
          2 <- a module's ATTRIBUTE read as a value, across a dylib boundary
          1 <- other refusal
          1 <- a handler arm with a body (no unwinder to emit it into)
```

**The other 126 did not change cause at all**, so the matrix above cannot see
them — they arrived as a `codegen/dependency` from a class that is not a codegen
class, or from outside the scope. Classified by refusing module, which is the
half a cause table cannot give (the 236 as swept, against the `-11` log):

| how it arrived | n | refused in |
|---|---|---|
| a refusal landed **in front of it** (§3.3) | **110** | `_syscalls.mojo` |
| crossed a **class** into `codegen/dependency` | **100** | `_syscalls.mojo` |
| existed at `65b88dab` and **passed at `-11`** | **16** | `_syscalls.mojo` |
| genuinely **new in the scope** | **3** | `_syscalls.mojo` |
| genuinely new in the scope | 1 | (this file) |
| a refusal landed in front of it | 5 | (this file) |
| crossed a class | 1 | (this file) |
| | **236** | **229 in `_syscalls.mojo`**, 7 in-file |

**So 229 of the 236 are one module refusing a file it refused nothing in at
`-11`, and 7 are the six distinct in-file constructs of §4.2 plus
`_syscalls.mojo`'s own.** The capability that landed this round (§2.3's 88
host-import files, and §2.3's 100 class-crossings into a codegen class) and the
regression that landed with it are **the same files seen from two ends** — which
is the most useful sentence in this section, and invisible in a class table,
where those 99 files read as "capability arrived" in one row and "passes fell"
in the adjacent one.

**Both halves are printed by one command**, because "a row fell" and "a row grew"
are the same event read from two ends, and only one of them is visible in a
counts table.

---

## 4. Ranked causes, and the next step per row

`python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-12.txt` — and
the x86-64 arm prints the same table with the same numbers (§2.2).

**FILES BLOCKED IS AN UPPER BOUND**: a file's terminal cause is the first refusal
its build walk reaches, so fixing one moves the file to the next with the count
unchanged. §5 measures that bound for this round's largest row.

| files | `-11` | in-file | cause | refused in | owner / next step |
|---|---|---|---|---|---|
| **236** | 6 | 7 | **`other refusal`** — §3.1's one sentence | **`_syscalls.mojo` x229**, (this file) x7 | **§5** — unclaimed, and this branch's |
| **148** | 148 | 15 | a call to a name the defining module does not export | `std.format._utils` x105, `std.memory.alloc` x28, `std.bit.mask` x8, … | **claimed** (`formal23-1`); unmoved for a third round, and `uses:` is 39 of 105 / 6 of 28 / 1 of 8 |
| **59** | 59 | 0 | a module that exports nothing cannot be a dylib | `constants.mojo` x33, `_io.mojo` x23, `_select.mojo`, `_unicode_lookups.mojo`, `stat.mojo` | **claimed** (`formal16-2`); `-11` §4 measured the constants-only family as permanent |
| **6** | 6 | 1 | variadic call has no ABI | `tile.mojo` x5, (this file) x1 | `FORMAL_a_variadic_parameter_read_has_no_abi.md`, claimed (`formal28-2`). `-11` §4.4 measured that a variadic parameter's value is **not knowable**, and that the cheap lowering answers wrong-but-exit-0 |
| **6** | 115 | 5 | string composition: nothing to compose into | (this file) x5, `cas.py`, `module_loader.py`, … | **claimed** (`formal25-5`); §3.3 is what happened to its other 109 |
| **4** | 4 | 3 | MLIR dialect construct | (this file) x3, `function.mojo` x1 | `FORMAL_mlir_dialect_refusal_is_false_of_the_word_valued_ops.md`, claimed (`formal29-2`) |
| **2** | 4 | 2 | a module's ATTRIBUTE read as a value, across a dylib boundary | (this file) x2 — `t_argv.mojo`, `unescape_c.py` | `FORMAL_module_state_no_storage.md`, claimed (`formal29-3`) — an ABI project (§(2)) |
| 2 each | | | method call on a value receiver; `Optional unwrap` | | §4.1 |
| 1 each | | | **7** further single-file causes | | §4.2 |

**Ownership is read from `tools/control.py claims`, not from the `-11` map**,
because two rows the `-11` map recorded as unowned have since been claimed:
`formal28-2` took the variadic row and `formal29-2`/`formal29-3` took the MLIR
and module-ATTRIBUTE rows. **The only large unowned codegen cause in the corpus
is §3.1's, and it is this branch's.**

**One row lost 2 of its 4 files to the regression, which a counts table shows as
`4 → 2` and nothing else:** the module-ATTRIBUTE row is 2 files here and was 4 at
`-11`; `tools/detach.py` and `tools/gatewatch.py` left it for
`_syscalls.mojo`, and **nothing joined it**. `t_argv.mojo` — the `sys.argv` file
`-11` §4 singled out as the row's most interesting member — is still in it, and
`unescape_c.py`'s `sys.stdin` joined it at some point in between.

**And the two are not the same case, which is the useful part.** With the fix in,
`tools/detach.py` is **back on this row** (its own `sys.argv` read). 
`tools/gatewatch.py` is **still refused — on the encoding block, and now
correctly**: it has a real non-ASCII string *value* of its own,
`'STUCK (>60 min) — needs help'` (measured, after the fix:
`non_ascii_strings_in` finds **1** for `gatewatch.py` and **0** for
`_syscalls.mojo`, which had 31). So §5 does not put that file back and does not
claim to: it moves it from a shrug to a named row with a real cause, which is the
difference between "nobody has looked" and "here is what is in the way".

### 4.1 The two 2-file rows

* **method call on a value receiver** — `std/collections/binary_heap.mojo`'s own
  `self.clear()` and `std/format/repr.mojo`'s: one stdlib file's own source each,
  and the stdlib is not editable from a repository worktree. (`-11` §4.1 named
  `float_literal.mojo`'s `write_repr_to` as the second; it is not in this row now.)
* **`Optional unwrap`** — `std/collections/set.mojo` and
  `std/memory/owned_pointer.mojo`, **both refused in `builtin_slice.mojo`**, which
  is the same two files `-11` §3.4 recorded as this row coming back.
  `FORMAL_optional_needs_a_niche.md` is **claimed** (`formal29-3`).

### 4.2 The seven single-file causes

Seven rows of one file each, every one a distinct construct and every one in the
file's own source:

| file | construct |
|---|---|
| `std/benchmark/compiler.mojo` | `inlined_assembly['', NoneType, 'r,~{memory}', True]` — a subscript whose index is a TUPLE |
| `std/builtin/len.mojo` | a `` `...` `` body standing where the lowering needs instructions |
| `std/builtin/none.mojo` | `writer.write_string()` — a method on a multi-field struct where a descriptor is meant |
| `std/math/polynomial.mojo` | `comptime num_coefficients = ...` does not fold to a constant |
| `mojo/middle/metal_ops.py` | `c_ctype.rstrip()` returns a SHORTER string — `LENGTH_DEPENDENT_METHODS` names the fix's shape |
| `t1.mojo` | `sys.exit()` — a call into a linked module that does not export the name, **deliberately not taken**, because `formal/hostmods/sys.mojo`'s own docstring and `test_formal_sys.py` both pin `doc/ABI.md`'s rule that a C library name like `exit` is provided by libSystem |
| `test_llm/dumb_gemm.mojo` | `[FloatLiteral] * m * k` — a repetition whose count this path cannot read |

**None is a shared-backend patch**, and none is in a claim. **A eighth is filed
rather than listed here**, because it is not a refusal at all: §3.1's in-file
`other refusal` set contains `test_formal_libc_symbol.py`, whose message is
`parse error: …:483:23: unterminated string literal` — `fire_compiler.py`'s
tokenizer refusing a PEP 701 f-string whose replacement field spans **lines**.
Measured over six shapes: a nested same-quote f-string parses, a multi-line
replacement field and a comment inside the braces do not. One file in the corpus,
a parser change rather than a formal one, filed that round under its own doc
with its own reproduction and next step (that doc is deleted with its fix).
**FIXED 2026-10-05** on `work/formal32-sweep-b13`;
`bugs/FORMAL_sweep_work_map_2026-10-05_b13.md` §5 is the record and
`test_string_literal_lexing.py`'s `LITERALS` block is the test.

---

## 5. What this branch changed, measured

Three commits on top of `master` at `77b24183`: this map and the two logs; the
round-over-round tool; and the fix below. **The fix is in `formal/model.py`'s
TEXT ENCODING scan and in the two instruments that RANK refusals, not in either
backend**, and it is measured on both sides.

### 5.1 The fix, in the model

`formal/model.py::non_ascii_strings_in` no longer descends into a bare string
`ExprStmt`. The predicate is a new **named** function,
`formal/model.py::is_docstring_statement`, and it is named rather than inlined
because **`module_body` already asked the same question** — its own block comment
says *"a module DOCSTRING — a bare string `ExprStmt` — is not body"* and its loop
tested for it inline. Two answers to "is a bare string statement a value on this
path" is how 229 files came to be refused over six lines of em-dash prose, so
`module_body` now calls the same function and there is one answer.

**THE ARGUMENT IS REACHABILITY, NOT "IT IS NOT EMITTED",** and the difference is
measured: a FUNCTION docstring's bytes **do** reach the image (`ZZFNDOCPROBEZZ`
appears once in a built image whose module docstring's `ZZDOCSTRINGPROBEZZ`
appears zero times). What makes a docstring not a value is that nothing can name
it — `__doc__` is on `_UNRESOLVED_NAME_ALLOWED`, so a read of `f.__doc__` is
materialised from that table rather than read out of the literal — and
`publish_non_ascii_strings`'s own docstring already argues the block in exactly
those terms: *"a string one module interns is a value another module can hold."*

The predicate is deliberately the **wide** test (any bare string statement, not
only a body's first), because a bare string expression statement is discarded on
every path, so there is no spelling in which it holds a value; a narrow
"first statement of a body" rule would be a second answer with a case the wide one
does not cover. And the exclusion is three lines rather than a flag, because
`ExprStmt`'s only fields are `value`, `line` and `col` — there is nothing else in
it to descend into.

**IT IS NOT OVER-BROAD.** A real non-ASCII value still publishes and still
refuses, on both architectures:

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/ascii/t_real .tmp/ascii/t_real.mojo
build: len(tagged(...)) is refused: on this path it would answer in BYTES where CPython answers in CHARACTERS. […]
$ … --backend=x86_64 …
build: len(tagged(...)) is refused: on this path it would answer in BYTES where CPython answers in CHARACTERS. […]
```

(CPython prints 5 there and the byte count is 6, so the refusal is right.) And an
all-ASCII image builds and answers CPython: `s = "hi"; printf("[%c][%c]", s[0],
s[1])` prints `[h][i]` on arm64, identically.

### 5.2 The fix, in both ranking instruments

The refusal that caused the regression had **no row in `CAUSES` and none in
`_REFUSAL_FAMILIES`**, so 229 files read as `other refusal` — the bucket both
tools define as *"nobody has looked"*. The two tables are keyed on different
things (what a fix would have to CHANGE versus the shape of the message), so
**both** needed the row, which is the same two-part argument `…_b11.md` §5.1 made
for f-strings.

The row is **`a non-ASCII string: BYTES where CPython has CHARACTERS`**, with
**two alternatives**: `codepoint_refusal` and `printf_text_width_refusal` /
`printf_text_conversion_refusal` all quote one clause (`is refused: on this path
it would answer in BYTES where CPython answers in CHARACTERS`) and so are one
alternative covering three constructs, and `string_element_refusal`'s wording
(`is refused on a string whose text is not ASCII`) shares none of it.

| | `-12` as swept | **`-12` with §5.2's row** |
|---|---|---|
| rank 1 | **236 `other refusal`** | **230 `a non-ASCII string: BYTES where CPython has CHARACTERS`** |
| rank 2 | 148 `a call to a name the defining module does not export` | 148 (unchanged) |
| rank 3 | 115 `string composition: nothing to compose into` | 59 `module exports no public functions` |
| `other refusal` | 236 | **6** |
| the log's own by-family breakdown, `other refusal` (both codegen classes) | **388** | **158** |
| causes that fire on this corpus (of 66 in the table) | 17 | **17** |

The row **stays**: the refusal is CORRECT for a real non-ASCII value, and a queue
that emptied this row by deleting it would be reading a fix as a closure.

### 5.3 The ceiling, measured — and it removes the wall rather than moving it

**15 of the 229 probed, one build command each**, sampled across the row rather
than taken from one corner — and the point of the sample is the column on the
right, not the number that pass:

| file | what it lands on with the fix |
|---|---|
| `formal/hostmods/os/_syscalls.mojo` | **`pass`** |
| `formal/hostmods/ast.mojo` | **`pass`** |
| `tools/detach.py` | the module-ATTRIBUTE row — **back where `-11` had it** |
| `_ab.py` | `not-answerable/host-import` — `atexit`, a fact about the target |
| `std/builtin/float_literal.mojo` | its own in-file refusal (`__int_literal__().__int__(…)`) |
| `std/collections/type_dict.mojo` | its own in-file refusal (`comptime` off a type parameter) |
| `std/algorithm/backend/tile.mojo` | the variadic-ABI row |
| `std/_gpu/__init__.mojo` | the export-gate row |
| `type_system.py` | the string-composition row — **back where `-11` had it** |

**And the 106 files that went dark go back where they were.** Six sampled from
the 106, all six landing on the f-string refusal `-11` measured them on:
`cas.py` and `checked_run.py` and `comptime.py` on `cas.py:451`,
`build_config.py` and `compile_stdlib.py` on `module_loader.py:108`,
`build_stdlib_dylib.py` through `cas.py`.

**Not one of the 21 sampled files lands on another encoding refusal** — 15 from
the table above plus these 6 — and that is the property that distinguishes
REMOVING a wall from moving it. It is the check a reader should make before
believing any row's count, and it is the one this map's own §3 exists to make
automatic.

**The one file of the 229 that stays on the encoding block after the fix is
`tools/gatewatch.py`, and it is worth naming because it is the case that proves
the exclusion is not a blanket amnesty** (§4). `_syscalls.mojo` itself goes from
**31** non-ASCII literals to **0**, which is the whole fix in one number.

### 5.4 It repairs a registered gate job, which is a second measurement

`python3 test_formal_sweep.py` was **127 tests with 1 ERROR** before this branch
and is **133 tests, 0 failures** after. The error was
`TestLibSystemBindSpelling.setUpClass`, which builds
`formal/hostmods/os/_syscalls.mojo` as its fixture and raised on the refusal —
so its six tests were never running, in a job the gate runs every time. The fix
is what makes them run again.

### 5.5 The tests, and what they prove

* **the model, at the scan** — `test_formal_unicode.py`'s image-scan section
  gains **8 checks**: a module docstring, a function docstring, a bare string
  statement that is *not* first, **a docstring beside a real non-ASCII value**
  (which must still publish — without that row the fix would also have silenced
  `printf("%s", "héllo")`, the opposite of what it is for), and the predicate
  asked directly three ways. **104 behavioural + 46 model checks, all PASS**;
  the 96 behavioural cases that were there before are unchanged, which is the
  proof the exclusion is narrow.
* **both tables' rows are reachable from a real message, and the samples are
  BUILT not copied** — `test_refusal_taxonomy.py`'s `_non_ascii_messages()`
  **calls** `model.string_element_refusal` (on a PARSED `s[0]`, because
  `spelled()` and `string_literal_text()` both read real node shapes and
  `SubscriptExpr`'s receiver is `obj`, not `base`) and
  `model.codepoint_refusal`, and **raises** rather than outliving either — the
  third built pair in that file and the third time that file's docstring's point
  3 has been the reason. The pair is in **both** tables (`SAMPLES` for the
  family, `CAUSE_SAMPLES` for the cause), because the two labels are spelled
  independently in two files and their drifting apart is the disagreement a
  reader of either has to be able to see. **269/269 checks, 45 families, 66
  causes.**
* **the round-over-round tool** — `test_formal_sweep.py::TestRoundOverRound`,
  9 checks, and the one that uses no fixture is
  `test_the_committed_rounds_reproduce_the_map_they_were_derived_from`, which
  asserts `…_b11.md`'s hand-computed §2.1/§2.3/§3 numbers against the committed
  logs.

```console
$ python3 test_refusal_taxonomy.py
refusal taxonomy: PASS (269/269 checks, 45 families, 66 causes)
$ python3 test_formal_sweep.py
Ran 133 tests in 13.867s
OK
$ python3 test_formal_unicode.py
formal unicode: model PASS=46 FAIL=0
formal unicode: PASS=104 FAIL=0
$ python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-12.txt | head -3
files in-file  cause
    230       1  a non-ASCII string: BYTES where CPython has CHARACTERS
    148      15  a call to a name the defining module does not export
```

### 5.6 What the fix does NOT claim

**`FILES BLOCKED IS AN UPPER BOUND` and this is where that bites.** §5.3 measures
15 files' worth of the 229 and says nothing about the other 214 — they move to
whatever is behind the wall, which for most of them is a row this map already
names. **The honest reading of §5.3 is "the wall is gone", not "229 files
recovered"**: on the evidence, 2 build, 3 land on rows this map already lists, 1
is a fact about the target, 3 are their own in-file refusals, and the 6 sampled
of the 106 dark files go back to the row `-11` measured them on. **A re-sweep is
the only way to price the other 214**, and §6 gives the command.

**And one file of the 229 stays on the encoding block after the fix, on purpose.**
`tools/gatewatch.py` has a non-ASCII string VALUE of its own —
`'STUCK (>60 min) — needs help'` — so `non_ascii_strings_in` still finds one
there while it now finds **0** in `_syscalls.mojo`, which had 31. That is the
case that proves the exclusion is a reachability test and not a blanket amnesty,
and it is why §4 records it separately: a file that stays refused for a real
reason, on a row with a name, is the outcome the other 228 are owed.

Also not claimed: the `s[i]` refusal's *other* half. `string_element_refusal`'s
docstring is explicit that "an index a KNOWN TEXT makes answerable is still not
answerable, because the obstacle is where the answer would live rather than what
it is" — a one-CHARACTER `str` is a new object and this representation has
nowhere to put one. That is the composition row's missing buffer, it fires for
ASCII text too, and nothing here touches it.

---

## 6. Reproducing this

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label sweep-x86-12 -- \
  python3 tools/formal_sweep.py -j 4 -t 120 --arch x86_64 > bugs/sweeps/sweep-x86-12.txt 2>&1
python3 tools/memslot.py --gb 8 --label sweep-arm-12 -- \
  python3 tools/formal_sweep.py -j 4 -t 120            > bugs/sweeps/sweep-arm-12.txt  2>&1

python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-arm-12.txt            # §2, §4
python3 tools/formal_sweep_causes.py --min 3 bugs/sweeps/sweep-x86-12.txt            # §4, the same table
python3 tools/formal_sweep_parity.py  bugs/sweeps/sweep-arm-12.txt \
                             bugs/sweeps/sweep-x86-12.txt                           # §2.2
python3 tools/formal_sweep_rounds.py  bugs/sweeps/sweep-arm-11.txt \
                             bugs/sweeps/sweep-arm-12.txt                            # §3
python3 test_refusal_taxonomy.py                                                       # §5
python3 test_formal_sweep.py TestRoundOverRound                                       # §5
python3 test_formal_sweep.py                # §5.4: 133 tests, and the 6 that now run
python3 test_formal_unicode.py                                                        # §5.5
```

**§2.1's class counts are not computed by a reader**: they are the
`(classes sum to 735 = 735 files swept)` block each log ends with, which the
sweep runner computes and checks against the file count. **§2.4's 19 and 5,
§3.3's 106 and §3.4's 110 are `tools/formal_sweep_rounds.py`**, which is
committed on this branch precisely so that they are printed rather than
re-derived: `…_b10.md` §6 and `…_b11.md` §6 each said in the same words that this
comparison should have become a tool rather than a fourth description of one, and
`test_formal_sweep.py::TestRoundOverRound` is its test. **§2.4's 13 new files are
`formal_sweep.py`'s own `find_source_files` diffed against `git ls-tree
65b88dab`, and §2.3's per-module host-import table is each log's own `by module:`
line.** **§3.2's 31 docstrings and the `ZZDOCSTRINGPROBEZZ` / `ZZFNDOCPROBEZZ`
measurement are three commands**, in §3.2 and §5.1. **§4.2's parse error is
the multiline-f-string lexing hole** — this front end refusing a PEP 701 f-string
whose replacement field spans lines — which had its own six-shape measurement
that round and is fixed; see
`bugs/FORMAL_sweep_work_map_2026-10-05_b13.md` §5.

**`master` HAS MOVED 8 COMMITS SINCE, so a re-run differs — and here is where.**
`git diff 77b24183..master` over the files this sweep sweeps:

| file | Δ | what it is |
|---|---|---|
| `formal/model.py` | 8 lines, **all of them comments** | a docstring rewrite naming `dict_literal_key_value_kind`. **The one file that decides every verdict is behaviourally unchanged**, which is why §2's numbers are still worth reading. |
| `formal/build.py` | +83 | a nested typed-frame improvement (`_typed_nested_frame` grows a frame holder through a `MemberExpr`), and `borrowed_structs` — a LIBRARY that applies another module's template instantiation now builds (`60c49ae7`) |
| `formal/imports.py` | +95 | the module-set side of the same two features |
| 2 test files, `tools/suite.py`, `test_suite.py`, `bugs/**` | — | not swept, or swept as a host-import row |

So the expected deltas on a re-run are the **export-gate / borrowed-template
rows** (`60c49ae7` makes `Pair[Int]()` written in an importing module bind), the
**frame-holder family** (`7d5898e7`), and the scope — `test_formal_per_struct_asks.py`
is registered now. **`_syscalls.mojo` and this round's regression are not among
them**, because the fix for that is on this branch and not on `master`: a re-run
on `master` alone reproduces the 229-file wall.

**≤ 36 minutes of wall for both arms together** at `-j 4` each, on a box at load
16.3. The CAS is content-addressed and machine-wide, so a re-run with nothing
changed reads a file per file; **editing `formal/`, the parser, `mojo/middle/`,
or `tools/formal_sweep.py` invalidates all of it** — which is why this run
rebuilt **733 of 735** files (`cas: 2 hit / 733 miss` on both arms). Each arm
also rebuilt **4** files on purpose: the ones that link a formal dylib, because
the dylib is not in the cache key.
