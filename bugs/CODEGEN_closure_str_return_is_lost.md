# CODEGEN: a closure that returns a `str` prints a decimal address

Found 2026-10-29 while testing decorator rebinding
(`COMPILE_FAIL_decorator_application_dropped.md`). A closure's return type
is not carried to its call site when the return is a `str`, so the value
comes back as an `int64_t` and is printed as a decimal number.

## Repro

```python
def outer(p):
    def inner(x):
        return p + x
    return inner

def main():
    g = outer("<")
    print(g(">"))
```

- CPython 3.14.7: `<>`
- compiled (`single-TU`, `gcc -fgimple`): `8751303784` (a pointer printed
  as an integer; the value changes per run)

The same happens for a MODULE-scope binding (`g = outer("<")` at top level,
`print(g(">"))` inside `main`): `8606666088`.

## Why it matters

Any decorator whose wrapper returns a `str` is affected, since the wrapper
is exactly this shape. `decorator_rebinding_is_applied_at_runtime` covers
integer returns only for that reason.

## What is known

- Integer closure returns are correct (`wrap` in `twice(f)` returning
  `f(x) * 2`, tested in `test_gimple.py`).
- The call goes through `mojo_fnptr_call_N`, the homogenized `int64_t`
  convention. `_callable_ret_types` is the table that should carry the
  `char *` return to the call site; it is keyed by the lowered VALUE and
  the closure's return is cast into a fresh temp, so the key does not
  survive. This is the same family as the carriers listed in
  `test_callable_return_type_survives_its_carrier`.

## Next bounded action

Add the `char *` case to `test_callable_return_type_survives_its_carrier`
(a FACTORY-returned closure whose return is `str`), confirm it prints
`<>` on the single-TU path, then trace which carrier drops the `char *` type
for a closure returned by a factory (`outer`'s return) and record it in
`_callable_ret_types` the way the `_Bool`/`double` cases are recorded.

Regression: none yet. A test asserting the current decimal output would
lock the bug in.
