# SUITE: `modcache` slice 4 calls an imported plain overload's home symbol no unit defines

**Status (2026-11-18): open, pre-existing on master. Found while fixing the
stale `modcache` slice-2 assertion (it demanded an extern object for an inferred
generic call the in-TU pre-pass now defines; a test-only change that cannot
reach this path); reproduces in isolation from a clean tree.**

## What I ran

    python3 tools/memslot.py --gb 8 --label modcache-file -- python3 test_module_cache.py

`Results: 179 passed, 2 failed` (the slice-2 check this branch fixes was the
documented red; these two are separate):

    FAIL  slice4: client calls the signature-mangled overload
    FAIL  SB-1 (fire.py build CLI): build succeeds and produces an executable  <<timed out after 240s

The SB-1 line is load: that test passes in isolation (`3 passed, 0 failed`) and
its own comment says a timeout there is load, not a wrong answer. The slice-4
failure reproduces alone:

    python3 tools/memslot.py --gb 8 --label slice4-target -- python3 .tmp/run_slice4.py
    FAIL  slice4: client calls the signature-mangled overload

## What I saw

`test_module_cache.py:750` (`test_elaboration_overload`) compiles

    from el_ovlib import pick
    fn main():
        var a: Int64 = 5
        var y = pick(a)

with `runtime/el_ovlib.mojo` defining `pick(x: Int64)` and `pick(x: Int32)`, and
requires `'pick__1_0_5_Int64' in code and len(objs) == 1`. What it produces now:

    #ifndef _MOJO_STUB_el_ovlib_pick_9f63a2
    #define _MOJO_STUB_el_ovlib_pick_9f63a2
    extern int64_t el_ovlib_pick_9f63a2 (int64_t);
      _t1 = el_ovlib_pick_9f63a2 (a);

with `objs == []` and `dylibs == []`. That C does not link:

    $ gcc -fgimple -Iruntime -c -o c.o c.c
    $ gcc -o c c.o runtime/fire_runtime.c
    Undefined symbols for architecture arm64:
      "_el_ovlib_pick_9f63a2", referenced from:
          __gimple_main in c.o

## Why

`_elaborate_overload_call` (`mojo/backend_gimple/emit_infra.py:6311-6327`) now
asks `_imported_overload_call_symbol` for the defining module's own symbol
first; with the lowered argument types (`['int64_t']`) it correctly chooses the
`pick(Int64)` overload and returns `el_ovlib_pick_9f63a2`, and the call is
emitted as an ordinary call to that home symbol.

The home module is resolved here by `module_loader`'s source fallback
(`imports.resolve` returns no dylib for `runtime/el_ovlib.mojo`), so it is seen
neither as a linked dylib nor as an inlined unit, and the old
`elaborate_overload_call` route — which built a private copy
(`pick__1_0_5_Int64`) and contributed its CAS `.o` to `objs` — is no longer
taken. Nothing defines the home symbol in the translation unit, and nothing is
on the link line.

The home-symbol shortcut comes from commit 294407139 ("imports: call the home
overload for an elaborated plain-overload call", 2026-11-17) and is right when
the home module is a dylib. It is wrong in the source-fallback shape, where the
same function previously produced a linkable result.

## Expected

Whatever route is chosen, `compile_linked`'s contract is that the returned C
links with the objects/dylibs it also returns. Either

- the home-symbol call is accompanied by a definition (the module's CAS object,
  or inlining the home module), or
- the home symbol is only chosen when the module is actually on the link line,
  and the source-fallback shape keeps the elaborated private copy + object.

## Exact next step

In `_elaborate_overload_call`, gate the `_home_sym` branch on the home module
being defined somewhere in this link: `_link_dylibs` contains its dylib, or its
path is in `_link_inline_modules` / `_compiled_modules`, or
`gen._module_global_inits` has its per-module record. Otherwise leave
`_home_sym = None` so the existing `elaborate_overload_call` route runs and
contributes `pick__1_0_5_Int64` plus its object as before.

Then fix `test_elaboration_overload` to assert the route the fixed code takes
*and actually link the result*: compile `c.c`, link `c.o` + `objs` + `dylibs`
(as `test_stage1_extern_boundary` already does for its own client), and run it.
The current `len(objs) == 1` / `pick__1_0_5_Int64` check is the old route's
contract; the symbol may legitimately be the home one once the link line
defines it.
