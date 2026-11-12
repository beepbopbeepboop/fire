# DIAGNOSTICS @align decorator — part 2: validate alignment and emit diagnostic

Split from `bugs/hard/DIAGNOSTICS_align_decorator.md` (umbrella step 6 of
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md`; plan:
`docs/diagnostics-missing-validation-plan.md` §6). This part covers step 6,
part 2 of the detailed plan: validate parametric `@align` expressions at
struct instantiation.

## Class
mid

## Prerequisite / depends on
The shared `@align` value rule (positive, power of 2, at most 2^29) is
implemented: `fire_compiler.py::_validate_align_decorators` (called from
`_parse_struct`) validates a struct's constant `@align(...)` argument at parse
time, with regression test `test_align_decorator_literal_diagnostic.py`.
`bugs/mid/DIAGNOSTICS_align_decorator-part1.md` (the align expression stored on
the AST) is the remaining dependency: this part's parametric cases read the
expression back at elaboration. This part extends the same rule to a generic
struct's bracket parameters; it must not add a second validation
implementation.

## Goal
Enforce that a struct's `@align(expr)` resolves to a positive power of 2. A
non-power-of-2 (or otherwise invalid) value must fail compilation with the
expected diagnostic, including parametric and arithmetic cases.

## Why this part
The modular integration test is parametric, e.g. a struct parameterized by
`alignment` with `@align(calculate_illegal_alignment(alignment))` or simpler
`@align(alignment)`. The function-call form is part 3; this part makes the
*parameter and arithmetic* subset work and proves the instantiation-time
diagnostic end to end:

```mojo
@align(alignment)
struct Aligned[alignment: Int]:
    var value: Int

fn main():
    var a = Aligned[3]()      # must fail: got 3
    print(a.value)
```

and

```mojo
@align(alignment * 2)
struct Aligned2[alignment: Int]:
    var value: Int

fn main():
    var a = Aligned2[3]()     # must fail: got 6
```

`Aligned[64]`, `Aligned2[32]` and `@align(alignment + 1)` at `[3]` must
compile. After monomorphisation the decorator argument is substituted
(e.g. `@align(alignment)` becomes `@align(3)`, `@align(alignment * 2)` becomes
`@align(3 * 2)`), so the value must be evaluated/validated at elaboration or
instantiation time rather than swallowed.

## Scope
- `elaborate.Elaborator.elaborate_generic_struct(...)` (and shared comptime
  evaluation): after binding type args and before treating the monomorphised
  text as final, parse the struct template, find its `@align` `CallExpr`, and
  evaluate the argument with the shared constant folder
  `mojo.middle.comptime.eval_const_int(expr, bindings)` (build bindings from
  integer-literal bracket args; include relevant module-level `alias`/`comptime`
  int bindings; leave unknowns unknown and do not emit a false diagnostic).
- Validate with part 1's rule/value test (positive, power of 2, at most `2^29`
  per the shared implementation): on failure raise a diagnostic `RuntimeError`
  whose text contains both `function instantiation failed` and
  `struct alignment must be a positive power of 2, got <N>`.
- Propagate the diagnostic instead of swallowing it: in
  `mojo/backend_gimple/emit_resolve.py` (`_ensure_generic_struct`,
  `_elaborate_generic_struct_call`) re-raise/propagate this `@align` diagnostic
  (not only `constraint failed` / `comptime assertion failed`) so it reaches
  the user at the instantiation site. Do the equivalent in
  `mojo/backend_gimple/elab_intu.py::_materialize` if the validator runs there
  (re-raise the diagnostic instead of refusing).
- Do not change layout semantics: applying a valid `@align(N)` to emitted C
  struct/alloca layout is out of scope; a valid decorator must continue to
  compile exactly as it does now.
- Use one shared implementation for the value test (introduced in part 1,
  e.g. in `fire_compiler.py`) and call it from elaboration paths; do not copy
  the power-of-2 test.

## Acceptance
- Compiling a struct with a concrete invalid alignment such as `@align(3)` (or
  an equivalent non-power-of-2) fails with a diagnostic stating the alignment
  must be a positive power of 2 and reporting the offending value; the error is
  surfaced at instantiation (`function instantiation failed` context).
- Compiling a struct with a valid power-of-two alignment such as `@align(8)`
  or `@align(64)` is accepted.
- Parametric/arithmetic instantiated cases where the computed alignment is
  non-power-of-2 fail with the required diagnostic (not silently accepted),
  e.g. `@align(alignment)` with `[3]` -> `got 3`,
  `@align(alignment * 2)` with `[3]` -> `got 6`.
- Valid parametric cases compile, e.g. `Aligned[64]`, `Aligned2[32]`,
  `@align(alignment + 1)` at `[3]` (4), powers of two `[1],[2],[4096]`, and a
  module-level `alias A = 64` used as `@align(A)`.
- Module-level `alias A = 3` with `@align(A)` produces the diagnostic with
  `got 3`. `@align(missing)` must not silently compile; it should report a
  user-visible unknown-declaration/name error consistent with the compiler.

## Notes
Part 3 adds `test_align_decorator_diagnostic.py` as the committed regression
covering the function-call/comptime-call case and the original integration
acceptance. A focused parametric-diagnostic test (e.g.
`test_align_decorator_parametric_diagnostic.py` alongside
`test_comptime_dtype_diagnostic.py`, using the `_compile_full` pattern: write
source under `.tmp/` and call `gimple_codegen.compile_to_gimple(...,
do_imports=True, filename=<that path>)`) is the expected narrow verification for
this part once implemented.

## Status
- **Open (replan/merge).**
- **2026-11-12 (merge with the part-1 fix):** the prerequisite's constant-value
  rule landed with the branch side of the merge (`_validate_align_decorators`
  in `fire_compiler.py`; its part-1 doc was removed with the fix, per the
  "a fully fixed bug's doc is deleted" convention). Remaining for this part:
  parametric/arithmetic evaluation at instantiation (the `elaborate_generic_struct`
  scope above) with the `function instantiation failed` / `struct alignment
  must be a positive power of 2, got <N>` diagnostic.
