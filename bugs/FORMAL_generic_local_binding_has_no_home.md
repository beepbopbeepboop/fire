# A generic struct constructed with inferred (or annotated) type arguments loses its binding's home

**Area:** FORMAL/build — binding-home classification. **Found 2026-10-06,
`work/formal94-docs`.**

**Status 2026-10-08 (`work/formal168-docs`): the ANNOTATED half is FIXED; the
INFERRED half is not, and it is the inference feature
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
owns.** A type argument in a local `VarDecl` annotation (`var m: Marker[Int] =
Marker(b.a)`) is now read as a DEMAND and the bare construction on the right is
rewritten to the mangled instantiation, so the annotated spelling binds `m`
exactly as `Marker[Int](b.a)` does. It works in an executable and across a dylib
boundary, both architectures. What landed:

* `formal/monomorph.py::annotated_construction_demands` — the reader. An
  annotation is a STRING on `VarDecl.type_ann`, so `all_instantiation_calls`
  (which walks CALL sites) cannot see the bracket in it; this reads
  `Base[…]` out of the annotation, requires the right-hand side to be a bare
  `Base(…)`, and refuses to speak for an argument it cannot name exactly (a
  nested application, or a name the scope binds as a value), which keeps the
  refusal of `Marker[origin_of(b)]` unchanged.
* `formal/monomorph.py::own_annotation_demands` — the own-struct-template table,
  merged into BOTH demand sets: `formal/imports.py::_own_instantiations` (the
  executable path) and `build_module_dylib`'s `mine` (the library path, whose
  own demand set is also the artifact's identity).
* the annotation arm of `rewrite_instantiation_calls`, which rewrites the bare
  construction the annotation demanded.

Pinned by `test_formal_monomorph.py`'s `a type argument in a local annotation is
a demand` (one file, two instantiations, CPython differential, both arches) and
`a library with an annotated construction publishes it` (the dylib boundary,
with the manifest assertion that the instantiation was published), plus
`a bare local construction with no annotation is still refused`, which pins the
boundary.

**The INFERRED half is unchanged and is not this doc's to close.** `var m =
Marker(b.a)` with no bracket anywhere states no type argument, so no demand is
invented and the refusal stands — the inference a bare call needs is the feature
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
names, and doing it here would bind an instantiation nobody wrote. The doc's
title's "inferred" half is therefore still open; its "annotated" half is done.

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

**DONE for the annotated spelling** (see the Status at the top): the inference
path through a generic construction now records the same home the
explicit-type-argument spelling already records, whenever the type arguments are
WRITTEN in the variable's annotation. Pinned by
`test_formal_monomorph.py`'s `a type argument in a local annotation is a demand`
and `a library with an annotated construction publishes it`.

**What remains is the INFERRED spelling** — `var m = Marker(b.a)` with no bracket
anywhere. That is a type-argument INFERENCE and is owned by
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`;
this doc's contribution to it is the reader above, which already turns a written
bracket in a non-call position into a demand, so the inference work only has to
produce the bracket. `test_formal_monomorph.py`'s
`a bare local construction with no annotation is still refused` is the row that
has to change when that lands.
