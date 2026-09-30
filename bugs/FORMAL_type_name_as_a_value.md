# FORMAL_type_name_as_a_value: a bare TYPE name in a value position is refused as a value with "no home"

> **The MESSAGE half is fixed. The COVERAGE half is not, and by design** — it
> needs a decision about whether a type is a value on this path at all, which is
> a reflection-table question and belongs to whoever owns the type table. What
> landed is the cheap half the doc asked for, and it is the half that was
> actionable: 32 of the 664 stdlib files now get a refusal that is TRUE about
> the file instead of one that sends the reader to the register allocator. The
> two backends still refuse every one of them, and the sweep's own accounting is
> byte-identical before and after.

## Status (2026-09-30 — the construct refusal landed, with the census this
## file asked for)

`model.is_type_name` + `model.type_as_value_refusal`, asked from
`formal/build.py`'s `check_module_symbols` in the same pre-pass as the MLIR
construct rules, so the better-worded message wins rather than being pre-empted
by the symptom.

## The reproducer, before and after

```mojo
def pick[t: DType](v: Int32) -> Int32:
    if t == NoneType:
        return 0
    return v
```

**Before**, on both architectures:

```text
build: main: 'Int32' has no home: the module-level symbol table is empty for
this unit, and the reading function declares no local or parameter by that
spelling. This path places a name in a register or a spill slot allocated for
THIS function, a receiver field's frame, or a module-level constant the build
folded — and a name in none of them is refused rather than read out of whatever
register the allocator left behind, …
```

**After**, byte-identical on arm64 and x86-64:

```text
build: main: 'Int32' is a TYPE, and a type is not a value on this path: a value
here is one 64-bit word, and a type is not one thing a word can hold. So there
is no register, spill slot, frame field or folded constant this could live in —
the question those four places answer is the wrong question for a type.
Comparing a `comptime` type parameter against a type name (`t == Int32`),
testing one with `is`, or passing one as an argument all need types to be
values: an interned tag per type, identical on both sides of a dylib boundary,
which is reflection-table work this path does not have. Branch on something the
word model can tell apart — a flag or an extra parameter the caller passes, a
separate function per case, or a property of the value itself rather than of
its type.
```

## The census, measured on this tree (not copied from the original report)

`check_module_symbols` run over every `.mojo` under
`../modular/mojo/stdlib/std`, before and after, on the same tree, 664 files,
17 s a run:

| verdict | before | after |
|---|---|---|
| not refused at all | 126 | **126** |
| refused as an imported module-level name | 305 | **305** |
| refused as `'<name>' has no home`, name is a **value** | 47 | **47** |
| refused as `'<name>' has no home`, name is a **type** (the false diagnosis) | 30 | **0** |
| refused as "a TYPE is not a value" (the true one) | 0 | **30** |
| any other refusal (multi-index, explicit-parameter list, …) | 156 | **156** |

Type names, by how many files name them: `DType` 15, `List` 7, `Self` 4,
`Error` 1, `Optional` 1, `NoneType` 1, `String` 1. The two that moved
differently are below.

**Every one of the 30 is a wording change and not a coverage change**, which is
the point of the original report and is worth measuring rather than asserting:
`tools/formal_sweep.py` over exactly those 30 files, before and after, gives
**byte-identical** summary blocks — `codegen 14`, `codegen/dependency 18`,
`codegen coverage 0/32`, denominator 32, and the same per-family counts. A
file that was refused is still refused; what changed is which sentence explains
it. (`test_formal_sweep_truth`, which pins the classifier, is green.)

## Two names that are BOTH a type and an imported module symbol

`std/benchmarks/collections/bench_set.mojo` (`Set`) and
`std/testing/prop/strategy/list_strategy.mojo` (`List`) both say
`from std.collections import Set` / `import List`, and both were refused as
"is an imported module-level name of another module … a module-level name is
not exported as a word". Asking the type question FIRST — which is what the
first version of this change did — replaced that with the type message, and it
was wrong for a reason worth recording:

* the module message is not a symptom, it is MORE specific, and
* it carries a backtick-quoted module name, which is the convention
  `tools/formal_sweep.py` reads to file a verdict as
  `not-answerable/unresolved-import`. `model.module_global_refusal` says so in
  its own comment: the module is spelled in BACKTICKS and the single-quoted
  spelling "reclassified thirteen stdlib files from `codegen/dependency` into
  'imports a module that is neither host nor in this backend's module set'".

So the type question is now asked AFTER the module question, and for a name that
is both, **both facts are said** — the construct first, then the module fact
with its `fn:` prefix suppressed, indented so they read as two sentences. Both
files are back in the `imported` bucket and the sweep is unchanged.

The ordering lesson generalises, and it is the one worth taking from this file:
"the construct refusal must win over the symptom" is right, and it is not the
same claim as "the construct refusal must be asked first". `module_global_refusal`
is a construct refusal too — a more specific one — and asking the type question
ahead of it was a regression dressed as an improvement.

## What is a type here, and where the table comes from

`model.is_type_name` is the union of the four tables that already know type
names, because each answers a different question and a name in only one of them
is still a type:

| table | contributes | why it is not enough alone |
|---|---|---|
| `POINTEE_WIDTHS` | `NoneType`, `Byte`, `Bool`, `c_char`, `SIMDSize`, … | a width, not a type-ness test |
| `INT_TYPE_CTORS`, `IDENTITY_TYPE_CTORS` (via `type_constructor_kind`) | `Int`, `Int32`, `String`, `Pointer`, … | only what a bare `T(x)` call means |
| `UNREPRESENTABLE_TYPE_CTORS` | `DType`, `Optional`, `List`, `Set`, `SIMD`, `Error`, … | a statement about the VALUE, not the name |
| `Self` | `Self` | in no table |

A struct this unit compiles is deliberately NOT in it: `check_module_symbols`
already places those names, and its own docstring says the same thing this
message says — "a struct is not a value and has no register".

## What is still open, and it is the part that needs a decision

The coverage half. Making `t == NoneType` answerable means a type has to BE a
value: a tag per type, interned, and **the same on both sides of a dylib
boundary**, so it cannot be a per-unit small integer. That is `type_info`-
shaped work and it is not a local fix. The message says so rather than implying
the reader could fix it by naming a variable differently, and it names the two
things that DO work: branch on something the one-word model can distinguish (a
flag or an extra parameter, a separate function per case), or on a property of
the value rather than of its type.

`std/sys/_assembly.mojo:94` (`comptime if result_type == NoneType:`) is still
refused, now with an accurate sentence. It was never the terminal cause of a
sweep file on this tree — the chain that reaches it is seventeen files deep
through `_get_kgen_string` (see `FORMAL_known_limits.md` §1.1) — so lifting the
refusal would not move a sweep number by itself.

## The "do not" this file ended with, honoured

`is_type_name` is used for exactly one thing: choosing which WORDS a refusal
uses. It is never asked "can this name be read", because the answer to that is
always no, and `name_resolves_without_a_local` is the list of the ones that can.
The four cases in `test_formal_run.py` are the guards on that boundary:

| case | what it pins |
|---|---|
| `refuse_a_type_compared_with_a_comptime_parameter` | the doc's own repro, refused identically on both backends |
| `refuse_a_bare_type_name_as_a_value` | the other shape — a bare read, no comparison |
| `type_as_a_callee_is_still_a_construction` | **passes before and after**: `Int32(5)` is a construction this path lowers, so the rule must be about a READ. A rule written as "any appearance of a type name" breaks it. |
| `refuse_an_unplaced_value_keeps_the_storage_story` | **passes before and after**: `return rebind` still gets the storage enumeration, because for a value that enumeration is the right story. 41 of the 664 files are in exactly this position. |

The callee exclusion is not new: `check_module_symbols` already skips
`CallExpr.func` roots for the same reason it skips MLIR roots, since a callee
names a symbol rather than reading a value.
