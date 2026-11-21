# GIR stage 5c: `None` is not the integer 0 (the representation decision)

Plan source: `doc/GIR.md`, Stage 5c. Measured 2026-11-21:

    def pick(x): print(x is None)
    pick(0)      # CPython False, compiled True   (WRONG)
    pick(None)   # CPython True,  compiled True
    def pick(x=None): print(x)
    pick()       # CPython None,  compiled 0      (WRONG)

## Why the representation is the blocker

`None` and `0` share the null word. The call site unboxes `None` on purpose
(`emit_infra.py`, `mojo_unbox_plain`): the compiler's own code tests `ptype is None` and
`x or default` by the zero word, and handing a box through once crashed the self-hosted compiler
in `strdup`. So changing the representation touches the self-hosted compiler's own paths.

## Next step (the plan's recommendation)

1. Pass the shared None box (`mojo_box_none()`) for a literal `None` argument to an
   UNANNOTATED parameter, and for a parameter default of `None`.
2. Mark such parameters DynWord (`gen._word_mark_dyn`) in the callee, and make `is None` on them use
   `mojo_word_is_none`.
3. Leave annotated `int` parameters unchanged.

## Acceptance

- The three repros above match CPython under `tools/pydiff.py`.
- `test_gimple_runner.py::test_none_argument_is_none_in_the_callee` still passes.
- The owner runs `make bootstrap` (the self-hosted compiler must still compile itself).
