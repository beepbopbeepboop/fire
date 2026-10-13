# A generic struct constructed with inferred (or annotated) type arguments loses its binding's home

**Area:** FORMAL/build — binding-home classification. **Found 2026-10-06,
`work/formal94-docs`.** NOT FIXED.

**Status 2026-10-12 (`work/formal307-docs`): the ROOT CAUSE is corrected and
measured — the field-access refusal below is a SYMPTOM, and this file's "Next
step" (the holder/frame classification and `field_access_refusal`) is looking one
layer too late.** The construction `Marker(b.a)` — a BARE call to a generic
struct, type arguments inferred — is never INSTANTIATED at all, so no `Marker`
declaration reaches the build's struct table and the local has no home because
there is no type for it to be a home of. The demand pipeline reads type
arguments off an explicit bracket ONLY (`formal/monomorph.py::all_instantiation_calls`
→ `demands` → `own_demands`, called for an executable by
`formal/imports.py::_own_instantiations`), and `Marker(b.a)` names none, so
nothing is demanded, nothing is generated, and the call is left as a symbol no
image provides.

Measured, arm64 (x86-64 identical: this is a source-level pipeline, before either
emitter):

```mojo
# (a) the bare call with NO field access, so the field refusal cannot fire:
struct Marker[T: AnyType]:
    var v: Int
def main(n: Int) -> Int:
    var m = Marker(7)
    return 0
#   build: the image would bind 1 symbol(s) that nothing provides …: Marker.
#          `Marker` is a call this build emitted and nothing provides it
```

(a) is the load-bearing measurement and this file did not have it: with no field
access there is STILL no `Marker`, which is what says the defect is the
CONSTRUCTION rather than the binding's classification. The annotated spelling
fails for the same reason, so the annotation is not a second mechanism:
`var m: Marker[Int] = Marker(7)` puts the type arguments on the ANNOTATION
(`VarDecl.type_ann`) and a bracket-free call in the VALUE, and the pipeline reads
neither — `formal/monomorph.py::rewrite_instantiation_calls` rewrites
`Base[Args](…)` call sites, and its own docstring says "What a bare type
ANNOTATION binds to is not covered here".

**Whose fix this is, and why it is not taken here.** Two OPEN docs own the two
halves and this file is an instance of both rather than a third bug:
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
(the inference — the bare call's whole subject) and
`bugs/FORMAL_generic_monomorph_scope.md` §1a/§2 (the name resolution and the
annotation binding). Landing either is a feature in `monomorph.py`'s demand and
rewrite pair, not a binding-home change, and this branch is a light worker.

**Pinned now by a row that names the root cause rather than the symptom**:
`test_formal_run.py`'s `a_bare_generic_construction_demands_no_instantiation`
(the bare call with no field access, `refuse:that nothing provides`), beside the
existing `origin_of_in_a_local_type_annotation_is_still_a_type` row, which pins
the downstream field refusal. Both flip to a build-and-run row on both
architectures the day the demand pipeline infers the arguments.

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

Find where the holder/frame classification decides what a `VarDecl`'s bound
name holds (the refusal text lives in `formal/model.py::field_access_refusal`,
raised when the emitter's slot table never got a home for the name — see
`formal/build.py:9620` and the holder tables both emitters build from), and
make the inference path through a generic construction record the same home
the explicit-type-argument spelling already records. Pinned now by no row —
`test_formal_run.py`'s `origin_of_in_a_local_type_annotation_is_still_a_type`
was re-pointed to record the actual refusal until this is fixed.
