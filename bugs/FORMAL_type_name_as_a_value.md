# FORMAL_type_name_as_a_value: a bare TYPE name in a value position is refused as a value with "no home"

Found while closing the `_get_kgen_string` import-resolution gap (see
`FORMAL_known_limits.md` §1.1, which records `std/sys/_assembly.mojo` as a
terminal module behind seventeen files). The false diagnosis that gap produced
is fixed and measured; this is the **next** construct on the same file, and it
is a different construct from the one that was fixed. It is a diagnostic-accuracy
defect, not a coverage one: every affected file is refused either way.

## The failing program

```mojo
def pick[t: DType](v: Int32) -> Int32:
    if t == NoneType:
        return 0
    return v
```

```
$ python3 fire.py build --formal --no-prove .tmp/tn/a.mojo -o .tmp/tn/a
build: pick: 'NoneType' has no home: the module-level symbol table is empty for
this unit, and the reading function declares no local or parameter by that
spelling. This path places a name in a register or a spill slot allocated for
THIS function, a receiver field's frame, or a module-level constant the build
folded — and a name in none of them is refused rather than read out of whatever
register the allocator left behind, …
```

**`NoneType` is a TYPE, and this message is about where a VALUE lives.** A
register, a spill slot, a frame field and a folded module constant are the four
places `unresolved_name_refusal` enumerates, and a type is in none of them
because a type is not a value and never was. The reader is sent to look at the
allocator when the answer is a fact about the language: `t` is a
`comptime` parameter carrying a type, `NoneType` names a type, and `==`
compares two types.

## Measured

`check_module_symbols` run over **every `*.mojo` under
`../modular/mojo/stdlib` (664 files)**, before and after the
specialization-callee fix, on the same tree:

| verdict | before | after |
|---|---|---|
| refused as an imported module-level name | 305 | **269** |
| refused as `'<name>' has no home` | 76 | **93** |
| not refused at all | 126 | **136** |
| files whose verdict changed | — | **52** (612 byte-identical) |

Of the 93 files now reporting `has no home`, **52 name a type** — up from 35
before, which is exactly the 17 files the specialization fix moved off the
false diagnosis in front of it. The type names are `NoneType`, `DType`, `Int`,
`Self`, `String`, `Byte`, `UInt8`, `UInt64`, … The other **41 are unchanged
and correct**: they name values (`debug_assert`, `rebind`,
`__is_run_in_comptime_interpreter`, `task_func`, …) that really are read in a
position with no storage, and the storage enumeration is the right story for
those. This is a pre-existing message defect that the fix above merely made
visible on 17 more files by removing the false refusal in front of it.

`std/sys/_assembly.mojo:94` is the one that matters for the chain this branch
was working on: `comptime if result_type == NoneType:`.

## Why it is NOT the same construct as the one that was fixed

The specialization fix changed *which* refusal fires. This is about the
refusal that fires being **false about the file** — the project's own rule
(`FORMAL_known_limits.md`, "a message that is false about the file is worse
than no message"). Compare the two shapes:

* a *read* of `NoneType` really is a value read, and the storage enumeration
  is the right story — `model.module_global_refusal` says the same thing in its
  own words for the neighbouring case ("a name in none of them has no address
  to read");
* a *type name in a type position* is not a read of anything, so no
  enumeration of value storage can be right about it.

The second needs its own answer, and there are two honest ones.

## What would close it, and the decision it needs

**The question first: is a type a value on this path at all?**

*If yes* — a `comptime` type parameter is one word (the calling convention
already says so: comptime parameters are "already full words, with no declared
width to normalize to"), so the natural encoding is a small integer tag per
type, interned per unit, and `DType` becomes a real object. That is a real
feature with a real cost: the tag has to be **the same on both sides of a
dylib boundary**, so it cannot be a per-unit small integer. It is
`type_info`-shaped work and belongs to whoever owns the reflection table.

*If no* — which is what `model.py` currently asserts everywhere else
(`check_module_symbols`'s own docstring: "A struct is not a value and has no
register"; `INT_TYPE_CTORS`/`IDENTITY_TYPE_CTORS` give a type name a meaning
only where it is *constructed*) — then the honest answer is a **refusal that
names the construct**, alongside the other construct refusals in
`check_module_symbols` (the MLIR-template map, the multi-index map), rather
than the value-placement enumeration.

**The next step, whichever is chosen, is the same first move:** add a rule that
recognises a *type position* — the `==`/!=` comparison of a `comptime`
parameter against a type name, a `is NoneType`, a bare type name as a call
argument — and ask the two questions in the right order:

1. is this name a **type** (in the existing `POINTEE_WIDTHS` /
   `IDENTITY_TYPE_CTORS` / `type_constructor_kind` tables, plus the structs
   this unit compiles)? If so, refuse with a text that says *a type is not a
   value on this path* and does **not** enumerate registers and spill slots;
2. only if not, fall through to the existing `has no home`.

**The ordering matters and is the whole cheap half.** The construct refusal
must be asked in the same pre-pass `check_module_symbols` already uses for its
MLIR map, so it wins over the symptom wherever it appears in the body — the
file's own comment for that map says the better-worded message must win "rather
than being pre-empted by the symptom", and today it is. See
`FORMAL_mlir_refusal_preemption.md` for the measured size of that ordering
problem; the type-name rule should be added to the same pre-pass, not to the
per-name walk.

## Do not

Do not fix this by putting builtin type names on
`model.name_resolves_without_a_local`. That list is, in its own docstring, the
list of names "a backend special case, or a Python-level value" places — and a
type is neither. It would make 93 files report no refusal at all and then
either fail later with a less informative message or, worse, build and read
whatever the allocator left behind, which is the outcome
`unresolved_name_refusal` exists to prevent.
