# CODEGEN_cpp_path_print_multi_arg_in_generator: `print(a, b)` with two arguments is refused in a generator body on the cpp path

## Repro

Run under `coro.pinned('cpp')` (`MOJO_CORO=cpp`), via
`gimple_codegen.compile_to_gimple_with_cpp(src, do_imports=False)`:

```python
def f(x):
    return x + 1

def g():
    a = f(1)
    print(a, 5)
    yield 2

def main():
    it = g()
    print(next(it))
main()
```

Got: `Unsupported shape(s): g: a call to unresolved callee 'print(...)' is not
supported in a compiled generator/coroutine body`. The module falls back to
interpreting from source.

Expected: the program compiles on the cpp path and prints `1 5` then `2`,
as CPython does.

The same refusal fires for `print(f(1), (yield 1))` once the yield is hoisted
(the hoisted form is `print(<temp>, <yield temp>)`), so this gap also blocks
yield-operand shapes that take a multi-argument `print`.

## Where

`mojo/backend_gimple/cpp_core.py`, the generic-callee refusal near
`a call to unresolved callee '{fname}(...)'` in the coroutine-body call
emitter. Single-argument `print` is dispatched; the multi-argument form is not
reached by that dispatch and falls through to the generic refusal.

## Next step

Find the single-argument `print` dispatch in the cpp coroutine-body call
emitter and extend it to N arguments: emit one print per argument with the
separator between them (CPython's default `sep=' '`, `end='\n'`), each argument
lowered through its own kind (int, float, bool, str, tagged word). Pin with a
`test_generator_matches_cpython` case on the cpp path, e.g. `print(a, 5)` with
the `a = f(1)` shape above.
