# CODEGEN: two undefined symbols left in the self-host link

**Found:** 2026-11-13, `fire.py build fire.py` after the compile errors were
cleared (see bugs/GATE_selfhost_closure_cannot_compile.md). The compile is now
clean; LINK fails with exactly two symbols:

```
Linking failed: Undefined symbols for architecture arm64:
  "_build_executable_d8f39a", referenced from:
      _jit_arm64_ARM64JIT_compile_and_execute in fire.o
  "_conforms_to", referenced from:
      _mojo_backend_gimple_emit_infra__conformance_pred_lambda_3 in fire.o
      _mojo_backend_gimple_emit_calls__comptime_conforms_to_pred_lambda_1 in fire.o
      _mojo_backend_gimple_emit_stmts__comptime_conforms_to_pred_lambda_1 in fire.o
```

Both are cross-module references emitted WITHOUT the module qualifier their
definition carries — the same class as the `_mojo_type` extern fixed in
`441bf6aae`, but on paths that fix did not reach.

## 1. `_conforms_to` — a module alias is not captured into a lifted lambda

`mojo/backend_gimple/emit_{calls,stmts,infra}.py` each do a FUNCTION-BODY
`import mojo.middle.comptime as _comptime_eval` inside
`_comptime_conforms_to_pred`, and the lambda they return calls
`_comptime_eval.conforms_to(t, tr, _b)`.

The definition is `int64_t mojo_middle_comptime_conforms_to_1ba23b (int64_t,
int64_t, MojoDict *)` (fire.ci:476395 in the 2026-11-13 dump). The lifted
lambda bodies instead emit a BARE `conforms_to (t, tr, _t2)`, and the
receiver read is a placeholder:

```
_t1 = (int64_t)0;  /* ct param or undeclared: comptime_eval */
_t2 = _env->_b;
_t3 = conforms_to (t, tr, _t2);
```

So `_comptime_eval` is NOT in the lifted closure's env: the capture analysis
does not treat a module alias (a module marker, not a value) as a capture, the
name is unknown in the lifted body, and `_lower_IdentExpr`'s fallthrough
(`emit_exprs.py:1237-1241`) answers the `(int64_t)0` placeholder. The member
call then resolves on an `int64_t` receiver and emits the bare member name.

Note the alias name itself is suspicious: `_comptime_eval` collides with the
`_comptime_*` naming the comptime machinery uses, which may be why it reads as
a comptime parameter. Worth checking before fixing the capture set.

## 2. `_build_executable_d8f39a` — FIXED: `_sanitize_qualifier('')` picked up a bogus remap

`jit/arm64.py:248` does a FUNCTION-BODY `from fire import build_executable`
inside `ARM64JIT.compile_and_execute`, and line 252 calls it. The definition
(fire.py:976) came out as `mojo_middle_build_executable_d8f39a` while the call
site emitted `build_executable_d8f39a` — undefined symbol at link.

Root cause: `_func_qualifier`'s tier 1 answers `_sanitize_qualifier(gen.module_name)`,
and the ROOT gen's `module_name` is `''`. `_sanitize_qualifier` then consults
`gen._inline_module_qualifiers`, which is keyed BOTH by the sanitized module of
every inlined file (`module_gen.py:5088`) AND by
`module.lstrip('.').replace('.','_')...` for relative imports
(`funcs_shared.py:1276`). A `from . import x` therefore writes the key `''`,
and the last such writer in a whole-closure build was `mojo.middle` — measured
directly: the dict contained `('', 'mojo.middle')`. So `_sanitize_qualifier('')`
returned `mojo_middle`, prefixing EVERY function the root module defined, while
importers' call sites (resolved through their own non-empty module) stayed
bare.

Fixed in `_sanitize_qualifier`: an empty module name returns `''` before the
remap. Verified: `build_executable_d8f39a` is now spelled identically at the
definition, the `/* from fire */` extern, the `_MOJO_STUB_` guard and both call
sites, and the link error for it is gone.

The deeper `_inline_module_qualifiers['']` collision is NOT fixed here — the
guard only makes an empty name immune. If some other path reads that key, it
will still see `mojo.middle`.

## 3. `_conforms_to` — a module alias is not visible in a lifted lambda (OPEN)

`mojo/backend_gimple/emit_{calls,stmts,infra}.py` each do a FUNCTION-BODY
`import mojo.middle.comptime as _comptime_eval` inside
`_comptime_conforms_to_pred`, and the lambda they return calls
`_comptime_eval.conforms_to(t, tr, _b)`.

The definition is `int64_t mojo_middle_comptime_conforms_to_1ba23b (int64_t,
int64_t, MojoDict *)`. The lifted lambda bodies instead emit a BARE
`conforms_to (t, tr, _t2)`, with the receiver read as a placeholder:

```
_t1 = (int64_t)0;  /* ct param or undeclared: _comptime_eval */
_t2 = _env->_b;
_t3 = conforms_to (t, tr, _t2);
```

`_gen_lifted_closure_body` (`emit_loops.py:3614-3621`) seeds the closure's
import scope from `_func_import_frames[outer_name]` — which only holds
`FromImportStmt` bindings — and then pre-scans the lambda's OWN body. A
function-body **`import M as A`** alias is recorded by neither: registering one
in `_collect_body_import_bindings` was tried and did NOT help, because the
callee path is `_lower_call` → `_lower_method_call`, which lowers the receiver
`A` through `_lower_IdentExpr`, and `_lower_IdentExpr` has no module-alias
branch at all (the module-marker handling lives in `_lower_MemberExpr`, which
the call path never consults). Adding a `var_types` entry for the marker was
also tried and reverted: every `_lower_MemberExpr` module-marker branch is
gated on `module_name not in gen.var_types`, so it would suppress them.

So the fix needs `_lower_IdentExpr` to answer a module marker for a name in
`gen._module_alias_names` (as `_gen_stmt_ImportStmt`'s
`{cname} = (int64_t)0;  /* module marker */` does in a body), plus a
module-alias branch in the `_lower_call`/`_lower_method_call` callee path.

Note the alias name itself is suspicious: `_comptime_eval` collides with the
`_comptime_*` naming the comptime machinery uses, which may be why it reads as
a comptime parameter. Worth checking first.

## Reproduce

```
python3 fire.py build fire.py -O0 -g -o /tmp/mojoc_test
# -> Linking failed: Undefined symbols ... _conforms_to
```

`python3 fire.py --dump-full fire.py` then grep `conforms_to (t, tr` in
`fire.ci`.

## Done when

`python3 fire.py build fire.py` links, and `python3 test_selfhost.py` passes
both halves.
