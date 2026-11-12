# CODEGEN_tagged_generator_mixed_type_step2-part2: str-box operands of * and box + box

Class: **mid**. Parent: `bugs/hard/CODEGEN_tagged_generator_mixed_type_step2.md` (split).

## Goal

A name bound to a tagged generator word and to a `str` (the box of step 2 part 3,
`mojo_box_from_str`, kind `'p'`) must work as the operand of `*` and of `+` when the
other operand is the same box. Today both read the box pointer as an integer.

## Measured (2026-11-12, HEAD of work/fix-replan-codegen-tagged-generator-mixed-type-step)

```
def g():
    yield 1
    yield "a"
    yield 3
def main():
    x = 0
    for v in g():
        x = v
        print(x * 2)   # CPython: aa; compiled: 8749559936 (a pointer-sized integer)
        print(x + x)   # CPython: aa; compiled: 8749559936
main()
```

`str(x)`, `bool(x)`, `f"<{x}>"`, `x == "a"` already agree with CPython. Step 2 part 3
covered `x + "!"` (a literal operand), not a box operand.

## Acceptance

The program above prints `2 / 2 / aa / aa / 6 / 6` on the compiled path, the same as
CPython. `str * int` on a str box repeats the string, and `str + str` where both operands
are the same mixed name concatenates them. The int-box cases (`x = 1` iteration) keep
printing `2` and `2`.

## Next step

Find the binary-operator emitter in `mojo/backend_gimple/emit_exprs.py` (the arm that
already has the step 2 part 3 literal-cast skip for a boxed operand). Two operands that
are both boxed, or a boxed str with an int, must take the str-aware path (the runtime
has `mojo_str_concat`-style helpers; confirm the exact name in `runtime/fire_runtime.c`
before relying on it) instead of the int64 path. Keep the int-only path unchanged.

## Done when

Test: `test_tagged_mixed_readsites.py`, case `str_box_binops` (it builds the program
through `fire.py build` and compares stdout to CPython):

    python3 test_tagged_mixed_readsites.py str_box_binops

It exits 0 when the case passes. Expected to fail today (the measured output above).
