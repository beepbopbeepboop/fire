# FORMAL_mlir_unit_hoist_is_unreachable_on_the_new_stdlib: the documented next step converts 0 files, and the reason is a position no MLIR reader scans

**Status 2026-10-01: the step named in
[`FORMAL_mlir_refusal_preemption.md`](FORMAL_mlir_refusal_preemption.md) as
"the exact next step, for whoever wants it" was IMPLEMENTED and MEASURED on the
new-modular stdlib, and it converts ZERO files. It is not landed, and this file
is why. The claim it was written for does not exist in this tree.**

That is the whole finding, and it is a negative result worth having recorded
rather than re-derived: the fix is correct, cheap, and worth 0, because the
files whose verdict a per-FUNCTION pre-emption gets "wrong" do not spell an MLIR
construct anywhere the pre-emption looks.

## What was implemented, and what it did

`FORMAL_mlir_refusal_preemption.md`'s last paragraph asks for: hoist `first_mlir`
from the function to the unit, and apply it ONLY against the two rows that are
symptoms rather than constructs — the placement refusal
(`model.unresolved_name_refusal`) and the imported branch of
`model.module_global_refusal`. That is what was written: a unit-level scan
(`_first_mlir_in`, using the same `model.mlir_template_refusal` /
`mlir_dialect_refusal` / `template_is_answered` readers the in-function pre-pass
uses, so the two cannot disagree about what counts as a construct) consulted
only at those two raise sites.

**Measured, 73 stdlib files that mention `__mlir_` at all, own-body verdict
via `formal/build.py:_formal_module_functions` per file — the instrument the
pre-emption doc itself specifies, because the sweep's terminal is a different
file's refusal:**

| | with the hoist | without |
|---|---|---|
| own-body verdict names an MLIR construct | 27 | 27 |
| own-body verdict is a symptom | 46 | 46 |
| **verdict changed at all** | **0** | — |

The whole diff is empty. `bit/bit.mojo` still reports
`llvm_intrinsic['llvm.ctlz', type_of(…), False]` as a tuple-indexed subscript,
`_gpu/globals.mojo` still reports `'GPUInfo' is imported from .host.info`, and so
on.

## Why: the three files, and where their `__mlir_` actually is

The doc's own table predicted this population would be 16 of 40, and on the
OLD stdlib (`../modular`) it was: 4 tuple-index rows plus 3 imported-name rows
plus 1 placement row, all convertible by the rule "a refusal that names a
construct is not pre-empted; a refusal that names a symptom is". On the
new-modular tree the rows are the same SHAPES, and every one of them is a file
whose `__mlir_` is somewhere the rule cannot see:

| file | its symptom verdict | where its `__mlir_` is |
|---|---|---|
| `std/_gpu/globals.mojo` | `'GPUInfo' is imported from `.host.info`` | line 109, the **return type** of `_resolve_max_threads_per_block_metadata() -> __mlir_type.\`!kgen.string\`` — a TYPE position, not in `fn.body` |
| `std/memory/address_space.mojo` | `'CurrentPlugin' is imported from std._plugin` | lines 44 and 52, **struct field initializers** (`comptime GENERIC = AddressSpace(__mlir_attr[...])` inside the `struct` body) — a `StructDef`'s members, not a function's |
| `std/io/file_descriptor.mojo` | `'CompilationTarget' is imported from std.sys` | lines 76 and 78, `self.value.__mlir_index__()` and `len(bytes).__mlir_index__()` — a METHOD NAME on a value, not a bare dialect root |
| `std/bit/bit.mojo` | the tuple-index refusal | line 86, `False.__mlir_i1__()` — the same shape, a method name |

So of the four, three have no dialect construct at all: `__mlir_index__` and
`__mlir_i1__` are the compiler's intrinsics for an index and an `i1`, called as
methods on values, and neither `mlir_template_refusal` nor `mlir_dialect_refusal`
claims them (measured: a function whose only `__mlir_` is `__mlir_i1__` is
reported through its construct, never through the dialect arm). The fourth,
`_gpu/globals.mojo`, has one, and it is a **return-type annotation**, which
`check_module_symbols` never walks and which this path treats as INERT —
measured, and this is the load-bearing measurement for whether the hoist should
be widened rather than dropped:

```mojo
def f() -> __mlir_type.`i8`:
    return 1

def main() -> Int32:
    return 0
```
```
$ python3 fire.py build --formal --no-prove .tmp/rt.mojo -o .tmp/rt
Built: .tmp/rt  [arm64/macho]
```

An MLIR type in a return position builds. So pre-empting `_gpu/globals.mojo`'s
`'GPUInfo' is imported from .host.info` — a specific, true, actionable sentence
naming the module and the reason a name has no home — with an MLIR refusal about
a type annotation the build happily ignores would be a **demotion**: exactly the
trade `FORMAL_mlir_refusal_preemption.md`'s middle section rules out ("a
regression in precision paid for a gain in truthfulness, which is not a trade
this document's refusals are trying to make").

## The census, for the next reader

Own-body verdict, `formal/build.py:_formal_module_functions` per file, the 73
new-modular stdlib files that mention `__mlir_` at all (this is the population
the pre-emption doc's denominator 40 was drawn from, re-measured):

* **27 name an MLIR construct**, and that is the honest number. Twelve of the 27
  are the module-level `comptime`-binding case
  (`std/{sys/info, builtin/{_coroutine,dtype,enum_like,rebind,type_aliases},
  reflection/reflect, simd, _gpu/host/{info,_builtin_targets}, origin/__init__,
  _gpu/_utils}.mojo`), which `collect_module_symbols` refuses by a rule of its
  own and `FORMAL_target_query_evaluator.md` item 1 measured and declined; the
  other 15 are a dialect root or a template reached from a function body, and
  those are the ones `first_mlir` is about.
* **8 are already `BUILDS`** (`_plugin/{_trait,cuda/cuda_plugin,hip/hip_plugin,
  metal/metal_plugin}`, `builtin/{_closure,_stubs,int,none}`) — an `__mlir_`
  mention is not by itself a construct.
* **4 are decided by two FUNCTIONS** (the table above). This is the residue,
  and it is 4 files, not 16.
* **32 are decided by a DIFFERENT construct entirely**, and the doc's list of
  them is the right one to work from: the frame-escape family (`atomic`,
  `collections/string/{string,string_span}`, `compile/compile`,
  `python/_cpython`, `utils/{coord,variant,static_tuple}`, `format/tstring`),
  the `type_of`/`__get_mvalue_as_litref` intrinsics (`memory/pointer`,
  `builtin/{none,tuple}`, `collections/{_conditional,optional}`,
  `ffi/unsafe_union`), and the bracketed-callee family (`builtin/bool`,
  `math/math`, `memory/memory`, `memory/stack_allocation`).

## The exact next step, if anyone wants one

Not the hoist. The three files with a real dialect construct outside every
scanned position need their refusal asked at the position, which is a
**different** change per position and none of them is a hoist:

1. **Struct-field initializers** (`memory/address_space.mojo:44,52`).
   `M.iter_nodes(fn.body)` never sees a `StructDef`'s members. A
   `refuse_module_level_mlir_templates`-style walk over struct bodies — the
   sibling of the module-level walk `collect_module_symbols` already does —
   would refuse the construct at its own site, which is where the other 10
   module-level ones are already refused. That is the closest thing here to a
   free conversion, because it converts a file whose verdict becomes an MLIR
   refusal rather than pre-empting a better one: `address_space.mojo`'s
   `'CurrentPlugin' is imported` is a boundary fact, and the struct field's
   template is fatal whether or not the import resolves. **Untested — measured
   only that the construct is there and is not currently seen.**
2. **`__mlir_index__` / `__mlir_i1__`** (`io/file_descriptor.mojo:76,78`,
   `bit/bit.mojo:86`). These are a genuine gap and NOT a diagnostic one: two
   intrinsics this path has no reader for, reached as method calls on values, so
   they fall through to whatever method-call or subscript message the call
   happens to earn. The question is what they denote — an index (a width) and an
   `i1` (a boolean) — and both are things this path can materialize, so this may
   be a real construct to lower rather than a refusal to sharpen. It is outside
   the claim this was measured under (`construct:mlir-and-gpu-globals`), which is
   why it is written down here rather than started.
3. **Return-type annotations** (`_gpu/globals.mojo:109`). **Do not.** Measured
   inert above, and acting on it is the demotion this file exists to prevent.

`FORMAL_mlir_refusal_preemption.md`'s "exact next step" paragraph should be
struck rather than left for the next worker to implement: on this tree it is a
no-op, and the paragraph's own table is what makes that visible — it was measured
on `../modular`, and three of the four rows it converts are files whose
`__mlir_` moved out of every position a pre-emption can see.

## Why this was not landed

A change that converts 0 files and adds a unit-wide AST walk to every compile is
a cost with no measurable benefit. `check_module_symbols` runs per function and
the added scan runs once per unit over the same bodies, so it is not free, and
the one thing it could have bought on this corpus is a worse message.