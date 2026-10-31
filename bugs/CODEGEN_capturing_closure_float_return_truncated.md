# CODEGEN: a capturing nested `def` returning `float` prints a truncated value

Found 2026-10-30 while fixing `CODEGEN_closure_str_return_is_lost`. Not part of
that fix: the return-type carry is correct here, the wrong value comes from
the closure's own `float` return ABI.

## Repro

```python
def use():
    n = 2
    def inner(x: int) -> float:
        return n + 0.5
    h = inner
    print(h(0))

use()
```

- CPython: `2.5`
- compiled (`single-TU`, `gcc -fgimple`, via `test_gimple`'s pipeline): `2.0`

It reproduces with no factory and no closure returned, so the
`_return_bound_method_ret_types` hop (which only fires for a `return`
of a closure, or a `g = f(...)` call whose callee returns one) is not
on this program's path. That is why it is treated as a separate defect.
I did not run it on the pre-change tree to confirm the baseline.

A NON-capturing closure with a `float` return is correct
(`f = lambda: 1.5` in `test_callable_return_type_survives_its_carrier`), and
an un-annotated capturing lambda (`h = lambda x: n + 0.5`) prints `2.5`.
So the defect is specific to a capturing nested `def` with an annotated
`-> float`.

## What is known

- A capturing closure is a `MojoBoundMethod *`; `mojo_bound_method_call_N`
  returns `int64_t`, and the callee's `double` result has to be narrowed by
  the call site through `_bound_method_ret_types`. The `2.0` is consistent
  with the double being truncated to an integer on the way through the
  int64 box (`2.5` -> `2`), then re-widened by `(double)`.
- Likely the trampoline (`mojo_bound_method_call_N` / the per-closure
  `_tramp`) narrows its return to `int64_t` before the call site sees a
  `double`. Not yet read in detail.

## Next bounded action

Read the trampoline emitted for a capturing `def` with a `double` return
(`_funcptr_<lifted>` / `mojo_bound_method_new` in `emit_calls.py` around the
closing-lambda arm, and `runtime/fire_runtime.h`'s `mojo_bound_method_call_N`).
Add the repro above to `test_callable_return_type_survives_its_carrier`
(single-TU and link-mode), confirm it fails as `2.0`, then carry the `double`
bits through the box the way `_Bool` and `char *` already are.

Regression: none yet beyond the repro above.
