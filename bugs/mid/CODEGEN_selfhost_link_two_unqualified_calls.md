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

## 2. `_build_executable_d8f39a` — the definition is qualified, the call is not

`jit/arm64.py:248` does a FUNCTION-BODY `from fire import build_executable`
inside `ARM64JIT.compile_and_execute`, and line 252 calls it.

* definition (fire.py:976, re-emitted per importer):
  `_Bool mojo_middle_build_executable_d8f39a (...)` — qualified `mojo_middle`
* the jit.arm64 call site: `build_executable_d8f39a (filename, mojo_src, ...)`
  — BARE

Measured with a probe on `_func_qualifier`/`_func_csym`: at the jit.arm64
gen the entry IS present and correct
(`{'module': 'fire', 'original_name': 'build_executable', ...}`) and tier 4
returns `fire`; at the root gen (`module_name=''`) `build_executable` is
`local=True`, so tier 1 answers `_sanitize_qualifier('')` = `''`. Neither
produces `mojo_middle`, and `_func_csym` was observed returning
`build_executable_d8f39a` (base `build_executable`, qualifier `''`). So the
`mojo_middle_` on the DEFINITION is being produced by some path other than
`_func_qualifier`/`_func_csym` — find that path first. The stub guard
`_MOJO_STUB_mojo_middle_build_executable_d8f39a` agrees with the definition,
so the text-scan/stub side uses the same wrong name.

An older artifact (`fire_build2.ci`, 2026-11-12) had the definition BARE
(`build_executable_d8f39a`), i.e. matching the call site — so this qualifier
appeared during the 2026-11-12/13 session, not long ago.

## Reproduce

```
python3 fire.py build fire.py -O0 -g -o /tmp/mojoc_test
# -> Linking failed: Undefined symbols ... _build_executable_d8f39a, _conforms_to
```

`python3 fire.py --dump-full fire.py` then grep `build_executable_d8f39a` and
`conforms_to (t, tr` in `fire.ci`.

## Done when

`python3 fire.py build fire.py` links, and `python3 test_selfhost.py` passes
both halves.
