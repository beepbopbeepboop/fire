# CODEGEN_imported_global_export_type_residual_call_shapes

## Summary

`var N = <call>` imported by name from a `.mojo` sibling still fails "conflicting
types" for the call shapes the export scan does not model. The whole-RHS
`NAME(...)` case of a same-file `def` is fixed (see module_loader.py's
`_ml_plain_call_callee` and its RHS-shape arm); these are the remainder.

## Repro (measured 2026-11-12, this tree)

Defining module `xr_defn.mojo`, importer `xr_use.mojo` doing
`from xr_defn import N` and `print(N)`, compiled with
`compile_to_gimple(use, do_imports=True, filename=<entry>)` and `gcc -fgimple`:

- `def g(): return 7` / `var N = g() + 1`: gcc error
  `conflicting types for 'xr_defn__mojo_global_get_N'; have 'int64_t(void)'`.
  The export answers `void *` (the RHS is not a whole-call, so the scan falls
  to its default). The defining module types the global `int64_t`.
- `def k(): return "a"` (no return annotation) / `var N = k()`: gcc error
  `conflicting types ...; have 'char *(void)'`. The definer infers `char *`
  from the body; the export scan has no body inference and answers
  `int64_t` (or `void *`), so the two disagree.

## Where it is

- `module_loader.py`, the `.mojo` `var` scan, RHS-shape arm. Only a
  whole-RHS `NAME(...)` whose `NAME` is a same-file `def` with an annotated
  return reaches the callee-return rule; everything else defaults to `void *`.
- The definer side is `mojo/backend_gimple/module_gen.py`
  `_phase17_value_type` (`BinOp` arm and the unknown-callee fallback via
  `_quick_type`) and the unannotated-`def` return inference in
  `mojo/backend_gimple/emit_funcs.py` (`gen.func_return_types[node.name] =
  ret_type`, around line 3485).

## Next step

1. For `var N = g() <op> ...` (any expression whose type the definer takes
   from `_quick_type`), the export needs the same answer. Either port that
   inference into the text scan (not sustainable) or have the importer of a
   `global_var` with no reliable text answer take the definer's type from the
   defining module's AST: `module_loader` already parses `.mojo` siblings for
   fn/struct exports, so run `_phase17_value_type` over that AST.
2. For an unannotated `def`, the export's `c_return_type` must come from the
   same body inference `emit_funcs.py` uses, not a default.
3. Regression tests go beside `test_module_class_attr_from_imported_global`
   in `test_gimple_runner.py` (both shapes must print the value), and the
   export-table cases beside `test_call_initialized_global_export_takes_callee_return_type`
   in `test_module_loader_stdlib.py`.

## Done when

Both repro variants compile with `gcc -fgimple` and print `8` and `a`
respectively, through `_compile_two_files_do_imports_and_run`.
