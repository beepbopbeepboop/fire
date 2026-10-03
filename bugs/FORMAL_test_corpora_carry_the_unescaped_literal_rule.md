# FORMAL_test_corpora_carry_the_unescaped_literal_rule: eight green test files explain their corpus with a limitation that was removed

**Status: OPEN, and deliberately LOW priority — nothing here is red and nothing
here is wrong except the sentence that explains the corpus.** Filed while
closing `bugs/FORMAL_sys_mojos_escape_note_is_stale.md`, whose remaining item was
this consequence-check.

**Class:** documentation. One of the nine sites is already fixed (the last row of
the table, done in the same commit that filed this). **Effect:** a maintainer reading any of these comments
concludes a formal image cannot hold a real newline in a string literal, which
has been false since `9023031b`, and either refuses to simplify the corpus or
writes new code around a limitation that does not exist.

## The measurement, once

A string literal is DECODED on this path, as CPython decodes it — in a program
and, since the check that mattered, **inside a module dylib** too, on both
architectures. `formal/hostmods/os/__init__.mojo`'s `linesep` and
`formal/hostmods/ast.mojo`'s `_quotes()` are now literals because of it, and
`test_formal_sys.py::test_a_literal_inside_a_module_is_decoded_too` is the test
that keeps it true (three decoded byte counts through a dylib boundary).

## The sites

Each of these says some form of "a Mojo string literal's `\n` is NOT unescaped
on this path, so a formal image prints the two characters `\` and `n`", and each
then picks a record separator that is correct either way — `@@` in most, `~xHH`
in `test_formal_json.py`'s `mask()`:

| file | line | the corpus it explains |
|---|---|---|
| `test_formal_dylib.py` | 330 | the shared `@@` record separator every suite in this family reuses |
| `test_ast_formal.py` | 237 | the corpus it does not embed as literals (a different reason — a trailing backslash swallowing the file — is still real) |
| `test_formal_libc_symbol.py` | 71 | its own records |
| `test_formal_stat.py` | 67 | its own records |
| `test_formal_os.py` | 153, 361 | `REC`, the separator the whole `os` suite reports through |
| `test_formal_os_backing.py` | 60 | its own records |
| `test_formal_time.py` | 55 | its own records |
| `test_formal_hashlib.py` | 92 | its own records |
| `test_formal_run.py` | — | **done**: its comment described a leading run of "all three of tab/space" on a case whose operand is three SPACES, and explained a `\t` that is not in it — a leftover from a case that has since moved. Corrected in place; the tab case is `str_lstrip_all_whitespace`, whose comment already carried the right explanation |
| `test_formal_json.py` | `mask()` | `~xHH` for every awkward byte in a JSON document |

## Why they were written that way, and what changing them costs

The spellings are right under BOTH answers, which is exactly what made them
worth having while the limitation was live, and they are still right now. So:

* **the fix is the sentence, not the corpus.** Each comment can say "this
  separator is `@@` rather than a newline because a suite that reads these
  records must not have to know whether the image decoded the literal", which is
  true forever, instead of naming a decoder that has since changed.
* **changing the corpus to real escapes is a separate, optional decision**, and
  it has a real cost: eight suites that are green would each have to be re-run on
  both architectures.
* what a rewrite would BUY is that the corpora would exercise the decoder
  through the same path a reader's program does. That is a genuine gain and it
  is not urgent.

## The exact next step, per site

Replace the false clause with the durable one, and leave the corpus alone:

> A record separator this suite can read back without asking whether the image
> decoded a literal: `@@`, two bytes a real newline cannot collide with.

For `test_formal_json.py`'s `mask()`, the durable reason is the same — every
awkward byte is escaped so the expected document and the produced one differ
only in the byte under test — and `~xHH` is fine to keep.

Two sites need a reader rather than a substitution, because their corpora are
pinned to something else as well:

* `test_ast_formal.py`'s, whose real reason (a trailing backslash swallowing the
  rest of the file, `bugs/CODEGEN_triple_quoted_literal_ending_in_a_backslash_
  swallows_the_rest_of_the_file.md`) is UNCHANGED by the decoder and must stay in
  the comment. Replace only the escape clause.
* `test_formal_dylib.py`'s, which is the convention every suite in this family
  reuses, so the durable wording matters more here than anywhere else: a reader
  in one of the other eight suites is following this comment.