# Link mode: a compiled closure references `mojo/middle/solvers.py`'s `DispatchSolver` methods and never emits them

**Status: OPEN, not fixed. Found 2026-10-02 on
`work/master-selfhost-fix3` at 797e97c1, while fixing the self-host
closure's three `gcc` errors in `mojo/middle/offload.py` (that work is
done; see `git log --oneline e3779dba..HEAD`).** Pre-existing: nothing in
that branch touched `mojo/middle/solvers.py`, struct-method emission, or
link mode, and the C this is about is generated with the alias fix
already in. Same FAILURE MODE as the two `<module>_toplevel` families that
were in the now-deleted
`bugs/CODEGEN_module_toplevel_undefined_in_selfhost.md` (deleted 2026-10-02
with both fixed: a symbol the closure declares and calls with no definition
anywhere in the link, and `'struct _<mod>_toplev' has no member named 'NAME'`
for a from-imported constant) but a different symbol set, a different module
and a different entry point, and neither of those docs' clusters covered it.

## What I ran

A two-file program compiled through `driver.compile_program` (LINK mode,
`do_imports=True` + `link_imports=True`), where the root imports
`fire_compiler` — i.e. the compiler's own source as a compiled program's
closure:

    # helper.py
    class Thing:
        def __init__(self, value):
            self.value = value

    class Alias:
        def __init__(self, value):
            self.value = -1

    # prog.py
    import helper as h

    def build(n):
        Alias = h.Thing
        node = Alias(value=n)
        print(node.value)
        return node.value

    def main():
        build(7)

    main()

    driver.compile_program(prog, src, output=exe, run=False)

## What I saw

`compile_program` returns `None`: the generated C compiles (0 gcc errors)
and the LINK fails.

    link failed: Undefined symbols for architecture arm64:
      "_mojo_middle_solvers_DispatchSolver__emit", referenced from:
          _mojo_backend_gimple_emit_stmts__with_emit_exits_902184 in 66016b3.o
      "_mojo_middle_solvers_DispatchSolver__emit_call", ... (same)
      "_mojo_middle_solvers_DispatchSolver__new_temp", ...
      "_mojo_middle_solvers_DispatchSolver__signature_ctypes", referenced from:
          _mojo_backend_gimple_emit_funcs__local_def_pts_751315 in 66016b3.o
      "_mojo_middle_solvers_DispatchSolver__struct_method_csym", ...

## What I confirmed about it

In the generated `client.c` (45 MB, saved from the failing run):

- `typedef struct DispatchSolver {` IS emitted (line ~1922), so the struct
  itself was registered;
- `int64_t mojo_middle_solvers_DispatchSolver__emit (...);` IS declared
  (line ~1025646) and IS called (lines ~1090189, ~1090430) — five
  references;
- there is NO definition anywhere in the file.

So this is the emission side dropping the METHOD BODIES of a struct whose
layout and forward declarations it emitted, in link mode, for a module
reached transitively (`mojo/middle/solvers.py` is four levels down:
`fire_compiler` -> ... -> `gimple_codegen` -> `mojo/middle/solvers.py`).
The same closure compiled through `compile_to_gimple(do_imports=True)`
(the `selfhost` / `mojoc` / `bootstrap-stage2-cc` path) DOES define them,
which is why the self-host jobs are green and this only shows up through
`driver.compile_program`.

## Exact next step

`gen_module_impl`'s struct-method emission loop, in the link-mode
(`link_imports=True`) configuration, is where to look: compare the set of
`ci.methods` / `_struct_method_overload_ids` entries it walks against the
`_all_closures` / `_method_mangled_names` marks for a transitively
imported module, and find where a method that reached the forward-
declaration pass is dropped before the body pass. The cheapest bisect is
the emitter's own "methods referenced but not emitted" bookkeeping if one
exists; failing that, dump `sorted(mangled method names)` per module in
link mode and diff against the non-link run, which agrees.

Not filed as a fix because link mode is outside this branch's claim
(`tools:selfhost-fix3`) and the answer needs a link-mode run to confirm —
a light-worker change here would land blind.