# FORMAL: a return-less call's value prints `0` where CPython prints `None` (master is red)

Found while disposing of recover row 63 (`recover-fadd1e3c1`, 2026-11-09). Master's own regression test fails.

## What I ran

On a `git archive master` export (a copy of master's tree, so this is master's state, not this branch's):

```
python3 test_formal_regression_returnless.py -v
  -> AssertionError: expected None, got: 0
```

Probe programs, built with `python3 fire.py build --formal --no-prove --backend=<arch> -o <out> <src>`, both backends build with rc 0:

```
def g(a, b):
    w = 1

def f(a, b):
    return g(a, b)        # (also: v = g(a, b); return v)

def main():
    print(f(1, 2))
    return 0
```

Both `arm64` and `x86_64` binaries print `0` and exit 0. `python3` on the same text prints `None`.

## What I expected

`None`, matching CPython and the master regression test.

## What master has, and how it got here

- `961b24313` (2026-11-02) refused a no-return call's value at every consuming position (print, return, ...) and deleted the bug doc `FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`. Its message says "Direction (b) representing None remains a separate project".
- `f226dc758` (2026-11-03, "Fix function with no return to return None (direction b)") took direction (b): it changed `formal/model/calls.py`, both emitters, `test_formal_value_model.py`, and `test_formal_regression_returnless.py`.
- After `f226dc758` the refusal is gone on master (the needle `returns the value of` appears in no master test), and the regression test expects `None`. The binaries still print `0`, so direction (b) is incomplete on one or both emitters.

## Decision and next step

Direction (b) is the decision master has already made, so the refusal that recover row 63 would restore is not the target. The next step is to finish direction (b): make the return-less callee's word read as `None` at the print and printf-vararg consumers, on both `formal/arm64_codegen.py` and `formal/x86_64_codegen.py`, and rerun:

1. `python3 test_formal_regression_returnless.py -v` (must print `None`)
2. `python3 test_formal_value_model.py a_return_less_function_returns_nothing a_functions_only_return_a_return_less_call_yields_nothing`
3. the probe above on both backends

If direction (b) cannot be finished, the alternative is to restore the refusal (`returnless_return_refusal` at the `print` / `return` consumers), which is what recover row 63 carries; either way the regression test and the binary must agree.
