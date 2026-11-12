# CODEGEN_imported_call_initialized_global_export_type

## Summary

A module-scope `var N = g()` (a global initialised from a function call) that
is imported by name from a `.mojo` sibling does not compile. The defining
module types its accessor from the callee's real return type (correct), but
the export table that the importer reads (`module_loader.py`, the `'kind':
'global_var'` entries) answers `void *` for any call-valued RHS. The importer
declares `extern void *<mod>__mojo_global_get_N (void)`, the definer defines
`int64_t <mod>__mojo_global_get_N (void)`, and gcc rejects the importer's
translation unit with "conflicting types". Surfaced while fixing
CODEGEN_imported_float_global_accessor_int64 (that doc is fixed; the
float-literal case passes).

## Repro (measured 2026-11-12, this tree)

`xmodint_defn.mojo`:

    def g():
        return 7

    var N = g()

`xmodint_use.mojo`:

    from xmodint_defn import N

    def main():
        print(N)

    main()

Compiled with `compile_to_gimple(use, do_imports=True, filename=<entry>)` and
`gcc -fgimple`:

    error: conflicting types for 'xmodint_defn__mojo_global_get_N';
           have 'int64_t(void)' ... previous declaration ... 'void *(void)'

Expected: prints `7`. The same program with the call replaced by a literal
(`var N = 7`) compiles and prints `7` (covered by
`test_module_class_attr_from_imported_global`). Same-module
`var N = g()` already prints `7`.

A float-returning callee (`def g(): return 2.5` / `var F = g()`) fails the
same way with `double` vs `void *`.

## Where it is

- Export side: `module_loader.py`, the `.mojo` `var` scan (`_vctype`
  assignment, around the `struct instance / call / container / other` `else`
  arm): every call-valued RHS is `void *`, because the scan is a text scan and
  has no callee return type.
- Definer side: `mojo/backend_gimple/module_gen.py` (the `_phase17_*` scans
  and the `_gscan_declare_global` / VarDecl pre-scan arms) types the global from
  the callee's `func_return_types`, which is correct for the defining module.
- Importer side: `mojo/backend_gimple/emit_infra.py`
  `_emit_imported_global_accessors` declares the extern from the export's
  `c_return_type`.

## Next step

Make the export's `c_return_type` come from the same answer the definer uses,
by construction. Concretely:

1. Have the export answer for a call-valued RHS be derived from the defining
   module's own type inference rather than the text scan's default. The
   natural home is the same `_phase17_value_type` the definer consults, run
   over the defining module's AST (`module_loader` already parses `.mojo`
   siblings for `fn`/`struct` exports, so a call-valued global's callee
   `func_return_types` entry is available there or can be computed by the same
   pass).
2. Failing that, emit the accessor for a call-valued global with the boxed
   `int64_t` in BOTH places (definer and export) regardless of the callee's
   type, and read the value back through the export's `int64_t` with the
   semantic type carried separately. This is the simpler option but gives up
   the typed accessor.
3. Add a regression beside `test_module_class_attr_from_imported_global` in
   `test_gimple_runner.py` for the int case (`N` prints `7`), then one for the
   float case once the export carries `double`.

## Done when

The repro above prints `7` and compiles with `gcc -fgimple`, and the
int-callee and float-callee variants both pass in `test_gimple_runner.py`.
