# FORMAL_sweep_work_map_2026-09-30: the formal backend's coverage, re-measured on current master and ranked by TERMINAL cause

**Measured 2026-09-30 on `24f96604` (master), arm64, the tool's default scope**
(this repo + `../modular/mojo/stdlib/std`). Replaces the sweep snapshot the
earlier workers planned from, which predates the `os`/`sys`/`struct`/
`argparse`/`glob`/`hashlib`/`time` host modules, the receiver hand-off, slice3,
frame-len and the toplevel-statement work.

    $ python3 tools/memslot.py --gb 16 --label sweep -- \
          python3 tools/formal_sweep.py > .tmp/sweep_20260930.log
    [arm64] 628 files: PASS=112 not-pass=516
      pass                          112
      codegen                       145   THE FINDING: refused a construct IN THIS FILE
      codegen/dependency            182   refused a construct in a module this file imports
      not-answerable/host-import    176
      not-answerable/unresolved-import  1
      not-answerable/unresolved-extern  4
      not-answerable/target-limit     5
      tool                            3
    codegen coverage: 112/439 = 25.5%

**The headline number is the least useful thing in this document.** 25.5% is a
rate over a denominator that is itself a census of refusals, and the table below
is the reason: **the "files blocked" column is an UPPER BOUND, and for the top
causes the measured bound is zero.** Two of them were measured here, by
implementing the fix and re-sweeping the affected files (§3). Read this document
as a plan, not as a ranking of work.

## How the ranking was made

Every printed line of class `codegen` / `codegen/dependency` is peeled to its
terminal message with `tools/formal_sweep.py`'s own `_split_chain` /
`_terminal_reason`, and keyed on a **cause** — what a fix would have to change —
rather than on the message. One cause in six modules is one fix that moves six
modules; one cause in one module is a fix that moves one file and says nothing
about the other five. The count is **files blocked**, i.e. printed lines, so a
dependency chain contributes one line to the cause at its end and nothing to the
cause at its top.

The ranking is `tools/formal_sweep_causes.py`, committed with this document so
the table below can be re-derived rather than taken on trust:

    $ python3 tools/formal_sweep_causes.py --min 5 <sweep log>
    $ python3 tools/formal_sweep_causes.py --json <sweep log>

It reuses `formal_sweep.py`'s own `_split_chain` / `_terminal_reason` / 
`_refuser`, so it cannot disagree with the sweep about where a chain ends. Its
cause list is a *label* set over message substrings, and the four operator
mistakes that list has already survived are written down in its docstring and
repeated below the table, because a taxonomy whose operators are undocumented
is a taxonomy whose numbers are only as good as whoever ran it.

## The ranked table

| # | cause | files blocked | in-file | refused in | one example | bug doc | worker |
|---|---|---|---|---|---|---|---|
| 1 | MLIR dialect construct (`__mlir_attr` / `__mlir_type` / `__mlir_op`) | **107** | 14 | `dtype.mojo` 48, `info.mojo` 34, `function.mojo` 8, `rebind.mojo` 2, `_select.mojo` 1, 14 files' own | `std/_plugin/selector.mojo` | `FORMAL_known_limits.md` §2 (a **permanent limit**, not work) | `formal-comptime-asm` (`construct:comptime-mlir-and-inline-asm-remainder`) |
| 2 | a TYPE name placed as a value: `L[T]()` or `DType.bool` | **41** | 3 | `binary_heap.mojo` 35, `random.mojo` 3, 3 files' own | `std/_plugin/__init__.mojo` | `FORMAL_type_argument_call_base_name_has_no_home.md` — **FIXED and `git rm`'d here**; ceiling measured at 0 (§3.1) | was none |
| 3 | a method parameter's field, with no call site to establish it | **27** | 0 | `builtin_slice.mojo` 27 | `std/base64/__init__.mojo` | `FORMAL_method_param_field_access.md` | none (the old `construct:receiver-handoff-method` is released) |
| 4 | receiver passed at argument position 0 | **25** | 25 | the file itself | `std/algorithm/reduction.mojo` | `FORMAL_frame_receiver_handoff.md` §"the position family" | none |
| 5 | frame address escapes: returned by its creator | **19** | 19 | the file itself | `std/builtin/_format_float.mojo` | `FORMAL_wide_receiver_by_reference.md`, `FORMAL_frame_receiver_handoff.md` §4 | none |
| 6 | `inlined_assembly` (a gimple-C runtime construct) | **18** | 0 | `_assembly.mojo` 18 | `std/atomic/__init__.mojo` | `FORMAL_known_limits.md` §1 (a **true limit**) | `formal-comptime-asm` |
| 7 | frame address passed where a value is wanted | **14** | 14 | the file itself | `std/builtin/tuple.mojo` | `FORMAL_wide_receiver_by_reference.md` | none |
| 8 | callee has no definition on this path | **12** | 12 | the file itself | `std/base64/base64.mojo` | `FORMAL_frame_receiver_handoff.md` §"Found, deliberately NOT fixed" | none |
| 9 | frame address escapes: aliased out of a method | **11** | 10 | the file itself 10, `itertools.mojo` 1 | `std/benchmark/_progress.mojo` | `FORMAL_wide_receiver_by_reference.md` | none |
| 10 | a slot's declared type is not declared by its struct | **10** | 10 | the file itself | `formal/arm64_codegen.py` | **none — FILED: `FORMAL_class_assigns_its_fields_in_init.md`** | none |
| 11 | a module-global name has no storage | **6** | 6 | the file itself | `formal/arm64.py` | `FORMAL_module_state_no_storage.md` | none |
| 12 | a field of a nested frame that the struct does not declare | 4 | 4 | the file itself | `std/memory/arc_pointer.mojo` | — (below the 5-file bar) | none |
| 13 | a name holds a frame address in more than one shape | 4 | 4 | the file itself | `analyze_benchmarks_types.py` | `FORMAL_frame_receiver_handoff.md` | none |
| 14 | a variadic call has no ABI | 3 | 1 | `tile.mojo` 2, the file itself 1 | `std/algorithm/backend/tile.mojo` | `FORMAL_known_limits.md` §1 | none |
| 15 | a field of a field: a frame slot holds one word, not a struct | 3 | 3 | the file itself | `std/collections/dict.mojo` | `FORMAL_wide_receiver_by_reference.md` | none |
| 16 | formal dylib has no public functions | 3 | 0 | `_unicode_lookups.mojo`, `constants.mojo`, `stat.mojo` | `std/math/__init__.mojo` | `FORMAL_known_limits.md` §1 | none |
| 17 | a module-level name of ANOTHER module is not exported as a word | 3 | 3 | the file itself | `mojo.mojo` | `FORMAL_module_exports_nothing.md` | `formal-module-attr` (integration-failed) |
| 18–30 | thirteen causes of 1–2 files each | 37 files total | | the file itself | — | see `FORMAL_known_limits.md` for the audit | none |

Rows 1–11 are every cause above 5 files: **290 of the 327 `codegen` +
`codegen/dependency` lines, in 11 of 30 causes.** Every one of them now has a
bug doc; row 10 did not and is filed with this map. The whole table, including
the refused-name histogram per cause, is reproducible with

    $ python3 tools/formal_sweep_causes.py --min 5 <sweep log>

**The two largest rows (1 and 6, 125 files between them) are not work at all** —
both are documented true limits, and together they are 38% of everything the
sweep calls a finding.

### The two boundaries that decide the table, and the two that bit

Both are recorded in `tools/formal_sweep_causes.py`'s module docstring, which is
where they belong — a table whose operators are not written down is a table
whose numbers are only as good as whoever ran it. **All four of these were got
wrong while producing this document, and three of them wrong QUIETLY.**

* **`callee has no definition on this path` is asked BEFORE `receiver passed at
  argument position 0`.** Both match `… is passed to …`, because the
  un-receivered message continues "… to `_b64encode()`, which is a name with no
  definition in hand". Asked the other way round, **12 findings hide in row 4**
  and row 4 reads 37 instead of 25. This is the specific way a taxonomy is
  worse than none: it puts a number in the wrong column, and the number is the
  one a planner would act on.
* **`frame address passed where a value is wanted` is asked before the same
  pair**, for the same reason and with the same direction of error.
* **A cause's alternatives are OR-ed; the markers inside one are AND-ed.** Both
  halves were wrong, in opposite directions. Written as one AND across three
  wordings, the MLIR cause required a message containing all three, matched
  **nothing**, and let 107 findings fall through to the next broad cause — loud,
  at least. Written as an OR *within* one alternative, a cause keyed on
  `reads '` / `out of a nested` / `has no such field` matched on `reads '` alone
  and reported **11 files for a cause that has 4** — quiet, and the two outputs
  are indistinguishable. The tool now has a shape assertion for the table
  because of a third variant of the same class of mistake: an alternative
  written `(("marker",))` is still iterable, so `all(...)` tests the message for
  each CHARACTER of the string and every English message contains all of them.
  That one put 71 files under a cause about nested frames, with an example
  unrelated to it, and raised nothing.
* **The log cannot separate `L[T]()` from `DType.bool`.** Both produce the same
  terminal message shape ("`<Func>: '<Name>' has no home: …") because the
  difference is in the AST — whether the refused `IdentExpr` is a subscript
  callee's base or a `MemberExpr`'s — and the printed line does not carry the
  AST. They are therefore ONE row (41), and the refused-name histogram
  (`List` 36, `DType` 4, `int` 1) is what separates them. Row 2's fix covers
  the 36 and not the 5, and §3.1 says so per file.
* **Row 1 is not work.** `FORMAL_known_limits.md` §2 measured it: `__mlir_attr`
  is a *dialect attribute* denoting a thing a freestanding image has no
  registry for, and the honest answer is the refusal. Its 107 files are the
  price of the backend's premise, not a queue. It is in the table because it is
  the largest column, and a reader who does not know that will read it as the
  biggest opportunity on the tree.

## 3. The measured ceiling: the count is a bound, and for the top causes the bound is 0

This is the part the earlier snapshot did not have, and it is the reason this
document is worth more than a sorted list. **A file's terminal cause is the FIRST
refusal the walk reaches, so a module is typically behind a stack of two to four
of them.** Fixing one moves the file to the next, and the sweep reports the new
one at the same count.

### 3.1 Row 2 — `L[T]()`, 41 files, **measured ceiling 0**

Fixed here (see §6 and `test_formal_run.py`'s `TYPE_APPLICATION_CASES`, each
answered case compared against CPython on both architectures). The false
diagnostic is gone, the construct now lowers on both architectures, and **not
one of the 41 files changes class** — re-swept exactly those 41:

    $ python3 tools/formal_sweep.py -j 6 -t 60 <the 41 files>
    [arm64] 41 files: PASS=0 not-pass=41
      codegen                        3
      codegen/dependency            38
    codegen coverage: 0/41 = 0.0%
    codegen/dependency by family: binary_heap.mojo: module exports nothing x35,
                                  random.mojo: other refusal x3

Where they land, in the order the walk now reaches them:

| files | new terminal cause | what it is |
|---|---|---|
| 35 | `binary_heap.mojo: formal dylib has no public functions` — "it declares only the generic struct template(s) `BinaryHeap`, and a parametric type has no single boundary layout either" | the **dylib export gate**, and it is a shallower limit than the one a direct build hits. A file that IMPORTS a module gets it as a dylib, and a module declaring only a generic struct template has nothing an importer can bind. This fires before any body is looked at. |
| 3 | `random.mojo: Rng_rand_scalar: 'DType' has no home` | **not row 2.** A bare TYPE name in a value position (`DType.bool` in `Scalar[DType.bool](…)`) — the same false-diagnostic shape as row 2, in a spelling this fix deliberately does not touch, and the one `work/frontend-silent`'s `f5bcb0a1` rewords. |
| 1 | `binary_heap.mojo: len(self._data)` — "this slot's DECLARED type is 'List[Self.T]' … `S()` does not run `__init__` on this path (premise a zero-argument S() does not run __init__)" | premise **B2**, and the reason this is the file's own in-file finding: built as an image the body IS reached, and `BinaryHeap.__len__` cannot be lowered while `S()` does not run `__init__`. |
| 1 | `func_attribute.mojo: FuncAttribute_MAX_DYNAMIC_SHARED_SIZE_BYTES: 'DType' has no home` | as above — a bare type name. |
| 1 | `detrace_diff.py: main: 'int' has no home` | as above — `'int'` is the RETURN ANNOTATION of `main`, read as a value. |

**Three limits, not one, and none of them is row 2.** So the honest reading of
row 2 before this change was **not** "41 files": it was "one false diagnostic
worth fixing, and 41 files that need a dylib export rule for generic struct
templates, a bare-type-name rule, and premise B2". Each of the three is a
bigger piece of work than row 2 was.

The `Optional` niche does NOT appear here, and this correction matters: a
hand-run `fire.py build --formal` of `binary_heap.mojo` reports `len(self._data)`
(premise B2) where the sweep's build reports the dylib export gate, because the
sweep builds the importer as a dylib and a direct build does not. **A ceiling
measured by hand-running one file is not the ceiling the sweep will report**, and
the difference is which of the stack you see.

### 3.2 Row 3 — `Slice.__eq__`, 27 files, **measured ceiling 0**

Implemented as a throwaway patch to measure the bound (declared parameter type
→ frame holder, seeded in `_frame_receivers`) and re-swept exactly the 27 files
the cause blocks:

    $ python3 tools/formal_sweep.py -j 8 -t 60 <the 27 files>
    [arm64] 27 files: PASS=0 not-pass=27
      codegen                       4
      codegen/dependency            23
    codegen coverage: 0/27 = 0.0%
    codegen/dependency by family: builtin_slice.mojo: other refusal x23

`Slice___eq__`'s `other.start` clears — and `builtin_slice.mojo` then refuses on
`self.step.or_else()` (an `Optional` unwrap, the same limit as above) and, in its
own body, on "an `Optional` receiver is stored in the field `self.start`"
(premise **B1**). **0 of 27.** The patch was not landed: a change that moves no
file and is not needed by any program is not worth its merge cost, and the
measurement is the deliverable.

`FORMAL_method_param_field_access.md`'s diagnosis is **confirmed on current
master** and its stated next step ("the DECLARED TYPE") does clear the refusal.

### 3.3 What this means for planning

* **Rank by "files that would reach `pass`", not by "files blocked".** Rows 2
  and 3 are 68 files of *not* work between them, and both were believed to be
  work until measured.
* **The cheapest real wins are the in-file causes**, because a file's own
  refusal is the only one it has: rows 4, 5, 7, 8, 9, 10 and 11 are 98 files,
  all in-file, and fixing one moves that file to `pass` unless it has a second
  construct behind the first (measurable, per file, in minutes).
* **The two largest rows are not fixable at all** (1 and 6 are documented true
  limits, 125 files), which leaves the real queue as rows 4/5/7/8/9/10/11 — 98
  files, no dependencies, and each one its own analysis question.

## 4. Host-module imports, by module

176 files, and **none of them is a coverage number** — the sweep deliberately
keeps this class out of every rate, and nothing here changes that. The split
that matters is in-reach (a Mojo-side implementation could in principle provide
it) against needs-a-host-process:

| module | files | in reach? | worker / doc |
|---|---|---|---|
| `re` | 57 | yes | `mod-re` (`module:re`) |
| `subprocess` | 40 | **no** — needs a host process this image does not have | permanent |
| `ast` | 11 | yes | landed by `mod-ast`; the 11 are `codegen`-adjacent, not host imports |
| `platform` | 11 | yes | `formal-os-backing` (`construct:os-backing-constructs`) |
| `json` | 7 | yes | `hostmods-2` |
| `concurrent.futures` | 6 | **no** — needs an embedded interpreter | permanent |
| `dataclasses` | 6 | yes | `mod-dataclasses` |
| `glob` | 6 | yes | `hostmods-2` |
| `collections`, `ctypes`, `shutil` | 4 each | `ctypes` **no**; the other two yes | `hostmods-2` |
| `fcntl` | 3 | **no** — a kernel object | permanent |
| `enum`, `pathlib`, `tempfile` | 2 each | yes | `hostmods-2` |
| 10 more, 1 each | 10 | mixed | — |

**112 of the 176 are in reach and 64 are permanent**, which is the number a
planner wants and the sweep prints for you. The 10 `ast`/`platform` rows are
worth a look rather than a claim: a file can be in this class *and* have a real
codegen gap behind the import, and the sweep's own line says so per file.

## 5. Tooling findings from this run (all real, none fixed here)

1. **3 files got no verdict at all**, all three with the same message:
   `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` —
   `std/gpu/compute/arch/mma_apple.mojo`, `mojo/middle/stmts_shared.py`,
   `test_arm64_emission.py`. The build driver is being handed something that is
   not JSON, and the sweep classifies it as `tool` (in no rate) rather than as
   the crash it is. **`FORMAL_sweep_tool_json_decode_error.md`.**
2. **1 file is `not-answerable/unresolved-import` for the module
   `formal_sweep`** — i.e. `tools/formal_sweep.py` itself, which imports
   `subprocess`. Harmless, but it means the sweep cannot classify its own file
   and a reader looking for a real finding there will not find one.
3. **The CAS carried the run**: 626 misses, 2 hits, ~4 minutes wall for 628
   files. The classification, not the compile, is what costs. Re-running after a
   `formal/` edit invalidates every entry (the key is `_criteria_id()`, this
   tool's own bytes) — so a one-line edit to a *cause marker* in
   `tools/formal_sweep_causes.py` is free, and a one-line edit to
   `formal_sweep.py` is not. Editing `formal/` invalidates all 628, which is
   why the post-fix re-sweeps in §3 took minutes rather than seconds.
4. **The scope is "every `.py`/`.mojo` under the repo", so adding a Python tool
   adds a file to the sweep.** `tools/formal_sweep_causes.py` makes the default
   scope 629 rather than 628, and it lands in
   `not-answerable/host-import` (it imports `collections`) — in no rate, and the
   same as `tools/formal_sweep.py` itself, which is how the sweep comes to be
   unable to classify its own source. Worth knowing before a reader diffs a
   file count against this document and finds 629.

## 6. What was fixed, and what it bought

Row 2. `formal/model.py` gains `subscript_callee_names` (one recogniser for "a
call's subscript callee is a symbol, not a value"), `subscript_callee_name`,
`empty_blob_constructor` and `blob_constructor_with_operands_refusal`; both
backends lower the zero-operand container constructor to the eight-byte blob
that IS the empty container, and `ValueKinds` classifies the result as a
container so `len()` of it is answerable.

* **Coverage: 0 files.** Measured by re-sweeping exactly those 41, not assumed
  — §3.1.
* **What it did buy:** a refusal that was false about the file is gone (the
  reader was sent to the register allocator for a fact about the language), a
  construct that is exactly representable is representable, and both
  architectures now agree on it — x86-64 refused the same source on a
  pre-existing `SubscriptExpr`-callee gap, and this closes that gap *for this
  construct* by asking the same two shared predicates arm64 asks rather than by
  copying its decision. The general gap stays a gap, and the x86-64 backend's
  own comment says so and names what would close it.
* **The tests are CPython comparisons, not constants.** `TYPE_APPLICATION_CASES`
  is four PAIRS — the Mojo text the backends build, and the CPython text that
  must print the same thing — and the expected value is whatever CPython prints,
  run at test time, on BOTH architectures. A constant is an assertion about a
  lowering written by the same person who wrote the lowering.
  `TYPE_APPLICATION_REFUSALS` holds the two counter-cases that keep the fix
  narrow: `len(List)` (the same spelling in a VALUE position) must still refuse
  with the register-allocator sentence, because that sentence is TRUE about
  that program, and `var xs: List[Int]` (a type in a NON-CALL position) must
  still build.
* **What has to happen next for those 41 files, in the order the sweep now
  reports them:** a dylib export rule for a module that declares only a generic
  struct template (35 files), a bare-TYPE-name-in-a-value-position rule (5, and
  overlapping `work/frontend-silent`'s `f5bcb0a1`), then premise B2 (1).
  **None of the three is row 2, and each is bigger than row 2 was.**
