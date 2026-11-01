# CODEGEN: a tagged generator value bound to a name loses its kind (`x = next(g)` prints `1`)

A generator whose yields mix kinds (`yield True` beside `yield "b"`) is a
TAGGED word: each yield is a box of its own kind. `print(next(g))` renders
correctly, but `x = next(g)` followed by `print(x)` used to not. The
assignment bound the value through `mojo_box_word`, which unwraps the box to
its bare bits, so the kind was gone before `print` ran.

## Status (2026-11-01, branch work/bug-codegen-a-bare-or-explicit-yield-of, partial fix)

**Landed (real behaviour change, both compiled paths):** a tagged-word bind
now keeps its box when the name is only ever bound from one tagged `next`:

- `gen._tagged_word_vals` (emit_infra.py, per-function, saved and restored
  with `_boxed_vals`): the temps produced by the two tagged-`next` sites
  (emit_calls.py, `_lower_generator_next` and the two-argument `next(it,
  default)`).
- The bind (emit_stmts.py, `IdentExpr` target): a tagged temp keeps its box
  when `ginf.tagged_next_bind_name` holds. That rule is every binding of the
  name in the function being `name = next(g)` for one generator local `g`
  that is itself bound once, and the name is not a parameter. The local is
  added to `_boxed_vals` and `_tagged_word_vals`. Anything else (a rebinding
  to a plain value, a second generator, a for target) takes the old unwrap.
- Boxed-operand arithmetic (emit_exprs.py, binary op): a tagged local
  operand uses `mojo_box_word` (the int word), not `mojo_box_double`, so
  `x + 1` stays int arithmetic (`mojo_box_double` made it `2.0`).

**Pins:** `run_tagged_word_bind_tests` in `test_gimple_generator_runner.py`
(five cases, CPython oracle). Before the fix: `tagged_bind_print_default`
prints `'1\nb\n'` and `tagged_bind_print_cpp` prints an address; after,
5/5 pass.

**Still open:**

1. **Float box arithmetic.** `yield 2.5; yield "b"`, `x = next(g); print(x)`
   now prints `2.5` on both paths (was wrong). `print(x * 2)` still prints a
   box ADDRESS on both paths (CPython `5.0`). By reading, the old bind gave the
   same box word, so this is not a regression. The fix needs an operand that
   selects int or double by the box kind at run time, which is the
   `_FLOAT_ARITH_OPS` run-time select already used for may-hold-float
   parameters; the tagged operand path should reuse that, not a new helper.
2. **Other consumers of a kept tagged local** (`str()`, f-string, a
   multi-argument `print`, comparisons with numbers, list append) were not
   audited beyond the pins above; they go through the `_boxed_vals` arms in
   emit_infra.py (`str`/print via `mojo_repr_boxed`) and were not separately
   measured.
3. Gate: this widens which generator-bound names keep a box. The integrator
   should compare `stdlib-dylib`'s `skip` count and `stdlib-syntax`'s `U` count
   before and after, and check `gimple_codegen` self-host (the new `_fet` entry
   and `_set_elem_fields` entry in emit_infra.py must match the generator's
   field tables).

## What was run and seen (2026-11-01, before the fix)

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
  printed `1`: the box was unwrapped at the bind.
- `MOJO_CORO=cpp` (`coro.pinned('cpp')`): `'1\n<address>\n'`. The `"b"` is a
  C++ string literal, which is not in the runtime's literal pool, so the
  unwrapped pointer read as an int.

Generated C for the cpp case (`_gimple_main`): `x = mojo_box_word(_t4);`
then `mojo_cstr_or_int_str(x)`. The GIMPLE binder was the cause, not the
generator body.

## Expected

`print(x)` prints the yielded value for every kind (`True`, `b`), on both
paths, matching CPython.
