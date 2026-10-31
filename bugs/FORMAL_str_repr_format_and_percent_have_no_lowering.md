# `str()`, `repr()`, `format()`, `%` and `.format()` have no lowering: a value's TEXT is not a compile-time constant

**Area:** FORMAL, both backends — five refusals in three different places
(`formal/model.py`'s `repr`/`format` link-audit refusals, its
`printf_text_conversion_refusal` for a `str(…)` operand, and the generic
`print()` operand refusal for `%` and `.format()`).
**Status:** OPEN, measured 2026-10-05 on `work/formal65-format-and-repr` at
`108392fc` (this repository, `/opt/homebrew/bin/python3` 3.14.7, formal arm64 +
x86-64).

## What I ran, what I saw, what I expected

Five spellings of the same question — "write this value's text" — each refused,
each with a DIFFERENT message, and none of them about the thing that is missing:

```console
$ for src in 'print(str(1))' 'print(repr(1))' 'print(format(1, "d"))' \
            'print("%d" % 1)' 'print("{}".format(1))'; do
    printf '%s\n' "$src" > .tmp/m.py
    python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/m .tmp/m.py 2>&1 |
      head -1
  done
build: the `%s` conversion in printf's format string reads `str(...)` as text, …
build: `repr(...)` is not lowered on this path, and the reason is a property of
        the NAME rather than of the link line: `repr`: a rendering whose spell…
build: .tmp/m.py: the image would bind 1 symbol(s) that nothing provides, so it
        could not be loaded: format. …
build: print() cannot tell whether BinaryOp is a string or a number …
build: print() cannot tell whether CallExpr is a string or a number …
```

and CPython on the same five: `1`, `1`, `1`, `1`, `1`.

The five messages are the finding as much as the five refusals are. Two of them
(`%`, `.format()`) are the GENERIC operand refusal, which is false about the
operand — the model classified it, and a `BinaryOp` that is `%` is not a
mystery. One (`format`) is a LINK-AUDIT message about a symbol nothing provides,
which is true and says nothing about what the writer wrote. One (`str`) is about
a `%s` conversion reading an expression, which is a real diagnosis of a real
hazard — it just does not say that `str` has no lowering. And one (`repr`) is the
only one that names the actual absence ("a rendering whose spelling depends on
the VALUE's type, and the type is not in a value"), which is what the other four
should say.

Rows: `test_formal_format_conformance.py`'s `str_call_refused`,
`repr_call_refused`, `format_call_refused`, `percent_refused`,
`dot_format_refused`, on both backends. The `!r`/`!s`/`!a` and
`:spec` rows (`fstring_repr_refused`, `fstring_str_refused`,
`fstring_ascii_refused`, `fstring_spec_refused`) are the same absence reached
through an f-string and are already covered by
`bugs/FORMAL_string_composition_has_no_buffer.md`, which owns the f-string half
and the buffer question; they are listed here so a reader of the table knows
where the boundary is.

## The actual absence

**`print` is the only value→text conversion this path has, and it is a
compile-time one.** `model.print_call_spelling` decides each operand's rendering
from what the operand statically is and writes it into ONE format string
(`%s`, `%lld`, `%llu`, plus the constant-text arms `print_constant_text` and
`bytes_repr_body`). Every one of those decisions is made before the image runs,
which is exactly what makes them decidable — and exactly why they cannot answer
the five questions above:

* **`str(x)` / `repr(x)` for a RUNTIME `x`** is "render the word in the register
  to text", which is what `%lld` and `%s` already are for a value whose KIND the
  build knows. So for an `Int` or a `String` operand the machinery exists and
  the only thing missing is the CALL. For any other kind it does not: `repr` of
  a `Bool` is `True`/`False`, of a `None` is `None`, of a `float` is
  shortest-round-trip (`bugs/FORMAL_a_float_has_no_print_spelling.md`), of a
  container is its elements' (`FORMAL_a_print_of_a_container_needs_a_text_loop.md`),
  of a type is `<class 'int'>`. **`print`'s own per-kind table is therefore the
  right first step for `str`/`repr`, and it is already written** — which is the
  useful thing this doc records.
* **`format(x, spec)`** is `print`'s table PLUS the format-spec mini-language:
  `[[fill]align][sign][#][0][width][,][.precision][type]` over `d x X o b e f g
  % c s`, plus the `,`/`_` separators and the `z`/`n`/`g` group separators. Each
  of those is a small, decidable emitter change ON TOP of a `%lld`-shaped
  conversion — `d` is `%lld`, `x` is `%llx`, `X` is `%llX`, `o` is `%llo`,
  `c` is `%c`, `b` is a base-2 loop, `s` is `%.*s` (and a WIDTH on a `%s` is a
  BYTE width on this path, which is its own bug for non-ASCII — the comment on
  `_PRINTF_QUANTIFIER_RE` in this file records it), and the flags map onto
  printf's own flags. **So the mini-language is mostly a table from a spec string
  to a printf conversion, plus the five arms printf has no conversion for.**
* **`"..." % x`** is the same mini-language with `%` as the sigil and no named
  fields, and it additionally has to bind a TUPLE of operands positionally
  (`"%d %s" % (a, b)`) and a MAPPING by key (`"%(k)s" % d`).
* **`"{...}".format(x)`** is the mini-language again plus `{}`/`{0}`/`{name}`
  field resolution and `!r`/`!s`/`!a` conversion — and `!a` is `ascii()`, which
  escapes every non-ASCII character, a rendering this path does not have for
  `str` either.

## What to do next, and in what order

1. **`print_call_spelling` becomes a `value_text(expr, kind)` reader that both
   `print` and `str`/`repr` ask.** One table for "what text does this value
   print as", asked by two call sites, is the shape this file already argues
   for everywhere else (`print_literal`/`print_format`/`print_kwargs` are three
   functions with one caller each precisely so the two backends cannot disagree).
   It also makes `str`/`repr` refusals *named by kind* instead of by name.
2. **Then `str(x)` for an `Int` and a `String`** — the two kinds whose rendering
   already exists — which unblocks the corpus rows that write `str(x)` where
   `print(x)` would do.
3. **Then the spec table** for `format()`, and `repr()` for the kinds in (1).
4. **Not `%` and not `.format()`** until the spec table is real: both are the
   mini-language with extra binding rules, and lowering them first would mean
   refusing the SPEC half while accepting the CALL half, which is how
   `str(1)` reads today — a refusal with no diagnosis.
5. **`!a`/`ascii()` is a separate piece of work** and should be refused by name
   rather than approximated by `%s`: it is not "the same text with escapes", it
   is a different rendering for every non-ASCII character.

## Is any of these a wrong answer rather than a refusal?

Measured, because "it is refused" and "it quietly printed 1" are different
failures and the second is this project's cardinal sin:

| source | this path, both arches | CPython |
|---|---|---|
| `print(str(1))` | refused (`printf_text_conversion_refusal`) | `1` |
| `s = str(5)` then `print(s)` | **refused**, by `string_method`-the-same-chain: "…It used to pass the value through unchanged, which is a number where every later step expects a pointer: `len(str(n))` with n = 10 built, ran and died of SIGSEGV…" | `5` |
| `r = repr("a")` then `print(r)` | refused (the `repr` link-audit refusal) | `'a'` |

So **all five are refusals and none is a wrong answer**, which is the right
shape for this document to be in: the fix here is a feature, not a repair. The
`str(5)` row's refusal is worth reading, though, because it is the best
diagnosis any of the five gets and it is a *hazard* report rather than a
diagnosis of the absence: it says what used to go wrong and not that `str` has
no lowering. Making it say the second thing is step 1 above.