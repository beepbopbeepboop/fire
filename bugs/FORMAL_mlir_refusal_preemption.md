# FORMAL_mlir_refusal_preemption: the refusal that NAMES the construct loses to the one that names a symptom

**Status 2026-09-30: the next step below has LANDED and this file is the
remainder, not the work.** The dialect refusal is now asked in the pre-pass,
before the per-name walk, so within one function the verdict no longer depends
on which of two statements is written first. Measured over the population the
defect applies to: **6 files moved to an MLIR-naming verdict, 0 moved off one,
0 changed verdict class.** What is left is the last paragraph of this file, and
it is a decision rather than an oversight.

Found while closing the `_get_kgen_string` import-resolution gap on
`std/sys/_assembly.mojo`. It is a diagnostic-accuracy defect and not a
coverage one: every file affected is refused either way, and no image is wrong.

## The failing program

```mojo
def main() -> Int32:
    var q = Unplaced                       # a genuine unplaced name
    var v = __mlir_op.`pop.inline_asm`[    # the construct that is actually fatal
        _type=None, assembly="nop", constraints="",
    ]()
    print(v)
    return 0
```

```
$ python3 fire.py build --formal --no-prove .tmp/ord/b.mojo -o .tmp/ord/b
build: main: 'Unplaced' has no home: the module-level symbol table is empty for
this unit, and the reading function declares no local or parameter by that
spelling. …
```

Reverse the two lines and the build says the useful thing:

```
$ python3 fire.py build --formal --no-prove .tmp/asm/main.mojo -o .tmp/asm/main
build: main: __mlir_op is an MLIR dialect construct. This path has no MLIR: it
lowers a Mojo program to a Mach-O image whose only value is a 64-bit word, and
an MLIR attribute, type or operation has no representation in one …
```

Same construct, same backend, same file's worth of source — the verdict is
decided by **line order**. `__mlir_op` has a precise, arch-free, already-written
refusal (`model.mlir_dialect_refusal`, asked from both backends through
`model.mlir_template_refusal`'s sibling call in `_emit_expr`); it loses to a
message that names a register table.

## Why this is the pre-emption and not a bug in either message

`check_module_symbols` walks the body in source order and raises on the first
name it cannot place. It already has a pre-pass for exactly this reason — the
`bracketed` map, built before the per-name walk, holding the refusals that
*name a construct*. The file's own comment says what the pre-pass is for:

> The two refusals that NAME the construct are asked first, through the ONE
> reader both backends use, so the better-worded message wins here rather than
> being pre-empted by the symptom.

That is implemented, and it holds — but only for `SubscriptExpr`/`MemberExpr`
spellings (`__mlir_attr[…]`, `__mlir_op.`lit.…``). The **dialect** refusal
(`__mlir_op`, a bare name with the `__mlir_` prefix) is reached by a separate
`name.startswith(M.MLIR_DIALECT_PREFIX)` branch *inside* the per-name walk, so
it is subject to source order like any other name. The pre-pass is half
implemented, and the half that is missing is the one that matters for
`std/sys/_assembly.mojo`.

`std/sys/_assembly.mojo` is the live case: `NoneType` at line 94 pre-empts
`__mlir_op.`pop.inline_asm`` at line 95, so the seventeen files behind that
module were told a type name has no register rather than that the file's whole
purpose — inline assembly — cannot be lowered at all.

## What landed

`formal/build.py`: the pre-pass records the FIRST MLIR construct the function
reaches — `first_mlir`, the `bracketed` entry when the construct is a template
and `model.mlir_dialect_refusal` when it is a bare name — and raises it before
the per-name walk. The walk's own dialect arm is GONE rather than kept as a
second opinion, because one reader asked twice is how two architectures come to
name different limits for one construct.

Three rules the implementation has to keep, each pinned by a case in
`test_formal_mlir_precedence.py` (7 cases; refusals asserted on BOTH
architectures):

1. **Source order still decides AMONG the MLIR constructs.** `__mlir_attr[…]`
   before a bare `__mlir_op` keeps its own more specific message, so a template
   is never downgraded to the generic dialect text
   (`an_attribute_template_keeps_its_own_refusal`,
   `a_type_template_keeps_the_type_refusal`).
2. **An ANSWERED target query is not pre-empted at all.** `#kgen.param.expr<…>`
   is a question this build answers, and `_fold_target_queries` has normally
   replaced it with the literal it denotes before this pass runs;
   `answered_roots` records the root identifier so the identifier arm and the
   template arm cannot disagree about one node inside one loop
   (`a_target_query_is_not_pre_empted`,
   `a_answered_query_does_not_pre_empt_a_missing_local`).
3. **The pre-emption is unconditional in the other direction**: a missing local
   and an MLIR construct in one function report the MLIR construct, in either
   order (`a_missing_local_above_the_dialect_construct_does_not_win` and its
   swapped twin).

## Measured, on this tree, before and after

The instrument matters here and it is NOT `tools/formal_sweep.py`: the sweep
resolves imports first and reports the chain's terminal, and for most of the
stdlib the chain's terminal is a different file's refusal — `_assembly.mojo`
itself is reported through `string_slice`. What the defect decides is the
verdict for a file's OWN body, so the measurement is
`formal/build.py:_formal_module_functions` per file (the dylib front end:
`_prepare_functions` + `_run_late_checks` on one unit, no import resolution).

Over the 88 stdlib files that mention `__mlir_` at all:

| | before | after |
|---|---|---|
| own-body verdict names an MLIR construct | 32 | **38** |
| …names something else | 42 | 42 |
| verdict class changed (`refusal` → anything) | — | **0** |

The 6 that moved, all of them from a placement message about a name:

| file | before | after |
|---|---|---|
| `std/atomic/atomic.mojo` | `fence: '__is_run_in_comptime_interpreter' has no home` | `__mlir_op` dialect construct |
| `std/builtin/globals.mojo` | `global_constant: 'StaticConstantOrigin' has no home` | `__mlir_op` |
| `std/memory/unsafe.mojo` | `SIMD[dtype, width] is a subscript whose index is a tuple` | `__mlir_op` |
| `std/sys/_assembly.mojo` | `inlined_assembly: 'NoneType' has no home` | `__mlir_op` |
| `std/sys/intrinsics.mojo` | `llvm_intrinsic: 'NoneType' has no home` | `__mlir_op` |
| `std/utils/numerics.mojo` | `nan: 'DType' has no home` | an `__mlir_attr` attribute template |

Restricted to the population this ordering decides — a dialect name reached by a
FUNCTION BODY, which is 40 of the 88, since a file that only mentions `__mlir_`
in a module-level binding is not in it at all (that binding is not part of the
walk): **18 named MLIR before, 24 after.** The denominator here is 40 and the
one in the original version of this file was 36 over `stdlib/` including
`test/` and `benchmarks/`, so the two tables' file counts are not comparable and
neither is claimed to be; what is comparable is each table against itself, and
both were taken with the per-file instrument described above.

## What is left: 16 of the 40 are decided by the order of two FUNCTIONS

The pre-emption is per function, because the loop it lives in is. So a file
whose MLIR construct sits in a LATER function than the refusal its earlier
function earns still reports the earlier one. Grouped by what the 16 report
today:

| what the file is told instead | files |
|---|---|
| a specific construct, accurately — a receiver shape, a frame-field premise, a user-defined `__init__`, a generic's explicit-parameter list | **9** — `ffi/__init__`, `iter/__init__`, `python/_cpython`, `runtime/asyncrt`, `compile/compile`, `collections/string/string_slice`, `memory/stack_allocation`, `io/io`, `os/os` |
| "… is a subscript whose index is a tuple", about a call whose bracket is really a generic's explicit-parameter list | **4** — `gpu/intrinsics`, `gpu/memory/memory`, `gpu/primitives/cluster`, `memory/memory` |
| an imported module-level name (`'GPUInfo' is imported from .info`) | **2** — `gpu/host/compile`, `gpu/primitives/grid_controls` |
| a placement message (`'DType' has no home`) | **1** — `gpu/compute/mma` |

**A per-FILE pre-emption is the wrong fix, and this table is the measurement
that says so.** It would convert the bottom seven rows and demote the top nine,
replacing nine specific and true sentences with one coarser true one — a
regression in precision paid for a gain in truthfulness, which is not a trade
this document's refusals are trying to make.

**The exact next step, for whoever wants it:** hoist `first_mlir` from the
function to the unit, and apply it ONLY against the two rows that are symptoms
rather than constructs — the placement refusal (`model.unresolved_name_refusal`
and its module-global sibling) and the imported-module-level-name refusal
(`model.module_global_refusal`'s `imported` branch). Both are decidable by which
reader produced the sentence, so the rule is mechanical rather than a judgement
about wording: **a refusal that names a construct is not pre-empted; a refusal
that names a symptom is.** That converts 3 files and demotes 0. The four
tuple-index files are left alone on purpose — their message is about a shape the
source did not use, and the construct that owns that judgement is the generic's
explicit-parameter list, which
`bugs/FORMAL_env_family_next_terminal.md` §2 and `FORMAL_known_limits.md` §1.2
already file.
