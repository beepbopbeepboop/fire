# CODEGEN_cpp_path_refuses_expression_position_yield: a `yield` used as a value inside a larger expression is refused on the cpp generator path

## Status (2026-11-01, left behind by the `x = yield` lowering)

The cpp escape hatch (`coro.pinned('cpp')`, `MOJO_CORO=cpp`) now lowers a
`yield` that is the whole right-hand side of an assignment: `x = yield` and
`x = yield v` (`_cpp_assign_received_yield` in `mojo/backend_gimple/cpp_core.py`).
A `yield` used as a value inside a larger expression is still refused at
compile time. The refusal is loud (the module falls back to interpreting from
source), so it is a coverage gap, not a silent wrong value.

### Repros (both refused on this tree)

```python
def g():
    print((yield 1))
    yield 2

def main():
    it = g()
    next(it)
    next(it)
main()
```

Refusal: `Unsupported shape(s): g: print() argument must be a scalar
int64_t/double/_Bool/char* expression.`

```python
def g():
    x = 1
    x += yield 2
    yield x

def main():
    it = g()
    print(next(it))
    print(next(it))
main()
```

Refusal: `Unsupported shape(s): g: unsupported expression in generator body:
YieldExpr.`

Both are run through `coro.pinned('cpp')` (for example via
`test_gimple_generator_runner._build_generator_program`). CPython runs both.

### Next step

The shapes that must lower, in the order they appear in practice:

1. An augmented assignment whose right side is a yield (`x += yield v`). It
   is the same shape as `x = yield v` with one read of `x` added, so it reuses
   the same received-None lowering. Check that the AugAssign lowering reaches
   the None guard (`_cpp_guard_none_operand`, which is registered from the
   BinaryOp branch of `_cpp_expr`): an AugAssign may not go through that branch.
2. A yield as a call argument (`print((yield 1))`). It needs the yield to be
   hoisted into its own statement, with the call reading the bound name. Add
   a hoisting pass in the cpp generator body lowering, scoped to statement
   bodies that contain a yield in an argument position.

Each lowering needs a cpp pin in `run_tagged_word_cpp_tests`
(`test_gimple_generator_runner.py`) with its CPython twin. The `send()` gap
that would change what these receive is in `bugs/CODEGEN_cpp_send_emits_default_path_symbol.md`.
