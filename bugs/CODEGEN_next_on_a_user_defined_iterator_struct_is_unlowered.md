# `next(<user-defined iterator struct>)` has no lowering, and the callee's
# type is not inferred either

## Status

OPEN. One half landed (see "What is fixed" below); the other half is a
type-inference project this is now explicitly parked on.

## What it looks like

`next(obj)` where `obj` is a user-defined iterator struct — Mojo's spelling of
Python's `next(obj)` = `type(obj).__next__(obj)`, with the method named
`__next__`:

```mojo
var list = [1, 2, 3]
var iter = peekable(list)     # a _PeekableIterator
assert_equal(next(iter), 1)
```

compiles to a call to a `next` symbol that does not exist:

```c
_t4 = next (_t3);
```

`next` is declared once, variadic, and never defined
(`mojo/backend_gimple/module_gen.py`: `'next', 'int64_t next(...);'` with a
`FIXME:` on the line). So the failure is not a compile error — it is

```
Undefined symbols for architecture arm64:
  "_next", referenced from: ...
```

at LINK, attributed to whichever function happens to contain the call.

The `for` loop over the SAME object is no better: `var iter = peekable(list)`
types `iter` as `int64_t`, not `_PeekableIterator *`, so
`emit_loops._get_actual_type` finds nothing in `_actual_types`, the
struct-protocol arm is skipped, and the loop lowers to `mojo_unsupported_iter`
— a loud runtime abort, but a no-op loop until then. Measured on
`test/iter/test_peek.mojo` at the parent commit: **3** calls to an undefined
`next` and **23** `mojo_unsupported_iter` sites in one generated file.

## Why it was green

`compile_stdlib.py` (the `stdlib-syntax` gate step) is a **syntax** check:
`compile` then `gcc -fgimple -fsyntax-only`. Nothing in it looks at whether
the emitted C is *usable*, and the `test/` tree is not linked by anything.
So 21 stdlib files reported PASS while carrying this. They are listed in
`compile_stdlib.py`'s `EXPECTED_FAILURES` now, with the reason.

The 21: `std/collections/string/iterators.mojo`,
`std/itertools/itertools.mojo`, `test/collections/string/test_iterators.mojo`,
`test/collections/{test_set,test_span}.mojo`, all nine `test/iter/test_*.mojo`,
ten `test/itertools/test_*.mojo`, `test/python/test_python_object.mojo`.

## What is fixed

`_lower_call` now refuses a `next(...)` that matched none of its forms,
instead of emitting the call to a symbol that does not exist
(`mojo/backend_gimple/emit_calls.py`). That is what made this visible: the
21 files above moved from a false PASS to a named, diagnosable refusal. The
same refusal is what caught this compiler's own `next(iter(_seen))` in
`_lower_call` — a link error thousands of lines from its cause, in the
`fire1` build.

`_lower_call` also gained a real lowering for the shape whenever the
receiver's type IS resolvable: `next(<struct>)` →
`{Struct}___next__(obj)`, resolving `__iter__`'s possibly-different iterator
type first, exactly as `emit_loops._gen_for_struct_iter` does. So a struct
whose type the codegen knows compiles for real now.

## What is missing, and why it is not a small step

The 21 files fail because `var iter = peekable(list)` gives `iter` the type
`int64_t`. `peekable` is a generic function in an imported module returning
`Self.IteratorOwnedType`, itself derived from a parameter type
(`InnerIterator`), which is itself derived from `__iter__`'s return. Closing
that means inferring a generic function's return type through `Self.<member>`
across module boundaries — the same gap that leaves the `for` loop over the
same object a `mojo_unsupported_iter`.

Until then, `next(<user struct>)` on an un-inferred receiver must stay a
refusal: the alternative is the silent wrong artifact, which is strictly
worse and is what this project has been removing one shape at a time.

## Next step

Infer the return type of an imported generic function well enough that
`peekable(list)` yields `_PeekableIterator *` in the caller. With that,
`_lower_call`'s struct-protocol branch (already landed) handles `next`, and
`emit_loops`' struct-protocol arm handles `for`, and all 21 files can come
out of `EXPECTED_FAILURES`.