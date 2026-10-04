# FORMAL_target_query_evaluator: what is left after the target-query evaluator landed

**Opened 2026-09-29. The construct `construct:comptime-mlir-attr` is LANDED and
this file records the residue, not the work.** The evaluator itself, the plumbing
and the suite are described in `FORMAL_known_limits.md` §2.0; this file is what
the reader needs when they ask "so why does `std/sys/info.mojo` still refuse?".

**Corrected 2026-09-30, after re-measuring every repro on this tree.** Blocker 3
below (`default parameter values`) is **CLOSED and was not a blocker at all** —
defaulted parameters are applied correctly, measured against CPython; and the
`__mlir_op` half of Blocker 2 is **CLOSED** (`FORMAL_known_limits.md` §2.2, which
said the construct still built and segfaulted and no longer does). Blocker 1 and
the `target_has_feature` half of Blocker 2 are unchanged, and the second of those
is a permanent refusal rather than a gap, so **`std/sys/info.mojo` still cannot
build and neither can the 37 files behind it.**

**Updated 2026-10-02: the ONE GAP the evaluator itself had (a query in a default
parameter value) is FIXED and LANDED — see §4. Nothing else here moved:
`std/sys/info.mojo` still does not build, for the two permanent refusals Blocker
1 names, so the file stands for the residue and only §4 is closed.**

**Updated 2026-10-03 (`work/formal10-6`): there was a SECOND gap of exactly §4's
shape, and it is FIXED and LANDED — see §5. A query in a struct field's
class-level initializer met none of the three walks, and it is two positions
rather than one (a `comptime` class attribute is not even in the tree), so both
were refused by a sentence about the wrong thing. Measured population: zero in
the stdlib, as §4's was — the value is in what the evaluator now answers wherever
the language lets a query be written, not in a coverage number. The residue is
unchanged and is still the residue: Blocker 1's two permanent refusals and the
`-mcpu=` feature of item 4.**

**Re-measured 2026-10-03 a second time (`work/formal16-8`): the gate this
document names is no longer the one that fires, and the one that does belongs to
another claim.** The table below says all three rows are stopped by "the dylib
export rule … a module that declares only a GENERIC struct template exports
nothing an importer can bind". That is no longer what happens. Measured today,
arm64, `python3 fire.py build --formal --no-prove -o .tmp/info.out
<stdlib>/std/sys/info.mojo`:

    build: info.mojo imports 'std.collections.string.string_span', which cannot
    be built either: binary_heap.mojo: BinaryHeap.pop() both changes its
    receiver and returns a value, and a formal value is one 64-bit word …

**So the import chain gets one module further than this document records**, and
the export rule this document points a reader at no longer fires first — the
blocker is now a body-level refusal inside `binary_heap.mojo`, whose subject is
`formal/model.py`'s `receiver_writeback_name` and which
`test_formal_run.py`'s `one_field_mutator_with_a_return_value_is_refused` pins.
**A planner who measured the gate this document names would measure the wrong
thing**, which is the whole reason this correction is here rather than left for
the next reader to discover.

What that changes about the two open items, and it changes nothing else:

* **item 1 (the `comptime`-type-binding site vocabulary)** is still deliberately
  not done, for the reason this document already measured — doing it moves two
  files off the findings list, makes one of them WORSE (`variadics.mojo` gets a
  message about a shape the source did not use), and builds nothing. It is now
  also behind THREE blockers rather than two, so the bargain has not improved.
* **item 4 (a per-CPU input for `target_has_feature`)** is still the only item on
  the list that could ever let the 37-file family build, still a feature rather
  than a fix, and now behind three blockers: the mutator-return shape above, the
  `!kgen.target` type binding, and `_current_target()`'s own body.
* **item 2 (the import diagnostic)** is closed and was closed on 2026-09-30.
* **`target_has_query_evaluator`'s own landing evidence is unchanged**:
  `python3 test_formal_target_queries.py` is 32/0 today, including the four §5
  checks and the two §4 ones, so nothing about the evaluator regressed while the
  gate in front of its consumer moved.

**Updated 2026-10-03: this document's own rows are no longer reachable, and its
item 1 is closed by a message rather than by a new site kind.** Both measured on
this tree (`python3 tools/formal_sweep.py -j 3 -t 120 <the three files>`, arm64):

| file | what this document measured in 2026-09-30 | what it says now |
|---|---|---|
| `std/sys/info.mojo` | the `!kgen.target` binding, then `_current_target` as a value | `codegen/dependency` — `info.mojo` imports `std.collections.string.string_span`, which imports `binary_heap.mojo`, and a module that declares only a GENERIC struct template exports nothing an importer can bind |
| `std/builtin/coroutine.mojo` | `_suspend_async: __mlir_op is an MLIR dialect construct` | `codegen/dependency`, same import chain |
| `std/builtin/variadics.mojo` | `Self.reduce[…]` is a subscript whose index is a tuple | `codegen/dependency`, same import chain |

The gate is the **dylib export rule** and it fires before any body is looked at,
so none of the three rows can be reached without it moving — which is row 2 of
the gate table in `bugs/FORMAL_sweep_work_map_2026-09-30.md` and not this
document's subject. A reader planning against any of the three rows should
measure that gate first; the refusals this document quotes are still the ones
those files carry when they are built as images, and they are still true.

**Item 1 is closed as a diagnostic, and the site-vocabulary change it sketched
is moot.** A module-level `comptime` binding initialised from an MLIR *type*
template is refused with a message that now names the consequence and not only
the template:

```
build: the module-level comptime binding '_T' is initialized from an MLIR type
template: __mlir_type.`!kgen.target` names an MLIR TYPE, not a value: the
template's elements are backtick-quoted type fragments and the whole thing
denotes a type, and a type is not something a register can hold on a path where
the only value is a 64-bit word. Refused rather than read out of a register,
which would give a program a number no source wrote.
```

That is what "a deliberate change to the `declared`/`comptime` site vocabulary,
with a new message for 'bound to a type', not as a one-line skip" asked for, and
it was made as wording rather than as a new site kind — which is the better
version of it here, because the binding is REFUSED before any read exists: there
is no `var _TargetType` in any surviving program to give a name-with-no-value to.
The two files this document measured moving (and `variadics.mojo` moving for the
worse) are behind the import gate above and cannot be re-measured.

What is left here is unchanged and is still not a bug: `target_has_feature` is a
refusal by design (a CPU feature is a property of a CPU, and this build names
the architecture it emits and never a CPU), `info.mojo` reads the target itself
as a value, and closing either is the per-CPU feature item 4 below.

The one-line answer: the target-query evaluator is not the next blocker. Two
other constructs are, in this order, and each is outside the claim that landed
the evaluator.

## What was measured, and what moved

`python3 tools/formal_sweep.py <files>` on this tree, arm64, 2026-09-29, before
and after `45f73c7` + `c64dc6a`:

| file | before | after |
|---|---|---|
| `std/sys/info.mojo` | `CODEGEN` — "the module-level comptime binding '_TargetType' is initialized from an MLIR **attribute** template" | `CODEGEN` — the same binding, now "an MLIR **type** template … names an MLIR TYPE, not a value" |
| `std/builtin/dtype.mojo` | `CODEGEN` — `_mIsSigned = __mlir_attr.\`#kgen.simd<1> : !kgen.scalar<ui8>\`` | unchanged (a dialect attribute — the half that is a true limit) |
| `std/builtin/type_aliases.mojo` | `CODEGEN` — `AnyOrigin = __mlir_attr[\`#lit.any.origin : !lit.origin<\`, …]` | unchanged (dialect attribute) |
| `std/builtin/rebind.mojo`, `std/builtin/simd.mojo`, `std/reflection/reflect.mojo` | `CODEGEN` — `#kgen.downcast<…>`, `#lit.struct<…>`, `#kgen.struct_field_types<…>` | unchanged (dialect attributes) |
| `std/gpu/host/compile.mojo`, `std/os/env.mojo`, `std/sys/_libc.mojo`, `std/subprocess/subprocess.mojo`, `std/bit/mask.mojo`, `std/gpu/globals.mojo` | `CODEGEN/DEPENDENCY` through `info.mojo` | `CODEGEN/DEPENDENCY` through `info.mojo` — **unmoved** |
| `std/collections/string/string_slice.mojo` | `CODEGEN/DEPENDENCY` | `CODEGEN` (a frame-receiver analysis limit, unrelated) |

**Zero files moved, and that is the honest headline.** The evaluator turned a
*false claim* into a *true* one — `info.mojo`'s binding is a type, and every
`#kgen.param.expr<…>` query in the file is now answered where it appears — but
`info.mojo` cannot build, so nothing downstream of it moves either. A reader
who expects the 46-file family to shrink should not.

## Blocker 1 — the `!kgen.target` TYPE binding, and `target_has_feature`

`std/sys/info.mojo` line 25:

```mojo
comptime _TargetType = __mlir_type.`!kgen.target`
struct CompilationTarget[value: _TargetType = _current_target()](TrivialRegisterPassable):
```

Three things, in the order they would have to be answered:

1. **A module-level `comptime` binding that names a TYPE.** The build has no
   type-level value, so the binding contributes nothing at runtime — and every
   read of `AnyCoroutine` / `_TargetType` in the stdlib is a type position
   (`var handle: AnyCoroutine`, `List[AnyCoroutine](…)`, `def(_resume_fn_type =
   def(AnyCoroutine) thin -> None)`), so it is *arguably* inert. The sound
   lowering is to record it as a name with no value (`collect_module_symbols`
   already has that state) so a VALUE read is refused by name.
   **Measured: doing that moves `std/builtin/coroutine.mojo` and
   `std/builtin/variadics.mojo` from `CODEGEN` to `CODEGEN/DEPENDENCY` and
   builds nothing new.** It was NOT done, deliberately: it turns a refusal that
   names the template into silence for those two files, and the four pins in
   `test_formal_run.py` that exist to catch a false PASS would each have to be
   rewritten. A worker who takes it on should do it as a deliberate change to
   the `declared`/`comptime` site vocabulary, with a new message for "bound to
   a type" — not as a one-line skip.

   **Re-measured 2026-09-30, with the skip applied as an experiment and then
   reverted** (`refuse_module_level_mlir_templates` not raising for a type
   template; nothing else changed), so that the recommendation above rests on
   what the three files then SAY and not only on their class:

   | file | before | with the type binding recorded as no-value |
   |---|---|---|
   | `std/sys/info.mojo` | `the module-level comptime binding '_TargetType' is initialized from an MLIR type template` | `_current_target: __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target` asks for the current TARGET itself, which is not a value on this path` |
   | `std/builtin/coroutine.mojo` | `… binding 'AnyCoroutine' is initialized from an MLIR type template` | `_suspend_async: __mlir_op is an MLIR dialect construct` — **its own body** |
   | `std/builtin/variadics.mojo` | `… binding '_IntToXGeneratorType' is initialized from an MLIR type template` | `Self.reduce[False, Self._AnySatisfiesReducer[…]] is a subscript whose index is a tuple` — **worse**: that bracket is a generic's explicit-parameter list, not a subscript, which is the shape `FORMAL_env_family_next_terminal.md` §2 files |

   So: two files get a deeper and more useful limit, one gets a message that is
   about a shape the source did not use, and **nothing builds** — `info.mojo`'s
   next refusal is `current_target` as a VALUE, which is as permanent as
   `target_has_feature` (a target is a description, not a 64-bit word), so item 2
   below is not the only thing between this module and a build; there are two
   permanent refusals in it. That is the measurement behind "not done
   deliberately": the change costs a new site kind, a new refusal message and
   four rewritten pins, and buys a mixed diagnostic in three files and no image.

2. **`target_has_feature`** (`_has_feature`, line 87) — refused on purpose. A CPU
   feature is a property of a CPU and the build names the architecture it emits
   and never a CPU. It IS a rule, and the two rules that could be derived
   without a database ("impossible for this architecture", "mandatory for it")
   would still leave `dotprod` / `i8mm` / `avx2` / `amx-tile` undecided. **This
   alone keeps `info.mojo` from building**, because `compile_module` lowers
   every function in the file. Closing it needs a per-CPU input (a `-mcpu=`-shaped
   flag on `compile_formal`, and a table) — a real feature, not a fix.

   **Not the only permanent refusal in the file.** `compile_module` lowers every
   function, and `_current_target()`'s own body —

   ```mojo
   def _current_target() -> _TargetType:
       return __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`
   ```

   — asks for the target as a VALUE, which this path refuses ("a target is a
   description, not a 64-bit word"). Its FIELDS answer; the target does not. So
   a worker planning a per-CPU input should know that answering
   `target_has_feature` is necessary and not sufficient: `info.mojo` reads the
   target itself, and the module-level binding that TYPES it is refused too.
   Measured, not inferred — see the table in item 1, where that is the message
   `info.mojo` reports once the binding is out of the way.

3. **`default parameter values` — CLOSED, and it was never a blocker.**
   `def _triple_attr[target: _TargetType = _current_target()]()` and 8 more in
   the same file default a parameter, and the question this item asked was
   whether the value is applied or silently bound to 0 — a wrong answer rather
   than a refusal. **Measured 2026-09-30: it is applied.** On this tree

   ```mojo
   def f(x: Int = 7, y: Int = 3) -> Int:
       return x * 10 + y
   def g(n: Int) -> Int:
       return n + f()
   def main() -> Int32:
       return g(20)
   ```

   builds for arm64 and for x86-64, and the image's exit status is 93 — which is
   `20 + 73`, and is what CPython gives the same program (`raise
   SystemExit(main())`, since a formal entry point's return value is the exit
   status). So the failure mode this item feared does not exist, and
   `_specialization_args` / the call rewriting do not need auditing for it.
   What remains true about the nine defaults in `info.mojo` is only that they
   default to a CALL, which is a different question and one this item did not
   ask.

## Blocker 2 — the import cycle, and a diagnostic that names the wrong thing

With the module-level refusal out of the way, `info.mojo` stops on its IMPORTS,
and the terminal is a cycle:

```
std/collections/string/string_slice.mojo:45   from std.sys import simd_width_of
std/sys/__init__.mojo:25                      from ._assembly import inlined_assembly
std/sys/_assembly.mojo:22                     from std.collections.string.string_slice
                                              import _get_kgen_string
```

The refusal this file used to quote, verbatim:

```
inlined_assembly: '_get_kgen_string' is imported from
`std.collections.string.string_slice`, so it is a module-level name of another
module. This path compiles an import into a dylib, and a module-level name is
not exported as a word … Give it a function (a
`std.collections.string.string_slice.fn()` call lowers) or write the value at
the use site
```

**Re-measured 2026-09-30: that sentence no longer appears for this file.**
`_assembly.mojo`'s own body now reports the construct it is written in —
`inlined_assembly: __mlir_op is an MLIR dialect construct` — because the MLIR
refusal is asked before the per-name walk now
(`formal/build.py`'s `first_mlir` pre-pass), and `NoneType` at line 94 no longer
gets there first. The message below is therefore about a construct the reader
will not see for `_assembly.mojo`, though the defect it describes is unchanged
and is still reachable elsewhere.

**That message is false about the file, and the defect it named is FIXED
(was `FORMAL_imported_generic_reported_as_a_module_level_name`, deleted
with the fix).** `_get_kgen_string` IS a function
(`std/collections/string/string_slice.mojo:2564`,
`def _get_kgen_string[string: StaticString, *extra: StaticString]()`), so the
advice "give it a function" is already satisfied. The real reason it is not
available is that it is a **generic**, and `reflect.EXCL_GENERIC` excludes
generics from a module's export set — which is also `FORMAL_known_limits.md` §1.1's
verdict for `std/sys/_assembly.mojo` (17 of family 1's 30 files, "true limit").

The fix was not a new message and not a fifth branch of
`module_global_refusal`: `model.imported_callee_refusal` already existed,
already named `doc/ABI.md`'s export rule, and already cited `_get_kgen_string` as
its measured case. It was simply not being ASKED of a BARE callee — only of a
bracketed one — so `widen(5)` reached the link audit instead. `formal/build.py`
now asks it before the callee exemption, over a set of bare `IdentExpr` callees
(`bug:FORMAL_imported_generic_reported_as_a_module_level_name`, 2026-10-01).

So Blocker 2 is two things, and neither is the target-query construct:
- the cycle itself (`string_slice` → `std.sys` → `_assembly` → `string_slice`),
  which `formal/imports.py`'s dylib build resolves by refusing the second visit;
- the `__mlir_op.`pop.inline_asm`` body of `inlined_assembly`, which is now
  **refused** — §2.2 of `FORMAL_known_limits.md` said it "builds and segfaults"
  when that was measured in wave 5, and it no longer does; the section has been
  rewritten with the re-measurement.

**Neither is fixable into a build, and that is the finding worth stating
plainly:** `_assembly.mojo`'s entire purpose is inline assembly, which a
freestanding image has no representation for. So the `_get_kgen_string` import
cannot be the blocker it appeared to be — the body is fatal whether or not the
import resolves — and no work on the import moves any of the 17 files behind
this module. What the import diagnostic is still worth is the reader's first
thirty seconds on any OTHER file that hits it.

## The order that would actually move files

1. ~~§2.2's `__mlir_op` refusal~~ — **DONE**, measured on both architectures for
   three spellings; `_assembly.mojo` is an honest refusal now. It did not
   unblock the cycle, and nothing would: the module cannot build at all.
2. The `imported`-branch diagnostic (own bug doc) — makes the next reader's
   first thirty seconds correct on a file whose real blocker is something else.
3. The `comptime`-type-binding site (this file, item 1) — two files off the
   findings list, nothing built.
4. A per-CPU input for `target_has_feature` — a feature, and the one that
   `info.mojo` needs. **This is the only item on the list that could ever let
   the 37-file family build**, and it is a refusal by design, so "letting it
   through" means a `-mcpu=`-shaped input to `compile_formal` plus a table — not
   a fix to a bug.
5. Only then the family's count means anything.

## What the landed change is verified by

`python3 test_formal_target_queries.py` — 25 checks, `PASS=25 FAIL=0` on
2026-09-30. The executed half builds the arm64 image, RUNS it and compares
against values the test states independently of the code under test (CPython for
`pointer_width`, `endianness`, `os` and `cross_compilation`; a commented
literal, with its provenance, for `simd_bit_width` and the `aarch64` spelling).
The refused half runs on **both** architectures. `python3 test_formal_run.py`
`PASS=398 FAIL=0` on the same day (the 341 this section used to quote predates
the cases added since; the floor, not the number, is the claim).

## §4 — the evaluator's own gap: a query in a DEFAULT PARAMETER VALUE, now closed

It answered a query wherever it met one in a FUNCTION BODY —
`formal/build.py:_fold_target_queries` — and `collect_module_symbols` answers one
in a MODULE-LEVEL `comptime` binding. A query in a **DEFAULT PARAMETER VALUE**
met neither: the value is not in `fn.body`, so the rewrite never saw it, and the
emitter substituted the node into the call at the call site
(`formal/arm64_codegen.py`'s `_emit_call`), where it was refused with the
multi-index MLIR wording — "assembles an MLIR attribute from a template", which
is false of a query `formal/model.py` answers everywhere else:

```mojo
def f(x: Int = __mlir_attr[
    `#kgen.param.expr<target_get_field,`,
    __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,
    `, "pointer_width" : index`, `> : index`]) -> Int:
    return x
```
```
build: __mlir_attr[… assembles an MLIR attribute from a template of backtick-quoted
literal fragments … there is no MLIR on this path for the template to become
```

**Measured population when this was found: ZERO**, and that is why it sat: every
default parameter value in the stdlib mentioning an `__mlir_` name is zero, and
`std/sys/info.mojo`'s nine defaulted parameters default to a CALL, not to a
query. So nothing real was affected and nothing real was fixed either — the
answer is that a construct the build handles is refused in one of the three
positions it can be written in.

**Landed 2026-10-02 (`417b9833`).** `_fold_target_queries` now walks
`fn.param_defaults` as well as `fn.body`, and `_fold_target_queries_in` handles
a `dict` (mutating it in place, never replacing it; keys are parameter NAMES and
a name is not an expression). Nothing about what the emitter substitutes changed
— the fold happens before anything reaches it, which is the whole reason the
rewrite lives in the shared pipeline.

Before (master's `formal/build.py`, same source, arm64):

```
build: __mlir_attr[`#kgen.param.expr<target_get_field,`, …] assembles an MLIR
attribute from a template of backtick-quoted literal fragments and compile-time
sub-expressions: it is not a subscript, and there is no MLIR on this path for the
template to become.
```

After, on both architectures — and the value is read through a call that OMITS
the argument, so this also pins that the folded literal is what
`model.bind_call_arguments` substitutes rather than only that the tree changed:

```
def g(n: Int) -> Int:  return n + f()
def main() -> Int32:   return g(20)
                       arm64 exit 84    x86_64 exit 84      (20 + pointer_width)
```

**The refused half is the more interesting half of the fix.** A query in a
default that this build CANNOT answer is left whole by the walk, exactly as in a
body, and is now refused with the message that names the missing fact rather than
with the template's shape:

```
build: this build cannot answer this target query: the current target
arm64/darwin (a macho image for arm64) has no 'triple' for this build to state:
the field is a property of a target DESCRIPTION …
```

Before the change the same program got the multi-index wording, which is a
message about a construct the build answers elsewhere and which no reader can
act on. That is the general shape of what was wrong: not one position missing a
case, but a position that fell through to a DIFFERENT rule, so the diagnostic a
reader got depended on where in the source they wrote the query.

**Three checks in `test_formal_target_queries.py`** (28 now, was 25):

* `a_query_in_a_default_parameter_value_is_replaced` — a UNIT check of the walk
  (`DEFAULT_WALK`), reporting the default's VALUE (`x=64`) rather than a count,
  because "no template is left" and "the right literal replaced it" are different
  claims and only the second is the answer;
* `a_query_in_a_default_parameter_value_is_folded` — EXECUTED, the exit status
  above, on arm64 as every executed case in that file is;
* `an_unanswerable_query_in_a_default_parameter_value_is_refused` — REFUSED on
  **both** architectures, so the two halves cannot trade places.

`test_formal_run.py`'s default-parameter cases (`constr_default_still_works`,
`constr_partial_fill_uses_the_field_defaults`,
`init_assigned_class_default_still_governs_the_value`,
`both_arch_a_defaulted_stack_argument`, `struct_default_word_opaque`) pass: 15
checks, 0 failures — the fold adds a walk over a dict and changes nothing for a
default that holds no query.

**What is left here is unchanged, and it is the part that matters:** two
permanent refusals in `std/sys/info.mojo` (the `!kgen.target` type binding, and
`target_has_feature`), so the 37-file family still does not build. See §1 and
"The order that would actually move files" above.

## §5 — the second gap of §4's shape: a query in a CLASS-LEVEL initializer (closed 2026-10-03)

§4 closed one position a query could be written in and not reach a walk. This is
the other one, and it is **two** positions rather than one — which is why it took
a measurement to find rather than a reading of the code.

A struct's body holds a field list and a method list, and neither is anywhere
`_fold_target_queries` looks: it walks `fn.body` and `fn.param_defaults`, and
`collect_module_symbols` answers a module-level `comptime` binding. A query as a
field's class-level initializer met none of the three:

```mojo
struct S:
    var w: Int = __mlir_attr[
        `#kgen.param.expr<target_get_field,`,
        __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,
        `, "pointer_width" : index`, `> : index`]
```

| | before | after (both architectures) |
|---|---|---|
| `var w: Int = <query>`, read `s.w` | `s.w reads a class-level constant of S, whose value is `__mlir_attr[…]` — and a formal value is one 64-bit word with nowhere to keep a non-literal one: a class-level constant's value is written in the class body, and this path has no module-global storage to read it back out of` | builds, prints `w=64` |
| `comptime W = <query>`, read `S.W` | the same refusal with the `comptime` half's reason ("often a CALL or a COMPUTATION rather than a literal, and this path has no comptime evaluator to run one") | builds, prints `w=64` |
| either, with a query this build CANNOT answer (`triple`) | the same two sentences | **refused with the evaluator's own**: `this build cannot answer this target query: the current target arm64/darwin … has no 'triple' for this build to state` |

The before column is the §4 defect again and not a wording problem: both
sentences are about STORAGE — a class-level constant's value has nowhere to live
— and both are false of a value that is one 64-bit literal the evaluator hands
over. A `var w: Int = 64` in the same position builds and prints `64` on both
architectures (measured), so the position is representable and only the fold was
missing.

**The second position is the one with the moving part.** A `comptime` class
attribute's value is not in the tree at all: `collect_module_symbols` parks it in
a dict on the struct and `struct_class_constants` reads it back out of there.
So folding it means writing the replacement back into that dict, by identity —
which is also the half the STDLIB needs, since `_PLUGIN_COUNT`,
`FPUtils.integral_type` and `_Null._mlir_type` are all `comptime` class
attributes. `formal/build.py`'s new `_fold_a_class_level_default` asks that dict
first and then walks the struct for a `value` slot holding the same node, and
`formal/model.py`'s `struct_class_constants` is what makes the identity exact.

Asked **at the read** (`_apply_constant_sites`) rather than by adding the class
body to `_fold_target_queries`'s input, because of ORDER and the order runs the
other way: `_rewrite_class_constants` — which is what reaches `_apply_constant_sites`
— runs BEFORE `_fold_target_queries`, whose call site says it is last on purpose.
So this read is the first thing to see a class-level initializer at all.

Four checks in `test_formal_target_queries.py` (32 now, was 28): two EXECUTED,
one per position, each comparing against the host's own `pointer_width` rather
than a literal this file could have got wrong in the same direction as the
implementation; and two REFUSED, one per position, on **both** architectures. The
refused half is what makes the executed half trustworthy — a fold that
substituted a zero would have printed `0` and passed nothing else.
