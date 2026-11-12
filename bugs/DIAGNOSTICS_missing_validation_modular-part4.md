# DIAGNOSTICS missing-validation part 4: fold float comparisons in comptime conditions

Class: **easy** (this doc lives in `bugs/`). Two small edits: one literal case
in the shared constant folder, and the float branch of the `where`-clause
binding table.

Parent: `bugs/hard/DIAGNOSTICS_missing_validation_modular.md` (the
"incomplete condition evaluation" remainder). Plan:
`docs/diagnostics-missing-validation-plan.md`.

## Goal

A `comptime assert` / `constrained` / `where` condition built from float
literals or a `Float64` parameter must be decided at compile time. Today every
float comparison is unfolded, so a provably-false one is silently accepted.

## Current state (measured 2026-11-12)

- `comptime assert 0.5 > 1.0, "small"` compiles with no diagnostic.
- `comptime assert 1.5 != 1.5, "neq"` compiles with no diagnostic.
- `constrained[0.5 > 1.0, "small"]()` compiles with no diagnostic.
- The folder has no float case: `mojo/middle/comptime.py::eval_const` (~438)
  handles `BoolLiteral`, `IntLiteral`, `StringLiteral`, ... but not
  `FloatLiteral`; `_const_foldable` (~868) has the same gap in its literal
  tuple. The comparison helper `compare_op` (~71) is type-agnostic and already
  returns the right answer once a `float` reaches it.
- `elaborate._where_bindings` (~652) accepts only a decimal integer or
  `True`/`False` type argument, so `def f[x: Float64]() where x > 1.0` called
  as `f[0.5]()` leaves the clause undecided and accepted.
- Integer, Bool, and String comparisons already fold; `fold_arith` is
  int-annotated, so float ARITHMETIC is out of scope.

## Scope

1. `mojo/middle/comptime.py`: `eval_const` returns `node.value` for a
   `FloatLiteral`; `_const_foldable` lists `FloatLiteral` with the other
   literals. Leave the arithmetic guard (`isinstance(l, (int, bool))`) alone —
   only `compare_op` on floats is in scope, so `0.5 - 0.1 > 0.3` stays
   unfolded rather than silently using a different arithmetic model.
2. `elaborate._where_bindings`: accept a float type argument
   (`-?\d+\.\d+([eE][-+]?\d+)?`) as a `float`, so a `Float64` parameter can
   satisfy a float `where` clause. Keep the existing int/bool branches and the
   "anything else is omitted" rule.
3. No new message text: `comptime assertion failed: <msg>`,
   `constraint failed: <msg>`, and the existing `requirement '...' is not
   satisfied` are the diagnostics.

## Acceptance

- `comptime assert 0.5 > 1.0, "small"`,
  `comptime assert 1.5 != 1.5, "neq"`, and
  `constrained[0.5 > 1.0, "small"]()` are rejected with their message.
- True/equal float conditions compile: `0.5 < 1.0`, `1.5 == 1.5`.
- `def f[x: Float64]() where x > 1.0` rejects `f[0.5]()` and accepts
  `f[2.5]()` (via a real `fire.py build`; the in-process path does not
  instantiate the generic).
- A condition over a float that is only known at run time stays undecided and
  compiles.
- Integer/String/Bool conditions and `comptime if` keep their behaviour.

## Done when

Add `test_comptime_float_condition_diagnostic.py` beside
`test_comptime_dtype_diagnostic.py` (do NOT register it in `tools/suite.py`)
and run exactly:

    python3 tools/memslot.py --gb 8 --label comptime-float -- python3 test_comptime_float_condition_diagnostic.py

The test covers the `comptime assert`/`constrained` cases with
`compile_to_gimple` and the two `where` cases through
`diagnostic_build.build_refusal`.

## Not in this part

Float arithmetic at comptime, float folding in the interpreter, and DType
predicates. No test registration.

## Status

- **Open.**
