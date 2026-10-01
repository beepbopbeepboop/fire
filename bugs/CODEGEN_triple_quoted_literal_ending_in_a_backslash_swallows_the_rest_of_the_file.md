# CODEGEN: a triple-quoted string literal holding a backslash swallows the rest of the file

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

## Why it is inconsistent with the rest of the language here

Everything else about literals on this path is byte-exact: the value of a
triple-quoted literal is its **content** (the delimiters are syntax, so
`strlen("""aaaaaaaa""")` is 8, measured), and a backslash is stored **as
written** (`strlen("""a\nb""")` is 4, measured). So a caller can put a
backslash-heavy source file into a literal and get it back byte for byte — and
then a *lexical* rule that CPython does not have, and that Python's own
tokenizer resolves the other way, decides where the literal ends.

CPython's rule, for the record, is that a backslash in a non-raw string escapes
whatever follows it and a backslash in a raw string does not, but in BOTH cases
the escape only matters for a quote: `r"\""` is a bytes literal containing a
quote, and `"\""` is a string containing a quote. Neither ends the literal at
the escaped quote. That is the behaviour to implement.

## What a fix has to do

Pick one rule and apply it in the scanner: an escape consumes the next byte
**only** when that byte is a backslash or the literal's quote character;
otherwise the backslash is an ordinary byte. That is CPython's rule, it makes
the three measured rows above agree, and it removes the interaction entirely —
a literal then cannot contain a byte sequence that changes where it ends.

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
