# HARD BUG: a lambda in a nested `def` that captures a local of the ENCLOSING function's enclosing scope reads 0

**State: OPEN.** Silent miscompile: exit 0, a plausible integer, the wrong value.

## Reproduction

Found 2026-10-29 while probing the shapes in
`CODEGEN_generator_lambda_expr_unsupported.md`. Compiled through
`test_gimple_runner.py`'s `test_gimple_stdout` (`fire.py run` agrees with
CPython on the same text):

```python
def outer(x):
    n = 2
    def inner(y):
        g = lambda z: z + n
        return g(y)
    return inner(x)

def main():
    print(outer(4))

main()
```

- CPython: `6`
- compiled: `4` (`n` is read as `0`)

The same shape inside a generator body (`def gen(): n = 2; def inner(x): ...`)
gives `4` too, so it is not generator-specific.

## What is and is not the trigger (measured 2026-10-29)

| shape | compiled | CPython |
|---|---|---|
| lambda captures `n`, defined and called in the SAME function (`def outer(x): n=2; g = lambda y: y+n; return g(x)`) | `6` | `6` |
| nested `def` whose body is `return y + n` (no lambda), `n` from `outer` | `6` | `6` |
| nested `def` whose body defines and calls a capturing lambda that captures ITS OWN local (`inner` has `n = 2`) | `6` | `6` |
| nested `def` defines a capturing lambda over `outer`'s `n` and calls it (**the failing shape**) | `4` | `6` |

So the defect needs all three: a lambda, a capture of a local that lives TWO
function scopes out, and the lambda sitting inside a nested `def`. The
capture reads a zero-initialised slot rather than failing to capture at all.

## Where to look

- `mojo/backend_gimple/emit_calls.py` `_lower_LambdaExpr` builds the lifted
  function's env from the free names it finds. The env field for `n` is
  filled at the lambda's creation site, and that site is inside `inner`, so
  the value has to be read from `inner`'s own env, which in turn had to be
  filled from `outer`'s local. The chain is one hop longer than any of the
  shapes above that work.
- `mojo/middle/lambdareduce.py` may be inlining the lambda at its call site
  (`g(y)`), where `n` is not in scope the way the inline path expects. Check
  first whether `g(y)` is inlined; `CODEGEN_nested_def_capturing_lambda_env_field_types_disagree`
  (deleted in `d05901b91`) was the one-hop version of this shape and was fixed
  by `_env_field_value`.

## Next step

1. Dump the generated C for the failing program
   (`gimple_codegen.compile_to_gimple(src)`) and find where `n`'s value is
   read inside `inner`'s lifted lambda. If the read is `_env->n` and the env
   store in `inner` is missing or stores before `n` is assigned, the fix is in
   how `inner`'s body builds the env for a capture of a name it does not own.
2. Add a `test_gimple_runner.py` case matching the failing shape exactly
   (`test_gimple_matches_cpython`), and confirm it fails before the fix.
3. Re-run the four shapes in the table above; all four must still match CPython.
