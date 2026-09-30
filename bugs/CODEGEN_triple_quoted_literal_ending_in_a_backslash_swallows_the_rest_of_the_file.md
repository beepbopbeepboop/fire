# CODEGEN: a triple-quoted string literal holding a backslash swallows the rest of the file

## Status (2026-09-30 — FIXED. The original diagnosis was wrong about the cause; the silent miscompile is closed and the class now matches CPython)

`fire_compiler.py`'s string scanner is now one function,
`_scan_string_end`, used by both the triple-quote collapse and the
ordinary-quote skip, and an unterminated literal is a **refusal**
(`SyntaxError`, CPython's own wording, with `file:line:col:`) instead of a
token whose value is the rest of the file. `test_string_literal_lexing.py`
compares 30 literals against `compile()` and requires the accept/refuse
verdict to agree on every one.

Everything below the line is the ORIGINAL report of 2026-09-29, kept as
written. **Its diagnosis and its proposed fix were both wrong**, and the
reason is worth more than the fix, so read the correction first.

---

## The correction: the escape rule was never wrong, and the fix this file asked for cannot work

The report says the lexer "honours an escape the value does not", and asks for
a different rule: *an escape consumes the next byte only when that byte is a
backslash or the literal's quote character*. Measured on this tree, that rule
is indistinguishable from the rule already in the tree **for every input that
can end a literal**, because only a backslash or a quote can be both "the byte
after a backslash" and "a delimiter". It changes what a literal's *characters*
are; it cannot change *where it ends*.

And where it ends is not a choice this front end gets to make:

```console
$ python3 -c 'compile("s = \"\"\"\\\"\"\"", "", "exec")'
SyntaxError: unterminated triple-quoted string literal (detected at line 1)
```

CPython refuses `"""\"""`. The backslash escapes the first quote of the
closing run, so the remaining two quotes cannot close the literal and the
literal runs to the end of the file. `"""a\""""b"""`, by contrast, is a
perfectly good 5-character-content literal in CPython and here alike, because
after the escaped quote there are still three quotes left to close it.

So the honest reading of the report's own reproducer is: **this front end
agreed with CPython about the boundary and then did not do anything about the
consequence.** CPython's boundary rule produces an unterminated literal, and
CPython has an answer for an unterminated literal. This path had none: the
scan loop ran off the end of the source, `end` was clamped to `n`, and a
STRING token was emitted holding every remaining line of the file. The bug is
the missing refusal, not the escape rule.

## What the silent miscompile actually was, measured

The build **succeeded**. That is the part worth recording, because it is why
this survived: `def main():` followed by `var a = <the rest of the file>` is a
syntactically complete function, so every layer above the tokenizer had nothing
to complain about.

```console
$ python3 fire.py build --formal --no-prove .tmp/lexer/frag2.py -o frag2
Built: frag2  [arm64/macho]          # exit 0, and the program prints nothing
```

Before the fix, `py_tokenize` on the reproducer produced:

```text
KW 'def' 1 0
NAME 'main' 1 4
...
STRING '"""\\"""\n    print(a)\n    print(1)\n' 2 8      ← the rest of the file
NEWLINE '' 2 0
DEDENT '' 4 0
```

After:

```console
$ python3 fire.py build --formal --no-prove .tmp/lexer/frag2.py -o frag2
build: parse error: .tmp/lexer/frag2.py:2:5: unterminated triple-quoted string literal
```

Line and column match CPython's for the same source, exactly.

## The same scan had a second, sharper face, which the report did not find

For single-quoted literals the delimiters were not swallowed — they were
**dropped**, because the ordinary-string skip simply stopped and the text was
left in the stream for the regex tokenizer, which does not match an unclosed
string. So the literal's own characters became ordinary code:

| source | parsed as (before the fix) | CPython |
|---|---|---|
| `x = "abc` | `x = abc` — a NAME | `SyntaxError` |
| `x = "abc\"` | `x = abc` | `SyntaxError` |
| `x = it's` | `x = it` **and a bare `s` statement** | `SyntaxError` |

`x = it's` is the sharpest of the three: a well-formed-looking line in a file
that is otherwise fine becomes two statements, and the second one is a bare
name that will fail (or worse, read a global) at run time. This is a *sharper*
failure than the triple-quote case, because the program's statement count
changes and the resulting diagnostics point at the wrong line.

## A third silent misparse in the same loop, found while fixing the first

The loop had no case for a **backtick** string, which is a Mojo string with no
CPython counterpart but which the rest of this front end treats as one
(`_TOKEN_RE` has a `` `[^`]*` `` arm; `_strip_inline_comment` has a matching
`in_str != '`'` special case). So a quote *inside* a backtick string was read
as a delimiter:

```python
x = `it's fine`     # parsed as x = `it's fine`   (an IdentExpr), by luck
x = `a"""b`         # the `"""` was a triple-quote OPENER: the backtick string
                    # was cut in two and the second half swallowed the rest of
                    # the file — the same failure as the reported bug
```

The first row is the one that made the new refusal unsafe to add: the
apostrophe in an English word would have been reported as an unterminated
string literal on a line with no unterminated literal on it, which is exactly
the "a message that is false about the file is worse than no message" failure
the formal backend's refusals are written to avoid. A backtick string is now
skipped as one opaque unit, to the next backtick (no backslash escape, which
is what the two existing backtick call sites already assume), and an
unterminated one is refused rather than silently reinterpreted.

## Measured: the refusal costs nothing on this repository

Every `.mojo` file in reach — 98 in this worktree plus all 664 under
`../modular/mojo/stdlib/std` — tokenizes and parses with the new code, and
**none** is refused. Measured by walking both trees and running
`py_tokenize` + `Parser.parse_module` over every file (2.7 s for all 762).
The refusal is therefore free on real source, which is the only thing that
could have made it a bad trade.

## The rest of the original report, for the record

## Status (2026-09-29 — OPEN, measured; the LEXER honours an escape the value does not)

A triple-quoted string literal whose text contains a backslash immediately
before the closing quote — or before a quote that could close it — is scanned
with escape processing, so the literal does not end where it appears to. The
text after it is swallowed into the string, and the program either fails to
parse or, worse, parses as something else.

## Reproducer

```python
def main():
    var a = """\""""
    print(a)
    print(1)
```

The literal is `"""` `\` `"""`. The lexer takes the `\"` as an escaped quote, so
the string continues past it, and `print(1)` and the rest of `main` end up
inside the string:

```text
build: parse error: .tmp/w/frag.py:4:0: Unexpected DEDENT('')
```

Measured shapes, all with `fire.py build --formal --no-prove`:

| literal text | result |
|---|---|
| `"""abc"""` | fine |
| `"""a"b"""` (one quote inside) | fine — a single `"` does not close a triple-quoted literal |
| `"""\\"""` (a backslash then the closing run) | **the rest of the file is swallowed** |
| `"""a\nb"""` (a backslash then `n`) | fine — the backslash escapes a character that is not a quote |

(The `build: parse error: ... Unexpected DEDENT` line above did not reproduce on
this tree even before the fix: with the tail absorbed into the literal the
program is `def main(): var a = <string>`, and a lone `def` with a DEDENT at
EOF is accepted. The row is kept because the *diagnosis* it was evidence for is
what turned out to be wrong, and the "or, worse, parses as something else" in
the paragraph above is what actually happens.)

## Why it is inconsistent with the rest of the language here

Everything else about literals on this path is byte-exact: the value of a
triple-quoted literal is its **content** (the delimiters are syntax, so
`strlen("""aaaaaaaa""")` is 8, measured), and a backslash is stored **as
written** (`strlen("""a\nb""")` is 4, measured). So a caller can put a
backslash-heavy source file into a literal and get it back byte for byte — and
then a *lexical* rule that CPython does not have, and that Python's own
tokenizer resolves the other way, decides where the literal ends.

**Correction:** the "lexical rule that CPython does not have" is not there.
`test_string_literal_lexing.py` measures all 30 literals against `compile()`:
the accept/refuse verdict now agrees on every one, and it agreed on every one
of the *accepted* ones before the fix too. The byte-exact **value** rule is a
real and deliberate divergence from CPython and is asserted separately in that
test, because it is a different question from where the literal ends.

## Measured impact on this repository

`test_ast_formal.py` embeds a corpus of Python sources as string literals, and a
corpus source is full of backslashes (regexes, `"\n"`, Windows paths), so the
test does not embed them as literals: it splits each source at every `"""` and
emits the pieces as a chain of `join2` calls, with every backslash and every
trailing quote character built at RUN time by a `CH(byte, n)` helper. That is
the shape a caller on this target has to use, and it is why the test carries
those helpers rather than a `mojo_string` of the kind the rest of the tree
uses. See also the same class of problem in
`formal/hostmods/ast.mojo`'s module docstring, where a literal is not an option
at all because a source file contains three double quotes.
