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

## Status 2026-11-22 (second round): the largest WRONG group is a field slot, and two pipelines disagree

Grouping the 112 WRONG programs by their first differing line (`pydiff --out`): the largest group is
`None` printed as `0` (about 19 programs, e.g. `classes/03_none_field_later_set`, `flow/13_return_tuple_unpack`).
The 2026-11-21 reading "compiled True" is gone; these are all `None` -> `0`.

**Reduction.** The minimal shape that reproduces through the gimple runner (`compile_mojo_to_gimple_exe`,
the path `pydiff` and the test suite use):

```python
class C:
    def __init__(self):
        self.s = None
    def open(self, x):
        self.s = x          # the field is now an int slot
    def take(self):
        r = self.s
        self.s = None       # a None store into that int slot
        return r
c = C()
c.open(42)
print(c.take())             # CPython: 42
print(c.take())             # CPython: None, runner: 0
```

**Two pipelines disagree.** `python3 fire.py run <file>` prints `None` for the same program, while the
runner prints `0`. So the runner path is the one that is wrong, and `fire.py run` is right for this shape
(the difference is consistent with the link-mode vs inline split in CLAUDE.md's verification notes). The
corpus program `classes/03_none_field_later_set.py` passes under `fire.py run` and is WRONG under `pydiff`.

**Mechanism (measured in code, not yet changed).**
- `emit_infra.py` (`box_mixed_store`, around line 4884) boxes a literal `None` with `mojo_box_none()`,
  but only for a slot that the inference has classified as MIXED (box-holding).
- The field `self.s` is inferred `int64_t` from `self.s = x` (an unannotated parameter receiving an int)
  and is not widened to mixed by the later `self.s = None` store. The `'none'` kind
  (`infra_infer.py` `_param_value_binding_kind`, line ~1862) is accepted for parameters but does not
  widen a struct field slot.
- So the store writes the NULL word, and the word read back prints `0`.

**Next step (one measured change):** find where a struct field's type is joined across its stores
(the field-type inference that fills `struct_field_types` for `self.<name> = <value>` assignments), and
make a `'none'` store join a word-typed field into the mixed (box-holding) kind, the same way a parameter
rebinding to `None` is already accepted. Acceptance: the reduction above prints `42` and `None` under the
runner, `pydiff` on `classes/03_none_field_later_set.py` is OK, and the oracle stays byte-identical
everywhere else (the change alters C only for classes that store `None` into a word field, so it should
change the C of only those programs; confirm the changed set by hash).

