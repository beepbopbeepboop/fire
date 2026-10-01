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
(`FORMAL_mlir_refusal_preemption.md`), and `NoneType` at line 94 no longer gets
there first. The message below is therefore about a construct the reader will
not see for `_assembly.mojo`, though the defect it describes is unchanged and is
still reachable elsewhere.

**That message is false about the file, and it is a separate bug worth its own
doc: `bugs/FORMAL_imported_generic_reported_as_a_module_level_name.md`.**
`_get_kgen_string` IS a function (`std/collections/string/string_slice.mojo:2564`,
`def _get_kgen_string[string: StaticString, *extra: StaticString]()`), so the
advice "give it a function" is already satisfied. The real reason it is not
available is that it is a **generic**, and `reflect.EXCL_GENERIC` excludes
generics from a module's export set — which is also `FORMAL_known_limits.md` §1.1's
verdict for `std/sys/_assembly.mojo` (17 of family 1's 30 files, "true limit").

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

**One gap the evaluator itself has, found while looking for the next step and
not fixed.** It answers a query wherever it meets one in a FUNCTION BODY —
`formal/build.py:_fold_target_queries` — and `collect_module_symbols` answers one
in a MODULE-LEVEL `comptime` binding. A query in a DEFAULT PARAMETER VALUE
meets neither: the value is not in `fn.body`, so the rewrite never sees it, and
the emitter substitutes the node into the call at the call site
(`formal/arm64_codegen.py`'s `_emit_call`), where it is refused with the
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

**Measured population: ZERO.** Every default parameter value in
`../modular/mojo/stdlib` mentioning an `__mlir_` name — the only non-body
position an MLIR template occurs in anywhere in the stdlib, the other being a
module-level binding, which `collect_module_symbols` already answers — is zero,
so nothing real is affected and `std/sys/info.mojo`'s nine defaulted parameters
(which default to a CALL, not to a query) are not this. The repair is one walk
(`_fold_target_queries` over `fn.param_defaults` as well as `fn.body`, on the
`xc_type_args` argument: a default is compile-time by construction) and it is
**not done here**, because a change to what the emitter substitutes into a call
argument list is not worth making for a shape no source in the corpus writes.
