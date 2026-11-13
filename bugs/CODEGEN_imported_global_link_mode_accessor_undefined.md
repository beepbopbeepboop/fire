# CODEGEN_imported_global_link_mode_accessor_undefined

## Summary

`fire.py build` of an importer that reads a module-scope `var` initialised
from a call-valued RHS (`var N = g() + 1`, or `var N = k()` with an
unannotated `def`) does not link the defining module's accessor in the
separate-object link. The link fails with
`"_xr_defn__mojo_global_get_N", referenced from: __toplevel`, and the driver
silently falls back to the single-translation-unit inline path, which
produces the correct output. The defect is hidden by that fallback. The
export-table type is also still the text scan's guess in this mode.

## Repro (measured 2026-11-12, after the do_imports fix on this branch)

    mkdir -p .tmp/lkD
    printf 'def g(): return 7\nvar N = g() + 1\n' > .tmp/lkD/xr_defn.mojo
    printf 'from xr_defn import N\nprint(N)\n'     > .tmp/lkD/xr_use.mojo
    python3 fire.py build -o .tmp/lkD/out .tmp/lkD/xr_use.mojo
    .tmp/lkD/out

Observed: `link failed: Undefined symbols ... "_xr_defn__mojo_global_get_N",
referenced from: __toplevel in <hash>.o`, then `Built: .tmp/lkD/out`, then
`8` (from the inline fallback). The unannotated-`def` shape
(`def k(): return "a"` / `var N = k()`) gives the same undefined accessor and
prints `a`.

Control: `var N = 7` (already worked before this branch) also prints a
`link failed` line, but its undefined symbols are generic runtime entries
("5 undefined" of the export table), not the accessor. That generic link noise
is pre-existing and is not this bug.

Before the do_imports fix (same repro, pre-fix tree) the inline fallback
also failed with "conflicting types for 'xr_defn__mojo_global_get_N'", so the
do_imports fix is what made the fallback succeed. The separate-object link
still fails for this shape.

## Where it is

- `driver.py` `compile_program`: the link-mode pipeline and its fallback to
  the inline path.
- The definer's separate object: its accessor `xr_defn__mojo_global_get_N`
  is not defined in it (the undefined reference shows the symbol is absent
  from the link). Not yet established why. Candidate: the definer compiled in
  link mode does not emit an accessor for a call-initialised global, or emits
  it under a different symbol. Unverified.
- `module_loader.py`, the `.mojo` `var` scan RHS-shape arm: in this mode the
  definer's own gen is not in the importer's process, so
  `_reconcile_imported_global_accessors` (emit_infra.py) has no
  `_module_globals` entry to read, and the export's guessed type stands.

## Next step

1. Compile only the definer in link mode and `nm` its object: does
   `xr_defn__mojo_global_get_N` exist, and under what name? Find the emit path
   that decides whether a link-mode module gets accessors for call-initialised
   globals (`module_gen.py` `_module_globals` accessor block near the
   `globals_list` loop, and the link-mode branch that writes the object).
2. If the definer does not emit it, fix that emit path. The accessor must be
   emitted whenever `_module_globals[mod]` holds the global.
3. For separate-TU mode, the export's type should come from the definer's
   AST, as the earlier `CODEGEN_imported_global_export_type` doc proposed:
   run `module_gen._phase17_value_type` over the sibling's statements. The
   text scan cannot reproduce it for expression RHS shapes.
4. Regression test: a `fire build` case (not `_compile_two_files_do_imports_and_run`,
   which is the single-TU path) asserting the link succeeds with no
   `link failed` line for `var N = g() + 1`, with the output `8`.

## Done when

`python3 fire.py build` of the repro above links without the
`link failed` / undefined-accessor line for both shapes, and prints `8` and
`a` from the linked executable (not the inline fallback).
