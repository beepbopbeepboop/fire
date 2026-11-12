# CODEGEN: an imported function whose parameters are partly UNANNOTATED gets an extern with the definer's arity and the scan's trailing-parameter types, and every call through it fails

Status: OPEN. Filed 2026-11-12 while fixing the `gen_module_impl` `char *` ← `int64_t` import-extern clobber (that doc is deleted with its fix); the reduced single-module repro of `mojo/backend_gimple/module_gen.py` (the same sanctioned vehicle, `build_stdlib_dylib.compile_module_to_c`) still fails with this class — 33 of the 40 remaining errors. Not part of that fix: the clobbered arm and this one read the same `sym_info` but fail on different fields.

## Symptom

In the importer's generated C, the import-extern preamble types the imported function from TWO independent inferences that disagree about arity:

```
error: too many arguments to function 'module_shared__register_sym_ab0ffa'; expected 2, have 7
error: passing argument 1 of 'module_shared__register_sym_ab0ffa' makes pointer from integer without a cast [-Wint-conversion]
```

Measured instances in the same single-module build (source line of the failing call in `mojo/backend_gimple/module_gen.py`): `_register_sym` (8901, 8999), `gmi_collect_self_assigns` (8398), `selfhost_homogeneous_tuple_ret_funcs` (808), `gmi_find_comptime_one` (5084), `gmi_prefold_toplevel_comptime` (5066), `gmi_nested_struct_defs` (3643, 3696, 3888), `gmi_scan_imported_global_homes` (15495), `gmi_scan_try_imports` (15340), `gmi_phase17_collect_appends` (15311), `gmi_collect_return_values` (14215), `gmi_scan_cpp_nested_imports` (13467).

## Suspect

`module_loader`'s text scan of the defining module's `def` line DROPS every unannotated parameter (`if ':' in param` at module_loader.py:838), so the importer's snapshot (`sym_info['parameters']` / `c_parameters`) is SHORTER than the definition. The import-extern block (gen_module_impl, mojo/backend_gimple/module_gen.py, the non-empty-parameter branch) replaces the scan's parameter list with the definer's ONLY when `_imported_def_pts(self, _sn, True)` is non-empty — i.e. only when the definer's resolved list was written to `_imported_home_param_types` (the one write site, emit_funcs.py:634, from the home module's own parsed `FunctionDef` through `_signature_ctypes`, falling back to the scan's `c_parameters` when the AST is not resolvable). When the fallback chain lands on the scan's dropped list (or the definer never compiled in this closure), the extern keeps the scan's arity and the call site passes the definer's — `too many arguments`, plus a type argument from a POINTER parameter into an INTEGER-typed trailing slot for every shifted position.

## Scope

1. Decide which inference owns the arity (the definer's list is the one the mangled name's overload hash is computed from — the same reason the empty-parameter arm and the parameter-type block beside it give the definer's list precedence), and make the fallback chain resolve to it.
2. Reduce one instance (e.g. `gmi_prefold_toplevel_comptime`: 1 scanned vs 2 defined) to a two-module program and add it as a regression test with the gcc `-fgimple -Os -g -ftrivial-auto-var-init=zero` verdict.
3. Fix at the source (the loader's scan or the fallback chain), not with a cast at the call.

## Done when

The reduced instance compiles under `gcc -fgimple -Os -g -ftrivial-auto-var-init=zero`, and the single-module repro of `mojo/backend_gimple/module_gen.py` no longer reports `too many arguments` for the instances above. The full self-host `fire.o` step is the integrator's check; a worker reports it as not run.
