# The stdlib dylib excludes 130 modules: each generic/inline copy of `dlsym` is emitted under the same bare symbol `_dlsym`

## Status

OPEN. The dylib builds (`built ... from 249 module(s)`), but 130 modules are dropped from it as "symbol already defined",
and every drop is the same symbol. The drop is only a stopgap; the underlying naming is a correctness risk, not just
noise. Found 2026-10-29 while sorting the dylib's screen output.

### 2026-10-29 planning round (no code landed)

**Measured.** The real `dlsym` body is type-dependent, not just a name clash: `std/sys/_libc.mojo:344-352`
(`mojo/stdlib/std/sys/_libc.mojo` in the modular checkout, lines 344-352) is `result = external_call["dlsym", type_of(result)](handle, name)`,
so the C return type of each specialization comes from `result_type`. A copy emitted once under a shared name with `T`
erased returns the wrong pointer type for every caller that is not the first module. So the fix must produce a
per-specialization body, not only a unique name and `static` linkage.

**Compiler facts (read, not run):**
- Ordinary generic function calls are emitted once per module with the type parameter erased. The C name comes from
  `_func_csym` (`mojo/backend_gimple/emit_funcs.py` ~2600) = safe name + `_overload_suffix` (~2166), which hashes the
  PARAMETER types only. Type arguments never enter the name, so `dlsym[NoneType]` and `dlsym[_EnvpType]` both get `_dlsym`
  when their parameter types match (`dlsym`'s parameters are untyped/`_CPointer`-typed, so the suffix is empty).
- Per-instantiation elaboration exists but is narrow. `mojo/backend_gimple/elab_intu.py` `run` (~3220) and `seed` (~3240)
  materialize a function root only when its return annotation names an unbuildable struct
  (`_fn_returns_unbuildable_struct`). A plain generic function such as `dlsym` is never elaborated, so it is never
  given a per-T body.
- The injective naming already exists: `monomorphize.mangle` (`monomorphize.py:190`) is `name_<fields of type args>`, and
  `_materialize` (`elab_intu.py:3130`) names every instantiation it creates with it.

**Decision needed (controller).** Option A (recommended): extend the elaboration seed so EVERY generic function
instantiation with type arguments, bracketed or inferred from an `out`/argument, is materialized through
`monomorphize_source` and named with `monomorphize.mangle`. Two modules then produce two distinct symbols, each with its
own body, and the dedup stopgap is no longer needed for these. Option B: keep erased bodies and only make copies
`static`. Rejected: B is wrong code for `dlsym`, because the bodies differ. A is a large change touching every
generic-function call site, so it needs the full gate.

**Implementation plan for Option A (exact places):**
1. `elab_intu.py` `seed` (~3240): also enqueue `kind == 'fn'` roots whose `_callee_kind` is `fn` and whose template
   (`elaborate.type_param_names`) is non-empty, with args from `_concrete_args` (bracketed) or `_infer_fn_args` (~412,
   inferred). Keep the `_MAX_INSTANTIATIONS` bound.
2. `_materialize` (~3130) already produces `mangled` for the fn kind; keep it. `work.alias[key] = mangled` (~3290) is the
   call-site rewrite map; confirm `_rewrite_callees` (~3528) rewrites bare calls to the alias, not only bracketed ones.
3. Emit side: the `.o` route must not also emit the bare-name copy (`_intu_func_args`, read in `run`'s contract).
4. Dylib: an instantiation used by one module stays file-local (`static`, by `_localize_symbols` or emit-time `static`), so
   the `exclude` path disappears; a cross-module instantiation gets the unique `mangle` name and is exported once.

**Tests that prove it:**
- `test_link_mode.py`: two modules, each calling `dlsym`-shaped generic (a type parameter that changes the return type
  through `type_of(result)`), with different specializations; `fire build` and run; assert each caller gets its own
  specialization's value and the program matches CPython. Also the same-module weak-stub repro (a bare call
  `pick(10)` to a generic with a defaulted bracket parameter, printing "unavailable in compiled mode").
- `build_stdlib_dylib.py` re-run (integrator, full gate): `dedup.log` has no `exclude` lines; module count 379, not 249.

**Blocking the next round:** Option A is not a quick round. It needs the controller's choice (A vs B) and the full gate.
Next round can start on step 1 once A is confirmed.

Separately found while scoping: a bare call to a generic function binds the weak stub in link mode (fixed by
`test_same_module_call_to_generic_with_default_binds_instantiation`, the defaulted-bracket-parameter inference).

### 2026-10-30 Option A step 1 narrowed to type parameters (landed; gate repair)

The elaboration seed's "materialize every generic function instantiation" change (`b06f14cbe`) turned the
landing gate red on master: `stdlib-syntax` (`std/math/math.mojo`, `std/_gpu/_utils.mojo`, the
`case .PASS:` / `comptime __match` refusal) and `std/collections/list.mojo` (`'NoneType' ... 'startswith'`),
plus the test/benchmark files that import them. Measured root cause, three parts, all now fixed in
`mojo/backend_gimple/elab_intu.py`:

- **Value arguments were instantiated.** `check_bounds`' `cpu_default: Bool` was bound to the literal `'0'`,
  `call_location`'s `inline_count` the same way, and `_get_llvm_struct_fields[n, dtype]` / `_get_buffer_...[bytes]`
  were bound to the caller's own parameters. A value parameter's body still holds a `comptime __match` /
  `comptime if` over the value, which cannot fold after substitution. `_fn_args_are_types` now admits a
  function root only when every bound parameter is a TYPE parameter (its annotation is a trait: builtin
  `_BUILTIN_TRAITS`, or a `trait X:` in the template's module). Value parameters stay on the `.o` route.
- **Caller-bound names were instantiated.** `_concrete_args` refuses a bracket argument the enclosing function
  binds (`_bound_in_scope`, fed by `_walk_scoped` in the seed, which replaces `_walk`).
- **Refused instantiations left a None callee.** `_Work.enqueue` reserves the alias as None; a refused
  `Pointer[...]` then made `_rewrite_ctor_calls` write `IdentExpr(name=None)`. Every alias consumer now reads
  through `_live_aliases`.

Verified (narrow, per named file, `compile_stdlib`'s `transpile_file` = codegen + gcc -fsyntax-only): all
eleven gate files PASS, plus `--module math|collections|_gpu|testing` with 0 failures. `test_link_mode.py`'s
`test_two_modules_specialize_one_generic_differently` and `..._binds_instantiation` both PASS (14-16 s each).
Checked on a worktree at current master with this change applied, since this branch's base lacks master's
`runtime/fire_async_runtime.cpp` `<cstdio>` fix. NOT verified: `build_stdlib_dylib.py` (the `exclude`
count and whether `_dlsym` copies now get unique names were not measured), `make gate`, self-host.

Still open: the dylib dedup, Option A steps 2-4 above. Only type-parameter instantiations are materialized
by this change; value-parameter generics stay on the `.o` route, which is what made the gate red.

### 2026-10-30 partial fix (landed; the dylib part is still open)

**What landed.** The repro `test_two_modules_specialize_one_generic_differently` was not a shared-symbol
bug. In the inline `do_imports=True` path, `_register_imported_generics` returned early, so a sibling
module's generic (`scale` from `pkg/gen.py`) was never registered. The bracketed call `scale[2](10)`
then matched nothing and lowered to `(int64_t)0 /* indirect call via SubscriptExpr */`, a silent zero
stub. The guard is removed (`mojo/backend_gimple/emit_funcs.py`), so the call elaborates a concrete
instantiation in both modes. The repro now prints `20`/`30`, and `test_link_mode.py` is 26 passed,
0 failed on this tree.

**What did not change, and is still open.** The dylib still excludes 130 modules as "symbol already
defined" (`_dlsym` in `dedup.log`). The shared-name copies are still emitted with bare names, so the
Option A design above (per-specialization `mangle` names and bodies, dedup removed) is the next step.
Two expectations to re-measure at the integrator's gate:
- `build_stdlib_dylib.py`: the exclusion count should move, and the `skip` count must not increase.
- `_register_imported_generic_structs` has the same `do_imports` guard. It was NOT changed here;
  check whether it hides the same silent-zero shape for generic structs before touching it.

**Not verified here.** No stdlib sweep, self-host build, or `make gate` was run. The integrator owns that.

**A rejected experiment.** Widening the elaboration seed to every generic function (`_fn_has_type_params`
in `elab_intu.py`) did not fix the repro, because the call never reached the seed in the do_imports path.
It also changed dylib skip and exclude counts. Not landed.

### 2026-10-29 repro round (regression test landed, red)

Landed: `test_link_mode.py::test_two_modules_specialize_one_generic_differently` (in `CASES`). Two modules call one
generic with different specializations (`scale[2]` in `a`, `scale[3]` in `b`, body `x * k`). Expected stdout `20`/`30`.

**Measured (red, before any fix):** `python3 test_link_mode.py`-equivalent run through `driver.compile_program`
prints `0` / `0`, rc 0. This is a silent miscompile. The bare symbol `_scale` is shared, so both callers run one body
(`k` erased). It is the same mechanism as `_dlsym`, with a smaller case.

Option A (the recommended design above) is still the next step, not yet implemented. It needs the full gate, so the
integrator should gate it. The test stays red until step 1 lands. Do not add an `expect=` marker for it, because that
would hide the miscompile.

## Measured

`python3 build_stdlib_dylib.py -o …` with `MOJO_DEDUP_LOG` set (the dedup log is now kept, see the commit that added it):

- `dedup.log`: 244 lines, 114 `localize` and 130 `exclude`. Every one names `_dlsym`.
- The 130 excluded modules are `std/gpu/*` and their importers; their symbols are lost from the dylib (clients fall
  back to compiling source, so the failure is silent and slow).
- The 4 `case .PASS:` skips (dtype, logger, address_space, testing/suite) are a separate bug, already on file as
  the `stdlib-syntax` gate failure (fixed by the enum-case / .NAME resolution).

## Why

The stdlib defines `dlsym` as a generic, `@inline(.always)` function (`std/sys/_libc.mojo:353`):

```mojo
def dlsym[result_type: AnyType = NoneType](handle, name, out result): ...
```

Each module that calls it instantiates its own copy, and the copies are emitted as a STRONG global `_dlsym` — the
bare C name, with no instantiation or module suffix. Two modules therefore define the same symbol.

Worse than a clash: two DIFFERENT specializations (`dlsym[_EnvpType]` in `_libc`, `dlsym[NoneType]` elsewhere) share
the name `_dlsym` with different bodies. The dylib keeps the first module's copy, so a later caller of a different
specialization that is linked against the dylib can get the wrong code. The dedup is hiding that by dropping the
modules, not by making the names distinct.

## Next step (plan)

1. Give each specialization a unique, deterministic C name: the mangled name must include the instantiation's type
   arguments (the same mechanism that already gives `_struct_cname`-style unique names for generic structs), so
   `dlsym[NoneType]` and `dlsym[_EnvpType]` cannot collide.
2. Emit an inlined generic copy as `static` (file-local) in the module that instantiates it, unless it is called across
   modules; a copy a caller in another module uses gets the unique name and is exported once.
3. Test: two modules that each call `dlsym` with different specializations, linked into one dylib: no exclusion,
   each call returns its own specialization's result (run it; compare with CPython where applicable).
4. Re-run `build_stdlib_dylib.py` and check `dedup.log` has no `exclude` lines and the module count is 379, not 249.
5. Delete this doc when the exclusions are gone.
