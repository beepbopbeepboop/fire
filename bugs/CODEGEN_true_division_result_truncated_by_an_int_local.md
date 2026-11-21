# CODEGEN: a true-division result truncates when it is stored in an int local (plain `=`, not `+=`)

Found 2026-11-20 while fixing the float augmented-assignment truncation
with `tools/pydiff.py` (CPython versus the compiled binary). That fix taught
the augmented-assignment side to rebind the local to the float; the plain
assignment and `return` spellings still truncate, through a different typing
path, so they are recorded here rather than folded into that fix.

## Repro `plain_halves.py`

```python
def half(n):
    return n / 2

def main():
    print(half(9))
    x = 9
    x = x / 2
    print(x)
main()
```

CPython prints `4.5` twice; the compiled binary prints `4` twice. `tools/pydiff.py`
reports WRONG on the first line.

## Root cause

The emitter is right: `_lower_binary_tail` sets `int_true_div` for `/` between
two signed integers and answers `double`. The type ESTIMATOR disagrees.
`resolve_shared._quick_type`'s `BinaryOp` arm (and therefore
`_local_value_type`, `_infer_local_var_types` and `_infer_return_type`'s
`_collect_return_types`) falls through to
`TypeLattice.join(int64_t, int64_t) = int64_t` for `a / b`. So:

- `x = x / 2` declares `x` int64_t from that binding, and the store's
  `_safe_coerce_emit('double', 'int64_t', ...)` truncates 4.5 to 4;
- `def half(n): return n / 2` infers an `int64_t` return type and the
  `return` conversion does the same.

The augmented-assignment fix did not need this because it computes the one
result type it needs in `_aug_assign_value_type`; the plain-assignment and
return arms still read `_quick_type`.

## Next step

Teach `_quick_type`'s `BinaryOp` arm the same true-division rule the emitter
uses (`op == '/'` and both operand estimates in
`gimple_ctypes._SIGNED_INT_TRUE_DIV_TYPES` -> `double`), ideally by sharing
the rule with `_aug_assign_value_type` so the estimator and the emitter cannot
drift. One caveat, measured against `PythonObject`:

    def main():
        a = PythonObject(34)
        b = PythonObject(10)
        c = a / b
        print(c)

emits `c` as an int64_t WORD of double BITS (`_py_box_expr`'s box arm in
`_lower_binary_tail`), and the pre-pass deliberately types it int64_t. The
`_quick_type` rule must therefore answer int64_t for a box operand
(`_py_box_expr(gen, node)`), and the pre-pass must see the same box set the
emitter does — today `_pybox_vars` is populated during emission, after
`_infer_local_var_types` has run. Either seed the box names from the body
before the pre-pass, or keep the fix in the pre-pass (`_local_value_type`)
and answer the box shapes explicitly.

Cases to pin in `test_gimple_runner.py` (`test_gimple_matches_cpython`):
`x = 9; x = x / 2`, `def half(n): return n / 2`, and a `PythonObject`
division as the control that must keep its box.

## Done when

Save the repro as a `.py`, run `python3 tools/pydiff.py <file>` and it prints
`OK`; add the cases above to `test_gimple_runner.py`, then delete this doc in
the same commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
