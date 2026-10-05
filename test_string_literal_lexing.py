#!/usr/bin/env python3
r"""String-literal lexing, compared against CPython literal by literal.

Quote runs are spelled `Q3` (three double quotes) / `SQ3` throughout, because
a literal triple quote inside this docstring would close it and a bare
backslash-quote would be read as a line continuation.

The front end's rule for where a string literal ENDS is CPython's, and this is
the test that holds it to that. A backslash consumes the next character,
whatever it is, so a backslash-quote does not close a non-raw literal — in a
triple-quoted one as much as in a single-quoted one — and a backslash
immediately before a closing run therefore leaves the literal UNTERMINATED.

That rule has a consequence which used to be silent, and which is the whole
reason this file exists: a triple-quoted literal holding a backslash before a
closing run used to swallow the rest of the file (fixed in `fd10fd92`, which
made an unterminated literal a REFUSAL — `-1` from `_scan_string_end` — where it
had been "keep scanning"). A source line reading

    s = Q3 + backslash + Q3          # i.e. Q3 \ Q3

followed by more source, is an unterminated triple-quoted literal and CPython
says so. This front end used to accept it and hand the emitter a STRING token
whose value was the REST OF THE FILE. The build then succeeded — `def main():
var a = <the rest>` is a syntactically complete function — so the miscompile
was invisible at the only point anyone looks, and a program that printed two
lines printed nothing. The same class of silence had a second, sharper face
for single-quoted literals: there the delimiters were not swallowed but
DROPPED, so `x = "abc` parsed as `x = abc` and `x = it's` parsed as `x = it`
followed by a bare `s`. Both are now refusals, with CPython's own wording.

What this test asserts, per literal:

  * ACCEPT vs REFUSE must agree with `compile()`. This is the assertion that
    would have caught the bug, and it is a comparison rather than a fixed
    expectation so a future rule change has to be argued, not just noticed.
  * When both accept, the token BOUNDARY must agree — one STRING token, whose
    raw text runs from the opening delimiter to the closing one.
  * The VALUE is this path's own documented contract, not CPython's: a literal
    is stored byte-exact, with the delimiters stripped and NO escape processed,
    so a backslash-n inside a literal is two characters and `r"a\nb"` is four
    too. That is a deliberate divergence (a caller can put a backslash-heavy
    file into a literal and get it back byte for byte) and it is asserted
    separately from the boundary, because the two are independent questions:
    agreeing with CPython about where a literal ends is not the same question
    as what its characters are.

One end-to-end case builds an arm64 image and RUNS it, because "the tokenizer
agreed with CPython" is not the claim a caller depends on — "the program
printed the same thing" is, and the lowering is a separate implementation
(formal/arm64_codegen.py) from the evaluator. There are five of them now, one
per family of literal this file covers.

The third family is the one that generalizes. Every pre-pass that rewrites a
line used to do it without asking where the literals are, and each wrote a
character the source never wrote — a SPACE where a backslash-newline pair is
worth nothing, SPACES where a TAB is content, and a whole invented LINE BREAK
for any of the eight characters `str.splitlines()` calls a line break and the
language does not. So the two tables a reader should look at second are
`CONTINUATIONS` (the pair) and the control-character rows in `LITERALS`, and
between them they cover every character whose treatment in this front end is a
decision rather than an accident.

Run:  python3 test_string_literal_lexing.py [-v]
"""
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fire_compiler as F  # noqa: E402

FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60

Q3 = '"' * 3          # a triple-quote run
SQ3 = "'" * 3

# (name, the literal's source text, OUR expected value, CPython's expected
# value or None for "no cross-check")
#
# `ours` (the THIRD column) is the byte-exact content: source text between the
# delimiters, with no escape processing. It is spelled out for every row rather
# than derived, because "byte-exact" is a contract a reader has to be able to
# check by eye. A row whose value is a real newline is written '\n' in the
# table below and comes from a source line break.
#
# The fourth column is the oracle: when it is given, `check_continuation`
# requires BOTH sides to equal it, so a row carrying one is a row the two
# engines agree on and a row leaving it `None` is a labelled divergence. The
# two are not interchangeable and reading the table as (ours, theirs) is the
# mistake that made the first version of the raw-literal rows below assert a
# divergence that no longer existed.
LITERALS = [
    # ── the plain shapes: one STRING token, content is what is between ──────
    ("triple_plain",        Q3 + "abc" + Q3,                "abc"),
    ("triple_one_quote",    Q3 + 'a"b' + Q3,                'a"b'),
    ("triple_two_quotes",   Q3 + 'a""b' + Q3,               'a""b'),
    ("triple_mixed_quote",  Q3 + "a'b" + Q3,                "a'b"),
    ("triple_newline",      Q3 + "a\nb" + Q3,               "a\nb"),
    ("triple_hash",         Q3 + "a#b" + Q3,                "a#b"),
    ("sq_triple_plain",     SQ3 + "abc" + SQ3,              "abc"),
    ("sq_triple_inner",     SQ3 + "a'b" + SQ3,              "a'b"),
    ("triple_dq_inside_sq", SQ3 + 'say "hi"' + SQ3,         'say "hi"'),
    ("sq_inside_dq",        '"don\'t"',                     "don't"),
    ("dq_inside_sq",        "'say \"hi\"'",                 'say "hi"'),
    ("ordinary_dq",         '"abc"',                        "abc"),
    ("ordinary_sq",         "'abc'",                        "abc"),

    # ── backslash: where the literal ends, and what the characters are ─────
    # The four rows that pin the rule itself. `ours` is byte-exact so the
    # backslash is in the value; CPython's differs for every non-raw one, and
    # that difference is asserted as a value difference, never as a boundary
    # difference.
    ("triple_bs_n",         Q3 + "a\\nb" + Q3,              "a\\nb"),
    ("triple_bs_bs",        Q3 + "a\\\\b" + Q3,             "a\\\\b"),
    ("triple_bs_quote",     Q3 + 'a\\"b' + Q3,              'a\\"b'),
    ("triple_bs_then_run",  Q3 + '\\"b' + Q3,               '\\"b'),
    ("triple_bs_bs_close",  Q3 + "\\\\" + Q3,               "\\\\"),
    ("ordinary_bs_quote",   '"a\\"b"',                      'a\\"b'),
    ("raw_triple_bs_n",     'r' + Q3 + "a\\nb" + Q3,        "a\\nb"),
    ("raw_triple_bs_quote", 'r' + Q3 + 'a\\"b' + Q3,        'a\\"b'),

    # ── UNTERMINATED: CPython refuses, and so must this ────────────────────
    # These are the rows the bug doc's reproducer is. Before the fix every one
    # of them built successfully and produced a different program.
    ("term_bs_then_close",  Q3 + "\\" + Q3,                 None),
    ("term_sq_bs_close",    SQ3 + "\\" + SQ3,               None),
    ("term_dq_trailing_bs", '"abc\\"',                      None),
    ("term_sq_trailing_bs", "'abc\\'",                      None),
    ("term_dq_eol",         '"abc',                         None),
    ("term_sq_eol",         "'abc",                         None),
    ("term_dq_bare_quote",  '"',                            None),
    ("term_sq_bare_quote",  "'",                            None),
    # A five-quote run after a backslash: the backslash eats the first quote,
    # the NEXT THREE close the triple-quoted literal, and the fifth opens a
    # single-quoted one with nothing to close it. CPython reports
    # "unterminated string literal" here, not "triple-quoted" — the exact
    # distinction that made the old behaviour look like a near-miss.
    ("term_five_run",       Q3 + "\\" + '"' * 5,            None),

    # ── CHARACTERS `str.splitlines()` CALLS LINE BREAKS AND THE LANGUAGE DOES
    # NOT ──
    #
    # The tokenizer used `src.splitlines()`, and that also breaks on vertical
    # tab, form feed, the four C1 information separators, NEL, LINE SEPARATOR
    # and PARAGRAPH SEPARATOR. CPython's tokenizer breaks on none of them, so
    # each of these used to be cut in half: the literal produced NO STRING token
    # at all, and the diagnostic that followed named a line with no problem on
    # it. `ours` is the byte-exact content, so for these the value is a
    # one-character hole in a three-character string.
    ("vtab_in_a_literal",        '"a\vb"',  "a\vb"),
    ("formfeed_in_a_literal",    '"a\fb"',  "a\fb"),
    ("c1_fs_in_a_literal",       '"a\x1cb"', "a\x1cb"),
    ("c1_gs_in_a_literal",       '"a\x1db"', "a\x1db"),
    ("c1_rs_in_a_literal",       '"a\x1eb"', "a\x1eb"),
    ("nel_in_a_literal",         '"a\x85b"', "a\x85b"),
    ("line_separator_in_a_lit",  '"a\u2028b"', "a\u2028b"),
    ("para_separator_in_a_lit",  '"a\u2029b"', "a\u2029b"),
    ("vtab_in_a_single_quoted",  "'a\vb'",  "a\vb"),
    # The control row in the other direction: a C0 control character
    # `splitlines()` does NOT break on, so it worked by accident. It is here so
    # that a fix which narrowed the set the wrong way — to "any control
    # character" — goes red here instead of passing by coincidence.
    ("control_char_that_is_not_a_break", '"a\x1fb"', "a\x1fb"),
    # ── and the three that ARE line breaks, in a single-quoted literal ──
    #
    # A single-quoted literal may not cross a line break, so CPython refuses
    # each of these and so must this. `\r` is the row that used to be ACCEPTED
    # with its literal silently destroyed: `_scan_string_end` only knew about
    # `\n`, while the line split knew about `\r` — one function disagreeing with
    # the other about the same question, which is the shape this whole area has.
    ("lf_in_a_single_quoted",       "'a\nb'",   None),
    ("cr_in_a_single_quoted",       "'a\rb'",   None),
    ("crlf_in_a_single_quoted",     "'a\r\nb'", None),
    ("cr_in_a_double_quoted",       '"a\rb"',   None),
    # ── a TAB, which is whitespace to the tokenizer and CONTENT to a literal ──
    #
    # The per-line pass used `line.expandtabs(_INDENT_SIZE)` on the whole line,
    # which is for the INDENT and nothing else — `indent` is computed from the
    # leading run alone. In code a tab is whitespace either way, so expanding the
    # body changed no token; inside a literal it rewrote the value, and
    # `print("x<TAB>y")` printed `x y` here and `x<TAB>y` in CPython.
    ("tab_in_a_literal",     '"a\tb"',  "a\tb"),
    ("tab_in_a_single_quoted", "'a\tb'", "a\tb"),
    ("tab_in_a_triple",      '"""a\tb"""', "a\tb"),
]


# Programs that must keep their shape: a literal followed by more source. The
# reported failure was never "this one literal parsed wrong", it was "the rest
# of the file went into the literal", so the assertion is on the STATEMENTS
# that come after it, not on the literal.
#
# `stmts_in` says where to count: "top" for the module body, or the name of a
# function whose body is counted instead (a `def` is one top-level statement
# however much is inside it, which is precisely why a swallowed tail used to
# leave a program that still LOOKED complete).
PROGRAMS = {
    "rest_of_file_survives": (
        'def main():\n'
        '    var a = ' + Q3 + 'x' + Q3 + '\n'
        '    print(a)\n'
        '    print(1)\n', ("main", 3)),
    "rest_of_file_after_backslash_quote": (
        'def main():\n'
        '    var a = ' + Q3 + 'a\\"b' + Q3 + '\n'
        '    print(a)\n'
        '    print(1)\n', ("main", 3)),
    # The docstring case, where the literal spans two physical lines and the
    # newline-padding in the collapse has to keep every later line number where
    # it was — a swallowed tail here would still leave two functions.
    "docstring_then_code": (
        'def f():\n'
        '    ' + Q3 + 'line one\n'
        'line two' + Q3 + '\n'
        '    return 7\n'
        'def main():\n'
        '    return f()\n', ("top", 2)),
    # A backtick string is a Mojo string with no CPython counterpart, but it is
    # a STRING, and a quote inside one is not a delimiter. Both of these used to
    # be silently mangled: the apostrophe opened a phantom string, and the
    # triple-quote run was taken for a triple-quoted literal's OPENER, which ate
    # the backtick's own closing delimiter and everything after it.
    "backtick_holding_an_apostrophe": ("x = `it's fine`\n", ("top", 1)),
    "backtick_holding_a_triple_run": ("x = `a" + Q3 + "b`\n", ("top", 1)),
    # The reproducer from the bug doc, verbatim in shape: one statement fewer
    # than the source has lines, because the tail became the literal's value.
    "repro_from_the_bug_doc_is_refused": (
        'def main():\n'
        '    var a = ' + Q3 + "\\" + Q3 + '\n'
        '    print(a)\n'
        '    print(1)\n', None),
    # A line-break character `str.splitlines()` invented, inside a COMMENT and
    # after a quote. The split put `b"` on a line of its own, `_strip_inline_
    # comment` had already run on the half above it, and the tail became a bare
    # NAME statement — a SECOND top-level statement out of a one-statement
    # program, which then raised NameError on `b` and reported it against the
    # def below. The count is the whole assertion: the program ran, and ran
    # against a statement the source does not contain.
    "control_char_in_a_comment_is_not_a_line": (
        '# a\vb"\n'
        'def main():\n'
        '    return 7\n', ("top", 1)),
    # And the same character inside a real literal, where the split destroyed the
    # STRING token outright: the program was refused with a diagnostic naming a
    # line two below the one with the problem.
    "control_char_in_a_literal_keeps_the_program": (
        'def main():\n'
        '    var a = "x\vy"\n'
        '    return 7\n', ("main", 2)),
    # The guard in the other direction for the tab: a tab is still an INDENT.
    # `_indent_expanded` expands the leading run only, and a tab at the start of
    # a line lands on a column boundary, so the nesting must be unchanged — a
    # fix that stopped expanding tabs altogether would leave the inner `return`
    # at the outer level and this count would be 2.
    "tab_indentation_is_still_an_indent": (
        "def main():\n"
        "\tx = 1\n"
        "\tif x == 1:\n"
        "\t\treturn 7\n"
        "\treturn 0\n", ("main", 3)),
}

# A backslash-newline pair inside a literal is a LINE CONTINUATION, and
# CPython's tokenizer decides what it is worth before the parser ever sees the
# token — measured with `tokenize`, the STRING token's own text differs:
#
#     "a\<nl>b"        token text 'a\\nb'  → the pair is DELETED
#     r"a\<nl>b"       token text 'r"a\\\nb"' → the pair is KEPT, it is content
#
# so the rule is "deleted unless the literal is raw", and it is a rule about
# TOKEN TEXT, which is exactly what this path's byte-exact value contract is
# stated over. Before the fix the line-joining pass deleted the backslash and put
# a SPACE there, so `"ab\<nl>cd"` was `abcd` in CPython and `ab cd` here — a
# character the source never wrote, silently, in every one of these shapes.
#
# Each row is (name, the statement, the value HERE, the value CPython gives it,
# or None when CPython's answer is not the contract for this row — see the rows
# that say so). Where both are given they must be EQUAL, because that is the
# whole claim for a continuation: a line continuation is not an escape, so
# whether the pair is deleted or kept, CPython is the oracle for both.
CONTINUATIONS = [
    ("plain",              'a = "ab\\\ncd"',            "abcd",  "abcd"),
    # The next line's INDENTATION is content inside a string — CPython deletes
    # the pair and nothing else, so these are `ab` + four spaces + `cd`. The
    # old join put one space in and lstripped the four, which is two wrong
    # characters in opposite directions.
    ("indented_next_line", 'a = "ab\\\n    cd"',        "ab    cd", "ab    cd"),
    # The closing delimiter lands on the next physical line. The old join put
    # the space BEFORE the closing quote, so the value grew a trailing space
    # that no amount of reading the source would predict.
    ("closes_on_the_next_line", 'a = "ab\\\n"',         "ab",    "ab"),
    ("two_continuations",  'a = "a\\\nb\\\nc"',         "abc",   "abc"),
    ("single_quotes",      "a = 'p\\\nq'",              "pq",    "pq"),
    # A `b` prefix is dropped by this front end (it has no bytes type), so the
    # value is a `str` here and CPython's is a `bytes` — a different question
    # from what the pair is worth, and the row still pins that the pair is
    # worth nothing.
    ("bytes_prefix",       'a = b"ab\\\ncd"',           "abcd",  None),
    # A quote run that does not close the literal is literal CONTENT, and so is
    # the next line's `b"` — which is only true if the join invented nothing
    # between them. Both sides read this as two adjacent literals, so the
    # concatenation is the parser's and the value must be `xb`.
    ("quote_run_then_text", 'a = "x\\\n""b"',           "xb",    "xb"),
    # ── raw: the pair is CONTENT, and this path now keeps it ──
    #
    # A RAW literal keeps the pair — CPython's token text for it is
    # 'r"a\\\nb"' — and it did not used to, because a value only reaches the
    # token stream with a newline in it through the placeholder
    # `replace_multiline_strings` builds, and the join ran after it. The join
    # now builds a placeholder for the line break itself, so the STRING token
    # carries `a\` + a real newline + `b`, which is CPython's value byte for
    # byte: a raw literal processes no escapes, so there is nothing left for
    # the two to disagree about.
    ("raw_keeps_the_pair", 'a = r"a\\\nb"',
     "a\\\nb", "a\\\nb"),
    ("raw_single_quoted", "a = r'a\\\nb'", "a\\\nb", "a\\\nb"),
    # The same on a two-letter prefix. The `b` is dropped by this front end (it
    # has no bytes type) so CPython's value is a `bytes` — a different question
    # from what the pair is worth, so `ours` is compared to its own spelling
    # and CPython only decides that the pair survives.
    ("raw_bytes_prefix", 'a = rb"a\\\nb"', "a\\\nb", None),
    # Indentation is content here for the same reason it is in a non-raw
    # literal — the line is joined with nothing in front of it either way — and
    # both sides keep all four spaces.
    ("raw_indented_next_line", 'a = r"ab\\\n    cd"', "ab\\\n    cd",
     "ab\\\n    cd"),
    ("raw_closes_on_the_next_line", 'a = r"ab\\\n"', "ab\\\n", "ab\\\n"),
    ("raw_two_continuations", 'a = r"a\\\nb\\\nc"', "a\\\nb\\\nc",
     "a\\\nb\\\nc"),
    # ── the one row where this path's answer is NOT CPython's ──
    #
    # The same rule on a TRIPLE-quoted span, which is placeholdered as a whole
    # before the join runs and so does keep the pair — and CPython deletes it
    # there, because a triple-quoted literal is not raw either. Pre-existing,
    # unchanged by the join, and part of the same no-escape-processing contract
    # as `"\n"` being four characters rather than one: fixing it means editing
    # the VALUE a triple-quoted literal collapses to, which would change the
    # text of every docstring in the compiler and the stdlib that holds such a
    # pair — a different change, and one nothing here depends on.
    ("triple_keeps_the_pair_here_too", 'a = """ab\\\ncd"""',
     "ab\\\ncd", None),
    # The control for the row above, and for `raw_keeps_the_pair`: the same
    # source spelled raw, where both sides agree. A fix that taught the join to
    # keep every pair would go red here.
    ("raw_triple_agrees", 'a = r"""ab\\\ncd"""', "ab\\\ncd", "ab\\\ncd"),
]


def our_literal_value(text):
    """The value of the name `text` assigns, as this front end reads it."""
    src = "def main():\n    " + text + "\n    return a\n"
    stmts = F.Parser(F.py_tokenize_named(src, "<t>")).with_filename("<t>").parse_module()
    return _value_of(stmts[0].body[0].value)


def cpython_literal_value(text):
    """The same statement, run by CPython."""
    ns = {}
    exec("def main():\n    " + text + "\n    return a\n", ns)
    return ns["main"]()


def _value_of(expr):
    """The `value` of an expression that is one literal, or its evaluated
    string for the two forms a continuation can produce that are not a single
    literal node — adjacent literals, and a concatenation of them."""
    cls = type(expr).__name__
    if cls in ("StringLiteral", "IntLiteral", "BoolLiteral"):
        return expr.value
    if cls == "BinaryOp" and expr.op == "+":
        return _value_of(expr.left) + _value_of(expr.right)
    raise AssertionError(f"{cls} is not a literal this check can read a value "
                         f"from: {expr!r}")


def check_continuation(name, text, ours_expected, cpython_expected, verbose):
    try:
        ours = our_literal_value(text)
    except SyntaxError as e:
        return False, (f"continuation {name}: refused a literal CPython accepts "
                       f"({text!r}): {e}")
    if ours != ours_expected:
        return False, (f"continuation {name}: {text!r} is {ours!r} here, "
                       f"expected {ours_expected!r}")
    if cpython_expected is not None:
        try:
            theirs = cpython_literal_value(text)
        except SyntaxError as e:
            return False, (f"continuation {name}: the row is not valid Python "
                           f"({text!r}): {e} — a row that cannot be the oracle "
                           f"is not a row")
        if theirs != cpython_expected or ours != theirs:
            return False, (f"continuation {name}: {text!r} is {ours!r} here and "
                           f"{theirs!r} in CPython, expected {cpython_expected!r} "
                           f"from both")
    if verbose:
        note = "" if cpython_expected is None else f"   (CPython: {cpython_expected!r})"
        print(f"  continuation {name:34s} {text!r} -> {ours!r}{note}")
    return True, ""


def check_code_continuation_is_unchanged(verbose):
    r"""The guard in the other direction: OUTSIDE a string the pair is still a
    line continuation, and the space the join has always put there is what keeps
    `1 +` and `2` two tokens. A fix that dropped the space unconditionally would
    glue them into one NAME, and would break every backslash continuation in the
    392 `.mojo` files on this tree — the pair is common there, just never inside
    a literal."""
    src = ("def main():\n"
           "    a = 1 + \\\n"
           "        2\n"
           "    return a\n")
    try:
        stmts = F.Parser(F.py_tokenize_named(src, "<t>")).with_filename("<t>").parse_module()
    except SyntaxError as e:
        return False, f"a backslash continuation in plain code was refused: {e}"
    body = stmts[0].body
    if [type(s).__name__ for s in body] != ["AssignStmt", "ReturnStmt"]:
        return False, (f"a backslash continuation in plain code parsed into "
                       f"{[type(s).__name__ for s in body]}, expected the assign "
                       f"and the return: {body!r} — the pair no longer joins the "
                       f"lines")
    expr = body[0].value
    if type(expr).__name__ != "BinaryOp" or expr.op != "+":
        return False, (f"'1 + \\\\<nl> 2' read as {expr!r}, so the two operands "
                       f"were glued into one token")
    ns = {}
    exec(src, ns)
    if ns["main"]() != 3:
        return False, f"CPython disagrees about '1 + \\\\<nl> 2': {ns['main']()!r}"
    if verbose:
        print(f"  continuation {'code_join':34s} '1 + \\\\\\n 2' -> "
              f"BinaryOp('+')")
    return True, ""


def cpython_verdict(literal):
    """('ok', value) if CPython accepts the literal, else ('refuse', msg)."""
    try:
        return ("ok", eval(literal, {"__builtins__": {}}, {}))
    except SyntaxError as e:
        return ("refuse", e.msg)
    except ValueError as e:
        # e.g. an unescaped backslash inside a bytes literal is a ValueError,
        # not a SyntaxError; it is still a refusal.
        return ("refuse", str(e))


def our_verdict(literal):
    """('ok', [(kind, value), ...]) or ('refuse', message).

    Goes through the whole front end — tokenize AND parse — because the bug was
    only ever visible at the boundary between them: the tokenizer emitted a
    token, the parser had nothing to complain about, and the emitter got a
    string containing someone else's source code.
    """
    src = "s = " + literal + "\n"
    try:
        tokens = F.Parser(F.py_tokenize_named(src, "<t>")).with_filename("<t>").parse_module()
    except SyntaxError as e:
        return ("refuse", str(e))
    strings = [(t.kind, t.value) for t in F.py_tokenize_named(src, "<t>")
               if t.kind == "STRING"]
    return ("ok", strings)


def our_literal_flag(text):
    """(the literal's `value`, its `is_interpolated`) as this front end reads it."""
    src = "def main():\n    " + text + "\n    return a\n"
    stmts = F.Parser(F.py_tokenize_named(src, "<t>")).with_filename("<t>").parse_module()
    lit = stmts[0].body[0].value
    return lit.value, lit.is_interpolated


# (name, the assignment's right-hand side, expected value, expected
# is_interpolated). CPython is not the oracle for the flag — it has no such
# notion, and this compiler's f-strings are its own — but `check_literal` above
# already pins each spelling's VALUE against CPython, and the value is half of
# what makes these rows bite: the two halves are only separable if the value is
# the thing being asked about, and it is.
FLAG_ROWS = [
    # The row the whole flag exists for, and the control for it. Both values
    # start with `f"`. `'f"n"'` is a four-character string that CPython prints
    # as `f"n"`; `f"n={n}"` interpolates. Asked of the value they are the same
    # question, and the prefix test answered `n` for both — on the interpreter
    # and the compiled path, silently, and as a REFUSAL on the formal ones.
    ("body_that_starts_with_f_quote", 'a = \'f"n"\'', 'f"n"', False),
    ("interpolated_f_string", 'a = f"n={n}"', 'f"n={n}"', True),
    ("body_that_starts_with_t_quote", 'a = "t\'x\'"', "t'x'", False),
    ("interpolated_t_string", 'a = t"v={v}"', 't"v={v}"', True),
    # The UPPERCASE spellings, which are the other half of the same question:
    # `_raw_string_is_ftstring` accepts `F`/`T` and the compiled path always
    # did, while the interpreter's own prefix test listed only `f"`/`t"` — so
    # `F"q={q}"` interpolated on one engine and printed its own source text on
    # the other. The flag agrees with CPython on both.
    ("body_that_starts_with_capital_f", "a = 'F\"q\"'", 'F"q"', False),
    ("interpolated_capital_f", 'a = F"q={q}"', 'F"q={q}"', True),
    # The escape is what makes the middle row work: with the inner and outer
    # quote THE SAME the `\"` survives into the value, so it starts `f\` and
    # every reader was right by accident. These two pin that the flag does not
    # depend on that accident.
    ("escaped_inner_quote_same_kind", 'a = "f\\"n\\""', 'f\\"n\\"', False),
    # A run that merges into an f-string (`f"a" "b"` is `f"""ab"""`) and a
    # `r`-looking body, which the prefix walk used to take the `r` off and the
    # quotes with it.
    ("merged_run_with_one_f_part", 'a = f"a" "b"', 'f"""ab"""', True),
    ("body_that_starts_with_r_quote", "a = 'r\"x\"'", 'r"x"', False),
    # Triple-quoted, both ways: the `f` one keeps its token (and interpolates),
    # the plain one arrives from the placeholder cache already stripped to its
    # body — so the two cannot be told apart from the value either.
    ("triple_quoted_interpolated", 'a = f"""a={n}"""', 'f"""a={n}"""', True),
    ("triple_quoted_ordinary", 'a = """doc"""', 'doc', False),
]


def check_interpolated_flag(verbose):
    """`StringLiteral.is_interpolated` has to answer for the VALUE as well.

    An interpolated literal's value is its whole source token and an ordinary
    one's is its body, so a body may begin with `f"` or `t'` or `F"` all by
    itself. Every engine used to decide "interpolated?" by sniffing the value's
    first two characters, which cannot tell those apart: the interpreter and the
    compiled path printed `n` for `'f"n"'`, and the formal backends refused
    correct code for it. The parser decides from the source token
    (`_raw_string_is_ftstring`) and the node carries the answer, so these rows
    are the two halves of one question side by side — and both are checked
    against the value the parser produced, because a flag that disagreed with
    its own node would be a worse bug than the one it replaced.
    """
    failures = []
    for name, text, expected_value, expected_flag in FLAG_ROWS:
        try:
            value, flag = our_literal_flag(text)
        except SyntaxError as e:
            failures.append(f"interpolated flag {name}: refused a literal CPython "
                            f"accepts ({text!r}): {e}")
            continue
        if value != expected_value or flag != expected_flag:
            failures.append(
                f"interpolated flag {name}: {text!r} parsed to value {value!r} "
                f"is_interpolated={flag}, expected {expected_value!r} / "
                f"{expected_flag} — the value and the flag are one answer, and a "
                f"reader that asked the value instead of the flag is what this "
                f"row exists to catch")
        elif verbose:
            print(f"  flag         {name:34s} {text!r} -> {value!r} "
                  f"interpolated={flag}")
    return (not failures), "; ".join(failures)


def check_literal(name, literal, expected_ours, verbose):
    cp = cpython_verdict(literal)
    ours = our_verdict(literal)
    if cp[0] != ours[0]:
        return False, (f"{name}: CPython says {cp[0]} ({cp[1]!r}) and this front "
                       f"end says {ours[0]} ({ours[1]!r}) for the literal "
                       f"{literal!r} — one of the two is wrong, and a literal "
                       f"whose boundary disagrees with CPython's is the "
                       f"silent-miscompile class this file exists for")
    if cp[0] == "refuse":
        if verbose:
            print(f"  both refuse  {name:28s} {literal!r} -> {ours[1]}")
        return True, ""

    # Both accept. Exactly one STRING token, spanning the whole literal.
    strings = ours[1]
    if len(strings) != 1 or strings[0][1] != literal:
        return False, (f"{name}: accepted {literal!r} as {len(strings)} STRING "
                       f"token(s) {strings!r}; expected exactly one spanning the "
                       f"whole literal, so the boundary matches CPython's")
    # And the value, which is this path's own byte-exact contract.
    value = F.Parser(F.py_tokenize_named("s = " + literal + "\n", "<t>")
                     ).with_filename("<t>").parse_module()[0].value.value
    if expected_ours is not None and value != expected_ours:
        return False, (f"{name}: the literal {literal!r} parsed to {value!r}, "
                       f"expected the byte-exact content {expected_ours!r}")
    if verbose:
        print(f"  both accept  {name:28s} {literal!r} -> {value!r}"
              f"   (CPython: {cp[1]!r})")
    return True, ""


def check_program(name, source, shape, verbose):
    """`shape` is (where, count) or None, meaning "this must be refused"."""
    if shape is None:
        try:
            F.Parser(F.py_tokenize_named(source, "<t>")).with_filename("<t>").parse_module()
        except SyntaxError as e:
            if verbose:
                print(f"  refused     {name:36s} {e}")
            return True, ""
        return False, (f"{name}: accepted a program CPython refuses, so the "
                       f"source after an unterminated literal was silently "
                       f"absorbed into it")

    where, count = shape
    try:
        stmts = F.Parser(F.py_tokenize_named(source, "<t>")).with_filename("<t>").parse_module()
    except SyntaxError as e:
        return False, f"{name}: refused a program CPython accepts: {e}"
    body = stmts
    if where != "top":
        body = [s for s in stmts
                if type(s).__name__ == "FunctionDef" and s.name == where]
        if len(body) != 1:
            return False, f"{name}: no function named {where!r} in {stmts!r}"
        body = body[0].body
    if len(body) != count:
        return False, (f"{name}: parsed into {len(body)} statement(s) where the "
                       f"source has {count}: {body!r} — this is the "
                       f"swallowed-source shape (a literal's value running on "
                       f"into the code after it)")
    if verbose:
        print(f"  shape kept   {name:36s} {len(body)} statement(s)")
    return True, ""


def check_refusal_message(verbose):
    """The refusal must name the file, the line and the construct."""
    src = ('def main():\n'
           '    var a = ' + Q3 + "\\" + Q3 + '\n'
           '    print(a)\n')
    try:
        F.py_tokenize_named(src, "some/file.mojo")
    except SyntaxError as e:
        text = str(e)
        for needle in ("some/file.mojo", ":2:", "unterminated triple-quoted "
                       "string literal"):
            if needle not in text:
                return False, (f"the refusal {text!r} does not name {needle!r}; a "
                               f"message that is vague about where the problem is "
                               f"is barely better than the silence")
        if verbose:
            print(f"  refusal      {text}")
        return True, ""
    return False, "an unterminated triple-quoted literal was accepted"


def run_end_to_end(verbose):
    """Build an arm64 image, RUN it, and compare with CPython on the same text.

    The lowering is a separate implementation from the interpreter, so agreeing
    about token boundaries upstream says nothing about the bytes that come out
    of the emitter. Two programs, because the two halves of the contract need
    different oracles:

    `agree` holds literals with NO backslash in them, so this path's byte-exact
    value and CPython's escape-processed value are the same string and CPython
    can be the oracle outright — same text, same stdout, same exit status. That
    is the strongest form and it is the one a caller can act on.

    `byte_exact` used to hold backslash-bearing literals with NO CPython oracle,
    on the stated ground that "a non-raw `a\\nb` is three characters to CPython
    and four here, by design". **That design is gone.** A literal's escapes are
    now decoded by every engine — `fire_compiler.decode_c_escapes`, called
    through `decoded_literal` — and a raw literal is told apart from a cooked
    one by `StringLiteral.is_raw`, which the parser records because
    `_strip_string_prefix_and_quotes` discards the `r`. So CPython IS the
    oracle for `byte_exact` now, which is why it is given one: a `\"` is a
    quote and a `r"\n"` is a backslash and an `n`, and the expectation is
    spelled from CPython rather than from a contract this path used to keep.

    The program still prints the literal as well as its length, so a mangled
    byte cannot hide behind a right count — that part was always the point of
    the case and is unchanged.
    """
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: the end-to-end cases build an arm64 image; host is "
              f"{platform.machine()}")
        return True, ""

    agree = ('def main():\n'
             '    a = ' + Q3 + 'p"q' + Q3 + '\n'
             '    b = ' + Q3 + 'x\ny' + Q3 + '\n'
             "    c = 'say \"hi\"'\n"
             '    print(a)\n'
             '    print(b)\n'
             '    print(c)\n'
             '    print(len(a) + len(b) + len(c))\n'
             '    return 0\n')
    # The two spellings ONE LEVEL APART, which is what makes this case worth
    # an oracle rather than a pinned expectation. `a` is cooked and its `\"` is
    # a QUOTE (three characters); `b` is raw and its `\n` is a BACKSLASH and an
    # `n` (four). A decoder that ignored `is_raw` would make both three and
    # print `p` newline `q` for `b`; one that decoded twice would make `b` two
    # characters. Only the pair pins both, and CPython answers for it.
    byte_exact = ('def main():\n'
                  '    a = ' + Q3 + 'a\\"b' + Q3 + '\n'
                  '    b = r' + Q3 + 'p\\nq' + Q3 + '\n'
                  '    print(a)\n'
                  '    print(b)\n'
                  '    print(len(a))\n'
                  '    print(len(b))\n'
                  '    return 0\n')
    # The fourth oracle-able program: backslash-newline pairs INSIDE literals.
    # CPython's tokenizer decides a line continuation is worth nothing before
    # the parser sees the token, and this path does the same, so for a non-raw
    # literal the two agree on the bytes even though they disagree about every
    # other escape. The raw spelling is here too, and is oracle-able for a
    # different reason: there CPython KEEPS the pair and so does this path, and
    # a raw literal processes no escapes, so again there is nothing left to
    # disagree about. Before the fix the raw value lost the backslash and the
    # newline with it, so the image printed one fewer line than CPython did.
    continued = ('def main():\n'
                 '    a = "ab\\\ncd"\n'
                 '    b = "x\\\ny"\n'
                 '    c = "m"\n'
                 '    d = r"p\\\nq"\n'
                 '    print(a)\n'
                 '    print(b)\n'
                 '    print(c)\n'
                 '    print(len(d))\n'
                 '    print(len(a) + len(b) + len(c) + len(d))\n'
                 '    return 0\n')
    # The fourth oracle-able program: characters that `str.splitlines()` calls
    # line breaks and the language does not, inside literals. CPython's value is
    # three characters and so is this path's (byte-exact), so the two agree and
    # CPython is the oracle — which is the point: the row is here because before
    # the fix this path had NO STRING token for any of them and the program did
    # not build at all.
    # All three characters are single-byte, deliberately: `len` on this path
    # counts BYTES (a string is a `char *`), so a multi-byte character here
    # would make the length row a test of that instead of of this.
    not_breaks = ('def main():\n'
                  '    a = "x\vy"\n'
                  '    b = "p\fy"\n'
                  '    c = "m\x1cy"\n'
                  '    print(len(a) + len(b) + len(c))\n'
                  '    print(a)\n'
                  '    print(b)\n'
                  '    print(c)\n'
                  '    return 0\n')
    # A TAB inside a literal, which the per-line pass used to expand on its way
    # to computing an indent. `od -c` on the image's stdout is the only way to
    # see this one: a space and a tab both look like nothing in a diff, so the
    # length row is the one that actually catches it, and both are asserted.
    literal_tab = ('def main():\n'
                   '    a = "x\ty"\n'
                   '    b = "p\tq"\n'
                   '    print(len(a) + len(b))\n'
                   '    print(a)\n'
                   '    print(b)\n'
                   '    return 0\n')
    # An ordinary string whose own TEXT begins with an f/t prefix and a quote.
    # CPython is the oracle and there is nothing to disagree about: the source
    # asks for no interpolation, so every engine must print the spelling back.
    # Before `StringLiteral.is_interpolated` this printed `n` and `x` on the
    # interpreter and the compiled path, and REFUSED to build here — three
    # wrong answers to one question that had to be answered somewhere other than
    # the value. The lengths are asserted with the text because a value printed
    # as its own spelling and a value counted as something else are different
    # failures; 4 + 4 is all this program claims (four characters each — the
    # letter, the quote, the letter, the quote).
    #
    # The escaped spelling of the same shape (`c = "f\\"n\\""`, whose value
    # starts `f\` and so was accidentally right for every prefix sniff) is in
    # FLAG_ROWS above rather than here: on this path a plain literal's `\"` is
    # still two characters at run time, so a `len` of it is a fact about escape
    # decoding and not about this bug.
    prefix_looking = ('def main():\n'
                      '    a = \'f"n"\'\n'
                      '    b = "t\'x\'"\n'
                      '    print(a)\n'
                      '    print(b)\n'
                      '    print(len(a) + len(b))\n'
                      '    return 0\n')
    cases = [
        # (name, mojo text, python text or None, expected stdout, expected exit)
        ("agree", agree, agree + "main()\n", 'p"q\nx\ny\nsay "hi"\n14\n', 0),
("byte_exact", byte_exact, byte_exact + "main()\n",
         'a"b\np\\nq\n3\n4\n', 0),
        ("continued", continued, continued + "main()\n",
         'abcd\nxy\nm\n4\n11\n', 0),
        ("not_line_breaks", not_breaks, not_breaks + "main()\n",
         '9\nx\vy\np\fy\nm\x1cy\n', 0),
        ("literal_tab", literal_tab, literal_tab + "main()\n",
         '6\nx\ty\np\tq\n', 0),
        ("prefix_looking", prefix_looking, prefix_looking + "main()\n",
         'f"n"\nt\'x\'\n8\n', 0),
    ]
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, source, py_text, want_stdout, want_exit in cases:
            src = os.path.join(tmp, name + ".mojo")
            out = os.path.join(tmp, name)
            with open(src, "w") as f:
                f.write(source)
            p = subprocess.run([sys.executable, FIRE, "build", "--formal",
                                "--no-prove", "-o", out, src],
                               capture_output=True, text=True,
                               timeout=BUILD_TIMEOUT, cwd=HERE)
            if p.returncode != 0:
                failures.append(
                    f"{name}: the build refused a program of valid literals: "
                    f"{(p.stderr or p.stdout).strip()[-400:]}")
                continue
            r = subprocess.run([out], capture_output=True, text=True,
                               timeout=RUN_TIMEOUT)
            if r.returncode != want_exit or r.stdout != want_stdout:
                failures.append(
                    f"{name}: the arm64 image exited {r.returncode} and printed "
                    f"{r.stdout!r}; expected exit {want_exit} and {want_stdout!r}")
                continue
            if py_text is not None:
                pysrc = os.path.join(tmp, name + ".py")
                with open(pysrc, "w") as f:
                    f.write(py_text)
                c = subprocess.run([sys.executable, pysrc], capture_output=True,
                                   text=True, timeout=RUN_TIMEOUT)
                if c.returncode != r.returncode or c.stdout != r.stdout:
                    failures.append(
                        f"{name}: the arm64 image printed {r.stdout!r} and exited "
                        f"{r.returncode}; CPython on the SAME text printed "
                        f"{c.stdout!r} and exited {c.returncode}")
                    continue
            if verbose:
                print(f"  end-to-end   {name:20s} printed {want_stdout!r}")
    for f in failures:
        return False, "; ".join(failures)
    return True, ""


def main(argv):
    verbose = "-v" in argv
    failures = []
    for name, literal, expected_ours in LITERALS:
        ok, why = check_literal(name, literal, expected_ours, verbose)
        if not ok:
            failures.append(why)
    for name, (source, shape) in PROGRAMS.items():
        ok, why = check_program(name, source, shape, verbose)
        if not ok:
            failures.append(why)
    for name, text, ours_expected, cpython_expected in CONTINUATIONS:
        ok, why = check_continuation(name, text, ours_expected, cpython_expected,
                                     verbose)
        if not ok:
            failures.append(why)
    ok, why = check_code_continuation_is_unchanged(verbose)
    if not ok:
        failures.append(why)
    ok, why = check_refusal_message(verbose)
    if not ok:
        failures.append(why)
    ok, why = check_interpolated_flag(verbose)
    if not ok:
        failures.append(why)
    ok, why = run_end_to_end(verbose)
    if not ok:
        failures.append(why)

    total = len(LITERALS) + len(PROGRAMS) + len(CONTINUATIONS) + 5
    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"string literal lexing: PASS={total - len(failures)} FAIL={len(failures)}")
        return 1
    print(f"string literal lexing: PASS={total} FAIL=0")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
