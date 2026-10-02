# FORMAL_string_literal_escape_is_not_decoded: `"a\nb"` is FOUR characters on the formal path

**Found 2026-09-30, while looking for the next step after the MLIR pre-emption in
`construct:comptime-mlir-and-inline-asm-remainder`. It is a WRONG ANSWER, not a
refusal, and it is not mine** — the string's content is the value-model lane's
(`construct:formal-value-model-gaps`, and `FORMAL_string_value_model.md` is that
lane's document). Filed with the measurement rather than fixed, per the rule that
a neighbouring gap gets a doc instead of a widened claim.

## What was run

```
$ cat .tmp/esc/h.mojo
def main() -> Int32:
    var a = "a\nb"
    var n = len(a)
    print("len=", n)
    return n
```

| engine | command | output |
|---|---|---|
| CPython | `python3 -c '…'` on the same text | `len= 3`, exit 3 |
| this repo's interpreter | `python3 fire.py run .tmp/esc/f.mojo` | `a`⏎`b` — real newlines |
| this repo's compiled path | `python3 fire.py build .tmp/esc/g2.mojo` | `a`⏎`b` then `3` — real newlines |
| **formal arm64** | `python3 fire.py build --formal --no-prove --backend=arm64` | `len= 4`, exit 4 |
| **formal x86-64** | same, `--backend=x86_64` | builds; same defect |

And the bytes, with `print("a\nb")` and `printf("c\nd\n")`:

```
$ .tmp/esc/e | od -c
0000000    a   \   n   b  \n   c   \   n   d  \n   x   \   n   y  \n
0000020    t   a   b   :   \   t   h   e   r   e  \n  \n
```

Every backslash in every string literal reaches the image as TWO characters. So
`len("a\nb")` is 4, `"\t"` is 2 (and `FORMAL_string_value_model.md`'s own case
`len("\t") == 2` at `test_formal_run.py:1472` is asserting the bug), and a
program that prints a line ending prints a literal `\n`.

## Why the formal path is the odd one out

The escape is not decoded by the parser, and that is deliberate and shared:
`fire_compiler.py`'s `_strip_string_prefix_and_quotes` strips a literal's outer
quotes and leaves the body as raw source text, because the compiled path *hands
the text to a C compiler*, which decodes it. `myinterpreter.py`'s
`_decode_c_escapes` exists for exactly this reason and says so:

> The parser strips a string literal's outer quotes but leaves escape sequences
> as raw two-character runs … so `"ab\ncd"` reached here as the 6-char text
> `ab\ncd` … while `mojo build` reported 5 (the C compiler decodes the escape in
> the emitted C literal). This realigns the two.

The formal backend is the one engine in this repository that does **not** hand
the text to a C compiler. It interns the string itself, in Python:

```python
# formal/arm64_codegen.py:2668, and the same function in x86_64_codegen.py
def _intern_string(self, s: str) -> str:
    label = f"str_{self._str_counter}"
    self._str_counter += 1
    self._strings.append((label, s.encode() + b"\x00"))
```

`s.encode()` encodes the RAW text, so the bytes in `__TEXT,__text` carry the
backslash. `FORMAL_string_value_model.md` has the image to prove it and does not
notice, because the one literal in its dump that has an escape is a `printf`
format: `b'hello\x00len=%d\\n\x00'` — that `\\n` is the bug, read as part of the
example.

So this is not a value-model question at all. It is one missing call, in the
one place where the "let C decode it" assumption does not hold.

## How much it reaches

Over `../modular/mojo/stdlib` (664 files), by the grep stated in
`tools/`-free terms — `"…"` where the body contains a `\n \t \r \\ \0 \a \b \f
\v \" \'`:

| | |
|---|---|
| `.mojo` files with a C-style escape inside a double-quoted string | **50** |
| such literals | **468** |
| of those, the escape is directly inside a `print`/`printf` argument | 2 |

The last row is the reason this has survived: almost none of the 468 are in a
printed literal, so no `test_formal_run.py` case that *executes* an image shows
it by accident — they all use `printf("%d\n", …)` whose format the backend
passes through, and only three expectations in the whole suite assert the wrong
spelling:

- `test_formal_run.py:1318` and `:1333` — `"v = %d\\n 7"`
- `test_formal_run.py:1374` — `"len=%d\\n 0"`

**Those three are expectations, not behaviour, and a fix must rewrite them in
the same commit.** A change that decoded the escape correctly would otherwise
look like three regressions.

## What is in the suite that will have to change with it

One case asserts this behaviour **by name and with a comment giving a reason**,
and a fixer has to confront it rather than route around it —
`test_formal_run.py:1470`, `str_membership_on_the_unescaped_representation`:

> The unescaping boundary, and it is the reason this case exists at all: string
> literals are stored UNESCAPED on this path, so `"\t"` is a BACKSLASH and a `t`
> — two characters — and a backslash is not a tab.

`len("\t") == 2` is one of its four assertions, so the case's expected `r=5`
becomes `r=1` under the fix. The comment's claim is false about the language and
false about this repository's other two engines — `fire.py run` and `fire.py
build` both print a tab there, as measured above — and it is contradicted in the
same tree by `myinterpreter.py`'s `_decode_c_escapes`, whose stated purpose is to
make the interpreter MATCH a path that decodes. It should be rewritten as what
it is (the boundary is the parser, and both consumers decode), not deleted, and
its four assertions are worth keeping: they are four different ways to get escape
handling wrong and the oracle for each is `python3`.

Three EXPECTATIONS elsewhere in the suite bake in the literal-backslash spelling
and must be rewritten in the same commit — a correct fix would otherwise look
like three regressions:

- `test_formal_run.py:1318` and `:1333` — `"v = %d\\n 7"`
- `test_formal_run.py:1374` — `"len=%d\\n 0"`

## The exact next step

1. **One decoder, in one place.** `myinterpreter.py:4741`'s `_decode_c_escapes`
   already implements the table (`\n \t \r \\ \" \' \0 \a \b \f \v`, plus `\xHH`,
   unknown escapes passed through) and its docstring already names
   `gimple_codegen._c_escape` as the same set. Move it to `fire_compiler.py`
   beside `_strip_string_prefix_and_quotes` — the module CLAUDE.md makes the
   single source of truth — and have `myinterpreter`, `gimple_codegen` and the
   formal backends all call it. **Do not add a second copy in `formal/`**: three
   copies of an escape table is three chances to disagree, and the disagreement
   is invisible in every test that does not print a newline.
2. **Call it from the interning path**, which is the one place that needs it:
   `formal/arm64_codegen.py:_intern_string` and its x86-64 twin. Decoding
   inside `_intern_string` rather than at every call site is the whole of the
   fix — every string on this path goes through it, and interning by content
   then gets the right key for free (two literals that differ only in escape
   spelling become one string, which is what `==` already assumes).
3. **Check the two callers that do not intern.** `formal/model.py`'s
   `folded_literal_node` materializes a folded target-query value, and
   `_scan_value_kinds` / `_declared_kind` ask about kinds from a literal's
   `value`; none of them care today because no folded value contains a
   backslash, and none of them should have to change. State that in the commit
   rather than leaving it to be discovered.
4. **Test it the way this area tests.** A case that builds the arm64 image,
   EXECUTES it and compares against CPython for `len("a\nb")`, `len("\t")`,
   `"\t" in s` and the printed bytes of `print("a\nb")` — on **both**
   architectures for the build half.
5. **Not in scope, and worth saying so:** raw strings. `_decode_c_escapes`' own
   docstring records that `r"..."` is not preserved by any engine in this tree,
   so decoding will not make it worse; a raw string that must keep its backslash
   is a separate question about `_strip_string_prefix_and_quotes`.

## What the next reader does not have to re-derive

The three engines agree on the answer and the formal one differs; that is
measured above, not inferred. `fire.py run` and `fire.py build` were both built
and run on this tree, so "the other engines decode it" is not a quotation of
`_decode_c_escapes`' docstring — it is what they printed.