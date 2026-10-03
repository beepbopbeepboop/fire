# FORMAL_sweep_work_map_2026-09-30_r2: the formal backend's coverage, re-measured on current master, ranked by TERMINAL cause

> **CURRENCY, re-read 2026-10-01. This is a SNAPSHOT of one commit, not a
> current measurement, and its numbers do not describe this tree** — 90+ commits
> of finished formal work have landed since `f378280d`, on this branch and on
> the branches it is merged from. This session was explicitly not permitted to
> run a sweep, so nothing here has been re-measured and no count below should be
> quoted as current. What survives is what does not decay: the per-cause RANKS as
> a picture of where the refusals were, §6's unexplained entries, and the three
> reasons the headline did not move — which are the part a reader planning work
> actually needs, and which are about the shape of the tree rather than about
> its numbers. A fresh sweep is the only way to re-date this file.

**Measured 2026-09-30 19:21 PDT on `f378280d` (master), arm64, the tool's default
scope** (this repo + `../modular/mojo/stdlib/std`).

    $ python3 tools/memslot.py --gb 16 --label sweep -- \
          python3 tools/formal_sweep.py > .tmp/sweep_20260930_r2.log
    [arm64] 637 files: PASS=112 not-pass=525
      pass                          112
      codegen                       148   THE FINDING: refused a construct IN THIS FILE
      codegen/dependency            221   refused a construct in a module this file imports
      not-answerable/host-import    145
      not-answerable/unresolved-import    1
      not-answerable/unresolved-extern   4
      not-answerable/target-limit        5
      tool                              1
    codegen coverage: 112/481 = 23.3%

Replaces `FORMAL_sweep_work_map_2026-09-30.md` (the r1 map, measured on
`24f96604`, 628 files, 112 pass) as the thing to plan from. r1 stays, because
its §3 ceiling measurements are measurements and three documents cite them;
nothing in r1 is wrong, and §6 below says exactly which of its numbers moved.

## The headline, and the three reasons it did not move

**Pass is 112, and it was 112 yesterday.** That is the fact a planner has to
explain before the table means anything, and it has three causes, all measured
here rather than inferred:

1. **The rate's denominator grew by 42 and the numerator by 0**
   (439 → 481). The host-module wave did what it was supposed to do — `re`
   (57 files) and `dataclasses` (6) left `not-answerable/host-import` entirely
   (`formal/hostmods/re.mojo` landed at `0f2ddc90`; `dataclasses` is now a
   front-end transform, `formal/imports.py:297`) — and the files that imported
   them moved the other way, into `codegen/dependency`, behind whatever those
   modules are refusing. **In-reach host-module work fell from 112 files to
   40** (§4), which is the wave finishing, not stalling.
2. **The one landed fix with a measurement behind it moved 35 files *deeper*
   rather than out.** `L[T]()` now lowers (`5536f17b`), so the 41 files r1
   attributed to it are re-reported at whatever the walk reaches next — and for
   35 of them that is `binary_heap.mojo`'s dylib export gate, which is why that
   row went from **3 files to 38** and became the second-largest cause on the
   tree. r1 §3.1 predicted this exactly and called it "not row 2, and bigger
   than row 2 was". It was right.
3. **Nine of the twelve causes above 5 files are owned by workers whose work is
   FINISHED and NOT IN MASTER** (rows 1, 4–12; row 1's owner is 55 commits of
   MLIR/inline-asm work). `git rev-list --count master..work/<b>`:

   | owner (claim) | unmerged commits | rows it owns |
   |---|---|---|
   | `formal-comptime-asm-r2-r2` (`construct:comptime-mlir-and-inline-asm-remainder`) | **55** | MLIR 108, `inlined_assembly` 18 |
   | `formal-module-globals` (`construct:module-global-storage`) | 13 | module-global storage 5 |
   | `formal-frame-by-value` (`construct:frame-address-as-value`) | 5 — **merged** | frame address passed where a value is wanted 14 |
   | `formal-class-fields-in-init` (`construct:class-assigns-fields-in-init`) | 5 — **merged** | slot's declared type 10 |
   | `formal-frame-escape` (`construct:frame-address-escapes`) | 4 — **merge ABORTED, see `FORMAL_returned_frame_two_incompatible_designs.md`** | frame escapes, returned 18 + aliased 10 |
   | `formal-receiver-position` (`construct:receiver-position-family`) | 4 | receiver at argument position 0, 25 |
   | `formal-method-param-field` (`construct:method-param-field-access`) | 2 | method parameter's field 27 |
   | `formal-receiver-handoff` (`construct:receiver-handoff-method`) | 6 | receiver hand-off |
   | `formal-string-return` (`construct:string-receiver-return`) | 7 | string receiver returned |
   | `formal-value-model` / `fix-merge-formal-value-model` (`construct:formal-value-model-gaps`) | 6 / 8 | the value model (not a row above 5 files) |

   The seven rows above the line own rows 4–12 of "the ranked table" below and
   **88 commits** between them; the three below it add 21 more.

   **Every number in rows 4–12 of the table below is therefore a
   PRE-FIX number**, measured on a tree that does not contain the fix its owner
   already wrote. The right action for those rows is *integrate and re-measure*,
   not more work — which is also why this map enqueues nothing against them
   (§5).

## How the ranking was made

Unchanged from r1, and the tool is unchanged in that respect: every printed line
of class `codegen` / `codegen/dependency` is peeled to its terminal message with
`formal_sweep.py`'s own `_split_chain` / `_terminal_reason`, and keyed on a
**cause** — what a fix would have to change — rather than on the message.

    $ python3 tools/formal_sweep_causes.py --min 5 .tmp/sweep_20260930_r2.log
    $ python3 tools/formal_sweep_causes.py --json .tmp/sweep_20260930_r2.log

**"FILES BLOCKED" IS AN UPPER BOUND, and for the two largest unowned rows it is
now MEASURED** (§3). Three causes have been measured this way: r1 measured two at
a ceiling of 0, and this run measures the third (§3.1). The count is printed
lines, so a dependency chain contributes one line to the cause at its end and
nothing to the cause at its top.

## The ranked table

Owner is `python3 tools/control.py claims` + `status` at 19:30. "unmerged" is
`git rev-list --count master..work/<branch>`.

| # | cause | files blocked | in-file | refused in | one example | bug doc | owner |
|---|---|---|---|---|---|---|---|
| 1 | MLIR dialect construct (`__mlir_attr` / `__mlir_type` / `__mlir_op`) | **108** | 14 | `dtype.mojo` 49, `info.mojo` 34, own 14, `function.mojo` 8, `rebind.mojo` 2, `_select.mojo` 1 | `std/_plugin/selector.mojo` | `FORMAL_known_limits.md` §2 — a **permanent limit**, not work | `formal-comptime-asm-r2-r2`, 55 unmerged |
| 2 | a module with no boundary symbol: only generic templates | **38** | 0 | `binary_heap.mojo` **35**, `_unicode_lookups.mojo` 1, `constants.mojo` 1, `stat.mojo` 1 | `std/_plugin/__init__.mojo` | `FORMAL_known_limits.md` §1 — **audited again today**, §1.2 below | **none** → `formal-dylib-export` |
| 3 | `==` between two values whose kind no call site established | **37** | 1 | `argparse.mojo` **36**, own 1 | `checked_run.py` | **none in r1 → filed here**: `FORMAL_argparse_blocked_on_unannotated_callee_comparison.md` | **none** → `formal-argparse-kind` |
| 4 | a method parameter's field, with no call site to establish it | **27** | 0 | `builtin_slice.mojo` 27 | `std/base64/__init__.mojo` | `FORMAL_method_param_field_access.md` | `formal-method-param-field`, 2 unmerged |
| 5 | receiver passed at argument position 0 | **25** | 25 | the file itself | `std/algorithm/reduction.mojo` | `FORMAL_frame_receiver_handoff.md` §"the position family" | `formal-receiver-position`, 4 unmerged |
| 6 | `inlined_assembly` (a gimple-C runtime construct) | **18** | 0 | `_assembly.mojo` 18 | `std/atomic/__init__.mojo` | `FORMAL_known_limits.md` §1.1 — a **true limit** | `formal-comptime-asm-r2-r2`, 55 unmerged |
| 7 | frame address escapes: returned by its creator | **18** | 18 | the file itself | `std/builtin/_format_float.mojo` | `FORMAL_wide_receiver_by_reference.md`, `FORMAL_frame_receiver_handoff.md` §4 | `formal-frame-escape`, **merge ATTEMPTED and ABORTED** — two incompatible returned-frame designs; see `FORMAL_returned_frame_two_incompatible_designs.md` |
| 8 | frame address passed where a value is wanted | **14** | 14 | the file itself | `std/builtin/tuple.mojo` | `FORMAL_wide_receiver_by_reference.md` | `formal-frame-by-value`, **merged** |
| 9 | callee has no definition on this path | **12** | 12 | the file itself | `std/base64/base64.mojo` | `FORMAL_frame_receiver_handoff.md` §"Found, deliberately NOT fixed" | **none** → `formal-callee-no-def` |
| 10 | frame address escapes: aliased out of a method | **10** | 9 | own 9, `itertools.mojo` 1 | `std/benchmark/_progress.mojo` | `FORMAL_wide_receiver_by_reference.md` | `formal-frame-escape`, **merge ATTEMPTED and ABORTED** — two incompatible returned-frame designs; see `FORMAL_returned_frame_two_incompatible_designs.md` |
| 11 | a slot's declared type is not declared by its struct | **10** | 0 | the file itself | `formal/arm64_codegen.py` | **FIXED and `git rm`'d** — the type is read out of what `__init__` ASSIGNS (`model.assigned_value_base_name` + `struct_init_field_types`, unanimity or nothing, with `struct_init_field_type_why` as the negative half) | `formal-class-fields-in-init`, **merged**; re-measured at 0 pass: 5 of the 10 land on rows 7/10 (the frame-LIFETIME family) and 3 leave the `codegen` class onto a host import (`re`, `types`) |
| 12 | a module-global name has no storage | **5** | 5 | the file itself | `formal/arm64.py` | `FORMAL_module_state_no_storage.md` | `formal-module-globals`, 13 unmerged |
| 13–33 | twenty-one causes of 1–4 files each | 47 files | | | — | `FORMAL_known_limits.md` for the audit | mostly none |

Rows 1–12 are every cause above 5 files: **322 of the 369** `codegen` +
`codegen/dependency` lines, in 12 of 33 causes. **Every one of the twelve has a
bug doc**; row 3 did not and is filed here.

### What moved since r1, cause by cause

| cause | r1 | r2 | why |
|---|---|---|---|
| MLIR dialect construct | 107 | 108 | `dtype.mojo` 48 → 49; the family is stable and permanent |
| **module exports no public functions** | 3 | **38** | the `L[T]()` fix let 35 `binary_heap.mojo` importers reach the export gate (§3.1 of r1 predicted 35) |
| **`==` between two values whose kind no call site established** | — (in `other refusal`) | **37** | 36 files blocked by `argparse.mojo`'s one comparison; **this cause did not exist in the table until this commit** — see below |
| a TYPE name placed as a value | 41 | **4** | `5536f17b` landed it. The 4 survivors are `DType.bool` in a value position, a different spelling the fix deliberately does not touch (`fix-merge-formal-type-as-value`) |
| method parameter's field | 27 | 27 | unchanged because the owner's 2 commits are unmerged |
| receiver at argument position 0 | 25 | 25 | unchanged, owner's 4 commits unmerged |
| frame escapes: returned | 19 | 18 | owner's 4 commits unmerged; the −1 is a file that moved to row 10 |
| `inlined_assembly` | 18 | 18 | unchanged, owner's 55 commits unmerged |
| frame address passed where a value is wanted | 14 | 14 | owner's 5 commits unmerged |
| callee has no definition | 12 | 12 | — |
| frame escapes: aliased | 11 | 10 | as row 7 |
| slot's declared type | 10 | 10 | owner's 5 commits unmerged |
| module-global storage | 6 | 5 | owner's 13 commits unmerged |
| the **`other refusal`** bucket | 32 | **48 → 4** | measured on this log with the table as it stood, 48 decomposed as **37** argparse's one comparison (now row 3), **4** a message a reword had emptied out of its own row, **3** the `None` default (now its own row), and a **4-file residual**. r1's 32 was measured on a different log; the two are not directly diffable, and the composition above is the part that is a census |

**The taxonomy was quietly wrong, and this commit fixes it.** Three defects,
none of which raised anything:

* **One marker was stale.** `formal-module-attr` reworded the module-level-name
  refusal from `… SO it is a module-level name of another module` to `… AND it
  is …`, so 4 findings walked out of that row into `other refusal` — a bucket
  whose name means *this tool has not classified this*. Both wordings are
  markers now, because a sweep log is an artifact and the table has to read the
  old ones too.
* **The third-largest construct in the tree had no cause at all** (37 files,
  row 3). It is added.
* **Two rows were dead or unreachable.** `unimplemented intrinsic` keyed on
  `formal_sweep.py`'s *family name*, which no message in the tree contains, and
  duplicated the `...`-body cause three entries above — deleted. `multi-index
  subscript` keyed on a phrase `formal/build.py` says a refusal was wrong about
  once, and sat **below** the broad `has no representation on this path` cause
  whose sentence the real message ends with, so it could never match — re-keyed
  on the live wording and moved above it.

`test_refusal_taxonomy.py` already existed for exactly this disease in
`formal_sweep.py`'s family table; it now carries the causes table too — one real
message per cause, every cause reachable from at least one, labels unique, both
wordings of the reworded message classified alike, and the two precedence
boundaries asserted independently of the samples. 95 checks, green. **A reword
that breaks a marker now fails a test instead of moving a column.**

## 3. The measured ceiling: "files blocked" is a bound, and rows 2 and 3 are measured

### 3.1 Row 3 — the argparse comparison, 37 files, **measured ceiling 1**

`formal/hostmods/argparse.mojo` refuses on ONE comparison, so 36 of its 37
files are behind it. The refusal names its own repair (annotate the callee), and
the repair is two annotations:

```mojo
def _name_len(rec, k) -> int:      # was: no annotation
def _fname_len(p) -> int:          # was: no annotation
```

Applied as a throwaway patch and re-swept exactly those 37 files — **with a cold
CAS**, which is not optional (§6.1):

    $ python3 tools/memslot.py --gb 16 --label sweep37nc -- env \
          GMOJO_HOME=$PWD/.tmp/gmojo_nc python3 tools/formal_sweep.py -j 4 -t 60 \
          $(cat .tmp/argparse37.txt)
    [arm64] 37 files: PASS=1 not-pass=36
      pass                            1
      codegen                         2   (a DIFFERENT cause: module-global storage x1,
                                         a type name as a value x1)
      not-answerable/host-import     34   platform x6, subprocess x6, json x5,
                                         concurrent.futures x4, collections x3, fcntl x3, …

**Ceiling: 1 of 37.** `argparse.mojo` itself reaches `pass`. The other 36 split
into 34 that leave the codegen denominator entirely (they import `platform`,
`subprocess`, `json`, `collections` — host modules with no Mojo source, a fact
about the target) and 2 that stay in it behind a different construct.

**A second-order fact worth more than the fix:** those 34 files were *in the
denominator* before (as `codegen/dependency`) and are *out of it* after. So
landing the two annotations takes the headline from `112/481 = 23.3%` to
`113/447 = 25.3%` — **+2 points of rate for +1 file of coverage.** The rate is
not a coverage measure here, and this is the clearest instance on the tree. The
patch is **not landed**: it is a `formal/hostmods/*.mojo` change whose value is
one file, and the decision about whether the sweep's denominator should move
like that belongs to whoever owns the sweep's semantics.

The measurement is the deliverable; the fix is two lines and is in
`bugs/FORMAL_argparse_blocked_on_unannotated_callee_comparison.md`.

### 3.2 Row 2 — the dylib export gate, 38 files, **audited, not fixed**

`FORMAL_known_limits.md` §1 audits this family at "30 files, 8 terminal
modules". It is **38 files, 9 terminal modules**, and the new one is
`std/collections/binary_heap.mojo` alone at 35 of the 38 — it was invisible in
r1 because `L[T]()` refused before the export question was reached. Measured the
way §1 measured the other eight, with the same two functions:

    binary_heap.mojo   exports=[]  exclusions={'BinaryHeap': 'generic-template'}
    stat.mojo          exports=[]  exclusions={'S_ISLNK': …, all 'generic-template'}
    _assembly.mojo     exports=[]  exclusions={'inlined_assembly': 'generic-template'}

**The verdict is the same as the eight: a true limit.** `struct BinaryHeap[T]`
has no single boundary layout, `doc/ABI.md` §Generics is explicit that a
generic is monomorphized and each instantiation is its own symbol, and Stage 5
monomorphization is not on this path. §1.2 of `FORMAL_known_limits.md` now
records it with this evidence.

**So the largest unowned row on the tree is not work either** — it is 35 files
waiting on Stage 5, which is a project, not a task. What is left to ask, and
what the enqueued worker is for, is whether there is anything short of Stage 5
that gives an importer something to bind: a per-instantiation export keyed by
type arguments, or a type descriptor the importer can bind a template through.
That is a design question with a cheap experiment, and "measure the marginal
effect first" is the whole of the task.

### 3.3 The two largest rows are limits, and that is 33% of everything the sweep calls a finding

Rows 1 and 6 (126 files) are documented true limits. Rows 1, 2 and 6 together are
164 of 369 `codegen` lines — **44%** — and none of the three is a bug. That
leaves **205 files** in rows 3–12: 37 unowned (row 3), 38 owned by nobody but
gated on Stage 5 (row 2 is in that 164; rows 4–12 are 139 files, every one of
them owned by a worker whose fix is already written and unmerged).

## 4. Host-module imports, by module

145 files, and **none of them is a coverage number** — the sweep keeps this
class out of every rate. The split that matters is in-reach (a Mojo-side
implementation could in principle provide it) against needs-a-host-process, which
`formal/imports.py` decides:

**In reach, and therefore work: 40 files** across `ast`, `collections`, `copy`,
`enum`, `functools`, `glob`, `io`, `json`, `math`, `pathlib`, `platform`, `stat`,
`typing`. **Permanent: 105** (`subprocess` 42, `importlib` 38, `concurrent.futures`
2, `ctypes` 3, `fcntl` 3, `socket`, `signal`, `html`, `posixpath` …).

| module | files | in reach? | note |
|---|---|---|---|
| `subprocess` | 42 | **no** — needs a host process this image does not have | permanent |
| `importlib` | 38 | **no** — it *is* the host's import machinery | permanent; **absent from r1's table** |
| `ast` | 10 | yes | landed as `formal/dataclass_transform.py`'s neighbour; was 11 |
| `platform` | 7 | yes | was 11 — `formal-os-backing` landed |
| `glob`, `shutil` | 6 each | yes | |
| `zlib` | 5 | **no** — a system library | permanent; **absent from r1's table** |
| `pathlib`, `tempfile` | 4 each | yes | was 2 each |
| `collections`, `ctypes`, `json` | 3 each | `ctypes` **no**; the other two yes | `json` was 7 |
| `concurrent.futures` | 2 | **no** — needs an embedded interpreter | permanent |
| `enum` | 2 | yes | |
| 10 more | 10 | mixed | |
| ~~`re`~~ | ~~57~~ | **gone** | `formal/hostmods/re.mojo`, `0f2ddc90` |
| ~~`dataclasses`~~ | ~~6~~ | **gone** | a front-end transform now (`formal/imports.py:297`) |
| ~~`fcntl`~~ | ~~3~~ | **gone** from this class | |

**In-reach work fell 112 → 40 files** over the two sweeps; the wave is nearly
done. **r1's §4 table cannot be diffed against this one**: it does not sum to its
own total (its rows come to 175 against a stated 176) and it omits `importlib`
(38) and `zlib` (5), the first and sixth largest rows here. Its per-module split
was a partial list, not a census; this one is.

## 5. What is enqueued, and what is not

**Enqueued (one worker per cause above 5 files with no claim held):**

| cause | worker | claim | the task, in one line |
|---|---|---|---|
| 3 — `==` between two unestablished kinds (37) | `formal-argparse-kind` | `construct:unannotated-callee-kind` | the fix is two annotations and the measured ceiling is **1**; land it with a test, or say why not — and say what it does to the denominator |
| 2 — a module with no boundary symbol (38) | `formal-dylib-export` | `construct:dylib-export-gate` | the ceiling is **Stage 5**; find whether anything shorter gives an importer something to bind, and measure what it buys |
| 9 — callee has no definition on this path (12) | `formal-callee-no-def` | `construct:callee-has-no-definition` | in-file, 12 files, no dependencies — measure the per-file ceiling before starting |

**Deliberately NOT enqueued**, because a claim is held (rows 1, 4, 5, 6, 7, 8, 10,
11, 12 — 139 files): more work against them would collide with the 88 commits of
finished, unmerged work their owners already wrote. **The cheapest thing anyone can do for those 139 files
is integrate those branches and re-run this sweep** — and the controller's queue
already holds `fix-merge-formal-{comptime-asm-r2-r2, module-globals,
class-fields-in-init, frame-by-value, frame-escape}`, so this is in flight.

## 6. Tooling findings from this run

### 6.1 The cache does not see a module edit, so a re-sweep can measure nothing

The first attempt at §3.1 re-swept the 37 files with the annotations applied and
got:

    [arm64] 37 files: PASS=1 not-pass=36      cas: 35 hit / 2 miss

**35 of 37 verdicts were replayed from the CAS** — `formal/hostmods/*.mojo` is
not in `cas._FORMAL_SOURCES` (it globs `formal/**/*.py`), so editing a hostmod
moves no key. The run looked like a result and was a copy of the previous one.
Forcing a cold store (`GMOJO_HOME` pointed at an empty directory) is the only way
to measure a fix that lands in a Mojo module. This is
`bugs/FORMAL_sweep_cache_ignores_imports.md`, still open; **its closing warning is
the one that applies here** — a sweep over a tree where a module source changed
is not evidence about anything that imports it, and the tool has no `--no-cache`.

### 6.2 `tool` is down to 1 file, and the file is not the same one

r1: 3 files with `json.decoder.JSONDecodeError`, always
`std/gpu/compute/arch/mma_apple.mojo`, `mojo/middle/stmts_shared.py`,
`test_arm64_emission.py`. Now: **1**, `test_imports.py`. A rotating set points at
the runner rather than at any source file — consistent with hypothesis 2 in
here (the child was killed or truncated, and
an empty stdout is what `char 0` looks like).

**That row is now CLOSED, and hypothesis 2 was not it.** The mechanism was
measured on 2026-10-01: `formal/build.py` and `formal/imports.py` rewrote
`<dylib>.manifest.json` **in place**, `open(path, "w")` truncates at the open,
and a reader in the 0.21 ms window before the first byte gets an empty file —
while `json.JSONDecodeError` is not an `OSError`, so none of the `except OSError`
around those reads caught it. 357 of 882 concurrent reads of a real 11,668-byte
manifest saw the 0-byte file. Every writer now goes through
`_write_json_atomic` (private temp, `fsync`, `os.replace`) and
`update_dylib_manifest` is the single read-modify-write all four of them share;
`test_formal_manifest_atomic.py` is the test. The one-sweep-per-architecture
`flock` is a second, independent guard.

### 6.3 The scope grew by 9 files, all in this repo

637 now, 628 in r1: the tools and tests that landed in between. Each one is a
file the sweep must classify, and a new Python tool lands in
`not-answerable/host-import` if it imports anything from `collections`,
`subprocess`, `argparse` … — which is why `formal_sweep_causes.py` itself is one
of row 3's 37.

## 7. What would move this number

Not in order of size — in order of *files that would reach `pass`*, which is the
only ranking that has survived contact with a measurement:

1. **Integrate the 88 unmerged commits** covering rows 4–12, and re-run this
   sweep. Every one of those nine rows is a pre-fix number.
2. **Fix the sweep's cache key** (`FORMAL_sweep_cache_ignores_imports.md`) so a
   module edit invalidates its importers' verdicts. Without it, *every*
   measurement of a fix that lands in a `.mojo` module is a copy of the
   previous run — which is most of them.
3. **Row 3's two annotations**: +1 pass, −34 from the denominator. Cheap,
   measured, and a decision about the rate as much as about the backend.
4. **Rows 5, 7, 8, 9, 10, 11, 12** (94 files) are the in-file rows: no
   dependency chain, so a file's own construct is the only thing between it and
   `pass`, and each one's owner has already written the fix. Integrate before
   starting anything.