# CODEGEN: a tagged generator value bound to a name loses its kind (`x = next(g)` prints `1`)

A generator whose yields mix kinds (`yield True` beside `yield "b"`) is a
TAGGED word: each yield is a box of its own kind. `print(next(g))` renders
correctly, but `x = next(g)` followed by `print(x)` does not. The assignment
binds the value through `mojo_box_word`, which unwraps the box to its bare
bits, so the kind is gone before `print` runs.

## What was run and seen (2026-11-01, master-based branch work/bug-codegen-a-bare-or-explicit-yield-of)

```python
def gen():
    yield True
    yield "b"

def main():
    g = gen()
    x = next(g)
    print(x)
    x = next(g)
    print(x)
main()
```

- Default (stack-switch) path: `'1\nb\n'`. CPython: `'True\nb\n'`. The bool
  prints `1`: the box is unwrapped at the bind.
- `MOJO_CORO=cpp` (`coro.pinned('cpp')`): `'1\n<address>\n'`. The `"b"` is a
  C++ string literal, which is not in the runtime's literal pool, so the
  unwrapped pointer reads as an int. The default path gets `b` only because its
  literal is registered.

Generated C for the cpp case (`_gimple_main`): `x = mojo_box_word(_t4);`
then `mojo_cstr_or_int_str(x)`. The GIMPLE binder is the cause, not the
generator body.

## Expected

`print(x)` prints the yielded value for every kind (`True`, `b`), on both
paths, matching CPython.

## Where the cause is

- `mojo_box_word` at the bind (the `x = mojo_box_word(...)` in the GIMPLE
  consumer of a tagged generator; the same rule as every possibly-boxed slot
  read: a local holds the word, not the box). The design is deliberate for
  arithmetic, but it loses the kind that a later `print` needs.
- The C++ side of the bind is fine: `x` is tracked as a tagged name
  (`_cpp_tagged_word_names`) when the binder is a coroutine body, and a
  `print` of it renders through `mojo_repr_boxed`.

## Next step

Give a tagged-word local a kind-preserving bind: keep the box for a name that
is only ever printed (or tracked as tagged), and unwrap only where a
numeric consumer needs the word. The GIMPLE emitter already knows the source
is tagged (`_lower_generator_next`, emit_calls.py, marks the result boxed),
so the bind site can record the name the same way the C++ emitter does.
Pin: the two-line program above on both paths, against the CPython oracle,
in `test_gimple_generator_runner.py` (add next to `run_tagged_word_cpp_tests`).
