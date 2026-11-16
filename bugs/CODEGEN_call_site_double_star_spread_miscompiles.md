# CODEGEN: a `**dict` spread at an ordinary call site is silently miscompiled

A function call that passes a `**<dict>` spread is lowered as if the dict
itself were the next POSITIONAL argument, so the callee receives the dict
pointer where the first parameter belongs and every keyword written in the
spread is dropped. The compiled program exits 0 and prints a number derived
from the dict's address. Found on master `b61b57dc5` / branch
`work/bug-land-mid-compile-fail-tools-c-analyz-2` (2026-11-15) while adding
`test_regress_generator_keyword_arg_binding.py`; it is a pre-existing bug,
not a regression from that fix, and it is the ORDINARY-call twin of the
generator keyword-binding bug that test pins.

## Reproduction

```python
def f(a, b=2, c=3):
    return a * 100 + b * 10 + c


def main():
    print(f(5, b=4))                       # 543, correct
    print(f(5, **{"b": 4, "c": 7}))        # CPython 547
    print(f(**{"a": 5, "b": 4, "c": 7}))   # CPython 547
    d = {"a": 5, "b": 4}
    print(f(**d))                          # CPython 543


main()
```

`python3 tools/memslot.py --gb 8 --label spread -- python3 fire.py build -o
<tmp>/spread <tmp>/spread.py` then run the binary:

| line | CPython | compiled (exit 0) |
|---|---|---|
| `f(5, b=4)` | `543` | `543` |
| `f(5, **{"b": 4, "c": 7})` | `547` | `43257497783` |
| `f(**{"a": 5, "b": 4, "c": 7})` | `547` | `432575036823` |
| `f(**d)` | `543` | `432575100823` |

(The printed values differ per build; they are a stringified dict/pointer
mixed with the digits the slots that did bind contributed. The point is that
they are not CPython's answers and nothing refuses.)

A call with only named keywords (`f(5, b=4)`) is correct, so the defect is
the `**` arm, not keyword binding: `node.args` carries the
`UnaryOp(op='**')` and the ordinary argument lowering
(`emit_calls._lower_named_call` / its generator twin
`_emit_generator_start_call`) treats it as one positional expression.

A compiled-generator call through the same ordinary path miscompiles too,
and there the stray dict word reaches the generator's value slot:

```python
def marks(marks='.', *, group=5, groups=2):
    while True:
        yield groups


def outer(items, groups=5, **kw):
    m = marks(groups=groups, **kw)
    for item in items:
        print(next(m), item)


outer([1, 2], groups=3, group=7)   # CPython: "3 1" / "3 2"
```

compiled (after the 2026-11-15 keyword-binding fix): `4390817680 1` /
`4390817680 2`, exit 0 — the dict word printed as the yielded value.

## What already works

- Named keyword arguments to an ordinary function bind by name.
- Named keyword arguments to a compiled generator bind by name (fixed by
  `test_regress_generator_keyword_arg_binding.py`, 2026-11-15).
- A `**<dict>` spread forwarded inside a C++-coroutine/generator body to a
  compiled generator is bound by name with runtime dict lookups
  (`cpp_core._cpp_generator_start_kwargs_expr`, landed with the ADAPT of
  `work/bug-mid-compile-fail-tools-c-analyzer-c-2`). That is the generator-
  body path only; this doc is about the ordinary call path.

## Next step

1. Decide the lowering: at a statically-resolved call, bind each
   `**<dict>` key by parameter NAME with a runtime dict lookup
   (`mojo_dict_contains`/`mojo_dict_pop_int`/`mojo_dict_pop_str`, the same
   primitives `_cpp_generator_start_kwargs_expr` uses), filling omitted
   slots with the callee's own defaults; or, until that exists, REFUSE the
   shape with a diagnostic. A positional guess is never correct.
2. The same treatment for `*<iterable>` positional spreads, which have the
   same "one positional expression" shape and should be measured before
   being claimed.
3. Add a compiled-vs-CPython regression next to `test_gimple.py` over the
   four lines above, plus one generator call with the same spread through
   the ordinary path.
