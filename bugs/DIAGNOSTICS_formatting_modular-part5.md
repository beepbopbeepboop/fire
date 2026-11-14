# DIAGNOSTICS: formatting comparison with modular (part 5)

## SPLIT: DIAGNOSTICS_formatting_modular-part1, DIAGNOSTICS_formatting_modular-part2, DIAGNOSTICS_formatting_modular-part3, DIAGNOSTICS_formatting_modular-part4, DIAGNOSTICS_formatting_modular-part5

## Symptom
Our diagnostic formatting for modular test cases does not match the expected format from the modular compiler. We need to compare our output with the modular reference and fix any discrepancies.

## Affected file
- `invalid_downcast_error.mojo` (diagnostic part)

## Acceptance
- The diagnostic output for `invalid_downcast_error.mojo` matches the modular reference format exactly.
- The status section of the bug doc reflects the fix.
- No other files are affected by this change.

## Notes
- This is part 5 of 5 parts for the `DIAGNOSTICS_formatting_modular` bug.
- The full list of affected files includes: `diagnostics_in_missing_locs.mojo`, `diagnostics_in_missing_locs_imports.mojo`, `diagnostic_format.mojo`, `kgen_lsp_check_parse_error.mojo`, and `invalid_downcast_error.mojo` (diagnostic part).
- This part focuses on `invalid_downcast_error.mojo` (diagnostic part).

## Status (2026-11-14): partial

Ground truth (`tools/mojo build` on `test/mojo-integration/invalid_downcast_error.mojo`, from the modular tree): the program is rejected with `error: function instantiation failed` and `note: struct 'invalid_downcast_error::Foo' does not have witness table for trait 'std::format::__init__::Writable'`, located at the `invalid(Foo())` call and through the instantiation chain.

Landed (behaviour change, not yet a user-visible fix):
- `comptime.conforms_to_closed` and `_stdlib_trait_index`: a struct's bases are walked through the module's own declarations and then the stdlib's trait declarations, so `Foo(ImplicitlyCopyable)` is decided not to conform to `Writable`. Previously `conforms_to` answered None (the trait is unknown to the module) and the rebind witness check accepted it. The verdict is False only when the walk is complete; any unresolved base gives None.
- The trait is named by its defining file (`std::format::__init__::Writable`), and the message prefix is `error: function instantiation failed`.
- The struct is named by its declaring module when the caller can attest to it (`elaborate.declaring_module_name`, threaded as `origin_module` into `monomorphize.instantiate`, diagnostics only, not in the CAS key). Direct `Elaborator` calls without an origin still name the instantiation's mangled file.
- The witness diagnostic is re-raised at the instantiation sites (`emit_resolve` x2, `elab_intu`) via `elaborate.is_downcast_witness_diagnostic` rather than swallowed.
- `emit_calls._comptime_conformance_map` factors the bases map out of `_comptime_conforms_to_pred`.

Measured after the change:
- `Elaborator().elaborate_generic_call(src, 'invalid', ['Foo'])` on the real test source now raises the expected message (with the mangled struct name, since no origin is passed).
- `fire build` on the real test source STILL exits 0, and the binary prints `invalid: unavailable in compiled mode`. The rebind check is never reached on that path. Measured by tracing: no `_elaborate_generic_call` for `invalid` or `main` (the `_gen` dispatch in `emit_calls` is never hit for these names), no `elab_intu` work item for `invalid`, and no `rebind[downcast...]` lowering. The call `invalid(Foo())` ends up as an unresolved extern, which module_gen turns into the `unavailable in compiled mode` stub.

Next step (not done): find how `main`'s expression statement `invalid(Foo())` is lowered in the user module. Start in `module_gen.py`, where `_local_generics` strips same-module generic functions and registers them in `_imported_generics`, then trace whether the ExprStmt in `main` reaches `emit_calls`'s call dispatch. A DBG print at `emit_calls.py`'s `if _gen:` shows the call is never dispatched for these names. Once the call is instantiated, the existing rebind check should raise the modular-format error, with the origin module naming the struct.

Also outstanding: the output has no `file:line:col` location lines (the real compiler prints them), and `emit_stmts.py` carries a second copy of `_comptime_conforms_to_pred` that should be merged with the one in `emit_calls.py`.

Verification for this change: `test_downcast_witness_diagnostic.py`, `test_align_decorator_parametric_diagnostic.py`, `test_conforms_to_condition_diagnostic.py`, `test_comptime_assert_diagnostic.py` pass. `compile_stdlib.py`: FAILED 0 (0 expected, 0 unexpected) before and after. `build_stdlib_dylib.py`: 249 modules, 0 skip lines, before and after.
