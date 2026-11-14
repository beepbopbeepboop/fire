# Lifted lambdas qualify calls through function-body module aliases

Part 1 of `bugs/hard/CODEGEN_selfhost_link_two_unqualified_calls.md`.
Class: easy. One codegen/lowering fix in the lifted-closure path; no new
lowering strategy.

Measured 2026-11-13 on this tree. `mojo/backend_gimple/emit_{calls,stmts,infra}.py`
define `_comptime_conforms_to_pred`, which does a function-body
`import mojo.middle.comptime as _comptime_eval` and returns a lambda that
calls `_comptime_eval.conforms_to(t, tr, _b)`. The definition is
`mojo_middle_comptime_conforms_to_1ba23b (...)` but the lifted lambda body
emits a bare `conforms_to (t, tr, _t2)` with the receiver lowered as a
placeholder:

```
_t1 = (int64_t)0;  /* ct param or undeclared: _comptime_eval */
_t2 = _env->_b;
_t3 = conforms_to (t, tr, _t2);
```

The self-host link then fails with `Undefined symbols ... "_conforms_to"`,
referenced from the lifted `_comptime_conforms_to_pred_lambda_1` bodies in
`emit_infra`, `emit_calls` and `emit_stmts` (section 2 of the parent doc,
`build_executable_d8f39a`, is already fixed).

Root cause, as located in the parent doc: a function-body `import M as A`
alias is not captured into a lifted lambda's visible scope (the lifted
closure seeds imports from `_func_import_frames`/`FromImportStmt` bindings
and a pre-scan of the lambda's own body, neither of which records a plain
`import ... as` alias), and even when the alias name is present the
lowering path does not treat it as a module marker — `_lower_IdentExpr` has
no module-alias branch and the `_lower_call` / `_lower_method_call` callee
path does not consult a module alias for the receiver, so the member call
resolves on the placeholder `int64_t` and emits the bare member name. The
alias name `_comptime_eval` collides with the `_comptime_*` naming the
comptime machinery uses, which may contribute to it reading as a comptime
parameter and is worth checking.

## Goal

A lifted lambda that calls through a module alias introduced by a plain
function-body `import ... as alias` in its enclosing function emits the
qualified callee symbol, the same symbol a direct (non-lifted) call in that
enclosing function would emit for `alias.member(...)`. The alias must be
recognized as a module namespace in the lifted body (not as a value, not as
a comptime parameter, and not captured as a closure env slot) even when its
spelling overlaps comptime/internal naming such as `_comptime_*`.

## Acceptance

- Compiling a small module where a function does `import <module> as <alias>`
  in its body and returns a lambda that calls `<alias>.<func>(...)` produces
  a lifted lambda body that calls the qualified symbol of `<func>` (the
  defining module's qualifier plus the function's mangled name), not the
  bare member name and not a placeholder receiver.
- The lifted lambda does not read the module alias from its closure/env
  struct, and the alias is not lowered as `(int64_t)0` with an
  "undeclared"/"ct param" placeholder in that body.
- A function-body `import ... as alias` whose name collides with comptime
  naming (e.g. `_comptime_eval`) is treated as the module alias, not as a
  comptime parameter, in the lifted lambda body.
- A direct (non-lifted) `alias.func(...)` call in the same enclosing function
  keeps today's qualified lowering; this change does not alter how module
  aliases lower outside a lifted closure.
- A lambda that calls a name that is genuinely a captured value (not a module
  alias) keeps today's capture/env behavior.
- No special-casing of `comptime`, `conforms_to`, or any specific module or
  function name; the fix is generic over function-body module aliases.

## Done when

File: `test_codegen_selfhost_link_two_unqualified_calls_part1.py` (repo root).

Command: `python3 test_codegen_selfhost_link_two_unqualified_calls_part1.py`

It compiles a minimal self-contained repro: a defining module exporting a
free function, and a consumer whose function does a function-body
`import <defining module> as _comptime_eval` and returns a lambda that calls
`_comptime_eval.<func>(...)`, then asserts the emitted GIMPLE/C for the
lifted lambda contains the defining module's qualified symbol for `<func>`
and contains no bare call to the unqualified member name and no
`undeclared: _comptime_eval` / comptime-parameter placeholder for the alias.
The test is red today (the lifted body emits the bare member name with a
placeholder receiver). It must pass.

## Where to start

`mojo/backend_gimple/emit_loops.py::_gen_lifted_closure_body` seeds the
closure's import scope from `_func_import_frames[outer_name]` and pre-scans
the lambda's own body (`_collect_body_import_bindings`), but function-body
`import M as A` (`ImportStmt`) aliases are recorded by neither. The whole-
module pre-scan (`emit_funcs.py::_prescan_func_import_frames`) and the
body-binding collector (`emit_funcs.py::_collect_body_import_bindings`) need
to register such aliases so the lifted closure's scope sees them (the same
way they already see `FromImportStmt` bindings), and the alias must land in
`gen._module_alias_names` for the lifted body's module-marker checks.

On the lowering side, `_lower_IdentExpr` in `mojo/backend_gimple/emit_exprs.py`
has no module-alias branch for names in `gen._module_alias_names` (compare
`_gen_stmt_ImportStmt`'s `{cname} = (int64_t)0;  /* module marker */` body
emission), so a bare read of the alias in a lifted body falls through to a
placeholder. The `_lower_call` / `_lower_method_call` callee path lowers the
receiver `A` through `_lower_IdentExpr` and never consults the module-alias
/member resolution the module-marker branches of `_lower_MemberExpr` use;
adding a `var_types` entry for the marker was tried and reverted because the
`_lower_MemberExpr` module-marker branches are gated on
`module_name not in gen.var_types`. The fix needs `_lower_IdentExpr` to
answer a module marker for a name in `gen._module_alias_names`, plus a
module-alias branch in the `_lower_call`/`_lower_method_call` callee path
that resolves `alias.member` to the qualified symbol (reusing the existing
member/module resolution rather than inventing a parallel path).

Keep the fix generic: record and resolve any function-body `import ... as`
module alias in a lifted closure, independent of the alias's spelling.
