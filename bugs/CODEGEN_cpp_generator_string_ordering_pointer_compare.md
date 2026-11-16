# CODEGEN: `<`/`>`/`<=`/`>=` on strings in a cpp generator body compares pointers

## Status 2026-11-14 — measured, not fixed (found while fixing string equality)

`==`/`!=` on two `char *` operands in a cpp C++20-coroutine body was pointer
identity; it now lowers to `mojo_cstr_cmp` / `mojo_cstr_cmp_word` by content
(commit dee41cad3, `cpp_core._cpp_str_compare`, regression
`test_link_mode.test_generator_string_equality_compares_content`).

The ORDERING comparisons were deliberately left alone in that fix:
`_cpp_str_compare` returns `None` for `<`, `<=`, `>`, `>=`, so they still emit
a raw C++ comparison of the two `char *` values — i.e. their heap/static
addresses, not their lexicographic order. Python's `str` ordering is
lexicographic, so a compiled generator's `if a < b:` can disagree with
CPython non-deterministically (it depends on allocation order).

## What to run

A link-mode program whose generator takes the cpp path (`import csv` plus
`_get_reader=csv.reader` as a default makes it eligible — same fixture as
`test_generator_string_equality_compares_content`) and does:

```python
def order(a, b, *, sep=",", _get_reader=csv.reader):
    if a < b:
        yield "LT"
    else:
        yield "GE"
```

`list(order("abc", "abd"))` must print `['LT']` the way CPython does.

## Expected

Lexicographic order, exactly CPython's `str` ordering.

## Exact next step

Extend `cpp_core._cpp_str_compare` (`mojo/backend_gimple/cpp_core.py`) to the
four ordering operators. The runtime comparison already exists and returns
`strcmp`'s sign convention: `mojo_cstr_cmp(char *, char *)` and
`mojo_cstr_cmp_word(char *, int64_t)` (`runtime/fire_runtime.c`), the same
pair the `==`/`!=` arm uses. Emit `< 0` / `<= 0` / `> 0` / `>= 0` and add the
regression next to `test_generator_string_equality_compares_content` in
`test_link_mode.py`. Keep the non-string fallthrough untouched: `_cpp_str_compare`
already returns `None` unless one side is statically `char *`.
