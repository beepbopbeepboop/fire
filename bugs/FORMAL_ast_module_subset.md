# FORMAL: `ast` is a tokenizer and a lexical validator, not a tree

## Status (2026-09-29 — the subset is DELIVERED and MEASURED; the gaps below are the design, not a to-do)

`formal/hostmods/ast.mojo` exists, and `formal/imports.py` no longer lists
`ast` as `HOST_MODELLED`. What it provides is the tokenizer
(`tokenize`, `tokenize_from`, `token_bound`, `token_name`) and a lexical and
block-structure validator (`parse`, `parse_reason`) whose answers are compared
against CPython's own `tokenize` and `compile` by `test_ast_formal.py`, which
builds the module into an arm64 image and RUNS it.

**It does not build a tree, and that is not a gap that can be closed on this
target.** A formal value is one 64-bit word, so a node with a type tag, a
child list and source coordinates is not representable as a value at all; the
obvious workarounds are all worse than the limitation: a node id into a
side table cannot be passed between the functions a caller writes, `isinstance`
against a host class is refused, and a subclass of a host class cannot be
declared. So `ast.parse` here answers "are the bytes and the block structure
sound", which is the question a *checker* asks before it hands a file to
something that will really compile it — and `docs` for the callers who wanted
`ast.walk` should say so.

The measured evidence, and the numbers behind every claim below:

| what | how it was measured | result |
|---|---|---|
| token kinds, positions, counts | `test_ast_formal.py` over 214 cases, the built image against this process's `tokenize` | identical |
| `parse` against `compile` | the same 214 cases | identical except the 38 pinned below |
| whole real files | 400 files of CPython 3.14.6 `Lib` and all 217 `.py` files in this repository, embedded whole, through the built image | 0 mismatches |
| no false positives over a whole corpus | the same state machine driven from CPython's own token stream over 2017 files (CPython `Lib` including `test/`, plus this repository) | 0 files the module refuses and CPython accepts; 3 files it accepts and CPython refuses, all listed under "missed errors" below |
| the sweep that motivated it | `python3 tools/formal_sweep.py -j8` over the ten files that were blocked on `ast` | `ast` is gone from the by-module line; the ten files are now blocked on `copy` x2, `glob` x2, `re` x2, `builtins` x2, `concurrent.futures`, `pathlib` — each one needs several modules, and this was the one |

## What it implements

`tokenize(src, out, cap)` and `tokenize_from(src, first, out, cap)` produce
CPython's token kinds, lines and columns, three words per token, into a
caller-owned list, resumable: `tokenize_from` with `first` set re-scans from the
start and records only the tokens from `first` on, which is how a caller with a
fixed buffer walks a stream too long for it. `token_bound(src)` is an upper
bound on the token count (three words per source byte plus eight, because every
token consumes at least one byte, an INDENT and a DEDENT consume none and there
is at most one of each per line, and ENDMARKER is one more) so a caller can size
a buffer without guessing. `token_name(kind)` spells `token.tok_name`, and
answers `""` for the codes this module never emits.

`parse(src)` is 1 or 0 and `parse_reason(src)` says which of two failure classes
it was — 0 valid, 1 a lexical error (a stray byte: a string that never ends, a
bracket left open, a malformed number), 2 a structural one (a shape the
statement rules refuse). The statement rules are: the brackets match and close;
a simple statement does not start with an operator that cannot open one (`+ x`
is fine, `, x` and `-> x` are not) and does not end with one (`x =`, `x +`,
`x ==`), unless the line is a compound header (`if x:`) or the operator is the
`*` of a `from a import *`; `def` and `class` are followed by a NAME; `if`,
`while`, `for`, `with` and `elif` are followed by something that can start an
expression and `except` by that or by a `:`; a comma does not directly follow an
opener or another comma. Each of those is a rule CPython's own parser
enforces, and each is in `test_ast_formal.py` as a case.

## The normalisation: an f-string run is ONE token

CPython 3.12+ emits an f-string as a run: `FSTRING_START`, then
`FSTRING_MIDDLE`/`OP`/`FSTRING_END` for the parts and the replacement fields.
This module emits the run's FIRST kind code once, at the run's start position,
and nothing else. A run nested inside another run's replacement field belongs to
the outer one — `f'{",".join([f"{o}.{f}" for f in fields])},)'` is one token here
and three runs in CPython's stream, and the case is in the corpus because
`Lib/dataclasses.py` has it.

A caller that needs the parts has to tokenize with CPython; what a caller on
this target needs is "where does this literal end", and one token per literal is
the answer to that.

## Known gaps, by kind

**38 pinned cases where CPython's parser refuses and this module accepts.** They
are in `test_ast_formal.py`'s `VERDICTS` with the verdict asserted, and this is
the list:

- the expression grammar, which `tokenize` does not check either: `x = 1..2`,
  `x = 1j2`, `x <> 1`, `x = ,1`, `x = 1 +* 2`, `x = 1 ** * 2`,
  `x = a | b ^ c & d ~ e`, `x = 1 2`, `x = a b c`, `x = a.5`, `x = *a`;
- a number's VALUE, for the same reason: `x = 1e`, `x = 1.2.3`, and the two that
  end early and leave a NAME — `x = 1e__0` is the number `1` and the name
  `e__0`, `x = 1e_5` is `1` and `e_5`, and two expressions with no operator
  between them is the parser's error, not the tokenizer's;
- a statement keyword in the wrong place: `for in x:`, an orphan `except:`,
  `else:`, `elif x:`, `finally:`, a header with no colon (`if x`, `for i in`),
  a ternary with nothing after `else`, `x = 1 else 2`, `x = not not`, `del`,
  `x = 1 if 2 else 3 else 4`, and `lambda x: x` used as a statement;
- a compound statement's own rules: `return 1` and `yield 1` outside a
  function, `x = (yield)`, `await x` outside `async def`, `nonlocal x` at
  module level, and `def f(x, x)` with a duplicate parameter;
- an annotation on a tuple target (`x, y: int = 1, 2` — "only single target (not
  tuple) can be annotated");
- an unexpected INDENT, which needs the block structure a tree would have:
  `if x:` / `  pass` / `   pass`, and a dedent to a column that is not on any
  enclosing level inside a block;
- one lexer corner: a backslash before a closing brace INSIDE a replacement
  field (`x = f"a\{b\}c"`), which CPython's own tokenizer refuses with
  "unexpected character after line continuation character" and this module
  accepts.

**3 real files in the 2017-file corpus that this module accepts and CPython
refuses**, all of them the same two things rather than the statement rules: a
coding declaration (`Lib/test/test_future_stmt/badsyntax_future.py`,
`Lib/test/tokenizedata/bad_coding2.py`) — a `str` has no encoding, so this is
not this module's business and never will be — and a non-ASCII character that
is not `XID_Start` (`Lib/test/tokenizedata/badsyntax_3131.py`, a `€` used as a
name). The identifier rule after PEP 3131 is "XID_Start, then XID_Continue",
and on BYTES the part of it this module computes exactly is "any byte at or
above 0x80 continues an identifier" (`_ident`, `_ident_cont`); the full Unicode
tables would be a data file this target cannot read.

## Divergences that are not about the verdict

**A lone CR is a line break here and whitespace to CPython.** `x = 1\ry = 2\r`
tokenizes to `NAME OP NUMBER NEWLINE ENDMARKER` here and to
`NAME OP NUMBER OP('\ry') OP NUMBER NEWLINE ENDMARKER` in CPython, which
absorbs the CR into the next token. A CRLF pair is a line break on both sides and
is in the corpus; a bare CR is not, because no token stream can match. It is
rare enough (old Mac line endings) that changing the rule would cost the CRLF
case for no gain.

**Columns count characters, not bytes** — and that took a fix to get right.
CPython's tokenizer works on the decoded source and its columns are character
offsets; this module works on bytes, so `hi - lo` counts a two-byte character
twice. 259 of the 2017 files in the corpus have a line where the two differ
(a box-drawing character in a comment, a non-ASCII identifier), and every
column after it on that line was wrong. `_chars` now subtracts the UTF-8
continuation bytes in the line prefix, which for valid UTF-8 is exactly the
character count, and the corpus cases (`# ─── box ───`, `Ω = 1`, `x = 'İ'`) pin
it.

## The measured limits, and what they are

- **The buffer is the caller's, and the window is the caller's.** Three words
  per token, and `tokenize_from` reports TOKEN_FULL (-2) at the end of a window
  and TOKEN_ERROR (-1) for a refusal, so the two are told apart by sign. A list
  literal on this target is capped at about 4095 words (the encoder asserts in
  `formal/arm64.py` — filed as
  `CODEGEN_list_literal_over_4095_words_asserts.md`), which is why a caller
  windows at a few hundred tokens rather than holding a whole file.
- **Bracket nesting is capped at 64 and indentation depth at 64** (`BRACKET_CAP`,
  `INDENT_CAP`), because both are fixed-size lists in `_lex`'s frame rather than
  a heap-allocated stack. A file nested deeper than that is refused, not
  mis-tokenized.
- **arm64 only, in practice.** The module calls libc (`strspn`, `strcspn`,
  `strncmp`, `str_alloc`, `memset`, `memcpy`) and the x86-64 formal link path
  refuses those externs, so `test_ast_formal.py` skips on a non-arm64 host the
  way `test_formal_os.py` does.
- **No module state.** Every set the scanner needs (`_ident`, `_ident_cont`,
  `_blanks`, `_cont`, `_not_cont`) is built per scan into the caller's frame, so
  a scan costs five allocations and there is nothing to initialise once. A
  caller in a loop pays that per call; it is measured at well under a
  millisecond for the 200KB files in the corpus.
- **Three backend defects shaped the code and are filed where they belong**, not
  worked around silently: a module-constant read inside an `elif` arm on this
  path is refused by the register allocator — the OTHER half of that same doc,
  a constant as an assignment's right-hand side, was fixed 2026-09-30, so only
  the `elif` shape still constrains this module
  (`CODEGEN_elif_arm_reading_a_module_constant_has_no_home.md`), a shift by more
  than 31 is miscompiled on arm64
  (`CODEGEN_shift_amount_above_31_is_wrong_on_arm64.md`), and a triple-quoted
  literal holding a backslash swallows the rest of the file in the HOST compiler
  (`CODEGEN_triple_quoted_literal_ending_in_a_backslash_swallows_the_rest_of_the_file.md`),
  which is why `test_ast_formal.py` embeds a source as a chain of joins.

## What a caller must not conclude

`parse(src) == 1` means "the bytes tokenize and the block structure is sound".
It does not mean the file compiles: the 38 pinned cases above are files CPython
refuses. A caller that needs the real answer needs a real parser, and the point
of this module is to let a checker reject the cheap failures — a stray quote, an
unclosed bracket, a statement that ends in `=` — without one.
