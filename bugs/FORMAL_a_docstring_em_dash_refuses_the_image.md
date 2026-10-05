# FORMAL_a_docstring_em_dash_refuses_the_image: `import os` is refused because `_syscalls.mojo`'s DOCSTRINGS use em-dashes, and 6 of 7 `test_formal_os.py` groups are red

**Area:** FORMAL (both backends; the refusal is asked from
`formal/model.py::string_element_refusal` and decided by
`formal/model.py::non_ascii_strings_in`, which both backends share)
· **Status:** OPEN, measured 2026-10-05 on `master` at `77b24183` **and on
master** — `git show master:formal/hostmods/os/_syscalls.mojo | grep -c "—"`
is **79** and `git show master:formal/model.py` has
`non_ascii_strings_in`, so nothing here is a local branch's state.
· **Found by:** `test_formal_interop.py`'s corpus having to be all-ASCII, and
then by running the formal suites it is registered beside.

**A DOCSTRING is a `StringLiteral` expression statement, so prose is a string
literal, and this backend's non-ASCII rule is per-UNIT rather than per-VALUE.**
`model.non_ascii_strings_in` walks the AST for `F.StringLiteral` nodes; the
module docstring is one, so `"""A helper — …"""` makes the unit "hold a string
whose bytes are not one byte per character", and then EVERY string subscript in
the image is refused by name.

**Nine lines, and the only non-ASCII character in them is in the docstring:**

```console
$ cat .tmp/ds/min1.mojo
"""A helper — whose module docstring uses an em-dash, which is PROSE."""


def head(s: String) -> Int:
  return s[0]


def main(n: Int):
  printf("%d", head("abc"))

$ python3 fire.py build --formal --no-prove -o m1 .tmp/ds/min1.mojo
build: s[0] is refused on a string whose text is not ASCII. …          [exit 1]

$ sed 's/—/--/' min1.mojo > min2.mojo && python3 fire.py build --formal \
      --no-prove -o m2 min2.mojo && ./m2
Built: m2  [arm64/macho]
97
```

`97` is `'a'`, which is what CPython prints. One character of PROSE, in a
comment-shaped construct that is never read as a value.

## 1. What this costs, measured

**Every formal program that imports a host module is refused.** All thirty-six
files in `formal/hostmods/` have non-ASCII docstrings, so every image they reach
is a non-ASCII image:

```console
$ printf 'import os\n\n\ndef main(n: Int):\n  printf("%%s", os.getcwd())\n' > uos.mojo
$ python3 fire.py build --formal --no-prove -o o1 uos.mojo
build: uos.mojo imports 'os', which cannot be built either: _syscalls.mojo:
d[i] is refused on a string whose text is not ASCII. … This image holds a
string literal that is not ASCII, so some string in it can have a character
`base + 1` walks into.
```

**The refusal lands in the one place a byte subscript is exactly right.** The
`d[i]` is inside `formal/hostmods/os/_syscalls.mojo`'s own `readdir` walk, and
the refusal's own last sentence recommends *"read the byte deliberately, with a
`Pointer[UInt8]` subscript and the arithmetic written out, which is what a
program that wants bytes wants"* — which is what that code is doing.

Suites red from this, measured 2026-10-05:

| suite | measured |
|---|---|
| `test_formal_os.py` | **1 of 7 groups pass** |
| `test_formal_imports.py` | 69 pass / 3 FAIL, all three refusing `shlex` or `os` |
| `test_formal_libc_symbol.py` | **2 of 11 cases pass**; `retvalue` fails on arm64 AND x86_64 with this refusal |
| `test_formal_doc_truth.py` | 8 unrelated FAILs (FORMAL.md's entry-point counts) |

## 2. Why it is a bug and not the rule working

`doc/ABI.md`'s TEXT ENCODING section states the rule as *"the formal backends
refuse those operations by name **in any image that contains a non-ASCII string
literal**"*, and its soundness argument is that *"every string value is a
literal's interned bytes or an interior pointer into them"*. That argument is
about **VALUES**, and it is the right one. A docstring is not a value:

* it is an expression **statement** with no consumer — nothing reads it, nothing
  prints it, nothing can subscript it;
* it is not interned into the string pool in any way a subscript could reach;
* and the image-level accumulation (`publish_non_ascii_strings`, which
  deliberately unions over every module in the image, for a good measured
  reason) inherits the over-approximation from the per-module scan.

So the fix belongs at `non_ascii_strings_in`: **a bare string expression
statement is a docstring and not a value**, and one that is the module's or a
function's first statement is exactly that. Two spellings of the same fix, and
they differ in blast radius:

* **Narrow, and enough.** Exclude a `StringLiteral` whose parent statement is a
  bare `ExprStmt` **and** which is the first statement of its module or function.
  That is precisely the docstring position and nothing else.
* **Wide, and it is a separate decision.** Exclude every bare string expression
  statement. Also sound (a bare string is a no-op), but it changes what an
  f-string-adjacent construct sees, so it wants its own measurement.

Note that the narrow rule does NOT make the underlying rule wrong: a real
non-ASCII literal in a function BODY still refuses the image, which is the
measured, documented behaviour and is correct.

## 3. The exact next step

1. `formal/model.py::non_ascii_strings_in` takes the statements; the walk already
   visits each node, so excluding the docstring POSITION needs the statement a
   node sits in. Either pass the owning statement down as it walks (it already
   pops them) or filter the returned texts against a precomputed set of
   docstring positions. **Whichever, put it in `model.py` and not in
   `fire_compiler.py`**: the parser cannot know a string is a docstring without
   the statement list, and the compiled path must not acquire this rule.
2. Add the case to `test_formal_unicode.py`, which is where the 80 measured rows
   of this rule live: a module docstring with a non-ASCII character plus one
   `s[0]` must BUILD and answer CPython, and a real non-ASCII literal in a body
   must still refuse. Both halves, because a fix that only relaxes the rule
   would be indistinguishable from deleting it.
3. Re-run the four suites in the table above; the expected delta is
   `test_formal_os.py` 7/7, `test_formal_imports.py` 72/72,
   `test_formal_libc_symbol.py` 11/11, and nothing else moving — `import os`
   becoming buildable can only ADD cases, and if any suite goes red from it that
   is a real second-order finding worth its own row here.

## 4. What is NOT wrong here, so the next person does not go looking

* **`len`/`find`/indexing being refused on non-ASCII text is CORRECT** and is
  `doc/ABI.md`'s documented rule; §2 of this doc does not propose to relax it.
* **The image-level accumulation is CORRECT** (`publish_non_ascii_strings`
  documents a measured two-module case where a replace gave `len("héllo") == 6`).
* **The escape spellings not being decoded** is a separate, already-filed gap:
  `bugs/LEXER_unicode_escapes_are_not_decoded.md`.