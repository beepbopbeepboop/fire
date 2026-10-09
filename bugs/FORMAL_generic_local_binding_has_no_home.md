# A generic struct constructed with inferred (or annotated) type arguments loses its binding's home

**Area:** FORMAL/build — binding-home classification. **Found 2026-10-06,
`work/formal94-docs`.**

**Status 2026-10-08 (`work/formal234-docs`): PARTIALLY FIXED — this doc's own
reproducer (an UNUSED type parameter) now builds and runs on both
architectures; the USED-parameter case remains, and is why the doc stays.**

`formal/monomorph.py::without_template_bodies` dropped EVERY struct template, so
`Marker` was never in `structs_by_name` and the bare `Marker(b.a)` had no home to
classify. It now keeps a struct template whose bracket parameters are ALL unused
TYPE parameters (`T: AnyType`, no comptime parameter) AND which the source
constructs BARE (`Marker(b.a)`; a `Marker[Int](…)` anywhere in the file drops it,
so the explicit instantiation and the bracketed-callee refusal keep their
meanings). Such a struct's layout does not depend on the argument, so its own
declaration IS the layout. Pinned by `test_formal_monomorph.py`'s `a bare
construction of an unused-parameter template` (CPython differential, both
architectures) and by the re-pointed `test_formal_run.py` row
`origin_of_in_a_local_type_annotation_is_still_a_type`, now the POSITIVE answer
(7) instead of the refusal it used to record.

**What is still open:** a type parameter the body USES — `struct Pair[T]: var a:
T` built as `Pair(1, 2)` — is a real INFERENCE (bind `T` from the argument's
type) and is still refused, as is `var p: Pair[Int] = Pair(1, 2)` through the
annotation. Those need the constructor-argument unifier
`elaborate.infer_struct_type_args` reached from the formal demand walk, which the
compiled path already has and the formal path does not.

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
