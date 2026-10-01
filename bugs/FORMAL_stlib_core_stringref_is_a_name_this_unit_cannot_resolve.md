# FORMAL_stlib_core_stringref_is_a_name_this_unit_cannot_resolve

**Status: OPEN, not fixed, and deliberately not started.** Found while measuring
row 5 of the work map ("value with no representation on this path", 15 files) for
the `construct:receiver-position-and-no-representation` claim. It is the
**1 file of 15** that group contains, and the brief that assigned the work named
it as a representative example — which is worth recording, because acting on the
named example would have built the wrong thing.

## What it is

`stdlib_core.mojo` is a **24-line** hand-written file at the repository root,
described by its own first line as "Minimal Mojo stdlib core for bootstrap". Its
terminal finding:

```
build: constructing StringRef has no representation on this path: this image has
no declaration of StringRef to construct — it is not a struct in this module or
in anything it imports, so there is no field list to bring up, and a formal
value is one 64-bit word.
```

**Read the second clause.** It is not that `StringRef` has no representation —
it is that **this image has no DECLARATION of it**, so there is nothing to
construct. `StringRef` is in `formal/model.py`'s `UNREPRESENTABLE_TYPE_CTORS`, so
the name reaches the unrepresentable branch; but the branch's own text
(`type_constructor_prefers_local_struct`'s docstring) says the right rule is that
a struct **declared in this unit** beats the name list, and there is no
declaration here to beat it with.

## Why it is not a value-model change

`grep -rn 'struct StringRef' ../new-modular/Mojo/stdlib/std/` finds **nothing**.
`StringRef` is not a type in the new-modular stdlib at all — this file is written
against an older or invented API, and every one of its signatures
(`print(s: StringRef)`, `open(path: StringRef)`, `read_file(...) -> StringRef`)
is annotated with a name the tree cannot resolve. `FileHandle` **is** declared,
in this same file, at line 22.

So the file is a **name-resolution** question — is a signature annotated with a
type the image cannot resolve a refusal, a host-import, or a not-answerable? —
and not the "which value kinds have no representation" question the row's name
suggests. The two have opposite fixes: this one is about what an unresolved
ANNOTATION means, and the other is about the value model.

## What was measured, and what is NOT here

Measured, both cases built with `python3 tools/formal_sweep.py`:

| the file | verdict |
|---|---|
| `stdlib_core.mojo` as it stands | `constructing StringRef has no representation` |
| a **one-field local** `struct StringRef: var p: Int` plus `StringRef("")` | **PASS** |

So the shape `StringRef(...)` lowers fine the moment the image can see a
declaration — which is `type_constructor_prefers_local_struct` doing its job, and
it confirms the refusal is about the missing declaration rather than about the
type. **1 file, and the ceiling of fixing it here is 0 PASSes**, because the file
would still be a 24-line stub whose every signature names a type the tree does
not have.

## The exact next step

Decide what an **unresolved type annotation** means on this path, once, in the
model:

1. if the annotated name is in `UNREPRESENTABLE_TYPE_CTORS`, it is a **real type
   this backend does not represent**, and the honest class is
   `not-answerable` (a fact about the target's API) rather than `codegen` (a gap
   in this backend) — which would move the file OUT of the `codegen` denominator
   **without making it answerable**, the drift direction
   `bugs/FORMAL_frame_receiver_handoff.md` §16 and §25 both call out;
2. if it is an arbitrary unknown name, it is a name-placement question and
   belongs with the `… has no home` family —
   `bugs/CODEGEN_elif_arm_reading_a_module_constant_has_no_home.md` and
   `bugs/FORMAL_binding_a_module_level_constant_to_a_local_is_refused.md` are
   two of that family's docs;
3. and in neither case should the answer be a **new representation** — the file's
   types do not exist in the stdlib this sweep builds against, so there is
   nothing to represent.

The place to put it is `formal/model.py`'s
`type_constructor_kind` / `type_constructor_prefers_local_struct` pair, which is
already the one place that decides "the name list, or this unit's declaration".

**Not this lane's file**: `stdlib_core.mojo` is at the repository root and
whether it belongs in the sweep at all is a question about the sweep's roots
rather than about the backend.
