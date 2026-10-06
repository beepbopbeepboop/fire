#!/usr/bin/env python3
"""Every method of `str` on the formal backends, with CPython as the oracle.

    python3 test_formal_str_methods.py [-v] [-k SUBSTRING] [--list]

Run one narrow slice while iterating:

    python3 test_formal_str_methods.py -k lstrip
    python3 test_formal_str_methods.py --list

WHAT THIS IS, AND WHY THE EXPECTATIONS ARE NOT TYPED
-----------------------------------------------------
`str` is the type whose methods this path refuses the most, so a test that
recorded "the backend answers 3" as a literal would be a SECOND source of truth
about a subject the model already has one for. So every row here is a pair of
the SAME source text:

  * the Mojo the backend is asked to build, and
  * the answer CPython gives for that text, computed IN THIS PROCESS.

The Mojo text and the Python text are the same string, so `eval` in this
process IS the oracle and no row states what any method answers. That is what
makes the non-ASCII rows possible at all: a `str` on this path is a bare
`char *` to UTF-8 bytes, so its methods answer in BYTES where CPython answers
in CHARACTERS, and the interesting question is exactly where the two part
company. A hand-typed table would have had to be re-derived by whoever wrote
it; an `eval` cannot drift from the interpreter running the test.

THE THREE VERDICTS, AND WHY A SILENT WRONG ANSWER IS THE WORST ONE
------------------------------------------------------------------
A row expects one of three things, and a row must say which:

  * `ANSWER` — the build succeeds, the image prints what CPython printed, and
    it exits 0. This is the only verdict that can be a WRONG ANSWER, and it is
    the one that matters. Measured on this tree before the fixes this file
    pins, four shapes BUILT and printed something CPython does not print —

        "ab".startswith(("x", "a"))    CPython True   this path 0
        "xxaxx".lstrip("x")            CPython "axx"  this path "xxaxx"
        "héllo".find("llo")            CPython 2      this path 3   (bytes)
        "héllo".count("é")             CPython 1      this path 2   (bytes)

    — and a fifth SHAPE DIED rather than answering at all: `"abc".find(98)`
    passed the integer 98 where a `char *` was expected and the image took
    SIGSEGV, exit 139, because the guard that exists checks the RECEIVER's
    kind and nothing anywhere checked the ARGUMENT's.

  * `REFUSED` — the BUILD fails, and the message names the thing that is
    missing. Asserted as a SUBSTRING, so a rewording does not break every row,
    but a specific one, so a message that stopped carrying its subject would.

  * `RAISES` — CPython raises `TypeError` and this path REFUSES rather than
    answering. Its own verdict, separate from `REFUSED`, because "the backend
    refuses" and "the backend answers as though the program were legal" are
    the two ends of the `find(98)` class, and the guard is what separates them.

ONE BUILD PER METHOD, AND WHY A RED STILL NAMES ITS ROW
--------------------------------------------------------
An `ANSWER` row is a `printf` of its own answer terminated by `@@`, so a whole
method's corpus goes in ONE image per architecture — 5 images per backend
rather than the 400 a row-per-build design would need, and the two
architectures' record lists are then compared with each other as well as with
CPython, which is how a lowering that differs between them is caught even where
both happen to agree with CPython.

A batch that fails to BUILD is not a lost measurement: `run_batch` falls back
to one image per row for that batch, so the report names the row. That is why
the batching is safe to be fast, and it is the reason the fallback exists
rather than being left to whoever hits it.

THE FIVE ANSWERED METHODS, AND WHY THE OTHERS ARE NOT IN THE ANSWER TABLE
-------------------------------------------------------------------------
`lstrip`, `startswith`, `endswith`, `find` and `count` are the five this path
lowers (`model.POINTER_BOUNDED_METHODS`), and they get the exhaustive
treatment: every receiver in the corpus against every argument shape CPython
accepts, including the shapes this path cannot answer (`chars`, a tuple,
`start`/`end`), on both architectures.

Every OTHER `str` method is a refusal row, and a refusal row is a real
assertion rather than a placeholder: the build must refuse, and the message
must NAME the method and say the actual missing half. The list of methods is
CPython's own `dir(str)`, read in this process, so it cannot go stale — a
method CPython grows appears here as a row with no expected substring, and that
row fails until somebody says why the method is out of reach. The `is*`
family, `encode`, `decode` and `translate` are the rows that needed their own
reasons: they were being refused by the generic "this backend lowers only
append, clear, close, write" sentence, which does not name them and which
sends a reader to wait for a length-prefixed string that is not what they are
missing.

`%`-formatting and `str.format` are refusal rows and nothing more: they are
`formal65-format-and-repr`'s claim, this file does not touch their lowering,
and a row that pins "refused, naming the operand shape" is what keeps that
claim honest from the outside.

WHAT IS DELIBERATELY NOT PINNED
-------------------------------
The `printf` differences that are not about `str`: `%d` reads a C `int` and so
renders 32 bits (`bugs/FORMAL_printf_d_renders_32_bits.md`), which is why every
number below is read through `%lld`, and a float operand read through `%f` on
x86-64 (`test_formal_math.py`'s `consts` group measures that one).
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FIRE = os.path.join(HERE, "fire.py")

BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")

#: The record separator. `@@` is the terminator every hostmod test in this tree
#: uses, and this file uses it for the reason `test_formal_dylib.py`
#: documents: a separator this suite can read back WITHOUT asking whether the
#: image decoded the literal. A suite whose reader had to know the answer
#: would be a suite that could not tell a mis-decoded separator from a wrong
#: method.
REC = "@@"

sys.path.insert(0, HERE)
from formal import model as M                                        # noqa: E402

ANSWER = "answer"
REFUSED = "refused"
RAISES = "raises"

RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what, detail))
    if not ok:
        print("FAIL %s\n     %s" % (what, detail))
    return bool(ok)


# ── the corpus ───────────────────────────────────────────────────────────────
#
# RECEIVERS. Chosen so that every rule a string method has is visible in at
# least one of them:
#
#   ""            the empty string: every length is 0, every search matches at
#                 0, and an empty needle matches at each of the 1 positions
#                 there are
#   "a"           one character, so a needle LONGER than the receiver is
#                 possible — the case `endswith` needs its unsigned-underflow
#                 guard for
#   "abc"         the ordinary case
#   "abcabc"      two occurrences, so `find`'s position and `count`'s tally are
#                 distinguishable, and so a bounded `start`/`end` window has
#                 something to cut
#   "aaa"         three overlapping copies of one byte: `count("aa")` is 1 and
#                 not 2, which is a one-instruction difference and the whole of
#                 Python's non-overlap rule
#   " a b  c "    leading, interior, doubled and trailing whitespace — the four
#                 positions a strip family has to get right, and a DOUBLED run
#                 so "strip whitespace" and "strip one space" differ
#   "  hi  "      the shape `model.LENGTH_DEPENDENT_METHODS["strip"]` is written
#                 about, whose measured `maxprot` is why `strip` is refused
#   "xxaxx"       a non-whitespace `chars` argument, so `lstrip(chars)` cannot
#                 be answered by the whitespace set and the ARGUMENT has to be
#                 the accept set — the row that is the argument's whole point
#   "héllo"       NON-ASCII, and the row that separates a byte answer from a
#                 character answer. Every method that reports a POSITION or a
#                 COUNT is asked about it, because those are the two answers a
#                 UTF-8 `char *` gets wrong; a STRING answer does not go wrong
#                 that way, which is why `startswith` over the same text is a
#                 row too (a byte compare is Python's answer for it)
#
# The one receiver deliberately absent is a string containing a NUL. This path
# cannot represent one — a `char *` ends at its NUL — so there is no such value
# here to compare against, and `model.py`'s string-representation note records
# that as a latent gap rather than a live answer. A row for it would be a row
# about a representation this path does not have.
RECEIVERS = ["", "a", "abc", "abcabc", "aaa", " a b  c ", "  hi  ", "xxaxx",
             "héllo"]

#: The five methods this path lowers, and the ARGUMENTS each is asked about.
#: `None` is the no-argument spelling and is only meaningful for `lstrip`,
#: whose two-argument-free forms are different answers.
ARGUMENT_METHODS = {
    # `chars` — the argument `lstrip` exists for. CPython strips any leading
    # character in the SET, so `"xxaxx".lstrip("x")` is `"axx"` and not the
    # receiver unchanged; and `lstrip()` strips whitespace, which is the only
    # place the two answers differ. `" x"` is the overlap case: a set with a
    # space AND an `x` is neither the whitespace set nor the `x` set.
    "lstrip": [None, '"x"', '"z"', '"xy"', '" x"', '"ab"', '"\\t"', '""',
               '"ax"'],
    # A TUPLE of affixes. CPython answers True when ANY element matches, and
    # `startswith(())` is False — an empty tuple is not a vacuous True, it is
    # "no affix matched". Both were measured wrong before the guard: a tuple is
    # a counted blob, its ADDRESS was compared as text, and the answer was 0
    # either way — which is right by accident for one of the two rows and wrong
    # for the other, which is exactly the shape that hides.
    "startswith": ['"a"', '"ab"', '"abc"', '"abcd"', '""', '("a", "z")',
                   '("z", "a")', '("z", "y")', "()", '("a",)', '"h"', '"é"',
                   '"z"'],
    # The same from the far end, and `"abcd"` is longer than `"abc"` for the
    # underflow guard.
    "endswith": ['"c"', '"bc"', '"abc"', '"abcd"', '""', '("c", "z")',
                 '("z", "c")', '("z", "y")', "()", '("c",)', '"o"', '"é"',
                 '"z"'],
    # `find`'s needle. The empty needle is the row with NO LOOP in the lowering
    # at all: `strstr` returns the receiver itself, so the answer is 0.
    "find": ['"a"', '"b"', '"c"', '"z"', '""', '"abc"', '"ab"', '"ll"',
             '"é"'],
    # `count`'s needle. `""` is the other no-loop row: it matches at each of
    # the L+1 positions, so the answer is `strlen(s) + 1`. `"é"` is a
    # two-BYTE needle over a two-character text, where CPython counts 1 and a
    # byte walk counts 2.
    "count": ['"a"', '"b"', '"c"', '"z"', '""', '"aa"', '"abc"', '"ab"',
              '"é"'],
}

#: `start`/`end`, for the two methods whose CPython signature has them. These
#: are the rows a signature check has to be able to tell apart: the same call
#: with one argument, with two and with three is a different answer each time,
#: so "this path takes exactly one argument" is an honest refusal only if the
#: source asked for the one it can answer. The negative `start` and the
#: end-before-start window are CPython's own clamping rules and are here so a
#: fold cannot quietly get them wrong by ignoring the arguments.
RANGE_CASES = [
    "find_b_one", "find_b_zero", "find_a_past_end", "find_b_negative",
    "find_c_window", "find_b_window", "find_b_backwards_window",
    "count_b_from1", "count_b_from0", "count_b_window", "count_a_past_end",
    "count_empty_from1",
]

#: Shapes CPython ACCEPTS and this path must not silently answer differently.
#: Each is a row whose `refusal` is what the message must contain, so a fix
#: that made one of them work has to come here and delete the row rather than
#: leave it passing.
GUARD_CASES = [
    # The four measured crashes/wrong answers. `"abc".find(98)` reached the
    # libc call with 98 in the pointer register and the image took SIGSEGV —
    # exit 139, measured, on BOTH architectures, from a green build.
    ("guard_find_int_needle", '"abc".find(98)', "its needle"),
    ("guard_count_int_needle", '"abc".count(98)', "its needle"),
    ("guard_startswith_int", '"abc".startswith(97)', "its affix"),
    ("guard_endswith_int", '"abc".endswith(99)', "its affix"),
    ("guard_lstrip_int_chars", '"xxaxx".lstrip(120)', "its chars"),
    # A tuple bound to a NAME cannot be folded — the build cannot see which
    # literals it holds — and cannot be walked either, so it is refused. It is
    # here because it is the shape that separates "the build can see the
    # affixes" from "the build cannot", and an answer that only handled the
    # literal would be right about the wrong reason.
    ("guard_startswith_tuple_name",
     '    t = ("z", "a")\n    printf("%lld' + REC + '", "abc".startswith(t))',
     "tuple"),
    ("guard_endswith_tuple_name",
     '    t = ("z", "c")\n    printf("%lld' + REC + '", "abc".endswith(t))',
     "tuple"),
    ("guard_startswith_list", '"abc".startswith(["a"])', "tuple"),
    # Arity CPython does not have: `lstrip` takes at most one argument, and a
    # two-argument call is a TypeError rather than a strip.
    ("guard_lstrip_two_args", '"xxaxx".lstrip("x", "y")', "one argument"),
]

#: The `start`/`end` expressions, paired with `RANGE_CASES`. Kept as source
#: text rather than as values because the whole point is that CPython
#: computes the answer from this text and this file states nothing.
RANGE_SOURCES = [
    '"abcabc".find("b", 1)',
    '"abcabc".find("b", 0)',
    '"abc".find("a", 99)',
    '"abcabc".find("b", 0 - 2)',
    '"abcabc".find("c", 1, 5)',
    '"abcabc".find("b", 0, 2)',
    '"abcabc".find("b", 4, 2)',
    '"abcabc".count("b", 1)',
    '"abcabc".count("b", 0)',
    '"abcabc".count("b", 1, 5)',
    '"abc".count("a", 99)',
    '"abc".count("", 1)',
]


def _mojo(text):
    """`text` as a Mojo string literal.

    The corpus holds Python's own spelling, and this re-quotes it, so a corpus
    entry carrying an escape reaches the backend as the CHARACTER CPython meant
    and not as a backslash and a letter — the escape trap
    `arm64_codegen._intern_string`'s docstring records, and one that would make
    every `lstrip("\\t")` row a test of the decoder rather than of the method.
    """
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _slug(text):
    """A filename-safe tag for a receiver, so a temp file says which row."""
    if text == "":
        return "empty"
    return "".join(c if c.isalnum() else "_" for c in text)[:20]


class Case:
    """One row: a source expression, and what CPython does with it."""

    def __init__(self, name, expr, group, refusal=None):
        self.name = name
        self.expr = expr
        self.group = group
        self.refusal = refusal
        self._value = None
        self._raises = None

    def cpython(self):
        """CPython's answer for `expr`, computed HERE and cached.

        `eval` with the builtins removed, so a row cannot accidentally call
        something: the subject is `str`'s own methods and Python's own `str`
        is what answers. A row whose expression CPython rejects records the
        exception TYPE and nothing else — the message is CPython's prose and
        has no bearing on what this path should say.
        """
        if self._value is None and self._raises is None:
            try:
                # `str` is in the namespace and nothing else is: `maketrans`
                # is a CLASS method, so its row has to be able to spell
                # `str.maketrans(...)`, and no other builtin is reachable —
                # the subject is `str`'s own methods, not this process's
                # globals.
                self._value = eval(self.expr, {"__builtins__": {}}, {"str": str})
            except Exception as exc:                        # noqa: BLE001
                self._raises = type(exc).__name__
        return self._value

    def expects(self):
        """`ANSWER`, `REFUSED` or `RAISES` — the row's own verdict."""
        self.cpython()
        if self._raises is not None:
            return RAISES
        if self.refusal is not None:
            return REFUSED
        return ANSWER

    def needle(self):
        """The substring this row's refusal message has to contain."""
        return self.refusal or self._raises

    def statement(self):
        """The Mojo statement(s) that print this row's answer.

        The rendering is a function of the CPython VALUE and of nothing else,
        so the statement the backend is asked to emit and the text this file
        expects are two halves of one decision and cannot disagree about how a
        string is printed here. A list is printed as its length and then its
        elements, because a list on this path is a blob and `printf("%s", x)`
        on a blob reads the count field as an address.
        """
        if self.refusal is not None or self._raises is not None:
            # A refusal row still needs a statement to be REFUSED about; a bare
            # call in a `printf` is the smallest program that mentions it.
            return 'printf("%%lld%s", %s)' % (REC, self.expr)
        value = self.cpython()
        if isinstance(value, (bool, int)):
            return 'printf("%%lld%s", %s)' % (REC, self.expr)
        if isinstance(value, str):
            return 'printf("[%%s]%s", %s)' % (REC, self.expr)
        if isinstance(value, (list, tuple)):
            out = ['printf("%%lld%s", len(%s))' % (REC, self.expr)]
            for i in range(len(value)):
                out.append('printf("[%%s]%s", %s[%d])' % (REC, self.expr, i))
            return "\n    ".join(out)
        raise AssertionError("unhandled CPython answer %r for %s"
                             % (type(value), self.expr))

    def expected(self):
        """What CPython prints, in the rendering `statement` generates."""
        if self.refusal is not None or self._raises is not None:
            return None
        value = self.cpython()
        if isinstance(value, (bool, int)):
            return "%d" % int(value)
        if isinstance(value, str):
            return "[%s]" % value
        if isinstance(value, (list, tuple)):
            return "\n".join(["%d" % len(value)]
                             + ["[%s]" % v for v in value])
        raise AssertionError(type(value))


# ── refusals: every other method of `str` ────────────────────────────────────
#
# The list is CPython's own `dir(str)`, read in this process, minus the five
# this path answers — so it cannot go stale as CPython grows a method: a new
# method appears here as a row with no expected substring, and that row fails
# until somebody says why the method is out of reach. That is the anti-rot
# half, and it is why `refusal_rows` raises instead of skipping.
#
# Each row asserts two things and the second is the one that is easy to lose:
# the build refuses, AND the message names the method. A refusal that says
# "this backend lowers only append, clear, close, write …" without naming
# `split` is a refusal a reader cannot act on, and it is what every name got
# before the `is*` family were given entries of their own.
REFUSAL_SUBSTRINGS = {
    # The `is*` family. What is missing is NOT a buffer: it is that each of
    # these is a UNICODE character-class question and this path holds bytes, so
    # `isdigit` over "²" is a question about a code point and there is no code
    # point here. The message says that, per method, so a reader who wants
    # `isalpha` is not sent to wait for a length-prefixed string that is not
    # what `isalpha` is missing.
    "isalnum": "CHARACTER", "isalpha": "CHARACTER", "isascii": "CHARACTER",
    "isdigit": "CHARACTER", "isdecimal": "CHARACTER",
    "isidentifier": "CHARACTER", "islower": "CHARACTER",
    "isnumeric": "CHARACTER", "isprintable": "CHARACTER",
    "isspace": "CHARACTER", "istitle": "CHARACTER", "isupper": "CHARACTER",
    # `encode`/`decode` are a codec question and `translate` is a table; all
    # three are the same missing half as the predicates, which is why they are
    # grouped with them rather than with the buffer cases.
    "encode": "code point", "decode": "code point", "translate": "code point",
    # The rest say why THEY are out, in the model's own words; the substring
    # is the subject of the sentence rather than the whole of it.
    "capitalize": "NEW string", "casefold": "NEW string",
    "center": "allocates a new buffer", "expandtabs": "RESULT",
    "index": "find", "join": "no heap", "ljust": "allocates a new buffer",
    "lower": "NEW string",
    "partition": "SEQUENCE", "removeprefix": "different pointer",
    "removesuffix": "different pointer", "replace": "RESULT",
    "rfind": "backwards", "rindex": "find", "rjust": "allocates a new buffer",
    "rpartition": "SEQUENCE", "rsplit": "SEQUENCE", "rstrip": "SHORTER",
    "split": "SEQUENCE", "splitlines": "SEQUENCE", "strip": "SHORTER",
    "swapcase": "NEW string", "title": "NEW string", "upper": "NEW string",
    "zfill": "allocates a new buffer",
    # `maketrans` is a CLASS method and not a method on an instance, so there
    # is no `"abc".maketrans()` for this path to refuse as a method call; it
    # is refused further down, as an unbound symbol the image would have to
    # bind. The needle is that message's own subject rather than a method
    # refusal, because that is the refusal this path actually produces.
    "maketrans": "nothing provides",
    # `__len__` is in the model's table because `len(s)` is the spelling that
    # works, and the message says so.
    "__len__": "len(s)",
    # `format`/`format_map`/`%`-formatting: `formal65-format-and-repr`'s claim.
    # They are here because a `str` conformance table that omitted them would
    # be quietly asserting that `str` has no formatting methods, and this file
    # does not touch their lowering.
    "format": "format", "format_map": "format",
}

#: How each refused method is SPELLED so CPython accepts the call. A refusal
#: row written as `"abc".strip()` would measure CPython's `TypeError` rather
#: than this path's refusal, so every method that takes an argument is given
#: one it accepts — and the ARGUMENTS are chosen to be the ones that make the
#: method interesting, not the ones that are easiest to spell:
#:
#:   * the width-taking family (`center`/`ljust`/`rjust`/`zfill`) is asked for
#:     a WIDTH LARGER THAN THE RECEIVER, because the case where the padding is
#:     zero is the case where a lowering that ignores the width looks right;
#:   * `replace` is asked for a substitution that CHANGES THE LENGTH, which is
#:     the whole of why it is refused;
#:   * `split`/`rsplit`/`splitlines`/`partition`/`rpartition` are asked for a
#:     separator that is PRESENT, so the row is not the empty-separator case
#:     that has an answer of a different shape;
#:   * `index`/`rfind`/`rindex` are asked for a needle that IS PRESENT, so
#:     CPython's answer is a position rather than the `-1`/exception the
#:     missing case gives;
#:   * `expandtabs` is asked about a tab that IS there.
#:
#: `maketrans` is here as `str.maketrans` because it is a class method: there
#: is no `"abc".maketrans()` for CPython to accept, and a row written as one
#: would be measuring the `AttributeError`/`TypeError` rather than the refusal.
REFUSAL_CALLS = {
    "capitalize": '"aBc dEF".capitalize()',
    "casefold": '"Straße".casefold()',
    "center": '"ab".center(8, "-")',
    "decode": '"ab".decode()',
    "encode": '"ab".encode()',
    "expandtabs": '"a\\tb".expandtabs(4)',
    "format": '"{}-{}".format(1, 2)',
    "format_map": '"{a}".format_map({"a": 1})',
    "index": '"abcabc".index("b")',
    "isalnum": '"ab1".isalnum()',
    "isalpha": '"ab".isalpha()',
    "isascii": '"ab".isascii()',
    "isdecimal": '"12".isdecimal()',
    "isdigit": '"12".isdigit()',
    "isidentifier": '"ab_1".isidentifier()',
    "islower": '"ab".islower()',
    "isnumeric": '"12".isnumeric()',
    "isprintable": '"ab".isprintable()',
    "isspace": '" ".isspace()',
    "istitle": '"Ab Cd".istitle()',
    "isupper": '"AB".isupper()',
    "join": '"-".join(["a", "b"])',
    "ljust": '"ab".ljust(8, "-")',
    "lower": '"aBc".lower()',
    "maketrans": 'str.maketrans("a", "b")',
    "partition": '"a,b".partition(",")',
    "removeprefix": '"xabc".removeprefix("x")',
    "removesuffix": '"abcx".removesuffix("x")',
    "replace": '"aXbXc".replace("X", "--")',
    "rfind": '"abcabc".rfind("b")',
    "rindex": '"abcabc".rindex("b")',
    "rjust": '"ab".rjust(8, "-")',
    "rpartition": '"a,b".rpartition(",")',
    "rsplit": '"a,b,c".rsplit(",", 1)',
    "rstrip": '"  hi  ".rstrip()',
    "split": '"a,b,c".split(",")',
    "splitlines": '"a\\nb".splitlines()',
    "strip": '"  hi  ".strip()',
    "swapcase": '"aBc".swapcase()',
    "title": '"ab cd".title()',
    "translate": '"abc".translate(str.maketrans("a", "b"))',
    "upper": '"aBc".upper()',
    "zfill": '"42".zfill(8)',
    "__len__": '"abc".__len__()',
}


#: The method list, as `dir(str)` spells it. CPython's, not this file's — and
#: `refusal_rows` fails on any name with no entry in `REFUSAL_SUBSTRINGS`, so
#: this list cannot quietly shrink either.
def str_method_names():
    return sorted(n for n in dir(str)
                  if not n.startswith("_") or n == "__len__")


def answer_rows():
    """Every ANSWER row: the five lowered methods over the whole corpus."""
    cases = []
    for method, args in ARGUMENT_METHODS.items():
        for recv in RECEIVERS:
            r = _mojo(recv)
            for i, arg in enumerate(args):
                expr = ("%s.lstrip()" % r if arg is None
                        else "%s.%s(%s)" % (r, method, arg))
                cases.append(Case("%s_%s_%d" % (method, _slug(recv), i),
                                  expr, method))
    return cases


def range_rows():
    return [Case(n, e, "range") for n, e in zip(RANGE_CASES, RANGE_SOURCES)]


def guard_rows():
    return [Case(name, stmt, "guard", refusal=needle)
            for name, stmt, needle in GUARD_CASES]


def refusal_rows():
    cases = []
    for name in str_method_names():
        if name in ARGUMENT_METHODS:
            continue
        cases.append(Case("refusal_%s" % name,
                          REFUSAL_CALLS.get(name, '"abc".%s()' % name),
                          "refusal", refusal=REFUSAL_SUBSTRINGS.get(name)))
    return cases


# ── building, running, judging ───────────────────────────────────────────────

def prog(body_lines):
    """A whole image whose `main` runs each line of `body_lines`."""
    return ("def main(n):\n"
            + "".join("    " + l + "\n" for l in body_lines)
            + "    return 0\n")


def build_run(tmpdir, name, source, backend):
    """Build `source` for `backend` and RUN the image.

    Returns `("ok", stdout)`, `("refused", message)` or `("died", detail)`.
    The three are distinct on purpose: a build that refuses and an image that
    crashes are different facts, and a reader told only "it failed" has to go
    and re-run it to find out which.
    """
    src = os.path.join(tmpdir, "%s_%s.py" % (name, backend))
    out = os.path.join(tmpdir, "%s_%s.bin" % (name, backend))
    with open(src, "w", encoding="utf-8") as f:
        f.write(source)
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove",
            "--backend=%s" % backend, "-o", out, src]
    r = subprocess.run(argv, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    if r.returncode != 0:
        return ("refused", (r.stderr or r.stdout).strip())
    if not os.path.isfile(out):
        return ("refused", "build reported success but wrote no image at %s"
                % out)
    run_argv = ["arch", "-x86_64", out] if backend == "x86_64" else [out]
    run = subprocess.run(run_argv, capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    if run.returncode != 0:
        return ("died", "exit %d, stderr %r"
                % (run.returncode, run.stderr[-200:]))
    return ("ok", run.stdout)


def records(stdout):
    """The image's `@@`-separated records, keeping an EMPTY one.

    Not `[r for r in out.split(REC) if r]`, which every hostmod test here
    writes: a row whose answer is the empty string produces an empty record,
    and dropping empties would delete it — so `"".lstrip()` would be a row
    that passes by having no records at all. The trailing split artefact (the
    `@@` at the end of the last `printf`) is dropped by POSITION instead, which
    is the one thing that is unambiguous.
    """
    recs = stdout.split(REC)
    if recs and recs[-1] == "":
        recs = recs[:-1]
    return recs


def judge(case, backend, res):
    """One (case, backend) verdict."""
    tag = "[%s] %s" % (backend, case.name)
    kind, payload = res
    want = case.expects()
    if kind == "refused":
        if want == ANSWER:
            return check(False, tag + " builds", payload[-400:])
        return check(case.needle() in payload,
                     tag + " refuses naming %r" % case.needle(),
                     payload[-400:])
    if kind == "died":
        return check(False, tag + " runs to completion", payload)
    if want != ANSWER:
        return check(False, tag + " is refused, not answered",
                     "it printed %r" % payload)
    recs = records(payload)
    want_s = case.expected()
    # A STRING answer is one record and a LIST answer is `1 + n`, so the
    # comparison is over the whole record list: joining with a newline would
    # make a two-record answer and a one-record answer containing a newline
    # indistinguishable, which is a distinction this path can produce.
    got = recs
    exp = ([want_s] if isinstance(case.cpython(), str) else want_s.split("\n"))
    return check(got == exp, tag + " prints %r" % (exp,), "printed %r" % (got,))


def run_one(tmpdir, case, backend):
    """One row: one image, one verdict."""
    lines = case.expr.split("\n") if "\n" in case.expr else None
    if lines is None:
        lines = [case.statement()]
    return judge(case, backend, build_run(tmpdir, case.name, prog(lines),
                                          backend))


def run_batch(tmpdir, cases, backend, got_by_arch):
    """One image per ANSWER batch, with a per-row fallback when it refuses.

    The batch is what makes the corpus affordable — 5 images per backend
    instead of ~400 — and the fallback is what keeps it honest: a batch that
    does not BUILD is re-run one row at a time, so the report names the row
    that broke instead of the method whose corpus contains it. A batch that
    BUILDS is compared record by record, so a wrong answer names its row too.
    """
    answer_cases = [c for c in cases if c.expects() == ANSWER]
    other_cases = [c for c in cases if c.expects() != ANSWER]
    if answer_cases:
        name = "batch_%s" % answer_cases[0].group
        body = []
        for c in answer_cases:
            body.extend(c.statement().split("\n"))
        res = build_run(tmpdir, name, prog(body), backend)
        if res[0] == "ok":
            recs = records(res[1])
            pos = 0
            for c in answer_cases:
                n = len(c.expected().split("\n")) \
                    if isinstance(c.cpython(), str) \
                    else len(c.expected().split("\n"))
                mine = recs[pos:pos + n]
                pos += n
                judge_records(c, backend, mine)
            if pos != len(recs):
                check(False, "[%s] %s produced %d records for %d rows"
                      % (backend, name, len(recs), pos),
                      "the batch and the row list disagree about how many "
                      "answers there are")
            got_by_arch.setdefault(name, {})[backend] = recs
        else:
            # The batch refused or died: fall back so the row is named.
            for c in answer_cases:
                r = run_one(tmpdir, c, backend)
                if r:
                    got_by_arch.setdefault(c.name, {})[backend] = [r]
    for c in other_cases:
        run_one(tmpdir, c, backend)


def judge_records(case, backend, recs):
    """Judge one row from records already read out of a batch."""
    tag = "[%s] %s" % (backend, case.name)
    exp = ([case.expected()] if isinstance(case.cpython(), str)
           else case.expected().split("\n"))
    return check(recs == exp, tag + " prints %r" % (exp,),
                 "printed %r" % (recs,))


def coverage_checks():
    """This file and the model must agree about which methods are ANSWERED.

    Both directions. A method the model lowers with no corpus here is a method
    nothing measures, which is the hole the project's own convention about
    ungated registrations is about; and a corpus for a method the model does
    not lower is a row asserting an answer this path does not give, which fails
    loudly instead — but it fails as a WRONG ANSWER report, which points at the
    backend rather than at the drift, so it is checked here where the message
    can name the drift.
    """
    lowered = set(M.POINTER_BOUNDED_METHODS)
    mine = set(ARGUMENT_METHODS)
    check(lowered == mine, "the answered-method set matches the model",
          "the model lowers %s, this file measures %s; the difference is %s"
          % (sorted(lowered), sorted(mine), sorted(lowered ^ mine)))
    missing = sorted(n for n in str_method_names()
                     if n not in ARGUMENT_METHODS
                     and n not in REFUSAL_SUBSTRINGS)
    check(not missing,
          "every str method is either measured or has a refusal reason",
          "%s has no entry in REFUSAL_SUBSTRINGS, so CPython grew a method "
          "this table has no reason for" % (missing,))
    # And the refusal CALLS: a row spelled `"abc".strip()` would measure
    # CPython's `TypeError` rather than this path's refusal, so every method
    # that takes an argument has to be spelled a call CPython accepts.
    uncalled = sorted(n for n in str_method_names()
                      if n not in ARGUMENT_METHODS
                      and n not in REFUSAL_CALLS)
    check(not uncalled,
          "every refused method is spelled a call CPython accepts",
          "%s has no entry in REFUSAL_CALLS, so its row would be measuring "
          "CPython's TypeError instead of this path's refusal" % (uncalled,))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-k", dest="substring", default=None,
                    help="run only rows whose name or group contains this")
    ap.add_argument("--list", action="store_true", dest="list_only",
                    help="list the rows and their verdicts, and exit")
    args = ap.parse_args()

    cases = (answer_rows() + range_rows() + guard_rows() + refusal_rows())
    # Every CPython answer is computed HERE, before a single build, so a row
    # whose expression CPython itself rejects shows up in `--list` as a `raises`
    # row rather than as a surprise in the middle of a run.
    for c in cases:
        c.cpython()

    if args.list_only:
        for c in cases:
            print("%-9s %-34s %-8s %s" % (c.group, c.name, c.expects(),
                                          c.expr.replace("\n", " ")))
        print("\n%d rows x %d backends" % (len(cases), len(BACKENDS)))
        return 0

    if args.substring:
        cases = [c for c in cases
                 if args.substring in c.name or args.substring == c.group]

    coverage_checks()

    got = {}
    with tempfile.TemporaryDirectory(prefix="strmeth") as tmpdir:
        for group in ("lstrip", "startswith", "endswith", "find", "count",
                      "range", "guard", "refusal"):
            rows = [c for c in cases if c.group == group]
            if not rows:
                continue
            for backend in BACKENDS:
                run_batch(tmpdir, rows, backend, got)

    # The two architectures, compared with EACH OTHER as well as with CPython.
    # A lowering that differs between them is a bug even where both answers
    # happen to agree with CPython on the corpus at hand, and this is the only
    # place that can see it.
    for name, per_arch in sorted(got.items()):
        if len(per_arch) != 2:
            continue
        a, b = BACKENDS
        check(per_arch[a] == per_arch[b],
              "%s: %s and %s produce the same records" % (name, a, b),
              "first three differences: %s"
              % [(x, y) for x, y in zip(per_arch[a], per_arch[b])
                 if x != y][:3])

    npass = sum(1 for ok, _, _ in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print("\nformal str methods: %d/%d checks passed "
          "(%d rows x %d backends)" % (npass, len(RESULTS), len(cases),
                                       len(BACKENDS)))
    if args.verbose:
        for ok, what, _ in RESULTS:
            print("  %s  %s" % ("PASS" if ok else "FAIL", what))
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
