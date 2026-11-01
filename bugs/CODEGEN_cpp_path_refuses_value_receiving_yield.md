# CODEGEN_cpp_path_refuses_value_receiving_yield: `x = yield` is refused on the cpp generator path

## Status (2026-11-01, found while pinning the TypeError fix for arithmetic on a received None, `none_received_arithmetic_raises_typeerror`)

The default (A3 stack-switch) path compiles `x = yield` and binds the sent
value. The cpp escape hatch (`coro.pinned('cpp')`, `MOJO_CORO=cpp`) refuses
the same program at compile time:

```
cannot compile module: function(s) g (generator function(s), contain a
`yield`/`yield from`) ... Unsupported shape(s): g: unsupported expression in
generator body: YieldExpr.
```

The refusal is loud (the module falls back to interpreting from source), so it
is a coverage gap, not a silent wrong value. It is why the arithmetic-on-None
regression pin exists only on the default path.

### Repro

```python
def g():
    x = yield
    try:
        print(x + 1)
    except TypeError:
        print("TypeError")
    yield 1

def main():
    it = g()
    next(it)
    next(it)
main()
```

Run it through `test_generator_matches_cpython` inside `with coro.pinned('cpp'):`
(e.g. `run_tagged_word_cpp_tests` in `test_gimple_generator_runner.py`).

- CPython: `TypeError`
- cpp path: compile refusal `unsupported expression in generator body: YieldExpr`

### Next step

1. In the cpp generator emitter (`gimple_cpp_*`), lower a `YieldExpr` that is
   the value of an assignment (`x = yield`, `x = yield v`) by reading the
   resume value the consumer passes in, the same way the default path's
   `mojo_gen_*` resume word does. Bare `yield` in statement position already
   lowers; only the expression-value form is missing.
2. Once it lowers, add the cpp pin for `none_received_arithmetic_raises_typeerror`
   next to `run_tagged_word_cpp_tests` (the source is `_NONE_RECEIVED_ARITH_SRC`
   in `test_gimple_generator_runner.py`), and check that it passes.
