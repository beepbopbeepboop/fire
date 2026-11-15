# GPU offload validation modular - part 6: the compiled path must refuse an under-supplied specialization instead of answering `0`

Parent: `bugs/hard/GPU_offload_validation_modular.md`. This part is the
compiled-path half of the `compile_offload_unbound_param_error.mojo` row; the
interpreted half is part 5, fixed 2026-11-15 (the interpreter now refuses the
under-supplied bracket with `failed to infer parameter 'y' of 'param_fn'`; its
doc was deleted with the fix).

## Goal

`python3 fire.py build` of a program that applies a generic function with fewer
specialization arguments than it declares must fail the build with the
missing-parameter diagnostic, instead of producing a binary that prints `0` and
exits 0.

## Current state (measured 2026-11-15, HEAD `fa105c747`)

Same probe as part 5:

    def param_fn[x: Int, y: Int](a: Int) -> Int:
        return a + x + y


    def main():
        print(param_fn[2](1))

`python3 tools/memslot.py --gb 8 --label probe-arity-compiled -- python3 fire.py .tmp/probe/arity.mojo`
prints `0` and exits 0 (measured peak 0.3 GB; one link-mode build, a few
minutes cold because it compiles the stdlib closure). There is no diagnostic
and no refusal: a silent wrong answer, which is the worst of the three possible
answers.

The same probe with BOTH parameters supplied (`param_fn[2, 3](1)`) prints `6`
at exit 0 on the same path, so this is the under-supplied instantiation and
NOT the nested-bracket-call stub bug:
`bugs/CODEGEN_nested_bracket_generic_call_stubs_to_zero.md` is a different
shape (a bracketed call inside an elaborated instantiation) and stays a
separate doc.

Where to start: `mojo/backend_gimple/emit_calls.py:3040`'s "stub below is 0"
path is what the under-supplied call falls through to in link mode; the
instantiation that should have claimed it is the link-mode/monomorphizing
pass. Emit the C for the probe (`fire.py --dump` refuses bracketed calls
outright in the single-TU path, with "needs the generic instantiated ... link
mode (fire build) does", so use the build) and find the call site that should
have been specialised.

## Work

1. Find the link-mode instantiation site that matches a bracketed call to its
   declaration and refuse when the bracket supplies fewer items than the
   declaration's non-defaulted comptime parameters — the rule part 5 added to
   `MojoFunction.__getitem__`.
2. Reuse part 5's message (`failed to infer parameter 'y' of 'param_fn'`) so
   the two engines name one mistake one way; `test_interp_oracle.py`'s premise
   is that they agree.
3. Do not widen the single-TU refusal that already exists
   (`emit_calls.py:3010`): that one fires for every owned bracketed call and is
   correct for that path.
4. Add `test_regress_gpu_offload_validation_modular_part6.py` next to the other
   `test_*gpu_offload*` files.

## Acceptance

- `python3 fire.py build -o <bin> <probe>` exits non-zero with
  `failed to infer parameter 'y'` and names `param_fn`; no binary is produced
  that prints `0`.
- The fully-supplied probe still builds and its binary prints `6`.
- The interpreter path's wording is identical (part 5), so a reader comparing
  the two runs sees one message.

## Done when

`python3 test_regress_gpu_offload_validation_modular_part6.py` exits 0. It builds the
10-line probe once through `tools/memslot.py --gb 8` + `python3 fire.py build`,
asserts the refusal and its wording, and then builds and runs the
fully-supplied control. Cost: two link-mode builds of a tiny program, measured
0.1-0.3 GB peak and 27-136 s for both (the stdlib closure dominates when the
compiler cache misses).

## Out of scope

- The interpreter path: part 5.
- The nested-bracket-call stub (`bugs/CODEGEN_nested_bracket_generic_call_stubs_to_zero.md`).
- Inferring a comptime parameter from runtime argument types.
- `compile_info` / offload target modelling: part 7.
