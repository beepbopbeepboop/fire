# CODEGEN_cyclic_closure_from_import_of_a_container_global_with_no_type_yet: a three-module import cycle reads 0 and raises `TypeError: object is not iterable`

## Status

OPEN. Partly closed for the compiler's own closure by
`78ec3618` ("codegen: a from-import of a global whose owner is still
compiling reads the owner"); what is left is the general case, and this
doc is the receipt for it. That commit fixed the *routing* — the bare
read now loads the owner's field when the owner's Mojo type is
independently known — but a USER closure has no such independent source,
so the read still falls to the unknown-identifier `(int64_t)0`.

## What I ran, and what I saw

Three modules, in a temp dir, compiled with the ordinary single-TU path
(`compile_to_gimple(src, do_imports=True)`):

    cyc_a.py                          cyc_b.py                     cyc_root.py
    NAMES: list = []                   from cyc_a import NAMES       import cyc_a
    def fill(v):                       def show():                  def main():
      global NAMES                       return list(NAMES)           cyc_a.fill([1, 2])
      NAMES = [str(x) for x in v]                                     print(cyc_a.touch())
    def touch():
      import cyc_b                     <- NESTED, so `_collect_import_modules`
      return cyc_b.show()                 sees it: cyc_b is compiled from
                                           INSIDE cyc_a's own gen_module_impl

`cyc_a.py`'s `import cyc_b` is inside a function on purpose: that is what
puts the importer on the compile stack *below* its own from-import's
owner, and it is not a contrivance — `fire_compiler.py:8040` does
exactly this (`from gimple_codegen import compile_to_gimple` inside a
`__main__` self-test), and that is how the self-host closure reached the
same state.

    $ python3 cyc_root.py
    ['1', '2']                                    <- CPython
    $ gcc-mp-15 -fgimple -I runtime -o cyc_root.exe cyc_root.c runtime/fire_runtime.c
    $ ./cyc_root.exe
    Unhandled exception: TypeError: object is not iterable
    exit=1

and in the generated C:

    _t1 = (int64_t)0;  /* ct param or undeclared: NAMES */

The value is a constant `0`, so `list(0)` reaches
`mojo_iter_boxed_list`, which raises for anything that is neither a
boxed string nor a registered container. The whole `show()` body is dead
code.

## Why the routing fix does not reach it

`78ec3618` gates its new route on the owner's Mojo type being
independently known: for the self-host closure it is, because
`_selfhost_module_scalar_globals` seeds `_global_to_module` /
`_global_var_types` from the compiler's own sources before any body is
lowered (its own docstring says why: the `gimple_codegen` <->
`gimple_gen_*` cycle). A user module gets no such pre-seed.

Without it, the type only becomes available at the owner's own Phase 1.7
scan, and that runs at `module_gen.py`'s ~10236 — AFTER the imported-module
compile loop at ~3442, i.e. after `cyc_b` has already been emitted.
Measured on this fixture, at `cyc_b`'s from-import scan:

    _global_to_module['NAMES'] = None       <- nothing has claimed it yet
    _global_var_types['NAMES'] = None
    _module_globals                         = {}   (cyc_a has not frozen)

so `_gmi_scan_imported_global_homes` skips the name at its FIRST gate
(`_iowner is None`) and never reaches the provisional-record arm.

## The next step, exactly

Make the owner's top-level global types available BEFORE its imported
modules are compiled, which is the one thing every reader wants and
nothing currently provides. Cheapest shape, and it reuses rather than
re-implements: the pre-seed hook already exists and already runs at the
right place — `gen_module_impl`'s `_seed_selfhost_module_globals(self)`
call at `module_gen.py:3003`, which fires when
`_is_selfhost_source_file(current_filename)`. So either

1. run that same pre-seed over EVERY module of the closure, not only the
   compiler's own sources (it is a pure function of the module's parsed
   top-level statements, `_selfhost_module_scalar_globals`'s loop, and
   `gen._module_stmts[mod]` is populated for every compiled module), or
2. hoist the own-scope half of Phase 1.7 (the `_scan_stmt` loop that
   calls `_phase17_set_gtype`, `module_gen.py:10246`) above the imported
   module compile loop, so `_global_to_module` / `_global_var_types` are
   populated for this module before its children are emitted.

(2) is the root fix and (1) is the small one; they are not exclusive, and
(2) also removes the "first writer wins" ordering hazard the pre-seed's
own comment describes. Either way the new type source must be SHARED by
reference into every nested `temp_gen` — the `_module_globals` /
`_global_to_module` sharing block in `emit_resolve.py` is where that
happens, and a per-gen copy is exactly the failure this doc is about.

Pin it with a `test_gimple_runner.py` row on the fixture above (three
modules, `_check_agrees_with_cpython`, compared against CPython's
`['1', '2']`) — it needs no white-box state, unlike the white-box test
`78ec3618` had to add for the routed case, because a user closure can
produce the cycle on its own.

## Why it is filed rather than fixed here

The owner has to publish its globals before its imports compile, which
means moving a Phase-1.7 pass across the imported-module compile loop in
the middle of `gen_module_impl` — a ~11k-line function in the compiled
path, on the self-host closure, with no gate runnable by the worker that
found this. That is a change that wants `make gate` behind it, not a
follow-up commit.