# CODEGEN: `None` passed to a function parameter is not `None` in the callee

A parameter bound from a call argument `None` does not compare equal to `None` in
the compiled body. Two spellings disagree with CPython, on master (80f4ebe4c,
2026-11-15), on both the ordinary GIMPLE path and the C++-coroutine path's
shared call lowering.

## Reproduction

```python
def a(x):
    print("unann is None:", x is None)
    print("unann == None:", x == None)


def b(x: str):
    print("str is None:", x is None)
    print("str == None:", x == None)


a(None)
b(None)
```

Run with `python3 tools/memslot.py --gb 8 --label none-param -- python3 <file>` and
with CPython:

| line | CPython | compiled |
|---|---|---|
| `unann is None:` | `True` | `True` |
| `unann == None:` | `True` | **`False`** |
| `str is None:` | `True` | **`False`** |
| `str == None:` | `True` | **`False`** |

A second probe shows the str-annotated case is not merely a comparison gap: the
callee receives something that is not the None value at all. `return x` from
`def f(x: str)` called with `None`, rendered by `repr`, prints `0` where CPython
prints `None`.

## Why it matters (real measurement)

`Tools/c-analyzer/c_common/scriptutil.py`'s `normalize_selection(selected: str,
*, possible=None)` opens with `if selected in (None, True, False): return
selected`. Called as `normalize_selection(None)`, the membership test is False in
the compiled binary, so execution falls into `elif isinstance(selected, str)`
(a type test that is true for every value of the str type) and returns a
`frozenset([<word>])`; printing the API's result produced `4383444896` (the set
pointer) where CPython prints `None`. The same function is currently refused
outright by a different, unrelated check (a `_Bool` return arm in a `char *`
function — see `bugs/mid/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil-part4.md`),
so the wrong answer was measured with that refusal lifted in memory.

## What is already there

`mojo_unbox_plain` (landed with `bugs/hard/GATE_red_recover-land_2026-11-02.md`
item 2) is supposed to turn a None box into the plain word at user-function call
sites. That lands `is None` for the unannotated parameter but leaves `== None`
wrong, and the str-annotated parameter is not unboxed at all (or is coerced to
the string `"0"` — see `_default_expr_to_pair`'s note that a 0 passed to a
`char *` parameter becomes `mojo_cstr_or_int_str(0)`, i.e. the one-character
string `"0"`, which is exactly what `repr` printed).

## Next step

1. Decide the representation: an argument `None` is the null word `0` for every
   parameter slot (pointer or word), and the callee's `is None` / `== None` must
   treat it as None. The str coercion must not turn a null word into `"0"` at a
   user-function call site (`mojo_cstr_or_int_str` belongs to `print`/`str`,
   not to argument passing).
2. Then make `==`/`!=` against `None` (and `in` a tuple containing `None`) agree
   with `is None` for both boxed and plain words.
3. Regression: a compiled-vs-CPython test next to the ordinary codegen tests
   (`test_gimple.py`) over the four lines in the table, plus `f(None)` returning
   `None` from a `str`-annotated parameter.
