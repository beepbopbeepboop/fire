# CODEGEN: `v is None` on a tagged generator value is True for a False or 0 yield

## Status (2026-11-01, partial fix on work/bug-codegen-is-none-on-a-tagged-false-or)

**Landed:** `x is None` / `x is not None` on a name bound from `next(g)` on a
kind-mixed generator now reads the box's kind (`mojo_word_is_none`) in
`_lower_binary_tail` (`mojo/backend_gimple/emit_exprs.py`), the same read the
`==` / `!=` lowering already used. Pinned by `run_tagged_none_identity_tests`
in `test_gimple_generator_runner.py` (default and `coro.pinned('cpp')`, CPython
oracle). It FAILED before the change (`True` for the False and 0 rows) and
passes after. The full `test_gimple_generator_runner.py` file is green (390/0).

**Still open (the for-loop shape, the probe below):** `for v in g(): print(v is None)`
is still wrong for a False or 0 yield. The for-loop target is registered in
`_boxed_vals` only (`emit_loops.py` ~3934), not `_tagged_word_vals`, so the new
branch does not see it. Adding the target to `_tagged_word_vals` is the wrong
fix: that set also switches arithmetic on the name to `mojo_box_int`, which
truncates a float yield.

**Next step:** add a per-name marker, separate from `_tagged_word_vals`, meaning
"this boxed word's None is the kind-'n' box". Set it at the for-target site in
`emit_loops.py` when `mixed_slots` (~3934), and read it in the same `is` branch
of `_lower_binary_tail` alongside `_tagged_word_vals`. The new set needs the
same lifecycle as `_tagged_word_vals`: `emit_infra.py` FuncState save/restore
(~877-1184) and the `_fet` field table (~8300). Pin the for-loop probe in
`run_tagged_none_identity_tests` once it passes.

**Keep the list-None answer.** A list or tuple slot's None is a bare NULL word
with no box, and the kind read would call it "not None". Only tagged operands
take the kind read, so that answer does not change.

**Gate note for the integrator:** the change fires only for a
`_tagged_word_vals` operand compared to None with `is`. `==` / `!=` are
unchanged. The `_mojo_classattr_init` local is not tagged, so its C should not
move. That is reasoned, not measured with `cmp`. `stdlib-dylib` and
`stdlib-syntax` should be unaffected, but check the `skip` and `U` counts.

## Probe (the for-loop shape, still open)

```python
def g():
    yield False
    yield 0
    yield None
    yield "a"
def main():
    for v in g():
        print(v is None)
main()
```

- CPython: `False`, `False`, `True`, `False`
- compiled, default path and `MOJO_CORO=cpp`: `True`, `True`, `True`, `False`

A `False` yield and an int `0` yield both answer `is None` True.

## Mechanism (read from the code)

The `is` lowering compares the slot's WORD (`emit_exprs.py`, `is` / `is not`
arm, around the `mojo_box_word` unwrap). A tagged `False` or `0` is a box whose
`bits` are 0, and `mojo_box_word` returns those bits, so the comparison is
`0 == 0`. A None yield is the shared kind-`n` box, whose `bits` are also 0, so
the bit comparison cannot tell them apart. The kind is only on the box.

`mojo_word_is_none` (`runtime/fire_runtime.c`) reads the kind. It is used for
`==` / `!=` on a boxed operand, and now also for `is` / `is not` on a tagged
operand.
