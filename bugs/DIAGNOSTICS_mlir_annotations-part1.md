# DIAGNOSTICS step 7: MLIR type/attribute annotations

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`; plan: `docs/diagnostics-missing-validation-plan.md` §7.

## Symptom
`__mlir_type.index` / `__mlir_attr.` annotations must parse and a bad call must report `error: invalid call to 'foo'` at the right location.

## Modular tests
identifier_source_range.mojo

## Files
fire_compiler.py annotation parsing, the call checker.

## Test
`def foo(x: __mlir_type.index)` called with a non-index value fails with `invalid call to 'foo'`.

## Acceptance
Add `test_mlir_annotation_diagnostic.py`.
## Status (2026-11-12): partial

**Landed:** a call that passes a LITERAL to a `__mlir_type.*` parameter is
refused at the argument, as the real compiler does (`_check_mlir_type_argument_calls`
in `fire_compiler.py`, run from `Parser.parse_module`). Measured with
`tools/mojo build`: `foo(1.5)`, `foo(3)`, `foo("s")`, `foo(True)` are each
refused. Our message is `invalid call to 'foo': value passed to 'x' cannot be
converted to '__mlir_type.index'`; the real one adds `from '<Kind>[<value>]'`,
which is not reproduced. Keyword arguments naming the parameter are covered.
Regression test: `test_mlir_annotation_diagnostic.py`.

**Not done:** a VARIABLE argument of the wrong type, e.g. `var y = 2.5; foo(y)`,
is still accepted. Checking it needs the argument's static type, which this
front end does not track. The next step is a small per-function static-type
table for locals (declared type, or the type of a literal initialiser) and
feeding it to the same check. Until then this doc stays open.

## Done when

`foo(y)` with `var y = 2.5` and `def foo(x: __mlir_type.index)` fails with
`invalid call to 'foo'` at `y`, in `test_mlir_annotation_diagnostic.py`
(the `test_variable_argument_is_not_checked` case flips to a refusal then).
