"""ast — CPython's `ast`, in the subset a formal image can actually compute.

WHY THIS FILE EXISTS
--------------------
`formal/imports.py` refused ten files in this repository with

    imports 'ast', which is a host module (CPython standard library), which has
    no Mojo source for this backend to compile

because `ast` was in HOST_MODELLED — "reachable in principle, not implemented".
`ast` is a shape over the SOURCE LANGUAGE: parsing, and a walk over the tree.
Nothing in it needs a second process, a socket, a thread or a dynamic loader,
so by the rule `formal/imports.py` states for that list, implementing it is
WORK and not a fact about the target. This file is that work, and its presence
is what takes `ast` out of HOST_MODELLED; the one-name edit is in
`formal/imports.py`, and the sweep's `not-answerable/host-import by module`
count for `ast` (10) drops to 0 because the module is found by the resolver
instead.

It lives in `formal/hostmods/`, which `formal/imports.py` adds to every file's
search roots as its LAST entry and which no other resolver in the tree lists —
NOT at the repository root, where a Mojo `ast` would capture `import ast` in
`fire.py`, `module_loader.py` and `gimple_codegen.py` themselves, which is
exactly the failure that moved `os`, `sys` and `struct` here. See
`_HOSTMODS_ROOT`.


WHAT CPYTHON'S `ast` IS, AND WHY HALF OF IT CANNOT EXIST HERE
-----------------------------------------------------------
`ast.parse(source)` returns a TREE of node objects. A program then asks what a
node IS (`isinstance(n, ast.FunctionDef)`), reads its fields (`n.name`,
`n.body`, `n.lineno`), walks it (`ast.walk`, `ast.iter_child_nodes`) and
sometimes rewrites it (`ast.NodeTransformer`, `ast.unparse`). On this target
every one of those steps is impossible, and each for its own measured reason —
none of them is a missing feature that more work would supply:

  * **A tree is not a value.** `formal/model.py`, "What a value is": a formal
    value is ONE 64-bit word in a function's own stack scratch, and that
    scratch is reclaimed when the function returns. A container is a
    frame-allocated blob of 8-byte slots, so a node list built inside a callee
    is a read of a frame the caller does not own (struct.mojo's limit 4, and
    `bugs/FORMAL_known_limits.md` §6.1's frame-escape family).
  * **`isinstance` cannot be called.** `isinstance(x, int)` is refused BY NAME:
    "int has no home: the module-level symbol table is empty for this unit".
    `int` is a type, a type is not a word, and there is no storage for one.
  * **Attribute access on a word is refused, not mis-lowered.** `t.body` where
    `t` is a one-word result is refused: "a field is lowered three ways and
    which one applies is decided by the BINDING of the base, not by a type …
    't' is bound here as a parameter, so none of the three is established".
  * **Subclassing a library type is not expressible.** `class R(ast.
    NodeTransformer)` is a class with a foreign base; a `struct` here is a
    frame blob, and a struct's layout does not cross a dylib boundary
    ("the library would bind 1 symbol(s) that nothing provides: Node" —
    measured).
  * **`unparse` and `dump` need the tree** they were handed.

So the half of `ast` that CAN exist here is the half that never builds a tree:
**the tokenizer and the syntax check.** Both are pure computation over the
source text, both are what CPython's own `ast.parse` runs first, and both are
checkable against CPython token for token over hundreds of real files — which
`test_ast_formal.py` does, comparing this module's output with the stream
`tokenize.generate_tokens` produces for the same bytes.

WHAT THIS MODULE PROVIDES
-------------------------
    parse(src)              -> 1 if src is a valid Python module, else 0
    parse_reason(src)       -> 0 valid, 1 a lexical error, 2 a structural one
    tokenize(src, out, cap) -> the token KIND codes, three words per token
    token_bound(src)        -> an upper bound on the token count, for sizing
    token_name(kind)        -> CPython's name for a kind code, for printing

Every one of these is a FUNCTION. There is no module-level state (a name that
outlives the frame that made it has nowhere to live —
`bugs/FORMAL_module_state_no_storage.md`), so nothing here remembers anything
between calls, and `ast.parse` is a call like every other. The kind-code
constants at the top of this file are module-level literals, which means they
are substituted HERE and are not readable from another module — `token_name` is
the public way to ask what a kind code means, and that is the same table
`tokenize` prints.

THE TOKEN STREAM IS CPYTHON'S, BY NUMBER
----------------------------------------
A kind code is a word, and the words CPython uses are the useful ones to use:
this module emits the `token` module's OWN integers (ENDMARKER 0, NAME 1,
NUMBER 2, STRING 3, NEWLINE 4, INDENT 5, DEDENT 6, OP 55, FSTRING_START 59,
FSTRING_MIDDLE 60, FSTRING_END 61, TSTRING_START 62, COMMENT 65, NL 66,
ERRORTOKEN 67). Nothing has to be translated to compare a stream with
`tokenize`'s, and a program that prints a kind code and a reader with
`token.tok_name` in hand are looking at the same number.

THE TWO PLACES THIS STREAM IS NOT IDENTICAL TO `tokenize`'S
----------------------------------------------------------
Both are stated here, in `test_ast_formal.py` (which compares against CPython
with exactly these two normalisations applied, and nothing else), and in
`bugs/FORMAL_ast_module_subset.md`:

  1. **An f-string or t-string is ONE token, not three or more.**
     `tokenize` splits `f"a{b}c"` into FSTRING_START, FSTRING_MIDDLE, OP `{`,
     NAME `b`, OP `}`, FSTRING_MIDDLE, FSTRING_END — the literal text, the
     replacement field's own tokens and the format spec are separate tokens,
     and a nested spec field (`f"{x:{w}}"`) nests further. The kind code
     emitted here is the run's FIRST one (FSTRING_START 59, TSTRING_START 62)
     and the token spans the whole literal, because the alternative is
     re-implementing CPython's f-string state machine — three token kinds, a
     format-spec sub-grammar, `#` comments inside a triple-quoted field
     (3.14) and PEP 701's reuse of the outer quote inside the field. Finding
     the literal's END still needs the brace/quote walk, and `_skip_field`
     below is that walk. `test_ast_formal.py` collapses each CPython f-string
     run to its first token and compares.
  2. **A lone CR is a line break here, and whitespace to `tokenize`.**
     `tokenize` lexes a `\r` on its own as the start of an operator run
     (`"x=1\ry=2\r"` gives NAME OP NUMBER OP `\ry` OP NUMBER NEWLINE
     ENDMARKER — the CR is absorbed into the next token). Here it ends the line,
     so the same source gives NAME OP NUMBER NEWLINE ENDMARKER. A CRLF pair is a
     line break on BOTH sides and is in `test_ast_formal.py`'s corpus; a bare
     CR is not, because no token stream can match. Measured over the corpus:
     zero files contain a lone CR, so nothing real is affected. A control byte
     is the other half of this item and does NOT differ: ERRORTOKEN is 67 and
     this module emits 67 for one.

WHAT `parse` CHECKS, AND WHAT IT DOES NOT
----------------------------------------
`parse` is the tokenizer plus a statement-level structural check, and its claim
is bounded on purpose: **it accepts every module the corpus contains and
rejects the classes of error listed at `parse` itself.** It is NOT a Python
parser: the expression grammar is not implemented, so `x = )` is caught (a
statement may not end with `)`) while `x = 1 +* 2` is not. Raising is not
available here either — a `raise` lowers to a call to a symbol nothing
defines — so CPython's `SyntaxError` is a RETURN VALUE, the same degradation
`struct.mojo` documents in its ERRORS section. The full list of what is and is
not checked is in `bugs/FORMAL_ast_module_subset.md`; the short version is
that this is a LEXICAL and BLOCK-STRUCTURE validator, and a file it accepts is
one whose bytes and block structure are sound.

THE MECHANICS, because they are the whole design
-------------------------------------------------
A string on this path is a bare `char *` (see `formal/model.py`'s string
section), so this module never reads a character: it asks the C library
questions about a pointer, which is the same answer computed by the same
algorithm CPython uses rather than a second implementation of it.

  * `strspn`/`strcspn` answer "how long is the run of these bytes" and "where
    is the next of these bytes" — the token classes, the indentation, the end
    of a comment;
  * `strncmp` answers the operator and keyword tables by longest match, which
    is exactly how a run of punctuation is split: `===` into `==` `=`, `<>`
    into one token, `+++` into three;
  * a character test is `strspn(s + i, SET) > 0` against a SET, never a byte
    load: a subscript on a `String`-annotated parameter is a silent wrong
    answer here (it reads the blob's count field —
    `bugs/CODEGEN_string_parameter_subscript_reads_count_field.md`), and every
    string in this module is a parameter;
  * the sets that need a byte which cannot be written in a source literal (a
    tab, a form feed, a CR, the 128 bytes >= 0x80) are BUILT with `str_alloc`
    + `memset`, the way `os.linesep` builds its newline: a string literal on
    this path is interned VERBATIM and its escapes are not unescaped, so
    `"\t"` is the two characters `\` and `t`. Every other set is a literal of
    printable bytes, and every set here is pinned byte for byte by
    `test_ast_formal.py`. The same verbatim rule has a second-order cost worth
    knowing about, because it is why `test_ast_formal.py` does not embed its
    corpus as literals: the compiler's LEXER honours an escape while finding a
    literal's end, so a literal holding a backslash before a quote can swallow
    the rest of the file
    (`bugs/CODEGEN_triple_quoted_literal_ending_in_a_backslash_swallows_the_rest_of_the_file.md`).
  * the string primitives are `os/_syscalls.mojo`'s, imported rather than
    written again: `str_alloc`, `str_build`, `str_len`. That is a real
    dependency — an `ast` dylib links `os`'s — and it is the right one,
    because a second implementation of "read a character from a `char *` on
    this target" is a second thing to be wrong.

LIMITS MEASURED, not assumed
----------------------------
  * **A token buffer is the caller's.** There is no list to return and no heap
    this module can use as one: `tokenize(src, out, cap)` writes three words
    per token into a list the CALLER allocated, and returns TOKEN_FULL when it
    does not fit. Two measurements make that the only sound shape. A list built
    inside a callee lives in that callee's frame (`struct.mojo` limit 4). And a
    `malloc`'d buffer does not work as the blob either: `Pointer[UInt8]` is
    this path's STRING annotation, so passing one where a blob is expected
    makes the callee index it as a string — measured, it crashes the image at
    the first store. `token_bound` exists so a caller can size the buffer
    without guessing.
  * **No recursion anywhere.** The machine stack under this entry stub holds
    about 60 frames (measured: `rec(60)` returns, `rec(62)` segfaults), so a
    recursive-descent parser could not be trusted with a real file's nesting.
    Every scan here is a loop, and the nesting state is two fixed-size lists
    in one frame.
  * **Indentation nests at most INDENT_CAP deep and brackets at most
    BRACKET_CAP** (64 each); deeper is a refusal, not a wrong answer. Measured
    over this repository plus CPython 3.14.6's `Lib`: the deepest indentation
    in any of those files is 12 and the deepest bracket nesting is 9.
  * **BOTH BACKENDS**, for the same reason `os` is: a module dylib that makes a
    call into the C library builds and runs under `--backend=x86_64` as well,
    and the claim this replaces was false — see the top of
    `formal/hostmods/os/__init__.mojo`, which is where the measurement is. A
    host with no x86-64 support at all still skips the x86-64 half of the
    suite, with the reason printed.
"""

from os._syscalls import str_alloc, str_build, str_len


# ── the kind codes, as CPython's `token` module numbers them ───────────────
#
# A kind is a word, and the words `token` uses are the useful ones: nothing has
# to be translated to compare this module's stream with `tokenize`'s, which is
# what `test_ast_formal.py` does over the corpus. These are literals, so they
# are substituted inside this module and are NOT importable from it — see
# `token_name`, which is the public way to ask.

ENDMARKER_K = 0
NAME_K = 1
NUMBER_K = 2
STRING_K = 3
NEWLINE_K = 4
INDENT_K = 5
DEDENT_K = 6
OP_K = 55
FSTRING_K = 59
TSTRING_K = 62
COMMENT_K = 65
NL_K = 66
ERRORTOKEN_K = 67

# What `tokenize` and this module return instead of a count.
TOKEN_ERROR = 0 - 1        # the source is not a tokenizable Python module
TOKEN_FULL = 0 - 2         # the caller's buffer cannot hold the stream

# What `_classify` puts in the kind field when the thing at that position is
# not a token. Both are above every kind code `token` uses, so they cannot
# collide with one.
CLS_CONT = 200             # a `\` + newline: no token, and the line goes on
CLS_ERR = 201              # a lexical error: this is not Python

# `_lex` modes. The check is a MODE and not a second function because the
# checks read the token being emitted, at the point in the loop where the
# source position of that token is still known: a second pass would need the
# stream, and a stream needs a caller-owned buffer, and `parse` must not make
# its caller allocate one to ask a yes/no question.
MODE_STREAM = 0
MODE_CHECK = 1

# The two fixed capacities, bounds rather than limits in practice; see the
# module docstring for what they were measured against.
INDENT_CAP = 64
BRACKET_CAP = 64


# ── the character sets ─────────────────────────────────────────────────────
#
# Every literal here is PRINTABLE bytes only, and that is not a style choice: a
# string literal on this path is interned verbatim and its escapes are NOT
# unescaped, so a `"\t"` in a `.mojo` file is the two characters `\` and `t`
# and a set of whitespace written as a literal would be a set containing a
# backslash. The sets that need an unprintable byte are built, below, with the
# `str_alloc` + `memset` idiom `os.linesep` uses for its newline.

SP = " "                  # 0x20
BSLASH = "\\"             # 0x5C
HASH = "#"                # 0x23
DIGITS = "0123456789"
DECRUN = "0123456789_"
ALNUM_ = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
LETTERS_ = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_"
HEXRUN = "0123456789abcdefABCDEF_"
OCTRUN = "01234567_"
BINRUN = "01_"
EXPMARK = "eE"            # the exponent marker of a float literal
IMAGMARK = "jJ"           # the imaginary suffix
PLUSMINUS = "+-"
RADIXMARK = "xXbBoO"      # what may follow a leading 0 in a based literal
PREFIX1 = "rRuUbBfFtT"    # the one-letter string prefixes
STAR = "*"               # the only operator that may END a `from` import
DOT = "."


def _high() -> str:
    """The set of the 128 bytes >= 0x80, as a NUL-terminated set string.

    Built, because a source file cannot spell a byte that is not valid UTF-8.
    It is the second half of `_ident`: CPython's identifier rule after PEP 3131
    is "XID_Start, then XID_Continue", and on BYTES the part of that this
    module can compute exactly is "anything at or above 0x80 continues an
    identifier" — measured against `tokenize` over the corpus, where a
    non-ASCII identifier is the case that would catch a missing set.
    """
    var b: Pointer[UInt8] = str_alloc(128)
    var i = 0
    while i < 128:
        memset(b + i, 128 + i, 1)
        i = i + 1
    return b


def _cont() -> str:
    """The set of the 64 UTF-8 CONTINUATION bytes, 0x80..0xBF.

    Built for the same reason as `_high`, and it is the complement that makes
    the column count cheap: a run of bytes that are NOT continuations is one
    `strspn`, so a line of ASCII costs one call per token instead of one per
    byte.
    """
    var b: Pointer[UInt8] = str_alloc(64)
    var i = 0
    while i < 64:
        memset(b + i, 128 + i, 1)
        i = i + 1
    return b


def _not_cont() -> str:
    """Every byte that is NOT a UTF-8 continuation: 0x01..0x7F and 0xC0..0xFF.

    The complement of `_cont`, and the one that does the work: `strspn` over it
    skips a whole run of ASCII in a single call, so a line of ASCII costs one
    call per token rather than one per byte.

    191 bytes and NOT 192, and not in numeric order, because a set string is
    NUL-terminated and a NUL inside it ends the set: 0x00 is left out for that
    reason (a NUL cannot be in a line this module has tokenized anyway) and the
    two ranges are laid end to end so that no terminator falls between them.
    """
    var b: Pointer[UInt8] = str_alloc(191)
    var i = 0
    while i < 127:
        memset(b + i, 1 + i, 1)
        i = i + 1
    i = 0
    while i < 64:
        memset(b + 127 + i, 192 + i, 1)
        i = i + 1
    return b


def _chars(src: str, lo: int, hi: int, cont: str, notc: str) -> int:
    """How many CHARACTERS `src[lo:hi]` holds, for a COLUMN.

    CPython's tokenizer works on the DECODED source, so its columns count
    characters; this module works on bytes, so a naive `hi - lo` counts a
    two-byte character twice and a four-byte one four times. On a line with no
    byte >= 0x80 the two agree, and that is the whole of ASCII source — but a
    box-drawing character in a comment or a non-ASCII identifier shifts every
    column after it on that line, which is 259 of the 2017 files in the corpus
    (measured). So the count is the byte length less the continuation bytes,
    which for valid UTF-8 is exactly the character count.
    """
    var n = 0
    var j = lo
    while j < hi:
        j = j + strspn(src + j, notc)
        if j >= hi:
            break
        if strspn(src + j, cont) == 0:
            break
        n = n + 1
        j = j + 1
    return hi - lo - n


def _ident() -> str:
    """The identifier-START set: ASCII letters, `_`, and every byte >= 0x80.

    One allocation, built by concatenation rather than a loop.
    """
    return str_build(LETTERS_, "", _high())


def _ident_cont() -> str:
    """The identifier-CONTINUATION set: the start set plus the ten digits.

    A separate set from `_ident` because the two questions are different, and
    using the start set for both is a wrong answer rather than a rough one:
    PEP 3131 says an identifier is XID_Start followed by XID_Continue, and the
    digits are in the second set only. Measured: with one set, `b2` lexed as
    the NAME `b` and the NUMBER `2`, and the token stream diverged from
    CPython's at that token — which is a wrong image, not a missing feature.
    """
    return str_build(ALNUM_, "", _high())


def _blanks() -> str:
    """Space, tab and form feed: the bytes that are horizontal whitespace.

    CPython's tokenizer also treats a form feed as a COLUMN RESET rather than
    as one column, which `_lex` honours, and a tab as a jump to the next
    multiple of 8. See the module docstring for why this is built and not
    written.
    """
    var b: Pointer[UInt8] = str_alloc(3)
    memset(b, 32, 1)
    memset(b + 1, 9, 1)
    memset(b + 2, 12, 1)
    return b


def _one(byte: int) -> str:
    """A one-byte set, so that a test for a control character is a `strspn`.

    `byte` is a number and not a character because there is no way to read a
    byte out of a string on this path: `s[i]` is a silent wrong answer for a
    parameter (see the module docstring). Passing the VALUE in is the only way
    to name a tab, a form feed or a CR, and every caller passes a constant.
    """
    var b: Pointer[UInt8] = str_alloc(1)
    memset(b, byte, 1)
    return b


def _tab() -> str:
    """0x09, on its own so that an indentation column can be advanced."""
    return _one(9)


def _formfeed() -> str:
    """0x0C, on its own so that an indentation column can be RESET."""
    return _one(12)


def _quotes() -> str:
    """The two quote bytes, 0x22 and 0x27, as a NUL-terminated set string.

    BUILT, and not written as a literal, for a measured reason: a string literal
    on this path is interned VERBATIM and its escapes are not unescaped, so
    there is no spelling of a two-byte set holding both quotes. `"\""` emits a
    backslash and a quote (the escape is not interpreted, so the set would also
    match every backslash in the source), `'\''` emits a backslash and an
    apostrophe for the same reason, and `'"'` — the one that looks right —
    emits the double quote alone (measured: a `'x = 'y'` source lexed its
    opening quote as a one-character OP). So the set is laid down a byte at a
    time, the way `os.linesep` builds its newline.
    """
    var b: Pointer[UInt8] = str_alloc(2)
    memset(b, 34, 1)
    memset(b + 1, 39, 1)
    return b


def _lf() -> str:
    """0x0A. The line break, and the end of a comment."""
    return _one(10)


def _cr() -> str:
    """0x0D. A line break only as the first half of a CRLF."""
    return _one(13)


# ── the operator table ─────────────────────────────────────────────────────
#
# Longest match at each position, and the table is CPython's own list —
# INCLUDING `<>`, which is not an operator any more but is in the tokenizer's
# table, so `a<>b` is one token while `a<<>b` is `<<` then `>`. Measured, both:
# guessing here would put the wrong boundaries in the stream, one token per
# operator, over every file in the corpus.

def _oplen(s: str, p: int) -> int:
    """How many bytes of `s` at `p` are ONE operator token. Never 0.

    Three bytes, then two, then one. A character that is in no entry is a
    one-character OP token, which is what `tokenize` does for `$`, `?` and
    backtick (measured: `a$b` and `a??b` are both OP tokens, one character
    each).
    """
    if strncmp(s + p, "**=", 3) == 0:
        return 3
    if strncmp(s + p, "//=", 3) == 0:
        return 3
    if strncmp(s + p, ">>=", 3) == 0:
        return 3
    if strncmp(s + p, "<<=", 3) == 0:
        return 3
    if strncmp(s + p, "...", 3) == 0:
        return 3
    if strncmp(s + p, "**", 2) == 0:
        return 2
    if strncmp(s + p, "//", 2) == 0:
        return 2
    if strncmp(s + p, ">>", 2) == 0:
        return 2
    if strncmp(s + p, "<<", 2) == 0:
        return 2
    if strncmp(s + p, "<=", 2) == 0:
        return 2
    if strncmp(s + p, ">=", 2) == 0:
        return 2
    if strncmp(s + p, "==", 2) == 0:
        return 2
    if strncmp(s + p, "!=", 2) == 0:
        return 2
    if strncmp(s + p, "->", 2) == 0:
        return 2
    if strncmp(s + p, "+=", 2) == 0:
        return 2
    if strncmp(s + p, "-=", 2) == 0:
        return 2
    if strncmp(s + p, "*=", 2) == 0:
        return 2
    if strncmp(s + p, "/=", 2) == 0:
        return 2
    if strncmp(s + p, "%=", 2) == 0:
        return 2
    if strncmp(s + p, "&=", 2) == 0:
        return 2
    if strncmp(s + p, "|=", 2) == 0:
        return 2
    if strncmp(s + p, "^=", 2) == 0:
        return 2
    if strncmp(s + p, "@=", 2) == 0:
        return 2
    if strncmp(s + p, ":=", 2) == 0:
        return 2
    if strncmp(s + p, "<>", 2) == 0:
        return 2
    return 1


# What an operator is TO A STATEMENT, which is a different question from how
# long it is. The classes, and what each one means to the two rules in
# `_lex`:
#   1 '('   2 '['   3 '{'   4 ')'   5 ']'   6 '}'
#       an opener or a closer: may not open a statement, may not end one,
#       except that a closer may end one
#   7 ','       may not open a statement, MAY end one (a tuple: `x = 1,`)
#   8 ';'      neither, and is allowed to open one because an empty simple
#              statement is legal (`x = 1;;`)
#   9 '+' '-' '~' '@' '*' '**'
#       may open one (a decorator, a unary sign, a starred target), may not end
#       one (`x = 1 +` is an error)
#  10 everything else, `:` and `=` and the comparison, bitwise, shift,
#      augmented-assignment, arrow and walrus operators among them: may not
#      open a statement and may not end one
#  11 '...'    may open one and may end one (`x = ...`)
def _opclass(s: str, p: int, m: int) -> int:
    """The statement class of the operator token at `s[p]` of `m` bytes."""
    if m == 1:
        if strncmp(s + p, "(", 1) == 0:
            return 1
        if strncmp(s + p, "[", 1) == 0:
            return 2
        if strncmp(s + p, "{", 1) == 0:
            return 3
        if strncmp(s + p, ")", 1) == 0:
            return 4
        if strncmp(s + p, "]", 1) == 0:
            return 5
        if strncmp(s + p, "}", 1) == 0:
            return 6
        if strncmp(s + p, ",", 1) == 0:
            return 7
        if strncmp(s + p, ";", 1) == 0:
            return 8
        if strncmp(s + p, "+", 1) == 0:
            return 9
        if strncmp(s + p, "-", 1) == 0:
            return 9
        if strncmp(s + p, "~", 1) == 0:
            return 9
        if strncmp(s + p, "@", 1) == 0:
            return 9
        if strncmp(s + p, "*", 1) == 0:
            return 9
        return 10
    if m == 2 and strncmp(s + p, "**", 2) == 0:
        return 9
    if m == 3 and strncmp(s + p, "...", 3) == 0:
        return 11
    return 10


def _is_header_kw(s: str, p: int, m: int) -> int:
    """1 if the NAME at `s[p]` of `m` bytes opens a line that ends with `:`.

    The rule this decides is the one that keeps `if x:` and `def f():` from
    being read as statements ending in a `:`. `match` and `case` are in it
    because they are SOFT keywords: `match = 1` is legal Python and does not
    end in a colon, so being in this list costs nothing and being out of it
    would refuse every `match` statement in the corpus.
    """
    if m == 2:
        if strncmp(s + p, "if", 2) == 0:
            return 1
    if m == 3:
        if strncmp(s + p, "for", 3) == 0:
            return 1
        if strncmp(s + p, "def", 3) == 0:
            return 1
        if strncmp(s + p, "try", 3) == 0:
            return 1
    if m == 4:
        if strncmp(s + p, "with", 4) == 0:
            return 1
        if strncmp(s + p, "else", 4) == 0:
            return 1
        if strncmp(s + p, "elif", 4) == 0:
            return 1
        if strncmp(s + p, "case", 4) == 0:
            return 1
    if m == 5:
        if strncmp(s + p, "class", 5) == 0:
            return 1
        if strncmp(s + p, "async", 5) == 0:
            return 1
        if strncmp(s + p, "while", 5) == 0:
            return 1
        if strncmp(s + p, "match", 5) == 0:
            return 1
    if m == 6:
        if strncmp(s + p, "except", 6) == 0:
            return 1
    if m == 7:
        if strncmp(s + p, "finally", 7) == 0:
            return 1
    return 0


def _is_expr_kw(s: str, p: int, m: int) -> int:
    """The class of the NAME at `s[p]` of `m` bytes: 0, 1 or 2.

    1 means the next token must be able to start an EXPRESSION, which is what
    `if`, `while`, `for`, `with` and `elif` require; 2 means the same, except
    that a `:` is also allowed, which is what a BARE `except:` needs
    (`try: pass` / `except: pass` compiles — measured, and the CPython corpus
    has one, so reading `except` as "must be followed by an expression" refuses
    a file that CPython accepts).

    A smaller set than `_is_header_kw`, and deliberately: `else`, `try` and
    `async` are followed by a `:` and not by an expression, and `match`/`case`
    are soft keywords that may be plain assignments or calls. A keyword not in
    this list is one whose next token is not checked, which is a missed error
    rather than a false refusal.
    """
    if m == 2:
        if strncmp(s + p, "if", 2) == 0:
            return 1
    if m == 3:
        if strncmp(s + p, "for", 3) == 0:
            return 1
    if m == 4:
        if strncmp(s + p, "with", 4) == 0:
            return 1
        if strncmp(s + p, "elif", 4) == 0:
            return 1
    if m == 5:
        if strncmp(s + p, "while", 5) == 0:
            return 1
    if m == 6:
        if strncmp(s + p, "except", 6) == 0:
            return 2
    return 0


# ── the three scanners, each returning a new position or TOKEN_ERROR ───────

def _skip_string(s: str, p: int, n: int) -> int:
    """Past the closing quote of the string literal starting at `s[p]`.

    `p` is at the opening quote. A backslash always consumes the byte after it,
    raw or not: in `r"\""` the backslash is data but it is still what keeps the
    quote from ending the literal, which is the rule both CPython tokenizers
    use. A single-quoted literal that reaches a newline, or either kind that
    reaches the end of the source, is TOKEN_ERROR — CPython raises
    "unterminated string literal" and "EOF in multi-line string" there, and
    `x = 'abc` is in the test file for exactly this.
    """
    var lf = _lf()
    var triple = 0
    var p2 = p
    if p2 + 2 < n and strncmp(s + p2, s + p2 + 1, 1) == 0 and \
            strncmp(s + p2, s + p2 + 2, 1) == 0:
        triple = 1
        p2 = p2 + 3
    else:
        p2 = p2 + 1
    while p2 < n:
        if strspn(s + p2, BSLASH) > 0:
            p2 = p2 + 2
            continue
        # The closing quote must be the byte the literal OPENED with, which is
        # what `strncmp(s + p2, s + p, 1)` asks: a `'`-delimited string ends at
        # the next `'`, not at the next quote of either kind. Measured, and the
        # difference is a whole token: `'x = f"y"'` ended at the inner `"` and
        # the rest of the line lexed as a NAME and a NEWLINE.
        if strncmp(s + p2, s + p, 1) == 0:
            if triple == 1 and p2 + 2 < n and \
                    strncmp(s + p2, s + p2 + 1, 1) == 0 and \
                    strncmp(s + p2, s + p2 + 2, 1) == 0:
                return p2 + 3
            if triple == 0:
                return p2 + 1
        if triple == 0 and strspn(s + p2, lf) > 0:
            return TOKEN_ERROR
        p2 = p2 + 1
    return TOKEN_ERROR


def _skip_field(s: str, p: int, n: int) -> int:
    """Past the `}` that closes the replacement field opening at `s[p - 1]`.

    This is the part of CPython's f-string grammar that has to be right to find
    a literal's END, and it is the whole of the difference between `f"{x:{w}}"`
    ending where it does and ending at the first `}`. Three things are tracked,
    and each was measured against `tokenize`:

      * brace depth, so a nested `{}` in a format spec does not close the field;
      * whether a `:` has been seen at depth 0, because after it the text is a
        format spec and a quote in a spec is LITERAL: `f"{x:'>10}"` is valid and
        its `'` never starts a string, while `f"{x:{'a'}}"` — inside the nested
        field — does;
      * a quote before any `:`, which starts a real nested string:
        `f"{d['k']}"` and `f"{ f'{x}' }"` both depend on it.
    """
    var depth = 0
    var spec = 0
    var p2 = p
    var j = 0
    var quotes = _quotes()
    while p2 < n:
        if strspn(s + p2, "{") > 0:
            depth = depth + 1
            p2 = p2 + 1
            continue
        if strspn(s + p2, "}") > 0:
            if depth == 0:
                return p2 + 1
            depth = depth - 1
            p2 = p2 + 1
            continue
        if spec == 0 and strspn(s + p2, quotes) > 0:
            j = _skip_string(s, p2, n)
            if j < 0:
                return TOKEN_ERROR
            p2 = j
            continue
        if depth == 0 and strspn(s + p2, ":") > 0:
            spec = 1
        p2 = p2 + 1
    return TOKEN_ERROR


def _skip_interpolated(s: str, p: int, n: int) -> int:
    """Past the closing quote of an f-string or t-string starting at `s[p]`.

    The body rules CPython applies outside a replacement field: `{{` and `}}`
    are literal braces, a single `}` is an error, a quote in either the one or
    the three character form ends the literal, and a newline inside a
    single-quoted f-string is an error.

    The backslash is the subtle one and it is NOT "escapes the next byte". It
    keeps a quote from ending the literal and it swallows a second backslash,
    but a BRACE is examined as if the backslash were not there: `f"a\{b}"`
    is the text `a\` and then the FIELD `b`, and `f"a\}b"` is the
    text `a\` and then "f-string: single '}' is not allowed" (both
    measured, and so is `f"\{{b}}"` being all literal). A scanner that
    consumes the brace instead turns the `b}` of the first into a lone `}` and
    refuses the whole file, which is what it did to `Lib/idlelib/help.py`.

    Also measured: `f"a\\{b}"` (a field after an escaped
    backslash), `f"a\"{b}"` (a field after an escaped quote),
    `f"{{}}{{b}}"` (a doubled brace is one literal brace), `f"{x}}}"` (the text
    `}}` after the field) and `f"{x}}"` (a single `}` is an error).
    """
    var lf = _lf()
    var triple = 0
    var p2 = p
    if p2 + 2 < n and strncmp(s + p2, s + p2 + 1, 1) == 0 and \
            strncmp(s + p2, s + p2 + 2, 1) == 0:
        triple = 1
        p2 = p2 + 3
    else:
        p2 = p2 + 1
    while p2 < n:
        if strspn(s + p2, BSLASH) > 0:
            # See the docstring: a backslash does not swallow a brace.
            if strspn(s + p2 + 1, "{") > 0:
                p2 = p2 + 1
                continue
            if strspn(s + p2 + 1, "}") > 0:
                p2 = p2 + 1
                continue
            p2 = p2 + 2
            continue
        if strspn(s + p2, "{") > 0:
            if strspn(s + p2 + 1, "{") > 0:
                p2 = p2 + 2
                continue
            p2 = _skip_field(s, p2 + 1, n)
            if p2 < 0:
                return TOKEN_ERROR
            continue
        if strspn(s + p2, "}") > 0:
            if strspn(s + p2 + 1, "}") > 0:
                p2 = p2 + 2
                continue
            return TOKEN_ERROR
        if strncmp(s + p2, s + p, 1) == 0:
            if triple == 1 and p2 + 2 < n and \
                    strncmp(s + p2, s + p2 + 1, 1) == 0 and \
                    strncmp(s + p2, s + p2 + 2, 1) == 0:
                return p2 + 3
            if triple == 0:
                return p2 + 1
        if triple == 0 and strspn(s + p2, lf) > 0:
            return TOKEN_ERROR
        p2 = p2 + 1
    return TOKEN_ERROR


def _uscore_ok(s: str, p: int, run: int) -> int:
    """1 if the `run` bytes of underscores and digits at `s[p]` are a legal
    digit sequence: no trailing `_` and no `__`.

    The two rules CPython's tokenizer enforces on a digit run, both measured:
    `1_` and `1__0` are "invalid decimal literal", while `0_0` and `0x_1f` are
    fine. It is a byte loop rather than a `strstr` because the run is not
    NUL-terminated, and `strstr` on the rest of the source would match an
    underscore pair that belongs to the NEXT token.
    """
    var j = 0
    while j < run:
        if strspn(s + p + j, "_") > 0:
            if j == run - 1:
                return 0
            if strspn(s + p + j + 1, "_") > 0:
                return 0
        j = j + 1
    return 1


def _skip_run(s: str, p: int, run: int) -> int:
    """`p + run`, or TOKEN_ERROR if those `run` bytes are not a legal digit
    sequence.

    The wrapper every digit run in `_skip_number` goes through, so the
    underscore rule is stated once: no trailing `_` and no `__`, which is what
    CPython's tokenizer enforces (`1_` and `1__0` are "invalid decimal
    literal"; `0_0` and `0x_1f` are fine — all four measured).
    """
    if _uscore_ok(s, p, run) == 0:
        return TOKEN_ERROR
    return p + run


def _based_run(s: str, p: int, run: int) -> int:
    """`_skip_based`'s tail: is this run a legal literal body, and where does
    the literal end?

    `run == 0` is `0x` with no digits ("invalid hexadecimal literal"); a
    letter-or-digit still attached when the run ends is a digit of the wrong
    radix, or a hex literal that stopped early — `0b12` is the error and
    `0x1g` is the number `0x1` followed by the NAME `g`, both measured.
    """
    if run == 0:
        return TOKEN_ERROR
    if strspn(s + p + run, ALNUM_) > 0:
        return TOKEN_ERROR
    return _skip_run(s, p, run)


def _skip_based(s: str, p: int) -> int:
    """Past a `0x`/`0o`/`0b` literal whose digits start at `s[p]`.

    The run of digits is the radix's OWN set and not "letters and digits",
    because CPython stops a hex literal at a non-hex letter — `0x1g` is the
    number `0x1` followed by the NAME `g`, not one malformed literal (measured)
    — and then refuses what is left if it is a digit of the wrong radix, which
    is `0b12` and `0o9` (measured: "invalid digit '2' in binary literal").

    Three arms, three RETURNS, and no `elif`: see `_classify` for why a chain
    that reads a module-level constant does not lower.
    """
    var run = 0
    if strspn(s + p - 1, "xX") > 0:
        run = strspn(s + p, HEXRUN)
        return _based_run(s, p, run)
    if strspn(s + p - 1, "bB") > 0:
        run = strspn(s + p, BINRUN)
        return _based_run(s, p, run)
    run = strspn(s + p, OCTRUN)
    return _based_run(s, p, run)


def _skip_exp(s: str, p: int) -> int:
    """Past the exponent whose `e` is at `s[p]`.

    The byte after the marker decides, and it must be a DIGIT or a sign
    followed by a digit — an UNDERSCORE is neither, which is the whole subtlety
    and the reason this is its own function. Measured, all four:

      * `1e5` and `1e+5` consume the exponent;
      * `1e` and `1e_5` do NOT: the number ends at the `1` and CPython leaves a
        NAME `e` or `e_5` after it (so `1e__0` is a number then a name);
      * `1e+` and `1e+_5` are ERRORS — a sign with no digit after it is a
        refusal, not a shorter token.

    So the "not an exponent" answer is `p` unchanged, and the caller carries on
    from there.
    """
    var q = 0
    if strspn(s + p + 1, DIGITS) > 0:
        return _skip_run(s, p + 2, strspn(s + p + 2, DECRUN))
    if strspn(s + p + 1, PLUSMINUS) > 0:
        if strspn(s + p + 2, DIGITS) == 0:
            return TOKEN_ERROR
        q = _skip_run(s, p + 3, strspn(s + p + 3, DECRUN))
        if q < 0:
            return TOKEN_ERROR
        return q
    return p


def _skip_number(s: str, p: int) -> int:
    """Past the end of the number literal starting at `s[p]`, or TOKEN_ERROR.

    The number grammar is the fiddliest part of the token rules, and every
    branch here is a measurement against `tokenize` rather than a reading of
    the grammar; the three scanners it calls hold the rules that have their own
    measured cases:

      * `0x1f` / `0o17` / `0b101` go to `_skip_based`;
      * `1e5` / `1e+5` / `1e` go to `_skip_exp`;
      * `1j` consumes one `j` and `1j2` is a number then a number;
      * `1..2` is `1.` and `.2`, `.5` is a number and a bare `.` is an operator,
        and `00` and `01` are numbers even though the PARSER refuses them — the
        tokenizer does not, and neither does this.
    """
    var i = p
    var run = 0
    if strspn(s + i, DIGITS) > 0 and strspn(s + i + 1, RADIXMARK) > 0:
        return _skip_based(s, i + 2)
    run = strspn(s + i, DECRUN)
    if run > 0:
        i = _skip_run(s, i, run)
        if i < 0:
            return TOKEN_ERROR
    if strspn(s + i, DOT) > 0:
        run = strspn(s + i + 1, DECRUN)
        if run > 0:
            i = _skip_run(s, i + 1, run)
            if i < 0:
                return TOKEN_ERROR
        else:
            i = i + 1
    if strspn(s + i, EXPMARK) > 0:
        i = _skip_exp(s, i)
        if i < 0:
            return TOKEN_ERROR
    if strspn(s + i, IMAGMARK) > 0:
        i = i + 1
    return i


# ── one token recorded ─────────────────────────────────────────────────────

def _emit(out, nt: int, k: int, line: int, col: int, cap: int) -> int:
    """Record one token as THREE words — kind, line, column — at `out[3 * nt]`.

    Three words and not one because a position is part of what a token is and
    there is no way to return two words from a function on this path. Returns
    `nt + 1`, or TOKEN_ERROR when the caller's buffer is full, which `_lex`
    reports as TOKEN_FULL: "the buffer is too small" and "this is not Python"
    are different answers and a caller has to be able to tell them apart.
    """
    if nt >= cap:
        return TOKEN_ERROR
    out[nt * 3] = k
    out[nt * 3 + 1] = line
    out[nt * 3 + 2] = col
    return nt + 1


def _put(out, slot: int, kind: int) -> int:
    """`out[slot] = kind`, and 0. Always 0; the value is the assignment.

    Every kind code this module records goes through here, and the indirection
    is load-bearing rather than decorative. It was written when a module-level
    constant was REFUSED as the bare right-hand side of an assignment —
    `out[0] = K` built the dylib and then failed the link audit with "K has no
    home: the register allocator collected no home for it" — and that half is
    FIXED (2026-09-30; it was the build's constant substitution, not the
    emitter). It is left as it is because `out[0] = K` is not the only thing
    that was refused, and the other half is still open: a module-level constant
    read inside an `elif` arm. Both measured, on five-line reproducers, and both
    in `bugs/CODEGEN_elif_arm_reading_a_module_constant_has_no_home.md`, whose
    Status now says which is which. Passing the code as an ARGUMENT sidesteps
    both at once, which is why it is written this way; the numbers are written
    once, here and at the constants.
    """
    out[slot] = kind
    return 0


def _pack_number(src: str, p: int, out) -> int:
    """Classify the NUMBER at `s[p]` into `out`. 0 for OK, 1 for a lexical
    error, so that the caller can tell a bad literal from a good one without
    reading `out[0]` twice."""
    var e = _skip_number(src, p)
    if e < 0:
        _put(out, 0, CLS_ERR)
        return 1
    _put(out, 0, NUMBER_K)
    out[1] = e
    return 0


def _pack_name(src: str, p: int, n: int, m: int, quotes: str, out) -> int:
    """Classify the identifier run at `s[p]` of `m` bytes into `out`: a NAME,
    or a string literal if the run is a PREFIX and a quote follows it.

    `rb"x"` is one STRING token and `abc"x"` is a NAME and a STRING (both
    measured against `tokenize`), which is the whole reason this is separate
    from `_classify`: the decision needs the run's LENGTH and its last byte,
    and CPython's prefixes are one or two letters with the quote right after.

    The two-letter prefixes are matched CASE-INSENSITIVELY, which is what
    CPython does: every case combination of `br` is a bytes literal and every
    case combination of `rf`/`rt` is an f-string or a t-string — `bR'q'`,
    `Rb'q'`, `Br'q'`, `RB'q'`, `rF`, `Rt`, `tR`, `TR` are all ONE token each
    (measured, all 100 two-letter combinations enumerated against
    `tokenize`). The two letters must DIFFER, so `bb`/`rr`/`uu` are a NAME and
    a STRING as CPython has it, and `u` combines with nothing, so `bu'q'` is a
    NAME and a STRING here where CPython raises — a missed error in the
    documented direction.

    The kind codes are written into `out[0]` and never bound to a local, and
    every arm RETURNS. Neither is taste, but only ONE of the two reasons is
    still live: a module-level constant read inside an `elif` arm is refused on
    this path ("'K' has no home: the register allocator collected no home for
    it") and always was, because an `elif` is lowered as a branch on a SAVED
    condition value and that place has no folded-constant case. So the arms are
    sequential `if`s with an early return and never an `elif`; see
    `bugs/CODEGEN_elif_arm_reading_a_module_constant_has_no_home.md`, whose
    Status section records this as the half that is still open. (The other half
    that file reported — a constant as an assignment's right-hand side — was
    fixed on 2026-09-30 and no longer constrains this module.)
    """
    var e = p + m
    # 0 not a prefix, 1 a plain string, 2 an f-string, 3 a t-string.
    var t = 0
    if m == 1 and strspn(src + p, PREFIX1) > 0 and \
            strspn(src + p + 1, quotes) > 0:
        if strspn(src + p, "fF") > 0:
            t = 2
        if strspn(src + p, "tT") > 0:
            t = 3
        if t == 0:
            t = 1
    if m == 2 and strspn(src + p + 2, quotes) > 0:
        if strspn(src + p, "bB") > 0 and strspn(src + p + 1, "rR") > 0:
            t = 1
        if strspn(src + p, "rR") > 0 and strspn(src + p + 1, "bB") > 0:
            t = 1
        if strspn(src + p, "rR") > 0 and strspn(src + p + 1, "fF") > 0:
            t = 2
        if strspn(src + p, "fF") > 0 and strspn(src + p + 1, "rR") > 0:
            t = 2
        if strspn(src + p, "rR") > 0 and strspn(src + p + 1, "tT") > 0:
            t = 3
        if strspn(src + p, "tT") > 0 and strspn(src + p + 1, "rR") > 0:
            t = 3
    if t == 0:
        _put(out, 0, NAME_K)
        out[1] = e
        out[3] = m
        return 0
    if t == 2:
        return _name_interp(src, e, n, m, FSTRING_K, out)
    if t == 3:
        return _name_interp(src, e, n, m, TSTRING_K, out)
    e = _skip_string(src, e, n)
    if e < 0:
        _put(out, 0, CLS_ERR)
        return 1
    _put(out, 0, STRING_K)
    out[1] = e
    out[3] = m
    return 0


def _name_interp(src: str, e: int, n: int, m: int, kind: int, out) -> int:
    """`_pack_name`'s interpolated arm: scan an f-string or t-string and record
    it under `kind`.

    A function of its own so that the kind is a PARAMETER: a module-level
    constant bound to a local is what this path refuses, and passing it down is
    both the shape that lowers and the one that keeps the numbers written once.
    """
    var e2 = _skip_interpolated(src, e, n)
    if e2 < 0:
        _put(out, 0, CLS_ERR)
        return 1
    _put(out, 0, kind)
    out[1] = e2
    out[3] = m
    return 0


def _classify(src: str, p: int, n: int, istart: str, icont: str,
             out) -> int:
    """What the token at `src[p]` is, written into the caller's `out`:
    `out[0]` the KIND (or CLS_CONT for a line continuation, which is not a
    token at all, or CLS_ERR), `out[1]` the position just past the token,
    `out[2]` the operator's statement class (`_opclass`, 0 for anything else)
    and `out[3]` the identifier run's length, which is what the keyword rules
    ask about.

    A CALLER-OWNED `out` and not a packed return word, for two reasons. This
    path cannot return two words, and the obvious packing needs shifts by 8, 40
    and 48 — a shift by more than 31 WAS silently miscompiled on arm64 (`1 << 40`
    computed `1 << 8`, measured, x86-64 correct; `encode_lsl_xd_xn_imm`'s base
    constant forced three bits of the immediate field, so every amount with a
    low bit pattern in that range was wrong, and the base is now
    `0xd3400000`). And even with that fixed, a caller-owned buffer is the shape
    this whole module uses: a list parameter is the only container a formal
    value can be, so four fields go into four words of it and cost nothing.

    Every arm RETURNS, and that is not a style choice either: an `elif` arm that
    reads a module-level constant is refused by this path's register allocator.
    See `_pack_name`, which says the same about binding one to a local.

    The classification order is CPython's: a line continuation, a comment, a
    number, an identifier (which may be a string prefix), a bare string, and
    then punctuation, where "not a letter, digit, quote, backslash or
    whitespace" is an operator of the table's length or one character of
    something that is not an operator at all.
    """
    var m = 0
    var adv = 0
    var lf = _lf()
    var cr = _cr()
    var quotes = _quotes()
    out[2] = 0
    out[3] = 0
    if strspn(src + p, BSLASH) > 0:
        # A line continuation, and nothing else: a backslash anywhere else is
        # "unexpected character after line continuation character".
        if p + 1 < n and strspn(src + p + 1, lf) > 0:
            _put(out, 0, CLS_CONT)
            out[1] = p + 2
            return 0
        if p + 2 < n and strspn(src + p + 1, cr) > 0 and \
                strspn(src + p + 2, lf) > 0:
            _put(out, 0, CLS_CONT)
            out[1] = p + 3
            return 0
        _put(out, 0, CLS_ERR)
        return 1
    if strspn(src + p, HASH) > 0:
        _put(out, 0, COMMENT_K)
        out[1] = p + strcspn(src + p, lf)
        return 0
    if strspn(src + p, DIGITS) > 0:
        return _pack_number(src, p, out)
    if strspn(src + p, DOT) > 0 and p + 1 < n and \
            strspn(src + p + 1, DIGITS) > 0:
        return _pack_number(src, p, out)
    m = strspn(src + p, istart)
    if m > 0:
        m = strspn(src + p, icont)
        return _pack_name(src, p, n, m, _quotes(), out)
    if strspn(src + p, quotes) > 0:
        var e = _skip_string(src, p, n)
        if e < 0:
            _put(out, 0, CLS_ERR)
            return 1
        _put(out, 0, STRING_K)
        out[1] = e
        return 0
    adv = _oplen(src, p)
    _put(out, 0, OP_K)
    out[1] = p + adv
    out[2] = _opclass(src, p, adv)
    return 0


def _line_kind(depth: int, lstate: int) -> int:
    """NEWLINE if this line break ends a logical line, NL otherwise.

    A function rather than two constants read into `k` in `_lex`, and for the
    measured reason `_pack_name` documents: a module-level constant bound to a
    local is refused on this path. The rule it answers is CPython's own — a
    newline inside brackets and a newline on a line with no tokens on it are
    both NL, and only the end of a logical line is a NEWLINE.
    """
    if depth == 0 and lstate == 2:
        return NEWLINE_K
    return NL_K


# ── the tokenizer, and the statement check that rides on it ────────────────

def _end_of_source(out, st, line: int, mode: int, nind: int) -> int:
    """The tail every end-of-source path shares: the DEDENTs back to column 0
    and the ENDMARKER, and nothing else. Returns the token count.

    `line` is the line the ENDMARKER is reported on and the caller has already
    settled it, because CPython's rule is "the line after the last line of the
    file": `""` gives (1, 0), `"   "` and `"x=1"` give (2, 0), `"x = 1\n"` gives
    (2, 0) and `"\n\n"` gives (3, 0) — all measured, and the DEDENTs before it
    are on that same line at column 0.
    """
    if mode == MODE_STREAM:
        while nind > 1:
            nind = nind - 1
            if _put_tok(out, st, DEDENT_K, line, 0) == 0:
                return TOKEN_FULL
        if _put_tok(out, st, ENDMARKER_K, line, 0) == 0:
            return TOKEN_FULL
    return st[0]


def _put_tok(out, st, k: int, line: int, col: int) -> int:
    """Record one token, honouring the window `st` describes. 0 = the window is
    full, 1 = recorded (or deliberately skipped, see below).

    `st` is the caller's THREE-word window: `st[0]` the absolute token index,
    `st[1]` the index the window starts at, `st[2]` how many tokens it holds.
    A list and not a packed word for the reasons `_classify` gives, and because
    a list is the only container a formal value can be at all.

    The window is what lets a caller tokenize a source with more tokens than
    one buffer holds: `st[1]` skips the tokens before the window without
    emitting them, and `st[0]` still counts every token, so the value
    `tokenize_from` returns is the stream's true length however many calls it
    took.
    """
    var nt = st[0]
    if nt - st[1] >= st[2]:
        return 0
    if nt >= st[1]:
        _emit(out, nt - st[1], k, line, col, st[2])
    st[0] = nt + 1
    return 1


def _ends_bad(cend: int, chdr: int, cneed: int, cexpr: int,
              lstate: int) -> int:
    """1 if the simple statement that has just ended may not end where it did.

    THE rule that reads a statement as a whole rather than token by token, and
    it is asked at the two places a statement can end: at its NEWLINE and at
    the end of the source when there was no NEWLINE. Three ways to fail:

      * it ends in an operator that cannot end one (`x =`, `x +`, `x ==`),
        unless the line opened with a keyword whose line ends in a colon —
        which is what keeps `if x:` from being read as ending in `:`;
      * it ends in a `def` or `class` with no name after it (`class` alone);
      * it ends in a keyword that wants an expression (`x = 1 if`), which
        `cend` does not see because a NAME may end a statement.

    `cneed` and `cexpr` are deliberately not cleared at a NEWLINE: they can
    only be set at depth 0 by a token that no valid statement ends with, so
    seeing one here IS the refusal.
    """
    if lstate == 2 and cend == 0 and chdr == 0:
        return 1
    if cneed != 0:
        return 1
    if cexpr != 0:
        return 1
    return 0


def _lex(src: str, out, cap: int, mode: int, first: int) -> int:
    """The token stream of `src`, three words per token, into the caller's
    `out`; or, in MODE_CHECK, whether `src` is a valid Python module.

    `first` is the index of the first token to RECORD: the tokens before it are
    counted and discarded, which is how a caller walks a stream too long for one
    buffer (see `_put_tok`).

    One function and one loop, because the alternatives are worse on this
    target: a recursive-descent lexer needs a stack as deep as the file's
    bracket nesting, and the machine stack under this entry stub holds about
    60 frames (measured — `rec(60)` returns and `rec(62)` segfaults), so the
    nesting state is here as two fixed-size lists in this frame instead.

    The loop has two halves, which is CPython's own structure. `atbol` is set
    only just after a line break OUTSIDE brackets, and that is where
    indentation, blank lines and comment-only lines are decided; everywhere
    else the loop is a token loop in which a newline is NL, the indentation is
    not read at all, and every token — whatever it is, from either half — goes
    through `_put_tok`, so the statement check below sees every token once.

    MODE_CHECK is the same loop with the checks switched on, and it returns 1
    (valid), 2 (a structural error) or TOKEN_ERROR (a lexical one). The checks
    are here rather than in a second pass because they need the token's own
    source position — `x = 1 +` is an error because of the operator's TEXT, and
    a stream of kind codes has forgotten it by the time a second pass would
    look.
    """
    var ident = _ident()
    var identc = _ident_cont()
    var blanks = _blanks()
    # `_chars` is called once per token and it needs these two, so they are
    # built HERE, once per scan, rather than inside it: `str_alloc` is a
    # `malloc`, and a malloc per token is 20k leaked allocations on a file
    # this size. There is no module-level state to cache them in — see the
    # module docstring — so the frame is the cache.
    var cont = _cont()
    var notc = _not_cont()
    var tab = _tab()
    var ff = _formfeed()
    var lf = _lf()
    var cr = _cr()
    # `ind[0]` is column 0, and `brk[d]` is the kind of the bracket at depth d.
    # Both are lists in THIS frame, read and written here and never handed out.
    var ind = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    var brk = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    # `_classify`'s four-word answer (kind, end, operator class, name length) and
    # `_put_tok`'s three-word window. Both are lists because a function returns
    # one word on this path; see `_classify`.
    var cl = [0, 0, 0, 0]
    var st = [0, first, cap]
    var n = str_len(src)
    var p = 0
    var line = 1
    var ls = 0            # where the current line starts, for the column
    var depth = 0
    var atbol = 1
    # 0: nothing on this logical line, 1: a comment, 2: a real token. This is
    # what decides NEWLINE against NL at the end of a line, and it is why a
    # comment-only line ends in NL and `x = 1  # c` ends in NEWLINE.
    var lstate = 0
    # `sstart` is 1 while the current SIMPLE statement has no token in it yet.
    # It is not the same question as `lstate`, and keeping them apart is what
    # makes `a=1;;` right: `;` is a token, so the line HAS content and ends in
    # a NEWLINE, and it also ends the statement, so the next `;` is the first
    # token of an empty statement — which is what CPython's parser refuses and
    # its tokenizer accepts (measured on both).
    var sstart = 1
    var nind = 1
    var i = 0
    var j = 0
    var w = 0
    var m = 0
    var t = 0
    var e = 0
    var k = 0
    var oc = 0
    # The statement check's state. `cend` is "the last token of this simple
    # statement may end it", `chdr` "this line opened with a keyword whose line
    # ends in a colon", `cneed`/`cexpr` "the next token must be a name / must
    # start an expression (class 2 also allows a `:`, for a bare `except:`)",
    # `cprev` "the last token was an opener or a comma", `cfrom` "this simple
    # statement is a `from` import", and `cbad` the refusal itself, kept as a
    # flag so that ONE report is enough and the rest of the file is still
    # scanned.
    var cend = 0
    var chdr = 0
    var cneed = 0
    var cexpr = 0
    var cprev = 0
    var cfrom = 0
    var cbad = 0
    while 1:
        if atbol == 1 and depth == 0:
            # ── a line that may be blank, a comment, or the start of a block ──
            m = strspn(src + p, blanks)
            if m > 0 and strspn(src + p, SP) == m:
                w = m
            else:
                # At least one tab or form feed in the run, so the column has to
                # be walked: a tab advances to the next multiple of 8 and a
                # form feed resets the column to 0, which is CPython's rule
                # (`strspn` cannot tell the three apart).
                w = 0
                i = 0
                while i < m:
                    if strspn(src + p + i, tab) > 0:
                        w = ((w >> 3) + 1) << 3
                    if strspn(src + p + i, ff) > 0:
                        w = 0
                    if strspn(src + p + i, tab) == 0 and \
                            strspn(src + p + i, ff) == 0:
                        w = w + 1
                    i = i + 1
            i = p + m
            if i >= n:
                # End of the source on a line that never had code on it. A run
                # of blanks with nothing after it is the file's last NL (`"   "`
                # gives NL then ENDMARKER — measured); a logical line with
                # tokens in it owes its NEWLINE, and that case is the TOKEN
                # LOOP's end-of-source below, not this one, because `atbol` is
                # set only straight after a NEWLINE.
                if m > 0:
                    if mode == MODE_STREAM:
                        if _put_tok(out, st, NL_K, line, _chars(src, ls, i, cont, notc)) == 0:
                            return TOKEN_FULL
                if mode == MODE_CHECK:
                    if cbad == 0:
                        return 1
                    return 2
                if n > 0 and strspn(src + n - 1, lf) == 0:
                    line = line + 1
                return _end_of_source(out, st, line, mode, nind)
            if strspn(src + i, HASH) > 0:
                j = i + strcspn(src + i, lf)
                if mode == MODE_STREAM:
                    if _put_tok(out, st, COMMENT_K, line, _chars(src, ls, i, cont, notc)) == 0:
                        return TOKEN_FULL
                p = j
                atbol = 0
                lstate = 1
                continue
            if strspn(src + i, lf) > 0:
                if mode == MODE_STREAM:
                    if _put_tok(out, st, NL_K, line, _chars(src, ls, i, cont, notc)) == 0:
                        return TOKEN_FULL
                p = i + 1
                line = line + 1
                ls = p
                continue
            # A line with code on it: the indentation decides INDENT/DEDENT.
            if w > ind[nind - 1]:
                if nind >= INDENT_CAP:
                    return TOKEN_ERROR
                nind = nind + 1
                ind[nind - 1] = w
                if mode == MODE_STREAM:
                    if _put_tok(out, st, INDENT_K, line, 0) == 0:
                        return TOKEN_FULL
            else:
                while w < ind[nind - 1]:
                    nind = nind - 1
                    if mode == MODE_STREAM:
                        # The DEDENT's column is the indentation of the line
                        # it dedents TO — `w`, the width of the line being
                        # started — and not the level it lands on and not zero.
                        # CPython reports both DEDENTs of a two-level dedent to
                        # column 0 at (4, 0) and the single DEDENT of an
                        # eight-to-four dedent at (4, 4), and every DEDENT at
                        # the end of a file at column 0 (all measured).
                        if _put_tok(out, st, DEDENT_K, line, w) == 0:
                            return TOKEN_FULL
                if w != ind[nind - 1]:
                    # A dedent to a column that is on no enclosing level:
                    # CPython raises IndentationError here, and so does this.
                    return TOKEN_ERROR
            p = i
            atbol = 0
            lstate = 0
            sstart = 1
            cfrom = 0
            continue
        # ── a token ──
        p = p + strspn(src + p, blanks)
        if p >= n:
            if depth > 0:
                # The end of the source inside an open bracket: CPython raises
                # "unexpected EOF in multi-line statement" here, and so does
                # this (measured on `f(1` and `def f(:`).
                return TOKEN_ERROR
            # End of the source in the middle of a logical line: it still owes
            # a NEWLINE if it has tokens (`"x=1"` gives NAME OP NUMBER NEWLINE
            # ENDMARKER — measured) and an NL if the last thing on it was a
            # comment (`"x=1\n# c"` gives … NEWLINE COMMENT NL ENDMARKER).
            if lstate == 2:
                if mode == MODE_STREAM:
                    if _put_tok(out, st, NEWLINE_K, line, _chars(src, ls, p, cont, notc)) == 0:
                        return TOKEN_FULL
                if mode == MODE_CHECK and cbad == 0 and \
                        _ends_bad(cend, chdr, cneed, cexpr, lstate) == 1:
                    cbad = 1
            if lstate == 1:
                if mode == MODE_STREAM:
                    if _put_tok(out, st, NL_K, line, _chars(src, ls, p, cont, notc)) == 0:
                        return TOKEN_FULL
            if mode == MODE_CHECK:
                if cbad == 0:
                    return 1
                return 2
            if n > 0 and strspn(src + n - 1, lf) == 0:
                line = line + 1
            return _end_of_source(out, st, line, mode, nind)
        # A line break is decided HERE rather than in `_classify`, because
        # whether it is an NL or a NEWLINE depends on `depth` and `lstate`,
        # which are this function's state and not an argument of a classifier.
        e = 0
        if strspn(src + p, lf) > 0 or \
                (strspn(src + p, cr) > 0 and p + 1 < n and
                 strspn(src + p + 1, lf) > 0):
            e = p + 1
            if strspn(src + p, cr) > 0:
                e = p + 2
            k = _line_kind(depth, lstate)
            oc = 0
            m = 0
        else:
            if _classify(src, p, n, ident, identc, cl) == 1:
                return TOKEN_ERROR
            k = cl[0]
            e = cl[1]
            oc = cl[2]
            m = cl[3]
        if k == CLS_CONT:
            # A line continuation produces no token at all — and one that ends
            # the file is an error, which is CPython's "unexpected EOF in
            # multi-line statement" (measured on `"x = 1 \\\n"`).
            p = e
            if p >= n:
                return TOKEN_ERROR
            line = line + 1
            ls = p
            continue
        # ── the one emit, and the one place the statement check runs ──
        if mode == MODE_STREAM:
            if _put_tok(out, st, k, line, _chars(src, ls, p, cont, notc)) == 0:
                return TOKEN_FULL
        if mode == MODE_CHECK and cbad == 0:
            if k == NEWLINE_K:
                if _ends_bad(cend, chdr, cneed, cexpr, lstate) == 1:
                    cbad = 1
            else:
                if k == OP_K:
                    if oc >= 4 and oc <= 6:
                        # A closer. `f(1]` is a CLEAN token stream — `tokenize`
                        # accepts it and its parser does not — so the bracket
                        # rules live HERE and not in the tokenizer.
                        if depth == 0:
                            cbad = 1
                        if depth > 0 and brk[depth - 1] != oc - 3:
                            cbad = 1
                    if oc == 7 and (cprev == 1 or cprev == 2):
                        cbad = 1
                # `cend` is updated by EVERY token, including the ones inside
                # brackets: a logical line's LAST token is at depth 0, so a
                # `)` that may end a statement has to have said so while the
                # depth was still 1.
                cend = 1
                if k == OP_K and (oc == 1 or oc == 2 or oc == 3 or
                                  oc == 9 or oc == 10):
                    cend = 0
                # `from a import *` ENDS in a `*`, which is otherwise an
                # operator that cannot end a statement — and it is a one-word
                # exception, not a general one: `x = *` is still refused
                # (measured on both).
                if k == OP_K and oc == 9 and cfrom == 1 and m <= 2 and \
                        strspn(src + p, STAR) > 0:
                    cend = 1
                if depth == 0:
                    # The rest of the statement rules, and only outside
                    # brackets: an operator inside `f(...)` is an expression's
                    # business, which is what lets a logical line span lines.
                    # `;` is in this set because an EMPTY simple statement is
                    # not Python: `tokenize` accepts `";"` and `"a=1;;"` as
                    # clean token streams and CPython's parser refuses both
                    # (measured). A `;` may END a statement, which is a
                    # different rule and is not here.
                    if k == OP_K and sstart == 1 and \
                            (oc == 10 or oc == 7 or oc == 8 or
                             (oc >= 4 and oc <= 6)):
                        cbad = 1
                    if cneed == 1 and k != NAME_K:
                        cbad = 1
                    if cexpr != 0 and k != NAME_K and k != NUMBER_K and \
                            k != STRING_K and k != FSTRING_K and \
                            k != TSTRING_K and oc != 1 and oc != 2 and \
                            oc != 3 and oc != 9:
                        # `except` alone is legal — `try: pass` / `except: pass`
                        # compiles, and there is one in the CPython corpus
                        # (`Lib/_pyio.py`), so it gets its own class in
                        # `_is_expr_kw` and a `:` is let through here.
                        if cexpr == 1:
                            cbad = 1
                        if cexpr == 2 and strncmp(src + p, ":", 1) != 0:
                            cbad = 1
                    cneed = 0
                    cexpr = 0
                    if k == NAME_K:
                        if m == 3 and strncmp(src + p, "def", 3) == 0:
                            cneed = 1
                        if m == 5 and strncmp(src + p, "class", 5) == 0:
                            cneed = 1
                        if sstart == 1 and m == 4 and \
                                strncmp(src + p, "from", 4) == 0:
                            cfrom = 1
                        cexpr = _is_expr_kw(src, p, m)
                        if sstart == 1 and _is_header_kw(src, p, m) == 1:
                            chdr = 1
                cprev = 0
                if k == OP_K and (oc == 1 or oc == 2 or oc == 3):
                    cprev = 1
                if k == OP_K and oc == 7:
                    cprev = 2
        # ── the state every token updates, whether or not it is checked ──
        if k == OP_K:
            if oc == 1 or oc == 2 or oc == 3:
                if depth >= BRACKET_CAP:
                    return TOKEN_ERROR
                brk[depth] = oc
                depth = depth + 1
            if oc == 4 or oc == 5 or oc == 6:
                if depth > 0:
                    depth = depth - 1
            if oc == 8:
                lstate = 0            # a `;` opens the next simple statement
        if k == NEWLINE_K:
            lstate = 0
            chdr = 0
            cend = 0
        # Any token at all makes the line have content, which is what decides
        # NEWLINE against NL — and `;` is a token, so `a=1;` ends in a NEWLINE
        # even though the statement it opened is empty.
        if lstate == 0:
            if k != NL_K and k != COMMENT_K and k != NEWLINE_K:
                lstate = 2
        if k == OP_K and oc == 8:
            sstart = 1
            cfrom = 0
        if k != NL_K and k != COMMENT_K and k != NEWLINE_K:
            if k != OP_K or oc != 8:
                sstart = 0
        if k == NAME_K or k == NUMBER_K or k == STRING_K or \
                k == FSTRING_K or k == TSTRING_K:
            sstart = 0
        if k == NEWLINE_K or k == NL_K:
            p = e
            line = line + 1
            ls = p
            # `atbol` only OUTSIDE brackets: inside them a line break is an NL
            # and the next line continues the same logical line, so treating it
            # as a line start would send the tokenizer back through the
            # indentation path and read the rest of the line as a fresh
            # statement — measured, `f(\n1\n)\n` lost its NEWLINE that way.
            if depth == 0:
                atbol = 1
            continue
        if k == COMMENT_K:
            p = e
            if lstate == 0:
                lstate = 1
            continue
        # A token may SPAN lines — a triple-quoted string is the only one that
        # can — and then every line break inside it is a line, and the column
        # after it is measured from the last one. CPython reports the NEWLINE
        # after `x = \'\'\'a\nb\'\'\'` at (2, 4) (measured), which is what
        # this produces. One `strcspn` per token says whether there is a line
        # break inside it at all; the loop runs only for the tokens that have
        # one, and leaves `i` just past the last of them.
        t = e - p
        i = p
        j = strcspn(src + p, lf)
        if j < t:
            while 1:
                line = line + 1
                j = j + 1
                i = p + j
                m = strcspn(src + i, lf)
                # `m == 0` means the byte AT `i` is itself a line break (a
                # blank line inside the literal) or that there is none left;
                # `strspn` says which, and getting it wrong counts a docstring
                # with a blank line in it as one line instead of two.
                if m == 0 and strspn(src + i, lf) == 0:
                    break
                if j + m >= t:
                    break
                j = j + m
            ls = i
        p = e
    return st[0]


# ── the public surface ─────────────────────────────────────────────────────

def tokenize_from(src: str, first: int, out, cap: int) -> int:
    """`tokenize`, starting at token `first`: the tokens before it are counted
    and not recorded, and the answer is the stream's TOTAL length either way.

    This is how a caller walks a source with more tokens than one buffer holds.
    A buffer on this target is a list literal, and a list literal is emitted
    with a 12-bit store immediate, so at most 4095 words — 1365 tokens of three
    words each — and a bigger one is a compiler crash rather than a refusal
    (`bugs/CODEGEN_list_literal_over_4095_words_asserts.md`). A 30 KB Python
    file is around 8000 tokens, so the loop is not optional:

        first = 0
        while 1:
            n = tokenize_from(src, first, buf, 1365)
            if n < 0 or n <= first + 1365:
                break            # TOKEN_ERROR, or the window reached the end
            first = first + 1365

    The window is a re-scan, not a resume: each call lexes from the beginning
    and throws the earlier tokens away, which costs one pass per window and
    needs no state carried between them.
    """
    return _lex(src, out, cap, MODE_STREAM, first)


def tokenize(src: str, out, cap: int) -> int:
    """The token stream of `src`: three words per token in the CALLER's `out`.

    `out[3 * i]` is the kind code, `out[3 * i + 1]` the 1-based line and
    `out[3 * i + 2]` the 0-based column of token `i`. Returns the number of
    tokens, TOKEN_ERROR if `src` is not a tokenizable Python module, or
    TOKEN_FULL if `out` cannot hold `cap` of them — three different answers,
    because "this is not Python", "your buffer is too small" and "here is the
    stream" are three things a caller acts on differently.

    The buffer is the caller's because a list built here lives in this frame
    (`struct.mojo`'s limit 4), and a `malloc`'d buffer is not an alternative
    (see the module docstring for the measurement). `token_bound` is how a
    caller sizes it without guessing.

    An f-string or t-string is ONE token (the module docstring says why), and a
    source that reaches the end inside an open bracket, inside a string or
    after a dangling backslash is TOKEN_ERROR, where CPython raises
    "unexpected EOF in multi-line statement".
    """
    return _lex(src, out, cap, MODE_STREAM, 0)


def token_bound(src: str) -> int:
    """An UPPER BOUND on the number of tokens in `src`, so a caller can size a
    buffer for `tokenize` without guessing and without a retry loop.

    Three words per source byte, plus eight. Every token that consumes source
    consumes at least one byte, so there are at most `str_len(src)` of those; an
    INDENT and a DEDENT consume none and there is at most one of each per
    line; and ENDMARKER is one more. The bound is deliberately loose — a
    buffer three words per byte of source is cheap next to being wrong, and
    `test_ast_formal.py` checks the bound against the real count for every file
    in its corpus, so it is a bound and not a hope.
    """
    return 3 * str_len(src) + 8


def parse(src: str) -> int:
    """1 if `src` is a valid Python module by this module's rules, else 0.

    THE CLAIM, precisely: **this is a lexical and block-structure check, not a
    Python parser.** It runs the tokenizer and then these checks, and each is a
    rule CPython's own parser enforces:

      * the bytes tokenize at all — a string that never ends, a bracket left
        open, a dangling backslash, a malformed number, an unterminated
        literal: `tokenize` raises there, and this is CPython's first stage;
      * the brackets MATCH and CLOSE: `f(1]` is a clean token stream that
        `tokenize` accepts, and CPython's parser raises on it, as does this;
      * a simple statement does not START with an operator that cannot open
        one (`= 5`, `+ x` is fine but `, x` and `-> x` are not), and does not
        END with one (`x =`, `x +`, `x ==`), unless the line is a compound
        header, which is what stops `if x:` from being read as ending in `:`,
        or the operator is the `*` of a `from a import *`;
      * `def` and `class` are followed by a NAME;
      * `if`, `while`, `for`, `with` and `elif` are followed by something
        that can start an expression, and `except` by that or by a `:` (a bare
        `except:` is legal);
      * a comma does not directly follow an opening bracket or another comma
        (`f(,a)`).

    What it does NOT check, and what `bugs/FORMAL_ast_module_subset.md` lists in
    full: the EXPRESSION grammar, so `x = 1 +* 2` passes here and fails in
    CPython; a keyword used as a name (`def = 5`); `return`/`yield` outside a
    function; `await` outside `async def`; duplicate parameters; a `return` with
    a value in a generator. Each of those is a real gap and none of them is
    hidden: this is a LEXICAL validator, and the bug doc a reader is sent to
    says which half of the grammar is implemented.

    CPython raises `SyntaxError` for all of it. Raising is not available here —
    a `raise` lowers to a call to a symbol nothing defines — so the answer is a
    return value, the same degradation `struct.mojo` documents in its ERRORS
    section. **A caller must therefore not read 1 as "this file will compile";
    it means "the bytes and the block structure are sound".**
    """
    var unused = [0]
    var r = _lex(src, unused, 0, MODE_CHECK, 0)
    if r == 1:
        return 1
    return 0


def parse_reason(src: str) -> int:
    """Why `parse` said no: 0 valid, 1 a lexical error, 2 a structural one.

    The same scan as `parse`, with the two failure classes kept apart, because
    they are worth different things to a caller: a lexical error is a stray
    byte — a string that never ends, a bracket left open, a bad number — and a
    structural one is a shape the statement rules refuse. CPython raises
    `SyntaxError` for both; this is the closest the target gets to saying
    which, and it is `_lex`'s own return value rather than a second scan.
    """
    var unused = [0]
    var r = _lex(src, unused, 0, MODE_CHECK, 0)
    if r == 1:
        return 0
    if r == 2:
        return 2
    return 1


def token_name(kind: int) -> str:
    """CPython's name for a kind code: "NAME", "FSTRING_START", …

    `token.tok_name`, spelled out, and the public way to ask: the constants at
    the top of this module are literals, so they are substituted HERE and cannot
    be imported. A code this module never emits is "".
    """
    if kind == ENDMARKER_K:
        return "ENDMARKER"
    if kind == NAME_K:
        return "NAME"
    if kind == NUMBER_K:
        return "NUMBER"
    if kind == STRING_K:
        return "STRING"
    if kind == NEWLINE_K:
        return "NEWLINE"
    if kind == INDENT_K:
        return "INDENT"
    if kind == DEDENT_K:
        return "DEDENT"
    if kind == OP_K:
        return "OP"
    if kind == FSTRING_K:
        return "FSTRING_START"
    if kind == TSTRING_K:
        return "TSTRING_START"
    if kind == COMMENT_K:
        return "COMMENT"
    if kind == NL_K:
        return "NL"
    if kind == ERRORTOKEN_K:
        return "ERRORTOKEN"
    return ""
