# A generic struct constructed with inferred (or annotated) type arguments loses its binding's home

**Area:** FORMAL/build — binding-home classification. **Found 2026-10-06,
`work/formal94-docs`.** **Status 2026-10-08 (`work/formal252-docs`): the
UNUSED-type-parameter class is FIXED, on both architectures; the
USED-parameter class is the residual and is a different item.**

## FIXED: a type parameter the body never mentions made a concrete struct look parametric

**Root cause, measured at the pipeline stage that drops template bodies.**
`formal/build.py` runs `_imported_structs` (which creates the mangled
instantiation for a *bracketed* construction, e.g. `Marker[Int](b.a)` →
`Marker_1_T_3_Int`) and then `_without_own_template_bodies`, which drops every
generic struct template declaration. `formal/monomorph.py::all_instantiation_calls`
reads the type arguments off **bracketed CALL SITES only**, so for the doc's
`var m = Marker(b.a)` (no bracket) no demand exists, no instantiation is
created, AND the template body is dropped — `structs_by_name` was empty and the
binding had no declaration to classify against. The refusal is emitted from
`_load_var` → `_no_home` → `model.field_access_refusal` for the field read
`m.v`, which is downstream of that absence rather than a decision about the
binding.

**The fix is a recogniser, not inference.** A struct template whose type
parameters all occur **only in its header** (`_struct_template_params_are_unused`,
with the header bracket removed by `_template_body_text`) produces the identical
declaration text for every argument, so it is extensionally a concrete struct:
`Marker[Int]` and `Marker[Bool]` are the same declaration. `without_template_bodies`
now KEEPS exactly those templates **when `stmts` itself constructs the name
without a bracket** (`Marker(v)`), so a template nobody writes that way is still
dropped and the analysis of its (possibly parameter-reading) body is still
skipped. The emitter then sees an ordinary concrete declaration and the whole
existing one-word/frame classification runs unchanged.

**Measured, both architectures.** All of the doc's examples now build and answer
7 (`tag`'s `m.v` is `g.a`):

| shape | before | now |
|---|---|---|
| `var m = Marker(b.a)` — inferred, T unused | refused, both arches | builds, both arches |
| `var m: Marker[Int] = Marker(b.a)` — annotated, T unused | refused, both arches | builds, both arches |
| `var m: Marker[origin_of(b)] = Marker(b.a)` — T unused | refused, both arches | builds, both arches |
| `Marker[Int](b.a)` — explicit bracket | builds | builds (unchanged) |
| plain `struct Marker` | builds | builds (unchanged) |

**Pinned.** `test_formal_run.py`'s
`both_arch_an_unused_type_parameter_construction_needs_no_bracket` (a one-field
WORD and a two-field FRAME in one program, 349, both architectures), and the
doc's own reproducer re-pointed from a refusal to an answer as
`origin_of_in_a_local_type_annotation_is_a_type` (7).

## The residual: a type parameter the body USES needs real inference

`struct Box[T: AnyType]: var v: T` + `var m = Box(n)` is **still refused** on
both architectures, and it is the same class the doc's title names but a
different item: the field's layout is a function of the argument, so a
bracket-less construction can only be bound by **inferring T from the
constructor's arguments** — which this path does not do. That is
`bugs/FORMAL_generic_monomorph_scope.md` §1/§4 territory (a type argument in a
non-call position is not a demand, and the demand walk reads brackets), not the
recogniser above, and `Marker[Int](n)` still builds. Pinned as a refusal, both
arches, by `test_formal_run.py`'s
`an_used_type_parameter_construction_without_a_bracket_still_refuses`, so the
keep-arm above cannot silently widen into a wrong layout.

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/probe/t16 .tmp/probe/t16.mojo
```

```mojo
struct Marker[T: AnyType]:
    var v: Int
struct Bag:
    var a: Int
    var b: Int
def tag(b: Bag) -> Int:
    var m = Marker(b.a)      # type arguments INFERRED
    return m.v
def main(n: Int) -> Int:
    var g = Bag(); g.a = 7; g.b = 8
    return tag(g)
```

## What was seen

Both architectures refuse:

```
build: tag: 'm.v' is a field access through 'm', and this path has no way to say
what 'm' holds. ... nothing this image can see about 'm's binding establishes
which ...
```

The SAME program with the type arguments spelled on the construction builds and
runs (`var m = Marker[Int](b.a)` — prints 7). An annotated local is no better:
`var m: Marker[Int] = Marker(b.a)` fails identically, and so does
`var m: Marker[origin_of(b)] = Marker(b.a)` — the annotation is not the
subject. A NON-generic one-field struct in the same positions builds and runs
(`var m = Marker(b.a)` with plain `struct Marker` is fine; so are
`def tag(b: Int) -> Int: var m: Marker = Marker(b)` and `var m: Marker =
Marker(7)` in `main`).

So the defect is exactly: a generic struct's construction whose type arguments
are inferred or supplied via the variable's type ANNOTATION never lands in a
binding the frame/holder analysis can classify, and every field access through
that name is refused. `def tag(ref b: Bag)` vs `def tag(b: Bag)` makes no
difference; it is inference-vs-explicit on the generic.

## Expected

`Marker(b.a)` with the generic's argument inferred from the field's type should
bind `m` the same way `Marker[Int](b.a)` does.

## Next step

**The original next step below was one layer too low, and the Status at the top
is what replaced it.** The refusal text does live in
`formal/model.py::field_access_refusal` and the emitters do consult the holder
tables — but the binding had **no declaration at all** to classify against,
because `formal/monomorph.py::without_template_bodies` had dropped the template
and no bracketed call site had asked for an instantiation. The fix is the
unused-parameter recogniser described above; the remaining item is inference for
a USED parameter (`FORMAL_generic_monomorph_scope.md` §1), not a holder-table
change.

The original text, kept so a reader can see which layer the measurement moved:

> Find where the holder/frame classification decides what a `VarDecl`'s bound
> name holds (the refusal text lives in `formal/model.py::field_access_refusal`,
> raised when the emitter's slot table never got a home for the name — see
> `formal/build.py:9620` and the holder tables both emitters build from), and
> make the inference path through a generic construction record the same home
> the explicit-type-argument spelling already records.

Pinned by `test_formal_run.py`'s
`both_arch_an_unused_type_parameter_construction_needs_no_bracket` (answer, both
arches), `origin_of_in_a_local_type_annotation_is_a_type` (the doc's own
reproducer, re-pointed from a refusal to 7), and
`an_used_type_parameter_construction_without_a_bracket_still_refuses` (the
residual, a refusal on both arches).
