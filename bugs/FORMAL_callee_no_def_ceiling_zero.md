# `callee has no definition on this path`: the ceiling is ZERO, four of its five
sentences were false, and the hand-off itself now lowers

**Status: the refusal is TRUE of every file it names (landed); the hand-off
itself is NO LONGER refused — the step §4 named is built (2026-10-01), and the
ceiling is re-measured below and is still 0 of 11, on the new-modular tree.**

The population is no longer 12. The 2026-10-01 x86-64 sweep of the new-modular
stdlib (`.tmp/sweep-x86-4.txt`, 623 files) files **33** files under this cause,
and they are 11 imported free functions, 18 genuinely unbound names, and 4
`__get_mvalue_as_litref` — see §1a for the full split and §1b for what the 11
land on now. The 18 and the 4 are unchanged and still correct: `getattr`,
`hasattr`, `type_of`, `debug_assert` are host builtins or stdlib functions the
file does not import, and `__get_mvalue_as_litref` is a compiler intrinsic that
yields MLIR. Nothing here can lower a name that no source declares.

The row is `bugs/FORMAL_sweep_work_map_2026-09-30.md` row 8 (12 files, all
in-file, no dependency chain, so the bound and the value look identical on
paper). This document is the measurement of the second, and the split of the
row's one sentence into the five things it was standing for.

---

## 1. The ceiling, per file, on a cold CAS

Every file re-built with `model.frame_undefined_callee_refusal` patched to
`None` **in that process only** (nothing in the tree edited; §6 has the six
lines), so the build walks past this refusal and reports the next one:

    env GMOJO_HOME=$PWD/.tmp/gmojo_nc python3 next_refusal.py <file>

A cold CAS is not optional here: `cas.formal_build_key` does not fold in the
sources of the modules a file imports
(`FORMAL_sweep_cache_ignores_imports`), and nine of the twelve import
most of the standard library. Run twice — before the change and after it, on two
different cold CAS directories — and the second cause is identical in all
twelve.

| file (relative to the stdlib's `std/`, or the repo) | callee | what stops it NEXT |
|---|---|---|
| `base64/base64.mojo` | `_b64encode` | **dependency**: `std.memory` → `builtin_slice.mojo` `Slice___eq__`, a field access through a parameter |
| `collections/_conditional.mojo` | `__get_mvalue_as_litref` | **dependency**: `std.builtin.device_passable` → `function.mojo`, `__mlir_attr[...]` |
| `collections/interval.mojo` | `debug_assert` | `a String receiver is passed to writer.write … method call on a value receiver` |
| `collections/list.mojo` | `iter` | `a List frame address is passed to origin_of() … a wrong category of argument` |
| `collections/optional.mojo` | `__get_mvalue_as_litref` | `a Optional receiver is passed to encoder.encode … method call on a value receiver` |
| `ffi/unsafe_union.mojo` | `__get_mvalue_as_litref` | **dependency**: `std.builtin.rebind` → `builtin_slice.mojo` |
| `format/_utils.mojo` | `ElementFn` | `a FormatStruct receiver is returned from a method … which did not create the frame` |
| `utils/coord.mojo` | `__get_mvalue_as_litref` | `a Coord receiver is passed to the call … method call on a value receiver` |
| `utils/variant.mojo` | `__get_mvalue_as_litref` | `a List frame address is passed to origin_of()` (value-only callee) |
| `formal/build.py` | `discover_closures` | **host import**: `copy` |
| `scripts/repro_ftplib_isolated.py` | `getattr` | **host import**: `subprocess` |
| `test_formal_call_proof_gen.py` | `hasattr` | **host import**: `ast` |

**Zero.** Six of the twelve are not `codegen` findings about this file at all
once this refusal is out of the way — they are `codegen/dependency` (3) or
`not-answerable/host-import` (3), which is where the sweep would classify them
if the import diagnosis were not preempted. **That preemption is its own defect
and its own document** — a frame refusal raised from `_prepare_functions` beats
the import diagnosis for any file that does both, which is 80 in-scope files,
and fixing it moves six rows of the map at once:
`FORMAL_frame_refusal_preempts_the_import_diagnosis.md`.

The other six are each behind a refusal that belongs to a *different* row of the
map: the method-call-on-a-value family (`formal-receiver-handoff`), the
value-only-callee family (`formal-frame-by-value`, `origin_of`), and the
frame-escape family (`formal-frame-escape`).

So the row's 12 is an upper bound with **no** slack, and this construct cannot
be worth a fix on file count. It is still worth something, and §2 is what.

## 1a. The 33 files of the new-modular tree, by arm

`python3 tools/formal_sweep_causes.py --min 4 .tmp/sweep-x86-4.txt`, and the
names read off the messages themselves. The arms are the five
`frame_undefined_callee_refusal` distinguishes, so this is a measurement of the
classifier's coverage and not a guess at it:

| arm | files | names |
|---|---|---|
| imported free function | **11** | `discover_closures`, `llvm_intrinsic` ×2, `bitcast` ×2, `_b64encode`, `dirname`, `_getpw_macos`, `external_call` ×2, `_check_not_poison_masked` |
| genuinely unbound | **18** | `type_of` ×7, `getattr` ×2, `hasattr` ×3, `coro_fn`, `gen`, `element_fn`, `encode_mov_rm64_r64`, `Scalar`, `debug_assert` |
| MLIR reflection intrinsic | **4** | `__get_mvalue_as_litref` ×4 |
| compile-time parameter | **0** | — |
| star import | **0** | (the 22 star-importing stdlib files land elsewhere) |

`type_of` is 7 of the 18 and is the largest single-name cluster in the whole
row. It is not a missing declaration: no `type_of` is defined anywhere in the
new-modular stdlib (`grep -rn "def type_of\|fn type_of"` over 252 files: no
hits), and the seven uses are all compile-time type queries — `type_of(self).mut`,
`type_of(x)._mlir_type`, `type_of(unsafe_from_address)()`. A type is not a
value on this path and there is nothing to hand back, so those seven are the
`formal-type-value-2` construct (`construct:type-name-as-value-2`, 82 files)
and not this one.

## 1b. The 11 imported files, re-measured after the contract landed

All eleven, one build each, on this tree, after the step in §4 is built:

| file | what stops it now | class |
|---|---|---|
| `formal/build.py` | host import `copy` | **`not-answerable/host-import`** |
| `std/base64/base64.mojo` | dependency: `binary_heap.mojo` `'List' has no home` | `codegen/dependency` |
| `std/sys/_libc.mojo` | dependency: `std.ffi` → `binary_heap.mojo`, same | `codegen/dependency` |
| `std/io/file.mojo` | a method call on a value receiver (`….write_to`) | `codegen` |
| `std/utils/numerics.mojo` | a method call on a value receiver (`arg1.gt`) | `codegen` |
| `std/pwd/pwd.mojo` | a frame address STORED IN A FIELD (`self.pw_name`) | `codegen` |
| `std/bit/bit.mojo` | `type_of()` — a name nothing binds (the unbound arm) | `codegen` |
| `std/sys/intrinsics.mojo` | `type_of()` — the unbound arm | `codegen` |
| `std/_gpu/intrinsics.mojo` | `Int()` — the unbound arm | `codegen` |
| `std/_gpu/primitives/warp.mojo` | `func()` — the unbound arm | `codegen` |
| `std/sys/_metal_print.mojo` | a declared parameter every call site disagrees with | `codegen` |

**0 of 11 reach `pass`.** The ceiling is zero again, on a different population,
and for the same reason: the row was never a block of work but a row of
*diagnoses*, and every one of these eleven files has a different real problem
underneath it. Seven of them are now reported by a DIFFERENT ARM of the same
classifier, which is the accuracy fix doing its work rather than a new
refusal: `_gpu/intrinsics.mojo` was refused for `llvm_intrinsic` and is now
refused for `Int()`, which is the first unbound name its walk reaches, and
`llvm_intrinsic` is a name it really does import.

**One file changed CLASS, and it is the one worth having.**
`formal/build.py` was `CODEGEN` and is now `NOT-ANSWERABLE/HOST-IMPORT`
(measured with `python3 tools/formal_sweep.py -j 3 -t 300 formal/build.py`).
A file that imports `copy` is out of this backend's reach whatever its codegen
says, so counting it as a codegen finding put an unbuildable file in the
measured denominator. That is the preemption `FORMAL_frame_refusal_preempts_the_import_diagnosis.md`
names, and parking the hand-off instead of raising it fixed it for this
construct as a side effect — the frame analysis no longer runs before the
imports do on this path, so the import is reported. It moves the coverage
denominator DOWN by one and the finding count down by one, which is the
direction that makes the number mean something.

## 2. The row's one sentence was five sentences, four of them false

The fifth branch of `frame_receiver_escape_refusal` said, of all of these:

> a X receiver is passed to `f()`, which is a name with no definition in hand:
> **this module's own functions are the only ones in this image**, and the
> symbol is unbound before the receiver's layout is a question. … there is no
> such callee here to be compiled.

Measured over 987 files (the repo, the stdlib's `std/` and `test/`), 41 files
reach this branch. After the change, by arm:

| arm | files | is the old sentence true of it? | minimal repro |
|---|---|---|---|
| **imported free function** — the callee is bound by a `from … import …` | **26** (2 in the sweep's default scope) | **NO, twice.** It IS compiled, into another module's library; and it is not one of this module's own functions. | `from lib import take_it` + `take_it(p)` |
| **compile-time parameter** — the callee is one of the enclosing `def[…]`'s parameters | 1 | **NO.** No compilation anywhere will define it until a call site instantiates it; nothing is missing. | `def drive[Fn: def(mut W)]` calling `Fn(w)` |
| **comptime reflection intrinsic** — `__get_mvalue_as_litref` | 5 | true but unhelpful: it names an MLIR-yielding intrinsic and says "look for a missing export" | `var lit = __get_mvalue_as_litref(q)` |
| **star import** — the callee is bound by nothing but a `from M import *` | 2 | **NO.** `M`'s export set may bind it, and that is a library this pass has not built. 22 stdlib files write one. | `from lib import *` + `take_it(p)` |
| **genuinely unbound** | 7 (4 in scope) | **YES** — the only one it was true of. | `mojo_print(p)` |

The two repro programs are five lines each and both are refused the same way on
arm64 and x86-64; they are `test_formal_run.py`'s
`byref_refuse_imported_free_function`, `byref_refuse_star_imported_free_function`,
`byref_refuse_compile_time_parameter` and `byref_refuse_reflection_intrinsic`.

A reader who believed the old sentence about `_b64encode` went looking for a
missing export of a module that exports it, or for a callee to add to the wrong
file — which is the failure mode this whole refusal family documents itself as
existing to prevent ("a message that asserts a mechanism which is not operating
sends the reader after a non-bug").

## 3. What landed

* `formal/model.py`: `frame_undefined_callee_refusal` — one classifier, five
  texts — and `frame_receiver_escape_refusal`'s fifth branch delegates to it,
  keeping its own five-case order (an ADDRESS constructor still returns `None`,
  which is what `Pointer(to=s)` depends on). One more case sits BEFORE the
  delegation and not in it: `FRAME_VARIADIC_BUILTIN_CALLS`, which is `print` —
  a name this backend compiles, so it never belonged in "no definition in hand"
  at all. §5 has the measurement.
* `formal/build.py`: `_check_frame_escapes`'s "not in this image" branch passes
  the three facts the classifier needs. `imported` is threaded from
  `_prepare_functions`, which is the only function that has the module
  statements.
* `formal/imports.py`: `imported_bound_names` (every name a `from … import …`
  binds here, private ones included) and `star_imported_modules`. Both read the
  AST, so they are available **before** `_resolve_imports` — which is where the
  frame analysis sits, and why they had to be AST readers and not manifest
  readers.
  `reexported_names` now shares `_from_import_bindings` with them; it is
  **byte-identical** to the loop it replaced over all 987 files (checked with
  `.tmp/diff_reexport.py`, `identical=987 differ=0`), which is the only reason
  that consolidation is safe: it is a table every dylib manifest is written
  from.

Nothing else moved: over the same 987 files, 41 messages changed and **all 41
are this construct** — no other file's message and **no file's class** changed.
(This was measured before the contract landed; §1b measures the classes after,
and the one that changed — `formal/build.py` — is this construct's doing.)

**All five arms keep the clause `which is a name with no definition in hand`,
and that is load-bearing.** `tools/formal_sweep.py`'s `_FRAME_ESCAPES` and
`tools/formal_sweep_causes.py`'s cause table both key on that exact substring —
it is what keeps this family out of the `receiver passed as an argument` bucket
its own message begins with. An arm that reworded the opening would not fail
any test: it would quietly move every file it names into whichever family
matches next, with a wrong number in a table a planner acts on. The first
version of this split had four arms that did *not* keep it. Measured after the
fix: 41 files, and **all 41 still classify as `callee has no definition on this
path`** in both tools (`formal_sweep._refusal_family` and
`formal_sweep_causes`' label, run over the real messages).

## 4. What is NOT fixed, and the exact next step — WHICH IS NOW BUILT

**As of 2026-10-01 the step below is DONE**, and the two arms of the classifier
that refused the hand-off are reachable only when the link line answers neither
question. What follows keeps the original diagnosis (it is what the step was
built from) and then records what changed.

The missing thing was not the refusal, it was a **per-parameter contract in the
dylib manifest**: for each exported function, which parameters its own analysis
made frame holders and of which struct. With that, the importer can compare it
against the argument it is passing and either follow the address or refuse for a
real disagreement — the cross-image half of `_check_holder_agreements`, which
stopped at the module boundary. The manifest recorded `exports` / `reexports` /
`constants` / `module` and no parameter information at all.

### 4a. The blocker named here is GONE, and that is what made the step buildable

The original text said the step was blocked on the map's row 3 —
`take_it(p: P)` with no call site, `p.a` refused as "a field access through a
base nothing establishes" — claimed by `formal-method-param-field`
(`construct:method-param-field-access`), and that "until that lands, no
cross-module free-function hand-off can be built at all, whatever the manifest
carries".

**It landed**: commit `0c603fb2` ("formal: lower a method parameter's field from
its DECLARED type", the `Slice.__eq__` family) seeds a parameter's frame-holder
status from the parameter's DECLARED type, which holds whether or not the
module contains a call site. Measured on this tree, the exact two-module program
whose callee module used to be unbuildable:

    # lib.mojo                          # prog.mojo
    struct P:                           from lib import P, take_it
      var a: Int                        def main(n: Int) -> Int:
      var b: Int                          var p = P()
    def take_it(p: P) -> Int:              p.a = 3
      return p.a * 10 + p.b                p.b = 4
                                           return take_it(p) + n

`fire.py build --formal --no-prove lib.mojo` → **Built**. So the callee module
compiles, and the only thing left was the manifest.

### 4b. What landed

* `formal/build.py` `_frame_param_contract` / `_export_frame_contract` — the
  contract is built from the holder tables `_frame_receivers` has just settled
  and published on every export entry as `frame_params`, so it travels in the
  manifest beside the symbol it belongs to. **Derived, never re-derived**: a
  second reading of "is parameter i a frame address" is the pair of
  recognitions that agrees until the day it does not, which is the failure
  `_frame_candidates` was added to prevent.
* A module that declares **no** framed struct publishes all-`None` rather than
  nothing. That was a real bug in the first version: the early return in
  `_frame_receivers` skipped the publication, so `def bump(x: Int, by: Int)` in a
  struct-free module published no contract and its consumer reported "nothing on
  this image's link line settles it" where the truth was "it is a plain word".
* `formal/model.py` `resolve_frame_parameter_contract` — the decision, beside
  its three refusal texts, comparing the callee's struct **names** against the
  caller's. Names, not counts: two modules may each declare a `Pair`, and
  `base + 8k` means the same thing on both sides only because both computed it
  from the same field list.
* The site is **parked** in `_check_frame_escapes` and decided by
  `check_imported_frame_handoffs` from the link line, because
  `_prepare_functions` runs before `_resolve_imports`. Parking is what stopped
  the frame refusal preempting the import diagnosis, which is why
  `formal/build.py` changed class (§1b).
* `_check_frame_escapes` asks the classifier **twice** — with the import facts
  and without, `comptime_param_of` in both — and the comparison is the decision.
  Asking the fifth case directly is the mistake that had to be avoided, and it
  was made first: it skipped every arm above it and reported `print(p)` as "a
  name with no definition in hand", false of a builtin that is compiled.
  Measured, and it is in the tree as a note at the branch.

### 4c. What it is worth, measured

`test_formal_run.py`, both architectures:

| case | expected | what it would be if the address were wrong |
|---|---|---|
| read through the parameter | 44 | — (44 is also the single-module answer) |
| **write** through the parameter | 96 | 46 |
| star-imported free function | 44 | — |
| layout disagreement (`Q(v,pad)` vs `P(pad,v)`) | refused by name | 213 where CPython says 312 |
| plain-parameter disagreement | refused | the frame's own address: 42 and 58 on consecutive runs of one arm64 binary, 250 on x86-64 |
| a name no library publishes | refused as a real "nothing binds it" | — |

The write case is the one that earns the rest: the contract is per-parameter and
says nothing about direction, so a store through the parameter is as
load-bearing as a load, and the call is its own **statement** on purpose —
folding it into the return expression reads `p.a` before the call, in CPython and
here alike, and the case would pass with the write going nowhere. (An earlier
draft did exactly that and "passed" for that reason.)

**The file count is 0**, §1b: the eleven imported files each land on a different
real problem, and seven of them are now reported by a different arm of the same
classifier. What the step bought is a construct that is no longer a limit of the
analysis — the refusal is now a *decision* rather than an admission — and one
file that changed from `codegen` to `not-answerable/host-import`.

### 4d. Still not this row's work

* **The 24 `test/` files** in the imported arm are outside the sweep's default
  scope (`DEFAULT_STDLIB_SUBTREES = ("std",)`), which is why the 2026-09-30 map
  says 12 where the real population over all roots is 41. That is a property of
  the sweep's scope, not a disagreement about the taxonomy.
* **A method's non-receiver parameter** of an imported struct was parked by the
  same change and is decided by the same contract, so the opaque-position arm
  there is narrower than it was. What is left of it is the receiver-position
  family, which is `construct:receiver-position-and-no-representation`'s, not
  this row's.

**Found in passing, not fixed, not this row's to fix:**
`“An aliased re-export is published under the DEFINING module's name”` — the sibling reader
this change added (`imported_bound_names`) records the name a `from … import`
BINDS, and `reexported_names` records the name the defining module gave it, so
`from leaf import base as aliased` in a package `__init__` publishes `base` and
the consumer's `aliased(21)` cannot bind. Measured, with the build refusing to
emit an image whose symbol nothing provides.

### MEASURED 2026-10-04 (`formal25-3`): that item is TWO items, one of them
### fixed here and the other still open — and the one that was open was not the
### one the sentence describes

The sentence above names the RE-EXPORT (a consumer importing an alias a module
published). Re-measured on this tree, the alias is refused in **three** places,
and the two halves have nothing to do with each other:

| # | shape | before | after |
|---|---|---|---|
| A | the PROGRAM imports under an alias and calls it (`from deflib import need_two as nt; nt(1)`) | worked | worked — `test_formal_cross_module.py`'s case, 2024 |
| B | the PROGRAM imports under an alias, and the program calls **the library's own function**, which calls the alias | **refused** — `mid.mojo: the library would bind 1 symbol(s) that nothing provides, so it could not be loaded: aliased` | **FIXED** — `compile_formal_dylib` hands its emitters `import_bindings` now |
| C | a MODULE re-exports an alias and a consumer imports it (`from mid import aliased`) | **refused** — “`aliased` is called, and it is imported from `mid` … That module does not export it, and the reason is `doc/ABI.md`'s export rule” | **still refused** |

**B is the one the sentence does not describe and the one that was silently
whole.** The alias is a property of the file that WRITES it, so a module that
calls one has to bind the DEFINING name — and `compile_formal_dylib` passed
`dylib_syms` and `dylib_exports` to its emitters and nothing else, where
`compile_formal` has always passed `import_bindings`. Two files and one
boundary would not have shown it: the existing case for A is a two-file tree, and
it passes on the program's side alone. B needs three (leaf defines, mid imports
under an alias and calls it, prog imports mid) and it is now
`test_formal_cross_module.py`'s `a LIBRARY that calls its own import alias binds
the defining name`, differential against CPython on both architectures.

**C is still open and is a smaller question than it looks.** `reexported_names`
already returns BOTH spellings — measured in process on this tree:

```python
>>> reexported_names(module_statements("mid.mojo"))
{'base': ('leaf', …, 'base'), 'aliased': ('leaf', …, 'base')}
```

so the publication table is right and the drop is downstream of it: both entries
name ONE symbol in `leaf`'s trie, and whatever writes the manifest keeps one
spelling. **The exact next step is to find where a re-export entry's NAME stops
being the key** — `compile_formal_dylib`'s `_formal_exports`/`module_prefixes`,
or the export trie — and to decide which spelling wins, because a consumer that
spells `aliased` and a consumer that spells `base` both have to bind, and that
is an ABI question (`doc/ABI.md`'s export rule) rather than a reader's fix. Until
it is decided, the honest state of this item is the sentence above plus the two
rows: B landed, C refused by name with a message that now names the export rule
rather than the link line.

## 5. The histogram that found the last false clause

The name histogram per arm (over the 41, which is what a cause table prints per
row) is how the two remaining imprecisions in this family were found, and both
are now fixed:

| arm | names |
|---|---|
| imported free function | `_b64encode`, `_write_float` ×2, `assert_equal` ×10, `assert_true` ×2, `rand`, `randn`, `realpath`, `split`, `exists` ×2, `write_sequence_to`, `_count_utf8_continuation_bytes`, `_end_metal_trace_capture`, `keep` |
| comptime reflection intrinsic | `__get_mvalue_as_litref` ×5 |
| compile-time parameter | `ElementFn` |
| star import | `assert_true`, `assert_equal` |
| unbound | `getattr`, `hasattr`, `iter`, `debug_assert`, **`print`**, **`type_of`** |

* **`print` is a name this backend COMPILES** — `print("hi")` builds, runs and
  prints — so "no definition in hand" was false of it, and it is the most
  consequential name on this list: with the refusal lifted, `print(<frame>)`
  builds, runs, **exits 0** and prints the frame's ADDRESS as a decimal, 6102330608
  on arm64 and 13027830976 on x86-64 for the same source, and a different number
  on every run because the address moves. It now has its own refusal
  (`FRAME_VARIADIC_BUILTIN_CALLS`), deliberately NOT in `FRAME_C_VALUE_CALLS`,
  whose sentence says "a C library entry point" and `print` is Mojo's builtin
  lowered through `_emit_print` in each backend's call emitter. It says
  **"frame address is passed to"**, lowercase and not "receiver is passed to",
  because those are the two sweep markers either side of it: written as
  "receiver" this file counted in the position family, and written as
  "frame ADDRESS" it fell into `other refusal` — the bucket this taxonomy
  exists to empty. Both were numbers in the wrong column with no test failing,
  so the one file it moves (`test/builtin/test_default_writable_compile_fail.mojo`,
  out of the sweep's default scope) is counted in row 7 and not in this row:
* **`type_of(x)` is not implemented on this path at all** (no occurrence of the
  name in `formal/`), so for it the generic sentence is true and it stays there.
* `getattr`, `hasattr`, `iter` are host builtins with no Mojo source anywhere,
  and `debug_assert` is a stdlib function (`std/builtin/debug_assert.mojo`) that
  `std/collections/interval.mojo` does not import — so "nothing in this image
  binds it" is true of all four. The useful refinement for them ("the backend has
  no implementation of this builtin") would need a table of what the backend DOES
  implement, and the honest test for that today is a name somebody wrote down
  after measuring it — see the `print` note above for why that is a debt rather
  than a design.

**What would retire the table**: the emitter-level builtins are hard-coded per
backend (`formal/arm64_codegen.py:5157` and `formal/x86_64_codegen.py:4926` each
spell `if name == "print"`), so "which builtins does this backend compile" is
now in three places — two emitters and this model set. A single published
`model.EMITTER_BUILTINS` that both emitters' `if name == …` chains and
`FRAME_VARIADIC_BUILTIN_CALLS` read would make the three agree by construction;
that is a change to both backends' call emitters and is not this construct's to
make.

### §5's table is BUILT (2026-10-01, `formal3-2-r2`)

`model.EMITTER_BUILTINS` — `{name: emitter method suffix}` — is published, both
emitters' dispatch chains read it through `model.emitter_lowers(name)`, and
`FRAME_VARIADIC_BUILTIN_CALLS` is DERIVED from it rather than written beside it.
So "which builtins does this backend compile" is one table, and the three places
cannot drift because two of them no longer exist as separate text.

`range` is the one name still spelled in each chain, because its emitter takes
the ARGS LIST rather than the `CallExpr` — a property of the emitter, not of the
builtin, so it lives in the table as the method name `_emit_range_list` rather
than in a caller that would have to know it. `open` is not in the table: it is
`BUILTIN_FUNCTIONS`'s `file_open`, because `open` is also a C library entry
point and the two are genuinely different facts.

Pinned two ways in `test_formal_run.py`. The end-to-end half is the case that
already existed, `byref_refuse_print_of_a_frame`, whose refusal is the sentence
this table exists to keep true. The consistency half is new,
`check_emitter_builtin_agreement`, which reads both emitters' SOURCES and fails
when any of three things is false: an emitter spells a builtin the table lacks;
the table names an `_emit_*` method a file does not define; or `print` leaves
`FRAME_VARIADIC_BUILTIN_CALLS`. All three verified by breaking each in turn — an
added `name == "enumerate"` chain, a table entry naming `_emit_no_such_method`,
and an emptied variadic set each produce exactly the corresponding failure and a
clean tree produces none.

The two backend suites that would catch a dispatch difference are green:
`test_formal_x86_64_parity.py` 6/6, `test_formal_frame_len.py` 10/10 (the `len`
dispatch), and a hand-built probe printing `len=3`, a `print`, and a `range`
sum on BOTH architectures. Full `test_formal_run.py` 534 PASS / 1 FAIL, the one
being the stale `a_mutated_module_global_is_refused` expectation this document's
own last section names as `FORMAL_module_state_no_storage`'s.

**This document stays**, which is a departure from the usual rule and the reason
is worth recording: four other bug docs and two sweep work maps cite it, so
deleting it would dangle references in files this task does not own — which is
worse than a document that records a construct whose refusal is landed and whose
ceiling is zero by design.

**What is open, and where each piece went (2026-10-03).** This section used to
point at "§4's TASK 2 (the loop-aware termination bound)" and "§A4 on the
x86-64 side", and **neither section exists in this document** — the references
were left behind by the rounds that rewrote it, so a reader following them found
nothing. Both are answered elsewhere now, and the pointers are:

* **The loop-aware termination bound.** A dylib export whose body loops still
  gets a NAMED obligation rather than a proof of `Total`, because
  `DylibExport.total_of_halts` consumes an acyclic, call-free CFG walk. Scoped
  and measured (four exports classified by the method the frame-bounds document
  prescribed) in `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §5-§6. It
  is a scheme extension — a ranking function or a fuel invariant — and it is
  `formal/` work on the emitter side plus Lean work in the library, not a change
  to the classifier this document is about.
* **The x86-64 side.** Answered, and the answer was a defect rather than a data
  point: `fire.py dylib --formal --backend=x86_64` built an **arm64** image
  (`--backend` is a global flag the `dylib` command never read) and
  `compile_formal_dylib(arch="x86_64", prove=True)` raised `KeyError` out of
  the arm64 generator. Both are now refused by name. Recorded with the
  measurement in `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §3, and
  pinned by `test_formal_dylib.py`'s `a proved dylib is an arm64 artifact, and
  says so`.

**And the clause every arm keeps now has a test.** §3 says the five arms all
open with `which is a name with no definition in hand` and that this is
load-bearing, because two taxonomies key on that exact substring while the
message itself begins `a X receiver is passed to …` — the receiving family's own
opening. It also records that the first version of the split had four arms that
did **not** keep it. Nothing tested it, so the same edit could be made again
silently. `test_refusal_taxonomy.py`'s `_no_def_callee_arm_checks` now asks the
question at the source rather than at a sample: one callee per arm (there are
**six** on this tree, not five — `UNIMPLEMENTED_BUILTINS` was added after this
document was written), three assertions each — the clause is present, both
tables classify the arm as `callee has no definition on this path`, and the
texts are pairwise distinct, since a shared text is the pre-split defect
returning and would pass the first two. Verified by breaking one arm's clause in
process: it produces exactly the predicted failure, both tools moving that arm
to `receiver passed as an argument` / `receiver passed to a call, position not
stated`.

## 6. How to reproduce the measurement

**The row's numbers** come from the sweep's own tooling, which is committed:

    python3 tools/formal_sweep.py            # the run that produced the log
    python3 tools/formal_sweep_causes.py --min 5 build/sweep.log

**The per-file ceiling** needs one build per file with this refusal suppressed
IN-PROCESS — six lines, and no edit to the tree (which is why it is not a patch
and why it can be re-run on someone else's branch without touching it):

    import sys, os, tempfile; sys.path.insert(0, os.getcwd())
    from formal import model as M
    M.frame_undefined_callee_refusal = lambda *a, **k: None   # walk past it
    import formal.build as B
    B.compile_formal(sys.argv[1], prove=False,
                     output=os.path.join(tempfile.mkdtemp(), "a.out"))

Run it under a **cold CAS** (`env GMOJO_HOME=$PWD/.tmp/gmojo_nc`) — nine of the
twelve import most of the standard library, and `cas.formal_build_key` does not
fold a module's sources in (`FORMAL_sweep_cache_ignores_imports`), so a
warm CAS replays verdicts about those modules' old contents.

**The minimal programs** are `test_formal_run.py`'s `byref_refuse_*` cases —
imported free function, star import, compile-time parameter, reflection
intrinsic, bare method name, `print` of a frame, and the `byref_refuse_invisible_callee`
guard for the generic sentence — committed, each refusing identically on arm64
and x86-64:

    python3 test_formal_run.py byref_refuse_imported_free_function

**The 41-file census by arm** was taken with a parse-plus-one-pass probe rather
than 987 builds: the refusal is decided in `_prepare_functions`, which runs
before codegen, emit and link, so `formal.build.parse_module` +
`_imported_structs` + `_prepare_functions` per file answers "which refusal is
this file's" with no image and no CAS. That probe was scratch (`.tmp/`, not
committed — it is a one-off, and `tools/formal_sweep.py` is the committed
authority for the same question at the cost of a build per file).