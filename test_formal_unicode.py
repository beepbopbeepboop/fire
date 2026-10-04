#!/usr/bin/env python3
"""STRINGS AND UNICODE on the formal backends, measured against CPython.

    python3 test_formal_unicode.py [-v] [case ...]

Every case in the two run tables carries the SAME program twice: once as Mojo
for `fire.py build --formal`, and once as Python that this file runs HERE, at
test time, and requires the image to agree with byte for byte. A hand-written
expected constant would be an assertion about a lowering made by the same
person who wrote the lowering, and a program that computes the right number for
the wrong reason passes either way.

Both architectures are required, and the reason is the project's standing one:
the two disagreeing answers this class is made of have both happened — an
f-string refused on one machine and answered on the other, a `sorted()` over
string keys returning them in interning order — and a one-sided assertion would
have been green throughout.

## What this file is for

A string on the formal path is a bare `char *` to NUL-terminated BYTES, and
that is decided (`bugs/FORMAL_string_value_model.md` §"The decision"). A Python
`str` is a sequence of CODE POINTS. For ASCII those are the same number, which
is why every answer here was right for a reason nobody had written down; for
anything else they are not, and the divergence is not a rounding error — it
changes which CHARACTER a position names:

    len("héllo")             6 where CPython says 5
    len("日本")              6 where CPython says 2
    len("a\\U0001F600b")      6 where CPython says 3
    "héllo".find("llo")      3 where CPython says 2
    "日本"[1]                one 0x9c — the second byte of 本
    printf("%6s", "héllo")   [héllo] where CPython prints [ héllo]

The decision these tables pin is `formal/model.py`'s TEXT ENCODING block, and
it has three answers rather than one: a LITERAL's text is known at compile time
so the character count is folded; an image with no non-ASCII string literal in
it has every string in it ASCII, so `strlen` IS `len()` and nothing changes;
and anything else is REFUSED BY NAME, because a byte count presented where a
character count belongs is a small plausible integer that a program then uses
as an index.

So the tables are three kinds of row and all three are load-bearing:

  * ANSWERED — the build knows the answer and must match CPython. The folds.
  * RIGHT ALREADY — `count`, `startswith`, `endswith`, `lstrip`, `==`, `in` and
    `%s` with no width are byte operations whose CPython answer happens to be
    the same one, because UTF-8 is self-synchronising. They are here so that a
    later change to the encoding block cannot quietly break them, and so that
    the file says which operations were CHECKED rather than assumed.
  * REFUSED — the build must refuse, on both machines, with the same words, and
    the words must name the non-ASCII case. An `expect=` marker on one of these
    would be a silenced test; there are none here.

Every refusal row also has a GUARD row beside it in the same table where it can:
an ASCII-only program that spells the same construct must still build and answer
CPython. Without the guard a fix that refused everything would pass this file.

## What this file does NOT cover, and where it went instead

  * `\\uXXXX`, `\\UXXXXXXXX` and `\\N{…}` ESCAPES are not decoded by
    `fire_compiler.decode_c_escapes`, so all three engines make a six-character
    string out of `"\\u00e9"` where CPython makes one character. That is a
    FRONT-END question shared by the interpreter, the compiled path and both
    formal backends, not a formal-backend divergence, so it is filed rather
    than fixed here: `bugs/LEXER_unicode_escapes_are_not_decoded.md`.
  * `ord`, `chr`, `hash`, `encode`, `decode` and iteration over a string are
    refused or dangling before this file reaches them, for reasons that have
    nothing to do with encoding (`ord`/`chr` are not lowered at all;
    `encode`/`decode` are refused as value methods; iteration over a string is
    `string_iteration_refusal`). They are recorded in that doc and in the two
    bug docs above; this file pins what the encoding block decides.
  * `upper`/`lower`/`strip`/`title`/`join`/`split`/`replace`/`reverse` are
    refused by `LENGTH_DEPENDENT_METHODS` for the missing BUFFER, before any
    question about ASCII or UTF-8 arises. That is the right refusal and it is
    not this file's to change.
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 240
RUN_TIMEOUT = 60

# ── the CPython-oracle rows ─────────────────────────────────────────────────
#
# (name, mojo_source, cpython_source)
#
# The Python column is the same program with `printf` spelled `print`, and it
# is RUN here rather than transcribed: the expected output is whatever CPython
# prints for that text.
ORACLE_CASES = [
    # ── `len`: the FOLD, which is a new capability ────────────────────────
    #
    # A string literal's text is known at compile time, so the number of
    # characters in it is `len()` of that text — no machine instruction and no
    # libc call, and no dependence on what the image's other strings hold.  All
    # three answered the BYTE count before the encoding block: 6, 6 and 6.
    ("len_latin1_literal_folds",
     'def main(n):\n'
     '    printf("len=%d\\n", len("héllo"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("len=%d" % len("héllo"), end="\\n")\n'),

    ("len_cjk_literal_folds",
     'def main(n):\n'
     '    printf("len=%d\\n", len("日本"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("len=%d" % len("日本"), end="\\n")\n'),

    # A character OUTSIDE the BMP: FOUR bytes, one code point, and the widest
    # gap in the table between "count the bytes" and "count the characters".
    #
    # Spelled as the CHARACTER and not as `\\U0001F600`, which is the whole of
    # a separate front-end defect: `fire_compiler.decode_c_escapes` handles the
    # C simple escapes and `\\xHH` and leaves `\\u`/`\\U`/`\\N{}` alone, so an
    # escape spelling would measure THAT (see the header and the bug doc) rather
    # than what this row is for.  With a real character the fold answers 3, where
    # the byte count was 6.
    ("len_astral_literal_folds",
     'def main(n):\n'
     '    printf("len=%d\\n", len("a😀b"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("len=%d" % len("a😀b"), end="\\n")\n'),

    # Every width in one string, so a fold that counted anything but code points
    # would have to be wrong about all of them at once to pass.
    ("len_mixed_widths_literal_folds",
     'def main(n):\n'
     '    printf("len=%d\\n", len("aé日😀z"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("len=%d" % len("aé日😀z"), end="\\n")\n'),

    ("len_empty_literal_folds",
     'def main(n):\n'
     '    printf("len=%d\\n", len(""))\n'
     '    return 0\n',
     'def main():\n'
     '    print("len=%d" % len(""), end="\\n")\n'),

    # The fold has to be a VALUE and not a special-cased spelling: it is read
    # by arithmetic here, so a build that materialised the number in the wrong
    # register would answer 0 or the address.
    ("len_fold_is_an_ordinary_value",
     'def main(n):\n'
     '    var i = len("日本") * 10 + 1\n'
     '    printf("i=%d\\n", i)\n'
     '    return 0\n',
     'def main():\n'
     '    i = len("日本") * 10 + 1\n'
     '    print("i=%d" % i, end="\\n")\n'),

    # `\\xHH` is decoded by `fire_compiler.decode_c_escapes`, so the literal's
    # TEXT is one character whose UTF-8 is two bytes — and the fold counts the
    # character.  This answered 2 (the bytes) before the encoding block, which
    # is the escape-decoding half of the same defect rather than a separate one.
    ("len_of_a_hex_escaped_byte_is_one_character",
     'def main(n):\n'
     '    printf("len=%d\\n", len("\\xe9"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("len=%d" % len("\\xe9"), end="\\n")\n'),

    # The ASCII BOUNDARY, and the row that says where the fold stops: 0x7F is
    # ASCII, so it is one byte and one character and the `strlen` is right.  A
    # boundary at 0x80 instead would refuse the DEL and accept U+0080, which is
    # the opposite of what UTF-8 says.
    ("len_of_a_del_character_is_still_a_strlen",
     'def main(n):\n'
     '    printf("len=%d\\n", len("\\x7f"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("len=%d" % len("\\x7f"), end="\\n")\n'),

    # ── `len`: an ASCII IMAGE is untouched ────────────────────────────────
    #
    # The condition on the refusal is the whole-image fact, so these are the
    # rows that prove it does not cost the corpus anything.  All three built and
    # ran and answered CPython before the encoding block too — that is the
    # point: the block is inert on an image with no non-ASCII literal in it.
    ("len_of_a_local_is_still_strlen",
     'def main(n):\n'
     '    var s = "abc"\n'
     '    printf("len=%d\\n", len(s))\n'
     '    return 0\n',
     'def main():\n'
     '    s = "abc"\n'
     '    print("len=%d" % len(s), end="\\n")\n'),

    ("len_through_a_string_parameter_is_still_strlen",
     'def size(s: String) -> Int:\n'
     '    return len(s)\n'
     'def main(n):\n'
     '    printf("len=%d\\n", size("abcdef"))\n'
     '    return 0\n',
     'def size(s):\n'
     '    return len(s)\n'
     'def main():\n'
     '    print("len=%d" % size("abcdef"), end="\\n")\n'),

    # The SAME literal read both ways in one program.  The `strlen` path and
    # the fold path are two lowerings of one question and this row is what
    # says they agree — the failure mode this project keeps meeting, where a
    # construct is right on one spelling and wrong on the other and only the
    # spelled one is in the test.
    ("len_of_a_name_and_of_the_same_literal_agree",
     'def main(n):\n'
     '    var s = "abc"\n'
     '    printf("%d %d\\n", len(s), len("abc"))\n'
     '    return 0\n',
     'def main():\n'
     '    s = "abc"\n'
     '    print("%d %d" % (len(s), len("abc")), end="\\n")\n'),

    # ── `find`: a POSITION, which is the wrong-answer-that-indexes one ────
    #
    # `strstr` returns a BYTE offset and CPython returns a CHARACTER offset.
    # `"héllo".find("llo")` answered 3 where CPython says 2, and a program
    # that slices or subscripts with that reads from the wrong place.
    ("find_of_a_non_ascii_literal_folds",
     'def main(n):\n'
     '    printf("i=%d\\n", "héllo".find("llo"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("i=%d" % "héllo".find("llo"), end="\\n")\n'),

    ("find_past_a_three_byte_character_folds",
     'def main(n):\n'
     '    printf("i=%d\\n", "日本語".find("本"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("i=%d" % "日本語".find("本"), end="\\n")\n'),

    ("find_of_a_non_ascii_needle_folds",
     'def main(n):\n'
     '    printf("i=%d\\n", "héllo".find("é"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("i=%d" % "héllo".find("é"), end="\\n")\n'),

    # The two answers that are NOT "the offset of a match": -1 is Python's
    # "absent" where `strstr` returns a NULL, and 0 is Python's empty-needle
    # answer where `strstr` returns the haystack.  A fold that computed
    # `str(hay).find(needle)` in Python would get both right; one that
    # special-cased only a hit would not.
    ("find_of_a_missing_needle_folds_to_minus_one",
     'def main(n):\n'
     '    printf("i=%d\\n", "héllo".find("zz"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("i=%d" % "héllo".find("zz"), end="\\n")\n'),

    ("find_of_an_empty_needle_folds_to_zero",
     'def main(n):\n'
     '    printf("i=%d\\n", "héllo".find(""))\n'
     '    return 0\n',
     'def main():\n'
     '    print("i=%d" % "héllo".find(""), end="\\n")\n'),

    # An ASCII haystack through a NAME, i.e. the ordinary `strstr` path in an
    # image that has a non-ASCII literal elsewhere.  It must NOT be refused:
    # the offset `strstr` returns over ASCII text is a character offset
    # whatever the needle holds, because a Python `str` needle always starts
    # with an ASCII byte or a lead byte and so cannot match inside ASCII text.
    ("find_on_an_ascii_haystack_is_still_strstr",
     'def main(n):\n'
     '    var table = ["héllo"]\n'
     '    printf("i=%d j=%d\\n", "hello".find("llo"), len(table))\n'
     '    return 0\n',
     'def main():\n'
     '    table = ["héllo"]\n'
     '    print("i=%d j=%d" % ("hello".find("llo"), len(table)), end="\\n")\n'),

    # ── RIGHT ALREADY, and pinned so the block cannot break them ──────────
    #
    # Each of these is a byte operation whose CPython answer is the same
    # answer, for one reason: UTF-8 is self-synchronising, so a byte substring
    # test over well-formed UTF-8 has the same BOOLEAN result, the same COUNT
    # and the same PREFIX/SUFFIX answer as a code point test.  They are here
    # because the alternative is an encoding block whose only evidence is that
    # it did not break something nobody measured.
    ("count_of_a_non_ascii_string_is_the_character_count",
     'def main(n):\n'
     '    printf("n=%d\\n", "héllo".count("l"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("n=%d" % "héllo".count("l"), end="\\n")\n'),

    ("count_of_a_multi_byte_needle_is_the_character_count",
     'def main(n):\n'
     '    printf("n=%d\\n", "日本語".count("本"))\n'
     '    return 0\n',
     'def main():\n'
     '    print("n=%d" % "日本語".count("本"), end="\\n")\n'),

    ("startswith_a_non_ascii_prefix",
     'def main(n):\n'
     '    if "héllo".startswith("hé"):\n'
     '        printf("yes\\n")\n'
     '    else:\n'
     '        printf("no\\n")\n'
     '    return 0\n',
     'def main():\n'
     '    print("yes" if "héllo".startswith("hé") else "no", end="\\n")\n'),

    ("endswith_a_non_ascii_suffix",
     'def main(n):\n'
     '    if "héllo".endswith("héllo"):\n'
     '        printf("yes\\n")\n'
     '    else:\n'
     '        printf("no\\n")\n'
     '    return 0\n',
     'def main():\n'
     '    print("yes" if "héllo".endswith("héllo") else "no", end="\\n")\n'),

    ("contains_a_non_ascii_substring",
     'def main(n):\n'
     '    if "llo" in "héllo":\n'
     '        printf("yes\\n")\n'
     '    else:\n'
     '        printf("no\\n")\n'
     '    return 0\n',
     'def main():\n'
     '    print("yes" if "llo" in "héllo" else "no", end="\\n")\n'),

    ("lstrip_a_non_ascii_string",
     'def main(n):\n'
     '    printf("[%s]\\n", "  héllo".lstrip())\n'
     '    return 0\n',
     'def main():\n'
     '    print("[%s]" % "  héllo".lstrip(), end="\\n")\n'),

    ("equality_of_two_non_ascii_literals",
     'def main(n):\n'
     '    if "héllo" == "héllo":\n'
     '        printf("eq\\n")\n'
     '    else:\n'
     '        printf("ne\\n")\n'
     '    return 0\n',
     'def main():\n'
     '    print("eq" if "héllo" == "héllo" else "ne", end="\\n")\n'),

    ("inequality_of_two_different_non_ascii_literals",
     'def main(n):\n'
     '    if "héllo" == "hello":\n'
     '        printf("eq\\n")\n'
     '    else:\n'
     '        printf("ne\\n")\n'
     '    return 0\n',
     'def main():\n'
     '    print("eq" if "héllo" == "hello" else "ne", end="\\n")\n'),

    # TRUTHINESS is a `strlen` against zero and stays one: a string is empty
    # iff its first byte is the terminator, whatever its encoding.  The empty
    # string here is ASCII, so this row also says the truthiness conversion is
    # not gated on the image's literals.
    ("truthiness_of_a_non_ascii_string_is_a_strlen",
     'def main(n):\n'
     '    var s = "é"\n'
     '    var e = ""\n'
     '    printf("%d %d\\n", 1 if s else 0, 1 if e else 0)\n'
     '    return 0\n',
     'def main():\n'
     '    s = "é"\n'
     '    e = ""\n'
     '    print("%d %d" % (1 if s else 0, 1 if e else 0), end="\\n")\n'),

    # A `%s` with NO width is a byte-for-byte copy, which is what CPython's
    # `sys.stdout` does too — so this is right, and it is the row that says
    # the width is the whole of the difference.
    ("printf_s_without_a_width_prints_the_bytes",
     'def main(n):\n'
     '    printf("[%s]\\n", "héllo")\n'
     '    return 0\n',
     'def main():\n'
     '    print("[%s]" % "héllo", end="\\n")\n'),

    ("printf_s_of_cjk_prints_the_bytes",
     'def main(n):\n'
     '    printf("[%s]\\n", "日本")\n'
     '    return 0\n',
     'def main():\n'
     '    print("[%s]" % "日本", end="\\n")\n'),

    ("printf_s_of_an_astral_character_prints_the_bytes",
     'def main(n):\n'
     '    printf("[%s]\\n", "a😀b")\n'
     '    return 0\n',
     'def main():\n'
     '    print("[%s]" % "a😀b", end="\\n")\n'),

    # A non-ASCII KEY, and a dict's key compare is a content compare, so it is
    # a byte compare and UTF-8 makes that the same answer.
    ("dict_lookup_with_a_non_ascii_key",
     'def main(n):\n'
     '    var d = {"hé": 1, "日": 2}\n'
     '    printf("%d %d %d\\n", d["hé"], d["日"], len(d))\n'
     '    return 0\n',
     'def main():\n'
     '    d = {"hé": 1, "日": 2}\n'
     '    print("%d %d %d" % (d["hé"], d["日"], len(d)), end="\\n")\n'),

    # ── GUARDS: the ASCII rows beside every refusal ──────────────────────
    #
    # `printf_width_on_ascii_text_is_a_byte_width_and_agrees`,
    # `subscript_into_an_ascii_string_reads_its_byte` and
    # `printf_width_beside_a_non_ascii_literal_still_prints` are the three
    # rows a "refuse every width" or "refuse every element read" fix would
    # fail.  The last one is the sharpest: the image DOES hold a non-ASCII
    # literal, and an ASCII operand is still answered.
    ("printf_width_on_ascii_text_agrees_with_cpython",
     'def main(n):\n'
     '    printf("[%6s]\\n", "hello")\n'
     '    return 0\n',
     'def main():\n'
     '    print("[%6s]" % "hello", end="\\n")\n'),

    ("printf_width_beside_a_non_ascii_literal_still_prints",
     'def main(n):\n'
     '    var table = ["héllo"]\n'
     '    printf("[%6s]\\n", "hello")\n'
     '    return 0\n',
     'def main():\n'
     '    table = ["héllo"]\n'
     '    print("[%6s]" % "hello", end="\\n")\n'),

    # The subscript on an ASCII string.  CPython's `s[0]` is a one-CHARACTER
    # string where this path's is the BYTE, so `%d` of it is a number where
    # CPython raises — the case prints the byte through `%c`, which is the
    # spelling the two agree on, and the DIVERGENCE of types is recorded in
    # `bugs/FORMAL_string_value_model.md` §"what was found while looking" as a
    # consequence of the missing buffer rather than of this block.
    ("subscript_into_an_ascii_string_reads_its_byte",
     'def main(n):\n'
     '    var s = "abc"\n'
     '    printf("c=[%c]\\n", s[1])\n'
     '    return 0\n',
     'def main():\n'
     '    s = "abc"\n'
     '    print("c=[%s]" % s[1], end="\\n")\n'),

    ("len_of_a_list_of_non_ascii_strings_is_the_blob_count",
     'def main(n):\n'
     '    var xs = ["héllo", "日本"]\n'
     '    var first = xs[0]\n'
     '    printf("n=%d\\n", len(xs))\n'
     '    return 0\n',
     'def main():\n'
     '    xs = ["héllo", "日本"]\n'
     '    first = xs[0]\n'
     '    print("n=%d" % len(xs), end="\\n")\n'),
]


# ── the REFUSAL rows ────────────────────────────────────────────────────────
#
# (name, mojo_source, needles)
#
# Every one must be refused on BOTH machines and with the SAME words, because a
# diagnostic that diverges by architecture is the same defect with a different
# subject (see the header).  The needles are chosen to be load-bearing: each one
# names the thing the reader has to change, so a message that lost one would
# stop being a diagnosis.
REFUSAL_CASES = [
    # The headline refusal: a string whose text this build cannot see.  Before
    # the encoding block this BUILT and answered 6 for `len("héllo")`.
    ("refuse_len_of_a_non_ascii_string_the_build_cannot_see",
     'def main(n):\n'
     '    var s = "héllo"\n'
     '    printf("len=%d\\n", len(s))\n'
     '    return 0\n',
     ["is refused", "BYTES where CPython answers in CHARACTERS",
      "'héllo'", "len(s)", "char *"]),

    # The same question through a PARAMETER, which is the shape the corpus is
    # full of and the one where a per-operand analysis could never answer: the
    # callee does not know what it was called with, and the CALL SITE does not
    # know what the callee will ask for.  The image's own literals decide.
    ("refuse_len_through_a_string_parameter_given_non_ascii_text",
     'def size(s: String) -> Int:\n'
     '    return len(s)\n'
     'def main(n):\n'
     '    printf("len=%d\\n", size("héllo"))\n'
     '    return 0\n',
     ["is refused", "BYTES where CPython answers in CHARACTERS",
      "len(s)", "'héllo'"]),

    # A POSITION.  The needle `s.find(llo)` is the construct as the source
    # spells it, which is what makes the message findable.
    ("refuse_find_of_a_non_ascii_haystack_the_build_cannot_see",
     'def main(n):\n'
     '    var s = "héllo"\n'
     '    printf("i=%d\\n", s.find("llo"))\n'
     '    return 0\n',
     ["is refused", "BYTES where CPython answers in CHARACTERS",
      "s.find('llo')", "'héllo'"]),

    # The NEEDLE is a name here and the haystack is a literal: one known text
    # is not enough for a POSITION, because which character the offset names
    # depends on everything before the match.  A different program from the row
    # above, refusing for the same reason — this is the row that says the two
    # operands are not interchangeable, and it is the one that would fail if a
    # "fix" asked only for the haystack's text.
    ("refuse_find_with_a_named_needle",
     'def main(n):\n'
     '    var p = "llo"\n'
     '    printf("i=%d\\n", "héllo".find(p))\n'
     '    return 0\n',
     ["is refused", "bytes from the start of the text"]),

    # An ELEMENT.  A byte is not a character, and this is a REFUSAL rather than
    # a fold because the answer CPython wants is a new one-character object
    # and a string value here is a `char *` into the image's read-only text.
    ("refuse_subscript_into_a_non_ascii_string",
     'def main(n):\n'
     '    var s = "日本"\n'
     '    printf("c=[%c]\\n", s[1])\n'
     '    return 0\n',
     ["is refused on a string whose text is not ASCII",
      "s[1]", "0x9c", "one CHARACTER"]),

    # The same element read through a LITERAL receiver, which is the row that
    # says knowing the text does not help: the obstacle is where the answer
    # would live, not what it is.
    ("refuse_subscript_into_a_non_ascii_literal",
     'def main(n):\n'
     '    printf("c=[%c]\\n", "日本"[1])\n'
     '    return 0\n',
     ["is refused on a string whose text is not ASCII",
      "the literal", "nowhere to put one"]),

    # A WIDTH.  `printf` is a C function and C has no characters, so `%6s`
    # pads to six BYTES.  The needle quotes the specifier as the source spells
    # it, including the flag, because `%-6s` and `%6s` pad on opposite sides
    # and a message that said "the width" would not say which one.
    ("refuse_printf_width_on_non_ascii_text",
     'def main(n):\n'
     '    printf("[%6s]\\n", "héllo")\n'
     '    return 0\n',
     ["`%6s`", "is refused", "BYTES where CPython answers in CHARACTERS"]),

    ("refuse_printf_left_width_on_non_ascii_text",
     'def main(n):\n'
     '    printf("[%-6s]\\n", "héllo")\n'
     '    return 0\n',
     ["`%-6s`", "is refused"]),

    # A PRECISION is the same defect as a width — `%.3s` of `"héllo"` emits
    # three bytes, half a character — and the quantifier scanner is what
    # catches it.  Without this row a scanner that read only the width would
    # pass everything above.
    ("refuse_printf_precision_on_non_ascii_text",
     'def main(n):\n'
     '    printf("[%.3s]\\n", "héllo")\n'
     '    return 0\n',
     ["`%.3s`", "is refused"]),

    # A width on an operand the build CANNOT see, in an image that holds a
    # non-ASCII literal elsewhere.  This is the whole-image condition doing
    # its work: the operand here is an ASCII name, and it is still refused,
    # because `%6s` of a value that might hold an `é` cannot be emitted with a
    # byte width and hope.
    ("refuse_printf_width_on_an_unseen_operand_in_a_non_ascii_image",
     'def main(n):\n'
     '    var table = ["héllo"]\n'
     '    var s = "hello"\n'
     '    printf("[%6s]\\n", s)\n'
     '    return 0\n',
     ["`%6s`", "is refused", "'héllo'"]),
]


def build_formal(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=BUILD_TIMEOUT, cwd=HERE)


def run_oracle_case(name, msrc, psrc, tmpdir, verbose):
    """Build on BOTH backends and require CPython's own output, byte for byte.

    CPython's answer is produced HERE by running the Python column, so the
    expectation is not a constant this file's author wrote about a lowering
    this file's author also wrote.
    """
    py = os.path.join(tmpdir, name + ".py")
    with open(py, "w", encoding="utf-8") as f:
        f.write(psrc + "\nmain()\n")
    ref = subprocess.run([sys.executable, py], capture_output=True,
                         timeout=RUN_TIMEOUT)
    if ref.returncode != 0:
        return False, (f"the CPython reference itself failed (exit "
                       f"{ref.returncode}): "
                       f"{ref.stderr.decode('utf-8', 'replace').strip()[-200:]}")
    want = ref.stdout
    mo = os.path.join(tmpdir, name + ".mojo")
    with open(mo, "w", encoding="utf-8") as f:
        f.write(msrc)
    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        p = build_formal(mo, out, backend)
        if p.returncode != 0:
            text = (p.stderr or p.stdout)
            return False, (f"--backend={backend} did not build: "
                           f"{text.strip()[-400:]}")
        run = subprocess.run([out], capture_output=True, timeout=RUN_TIMEOUT)
        got = run.stdout
        if got != want:
            return False, (f"--backend={backend} printed {got!r}, CPython "
                           f"printed {want!r}")
        if run.returncode != 0:
            return False, (f"--backend={backend} computed CPython's answer "
                           f"and exited {run.returncode}")
        if verbose:
            print(f"      {backend}: {got!r} == CPython")
    return True, ""


def run_refusal_case(name, msrc, needles, tmpdir, verbose):
    """Both backends must REFUSE, with the same words and every needle in them."""
    mo = os.path.join(tmpdir, name + ".mojo")
    with open(mo, "w", encoding="utf-8") as f:
        f.write(msrc)
    said = {}
    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        p = build_formal(mo, out, backend)
        text = (p.stderr or p.stdout)
        if p.returncode == 0:
            return False, (f"--backend={backend} BUILT a construct that must "
                           f"be refused — that is the wrong answer this case "
                           f"exists for, and it is silent")
        said[backend] = text
        missing = [n for n in needles if n not in text]
        if missing:
            return False, (f"--backend={backend} refused, but without "
                           f"{missing!r}: {text.strip()[-300:]}")
    if said["arm64"] != said["x86_64"]:
        return False, ("the two architectures refused DIFFERENTLY, which is "
                       "the same defect with a different subject")
    if verbose:
        print(f"      both refused: {needles[0]!r}")
    return True, ""


# ── the DECISION, pinned in process ─────────────────────────────────────────
#
# The tables above need a build each, which is what makes them trustworthy and
# also what makes them slow to iterate on.  These run against `formal/model.py`
# directly and pin the three answers and the two boundaries they turn on, so a
# change to the encoding block that moves a boundary shows up here in a second
# rather than in a minute of images.
def model_checks():
    sys.path.insert(0, HERE)
    import fire_compiler as F
    from formal import model as M

    passed, failures = 0, []

    def ok(label, got, want):
        nonlocal passed
        if got == want:
            passed += 1
        else:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    # ── the ASCII boundary, which is the one that decides the whole block ──
    #
    # `str.isascii` is the predicate, and the rows around it are the boundary:
    # 0x7F is ASCII and 0x80 is not, which is UTF-8's rule and not an
    # aesthetic choice — a lead byte is at least 0xC2 and a continuation byte
    # is 0x80..0xBF, so every multi-byte character has at least one byte
    # outside ASCII.  A block that drew its line at 0x80 exclusive in the other
    # direction (refusing DEL, accepting U+0080) would refuse a string of
    # control characters and accept a two-byte one.
    ok("isascii: DEL is ASCII", M.text_is_ascii("\x7f"), True)
    ok("isascii: U+0080 is not", M.text_is_ascii("\x80"), False)
    ok("isascii: empty is ASCII", M.text_is_ascii(""), True)
    ok("isascii: LATIN SMALL LETTER E WITH ACUTE is not",
       M.text_is_ascii("é"), False)
    ok("isascii: CJK is not", M.text_is_ascii("日本"), False)
    ok("isascii: a non-str is not ASCII", M.text_is_ascii(None), False)
    ok("codepoint count of 日本", M.codepoint_count("日本"), 2)
    ok("codepoint count of an astral character",
       M.codepoint_count("\U0001F600"), 1)

    # ── the image scan ──
    #
    # It has to find a literal in a NESTED function (which is a different
    # `FunctionDef` in the same statement list), skip a RAW literal (whose
    # backslashes are content, so decoding it would invent escapes it did not
    # ask for) and skip a BYTES literal (whose bytes are a blob's element
    # width, not a string's), and return DECODED TEXT rather than nodes — a
    # diagnostic that quotes `StringLiteral(value='…', line=…)` is a diagnostic
    # nobody can act on.
    def stmts(src):
        return F.Parser(F.py_tokenize(src)).parse_module()

    found = M.non_ascii_strings_in(stmts(
        'def outer(n):\n'
        '    var a = "plain"\n'
        '    def inner(n):\n'
        '        return "héllo"\n'
        '    return inner(n)\n'))
    ok("the scan finds a nested non-ASCII literal", found, ["héllo"])

    ok("the scan skips ASCII",
       M.non_ascii_strings_in(stmts('def main(n):\n    printf("%s", "abc")\n')),
       [])

    ok("the scan skips a raw literal",
       M.non_ascii_strings_in(stmts(
           'def main(n):\n    printf("%s", r"h\\u00e9llo")\n')), [])

    ok("the scan skips a bytes literal",
       M.non_ascii_strings_in(stmts(
           'def main(n):\n    printf("%s", b"\\xc3\\xa9")\n')), [])

    ok("the scan decodes before deciding",
       M.non_ascii_strings_in(stmts(
           'def main(n):\n    printf("%s", "\\u00e9")\n')), [])

    # ── the three answers of `string_codepoint_verdict` ──
    saved = M.non_ascii_strings()
    try:
        M.publish_non_ascii_strings([])
        # `args[1]`, not `args[0]`: `printf("%d", …)` puts the FORMAT first,
        # and indexing 0 would test the format string — which is ASCII, and so
        # would pass every row below for the wrong reason.
        lit = stmts('def main(n):\n    printf("%d", len("héllo"))\n')
        ascii_lit = stmts('def main(n):\n    printf("%d", len("abc"))\n')
        # An ASCII LITERAL: the `strlen` is the answer and the fold must NOT
        # be taken, because a fold of `"abc"` would be a second spelling of a
        # length the machine already computes.
        node = ascii_lit[0].body[0].value.args[1].args[0]
        ok("verdict: an ASCII literal stays a strlen",
           M.string_codepoint_verdict("len(\"abc\")", node, '"abc"')[0],
           M.LEN_FROM_STRLEN)
        # An ASCII image and an operand the build cannot see: also `strlen`,
        # and that is the row the corpus runs on.
        ok("verdict: unseen text in an ASCII image stays a strlen",
           M.string_codepoint_verdict("len(s)", None, "s"),
           (M.LEN_FROM_STRLEN, None))

        # A non-ASCII literal in the image changes the answer for the
        # UNSEEN operand only — the literal itself still folds.
        M.publish_non_ascii_strings(["héllo"])
        ok("verdict: unseen text in a non-ASCII image is refused",
           M.string_codepoint_verdict("len(s)", None, "s")[0], None)
        node = lit[0].body[0].value.args[1].args[0]
        verdict, folded = M.string_codepoint_verdict('len("héllo")', node,
                                                     '"héllo"')
        ok("verdict: a non-ASCII literal folds", verdict,
           M.LEN_FROM_CODPOINT_FOLD)
        ok("verdict: the fold is the CHARACTER count", folded, "5")
    finally:
        M.publish_non_ascii_strings(saved)

    # ── `string_position_verdict`, which has two operands ────────────────
    #
    # The row worth pinning is the third one: an ASCII haystack with an
    # UNKNOWN needle still gets `strstr`, because a Python `str` needle always
    # begins with an ASCII byte or a lead byte and so cannot match inside ASCII
    # text at all.  A block that demanded both texts would refuse every `find`
    # in the corpus over a needle it happens not to be able to match.
    #
    # The image has to hold the non-ASCII literal for the fold to be the
    # answer rather than a coincidence: with an empty image an ASCII `strstr`
    # and a fold agree on this case, so the row would pass for the wrong
    # reason — which is the mistake `test_formal_run.py`'s CPython-pair group
    # was created to catch, in a new place.
    saved = M.non_ascii_strings()
    try:
        M.publish_non_ascii_strings(["héllo"])
        hay = stmts('def main(n):\n    printf("%d", "héllo".find("llo"))\n')
        hay_arg = hay[0].body[0].value.args[1].func.obj
        needle = hay[0].body[0].value.args[1].args[0]
        ok("position: two literals fold",
           M.string_position_verdict('"héllo".find("llo")', hay_arg, needle),
           (M.STRING_POSITION_FOLD, "2"))
        # A MISS is Python's -1 and not a `strstr` NULL, so the fold has to
        # carry the absent case rather than only a hit.
        miss = stmts('def main(n):\n    printf("%d", "héllo".find("zz"))\n')
        ok("position: a literal miss folds to -1",
           M.string_position_verdict(
               '"héllo".find("zz")',
               miss[0].body[0].value.args[1].func.obj,
               miss[0].body[0].value.args[1].args[0]),
           (M.STRING_POSITION_FOLD, "-1"))
        ascii_hay = stmts('def main(n):\n    printf("%d", "hello".find("llo"))\n')
        ok("position: an ASCII haystack with an unknown needle is strstr",
           M.string_position_verdict('"hello".find(p)',
                                     ascii_hay[0].body[0].value.args[1].func.obj,
                                     None)[0],
           M.STRING_POSITION_STRLEN)
        # A non-ASCII haystack with an UNKNOWN needle can be neither, and this
        # is the row the REFUSAL table exercises end to end.
        ok("position: a non-ASCII haystack with an unknown needle is refused",
           M.string_position_verdict('s.find(llo)', hay_arg, None)[0], None)
    finally:
        M.publish_non_ascii_strings(saved)

    # ── the width scanner, which is the one piece of new parsing ──────────
    #
    # One entry per CONSUMED argument (so `*` counts), the quantifier's own
    # text including its flags, `None` for no width and no precision, and None
    # for a format this does not parse — which is the permissive direction, so
    # an unusual `%` in a corpus format string cannot become a new refusal.
    ok("widths: no quantifier",
       M.printf_text_widths("%s"), [None])
    ok("widths: a width", M.printf_text_widths("%6s"), ["6"])
    ok("widths: a left-aligned width keeps its flag",
       M.printf_text_widths("%-6s"), ["-6"])
    ok("widths: a zero pad keeps its flag", M.printf_text_widths("%06s"), ["06"])
    ok("widths: a precision", M.printf_text_widths("%.3s"), [".3"])
    ok("widths: width and precision", M.printf_text_widths("%10.3s"), ["10.3"])
    ok("widths: a star width consumes its argument",
       M.printf_text_widths("%*s"), ["*"])
    ok("widths: a non-string conversion keeps its own column",
       M.printf_text_widths("%6d %s"), ["6", None])
    ok("widths: a literal percent consumes nothing",
       M.printf_text_widths("%s%%%d"), [None, None])
    ok("widths: an unparsed format is None",
       M.printf_text_widths("%2$6s"), None)

    # ── the two refusals are INDEPENDENT of each other ────────────────────
    #
    # A string INDEX (a string used to index a string) is refused by
    # `string_index_refusal` on the operand KINDS, with no reference to the
    # image's literals; a string ELEMENT of non-ASCII text is refused by
    # `string_element_refusal` on the image.  Merging them would make one
    # architecture's answer depend on whether the other had asked yet.
    saved = M.non_ascii_strings()
    try:
        M.publish_non_ascii_strings([])
        ok("element: an ASCII image does not refuse a string element",
           M.string_element_refusal(None, None), None)
        M.publish_non_ascii_strings(["日本"])
        ok("element: a non-ASCII image refuses a string element",
           M.string_element_refusal(None, None) is not None, True)
        ok("index: a string index is refused on the KINDS alone",
           M.string_index_refusal(M.STR_KIND, M.STR_KIND, "t") is not None,
           True)
        ok("index: an integer index is not that refusal",
           M.string_index_refusal(M.STR_KIND, M.INT_KIND, "0"), None)
    finally:
        M.publish_non_ascii_strings(saved)

    return passed, failures


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is {platform.machine()}")
        return 0

    def selected(table):
        return [c for c in table if not args.cases or c[0] in args.cases]

    known = {c[0] for c in ORACLE_CASES} | {c[0] for c in REFUSAL_CASES}
    if args.cases:
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
            return 2

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, msrc, psrc in selected(ORACLE_CASES):
            good, why = run_oracle_case(name, msrc, psrc, tmpdir, args.verbose)
            print(f"  {'PASS' if good else 'FAIL'}  {name}"
                  + ("" if good else f"\n        {why}"))
            passed += good
            failed += not good
        for name, msrc, needles in selected(REFUSAL_CASES):
            good, why = run_refusal_case(name, msrc, needles, tmpdir,
                                         args.verbose)
            print(f"  {'PASS' if good else 'FAIL'}  {name}"
                  + ("" if good else f"\n        {why}"))
            passed += good
            failed += not good
    mp, mf = model_checks()
    for detail in mf:
        print(f"  FAIL  model: {detail}")
    print(f"formal unicode: model PASS={mp} FAIL={len(mf)}")
    passed += mp
    failed += len(mf)
    print(f"formal unicode: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())