# CODEGEN_tagged_generator_mixed_type_step2-part1: int() and float() of a double box

Class: **mid**. Parent: `bugs/hard/CODEGEN_tagged_generator_mixed_type_step2.md` (split).

## Goal

A name bound to a tagged generator word and to a `double` (the box of step 2 part 2,
`mojo_box_from_double`, kind `'d'`) must read correctly through the builtin casts
`int(x)` and `float(x)`. Today both read the box as if it were a bare word.

## Measured (2026-11-12, HEAD of work/fix-replan-codegen-tagged-generator-mixed-type-step)

```
def g():
    yield 1
    yield 2.5
    yield 3
def main():
    x = 0.5
    for v in g():
        x = v
        print(int(x))          # CPython: 2 on the 2.5 iteration; compiled: 2.5
        print(float(x) + 1.0)  # CPython: 3.5; compiled: 4385631985.0 (box pointer bits)
main()
```

`print(x * 2)`, `x - 1`, `x < 2`, `str(x)`, `bool(x)`, `x / 2` already agree with CPython.

## Acceptance

The program above prints `1 / 2.0 / 2 / 3.5 / 3 / 4.0` on the compiled path, exactly
as CPython does. `int(x)` truncates toward zero for a boxed double, and `float(x)` of a
boxed double returns the double the box holds (an int box widens, as it already does
for `x + 1.0`).

## Next step

Find the `int(` and `float(` builtin cast arms in `mojo/backend_gimple/emit_exprs.py`
(and `emit_infra.py` if the cast is typed there). A boxed operand must unbox through the
kind-aware read (`mojo_unbox_plain` / the `'d'` arm, see
`docs/tagged_generator_mixed_type-box.md` §4) before the cast, the same way the str
literal-cast arm was taught to skip a boxed operand in step 2 part 3.

## Done when

Test: `test_tagged_mixed_readsites.py`, case `double_box_casts` (it builds the program
through `fire.py build` and compares stdout to CPython):

    python3 test_tagged_mixed_readsites.py double_box_casts

It exits 0 when the case passes. Expected to fail today (the measured output above).
