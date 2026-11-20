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

`mojo_unbox_plain` (landed earlier as item 2 of the `GATE_red_recover-land_2026-11-02`
bootstrap-recovery work) is supposed to turn a None box into the plain word at
user-function call sites. That lands `is None` for the unannotated parameter but
leaves `== None` wrong, and the str-annotated parameter is not unboxed at all (or
is coerced to the string `"0"` — see `_default_expr_to_pair`'s note that a 0 passed
to a `char *` parameter becomes `mojo_cstr_or_int_str(0)`, i.e. the one-character
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

## Status 2026-11-16: one attempt was tried and REVERTED. Do not repeat it.

Branch `work/bug-codegen-none-passed-to-a-parameter-i` (commit `db6b4f640`)
was landed and then reverted the same day. It passed its own test and broke
six cases of `test_gimple_runner.py` that passed before:

    gimple_int_in_mixed_str_int_list
    gimple_str_window_matches_cpython
    gimple_percent_format_star_width_and_precision
    gimple_erase_slot_holding_a_string
    gimple_namedtuple_literal_runs          (crashed, exit -11)
    gimple_none_local_needle_in_membership

What it did wrong. It decided "None is the word 0 everywhere" and then made
the rest of the compiler agree with that:

- `x == None` on a plain integer became `x == 0`. So `0 == None` is True.
  In Python it is False. The code it deleted in `_lbt_none_eq`
  (`mojo/backend_gimple/emit_exprs.py`) was the earlier fix for exactly that.
- membership in a mixed list matched a None slot against the integer 0.
- a NULL `char *` printed as `None`, including where it is an empty/absent
  string that must not print at all.

Rule for the next attempt. The integer 0 and None must stay different
values. A fix may change how None is PASSED to a parameter (the boxed None
word, or a typed null for a pointer parameter) and how the callee tests it.
It must not change what `== None`, `in`, `str()` or `repr()` answer for the
integer 0 or for an empty string.

Run before calling it done (about 30 minutes, and required for this bug):

    python3 test_gimple_runner.py

The six names above must pass, together with this doc's own test.
