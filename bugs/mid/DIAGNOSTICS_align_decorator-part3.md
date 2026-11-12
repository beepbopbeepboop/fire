# DIAGNOSTICS step 6, part 3: evaluate a comptime function call in `@align`

Part of the split of `bugs/hard/DIAGNOSTICS_align_decorator.md`; the original
doc is part of the umbrella
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md` and the plan is
`docs/diagnostics-missing-validation-plan.md` §6.

**Prerequisites:** part 1
(`bugs/DIAGNOSTICS_align_decorator-part1.md`, the shared `@align` value rule)
and part 2 (`bugs/mid/DIAGNOSTICS_align_decorator-part2.md`, evaluation against
a generic struct's bracket parameters at elaboration time). This part adds the
one missing expression shape and the original integration acceptance test; it
must reuse parts 1/2's validator rather than add a third one.

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
power of 2. The current tree compiles the equivalent source (verified with the
exact shape above, minus `TrivialRegisterPassable`/stdlib imports, through
`gimple_codegen.compile_to_gimple(..., do_imports=True, filename=<real file>)`):
there is no `@align` consumer, so the call is never evaluated and no
diagnostic is produced.

Part 2's evaluator sees `calculate_illegal_alignment(23)` as a `CallExpr` and
declines it. This part supplies a `call_hook` so the same
`mojo.middle.comptime.eval_const_int(expr, bindings, call_hook=...)` folds it,
exactly as the ordinary comptime path already folds an imported call.

## Scope

1. **Use the existing call-evaluation seam.** Do not write a new interpreter.
   `mojo.middle.comptime.eval_const_int` already takes
   `call_hook(name, argvals) -> int | None`. The gimple path's existing hook
   is `mojo/backend_gimple/emit_infra.py::_comptime_call_hook`, which looks
   the callee up in `gen._imported_fn_sources`, extracts it with
   `elaborate.extract_fn_source`, and runs it as cached machine code with
   `comptime.evaluate(fn_src, name, argvals)`.
2. **Provide the module-local lookup.** At `elaborate.Elaborator.
   elaborate_generic_struct`, the full module source is available even though
   the extracted struct template is not. Build the hook from `module_src`:
   `elaborate.extract_fn_source(module_src, name)` then
   `comptime.evaluate(fn_src, name, argvals)`, returning `None` on any
   failure. `@no_inline` is just a decorator on the callee and must not change
   the answer.
3. **Bound the evaluation.** Only a pure scalar call whose arguments are all
   compile-time ints may fold. A call the hook cannot resolve (missing
   function, non-scalar parameter, body with side effects that needs the
   runtime) returns `None`; an unanswerable expression must stay accepted,
   not become a false diagnostic. Do not recurse without a depth bound.
4. **Reuse part 1's value test** and part 2's elaboration error path. On an
   invalid result raise the same `RuntimeError` carrying
   `function instantiation failed` and
   `struct alignment must be a positive power of 2, got <N>`, and make sure
   `mojo/backend_gimple/emit_resolve.py::_ensure_generic_struct` /
   `_elaborate_generic_struct_call` re-raise it (parts 2/3 add the phrase to
   their allow-list, or a dedicated diagnostic exception is propagated).
5. **Layout is still out of scope.** A valid `@align` value continues to
   compile without applying the alignment to the emitted struct/alloca; the
   original bug doc asks for validation only.

## Acceptance

Add `test_align_decorator_diagnostic.py` (the filename the original doc names)
beside `test_comptime_dtype_diagnostic.py`. Use its `_compile_full` pattern:
write the source under `.tmp/` and call
`gimple_codegen.compile_to_gimple(src, do_imports=True, filename=<path>)`.

    python3 test_align_decorator_diagnostic.py

Required cases:

| source | expected |
|---|---|
| the modular shape above with `calculate_illegal_alignment(x) = x * 3` and `AlignedTrivialParam[23]` | `RuntimeError` containing `function instantiation failed` **and** `struct alignment must be a positive power of 2, got 69` |
| same shape, `calculate_alignment(x) = x * 2` and `[...][32]` | compiles (64) |
| same shape, `return x * 3` and `[22]` | diagnostic with `got 66` |
| function returns `0` / a negative value | diagnostic, not a silent compile |
| a call the hook cannot evaluate (e.g. a non-scalar argument) | compiles or reports the existing unknown-diagnostic; must not crash |

Use the exact modular call spelling `@align(calculate_illegal_alignment(alignment))`
with `alignment` as the struct's bracket parameter, so the test proves the
call is evaluated *after* the bracket substitution. Do not import
`TrivialRegisterPassable` or `std.testing`; they are orthogonal to this
validator and would make the test depend on stdlib availability.

## Status
- **Open.**
