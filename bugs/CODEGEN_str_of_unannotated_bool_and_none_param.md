# CODEGEN: `str()` of an unannotated parameter holding a bool or None prints an int

**Found by:** the `globcompiled` fix (work/fix-gate-globcompiled), while checking keyword-argument values.
Not in that job's path, and not fixed there.

## Repro

```python
def f(p, *, recursive=False):
    return str(recursive)

def g(v):
    return str(v)

print(f(1, recursive=True))
print(f(1))
print(g(True))
print(g(None))
```

- `python3 fire.py build drv.py -o drv && ./drv` prints `1`, `0`, `1`, `0`.
- CPython prints `True`, `False`, `True`, `None`.

## What is known

- Module-scope `str(True)` and `str(None)` are correct (`True`, `None`), so the loss is in the
  parameter, not in `str()` itself.
- An unannotated parameter is typed as the tagged `int64_t` word (`funcs_shared._param_ctype`). A bool or
  None that arrives as the word is then formatted as its integer value. The bool and None tags are lost
  at the parameter boundary.
- The keyword-argument mismatch the `globcompiled` fix found (`m.f('x', recursive=True)` binding the wrong
  slot) is fixed; what remains in that repro is this formatting gap.

## Next step

Find where a call argument's bool/None tag is dropped before it reaches a word-typed parameter (the
call-site boxing in `_box_param_call_args` / `infra_infer.param_boxed_names` is the place to look), and
make the parameter's `str()` read the tag. Quick test: the repro above, as a `test_*.py` case beside
`test_gimple_runner.py`'s bool cases, comparing stdout with CPython.
