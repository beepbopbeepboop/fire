# CODEGEN: `v is None` on a tagged generator value is True for a False or 0 yield

## Status (2026-11-01, found while fixing the `== None` half on branch work/bug-codegen-a-bare-or-explicit-yield-of)

**Symptom (measured, both paths, CPython oracle):**

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

**Mechanism (read from the code):** the `is` lowering compares the slot's WORD
(`emit_exprs.py`, `is` / `is not` arm, around the `mojo_box_word` unwrap). A
tagged `False` or `0` is a box whose `bits` are 0, and `mojo_box_word` returns
those bits, so the comparison is `0 == 0`. A None yield is the shared kind-`n`
box, whose `bits` are also 0, so the bit comparison cannot tell them apart. The
kind is only on the box.

**What already exists:** `mojo_word_is_none` (`runtime/fire_runtime.c`) reads the
kind, and the `==` / `!=` lowering uses it for a boxed operand (the
`_lower_binary_tail` branch that comment names). That path is correct for
False, 0, None, str and float (`test_gimple_generator_runner.py`,
`run_tagged_none_equality_tests`). `is` was deliberately NOT routed through it
in that change.

**Why `is` was not changed in the same round:** the `is None` lowering is the
one `_mojo_classattr_init` / `_class_field_decl` depends on. The comment at
`emit_stmts.py` (the bind site, ~1327) records a regression where a local that
kept its box made `v is None` false for a real None slot. Switching `is` to the
kind check changes that path for every boxed name, not only tagged generator
values, so it needs the behaviour-preserving standard before it lands.

**Next step:**

1. Route `is` / `is not` on a `_boxed_vals` operand through `mojo_word_is_none`
   (same branch as the `==` change), keeping the non-boxed arms unchanged.
2. Pin: the probe above, default and `coro.pinned('cpp')`, CPython oracle; must
   FAIL before (`True` for the False and 0 rows) and PASS after.
3. Gate note: byte-identical generated C for the classattr case
   (`_mojo_classattr_init`) before vs after, and `stdlib-dylib`'s `skip` count and
   `stdlib-syntax`'s `U` count compared before vs after. A list-element None is a
   NULL word with a kinds row, not a box, so the kind check answers "not None"
   for it; a list-None `is` must keep its current answer until that is handled
   separately.
