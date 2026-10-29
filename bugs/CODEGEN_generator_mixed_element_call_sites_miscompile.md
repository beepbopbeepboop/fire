# CODEGEN: one generator called with a str list and an int list yields the str as an address

**State: OPEN, reproduced 2026-10-29 in a SINGLE module (so it predates the
module-boundary work). Silent: exit 0, wrong output.**

```python
def gen(xs):
    for x in xs:
        yield x

def main():
    for v in gen(["p", "q"]):
        print(v)
    for w in gen([1, 2]):
        print(w)
main()
```

| | CPython | compiled |
|---|---|---|
| output | `p` `q` `1` `2` | `4336152440` `4336152448` `1` `2` |

Measured with `build_and_run` from `test_module_boundary_regression.py`
(`compile_to_gimple(..., do_imports=True)` + `gcc -fgimple` + run).

## What is known

- The call-site scanner (`mojo/middle/coro.py`, `_scan_callsite_param_kinds`)
  does record the two observations for `xs`: `('list', 'p')` and `('list', 'i')`.
  Two different kinds for one slot is the "conflict" case, and a conflict is
  meant to refuse a generator whose yield reads that parameter.
- The refusal does not fire for this shape: the yield reads the LOOP TARGET
  `x` of `for x in xs`, not the parameter itself, so `_ambiguous_yielded_params`
  does not see it and the yield slot takes the `int64_t` default.
- The same shape with two `str` call sites, or two `int` call sites, is right.

## Next step

1. Make the conflict on a list parameter's element kind reach the generator's
   yield slot when the yield reads a for-loop target over that parameter. That
   is the same loop-target-vs-value-slot gap as
   `bugs/CODEGEN_generator_param_loop_target_kinds_still_unresolved.md`: read
   that doc's section on `_mojo_coro_param_elem_kinds` before changing anything.
2. Until then the honest result is a refusal, not a value. A test should assert
   the output is either CPython's or a compile refusal.
3. Cross-module: the same two calls spelled `m.gen([...])` in an importer give
   the same wrong output (measured 2026-10-29, after the closure call-site work
   in `coro.lower`). The fix belongs in the shared scanner, not the import path.
