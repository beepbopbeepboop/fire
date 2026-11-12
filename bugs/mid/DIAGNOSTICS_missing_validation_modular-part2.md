# DIAGNOSTICS_missing_validation_modular part 2: adjacent string-literal message continuation

Part 2 of the split of `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`.
Plan: `docs/diagnostics-missing-validation-plan.md` §11 names
`comptime_assert.mojo` as a formatting comparison; the long-message case is
also a real missing diagnostic detail, because the message is truncated.

## Why this part

Modular's `test/mojo-parser/statements/comptime_assert.mojo` has:

```mojo
def test_assert_with_long_message[cond: Bool]():
    comptime assert cond, "custom error message"
                          " with long message "
                          "and more"
```

The three literals are one message. The integration test
`test/mojo-integration/comptime_assert.mojo` is the same behaviour through the
real compiler (`expected positive number, got -2`).

This tree keeps only the first literal. Measured 2026-11-10:

```python
ast = fire_compiler.Parser(fire_compiler.py_tokenize(src)).parse_module()
# AssertStmt.msg == StringLiteral('custom error message')
# then ExprStmt(StringLiteral(' with long message '))
# then ExprStmt(StringLiteral('and more'))
```

Same-line adjacent literals already work (`"a" "b"` -> `"ab"`), and so does
the parenthesised form, through `Parser._merge_string_literals`. The gap is
only the bare continuation line: `py_tokenize` emits a `NEWLINE` at the end of
the first literal line, and `prev_ended_string` suppresses `INDENT`/`DEDENT`
for the next line but not that `NEWLINE`, so the parser never sees two
adjacent `STRING` tokens.

## Scope

`fire_compiler.py::py_tokenize` (phase 2, around the `prev_ended_string`
handling at lines 2670-2795).

- When the previous physical line ended with a `STRING` token and the current
  line's first significant token is another string literal, suppress the
  `NEWLINE` that ended the previous line so the parser's existing
  `_merge_string_literals` folds the run. Do this only when
  `paren_depth == 0`, the current line really starts with a string token
  (including the `f`/`r`/`b`/`t` prefixes), and the previous line is not a
  blank/comment line (the existing code already clears `prev_ended_string`
  there).
- Do not merge when the next line starts with anything else. In particular a
  dedented `fn`/`def`/`main` after a line ending in a string must keep its
  `DEDENT` and `NEWLINE` exactly as now.
- Preserve the existing `_merge_string_literals` semantics for plain, raw,
  bytes, f- and t-strings; this part adds no second concatenation rule.
- A `comptime assert` message is the motivating site, but the fix belongs in
  the tokenizer/parser, not in `execute_AssertStmt` or a message-only special
  case.

If the tokenizer change proves too broad, the fallback is to parse the
`comptime assert` / `assert` message inside an implicit bracket context (the
same way a call argument list suppresses `NEWLINE`), reusing
`_merge_string_literals`; do not add a third string-joining implementation.

## Acceptance

Add to `test_comptime_assert_diagnostic.py`:

```python
def test_comptime_assert_adjacent_literal_message():
    src = ('def use_positive_int[x: Int]():\n'
           '    comptime assert x > 0, "custom error message"\n'
           '                          " with long message "\n'
           '                          "and more"\n'
           'def main():\n'
           '    use_positive_int[0]()\n')
    # compile_to_gimple(..., do_imports=True, filename=<real temp file>)
    # must raise RuntimeError containing
    #   `custom error message with long message and more`
```

Also add the modular integration shape (same message, `x = -2`) and a control
that a blank line between two string literals is still not merged. The
existing same-line and parenthesised cases in the file must keep passing.

Run only:

    python3 test_comptime_assert_diagnostic.py

No suite registration and no whole-closure compile.

## Status
- **Open.**
