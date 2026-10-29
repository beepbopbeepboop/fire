# CODEGEN: a generator yielding an element of a string produced by a str METHOD CALL prints addresses

**State: OPEN.** Found 2026-10-28 while fixing the string-parameter case in
`generator_iterating_a_string_parameter_yields_nothing`
(`mojo/middle/coro.py` `_static_env`, the for-loop element kind).

## Repro

```python
def gen():
    s = 'ab'.upper()
    for it in s:
        yield it

def go():
    for v in gen():
        print(v)

go()
```

CPython prints `A` then `B`. Compiled prints `4340745018` / `4340745020`
(object addresses), exit 0.

## Mechanism

`_static_env` records a local's kind only from an annotation, a literal, or
`_yield_kind(value)`. `_yield_kind` has no case for a method call on a string
(`'ab'.upper()`, `.lower()`, `.strip()`, `.replace(...)`, ...), so `s` gets
no kind, `for it in s` finds no element kind, `it` falls through to the
int64_t yield slot, and the consumer prints the `char *` as an integer.

The same program with `s = 'AB'` (a literal) works; the parameter and
literal cases were fixed by the for-loop element-kind change in `_static_env`.

## Next step

Teach `_yield_kind` (or the `_static_env` local arm) the str-returning
methods, sourced from one table rather than a per-method special case, or
better, from the ordinary codegen's own call return types if they are
available at that pre-pass. Pin with a generator test next to
`generator_iterating_a_string_literal_yields_characters` in
`test_gimple_generator_runner.py`.
