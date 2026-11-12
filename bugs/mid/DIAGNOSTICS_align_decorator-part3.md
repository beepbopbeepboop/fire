# DIAGNOSTICS @align decorator — part 3: regression test (comptime function call in `@align`)

Split from `bugs/hard/DIAGNOSTICS_align_decorator.md` (umbrella step 6 of
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md`; plan:
`docs/diagnostics-missing-validation-plan.md` §6). This part adds the missing
expression shape and the original integration acceptance test.

## Class
easy

## Prerequisites / depends on
`bugs/mid/DIAGNOSTICS_align_decorator-part1.md` and
`bugs/mid/DIAGNOSTICS_align_decorator-part2.md` (parsing/storage and
power-of-two validation with diagnostics propagated at instantiation). This
part must reuse parts 1/2's validator rather than add a third one.

## Goal
Add support for evaluating a comptime function call in `@align(...)` (so the
original modular shape is diagnosed) and add the committed regression test for
`@align` decorator validation.

## Why this part
The modular integration test uses a function call in the decorator:

```mojo
@no_inline
def calculate_illegal_alignment(x: Int) -> Int:
    return x * 3

@align(calculate_illegal_alignment(alignment))
@fieldwise_init
struct AlignedTrivialParam[alignment: Int](TrivialRegisterPassable):
    pass

@no_inline
def return_illegally_aligned_struct() -> AlignedTrivialParam[23]:
    return {}

def main():
    # CHECK: function instantiation failed
    # CHECK: struct alignment must be a positive power of 2, got 69
    print(return_illegally_aligned_struct().alignment)
```

`alignment = 23` -> `calculate_illegal_alignment(23)` -> `69`, which is not a
power of 2. Part 2's evaluator can see the call as a `CallExpr` but may not be
able to fold it without a call hook; this part supplies that capability.

## Scope
- Use the existing call-evaluation seam: `mojo.middle.comptime.eval_const_int`
  already takes `call_hook(name, argvals) -> int | None` (see the gimple path's
  existing hook in `mojo/backend_gimple/emit_infra.py::_comptime_call_hook`,
  which resolves/imports and runs via `comptime.evaluate`). Do not write a new
  interpreter.
- Provide module-local lookup for the hook at elaboration time (full module
  source available): e.g. `elaborate.extract_fn_source(module_src, name)` then
  `comptime.evaluate(fn_src, name, argvals)`, returning `None` on failure.
  `@no_inline` on the callee must not change the answer.
- Bound evaluation: only pure scalar calls whose arguments are compile-time ints
  may fold. A call that cannot be resolved/evaluated must not cause a false
  diagnostic or crash (return `None` / remain accepted per existing behavior);
  do not recurse without a depth bound.
- Reuse part 1's value test and part 2's elaboration/error-propagation path. On
  an invalid result raise the same `RuntimeError` carrying
  `function instantiation failed` and
  `struct alignment must be a positive power of 2, got <N>`, propagated to the
  instantiation site.
- Layout is out of scope: a valid `@align` value continues to compile without
  applying alignment to emitted struct/alloca layout (validation only).

## Acceptance / regression test
- Create `test_align_decorator_diagnostic.py` next to existing diagnostics
  tests (e.g. beside `test_comptime_dtype_diagnostic.py`) using the
  `_compile_full` pattern: write source under `.tmp/` and call
  `gimple_codegen.compile_to_gimple(src, do_imports=True, filename=<path>)`.
- `python3 test_align_decorator_diagnostic.py` is the narrow verification for
  this bug and passes once parts 1-3 are implemented.
- Cover (matching observable expectations where applicable to this compiler's
  diagnostic wording):
  - a valid power-of-two alignment accepted (e.g. `@align(4)` / `@align(8)`),
  - an invalid non-power-of-2 alignment rejected with the expected diagnostic
    (`struct alignment must be a positive power of 2, got N`, and/or
    `function instantiation failed` context as produced),
  - the original modular parametric/call case:
    `@align(calculate_illegal_alignment(alignment))` with `alignment` as the
    struct's bracket parameter, `calculate_illegal_alignment(x) = x * 3`,
    instantiated as `[23]` -> diagnostic containing `function instantiation
    failed` and `struct alignment must be a positive power of 2, got 69`.
  - same call shape, valid result (e.g. `x * 2`, `[32]` -> compiles / 64),
  - same call shape, another invalid result (e.g. `x * 3`, `[22]` -> `got 66`),
  - function returns `0` / negative value -> diagnostic, not silent compile,
  - a call the hook cannot evaluate (e.g. non-scalar argument) compiles or
    reports the existing unknown diagnostic; must not crash.
- Do not import `TrivialRegisterPassable` or `std.testing` in the test; they
  are orthogonal and would add stdlib dependencies. Do not require
  whole-closure builds, `--dump-full`, or the quality gate.

## Status
- **Open (replan/merge).**
