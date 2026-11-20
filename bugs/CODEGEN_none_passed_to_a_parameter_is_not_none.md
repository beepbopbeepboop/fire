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
pointer) where CPython prints `None`. (That refusal, a `_Bool` return arm in a `char *`
function, no longer applies: the module builds, and the function's arms are boxed as a tagged
word. What still differs from CPython for this function is tracked in
`bugs/CODEGEN_param_annotation_contradicted_by_the_body.md`.)

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

## Status 2026-11-19: the four table lines are fixed; one residual remains

Landed (no representation change: the integer 0 and None stay different values):

- `emit_infra._emit_call`: a literal `None` argument passed to a `char *` parameter is the NULL
  pointer, not `mojo_word_cstr_value(0)` (the string `"0"`). It needs the call's argument nodes,
  so the statement-call site in `emit_stmts` (`b(None)` with the result discarded) now passes
  `node.value.args` as `_call_expr` already did.
- `emit_exprs._lbt_none_eq`: `x == None` / `x != None` on an UNANNOTATED parameter (a word of
  unknown kind, `gen._cur_untyped_params`) tests the null word, exactly as `x is None` does,
  instead of folding to a constant. An annotated int still folds (`0 == None` stays False).
- Test: `test_gimple_runner.py::test_none_argument_is_none_in_the_callee` compares the doc's
  four lines, `!=`, the empty string, `"0"`, `c(0)`, `c(5)` and `0 == None` against CPython.
- Checked: all 640 `test_gimple_runner.py` cases passed on this change (the six the reverted attempt
  broke included), `test_gimple.py` passes, `compile_stdlib.py` 610/0 unexpected,
  `build_stdlib_dylib.py` 0 skips.

Still open: `repr(c(None))` for `def c(x: str): return x` prints `''`, CPython `None`. The cause is
`runtime/fire_runtime.c::mojo_repr_str`'s deliberate `if (!s) s = "";`. Changing a NULL string to
repr as `None` is the right answer for this program, but the self-hosted AST dumps are compared byte
for byte against the interpreted ones in `make bootstrap` (stage1 == stage2 == stage3), and a NULL
string field in those dumps is spelled `''` today. So that edit needs the owner's bootstrap run; the
`'0'` it used to print is gone.

Also still open, found on the way: an unannotated parameter holding the integer 0 answers
`x is None` True (the word is 0), where CPython says False. That is the cost of the single null
word for an unknown-kind parameter; closing it needs a distinct None word, which is the
representation decision the reverted attempt got wrong.
