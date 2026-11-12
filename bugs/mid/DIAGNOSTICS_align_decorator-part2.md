# DIAGNOSTICS step 6, part 2: validate parametric `@align` expressions at struct instantiation

Part of the split of `bugs/hard/DIAGNOSTICS_align_decorator.md`; the original
doc is part of the umbrella
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md` and the plan is
`docs/diagnostics-missing-validation-plan.md` §6.

**Prerequisite:** part 1
(`bugs/DIAGNOSTICS_align_decorator-part1.md`) adds the parser helper that
recognises `@align` and validates a constant value. This part extends that
same rule to a generic struct's bracket parameters; it must not add a second
validation implementation.

## Why this part

The modular integration test is parametric:

```mojo
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

The function call is part 3. This part makes the *parameter and arithmetic*
subset work and proves the instantiation-time diagnostic end to end:

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
compile. The current tree compiles all of these (verified by compiling the
`@align(alignment)`/`Aligned[3]` source through
`gimple_codegen.compile_to_gimple(..., do_imports=True, filename=<real file>)`),
so the observable change is the error.

The value seen at instantiation is the value after monomorphisation:
`monomorphize.monomorphize_source` substitutes the bracket parameters in the
decorator text, so `@align(alignment)` becomes `@align(3)` and
`@align(alignment * 2)` becomes `@align(3 * 2)`. Part 1's parser rule alone is
not sufficient because the error is currently swallowed on the elaboration
path (next section), and because expressions are not folded there.

## Scope

1. **Evaluate the decorator at elaboration time.**
   `elaborate.Elaborator.elaborate_generic_struct(module_src, struct_name,
   type_args)` already has the template source and the bound arguments. After
   `bind_type_args`, and before the monomorphised text is treated as the
   answer), parse the struct template (`extract_struct_source` returns the
   `struct` text), find its `@align` `CallExpr`, and evaluate the argument with
   the shared constant folder `mojo.middle.comptime.eval_const_int(expr,
   bindings)`. `bind_type_args` returns the concrete arguments as *strings*
   (`{'alignment': '3'}`), so build an evaluator binding table that maps each
   parameter whose argument is an integer literal to that `int`; leave
   non-integer arguments out. A module-level `alias NAME = <int>` /
   `comptime NAME = <int>` referenced from the decorator must be added to the
   bindings (parse the top-level statements of `module_src`); an unknown name
   remains unknown and must not become a false diagnostic.
2. **Validate with part 1's rule.** Positive, power of 2, at most `2^29`.
   On failure raise a `RuntimeError` whose text contains both:
   `function instantiation failed` and
   `struct alignment must be a positive power of 2, got <N>`.
3. **Do not swallow it.** `mojo/backend_gimple/emit_resolve.py`'s
   `_ensure_generic_struct` and `_elaborate_generic_struct_call` catch
   `Exception` from elaboration and only re-raise a `RuntimeError` whose
   message contains `constraint failed` or `comptime assertion failed`;
   everything else is recorded in `_generic_struct_elaboration_failures` and
   the codegen falls back to the raw template. Add the `@align` diagnostic to
   that re-raise set (or introduce a dedicated diagnostic exception that both
   sites propagate) so the error reaches the user at the instantiation site.
   Do the same check in `mojo/backend_gimple/elab_intu.py::_materialize`,
   whose `Parser(...).parse_module()` failure is currently converted to a
   `work.refuse(...)`: if the shared validator runs there, re-raise this
   diagnostic instead of refusing.
4. **Do not change layout semantics.** Applying a valid `@align(N)` to the
   emitted C struct/alloca is out of scope; this part only rejects an invalid
   value. A valid decorator must continue to compile exactly as it does now.

Use one shared implementation for the value test in `fire_compiler.py` (part 1)
and call it from both elaboration paths; do not copy the power-of-2 test into
`elaborate.py` and `emit_resolve.py`.

## Acceptance

Add `test_align_decorator_parametric_diagnostic.py` beside
`test_comptime_dtype_diagnostic.py`. Follow that file's `_compile_full` helper:
write the source to a real file under `.tmp/` and call
`gimple_codegen.compile_to_gimple(src, do_imports=True, filename=<that path>)`.
Do not add a suite registration in this part.

    python3 test_align_decorator_parametric_diagnostic.py

Cases:

| source | expected |
|---|---|
| `@align(alignment)`, `Aligned[3]` | `RuntimeError` containing `function instantiation failed` and `struct alignment must be a positive power of 2, got 3` |
| `@align(alignment)`, `Aligned[64]` | compiles |
| `@align(alignment * 2)`, `Aligned2[3]` | diagnostic with `got 6` |
| `@align(alignment * 2)`, `Aligned2[32]` | compiles (64) |
| `@align(alignment + 1)`, `Aligned3[3]` | compiles (4) |
| `@align(alignment)`, `Aligned[1]`, `Aligned[2]`, `Aligned[4096]` | compile |
| module-level `alias A = 64` + `@align(A)` | compiles |
| module-level `alias A = 3` + `@align(A)` | diagnostic with `got 3` |
| `@align(missing)` | does not silently compile; the user-visible error names `missing` |

The last case may use the parser's existing unknown-declaration message from
`align_decorator_errors.mojo` (`use of unknown declaration 'missing'`) if the
evaluator can distinguish it from an unbound-but-known bracket parameter.

## Status
- **Open.**
