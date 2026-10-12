# LEXER: `\uXXXX`, `\UXXXXXXXX`, `\N{…}` and octal escapes are not decoded, by any engine

**Area:** the front end — `fire_compiler.py`'s `decode_c_escapes`, which is the
tree's ONE decoder and which the interpreter, the compiled path and both formal
backends all go through.
**Status:** OPEN, measured 2026-10-04 on `work/formal26-unicode` at `2da07408`,
on this repository's own toolchain (`/opt/homebrew/bin/python3` 3.14.7,
Apple clang, `formal` arm64 + x86-64). Not fixed here: it is a front-end
question shared by three engines, not a formal-backend divergence, and the
string-encoding work this branch did is downstream of it.

## 1. What was run

```console
$ cat .tmp/uni/esc3.mojo
def main(n):
    printf("u=%d U=%d N=%d x=%d t=%d o=%d r=%d\n",
           len("\u00e9"), len("\U0001F600"), len("\N{LATIN SMALL LETTER E WITH ACUTE}"),
           len("\x41"), len("\t"), len("\101"), len("é"))
    return 0
$ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
      --backend=$a -o esc3.$a esc3.mojo >/dev/null && ./esc3.$a; done
arm64: u=6 U=10 N=35 x=1 t=1 o=4 r=1
x86_64: u=6 U=10 N=35 x=1 t=1 o=4 r=1
$ python3 fire.py build -o esc3.g esc3.mojo >/dev/null && ./esc3.g    # compiled
u=6 U=10 N=35 x=1 t=1 o=4 r=2
$ printf '%s\n' 'print(len("\u00e9"), len("\U0001F600"),
      len("\N{LATIN SMALL LETTER E WITH ACUTE}"),
      len("\x41"), len("\t"), len("\101"), len("é"))' > esc4.py
$ python3 fire.py run esc4.py
6 10 35 1 1 4 1
```

and the same seven spellings under `python3` itself:

```
"\u00e9"                            len=1
"\u00e9"                            len=6
"\U0001F600"                                  len=10
"\N{LATIN SMALL LETTER E WITH ACUTE}"           len=35
"\x41"                                        len=4
"\t"                                          len=2
"\101"                                        len=4
```

## 2. The measurement

One column per engine, and the engines AGREE with each other and disagree with
CPython in the same four places:

| spelling in the source | CPython `len` | interpreter | compiled | formal arm64 | formal x86-64 |
|---|---|---|---|---|---|
| `"é"` (the CHARACTER) | 1 | 1 | **2** | 1 | 1 |
| `"\x41"` | 1 | 1 | 1 | 1 | 1 |
| `"\t"` | 1 | 1 | 1 | 1 | 1 |
| `"\u00e9"` | **1** | **6** | **6** | **6** | **6** |
| `"\U0001F600"` | **1** | **10** | **10** | **10** | **10** |
| `"\N{LATIN SMALL LETTER E WITH ACUTE}"` | **1** | **35** | **35** | **35** | **35** |
| `"\101"` | **1** | **4** | **4** | **4** | **4** |

**Four escapes are wrong and three are right**, and the three that are right are
right for two different reasons worth keeping apart:

* `\xHH` and the C simple escapes (`\n \t \r \\ \" \' \0 \a \b \f \v`) — these
  are in `decode_c_escapes`'s table, so they are decoded, and the string that
  reaches the image is the right one. `\0` alone is also right, and only because
  the table maps `'0'` to `'\0'`.
* `\101` is wrong **because of that same `'0'` entry**, and it is the row that
  makes it a table problem rather than a missing one: the decoder sees `\0`,
  emits a NUL, and then `101` is ordinary text. So `"A"` is a
  four-character string whose first character is NUL. A bare `\0` and a
  three-digit octal escape are the same two characters of input and only one of
  them is an escape, so any fix has to consume the whole octal run — which is
  also why the fix cannot be "add `u` to the table".

## 3. Why this is not a formal-backend bug and is still worth a doc

**It is one decoder and four engines read it.** `fire_compiler.decode_c_escapes`
is the tree's single escape decoder by design — `decoded_literal`'s own docstring
says consolidating it "would otherwise have introduced that divergence in all
three engines at once", and the rightness of that consolidation is not in
question. What the table holds is the whole defect: `\u`, `\U`, `\N{…}` and a
multi-digit octal run are absent from it, and an absent escape is deliberately
passed through (the docstring says so: *"\d" is a backslash and a d, which is
CPython's own behaviour*).

**That last clause is the sharp edge.** For `"a\qb"` CPython keeps the
backslash and so does this tree, and that is right. For `"\u00e9"` CPython does
NOT keep it — it is a named escape, and this tree cannot tell a named escape
from an unknown one because it has no list of them. So "an unknown escape keeps
its backslash" and "a KNOWN escape is missing" are the same behaviour here and
opposite behaviours in CPython, and the second one is a wrong answer with no
diagnostic: the program runs, exits 0, and prints a six-character string where
the source wrote one.

**The compiled path's `r=2` is a different defect and is recorded here only so
the table above is not misread.** `len("é")` through `fire.py build` answers 2 —
the BYTE count — where the formal backends answer 1. That is
`mojo/backend_gimple`'s string length being a `strlen` with no encoding layer,
which is the same class as what `work/formal26-unicode` fixed for the two formal
backends and is NOT fixed there: that work's contract is the formal backends
(`doc/ABI.md` §"Library container types" records the `String` → `char *` row for
both). Whoever owns the compiled path's string model owns that row.

## 4. What is already true because of `work/formal26-unicode`, and why it matters here

**The formal backends' encoding block makes the FIX for this a one-liner, and
they are the only two engines where that is true.** With the decoder corrected,
`len("\u00e9")` is 1 on arm64 and x86-64 with no further work, because
`formal/model.py`'s TEXT ENCODING block folds `len()` of a string LITERAL from
its decoded text — so the character count follows the text automatically. On the
interpreter and the compiled path the same decoder change is necessary but not
sufficient: each has its own `len` over a `str`, and the compiled path's is a
`strlen` in bytes.

That ordering is the useful fact for whoever takes this, and it is why the two
rows that would otherwise look like a contradiction are not one:

| spelling | what a decoder fix alone gives | what else is needed |
|---|---|---|
| `len("\u00e9")` | arm64 1, x86-64 1 — nothing else | the interpreter's `len` is already a `str` `len`; the compiled path's is a byte count |
| `printf("[%s]", "\u00e9")` | the right BYTES on every engine | nothing — a `%s` copies bytes, which is what `sys.stdout` does |

## 5. The next step, exactly

1. **`decode_c_escapes`: add the three named escapes and fix the octal run.**
   `\uXXXX` (exactly four hex digits), `\UXXXXXXXX` (exactly eight),
   `\N{NAME}` (the braced form, through `unicodedata.lookup` — CPython raises
   `KeyError` for an unknown name, and a decoder that returned something else
   would be a second wrong answer), and an octal run of one to three digits
   after `\`. The digit-count rules matter and are what `\xHH` already gets right
   by refusing a short one: CPython's `"\x41"` is `A` and `"\x4"` is a literal
   `\x4`.
2. **Keep the permissive branch for everything else.** `\q`, `\d` and a trailing
   lone backslash stay verbatim; that is CPython's behaviour and
   `test_string_literal_lexing.py`'s table already asserts it for the escapes it
   covers.
3. **A REGRESSION row per escape and per engine**, and the oracle is `python3`
   itself rather than a constant — the same discipline `test_formal_unicode.py`
   uses, and for the same reason: these are numbers a person transcribing them
   gets wrong by one digit, and `len("\N{LATIN…}")` is 35.
4. **The formal rows belong in `test_formal_unicode.py`** and are one line each
   once the decoder is fixed, because the fold already reads the decoded text.
   The table there deliberately spells its astral rows as the CHARACTER rather
   than as `\U0001F600` for exactly this reason, and says so.