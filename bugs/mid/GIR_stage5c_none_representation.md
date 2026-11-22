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

## Status 2026-11-22: measured; the three repros now pass, the pool does not

Re-measured on master (`9767d4c26`):

- The three repros above match CPython: `pick(0)` prints `False`, `pick(None)` prints `True`, `pick()`
  prints `None`. `tools/pydiff.py` reports the two repro files OK, and
  `test_gimple_runner.py::test_none_argument_is_none_in_the_callee` passes. The 2026-11-21 "WRONG" readings
  are stale.
- The full corpus (`python3 tools/pydiff.py tools/pydiff_corpus -j 6`): 285 programs, OK 135, WRONG 112,
  CRASH 29, GCC 3, REFUSED 3, ERROR 2, TIMEOUT 1. Of the 112 WRONG, 65 contain the substring `None` (a
  crude count; it is not the 32-program pool the workers doc named, and the pool list is not in the tree).
- Not verified here: the mechanism the Next step describes (a literal `None` passed to an unannotated
  parameter as `mojo_box_none()`, and the `mojo_word_is_none` read). The repros pass, so something
  already handles them, but the doc has not confirmed which code path does. Owner's `make bootstrap`
  is still the acceptance check for the self-hosted compiler.

So the three repros are fixed, but the bug is not: the None-related WRONG programs remain, and the
representation question (`doc/GIR_WORKERS.md` §6) is still the owner's to answer. The doc stays open.

**Next step (measurement first):** rebuild the 65 `None`-mentioning WRONG programs' list from a fresh
`pydiff` run (`--out DIR` writes each WRONG program's two outputs), group by the first differing line,
and pick the largest group whose cause is the unannotated-parameter path. That group is the slice.
