# CODEGEN: a generator expression that captures an annotated parameter is refused

Found 2026-10-29 while running `test_gimple_generator_runner.py`. Pre-existing
on master (reproduced with the enumerate fix reverted).

## Repro

```mojo
def scaled(items: List[Int], k: Int):
    return list(x * k for x in items)

def main():
    print(scaled([1, 2, 3], 10))

main()
```

    expected (CPython / the test's oracle):  [10, 20, 30]
    compiled:  refused at compile time:
      "generator expression could not be compiled into a generator: __genexp_0 —
       neither the stack-switch nor the C++20 coroutine path supports this shape
       (a captured value the synthesized generator cannot take, most often a
       struct or a container)."

The `if`-filter form fails the same way
(`list(x * 2 for x in items if x % 2 == 0)` over `List[Int]`).

## Failing tests (test_gimple_generator_runner.py, both red on HEAD)

- `genexp_over_annotated_param_with_capture`
- `genexp_over_annotated_param_with_condition`

## Next step

The refusal is the synthesized `__genexp_0` generator not accepting the
captured `k: Int`. The captured value is a plain scalar, so it should be
passed as an ordinary generator argument, the same way a call-site argument
kind reaches a generator parameter. Find the capture-check in the genexp
synthesis path and check why a scalar annotated-param capture is classed as
"cannot take" alongside structs and containers. Make the scalar case compile
and keep the struct/container refusal unchanged.
