# FORMAL_target_query_evaluator: what is left after the target-query evaluator landed

**Opened 2026-09-29. The construct `construct:comptime-mlir-attr` is LANDED and
this file records the residue, not the work.** The evaluator itself, the plumbing
and the suite are described in `FORMAL_known_limits.md` §2.0; this file is what
the reader needs when they ask "so why does `std/sys/info.mojo` still refuse?".

The one-line answer: the target-query evaluator is not the next blocker. Three
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

2. **`target_has_feature`** (`_has_feature`, line 87) — refused on purpose. A CPU
   feature is a property of a CPU and the build names the architecture it emits
   and never a CPU. It IS a rule, and the two rules that could be derived
   without a database ("impossible for this architecture", "mandatory for it")
   would still leave `dotprod` / `i8mm` / `avx2` / `amx-tile` undecided. **This
   alone keeps `info.mojo` from building**, because `compile_module` lowers
   every function in the file. Closing it needs a per-CPU input (a `-mcpu=`-shaped
   flag on `compile_formal`, and a table) — a real feature, not a fix.

3. **`default parameter values`.** `def _triple_attr[target: _TargetType =
   _current_target()]()` and 8 more in the same file default a parameter to a
   call. Whether this path lowers a defaulted parameter at all is a separate
   construct; **not measured here** — whoever gets to it should check
   `_specialization_args` and the call rewriting in `formal/build.py` first,
   because a defaulted parameter silently bound to 0 would be a wrong answer
   rather than a refusal.

## Blocker 2 — the import cycle, and a diagnostic that names the wrong thing

With the module-level refusal out of the way, `info.mojo` stops on its IMPORTS,
and the terminal is a cycle:

```
std/collections/string/string_slice.mojo:45   from std.sys import simd_width_of
std/sys/__init__.mojo:25                      from ._assembly import inlined_assembly
std/sys/_assembly.mojo:22                     from std.collections.string.string_slice
                                              import _get_kgen_string
```

The refusal, verbatim:

```
inlined_assembly: '_get_kgen_string' is imported from
`std.collections.string.string_slice`, so it is a module-level name of another
module. This path compiles an import into a dylib, and a module-level name is
not exported as a word … Give it a function (a
`std.collections.string.string_slice.fn()` call lowers) or write the value at
the use site
```

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
- the `__mlir_op.\`pop.inline_asm\`` body of `inlined_assembly`, which §2.2 of
  that document already says **builds and segfaults** and should be refused.

## The order that would actually move files

1. §2.2's `__mlir_op` refusal (minutes, already scoped in
   `FORMAL_known_limits.md` §2.2) — turns `std/sys/_assembly.mojo` from a
   crash-on-first-instruction into an honest refusal. Does not unblock the cycle.
2. The `imported`-branch diagnostic (own bug doc) — makes the next reader's
   first thirty seconds correct.
3. The `comptime`-type-binding site (this file, item 1) — two files off the
   findings list, nothing built.
4. A per-CPU input for `target_has_feature` — a feature, and the one that
   `info.mojo` needs.
5. Only then the 46-file family's count means anything.

## What the landed change is verified by

`python3 test_formal_target_queries.py` — 25 checks, `PASS=25 FAIL=0`. The
executed half builds the arm64 image, RUNS it and compares against values the
test states independently of the code under test (CPython for `pointer_width`,
`endianness`, `os` and `cross_compilation`; a commented literal, with its
provenance, for `simd_bit_width` and the `aarch64` spelling). The refused half
runs on **both** architectures. `python3 test_formal_run.py` `PASS=341 FAIL=0`.
