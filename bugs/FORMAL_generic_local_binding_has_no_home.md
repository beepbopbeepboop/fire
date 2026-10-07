# A generic struct constructed with inferred (or annotated) type arguments loses its binding's home

**Area:** FORMAL/build — binding-home classification. **Found 2026-10-06,
`work/formal94-docs`.** NOT FIXED.

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
