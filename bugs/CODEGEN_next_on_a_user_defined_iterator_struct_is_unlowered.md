# `next(<user-defined iterator struct>)` has no lowering, and the callee's
# type is not inferred either

## Status

OPEN. **Nothing here was fixed in the 2026-10-01 second session, and the reason
is worth more than a fix would have been:** the family's real size was measured
wrong by 4x, and the two sessions' measurements of it disagreed with each
other. `tools/undef_import_census.py` reported "424 sites / 157 names / 194
files" for this whole family; the true figure is **96 sites / 51 names / 60
files** (108 before this session's fixes), because the instrument was counting
the codegen's own guarded forward declaration for every imported name — called
or not. So the next session starts from a number it can trust and a mechanism
list that is 4x shorter, not from this document's original framing.

The three prerequisites below are still all missing; none was reached. What DID
land is in `bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`,
which owns the family: a `comptime for` bare-literal codegen bug, a defaulted
`[...]` bracket parameter treated as required, a generic struct constructed
with no bracket arguments, and two measurement defects in the census itself.

**One thing this document's own "What it looks like" section should have said
sooner.** The refusal `_lower_call` raises for an unresolved `next(<struct>)` is
what keeps these 21 honest, and it is the reason none of them can be made to
pass by elaborating `peekable` alone. `peekable(list)` needs, in order:
dependent return types (`_PeekableIterator[type_of(iterable).IteratorOwnedType]`,
which means resolving `List.IteratorOwnedType` = `_ListIterOwned[Self.T]` and
so `Self.<comptime member>` from the struct's own `comptime` declarations);
`Self.<member>` resolution, which fix #1 below deliberately does NOT do; in-TU
instantiation, because `peekable`'s body is `return {iter(iterable)}` and `iter`
is itself an excluded generic (the `.o` route cannot work); and trait-bounded
overload selection that REFUSES on a residual tie. That is a type-inference
layer, not a wiring change, and it is the same layer `size_of[T]()`'s use-site
inference needs. Sequencing it against that larger problem is strictly better
than sequencing it against 21 files.

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

The `for` loop over the SAME object is no better. Measured on
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
`test/collections/{test_set,test_span}.mojo`, seven `test/iter/test_*.mojo`,
eight `test/itertools/test_*.mojo`, `test/python/test_python_object.mojo`.

**Two of those entries were dead.** `test/itertools/test_chain.mojo` and
`test/itertools/test_peek.mojo` had moved to `test/iter/`, so their entries
named files this sweep never attempts — and a vanished file can never be
observed going green, so nothing reported them. `compile_stdlib.py` now
computes `GONE EXPECTED_FAILURES entries` on a full sweep (the set difference
against the swept paths, alongside the existing `STALE ... now passing` check)
and exits non-zero on it, because a declared red that describes nothing is a
worse hole than one that describes a real bug. Both dead entries are removed;
the files' current paths were already listed.

**And `exit 0` with 21 `...FAIL` lines on screen is not a bug.** `main()` exits
non-zero on `unexpected_failed`, on `stale_expected`, and now on
`_gone_expected`. Verified by deleting one live entry: the same run then
prints `UNEXPECTED failed files:` and exits 1. A `FAILED: 21 (21 expected, 0
unexpected)` summary is the `expect=` mechanism working, and the per-file CAS
cache is a separate axis again — this step re-runs real codegen and a real
`gcc` on a CAS miss, so a 1.4 s green is a warm cache, not a skipped check.

## What is fixed

Three things, all of which turn a silent wrong artifact into a named failure
or correct the substitution underneath it.

**1. `_lower_call` refuses a `next(...)` that matched none of its forms**,
instead of emitting the call to a symbol that does not exist
(`mojo/backend_gimple/emit_calls.py`). That is what made this visible: the
21 files above moved from a false PASS to a named, diagnosable refusal. The
same refusal is what caught this compiler's own `next(iter(_seen))` in
`_lower_call` — a link error thousands of lines from its cause, in the
`fire1` build.

**2. `_lower_call` has a real lowering for the shape whenever the receiver's
type IS resolvable**: `next(<struct>)` → `{Struct}___next__(obj)`, resolving
`__iter__`'s possibly-different iterator type first, exactly as
`emit_loops._gen_for_struct_iter` does. So a struct whose type the codegen
knows compiles for real now. Verified on a non-generic two-struct case
(`struct It` with `__next__`, held by `struct Box`): emits `It___next__`.

**3. `monomorphize_source` substitutes `Self.<param>` as a unit**
(`monomorphize.py`), in a pass that runs before the bare-word one so the
`Self.` qualifier is dropped with the name it qualifies. `Self.T` inside
`struct Box[T]` is the enclosing type's own name for the parameter, so for
`Box[int64_t]` it denotes exactly `int64_t`; the bare-word pass alone could
only rewrite its `T` and leave `Self.` glued to the argument, producing
`Self.int64_t` — a member name that means nothing, which `_mojo_type` then
answered as `int64_t`. That silence is what boxed every generic iterator's
inner field (`_PeekableIterator[InnerIterator]`'s `var _inner:
Self.InnerIterator`, `_TakeWhileIterator`'s, `_FlattenIterator`'s, …), so
`next(self._inner)` inside those monomorphized methods had no receiver type
even once the struct WAS instantiated for a concrete type argument. Pinned by
`test_module_cache.py::test_self_qualified_type_param_substitution` (8 cases,
including the nested-shadowing span rule and a struct-typed argument).

Its supporting half: `elaborate_generic_struct` now also publishes each field's
RAW Mojo annotation (`info['anns']`), and `_ensure_generic_struct` resolves
those through `gen._resolve_type` — the one resolver that consults this
compile's `struct_field_types` — after materializing any generic-struct
instantiation the annotation names into its concrete mangled name
(`_materialize_generic_struct_mentions`). Without it the caller registered
`<inner> *` while `elaborate._struct_layout` — a stateless `_mojo_type`, with
no access to that registry — registered the same field boxed, i.e. the two
sides of the same struct disagreed about its layout.

**No behaviour regression**: `compile_stdlib.py` is 589 passed / 21 expected /
0 unexpected both before and after, and the shape that motivated #3
(`Wrapper[Inner[int64_t]]` whose method calls `next(self._inner)`) fails
IDENTICALLY before and after — the `next(...)` refusal already blocked it, so
#3 is a prerequisite, not a partial version of the fix.

## What the remaining blocker actually is

Measured 2026-10-01 on `test/iter/test_peek.mojo`, which is the smallest
member of the family. The receiver's type is `int64_t` because **`peekable` is
never elaborated** — not because its return type is mis-substituted.

Three independent measurements, in order:

1. **The callee is deliberately not an export.** `reflect.collect_exports_src`
   drops every generic template, and `reflect.export_exclusions` on
   `std/iter/__init__.mojo` returns exactly
   `['_ChainedIterator', '_Empty', '_Enumerate', '_MapIterator', '_Once',
   '_PeekableIterator', '_ZipIterator', 'chain', 'empty', 'enumerate', 'iter',
   'map', 'next', 'once', 'peekable', 'zip']`.
   `module_loader.load_module('std.iter')` accordingly returns 14 exports and
   no `peekable`. This is intentional (ELABORATION.md): a generic has no single
   concrete symbol, so importers are supposed to instantiate it on demand.

2. **Nothing instantiates it.** Compiling the file with the `next` refusal
   stubbed out — a throwaway probe, not a candidate fix — succeeds, and the C
   contains no `_PeekableIterator` definition and this call:

   ```c
   #ifndef peekable
   extern int64_t peekable (...);  /* from std.iter */
   ...
   int64_t iter;
   ...
   _t2 = peekable (list);
   iter = _t2;
   _t6 = _t5;  /* int64_t.peek() stubbed */
   ```

   So the artifact that would pass this gate is a call to a symbol nothing
   defines, plus a boxed integer where the iterator is. **Making these 21 files
   go green without fixing the type inference would convert an honest red into
   a false green** — which is why the refusal stays and the fix is not a
   lowering.

3. **The demand-driven elaborator cannot reach `peekable` either.** The call
   site does register the overload set (`_imported_overloads['peekable']`,
   because `std/iter/__init__.mojo` really does declare `def peekable` twice),
   so `_lower_call` does call `_elaborate_overload_call`. It returns `None`,
   at `Elaborator.elaborate_overload_call`'s own no-match bail:

   ```python
   arg_mojo = [c_to_mojo(ct) for ct in arg_ctypes]   # ['MojoList *'] -> ['Int']
   for src, ptypes, ret in overloads:
       if ptypes == arg_mojo:                        # ['Some[Iterable]'] / ['Some[IterableOwned]']
   ```

   The two overloads are distinguished only by a TRAIT BOUND (`Some[Iterable]`
   vs `Some[IterableOwned]`), which `c_to_mojo`'s scalar table cannot answer,
   so nothing matches and the elaborator declines — correctly, since it must
   not silently pick the first.

   And were it to match, it would not be enough: the chosen overload's return
   type is `_PeekableIterator[type_of(iterable).IteratorOwnedType]`, which
   depends on the ARGUMENT's type, and `elaborate_overload_call` compiles the
   renamed function standalone via `monomorphize.compile_fn` — a body of
   `return {iter(iterable)}`, where `iter` is itself an excluded generic. The
   elaborator's model has no notion of a dependent return type.

So the work is, in order:

1. **Overload selection on trait conformance**, not on scalar parameter
   types: pick between `Some[Iterable]` and `Some[IterableOwned]` from what
   the argument's type actually conforms to (`Elaborator.check_conformance`
   and `Some[...]` already exist; `_C_TO_MOJO` is the table that has to learn
   to answer a conformance question instead of a ctype).
2. **Dependent return types**: resolve `type_of(<arg>).IteratorOwnedType`
   against the argument's concrete type, so `peekable(list)` is
   `_PeekableIterator *` in the caller. That needs the argument's
   `IteratorOwnedType` to be known — which means the callee's `Self.<member>`
   comptime members have to be resolvable too, and they are NOT type
   parameters (fix #3 above is deliberately scoped to type parameters and
   leaves `Self.Element`, `Self.IteratorOwnedType`, `Self._OuterProduct2Type`
   alone, since substituting those would be wrong).
3. **Materialize the returned generic struct in the CALLER** — the elaborated
   `Inner_int64_t` plus the methods `next` needs (`__next__`, and `__iter__`'s
   possibly-different type, which `_lower_call`'s struct-protocol branch
   already resolves) — so `func_return_types` carries `<mangled>___next__` and
   the existing struct-protocol branch takes over with no further change to
   `emit_calls.py`.

Until all three land, `next(<user struct>)` on an un-inferred receiver must
stay a refusal: the alternative is the silent wrong artifact, which is strictly
worse and is what this project has been removing one shape at a time.

## Next step

Start at (1), and gate it on the artifact, not on the gate step: build one
module that instantiates `peekable(list)` for a real list and check that the
emitted C both DEFINES `peekable` and CALLS a real `_PeekableIterator___next__`.
`compile_stdlib.py` cannot see either — that is this doc's original "Why it
was green" — so a green `stdlib-syntax` here proves nothing on its own.

**Scope warning, measured 2026-10-01.** This doc's 21 files are not 21 bugs.
`tools/undef_import_census.py` measures **424 sites / 157 names / 194 files**
whose generated C calls an imported bracket-parametrized template that nothing
defines, and it established that registration already works — `_imported_generics`
contains the name and the elaborator is reached and correctly declines. A large
share of those templates take **no arguments** (`size_of[T]()`, `align_of[T]()`,
`bit_width_of[T]()` …), so their type argument is recoverable only by
bidirectional, use-site-driven inference. See
`bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`, which
owns that scope; the honest estimate for the whole family is a type-inference
layer, not a wiring change.