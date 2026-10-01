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
reason this file exists
(bugs/CODEGEN_triple_quoted_literal_ending_in_a_backslash_swallows_the_rest_of_the_file.md).
A source line reading

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
(formal/arm64_codegen.py) from the evaluator.

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

# (name, the literal's source text, expected value or None to mean "whatever
# CPython computes", expected_ours_value)
#
# `ours` is the byte-exact content: source text between the delimiters, with no
# escape processing. It is spelled out for every row rather than derived,
# because "byte-exact" is a contract a reader has to be able to check by eye.
# A row whose value is a real newline is written '\n' in the table below and
# comes from a source line break.
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
}


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
        tokens = F.Parser(F.py_tokenize(src, "<t>")).with_filename("<t>").parse_module()
    except SyntaxError as e:
        return ("refuse", str(e))
    strings = [(t.kind, t.value) for t in F.py_tokenize(src, "<t>")
               if t.kind == "STRING"]
    return ("ok", strings)


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
    value = F.Parser(F.py_tokenize("s = " + literal + "\n", "<t>")
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
            F.Parser(F.py_tokenize(source, "<t>")).with_filename("<t>").parse_module()
        except SyntaxError as e:
            if verbose:
                print(f"  refused     {name:36s} {e}")
            return True, ""
        return False, (f"{name}: accepted a program CPython refuses, so the "
                       f"source after an unterminated literal was silently "
                       f"absorbed into it")

    where, count = shape
    try:
        stmts = F.Parser(F.py_tokenize(source, "<t>")).with_filename("<t>").parse_module()
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
        F.py_tokenize(src, "some/file.mojo")
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

    `byte_exact` holds backslash-bearing literals, where CPython *cannot* be the
    oracle (a non-raw `a\\nb` is three characters to CPython and four here, by
    design). The expectation is spelled out instead, from the documented
    contract, and the program prints the literal as well as its length so a
    mangled byte cannot hide behind a right count.
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
    # The literals here are the ones whose characters this path does NOT
    # reinterpret: a quote run, a real newline, a quote of the other kind.
    byte_exact = ('def main():\n'
                  '    a = ' + Q3 + 'a\\"b' + Q3 + '\n'
                  '    b = r' + Q3 + 'p\\nq' + Q3 + '\n'
                  '    print(a)\n'
                  '    print(b)\n'
                  '    print(len(a))\n'
                  '    print(len(b))\n'
                  '    return 0\n')
    cases = [
        # (name, mojo text, python text or None, expected stdout, expected exit)
        ("agree", agree, agree + "main()\n", 'p"q\nx\ny\nsay "hi"\n14\n', 0),
        ("byte_exact", byte_exact, None, 'a\\"b\np\\nq\n4\n4\n', 0),
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
    ok, why = check_refusal_message(verbose)
    if not ok:
        failures.append(why)
    ok, why = run_end_to_end(verbose)
    if not ok:
        failures.append(why)

    total = len(LITERALS) + len(PROGRAMS) + 3
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
