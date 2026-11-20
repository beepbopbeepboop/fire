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
word. What still differs from CPython for this function is the UNANNOTATED spelling
of the same body: `bugs/CODEGEN_untyped_parameter_word_kind_not_recovered.md`.

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

## Status 2026-11-20: repr of a None str value is `None`; the unannotated-word residual remains

Landed: `repr` of a statically `char *` value renders a NULL as `None`, as CPython does.

- `runtime/fire_runtime.c` / `fire_runtime.h`: new `mojo_repr_str_or_none(char *)`, NULL -> `strdup("None")`,
  otherwise `mojo_repr_str`. Plain `mojo_repr_str` is unchanged, so every other caller keeps NULL-as-`''`.
- Registered beside `mojo_repr_str` in `mojo/middle/rt_sigs.py`, `gimple_codegen.py`'s table and
  `emit_infra.py`'s `_FRESH_STRING_RETURNS` and malloc-unconditional lists.
- Codegen sites switched: `emit_resolve.py` (the `rat == 'char *'` arm of the repr resolver) and the five
  `mojo_repr_str((char *)(...))` sites in `cpp_core.py` (the C++-coroutine path's f-string, `repr()` and
  list/tuple element reprs). `module_gen.py`'s generated dataclass/struct walkers already tested NULL -> None
  for `char *` fields and are unchanged.
- Measured against CPython (`repr(c(None))`, `repr(g(None))` with `def g(x: str = "")`, `repr(r(None))` in a
  `str`-annotated function): compiled now prints `None`, `None`, and `repr("")`, `repr(0)`, `0 == None`,
  `"" == None` are unchanged.
- Regression: `test_gimple_runner.py::test_none_argument_is_none_in_the_callee` gained
  `def r(x: str): return x` and `print(repr(r(None)), r(None), repr(r("")), repr(r("0")))`.
- Generated-C effect, measured: with `#line` directives stripped, `myinterpreter.py`, `fire.py` and
  `gimple_codegen.py` emit identical C before and after. In `fire_compiler.py` exactly 15 call sites change, all
  `{x!r}` inside `SyntaxError` messages of token values. The `.ast`/`.tok` dumps are not affected: they go through
  `repr(ast)`, whose dataclass fields are already NULL-tested in `module_gen.py`.
- The `make bootstrap` byte-compare has NOT been run here (agent policy). The owner should run it once to confirm
  stage1 == stage2 == stage3 with this change.

Still open: an UNANNOTATED parameter (or a copy of one) holding None answers `repr` / `str` with `0`:
`def u(x): return x` then `repr(u(None))` prints `0` (CPython `None`), and `y = x` inside a `str`-annotated
function does the same. The word is the null word, and an unknown-kind word cannot say `repr` is `None`
rather than `0`. Closing this needs the distinct None word the reverted attempt got wrong (decision in item 1
above); `== None` and `in` on the integer 0 must stay False. Unrelated to this entry's repr fix.

Also still open: an unannotated parameter holding the integer 0 answers `x is None` True (the word is 0),
where CPython says False. Same cause as the entry above.
