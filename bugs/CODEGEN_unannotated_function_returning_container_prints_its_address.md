# CODEGEN: an unannotated function's return type is int64_t, so a dict/list it returns prints as its address

Found 2026-10-01 while fixing the `dict |` operand coercion in
`Lib/collections/__init__.py` — the collection this bug belongs to is
already-known-broken, which is why it is easy to mistake for a
regression in whatever you just changed.

## The repro

```python
a = {'x': 1}
b = {'y': 2}
print(a | b)
```

| | output |
|---|---|
| `python3` | `{'x': 1, 'y': 2}` |
| `python3 fire.py build` + run | `4312286912` |

**Exit 0, no diagnostic, a pointer's digits where a dict belongs.** The
same happens for any container-producing unannotated function — including
through a function boundary:

```python
def f(a, b):
    return a | b
print(f({'x': 1}, {'y': 2}))     # 4298800704
```

The union itself is computed correctly; only the *return type* is wrong.
In the generated C, `f`'s definition and the `sprintf` that formats its
result for `print`:

```c
  _t7 = f_2dbb98 (_t8, _t10);
  _t12 = (char *) _t13;
  sprintf (_t12, _t14, _t7);      /* %s against an int64_t */
```

`def f(a, b): return a | b` has no return annotation, so the return type
falls to the `int64_t` default — the value is a `MojoDict *`, and
`sprintf`'s `%s` reads its bits as a decimal.

## Confirmed pre-existing, not a regression

Verified by reverting the only change in flight (`_as_dict_operand` in
`mojo/backend_gimple/emit_exprs.py`, the `dict |` right-operand coercion)
and re-running: the repro prints a pointer **both with and without** it —
`4350312128` vs `4317345372`. Only the digits differ, because they are
the address. So a change to that area is not what causes this, and a
test that only asserts "not a pointer" would pass on the broken tree.

## Why the gate has not caught it

Every interpreter-suite test passes, because `fire.py run` evaluates this
correctly — it is the compiled path only. `test_runtime_diff.py` compares
the two *engines*, and this is a compiled-only gap, so a shared bug is
not the shape here but the interpreter being right masks it in any test
that checks only one side.

## Next step

Return-type inference for an unannotated `def` whose body is a single
`return <container-expr>`. `_infer_local_var_types` has the machinery for
the LOCAL case (`test_gimple.py`'s `field_value_through_local_keeps_char_star_return_type`
is the same shape one level in, and passes), and the seed-the-inference-
from-inferred-locals machinery already exists for method returns — the
2026-09-06 zipfile entry records that fix landing for exactly this class
(`ZipExtFile.read` returning `MojoBytes *`). A free function's return is
not evidently covered by either.

The honest first step is to find what decides a free function's return
ctype when nothing is annotated and check whether a `MojoDict *` /
`MojoList *` RHS can reach it — the same place `_param_ctype` decides a
parameter, which is why that one already answers `int64_t` correctly for
an unannotated `char *` default.

A regression belongs beside `test_gimple.py`'s
`field_value_through_local_keeps_char_star_return_type`, and must be
asserted against CPython's stdout on both pipelines — a "does not print a
number" check is not enough, as the paragraph above shows.