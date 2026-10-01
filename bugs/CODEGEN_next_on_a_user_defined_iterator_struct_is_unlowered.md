# `next(<user-defined iterator struct>)` has no lowering, and the callee's
# type is not inferred either

## Status

OPEN, but for one reason instead of two. The RECEIVER'S TYPE half is still a
type-inference project (see "What is missing"), but the other half — which
was not this doc's subject and had been hiding behind it — is FIXED: a
user-defined iterator struct reached through `from mod import Struct` spelled
its protocol methods' C names with a hand-written `{Struct}___{method}__`
f-string instead of `gen._struct_method_csym`, the tree's one composer, so
the home-module qualifier was dropped and the call went to a symbol nothing
defines. `emit_loops._gen_for_struct_iter` (all three of `__iter__`,
`__has_next__`, `__next__`) and `_lower_call`'s `next(<struct>)` branch both
did this; both now compose through `gen._struct_method_csym`.

Measured, on a two-module fixture (`xmoditer_defn.py` holding the struct +
`make()`, `xmoditer_use.py` doing `next(d)` / `for x in d` / `next(e)`):

before —

    error: implicit declaration of function 'It___next__'; did you mean 'itmod_It___next__'?
    error: implicit declaration of function 'It___iter__'; did you mean 'itmod_It___iter__'?
    error: assignment to 'It *' from 'int' makes pointer from integer without a cast

after — builds clean and prints `1 2 3 1` (`next(d)` advances n to 1 and
returns 1; the `for` then yields n=2,3 and stops because `__has_next__` is
`n < 3`; `next(e)` on a fresh `It` is 1).

Note the severity: gcc's `-Wimplicit-function-declaration` fallback types the
undeclared call as returning `int`, so `It___iter__(It *)` became an `int`
that was then assigned to an `It *` — a wrong pointer, not merely a missing
symbol. So this was never going to stay a clean link error.

Regression: `test_gimple_runner.py`'s
`cross_module_iterator_struct_protocol_symbols`. It asserts the built
binary's real stdout and that gcc is clean; pre-fix it does not compile at
all. There is deliberately NO CPython comparison in that test:
`__has_next__` is a Mojo-only protocol, so CPython has no such method and
would call `__next__` until it raised — running the fixture under CPython
loops forever.

## What is fixed (the receiver's type half, from an earlier session)

`_lower_call` now refuses a `next(...)` that matched none of its forms,
instead of emitting the call to a symbol that does not exist
(`mojo/backend_gimple/emit_calls.py`). That is what made this visible: the
21 files above moved from a false PASS to a named, diagnosable refusal. The
same refusal is what caught this compiler's own `next(iter(_seen))` in
`_lower_call` — a link error thousands of lines from its cause, in the
`fire1` build.

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

## What is fixed (the receiver's type half, from an earlier session)

`_lower_call` now refuses a `next(...)` that matched none of its forms,
instead of emitting the call to a symbol that does not exist
(`mojo/backend_gimple/emit_calls.py`). That is what made this visible: the
21 files above moved from a false PASS to a named, diagnosable refusal. The
same refusal is what caught this compiler's own `next(iter(_seen))` in
`_lower_call` — a link error thousands of lines from its cause, in the
`fire1` build.

`_lower_call` also gained a real lowering for the shape whenever the
receiver's type IS resolvable: `next(<struct>)` → `{Struct}___next__(obj)`,
resolving `__iter__`'s possibly-different iterator type first, exactly as
`emit_loops._gen_for_struct_iter` does. So a struct whose type the codegen
knows compiles for real now — which is what made the missing module
qualifier above findable at all, and the two fixes are the same subject:
"a struct whose type the codegen knows" now means across a module boundary
too.

## What is missing, and why it is not a small step

The 21 files fail because `var iter = peekable(list)` gives `iter` the type
`int64_t`. `peekable` is a generic function in an imported module returning
`_PeekableIterator[type_of(iterable).IteratorType[origin_of(iterable)]]`
(`std/iter/__init__.mojo`:824), whose own type parameter comes from the
argument's `IteratorType`, which is itself a `comptime` member of the
argument's type — and `_PeekableIterator` in turn declares
`comptime IteratorOwnedType: Iterator = Self`. Closing that means inferring a
generic function's return type through `Self.<member>` and through a
parameter's `comptime` member, across a module boundary — the same gap that
leaves the `for` loop over the same object a `mojo_unsupported_iter`.

Until then, `next(<user struct>)` on an un-inferred receiver must stay a
refusal: the alternative is the silent wrong artifact, which is strictly
worse and is what this project has been removing one shape at a time.

## Next step

Infer the return type of an imported generic function well enough that
`peekable(list)` yields `_PeekableIterator *` in the caller. With that,
`_lower_call`'s struct-protocol branch handles `next`, `emit_loops`'
struct-protocol arm handles `for`, and all 21 files can come out of
`EXPECTED_FAILURES`. The symbol composition those two paths do is already
correct across modules (fixed above), so nothing else stands between the
inference and the 21 files.

The part that is left does not reproduce on a plain two-module fixture any
more: `defn.py` holding `class It` + `def make() -> It`, `use.py` doing
`from defn import make; print(next(make()))`, builds and prints `1` after
the fix above. It needs a GENERIC factory whose declared return type is
built from a parameter's `comptime` member — the `peekable` shape above —
which is why the repro is `test/iter/test_peek.mojo` and not a two-line
fixture.