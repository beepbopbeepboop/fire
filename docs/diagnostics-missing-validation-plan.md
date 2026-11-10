# DIAGNOSTICS missing-validation umbrella — remaining work plan

Umbrella: `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`.

Landed 2026-11-09 (see the umbrella's Status): missing-module diagnostic
(inline + link, first missing component), `out` + return type, runtime assert
message, `except <name>:` catch-all binding, ambiguous same-name import,
qualified-member leak (`mod.name`).

This plan covers the remainder. Each step is independently dispatchable; the
scope names the files, the test names the observable that must change.

## 1. Generic `where`-clause enforcement at call sites

**Scope:** `mojo/backend_gimple/emit_resolve.py`, `emit_calls.py`,
`mojo/middle/comptime.py`. When a call instantiates a generic whose `where`
clause is provably false for the supplied type arguments, raise
`error: invalid call to '<fn>': violated constraint` (modular
`tuple_contains_type_mismatch_error.mojo`, `tuple_first_of_error.mojo`).
**Files:** the constraint evaluator already folds comparisons and `and`/`or`
(see the umbrella Status); the gap is evaluating a `where` clause against the
CALL site's concrete type arguments and refusing the instantiation.
**Test:** a `f[T: Equatable](x: T) -> Bool where T == Int` called as
`f[Float64](1.0)` must fail to compile. Regression:
`test_where_clause_call_site_diagnostic.py`.
**Acceptance:** the modular `tuple_*` tests' error lines are reproduced; a
satisfied `where` clause still compiles.

## 2. Trait conformance diagnostics

**Scope:** conformance checking for `struct X(...)` trait lists. Sub-steps:
- 2a. Conditional conformance (`Copyable where conforms_to(T, Copyable)`):
  report `constraint for 'X' does not imply constraint for ancestor trait 'Y'`
  and the diamond case (`struct_conditional_trait_conformance_errors.mojo`).
- 2b. Defaulted trait method signature mismatch:
  `'Map[mapFn]' does not implement all requirements for 'Strategy'`
  (`defaulted_trait_method_bad_conformance.mojo`).
- 2c. Enum `_enum_is_exhaustive` type check
  (`enum_exhaustive_errors.mojo`).
- 2d. Downcast witness table (`invalid_downcast_error.mojo`).
- 2e. MOCO-4400 no-crash + `does not implement all requirements for 'Iterable'`.
**Files:** `mojo/backend_gimple/emit_resolve.py`, `mojo/middle/funcs_shared.py`,
the trait registry.
**Test:** each modular test's `error:` line is reproduced; no crash.
**Acceptance:** all five modular files fail with the expected diagnostic.

## 3. Inferred-parameter dependency errors

**Scope:** `autoparam_dependency_errors.mojo`. An inferred parameter (`_`)
whose type depends on a non-inferred parameter is an error:
`inferred parameter of type 'Pair[c, c]' cannot depend on non-inferred
parameter 'c'`; an element-type parameter that is not inferred is
`element type parameter 'NeedsPair[a, b, p]' must be an 'inferred' parameter`.
**Files:** the struct-signature elaboration in `fire_compiler.py` /
`mojo/backend_gimple/module_gen.py`.
**Test:** `struct RepeatedDep[c: Int, X: Pair[c, c]]` fails; a satisfied
dependency compiles.
**Acceptance:** the modular file's error lines are reproduced.

## 4. Binding deferral reporting

**Scope:** `failed_binding_deferrals.mojo`. A failed struct binding reports
only the error that failed it (`violated constraint` /
`invalid bindings in signature: lacking evidence`), not the constraints it
deferred.
**Files:** the generic-binding path in `mojo/backend_gimple/emit_resolve.py`.
**Test:** `NeedsCopyablePos[CondCopyable[U], 0]` fails with `violated
constraint`; `[..., 1]` compiles.
**Acceptance:** the modular file's two error lines are reproduced.

## 5. Elaboration recursion detection

**Scope:** `elaboration_error_recursion1.mojo`. A self-recursive generic
instantiation must be refused with `self recursive call will cause an infinite
loop` / `elaborator expansion is N levels deep - infinite recursion?`, not
compiled or hung.
**Files:** the instantiation loop in `mojo/backend_gimple/module_gen.py` /
`monomorphize.py`; add a depth counter and a warning at the recursive call.
**Test:** `self_recursion[i + 1]()` inside `self_recursion` fails with the
recursive-loop diagnostic.
**Acceptance:** the modular file's CHECK lines are reproduced; no hang.

## 6. `@align` decorator validation

**Scope:** `align_decorator_parametric_error.mojo`. `@align(expr)` on a
struct requires a positive power of 2; `function instantiation failed` /
`struct alignment must be a positive power of 2, got N`.
**Files:** `fire_compiler.py` (decorator parsing), `mojo/backend_gimple/`
(struct emission).
**Test:** `@align(calculate_illegal_alignment(alignment))` with a non-power-of-2
value fails.
**Acceptance:** the modular file's CHECK line is reproduced.

## 7. MLIR type/attribute annotations

**Scope:** `identifier_source_range.mojo`. `__mlir_type.index` /
`__mlir_attr.` annotations must parse and a bad call must report
`error: invalid call to 'foo'` at the right location.
**Files:** `fire_compiler.py` (annotation parsing), the call checker.
**Test:** `def foo(x: __mlir_type.index)` called with a non-index value fails.
**Acceptance:** the modular file's CHECK line is reproduced.

## 8. LSP error recovery

**Scope:** `error_tolerance.mojo`. The parser must recover from an unknown
declaration and keep parsing (`error: use of unknown declaration`
followed by `lit.struct.decl @Good`).
**Files:** the parser's error-recovery path; the LSP front end (if present).
**Test:** a file with an unknown declaration followed by a valid struct.
**Acceptance:** the modular file's CHECK lines are reproduced.

## 9. Docstring code-block self-import

**Scope:** `docstring_self_import.mojo`. A docstring code block that imports
its own module must be rejected: `module 'X' cannot import itself`.
**Files:** docstring code-block extraction (new) + the import checker.
**Test:** a docstring containing `` ```mojo import X ``` `` in module X.
**Acceptance:** the modular file's CHECK line is reproduced.

## 10. mojoc / precompiled import errors

**Scope:** `import_mojoc_conformance_error.mojo`,
`import_mojoc_implicit_default_param.mojo`, `import_dual_mount_mojoc.mojo`.
Importing a precompiled module whose stored signature violates a constraint
must report the conformance error.
**Files:** `.mojoc` loading (if present) + the conformance checker from
step 2.
**Test:** each modular file's `error:` line.
**Acceptance:** the three modular files fail with the expected diagnostics.

## 11. Category B (diagnostic formatting) — compare, do not chase

`comptime_assert.mojo`, `where_message.mojo`, `never_conforming_no_synthesis.mojo`,
`not_conformance.mojo`, `variadic_kwargs.mojo` assert on modular's MLIR output,
which this compiler does not produce. Only file a bug where our diagnostic is
WORSE than modular's for the same source; do not attempt a canonicalization
map.
