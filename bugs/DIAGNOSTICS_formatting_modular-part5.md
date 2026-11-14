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

## Status (2026-11-14, later): root cause of the "never dispatched" call found and fixed

Two defects, both measured with an in-process driver (`compile_to_gimple`,
0.2 s) rather than a full build:

1. `emit_stmts._gen_stmt_ExprStmt` lowers a bare statement call to a plain
   function through its own fast path and never reached `_lower_call`'s
   `_elaborate_generic_call` arm (`_lower_call` was only entered for the
   argument `Foo()`). `invalid(Foo())` therefore became `invalid (_t1);`, an
   extern against the weak "unavailable in compiled mode" stub. Fixed: a bare
   call whose name is in `gen._imported_generics` (and not locally bound) is
   routed through `_lower_call`.
2. Even routed, `elaborate_generic_call_inferred` returned None: `x: T` was
   bound only from `c_to_mojo(ctype)`, and a struct value's C type `Foo *` is
   not in that table (it is equally a `Pointer[Foo]`, so guessing is wrong).
   Fixed: `emit_resolve._constructed_struct_type` supplies the Mojo type when
   the argument is syntactically a direct constructor call of a module struct,
   threaded as `arg_mojo_types` through `elaborate_generic_call_inferred` ->
   `infer_type_args` -> `_unify_param_ann`.

Result: `compile_to_gimple` on the real test source now raises `error: function
instantiation failed` / `note: struct 'invalid_downcast_error::Foo' does not
have witness table for trait 'std::format::__init__::Writable'`. Test:
`test_inferred_generic_statement_call.py` (4 cases: statement call
instantiated, value/statement forms agree, rejected instantiation reported,
local shadow left alone). Stdlib compile and dylib green (owner run).

Remaining (this doc stays open): the `file:line:col` location lines and the
instantiation-chain notes the real compiler prints; merging the second
`_comptime_conforms_to_pred` in `emit_stmts.py` with the one in `emit_calls.py`;
`_imported_overloads` calls in statement position take the same fast path and
probably have the same defect (not measured).

### 2026-11-14 (evening): duplicate predicate merged

`emit_stmts._comptime_conforms_to_pred` (an inlined copy of the one in
`emit_calls.py`, identical merge logic) is deleted; `emit_stmts` calls
`ggc._comptime_conforms_to_pred`. `compile_stdlib.py` FAILED 0 (0 expected, 0
unexpected), `build_stdlib_dylib.py` 249 modules / 0 skip lines.
Still open: the location lines and instantiation-chain notes, an end-to-end
`fire build` exit-code confirmation, and the `_imported_overloads` statement-path
question.
