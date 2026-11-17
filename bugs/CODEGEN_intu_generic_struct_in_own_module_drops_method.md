# CODEGEN: materializing a generic struct in its OWN module drops that module's method definitions

Status: open. Found 2026-11-15 while landing free-function overload emission.

## What I ran

Compile `std/iter/__init__.mojo` alone (the `build_stdlib_dylib` per-module
path), then inspect the generated C and the built dylib:

    python3 -c "...compile_module_to_c(std/iter/__init__.mojo)..."
    nm -gU build/libmojostdlib.arm64.dylib | grep Enumerate___next__

## What I saw

With the `_Enumerate` construction reachable from a newly-emitted plain
`enumerate(var iterable, start=0)` overload (`return _Enumerate(iter(iterable^),
start=start)`), the in-TU generic materializer (`elab_intu`) instantiated
`_Enumerate` **inside `std/iter/__init__.mojo` itself**. The module's own
`_Enumerate.__next__` method then became prototype-only:

    /* _Enumerate.__next__: definition-site body not lowerable in this TU —
       ... `next(...)` ... `Self.InnerIteratorType` names an unbound type
       parameter ... — prototype only; the instantiating TU emits the
       mangled copy */

and the shipped dylib referenced `_std_iter___init____Enumerate___next__`
without defining it:

    nm -u build/libmojostdlib.arm64.dylib | grep Enumerate___next__
    _std_iter___init____Enumerate___next__

Any program linking the dylib aborts at load with
`dyld: symbol not found in flat namespace
'_std_iter___init____Enumerate___next__'` (measured with a two-line
`import re` program built by `fire.py build`). With the plain `enumerate`
overload not emitted, the dylib defines the symbol and the program runs.

## What I expected

Instantiating one generic struct should not change whether the DEFINING
module emits its own struct's methods; the definition and every instantiation
should agree, or the module should honestly refuse rather than publish a dylib
with a dangling internal reference (`-undefined dynamic_lookup` hides it from
the link).

## Exact next step

`elab_intu.run` should skip (or defer) a `kind == 'struct'` root whose
`StructDef` is defined in the CURRENT file: `std/iter/__init__.mojo` is
compiling the very struct whose methods it is about to emit, and the
materialized copy changes the struct registration/return-type inference that
the method pass reads. The `MoveOnlyList` in-TU case the pass exists for is a
LOCAL (non-generic-file) struct in a *test* module; guard on "this struct's
own StructDef is in `stmts` and has `type_param_names`", and let the normal
struct-method path serve it. Then re-run the two-module check above and
`test_gimple.py`'s iterator cases.

Until that lands, `module_gen`'s overload gate keeps a plain overload set
unemitted when any body constructs a generic struct defined in the same file
(the pre-2026-11-15 behaviour).
