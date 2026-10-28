#!/usr/bin/env python3
"""CPython-oracle table for what `print` writes, on BOTH formal backends.

`print` is the one output call this path lowers for real: it builds a `printf`
format out of what each operand statically is and passes the operands as
varargs, so what lands on stdout is what the source says. That makes it the
place where every question about FORMATTING becomes observable, and it is why
this file is a table rather than a pile of cases: one row per SHAPE of operand,
each built and RUN on both architectures and compared against CPython running
the same text in this process.

**CPython is the oracle, not a copied expectation.** Every `("value",)` row
computes its own answer by running the same source through `python3` here, so a
row cannot rot into asserting a hand-written number and a fix that changes what
this path prints cannot be satisfied by editing the table. That is the whole
argument for the shape: the expected text is a property of the SOURCE, and the
source is what both sides run.

**How a row is allowed to pass.** Three answers are correct on this path and a
row must say which it expects, so a refusal cannot pass for a rendering and a
rendering cannot pass for a refusal:

  * `("value",)` — the image prints what CPython prints for the same source and
    exits 0. No text is written down, because CPython computes it.
  * `("refuse", substring)` — the BUILD refuses, and the message contains
    `substring`. A substring and not the whole sentence, so a rewording does not
    break every row; but a specific one, so a message that stopped naming the
    thing it is refusing would.
  * `("divergent", here, cpython)` — the image prints `here` where CPython
    prints `cpython`. **The census of what is left**, and it is a separate
    section for the reason `test_formal_int_semantics.py` keeps its own: a
    conformance table that quietly omitted the rows this path gets WRONG would
    be a census with the failures taken out, which is the failure written down
    nowhere. Both texts are asserted, and the CPython one is checked against
    CPython, so the table cannot rot into pinning a stale "correct" answer.

**Both architectures, always.** The worst form of a formatting bug is the two
backends disagreeing about it, so every row is built and run twice. The
formal42 batch measured exactly that class: `-2**63 // -1` was a wrong number on
arm64 and a SIGFPE on x86-64, from one source, and a test that compared only
exit statuses would have called the second "did not crash".

**No row reads a value through `printf("%d", …)`.** Measured on both backends:
`%d` reads a C `int` and prints 0 for `2**62`, where `%lld` and `print` are
right (`FORMAL printf d renders 32 bits`). Every output call here is
`print`, which is also the call under test.

**What this path cannot render is refused, and a refusal is a documented
answer rather than a missing one.** The rows below name, for each shape, what is
missing: a float's SPELLING (CPython's is the shortest decimal that round-trips,
which is not a libc conversion), a container's brackets and separator (a loop
emitting text, not a conversion of a word), an f-string's buffer (the same
missing buffer that refuses `+`, `upper` and `join`), and `str`/`repr`/`format`/
`%`/`.format()` as names with no lowering. Two of those refusals used to be
messages that were FALSE about the source — `print(1.5)` was "cannot tell
whether FloatLiteral is a string or a number" when the model's own `FLOAT_KIND`
says it is a `double` — and they are the rows that keep them honest.

Run:  python3 test_formal_format_conformance.py [-v] [-k SUBSTRING] [-m]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")

#: An object address in a pinned answer. CPython writes one for an instance and
#: it is a fact about the allocator, not about the program, so a row that pins
#: one pins where the heap landed; this is what a reader compares instead.
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{4,}")


def prog(*lines):
    """A row's source: `lines` as module-level statements.

    Module level rather than a function body because that is the harder of the
    two scopes and the one a script is written in: `formal/build.py`'s
    `_module_body_function` wraps it as `def __module_body__():`, so a
    module-level `print` goes through the same emitter with a different name —
    and, before this file's subject was fixed, a module-level `FLAG = True` lost
    its `bool` to a constant substitution that the function-local spelling never
    went through. Rows that need the other scope say so with `in_main`.
    """
    return "\n".join(lines) + "\n"


def in_main(*lines):
    """The same statements inside a function, which is the other scope.

    A `def` in the row's own source would need its own name in every row and
    would collide with the backend's entry-point conventions; this is the one
    line that says "a local", so a reader can see which scope each row is about.
    """
    return prog(*(["def _fmt_case():"] + ["    " + l for l in lines]
                  + ["", "_fmt_case()"]))


# ── the table ───────────────────────────────────────────────────────────────
#
# (name, source, want).  `want` is one of the three shapes in the module
# docstring.  Nothing here writes down a `("value",)` row's expected text: it is
# CPython's, computed per row.

ROWS = [
    # ── integers: the shape that has always worked, pinned so the other rows'
    #    fixes cannot have broken it ──────────────────────────────────────
    ("int_small", prog('print(42)'), ("value",)),
    ("int_zero", prog('print(0)'), ("value",)),
    ("int_negative", prog('print(0 - 42)'), ("value",)),
    ("int_max", prog('print(9223372036854775807)'), ("value",)),
    ("int_min", prog('print(0 - 9223372036854775807 - 1)'), ("value",)),
    # The unsigned edge, which is the row that decides the SIGNEDNESS of the
    # conversion: `%lld` on a `UInt64` whose top bit is set prints a negative
    # number, so `print` asks the operand's own type.
    ("uint64_max", in_main('a: UInt64 = 18446744073709551615', 'print(a)'),
     ("value",)),
    ("uint32_max", in_main('a: UInt32 = 4294967295', 'print(a)'), ("value",)),
    # A NARROW type, whose word is already sign/zero-extended to the 64-bit one
    # it is stored in — so width is not what decides the conversion.
    ("int8_max", in_main('a: Int8 = 127', 'print(a)'), ("value",)),
    ("int32_min", in_main('a: Int32 = 0 - 2147483647 - 1', 'print(a)'),
     ("value",)),
    ("int_expr", in_main('a = 6', 'b = 7', 'print(a * b)'), ("value",)),

    # ── bool: CPython prints a WORD, and every one of these used to print the
    #    word's own 0/1 ───────────────────────────────────────────────────
    ("bool_true", prog('print(True)'), ("value",)),
    ("bool_false", prog('print(False)'), ("value",)),
    # A COMPARISON is a bool whatever any declaration says, and it is the shape
    # every `check` helper in this repository's own source writes.
    ("bool_compare_true", in_main('a = 1', 'b = 2', 'print(a < b)'),
     ("value",)),
    ("bool_compare_false", in_main('a = 1', 'b = 2', 'print(a > b)'),
     ("value",)),
    ("bool_eq", in_main('a = "x"', 'b = "x"', 'print(a == b)'), ("value",)),
    ("bool_ne", in_main('a = 1', 'b = 2', 'print(a != b)'), ("value",)),
    ("bool_is", in_main('n2 = None', 'print(n2 is None)'), ("value",)),
    ("bool_in", in_main('xs = [1, 2]', 'print(2 in xs)'), ("value",)),
    ("bool_not", in_main('a = 1', 'print(not a)'), ("value",)),
    # A `Bool` DECLARATION is the evidence a shape cannot supply, so these three
    # are a different reader: a parameter, an annotated local, and a frame field
    # (the last is pinned below rather than here, because it needs a struct).
    ("bool_param", in_main('def show(flag: Bool):', '    print(flag)',
                           'show(True)', 'show(False)'), ("value",)),
    ("bool_local", in_main('b: Bool = True', 'print(b)'), ("value",)),
    ("bool_local_false", in_main('b: Bool = False', 'print(b)'), ("value",)),
    # A `-> Bool` CALLEE, whose declared return type is in the emitter's function
    # table rather than in the model's.
    ("bool_call", prog('def flag() -> Bool:', '    return True',
                       'print(flag())'), ("value",)),
    ("bool_call_local", in_main('def flag() -> Bool:', '    return True',
                                'b = flag()', 'print(b)'), ("value",)),
    # A module-level CONSTANT, which is the shape that needed the substitution
    # fixed as well as the printer: the folded word is 1, and the read used to
    # become an `IntLiteral(1)`.
    ("bool_const", prog('FLAG = True', 'print(FLAG)'), ("value",)),
    ("bool_const_annotated", prog('FLAG: Bool = False', 'print(FLAG)'),
     ("value",)),
    # And the MIXED print, which is the case the render has to get right: one
    # `printf`, five conversions, a literal and a value and a bool and `None`.
    ("print_mixed", prog('print("a", 1, "b", True, None)'), ("value",)),
    ("print_bool_with_text", in_main('a = 1', 'b = 1 + 1',
                                     'print("eq:", a == b, "!")'), ("value",)),

    # ── None: no representation at all, so only a build-time decision is
    #    renderable, and it is the four characters ─────────────────────────
    ("none_literal", prog('print(None)'), ("value",)),
    ("none_name", in_main('n2 = None', 'print(n2)'), ("value",)),
    ("none_const", prog('N = None', 'print(N)'), ("value",)),
    # A name rebound to something else claims NOTHING, which is the rule that
    # keeps the two rows above from being a wrong answer for this one.
    ("none_then_int", in_main('n2 = None', 'n2 = 5', 'print(n2)'),
     ("value",)),

    # ── str: the shape `print` has always had, and the escapes that decide
    #    whether a format string is a format string ───────────────────────
    ("str_plain", prog('print("hi")'), ("value",)),
    ("str_empty", prog('print("")'), ("value",)),
    ("str_double_quote", prog('print("a\\"b")'), ("value",)),
    ("str_single_quote", prog('print("a\'b")'), ("value",)),
    ("str_backslash", prog('print("a\\\\b")'), ("value",)),
    ("str_backslash_n", prog('print("a\\\\nb")'), ("value",)),
    ("str_tab", prog('print("a\\tb")'), ("value",)),
    ("str_newline", prog('print("a\\nb")'), ("value",)),
    ("str_return", prog('print("a\\rb")'), ("value",)),
    # A NUL is the one character this path cannot print at all: the literal is a
    # NUL-terminated table entry and `%s` stops at the first one, so the line
    # would be cut short at offset 1 of 3. Refused rather than truncated.
    ("str_nul_refused", prog('print("a\\x00b")'),
     ("refuse", "print() of text holding a NUL byte is refused")),
    ("str_nul_in_sep_refused", prog('print("a", "b", sep="\\x00")'),
     ("refuse", "print() of text holding a NUL byte is refused")),
    # A `%` is the escape that decides the WHOLE format-string discipline: it
    # has to reach printf doubled or it starts a conversion specification with
    # no argument behind it.
    ("str_percent", prog('print("100% done")'), ("value",)),
    ("str_percent_escape", prog('print("\\\\x25")'), ("value",)),
    # A RAW literal, where the backslash is TEXT and must survive as one.
    ("str_raw", prog('print(r"a\\nb")'), ("value",)),
    # Non-ASCII, which is already in the source text rather than arriving from
    # an escape.
    ("str_non_ascii", prog('print("h\\u00e9llo")'.replace("\\u00e9", "é")),
     ("value",)),
    ("str_name", in_main('s = "abc"', 'print(s)'), ("value",)),
    ("str_concat_literals", prog('print("a" "b")'), ("value",)),

    # ── bytes: CPython writes `repr(b)`, never the text ───────────────────
    ("bytes_simple", prog('print(b"ab")'), ("value",)),
    ("bytes_empty", prog('print(b"")'), ("value",)),
    # CPython's quote CHOICE, not a fixed quote: `'` unless the bytes hold `'`
    # and not `"`.
    ("bytes_apostrophe", prog('print(b"a\'b")'), ("value",)),
    ("bytes_double_quote", prog('print(b\'a"b\')'), ("value",)),
    # …and its escapes: the four named ones, with the backslash doubled.
    ("bytes_tab", prog('print(b"a\\tb")'), ("value",)),
    ("bytes_newline", prog('print(b"a\\nb")'), ("value",)),
    ("bytes_backslash", prog('print(b"a\\\\b")'), ("value",)),
    # …and the rest of the byte range: CPython escapes everything outside
    # printable ASCII, and the four named escapes are the only ones it names.
    ("bytes_del", prog('print(b"a\\x7fb")'), ("value",)),
    ("bytes_nul", prog('print(b"a\\x00b")'), ("value",)),
    ("bytes_high", prog('print(b"\\xff")'), ("value",)),
    ("bytes_utf8", prog('print(b"\\xc3\\xa9")'), ("value",)),
    ("bytes_control", prog('print(b"\\a\\b\\f\\v")'), ("value",)),
    ("bytes_backslash_t", prog('print(b"a\\\\tb")'), ("value",)),
    ("bytes_raw", prog('print(rb"a\\nb")'), ("value",)),
    ("bytes_space", prog('print(b" ")'), ("value",)),
    # …and the one `bytes` shape that is refused: a NAME. Its spelling is a
    # constant of the BINDING, which this path does not track, so writing the
    # first binding's bytes would be a plausible wrong answer.
    ("bytes_name_refused", in_main('b = b"ab"', 'print(b)'),
     ("refuse", "print() of a `bytes` value is refused")),
    ("bytes_name_rebound_ok", in_main('b = b"ab"', 'b = "ab"', 'print(b)'),
     ("value",)),

    # ── print's own arguments: `sep`, `end`, and the two that are refused ──
    ("print_two", prog('print("a", "b")'), ("value",)),
    ("print_three", prog('print("a", "b", "c")'), ("value",)),
    ("print_sep", prog('print("a", "b", sep="-")'), ("value",)),
    ("print_sep_empty", prog('print("a", "b", sep="", end="")'), ("value",)),
    ("print_sep_multi", prog('print("a", "b", "c", sep="")'), ("value",)),
    ("print_end", prog('print("a", "b", end="!")'), ("value",)),
    ("print_end_empty", prog('print("a", end="")'), ("value",)),
    ("print_no_args", prog('print()'), ("value",)),
    ("print_sep_only", prog('print(sep="-")'), ("value",)),
    ("print_end_only", prog('print(end="")'), ("value",)),
    ("print_flush", prog('print("a", flush=True)'), ("value",)),
    ("print_flush_false", prog('print("a", flush=False)'), ("value",)),
    ("print_sep_mixed", prog('print(1, 2, sep=",")'), ("value",)),

    # ── the shapes this path REFUSES, one row each ────────────────────────
    # A float: the value is one word and is right; the SPELLING is missing,
    # because CPython's is the shortest decimal that round-trips and no libc
    # conversion is that function.
    ("float_refused", prog('print(1.5)'),
     ("refuse", "print() of a float is refused")),
    ("float_zero_refused", prog('print(0.0)'),
     ("refuse", "print() of a float is refused")),
    ("float_in_a_print", prog('print("x", 1.5)'),
     ("refuse", "print() of a float is refused")),
    # A container, per syntax and through a name: the kind is `list:int` in
    # every case and the message says so.
    ("list_refused", prog('print([1, 2])'),
     ("refuse", "print() of a container is refused")),
    ("tuple_refused", prog('print((1, 2))'),
     ("refuse", "print() of a container is refused")),
    ("dict_refused", prog('print({1: 2})'),
     ("refuse", "print() of a container is refused")),
    ("set_refused", prog('print({1, 2})'),
     ("refuse", "print() of a container is refused")),
    ("list_name_refused", in_main('xs = [1, 2]', 'print(xs)'),
     ("refuse", "print() of a container is refused")),
    ("nested_list_refused", prog('print([[1], [2]])'),
     ("refuse", "print() of a container is refused")),
    # The formatting MINI-LANGUAGE: the format spec, `%`, `.format()`, the
    # conversions, `!r`/`!s`/`!a`, and `str()`/`repr()`/`format()` by name.
    # Each is a distinct missing thing and each row names its own.
    ("fstring_refused", prog('print(f"{1}")'),
     ("refuse", "an f-string literal on line 1 is refused")),
    ("fstring_spec_refused", prog('print(f"{1:5d}")'),
     ("refuse", "an f-string literal on line 1 is refused")),
    ("fstring_repr_refused", prog('print(f"{1!r}")'),
     ("refuse", "an f-string literal on line 1 is refused")),
    ("fstring_str_refused", prog('print(f"{1!s}")'),
     ("refuse", "an f-string literal on line 1 is refused")),
    ("fstring_ascii_refused", prog('print(f"{1!a}")'),
     ("refuse", "an f-string literal on line 1 is refused")),
    ("percent_refused", prog('print("%d" % 1)'),
     ("refuse", "print() cannot tell whether BinaryOp")),
    ("dot_format_refused", prog('print("{}".format(1))'),
     ("refuse", "print() cannot tell whether CallExpr")),
    ("format_call_refused", prog('print(format(1, "d"))'),
     ("refuse", "format")),
    ("str_call_refused", prog('print(str(1))'),
     ("refuse", "`%s` conversion in printf's format string reads `str(...)`")),
    ("repr_call_refused", prog('print(repr(1))'),
     ("refuse", "`repr(...)` is not lowered on this path")),
    # …and the two `print` keywords whose value must be a literal, which are
    # refused because they are BAKED INTO the format string.
    ("sep_not_a_literal", prog('print("a", "b", sep=1)'),
     ("refuse", "print(sep=...) must be a string literal")),
    ("flush_not_a_literal", prog('print("a", flush=1)'),
     ("refuse", "print(flush=...) must be True or False")),
    ("unknown_kwarg", prog('print("a", end2="x")'),
     ("refuse", "print() has no keyword argument 'end2'")),
    # `file=sys.stdout` — the one value CPython's own most ordinary print uses.
    # The `sys` MODULE is not a value this path can place, which is a module
    # boundary and not a formatting question, so the row names that.
    ("file_sys_stdout", prog('import sys', 'print("a", file=sys.stdout)'),
     ("refuse", "a module is not a value this path can place")),
]

# ── the rows that PIN what is still wrong ───────────────────────────────────
#
# Everything above is either right or refused with a sentence that says what is
# missing. These are neither, and a conformance table that left them out would
# be reporting the subject without its failures — the failure written down
# nowhere. Each asserts the CURRENT answer, states CPython's beside it, and
# names the bug doc; when the doc's fix lands the row becomes `("value",)` and
# the doc is deleted with it.
DIVERGENT_ROWS = [
    # A `\\uXXXX` escape is not decoded by `fire_compiler.decode_c_escapes`, so
    # the six characters reach stdout. CPython prints the character. The
    # decoder is SHARED with the interpreter (`python3 fire.py run` prints
    # `\u00e9` too) and with the compiled path, so this is a FRONT-END
    # question and not a print one, and it is already filed there with its whole
    # table: `LEXER unicode escapes are not decoded`.
    ("unicode_escape", prog('print("\\u00e9")'),
     ("divergent", "\\u00e9\n", "é\n")),
    # A TYPE VALUE is a 64-bit tag on this path and `is_number_kind` says a tag
    # prints as a number, DELIBERATELY (`formal/model.py`'s `TYPE_KIND`, and
    # `test_formal_run.py`'s `TYPE_VALUE_NUMBER_CASES` pins the tag). CPython's
    # `<class 'int'>` is a NAME chosen by the tag, which is a table this path
    # does not have. Named in
    # `bugs/FORMAL_a_print_of_a_container_needs_a_text_loop.md`'s last section,
    # with the instance row below it.
    ("type_value", prog('print(int)'),
     ("divergent", "3143511548502526014\n", "<class 'int'>\n")),
    # A class INSTANCE is one word here, and for a one-field struct that word is
    # its only field, so `print(p)` renders the field. Same section, same doc.
    # CPython's answer carries an ADDRESS, which is a fact about the allocator —
    # `judge` masks both sides rather than pinning one machine's heap.
    ("instance", prog('class P:', '    def __init__(self):',
                      '        self.x = 1', 'p = P()', 'print(p)'),
     ("divergent", "1\n", "<__main__.P object at 0x__addr__>\n")),
    # A `bytes` NAME is a REFUSAL and not a row of its own, so it is with the
    # other refusals: `b = b"ab"; print(b)` printed `ab` before this file's
    # subject was fixed, and CPython prints `b'ab'`. The spelling is a constant
    # of the LITERAL and this path does not track which literal a name was last
    # bound to, so it says so rather than writing the first binding's bytes.
]

# ── the shared readers, with no build at all ────────────────────────────────
#
# Four checks on `formal/model.py`'s own predicates, and they are here for the
# reason `test_formal_value_model.py` measures in its 19 cases: the RULES are
# what both backends read, so a row that pins a rule costs no image and catches
# a change to the table itself rather than to one lowering of it. Each answer is
# CPython's own, computed here.
UNIT_CHECKS = []


def unit(name, got, want):
    UNIT_CHECKS.append((name, got, want))


def _unit_checks():
    """Fill `UNIT_CHECKS` — split out so the table above stays readable."""
    import fire_compiler as F                                    # noqa: E402
    from formal import model as M                                # noqa: E402

    def lit(text, **kw):
        return F.Parser(F.py_tokenize("print(%s)" % text)).parse_module()[0] \
            .value.args[0]

    # CPython's own `repr` of each `bytes`, which is what `bytes_repr_body` has
    # to reproduce — computed here rather than written down. `repr(b)` is the
    # `b` PREFIX and then the quoted body, so the body is everything after it:
    # `[1:]`, which keeps the quotes the function is asked to choose.
    #
    # Every spelling is here, including the three that pin the reader: the value
    # is `lit.value` and NOT `decoded_literal(lit)` (`b"a\\tb"` would decode a
    # second time to a TAB), it is one character per BYTE (`b"\xff"` is U+00FF),
    # and a raw literal is already undecoded (`rb"a\nb"` holds the backslashes).
    for text, value in [("b\"ab\"", b"ab"), ("b\"a'b\"", b"a'b"),
                         ("b'a\"b'", b'a"b'), ("b\"a\\tb\"", b"a\tb"),
                         ("b\"a\\nb\"", b"a\nb"), ("b\"\"", b""),
                         ("rb\"a\\nb\"", b"a\\nb"),
                         ("b\"a\\\\tb\"", b"a\\tb"),
                         ("b\"a\\x00b\"", b"a\x00b"),
                         ("b\"\\x7f\"", b"\x7f"), ("b\"\\xff\"", b"\xff"),
                         ("b\"\\xc3\\xa9\"", b"\xc3\xa9"),
                         ("b\"\\a\\b\\f\\v\"", b"\a\b\f\v"),
                         ("b\" \"", b" ")]:
        got = M.bytes_repr_body(lit(text).value)
        unit("bytes_repr_body(%s)" % text, got, repr(value)[1:])
    # The two texts a bool prints as, from CPython.
    for text, value in [("True", True), ("False", False)]:
        unit("print_constant_text(%s)" % text,
             M.print_constant_text(lit(text)), str(value))
    unit("print_constant_text(None)", M.print_constant_text(lit("None")),
         "None")
    unit("print_constant_text(1)", M.print_constant_text(lit("1")), None)

    # Which shapes are bools whatever any declaration says, and which are not:
    # the second list is the half that matters, because an `and`/`or` yields
    # one of its OPERANDS and an arithmetic result is a number.
    for text, want in [("True", True), ("False", True),
                       ("1 < 2", True), ("1 is None", True),
                       ("2 in [1]", True), ("not 1", True)]:
        unit("bool_valued_shape(%s)" % text,
             M.bool_valued_shape(lit(text)), want)
    for text in ["1 + 1", "1 & 1", "[1, 2]", "'a'"]:
        unit("bool_valued_shape(%s) is not" % text,
             M.bool_valued_shape(lit(text)), False)


# ── the runner ──────────────────────────────────────────────────────────────

RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print("FAIL  %s" % what + ((": " + detail) if detail else ""),
              flush=True)
    return bool(ok)


#: The names CPython has to be able to RESOLVE for a row's source, and nothing
#: else. A `def`'s parameter and return annotations are evaluated when the `def`
#: runs (PEP 3107), so `def flag() -> Bool:` is a `NameError` under CPython
#: while the formal path reads `Bool` as a type declaration and is right about
#: it — and a LOCAL annotated assignment is not evaluated at all (PEP 526),
#: which is why `a: Int8 = 127` needs nothing here.
#:
#: Defining them changes no printed value: they are classes nothing constructs
#: and nothing prints, and a row that printed one of them would be testing the
#: annotation rather than the rendering. The image is built from the row's
#: source ALONE, so this text reaches CPython and not the backends — which is
#: the right way round, because it is CPython that needs the help.
ORACLE_PREAMBLE = "\n".join(
    "class %s: pass" % n for n in
    ("Bool", "Int", "Int8", "Int16", "Int32", "Int64",
     "UInt8", "UInt16", "UInt32", "UInt64", "Float64", "String", "DType")) + "\n"


def cpython(source):
    """Run `source` under this interpreter. Returns (rc, stdout)."""
    with tempfile.TemporaryDirectory(dir=os.path.join(HERE, "build")) as td:
        path = os.path.join(td, "oracle.py")
        with open(path, "w") as f:
            f.write(ORACLE_PREAMBLE)
            f.write(source)
        r = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, timeout=RUN_TIMEOUT)
    return r.returncode, r.stdout


def build_run(tmpdir, name, source, backend):
    """Build `source` for `backend` and RUN the image. Returns (rc, out, err)."""
    src = os.path.join(tmpdir, "%s_%s.py" % (name, backend))
    out = os.path.join(tmpdir, "%s_%s.bin" % (name, backend))
    with open(src, "w") as f:
        f.write(source)
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove",
            "--backend=%s" % backend, "-o", out, src]
    r = subprocess.run(argv, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    if r.returncode != 0:
        return ("BUILD-FAIL", (r.stderr or r.stdout), r.returncode)
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    return ("RAN", run.stdout, run.returncode, run.stderr.strip())


def judge(row_name, backend, res, want, oracle=None):
    """One (row, backend) verdict. Returns True when it is what the row wants."""
    tag = "[%s] %s" % (backend, row_name)
    kind = res[0]
    if kind == "BUILD-FAIL":
        text = res[1]
        if want[0] != "refuse":
            return check(False, tag + " builds", text.strip()[-300:])
        return check(want[1] in text, tag + " refuses naming %r" % want[1],
                     text.strip()[-300:])
    _, out, rc, err = res
    if want[0] == "refuse":
        return check(False, tag + " is refused, not answered",
                     "it printed %r and exited %d" % (out, rc))
    if rc != 0:
        return check(False, tag + " exits 0", "exit %d, stderr %r" % (rc, err))
    if want[0] == "value":
        want_text = oracle[1]
        return check(out == want_text, tag + " prints %r" % want_text,
                     "printed %r" % out)
    here, cpython_text = want[1], want[2]
    # Both texts, and the TABLE'S CPython answer first: a row whose "correct"
    # answer has gone stale must fail as a stale oracle rather than as a wrong
    # image, or the fix that makes the image right also silently rewrites the
    # claim about CPython.
    #
    # An OBJECT ADDRESS is masked on both sides (`ADDRESS_RE`): CPython writes
    # one for an instance and it is a fact about the allocator, not about the
    # program, so a row that pinned it literally could only ever pass on the
    # machine that wrote it. `here` is never masked — it is what THIS path
    # prints, and it is not an address.
    def mask(t):
        return ADDRESS_RE.sub("0x__addr__", t)
    if mask(oracle[1]) != mask(cpython_text):
        return check(False, tag + " the CPython answer in the table",
                     "this process printed %r, the table says %r"
                     % (oracle[1], cpython_text))
    return check(out == here,
                 tag + " prints the pinned %r (CPython: %r)"
                 % (here, cpython_text), "printed %r" % out)


def run_table(tmpdir, rows, want_index):
    for row in rows:
        name, source = row[0], row[1]
        want = row[2] if want_index == 2 else row[3]
        oracle = cpython(source)
        if want[0] != "refuse" and oracle[0] != 0:
            check(False, "[oracle] %s runs under CPython" % name,
                  "exit %d" % oracle[0])
            continue
        for backend in BACKENDS:
            res = build_run(tmpdir, name, source, backend)
            judge(name, backend, res, want, oracle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-k", dest="substring", default=None,
                    help="run only the rows whose name contains this")
    ap.add_argument("-m", "--models-only", action="store_true",
                    help="run only the no-build checks on formal/model.py")
    args = ap.parse_args()

    _unit_checks()
    if not args.models_only:
        rows = [r for r in ROWS if not args.substring or args.substring in r[0]]
        if not args.substring:
            rows += list(DIVERGENT_ROWS)
        else:
            rows += [r for r in DIVERGENT_ROWS if args.substring in r[0]]
        # Under `build/` rather than the system temp: the images are ~100 KB
        # each and a few hundred of them land in one directory, and `build/` is
        # the tree's own scratch (and already git-ignored), so a run leaves
        # nothing anywhere else.
        with tempfile.TemporaryDirectory(dir=os.path.join(HERE, "build")) as td:
            run_table(td, rows, 2)

    for name, got, want in UNIT_CHECKS:
        if args.substring and args.substring not in name:
            continue
        check(got == want, "model: " + name, "got %r, CPython says %r"
              % (got, want))

    npass = sum(1 for ok, _ in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print("\n%d/%d checks passed%s"
          % (npass, len(RESULTS),
             " (models only)" if args.models_only else ""))
    if args.verbose:
        for ok, what in RESULTS:
            print("  %s  %s" % ("PASS" if ok else "FAIL", what))
    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()