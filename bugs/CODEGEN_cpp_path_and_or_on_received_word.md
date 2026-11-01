# CODEGEN_cpp_path_and_or_on_received_word: `and`/`or` on a tagged word with a str right operand

Found 2026-11-01 while hoisting yields in conditions (CODEGEN_cpp_path_refuses_expression_position_yield).

## Status (2026-11-01): partial fix landed

Landed: `and`/`or` with a TAGGED left operand and a NON-str right operand now
lower to a tagged word (`cpp_core._cpp_and_or_is_tagged`, `_cpp_tagged_operand_word`,
`cpp_async._cpp_word_of_kind`). The result is the left word or the right
operand boxed by its kind; the truth test is `mojo_truthy_word`. The result
is tracked as tagged everywhere a tagged word is consumed: `print`, `if`/`while`/`not`,
arithmetic (the None guard), and `y = x or 5` (the assignment marks `y`).
Pinned by `received_and_or_operand_cpp` and `tagged_next_and_or_operand_cpp`
in `test_gimple_generator_runner.py`.

Still wrong (the remaining scope):

1. **str right operand**: `x or 'd'`, `x and 'a'` with a tagged `x`. These
   keep the old lowering on purpose (see `_cpp_and_or_is_tagged`): `or` uses the
   `_W` struct, whose `char *` view is the raw word, so a str-box left operand
   (`x = next(g)` yielding `"a"`) prints the box's address, and `and` falls to a
   C `&&` (prints `1`). Next step: make the `_W` result carry the tagged word,
   with `operator char *` returning `(char *)mojo_box_word(w)`, and mark the
   result tagged only where its declared type is not `char *` (the
   `s = x or 'd'` local must stay `char *`). Add `and` to the str-right branch.
2. Repro for (1): `x = next(g)` on a generator yielding `0, "a", 3`, then
   `print(x or 'd')` and `print(x and 'a')`; compare to the CPython oracle.

## Repro (original, now fixed for the int right operand)

```
def g():
    x = yield 1
    print(x or 5)
    print(x and 7)
    yield 2
```

CPython: `1\n5\nNone\n2\n`. Before the fix the cpp path printed `1\n1\n1\n2\n`.
