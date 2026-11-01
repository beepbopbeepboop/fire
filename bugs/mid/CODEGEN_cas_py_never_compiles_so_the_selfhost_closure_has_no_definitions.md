# `cas.py` does not compile, so the self-host closure's call sites have no definitions

## Status

OPEN. Blocks `make mojoc`, and therefore every self-host and bootstrap step.
NOT introduced by the bugs3 merges — see "Pre-existing" below for the measured
comparison — but it is what `make mojoc` reports today, and it is newly
*diagnosable* rather than silently absorbed (the two rollback fixes in this
branch's history are why: see "Why it is newly visible").

`fire.py build fire.py` ends with 38 errors in four classes:

| count | class |
|---|---|
| 14 | `assignment to 'char *' from 'int'` in `driver.py:52` (`prog_key`) |
| 11 | `implicit declaration of function 'cas_*' / 'version_*' / 'imports_*'` |
| 3 | `assignment to 'Span *' from 'int64_t'` in `parsing_floats.mojo` |
| rest | assorted gimple conversions, `myinterpreter_MojoFunction___call__` arity |

## The shape

`fire.py` imports `driver` on its build path; `driver.py` imports `cas`,
`build_stdlib_dylib`, `build_config`, `version` and `formal.imports`. In the
compiled closure those eleven cross-module FREE FUNCTIONS therefore appear both
as definitions (in their own module's text) and as call sites (in `driver.py`).

**The definitions are not there.** `cas.py` fails to compile, so
`_compile_imported_module` falls back to source inclusion and no
`cas_<fn>` symbol is emitted at all — which is why gcc says

```
driver.py:52:9: error: implicit declaration of function 'cas_toolchain_fingerprint_e253d6';
                                        did you mean 'toolchain_fingerprint'?
```

and why the follow-on is `assignment to 'char *' from 'int'`: an
implicitly-declared function is typed `int`, and the result is assigned to a
`char *`.

## The actual root cause is upstream, in the stdlib

`fire.py build cas.py` on its own fails with three

```
stdlib/std/collections/string/_parsing_numbers/parsing_floats.mojo:371:8:
  error: assignment to 'Span *' from 'int64_t' makes pointer from integer without a cast
```

which is the stdlib dylib refusing to build, so the module falls back to
source and `cas.py` never gets its definitions. So the eleven implicit
declarations are a SYMPTOM. The defect is:

`get_sign(x: StringSlice[_]) -> Tuple[Float64, type_of(x)]` returns
`(-1.0, x[byte=1:])` and `(1.0, x)`. `_infer_return_elem_type` infers the
tuple's element type as `Span *` — measured, directly:

```
>>> _infer_return_elem_type(get_sign.body, func_def=get_sign)
'Span *'
```

Both elements are `FloatLiteral` (→ `double`) and an `IdentExpr` naming the
`Span *`-typed parameter `x`. Neither is a CONTAINER, so the right answer is
"not a container" (`None`), and the caller keeps the `int64_t` default. What
happens instead is that the `Span *`-typed parameter leaks in through
`var_types` and then `TypeLattice.join_all(['double', 'Span *'])` picks the
pointer — because `TypeLattice.join` deliberately returns the pointer when it
meets a float, which is correct for ARITHMETIC and wrong for a heterogeneous
tuple's element type, which has no single element type at all.

At the call site, `sign_and_stripped[0]` is then read through `mojo_list_get_int`
(the right accessor for slot 0, a `Float64`) but ASSIGNED into a variable
declared `Span *`, because the tuple's one element type says every slot is a
pointer.

Reproduce: `fire.py --dump` the stdlib module and read `_t25 = (Span *)_t24;`
followed by `sign = _t25;`.

## Next step

1. `_quick_container_elem` should answer `None` for an `IdentExpr` that names a
   SCALAR-typed parameter, or `_infer_return_elem_type` should refuse to
   `join_all` a mix that includes a pointer and a float for a TUPLE (the
   distinction `TypeLattice.join` cannot make and this call site can).
   Measured to be pre-existing: master infers `'Span *'` for the same body.
2. With the stdlib building, `cas.py` compiles and the eleven implicit
   declarations disappear on their own — the mangling half is not the bug.
3. Only if some remain: `_SELFHOST_SIGS` plus a `_effective_param_types` tier
   that consults it. **Tried and rejected**: adding the eleven to
   `_NO_OVERLOAD_MANGLE` breaks
   `test_gimple.py::test_known_function_not_shadowed_by_global_fnptr` (which
   asserts the mangled `cas__hash (` spelling), and adding a
   `_SELFHOST_PARAM_TYPES`-first tier to `_effective_param_types` breaks
   `test_aliased_and_reexported_imports_resolve_to_the_defining_module`.
   Both are recorded because the next person will try them.

## Why it is newly visible

`_compile_imported_module` rolls back seven emission marks when a subtree
raises and its generated text is discarded — `_funcptr_builtins_needed`,
`_emitted_funcptr_builtins`, `_emitted_structs`, `_emitted_ptr_helpers` and
four more. It did NOT roll back `_str_pool_declared` or `_emitted_c_helpers`.
Those two are fixed in this branch (commits 46583c3d and e242deaa), taking
`fire.py build fire.py` from 1308 errors to 38 — the discarded subtree had been
leaving ~1300 dangling `_slit_N` and `_mojo_sizeof_*` references behind, which
gcc reported before it ever reached this one.

At `d0796643` (this branch's starting point) the same build succeeds, and
`fire.py build cas.py` there fails with a different error — 17x
`'_cas_globals' undeclared`, a symbol that exists nowhere in the tree. So
`cas.py` has never compiled in this window; the base build only passed because
its failures were absorbed rather than reported.

## Pre-existing

Both trees fail to compile `cas.py`:

| tree | `fire.py build fire.py` | `fire.py build cas.py` |
|---|---|---|
| `d0796643` (branch base) | exit 0, 0 errors | exit 1, 17x `_cas_globals undeclared` |
| this branch | exit 1, 38 errors | exit 1, 3x `Span *` in `parsing_floats.mojo` |

Not attributable to the bugs3 merges.