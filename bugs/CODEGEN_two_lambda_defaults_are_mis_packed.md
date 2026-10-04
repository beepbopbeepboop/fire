# A lambda with two defaulted parameters, or a default before its `*args`, is
# called with the wrong values

## Status

OPEN, and NEW — measured 2026-10-02 while closing
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`'s last own-scope item
(the variadic lambda inside a compiled generator body, now fixed). Both shapes
below **exit 0 with a plausible integer**, which is the reason
`mojo/middle/coro.py`'s `_lambda_shape_ok` refuses them rather than warning:
the disagreement is invisible without CPython alongside.

## What I ran, and what I saw

Every shape compiled, linked and run inside a compiled **generator** body
(`test_gimple_runner.py`'s `compile_mojo_to_gimple_exe`, CPython alongside):

| program (all inside `def gen(n): e = <lambda>; yield e(...)`) | CPython | compiled |
|---|---|---|
| `lambda x=n, *a: x + a[0]`, called `e(0, 5)` | `5` | **`8`** |
| `lambda x, y=n, z=10: x + y + z`, called `e(4)` | `17` | **`135`** |

and these, from the same sweep, are **correct** today and must stay correct,
because they are what makes the two refusals narrow rather than a blanket
return to the old guard:

| shape | CPython | compiled |
|---|---|---|
| `lambda *a: add(a[0], a[1])`, `e(4, 5)` | `9` | `9` |
| `lambda *a: addall(a)`, `e(1, 2, 3)` | `6` | `6` |
| `lambda *args, **kwargs: add(n, args[0])` capturing `n`, `e(7)` | `10` | `10` |
| `lambda f, *a: add(f, a[0])` … `lambda f, g, h, i, *a:` (1-4 leading params) | right | right |
| `lambda **k: add(k["a"], 1)`, `e(a=6)` | `7` | `7` |
| `lambda *a, k=n: add(a[0], k)`, `e(4)` | `7` | `7` |
| `lambda *, x=n: x + 1` | `4` | `4` |
| `lambda x=n: x + 1` / `lambda x, y=n: x + y` / `lambda x, *, k=n: x + k` | right | right |

One more boundary, already correct and already its own refusal:
`lambda f, g, h, i, j, *a:` (five ordinary leading parameters) is REFUSED by
`_lower_LambdaExpr` with "a lambda with 5 ordinary parameters before its
`*args` is not supported". That is deliberate and documented, not a defect.

Note that `lambda x=n, *a: x + a[0]` is **correct on the ordinary (non-
generator) path** — measured, `5` — and wrong only inside a generator body. So
the fault is in a generator-body-specific step, not in the shared lifting.

## What is believed

A lambda's defaults never reach its lifted C signature.
`mojo/backend_gimple/emit_calls.py`'s `_lower_LambdaExpr` builds the synthetic
`FunctionDef` with

```python
syn_params = []
for _pn, _pt in node.params:
    syn_params.append((_pn, None))
```

— a comment right above it says "Strip defaults so `_gen_lifted_closure` doesn't
try to resolve them as types". So the lifted function sees `x` and `a` as
ordinary positional parameters, and every defaulted argument must be
**substituted somewhere on the call side**. One substitution works; two do not.

That is exactly the shape of both failures:

* `lambda x=n, *a`, `e(0, 5)`: `8` is `n + n` — the caller's `0` for `x` was
  dropped and the default used instead, i.e. **the default overrode an
  explicitly-passed positional** in the presence of a variadic tail.
* `lambda x, y=n, z=10`, `e(4)`: `135` is `4 + 3 + ...` — with two defaults to
  place and one supplied argument, at least one slot kept the wrong source.

The obvious place to look is the call-site default padding, which the callable
paths already share: `calls_shared._default_expr_to_pair` (the ordinary
`param_defaults` padding) and the `MojoVarargFn` leading-parameter count in
`runtime/fire_runtime.h` ("Variadic callables" — it records "how many ordinary
leading parameters precede the `*args`"). A lambda's defaults are not in
`param_defaults` at all, because a lambda is not a `FunctionDef` the padding
machinery reads, so there is a second, lambda-specific substitution path
somewhere between `_lower_LambdaExpr` and `mojo_fnptr_call_N`.

## The exact next step

1. Find that second path: grep the call lowering for where a `LambdaExpr`'s
   `(pname, default)` pairs are read at a call — the materialization site and
   `mojo_fnptr_call_N`/`mojo_maybe_bound_call_N` are the two ends. Expect it to
   key on "how many leading params" or on "is there a variadic tail", because
   that is the discriminator both failures share and the correct cases do not.
2. Fix it there, not in `_lower_LambdaExpr`'s signature: putting the defaults
   back into `syn_params` would make `_gen_lifted_closure` try to resolve them
   as type annotations, which is the reason they were stripped.
3. Then delete the two refusal clauses in `mojo/middle/coro.py`'s
   `_lambda_shape_ok` **in the same commit**, and turn
   `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`'s
   `still deliberately excluded` note into the statement that it is all
   admitted. Leaving the refusals after a fix is the way a guard becomes a
   permanent, invisible lie.
4. Regression tests belong beside `test_gimple_generator_runner.py`'s existing
   lambda coverage, one per row of the two tables above.

## How it was found

Not by a suite. It was found by asking whether `mojo/middle/coro.py`'s
`_lambdas_ok` was still TRUE — a guard written to refuse a shape that was
miscompiled in August 2026, kept after the mechanism that miscompiled it
(`MojoVarargFn`) landed. Widening the guard to the measured frontier is what
exposed these two, and both are silent, so nothing else would have.