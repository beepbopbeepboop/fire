# CODEGEN_cpp_path_and_or_on_received_word: `and`/`or` on a received yield word ignores its truthiness

Found 2026-11-01 while hoisting yields in conditions (CODEGEN_cpp_path_refuses_expression_position_yield).

## Repro

```
def g():
    x = yield 1
    print(x or 5)
    print(x and 7)
    yield 2

def main():
    it = g()
    print(next(it))
    print(next(it))
main()
```

Run under `coro.pinned('cpp')` (the `MOJO_CORO=cpp` escape hatch) via
`gimple_codegen.compile_to_gimple_with_cpp` and the test runner's
`_build_generator_program`.

- Compiled cpp output: `1\n1\n1\n2\n`
- CPython: `1\n5\nNone\n2\n`

`x` is the None box the consumer resumes the yield with (`_cpp_assign_received_yield`).
The `or`/`and` lowering in `mojo/backend_gimple/cpp_core.py` tests the word's bits
(`or` only has a string-typed special case, `_or_lt`/`_or_rt`), so the box reads as
truthy and the result is the word, not the operand Python would return.

`if x:` / `while x:` / `not x` on a received word are correct now: they go through
`mojo_truthy_word` (`_cpp_is_tagged_word_expr` in the `if`/`while` branch and the
`not` branch of `_cpp_expr`).

## Why it is not fixed here

`and`/`or` return an OPERAND, so a tagged left operand needs a result kind as
well as a truth test: `x or 5` is the None box or `5`, and that result must be
printed/bound as a tagged word, not an int64. That is a representation change in
the operator lowering, not a one-line truth test.

## Next step

In `cpp_core.py`'s `BinaryOp` lowering, for `op in ('and', 'or')` with a tagged-word
left operand (`_cpp_is_tagged_word_expr`): compute the truth with
`mojo_truthy_word`, and produce the operand word itself on the chosen side
(`or`: `truthy ? left : right`; `and`: `truthy ? right : left`), with the right
operand's kind carried by the same box. Pin with the repro above against the
CPython oracle in `run_tagged_word_cpp_tests`.
