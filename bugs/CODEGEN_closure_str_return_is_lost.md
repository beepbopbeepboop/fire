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

## Status (2026-10-30 — PARTIAL: the annotated shape is fixed; the untyped repro is not)

LANDED. The carrier that dropped the type was the bound-method table, not
`_callable_ret_types`. A capturing closure's value is a `MojoBoundMethod *`,
recorded in `_bound_method_ret_types` (emit_exprs.py, the capturing-name arm).
Three hops did not carry it:

- `return inner` in the factory: `emit_stmts.py`'s return site only forwarded
  `_callable_ret_types`. It now also records `_return_bound_method_ret_types`.
- `g = mk(...)`: `emit_infra.carry_callable_ret_from_call` now copies that
  entry into `_bound_method_ret_types[g]`, which `g(...)` reads.
- `mk(...)(...)`: `GimpleGen.lower_expr` stamps the callee's return type on
  the CallExpr through the new `_return_callable_ret_for`, and emit_calls'
  chained-call arm passes it to `_lower_bound_method_call_value`.

Measured (`.tmp` driver, `test_gimple`'s pipeline, both `single-TU` and
`link-mode`): `def mk(p: str)` returning `def inner(x: str) -> str` gives
`<>`, `[]`, and the `bool` factory gives `True`/`False`, matching CPython.
Regression: `test_callable_return_type_survives_its_carrier` now includes
`mk_str` (named and chained).

STILL OPEN: the doc's own repro is UNTYPED (`def outer(p)` / `def inner(x)`).
That still prints a decimal, for a different reason: an un-annotated `x` is
typed `int64_t`, so `inner`'s C signature is `int64_t inner(..., int64_t x)`
and `g(">")` passes a `str` into an `int64_t` slot. Fix is parameter inference
for un-annotated closure parameters from their call sites (or refusing
honestly). That is its own change; not started here.

Adjacent, not this bug: a capturing nested `def` with `-> float` truncates its
result on the call path. See `bugs/CODEGEN_capturing_closure_float_return_truncated.md`.
