# DIAGNOSTICS_missing_validation_modular part 3: comptime-for over list comprehensions

Part 3 of the split of `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`.
This is the "comptime-for shapes beyond the gimple unroller" item in the
umbrella's Status.

## Why this part

The gimple comptime-for unroller already resolves a literal list/tuple/dict, a
`range(...)`, a `product(range(...))`, a comptime alias, a string, and a
subscript/slice of a comptime-known value (regressions in
`test_comptime_assert_diagnostic.py` / `test_constrained_diagnostic.py`). It
does not resolve a comprehension used as the iterable.

Measured 2026-11-10:

```mojo
fn f():
    comptime vals = [i * 2 for i in range(3)]
    comptime for v in vals:
        comptime assert v != 4, "bad"
fn main():
    f()
```

This compiles with no diagnostic. A `comptime assert` in the same loop over a
literal list (`[0, 2, 4]`) fails correctly, so the defect is the value of
`vals`: `mojo.middle.comptime.eval_const` has no `Comprehension` case, the
unroller's non-literal branch calls `gen._eval_const(node.iterable)` and gets
`None`, and the body is not unrolled with a bound loop variable. The same
applies to `constrained[...]()` inside such a loop, and to a comprehension
used directly as `comptime for x in [ ... for ... ]`.

`fire_compiler.Comprehension` already carries exactly what is needed
(`kind`, `element`, `value`, `generators`), and `Generator` carries `target`,
`iterable`, `conditions`; no parser work is required.

## Scope

`mojo/middle/comptime.py::eval_const` (and only that folder):

- add a `Comprehension` case that evaluates, in source order, each
  `Generator`:
  - resolve `generator.iterable` with `eval_const` (reuse the existing
    `range`, list, tuple, str and dict support; do not add new iterable
    forms here);
  - for each value, bind `generator.target` to it in a copy of `bindings`;
    a plain identifier target is in scope for this part;
  - evaluate each expression in `generator.conditions` with
    `eval_const_bool`; skip a row when a condition is false;
  - evaluate `Comprehension.element` in the extended bindings (and
    `Comprehension.value` for a dict comprehension);
  - return a `list` / `set` / `dict` according to `kind`, or `None` as soon
    as any piece is not foldable.
- Do not change the unroller. Its non-literal branch already accepts a
  resolved `list`/`tuple`/`str`/`dict`, so a folded comprehension starts
  unrolling through the existing code.
- Nested comprehensions fall out of the recursive call; a generator over a
  comprehension is allowed if its inner `eval_const` resolves. Tuple-unpacking
  targets and `async`/generator-expression kinds are deliberately out of
  scope.

## Acceptance

Add cases to `test_comptime_assert_diagnostic.py` (and the `constrained`
sibling in `test_constrained_diagnostic.py`):

```python
def test_comptime_assert_in_comptime_for_list_comprehension():
    _compile('fn f():\n'
             '    comptime vals = [i * 2 for i in range(3)]\n'
             '    comptime for v in vals:\n'
             '        comptime assert v != 4, "bad"\n')

def test_comptime_assert_in_comptime_for_list_comprehension_true():
    _compile('fn f():\n'
             '    comptime vals = [i * 2 for i in range(3)]\n'
             '    comptime for v in vals:\n'
             '        comptime assert v != 5, "ok"\n')
```

The false case must raise `RuntimeError` containing
`comptime assertion failed: bad`; the true case must compile. Also cover a
comprehension with an `if` filter (`[i for i in range(5) if i > 2]`) and the
direct form `comptime for v in [i * 2 for i in range(3)]:`. A non-constant
element (`[x * 2 for x in values]` with `values` unknown) must stay unfolded
and behave exactly as before.

Run only:

    python3 test_comptime_assert_diagnostic.py
    python3 test_constrained_diagnostic.py

No suite registration and no whole-closure compile.

## Status
- **Open.**
