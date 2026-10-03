# A `;` or a `|` in a help string truncates it, because the spec is a `;`-separated record string

**Status: OPEN, measured, not fixed — the representation is the module's ABI and
every caller and every reader of it would move together.** Found on 2026-10-03
while implementing `bugs/FORMAL_argparse_help_wrapping_not_implemented.md`'s
wrapping, whose test corpus could not use a semicolon in a help string.

## What I ran

```console
$ python3 test_formal_argparse.py
  FAIL  the parse matches CPython, case for case
        1 of 66 cases differ from CPython:
  wrapentry[0] argv='--help': stdout differs.
  image:   '...  -j, --jobs JOBS     the number of workers to run in parallel\n...'
  cpython: '...  -j, --jobs JOBS     the number of workers to run in parallel, and more than\n...'
```

with the declaration

```python
(["-j", "--jobs"], dict(type=int, default=8,
                        help="the number of workers to run in parallel; more than the core count is usually slower"))
```

## What it is

The spec a caller passes to `argparse.parse` is one string: records separated
by `;`, fields within a record by `|` (`formal/hostmods/argparse.mojo`'s `_rec`,
`_nrec`, `_fld`, `_ftext`). `F_HELP` is the last field of a record, and `_ftext`
reads it as `str_prefix(p, strcspn(p, "|;"))` — up to the next `|` or `;`.

So a help string containing either byte ends there, and everything after it in
the same string is read as **more records**: the `;` case produced two EMPTY
`positional arguments:` entries in the help listing, because the tail of the help
text parsed as a record with no name and no metavar. CPython prints the whole
string. A `|` truncates the help text at the same place, more quietly, with no
extra records.

## Why it is not a one-character fix

Escaping is the obvious answer and it is an ABI change: `_fld`/`_ftext` would
have to unescape, and every WRITER of a spec — the test's `record_for`, and every
program in the corpus that builds one by hand (and any `formal/hostmods/` module
that constructs a spec) — would have to escape, or a spec written the old way
would read differently. A record string that is also a positional-argument ABI is
not a place to change the meaning of a byte quietly.

Two shapes that would both work, and neither is free:

1. **Escape in the field encoding** (`\;` for a semicolon, `\|` for a bar), with
   `_fld` unescaping. Every existing spec keeps working UNCHANGED, because no
   existing spec contains a backslash in a field — that has to be asserted, not
   assumed, and `test_formal_argparse.py`'s export/census tests are where it
   belongs. The cost is a second reader in `_fld` and a rule for which bytes are
   escapable.
2. **Length-prefixed fields**, which is what the rest of this module's internals
   do (the `pat` buffer, the `seen` scratch) and which removes the question
   entirely. It changes every writer, so it is a migration rather than a patch.

Option 1 is the smaller change and is what I would do; the reason it is not done
here is that it is a different subject from the wrapping this session landed, and
a change to the spec's meaning belongs in a commit that says so.

## The exact next step

1. Pick option 1 and state the invariant it needs: **no field of an existing
   spec contains a backslash**, checked by a test over the corpus rather than
   asserted here.
2. `_fld` unescapes while scanning for the separator — which means it cannot use
   `strcspn` for a field that may contain an escaped `|`, so the scan becomes a
   loop. Measure the cost: `_fld` is called for every field of every record on
   every parse.
3. `record_for` in `test_formal_argparse.py` escapes, and a case with `;`, `|`
   and `\\` in one help string goes in the corpus so the round trip is compared
   against CPython's rather than against itself.
