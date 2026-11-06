from . import *

# ── WHAT A LOWERED STRING METHOD'S ARGUMENTS MAY BE ────────────────────────
#
# `POINTER_BOUNDED_METHODS` decides WHICH string methods exist on this path and
# `value_method_refusal` guards the RECEIVER of each one. Neither of them says
# anything about the ARGUMENTS, and that gap was the whole of the measured
# defect this block exists for. Every one of the five lowerings reads its
# argument as a `char *` and hands it to a libc routine, so an argument that is
# not a `char *` is not a wrong answer — it is a call into the C library with a
# number where an address belongs. Measured, both architectures, from a green
# build:
#
#     "abc".find(98)     ->  SIGSEGV, exit 139
#     "abc".count(98)    ->  SIGSEGV, exit 139
#     "abc".startswith(97) -> SIGSEGV, exit 139
#
# 98 is `'b'`, so every one of those is a call that CPython REJECTS with a
# `TypeError` and that this path turned into a dereference of the integer 98.
# The receiver guard could not have caught it — `"abc"` is a string literal, so
# the receiver's kind is exactly right — which is why the answer cannot be a
# second receiver guard but has to be a guard on the operand the libc call
# actually reads.
#
# Two more shapes reach the same place without faulting, and they are worse
# because they ANSWER:
#
#     "ab".startswith(("x", "a"))    CPython True   this path 0
#     "xxaxx".lstrip("x")            CPython "axx"  this path "xxaxx"
#
# The first is a TUPLE, which on this path is a counted blob, so its address
# was compared as text — and `strncmp` found no match and reported 0, which is
# a plausible-looking boolean. The second is an argument that was not read at
# all: `lstrip`'s lowering passed `model.STRIP_CHARS` to `strspn` whatever the
# source said, so the `chars` parameter was accepted, type-checked against
# nothing, and ignored. Both are in `test_formal_str_methods.py` as `guard` and
# `lstrip` rows, and both were measured before this block existed.
#
# THE SHAPE OF THE ANSWER. `string_method_call_plan` below is ONE reader for
# both architectures, asked once per call from each backend's method dispatch
# and returning one of four things. The DECISION is here because a decision
# taken per architecture is a decision that can differ; the FACTS are the
# backend's, which is why `arg_kinds` is passed in rather than read here.

# The four answers. `None` as the verdict is the refusal, so a caller writes
# `if plan is None: raise CodegenError(why)` and cannot mistake a refusal for
# an answer — which is the failure mode a bare string return invites.
STRING_PLAN_EMIT = "emit"          # emit the libc lowering; payload is the
                                    # accept set for `lstrip`, else None
STRING_PLAN_FOLD_INT = "fold_int"  # payload is the INTEGER to materialise
STRING_PLAN_FOLD_TEXT = "fold_text"  # payload is the TEXT to intern

# The argument's NAME in each of the five methods, and how many this path
# accepts. The names are CPython's own (`str.lstrip.__doc__` and the
# signatures beside it) rather than this file's, because the refusal quotes the
# parameter the source passed and a reader looking it up will look it up under
# CPython's spelling. The full list is CPython's, INCLUDING the parameters this
# path does not lower, because the refusal has to name the one it is refusing —
# a message that said "argument 1" where the source said `start` would be
# telling the reader something they can see.
STRING_METHOD_ARGS = {
    "lstrip": ("chars",),
    "strip": (),
    "rstrip": (),
    "startswith": ("prefix",),
    "endswith": ("suffix",),
    "find": ("sub", "start", "end"),
    "count": ("sub", "start", "end"),
    "upper": (),
    "lower": (),
}

# How many of the above each lowering actually emits. `find`'s and `count`'s
# are 1: the window's `start`/`end` are refused, and `string_method_unlowered_
# arg_refusal` is what says so. The two counts are separate because CPython's
# parameter list and this path's are different facts, and a table that held one
# column for both would have to invent the difference somewhere else.
STRING_METHOD_MAX_ARGS = {
    "lstrip": 1, "strip": 0, "rstrip": 0, "startswith": 1, "endswith": 1, "find": 1, "count": 1,
    "upper": 0, "lower": 0,
}

# The parameters of the above that may be OMITTED. `lstrip()` with no argument
# is not a degenerate call — it is the call that strips WHITESPACE, which is a
# different answer from `lstrip(chars)` for every receiver CPython does not
# already have no leading `chars` character in, so the two arities are two
# methods rather than one method and a shorthand. That is also why it is a
# separate table rather than a `min_args` column: whether a parameter is
# optional is CPython's fact, and which one it is decides which sentence the
# arity refusal uses.
STRING_METHOD_OPTIONAL_ARGS = {
    "lstrip": ("chars",),
}

# The parameters this path does not lower, per method, and the half that is
# missing for each. `find`'s and `count`'s are the same pair and the same
# reason, and the two halves are NOT the same size, which is why they are two
# entries rather than one sentence: `start` only moves where the search begins,
# which is pointer arithmetic this path can do, and `end` has to BOUND it,
# which no libc routine here does — `strstr` walks to its haystack's NUL and
# there is no `strnstr` in libSystem. So the honest split is "start could be
# lowered and is not yet" against "end has no libc form at all", and a refusal
# that gave them one reason would send a reader to build the wrong thing.
STRING_METHOD_UNLOWERED_ARGS = {
    "find": {
        "start": "a position to start from, which is pointer arithmetic on a "
                 "`char *` — `strstr(s + start, sub)` — and is not lowered here "
                 "only because the CLAMPING CPython applies to it (a negative "
                 "`start` counts back from the end, a `start` past the end is "
                 "the end) is a four-way branch that has to be emitted per "
                 "architecture rather than folded",
        "end": "the far end of a window, and no libc routine on this path can "
               "bound a search with one: `strstr` walks to its haystack's NUL "
               "and libSystem has no `strnstr`, so the bound would have to be "
               "a hand-written `strncmp` loop in each backend",
    },
    "count": {
        "start": "a position to start from; see `find`'s `start`, which is "
                 "the same offset and the same clamping",
        "end": "the far end of a window; see `find`'s `end`, which is the "
               "same missing bounded search",
    },
}


def string_method_unlowered_arg_refusal(dotted: str, method: str,
                                        extra: list) -> str | None:
    """Why these extra arguments cannot be lowered, or None when there are none.

    The message names each PARAMETER and says what is missing for it, because
    "takes exactly one argument on this path (got 2)" — which is what both
    emitters said, in their own words, before this existed — tells a reader
    that a count is wrong without telling them WHICH of `start`/`end` it is or
    why. It also does not say what to do instead, and the two facts together
    are what make a refusal actionable.

    An extra argument that is past CPython's OWN parameter list is not a
    parameter at all — `lstrip("x", "y")` is a `TypeError` in CPython, and
    `"a".lstrip("x", "y")` has no second parameter to be missing — so it is
    named by its POSITION and the message says the call has more arguments than
    the method has parameters. Naming it `argument 2` rather than inventing a
    parameter name is the honest form, and it is the reason `names[i]` is
    guarded: an unguarded index here took an `IndexError` out of the refusal
    path, which is a crash in the diagnostic rather than a diagnostic.
    """
    if not extra:
        return None
    names = STRING_METHOD_ARGS[method]
    limit = STRING_METHOD_MAX_ARGS[method]
    table = STRING_METHOD_UNLOWERED_ARGS.get(method, {})
    named, halves, past = [], [], False
    for i in extra:
        if i < len(names):
            n = names[i]
        else:
            past = True
            n = "argument %d" % (i + 1)
        named.append(n)
        halves.append(table.get(
            n, "a parameter the method does not have: CPython's `%s` takes "
               "at most %d argument%s, so this call is a TypeError rather "
               "than a question" % (method, len(names),
                                    "" if len(names) == 1 else "s")))
    return (f"{dotted}() lowers {names[:limit]} and this call also passes "
            f"{', '.join('`%s`' % n for n in named)}. What is missing here is "
            f"{' and '.join(halves)}. "
            + ("`.%s(%s)` with the needle alone is the whole of what this path "
               "answers for `%s`" % (method, names[0], method)))


def string_method_count_empty_needle(dotted: str, recv):
    """`(verdict, payload)` for `count("")`, whose answer is a LENGTH.

    The one `count` whose answer is not a function of the needle's position in
    the haystack: an empty needle matches at each of the L+1 boundaries of a
    string of length L, so the answer is `len(s) + 1`. The emitter computes
    that as `strlen(s) + 1`, which is right in BYTES and wrong in CHARACTERS
    for any text that is not ASCII — measured, `"héllo".count("")` answered 7
    where CPython answers 6, because `strlen` sees five characters as six
    bytes.

    It is the ONLY such row in this table's `count` group, and that is not an
    accident: a non-empty needle's byte occurrences coincide with its character
    occurrences, because UTF-8 is self-synchronising (a lead byte occurs only
    at a character boundary) and a needle written in source is always a whole
    number of characters. So `count` over `"é"` or `"ll"` is right by that
    argument, while the empty needle's "+1 per boundary" is a count of
    boundaries and there is one fewer boundary per multi-byte character. The
    rows that need stating are therefore the empty one and only the empty one,
    and saying so here is what keeps the next reader from re-deriving it.

    `STRING_PLAN_FOLD_INT` when the build knows the receiver's text, which is
    the answer with no instruction at all; the permissive `EMIT` when the image
    holds no non-ASCII literal, where `strlen` and `len` are the same function;
    and a refusal otherwise, for the same reason `string_position_verdict`
    refuses: a byte count presented as a character count is a small, stable,
    plausible-looking wrong number.
    """
    text = string_literal_text(recv)
    if text is not None:
        return (STRING_PLAN_FOLD_INT, codepoint_count(text) + 1)
    if non_ascii_strings():
        return (None, codepoint_refusal(
            f"{dotted}()", spelled(recv)))
    return (STRING_PLAN_EMIT, None)




def string_method_arg_refusal(dotted: str, method: str, param: str, arg,
                              kind) -> str | None:
    """Why `arg` cannot be read as a `char *`, or None when it can.

    This is the guard that did not exist, and the four cases it distinguishes
    are the four things a source can put where a needle goes. They are handled
    in this order because they get progressively less specific, and the order is
    the order a reader needs them in: a shape this path KNOWS how to answer
    (a literal tuple of affixes, folded by the caller) never reaches here, a
    shape it can name (a number) gets the number in the message, and a shape
    it can only observe (something whose kind the source does not say) gets the
    "annotate it" sentence.

    **The kind guard is positive evidence, for the reason
    `value_method_refusal`'s is.** `kind is None` is "this build cannot tell",
    and it is NOT read as "it is fine": the unclassified case is refused rather
    than guessed, because the guess here is a dereference. `find`'s own
    docstring records the same reasoning for the position it computes —
    `string_position_verdict` refuses rather than emitting a byte offset as a
    character one — and this is the argument-side half of that decision.
    """
    if string_operand_is_string(kind):
        return None
    if is_list_kind(kind) or isinstance(arg, (F.TupleExpr, F.ListExpr)):
        return (f"{dotted}() is given a {spelled(arg)} as its `{param}`, and a "
                f"tuple on this path is a COUNTED BLOB rather than a sequence "
                f"of text: lowering it would compare the blob's HEADER — its "
                f"element count, then its first element — as though those "
                f"bytes were the affix, and `strncmp` would find no match and "
                f"answer 0, which is a plausible-looking boolean rather than a "
                f"wrong one that looks wrong. Measured on both architectures, "
                f"`\"ab\".startswith((\"x\", \"a\"))` answered 0 where CPython "
                f"answers True. This path answers a tuple whose elements are "
                f"all string LITERALS, where the build can see the affixes and "
                f"compute Python's own answer; a tuple bound to a name cannot "
                f"be seen into, so bind the affixes to a literal tuple or "
                f"compare each one yourself")
    if kind is None:
        return (f"{dotted}() is given a `{param}` whose type the source does "
                f"not say — {spelled(arg)} — and this lowering reads it as a "
                f"`char *` and hands it to the C library, which would walk "
                f"whatever address those bytes hold. Annotate the {param} "
                f"(e.g. `{param}: String`), bind it to a string literal, or "
                f"pass a literal directly")
    return (f"{dotted}() is given a `{param}` of kind {kind!r} — "
            f"{spelled(arg)} — and this lowering reads its argument as a "
            f"`char *` and hands it to the C library, so a number here is an "
            f"ADDRESS rather than text to search for. Measured on both "
            f"architectures, `\"abc\".find(98)` took SIGSEGV — exit 139 — "
            f"because 98 was dereferenced, and CPython rejects that call with "
            f"a `TypeError` rather than answering it. Pass text: "
            f"`{param}=\"b\"`")


def string_method_lstrip_accept_set(dotted: str, arg) -> str | None:
    """The `strspn` ACCEPT SET for `lstrip(chars)`, or None to refuse.

    `strspn(s, set)` returns the length of the initial segment of `s` made only
    of bytes in `set`, which is exactly `lstrip(chars)` whenever every
    character of `chars` is one byte wide — so the argument IS the accept set
    and the lowering is one instruction different from the no-argument form.
    That is why this is a fold of a `StringLiteral` into the emitter rather
    than a new lowering: the emitter already emits `strspn(s, X)` and already
    had `X` hard-wired to `model.STRIP_CHARS`, which is why the `chars`
    parameter was accepted and then ignored.

    **The refusal is about `chars` and not about the RECEIVER, and the
    distinction is the whole of the correctness argument.** Python's `chars` is
    a set of CHARACTERS and `strspn`'s is a set of BYTES, and the two agree
    exactly when every character in the set is single-byte. They disagree the
    moment the set holds a multi-byte character, and they disagree SILENTLY:
    with `chars = "Ã"` (U+00C3, bytes C3 83) and a receiver of `"é"`
    (C3 A9), Python strips nothing — `é` is not `Ã` — while `strspn` consumes
    the leading C3 and hands back a pointer into the middle of a character,
    which prints as an invalid UTF-8 fragment. So the check is on the SET.

    The permissive row follows `string_position_verdict`'s reasoning rather
    than inventing a new one: when the build cannot see the set, the IMAGE's
    own fact is the bound, because on this path every string value is a
    literal's interned bytes or an interior pointer into them
    (`model.py`'s string-representation note, point 3). So an image with no
    non-ASCII literal cannot hold a non-ASCII `chars`, whatever the name is
    bound to, and `non_ascii_strings()` is a sufficient answer rather than a
    guess.
    """
    text = string_literal_text(arg)
    if text is not None:
        if text_is_ascii(text):
            return text
        return (f"{dotted}(chars) is refused: its `chars` is a set of "
                f"CHARACTERS in CPython and a set of BYTES here, and the two "
                f"agree only while every character in the set is one byte "
                f"wide. `{spelled(arg)}` holds "
                f"{_non_ascii_examples([text]) or 'a non-ASCII character'}, so "
                f"`strspn` would consume the leading byte of a multi-byte "
                f"character and hand back a pointer into the middle of it — a "
                f"string that prints as an invalid UTF-8 fragment rather than "
                f"as an error. Pass a `chars` of ASCII characters, where the "
                f"byte set and the character set are the same set")
    if not non_ascii_strings():
        # The image holds no non-ASCII literal, so every `char *` in it is
        # ASCII bytes and the accept set is one byte per character whatever
        # the name is bound to.
        return None
    return (f"{dotted}(chars) is refused: `chars` is a set of CHARACTERS in "
            f"CPython and a set of BYTES here, and the two agree only while "
            f"every character in the set is one byte wide. This image holds a "
            f"string literal that is not ASCII — "
            f"{_non_ascii_examples(non_ascii_strings())} — and "
            f"{spelled(arg)} is a name, so the build cannot see what "
            f"characters its value holds. Pass a `chars` of ASCII "
            f"characters, where the byte set and the character set are the "
            f"same set")




# ── THE COMPILE-TIME FOLD, and the thirty-five methods it answers ──────────
#
# `LEN_FROM_CODPOINT_FOLD`, `STRING_POSITION_FOLD` and `ord_fold` already fold
# the three constructs whose answer is a function of text the build can read.
# This block is the same idea for the rest of `str`, and the reason it is worth
# having is arithmetic rather than taste: on this path the answer to most string
# methods is a NEW BUFFER, and there is nowhere to put one — a literal is
# interned into `__TEXT,__text` with `initprot 0x5`, read and execute and not
# writable, which is the measured reason half of `LENGTH_DEPENDENT_METHODS`
# gives. But that obstacle is about the RUN-TIME answer, and it does not apply
# when the build can see the text: then the answer is computed here, in Python,
# by the same `str` methods CPython runs, and the result is an ordinary literal
# this path already knows how to emit. No buffer, no length, no new instruction
# on either architecture.
#
# So the row's cost is a SCOPE, not a correctness risk, and the scope has one
# rule: **every operand's text must be visible to the build.** A name, a
# parameter or a call result is text behind a `char *` at run time, and there
# the fold does not apply and the method's own refusal stands. That is the same
# rule `string_position_verdict` applies to `find`, and the reason it can be
# stated once for the whole family.
#
# **What this buys that is not obvious, and is the reason to do it at all: the
# fold is exact where a run-time lowering could not be.** `isdigit` over "²",
# `upper` over "ß", `title` over "ǳ" and `swapcase` over "i̇" are Unicode
# questions, and a byte-level implementation of any of them would be a
# DIFFERENT predicate rather than a wrong one this path could honestly emit (see
# `CODEPOINT_CLASS_REFUSAL`). Computed here they are CPython's own answers,
# because they are CPython's own methods — `"²".isdigit()` folds to True, and
# the image materialises a 1. So the twelve predicates, which are the largest
# group in `dir(str)` after the case conversions, are answered outright for
# text the build can see, with no character model at all.
#
# The values are the UNBOUND `str` METHODS, not lambdas. `str.upper` applied to
# a decoded literal is Python's own `upper`, so this table cannot be a second
# implementation of any of them: a change in CPython's rules changes this
# backend's answers, which is the property a table of hand-written case folding
# would not have.
#
# `arity` is the number of arguments the method takes AFTER the receiver, and it
# is `None` for a method this path will not fold however many arguments it is
# given — `translate` (a table), `format`/`format_map` (another worker's claim),
# `encode` (a `bytes` result, which is a blob and not a string). The arity is
# what decides a refusal for a call this path would otherwise fold: a
# three-argument `center` is CPython's answer too, so it folds, and a
# three-argument `strip` is a `TypeError` in CPython, so the fold declines and
# the call is refused rather than folded into something CPython never computed.
STRING_FOLDED_METHODS = {


    # ── the case conversions: receiver only, and all six are Unicode ──
    "upper": (str.upper, 0, STR_KIND),
    "lower": (str.lower, 0, STR_KIND),
    "title": (str.title, 0, STR_KIND),
    "capitalize": (str.capitalize, 0, STR_KIND),
    "swapcase": (str.swapcase, 0, STR_KIND),
    "casefold": (str.casefold, 0, STR_KIND),
    # ── the trims: receiver only ──
    # `lstrip` is absent because it is LOWERED, not folded: its answer is an
    # interior pointer and `strspn` computes it at run time, which also answers
    # the case where the receiver is a name. Folding it would be the smaller
    # answer.
    "strip": (str.strip, 0, STR_KIND),
    "rstrip": (str.rstrip, 0, STR_KIND),


    # ── the pads: a WIDTH, and a fill character that may be given or not ──
    "zfill": (str.zfill, 1, STR_KIND),
    "center": (str.center, 2, STR_KIND),
    "ljust": (str.ljust, 2, STR_KIND),
    "rjust": (str.rjust, 2, STR_KIND),
    # ── the substitutions ──
    "replace": (str.replace, 3, STR_KIND),
    "removeprefix": (str.removeprefix, 1, STR_KIND),
    "removesuffix": (str.removesuffix, 1, STR_KIND),
    "expandtabs": (str.expandtabs, 1, STR_KIND),


    # ── the predicates: receiver only, and each is a CHARACTER-class
    # question. This is the group a byte-level lowering could not answer at


    # all, and the group the fold answers outright. ──
    "isalnum": (str.isalnum, 0, INT_KIND),
    "isalpha": (str.isalpha, 0, INT_KIND),
    "isascii": (str.isascii, 0, INT_KIND),
    "isdecimal": (str.isdecimal, 0, INT_KIND),
    "isdigit": (str.isdigit, 0, INT_KIND),
    "isidentifier": (str.isidentifier, 0, INT_KIND),
    "islower": (str.islower, 0, INT_KIND),
    "isnumeric": (str.isnumeric, 0, INT_KIND),
    "isprintable": (str.isprintable, 0, INT_KIND),
    "isspace": (str.isspace, 0, INT_KIND),
    "istitle": (str.istitle, 0, INT_KIND),
    "isupper": (str.isupper, 0, INT_KIND),


    # ── the three SEARCHES that raise or need a direction `find` does not
    # answer. `index` is `find` plus "and raise if it is -1", and the raise is
    # the whole difference; folding it computes the position AND the fact that
    # there is one, and a needle that is absent falls through to the refusal
    # rather than to a -1 that CPython never returns. `rfind` walks backwards
    # and `rindex` is its raising form; both are pure functions of the text and


    # both are answers a `strstr` cannot give. ──
    "index": (str.index, 1, INT_KIND),
    "rfind": (str.rfind, 1, INT_KIND),
    "rindex": (str.rindex, 1, INT_KIND),
}

# The methods this block deliberately does NOT fold, and the one-line reason for
# each. A table rather than a comment, because `test_formal_str_methods.py`
# asserts against it: a `str` method that is neither in `STRING_FOLDED_METHODS`
# nor in `POINTER_BOUNDED_METHODS` nor given a refusal reason fails that file's
# coverage check, so this table and the test are two ends of one ratchet.
STRING_METHODS_NOT_FOLDED = {
    "translate": "a translation TABLE, keyed by code point — the same missing "
                 "half as `CODEPOINT_CODEC_REFUSAL`, and the table itself is a "
                 "sequence this path would have to read",
    "maketrans": "builds that table",
    "encode": "its result is a `bytes` object, which on this path is a counted "
              "BLOB rather than a `char *`, so there is nothing to intern the "
              "answer into",
    "decode": "CPython's `str.decode` does not exist — the method is on "
              "`bytes` — so there is no `str` method to fold",
    "format": "`formal65-format-and-repr`'s claim; not touched here",
    "format_map": "`formal65-format-and-repr`'s claim; not touched here",
    "join": "its operand is a SEQUENCE, and a sequence's ELEMENTS have to be "
            "text the build can see; see `STRING_FOLDED_LIST_METHODS`",
    "split": "its result is a SEQUENCE; see `STRING_FOLDED_LIST_METHODS`",
    "rsplit": "its result is a SEQUENCE; see `STRING_FOLDED_LIST_METHODS`",
    "splitlines": "its result is a SEQUENCE; see "
                  "`STRING_FOLDED_LIST_METHODS`",
    "partition": "its result is a SEQUENCE; see `STRING_FOLDED_LIST_METHODS`",
    "rpartition": "its result is a SEQUENCE; see "
                  "`STRING_FOLDED_LIST_METHODS`",
    # The five lowered ones are answered at RUN time by a libc call, which is
    # strictly more than the fold: it also answers a receiver that is a name.
    "lstrip": "lowered by `strspn`, which also answers a receiver the build "
              "cannot see",
    "startswith": "lowered by `strncmp`, same",
    "endswith": "lowered by `strncmp`, same",
    "find": "lowered by `strstr`, and folded for a non-ASCII haystack by "
            "`string_position_verdict`",
    "count": "lowered by a `strstr` loop, and folded for an EMPTY needle by "
             "`string_method_count_empty_needle`",
}


def fold_operand_value(node):
    """The Python VALUE of a literal the build can compute with, else None.

    The operand reader `string_method_fold` uses, and it is four shapes
    because a folded string method takes more than text: `zfill`'s width is an
    integer, `split`'s separator may be `None` (which is a DIFFERENT algorithm
    — CPython's whitespace rule with its own runs — and not a default value the
    fold could substitute), and `expandtabs`'s size may be omitted.

    `0 - 2` is here for the reason it is all over this tree's own tests: the
    project's convention is that a negative number is written `0 - n` because a
    unary minus binds tighter than the arithmetic around it (see
    `test_formal_int_semantics.py`'s precedence rows), so a fold that read only
    `IntLiteral` would decline every negative width in a corpus written this
    way. The evaluator is deliberately tiny — literals, `+`/`-` over them, and
    a unary sign — because every shape it does NOT cover is a shape that falls
    through to the refusal, which is the safe direction: a fold that guessed an
    arithmetic expression's value would be computing CPython's answer to a
    question nobody asked.

    `None` is returned for "not a literal the build can see", and a fold that
    wants a real `None` cannot have one — which is why `split(None)` is in
    `STRING_METHODS_NOT_FOLDED`'s companion table rather than folded here. The
    distinction is worth stating because it is the one place this function's
    return value is ambiguous, and it is resolved by the CALLER checking
    `isinstance(node, F.NoneLiteral)` rather than by this function inventing a
    sentinel.
    """
    if isinstance(node, F.StringLiteral):
        return string_literal_text(node)
    if isinstance(node, F.BoolLiteral):
        return bool(node.value)
    if isinstance(node, F.IntLiteral):
        return int(node.value)
    if isinstance(node, F.NoneLiteral):
        return None
    if isinstance(node, F.UnaryOp) and node.op in ("-", "+"):
        inner = fold_operand_value(node.operand)
        if isinstance(inner, int) and not isinstance(inner, bool):
            return -inner if node.op == "-" else inner
        return None
    if isinstance(node, F.BinaryOp) and node.op in ("+", "-"):
        left = fold_operand_value(node.left)
        right = fold_operand_value(node.right)
        if (isinstance(left, int) and not isinstance(left, bool)
                and isinstance(right, int) and not isinstance(right, bool)):
            return left + right if node.op == "+" else left - right
        return None
    return None


def string_method_fold(method: str, dotted: str, recv, args: list):
    """`(verdict, payload)` for a FOLDABLE string method, or `EMIT` to decline.

    The reader behind `STRING_FOLDED_METHODS`, and the rule it applies is one
    sentence: **if the build can see the text of every operand, the answer is
    Python's own and no instruction is needed.** `STRING_PLAN_FOLD_TEXT` for a
    `str` answer, `STRING_PLAN_FOLD_INT` for a number, and
    `(STRING_PLAN_EMIT, None)` — which the caller reads as "not foldable, carry
    on" — whenever any operand's text is behind a `char *`.

    The decline cases are four and each is deliberate:

      * an operand the build cannot see. The fold is a compile-time
        computation, so a run-time value has nothing to compute from.
      * a call CPython itself rejects, or one whose arity this path does not
        fold (`"abc".center(1, "-", "x")`). The fold DECLINES rather than
        raising, so the caller's own refusal speaks — a fold that raised
        CPython's `TypeError` would be reporting Python's message for a
        construct this path has its own words about.
      * a folded `str` that CONTAINS A NUL. `"a\0b".upper()` is `"A\0B"` in
        CPython and is unrepresentable here: a `char *` ends at its NUL, so
        emitting the answer would produce `"A"` — a string that is not what the
        method returned and that looks entirely plausible. This is the same
        latent gap `model.py`'s string-representation note records for
        `len`, reached from a method.
      * a folded LIST, which is `STRING_FOLDED_LIST_METHODS`'s business and is
        declined here so that the text table above stays a table of TEXT and
        NUMBERS.

    Everything it computes, it computes by calling the unbound `str` method on
    the DECODED text — `string_literal_text`, which is the tree's one decoder,
    the same one both backends' `_intern_string` calls. So `"a\\nb".upper()` is
    an `A`, a newline and a `B`, and the image interns those three characters
    and not a backslash and an `n`.
    """
    entry = STRING_FOLDED_METHODS.get(method)
    if entry is None:
        return (STRING_PLAN_EMIT, None)
    fn, arity, kind = entry
    if len(args) > arity:
        return (STRING_PLAN_EMIT, None)
    recv_text = string_literal_text(recv)
    if recv_text is None:
        return (STRING_PLAN_EMIT, None)
    arg_texts = []
    for a in args:
        if isinstance(a, F.NoneLiteral):
            return (STRING_PLAN_EMIT, None)
        text = fold_operand_value(a)
        if text is None:
            return (STRING_PLAN_EMIT, None)
        arg_texts.append(text)
    try:
        value = fn(recv_text, *arg_texts)
    except Exception:                                       # noqa: BLE001
        # CPython raises here — `index` on an absent needle, `center` with a
        # two-character fill — so there is no answer to fold. Decline and let
        # the caller refuse in its own words.
        return (STRING_PLAN_EMIT, None)
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        return (STRING_PLAN_FOLD_INT, value)
    if isinstance(value, str):
        if "\0" in value:
            return (STRING_PLAN_EMIT, None)
        return (STRING_PLAN_FOLD_TEXT, value)
    return (STRING_PLAN_EMIT, None)


def string_method_fold_nul_refusal(dotted: str) -> str:
    """Why a folded answer holding a NUL cannot be emitted, if it is needed."""
    return (f"{dotted}() folds to text containing a NUL, and a `char *` on "
            f"this path ENDS at its NUL, so interning the answer would produce "
            f"the text before it — a string that is not what the method "
            f"returned and that prints as though it were. This is the same "
            f"representation gap `len` of a string with an embedded NUL has, "
            f"reached from a method")


def string_method_call_plan(method: str, dotted: str, recv, args: list,
                            arg_kinds: list):
    """`(verdict, payload)` for one call to a string method.

    The ONE reader of "may this call be lowered", asked by both backends from
    their method dispatch, so a construct the two machines could disagree about
    cannot be answered differently by them. It is asked BEFORE
    `value_method_refusal`, which is the order that lets the two guards be
    complementary rather than conflicting: a method that can be FOLDED here has
    no receiver question to ask — its receiver is a literal by definition — and
    a method that cannot is refused by one of the two, with this one naming the
    operand and `value_method_refusal` naming the missing representation.

    `arg_kinds` is the backend's own per-argument answer — one kind per
    positional argument — because the kind of an expression is a flow fact
    (`ValueKinds` plus each backend's `_string_vars`), and re-deriving it here
    would be the second reader of a fact the first one already settled with the
    same arguments.

    `STRING_PLAN_EMIT`'s payload is the `lstrip` ACCEPT SET when the source
    supplied one and `None` when it did not, which is the only payload an emit
    verdict carries; the fold verdicts carry the folded value itself.
    """
    if method in STRING_FOLDED_METHODS:
        plan, payload = string_method_fold(method, dotted, recv, args)
        if plan != STRING_PLAN_EMIT or method not in string_buffer_methods():
            return (plan, payload)
        # fell through fold for a buffer method; check non-ASCII
    if method in string_buffer_methods() and non_ascii_strings():
        return (None, buffer_case_refusal(dotted))
    if method not in STRING_METHOD_ARGS:
        return (STRING_PLAN_EMIT, None)
    names = STRING_METHOD_ARGS[method]
    limit = STRING_METHOD_MAX_ARGS[method]
    optional = STRING_METHOD_OPTIONAL_ARGS.get(method, ())
    if not (limit - len(optional)) <= len(args) <= limit:
        extra = list(range(limit, len(args)))
        missing = list(range(len(args), limit))
        why = string_method_unlowered_arg_refusal(dotted, method, extra)
        if why is None and missing:
            why = (f"{dotted}() needs at least {limit - len(optional)} "
                   f"argument on this path — `{names[0]}` — and this call "
                   f"passes {len(args)}, so there is nothing to search for. "
                   f"CPython raises a TypeError here rather than answering")
        if why is not None:
            return (None, why)
    accept = None
    if method in ("startswith", "endswith") and args:
        foldable, value = affix_tuple_fold(dotted, method, recv, args[0])
        if foldable:
            return (STRING_PLAN_FOLD_INT, 1 if value else 0)
    if method == "count" and args and string_literal_text(args[0]) == "":
        return string_method_count_empty_needle(dotted, recv)
    for i, arg in enumerate(args):
        why = string_method_arg_refusal(dotted, method, names[i], arg,
                                        arg_kinds[i] if i < len(arg_kinds)
                                        else None)
        if why is not None:
            return (None, why)
    if method == "lstrip" and args:
        accept = string_method_lstrip_accept_set(dotted, args[0])
        if isinstance(accept, str) and accept != "" and "\0" in accept:
            return (None, f"{dotted}() is given a `chars` containing a NUL, "
                          f"and a NUL inside the accept set would end the set "
                          f"one character early — `strspn` reads its second "
                          f"argument as a C string")
    return (STRING_PLAN_EMIT, accept)


def affix_tuple_fold(dotted: str, method: str, recv, arg):
    """`(foldable, CPython's answer)` for a TUPLE affix.

    The second half of `string_method_arg_refusal`'s tuple case: this path
    cannot WALK a blob's elements at run time, but it does not have to. A tuple
    written in the source whose elements are all string literals is text the
    build can read, and CPython's rule for `startswith`/`endswith` over a tuple
    is "does ANY element match" — so the whole call is a compile-time
    computation and the emitters need no new instruction for it. `()` is the
    row that makes the rule worth stating: CPython answers False for it, and a
    vacuous "any" would answer True.

    `F.ListExpr` is deliberately NOT accepted, and the reason is CPython's
    rather than this path's: `str.startswith` accepts a tuple or a string and
    raises `TypeError` for a list, so `"ab".startswith(["a"])` has no answer
    to fold — the honest lowering of it is a refusal, and folding it would
    answer a question CPython declines to answer.

    Returning a bool rather than a lowered expression is deliberate. The
    alternative — materialising the answer as a sequence of `strncmp` calls —
    would mean unrolling an unbounded number of libc calls into an image, and
    the fold is the same computation with no code at all.
    """
    if not isinstance(arg, F.TupleExpr):
        return (False, None)
    elements = list(getattr(arg, "elements", []) or [])
    recv_text = string_literal_text(recv)
    texts = [string_literal_text(el) for el in elements]
    if recv_text is None or any(t is None for t in texts):
        return (False, None)
    probe = recv_text.startswith if method == "startswith" \
        else recv_text.endswith
    return (True, any(probe(t) for t in texts))




# The string methods that are a CONVERSION to a bare `char *` and are therefore
# the IDENTITY on this path.  Separate from `POINTER_BOUNDED_METHODS` because
# those COMPUTE something from the receiver's bytes and these compute nothing:
# a `String` here IS its own address (a literal is NUL-terminated, so its
# address is its length — `formal/arm64_codegen.py`'s empty-`String()` arm says
# so), and the type these return is a ONE-FIELD struct whose only field is that
# pointer, whose value on this path IS its field.  So `s.as_c_string_span()` is
# `s`, and saying otherwise would be inventing a conversion this value model
# does not have.
#
# `std/os/env.mojo` is the shape, and it is three call sites in one file whose
# every argument to `external_call` is spelled this way: measured on
# 2026-10-02, the file's terminal cause after the `OptionalPointer` return type
# was answered is
#
#     name.as_c_string_span() is a method call on a value, and this backend
#     lowers only append, close, write … and the string methods
#
# — a refusal that reads as "add it to the string table", which is what this
# table is, and whose real content is that the conversion is already a no-op.
#
# `as_c_string_slice` is the stdlib's PREVIOUS name for the same conversion
# (`bugs/FORMAL_env_family_next_terminal.md` records the old spelling's
# `unsafe_ptr()` blocker, and `test_formal_external_call.py` still transcribes
# it), so both are here: a rename is not a reason to refuse a construct whose
# lowering did not change.
#
# **`CStringSpan.ptr()` is deliberately NOT here**, and the reason is worth
# stating because it looks like the same case: on the real type it is the
# identity, but on THIS path a one-field struct's value and its field are the
# same word, so `s.as_c_string_span().ptr()` is a method on a method RESULT —
# which the emitters have no kind for, since the result of a call is not
# tracked in `ValueKinds`.  Lowering the inner conversion is what makes the
# outer one a bare name; the outer one is then a field read the frame analysis
# already owns.
STRING_IDENTITY_METHODS = ("as_c_string_span", "as_c_string_slice")


def string_identity_method(method: str):
    """`"str_identity"` when `recv.<method>()` is the receiver itself, else None."""
    return "str_identity" if method in STRING_IDENTITY_METHODS else None


def is_string_method(method: str) -> bool:
    """True when `method` is a method of `str` in this model — whether it is
    lowered (POINTER_BOUNDED_METHODS) or refused by name
    (LENGTH_DEPENDENT_METHODS).

    The distinction matters because a name in NEITHER table is a different
    failure: the source asked for a method this model has never heard of, and
    saying "that needs a length-prefixed string" about it would be a guess
    about what it does."""
    return method in POINTER_BOUNDED_METHODS or method in LENGTH_DEPENDENT_METHODS


def value_method_refusal(method: str, receiver_kind, dotted: str, *,
                         receiver_is_fd=None, receiver_shape=None) -> str | None:
    """Why `recv.method()` cannot be lowered here, or None when it can.

    Shared by both backends so the two architectures cannot disagree about
    which method calls are supported — the same rule the struct field-count
    refusal follows, and the reason this text lives in the model rather than
    being spelled twice.

    `receiver_kind` is what ValueKinds says the receiver holds, or None when
    the source does not say. It is REQUIRED for every string method.

    `receiver_is_fd` and `receiver_shape` are the two facts the KIND cannot
    carry, and both are per-backend because both are flow facts: whether the
    receiver is a file descriptor (tracked where it is bound, since `open(2)`
    is the only thing on this path that produces one), and where the receiver
    came from (a name, a frame slot, a literal, a call result). The DECISION
    of what each of those permits is here; only the facts are the backend's.

    The kind guard is the load-bearing part. Without it, `mlir_value.value()`
    — 359 of the calls in the stdlib — would be lowered as a string operation
    on whatever word the receiver happens to hold, and a struct's `.copy()`
    would be a `strstr` over a frame address. Both build. Both are wrong."""
    if method in POINTER_BOUNDED_METHODS and method not in LENGTH_DEPENDENT_METHODS:
        if string_operand_is_string(receiver_kind):
            return None
        if receiver_kind is None:
            return (f"{dotted}() is a method on a string, and the source does "
                    f"not say what its receiver holds — this path has no way "
                    f"to tell a char * from a word here, and lowering "
                    f"{method!r} anyway would treat an arbitrary 64-bit word "
                    f"as a pointer to bytes. Annotate the receiver (e.g. "
                    f"`s: String`) or bind it to a string literal")
        return (f"{dotted}() is a method on a string, and its receiver is "
                f"classified as {receiver_kind!r} rather than a string. "
                f"{method!r} is only lowered on a char *, and on anything else "
                f"the same bytes mean something different")
    if method in STRING_IDENTITY_METHODS:
        # The SAME kind guard as the pointer-bounded arm above, and for the same
        # reason: the conversion's answer is the receiver's ADDRESS, so on a
        # receiver this path cannot establish to be a char * the answer is an
        # address it made up. The two messages are deliberately not shared —
        # `STRING_IDENTITY_METHODS`'s own comment is the difference between them
        # (this one computes nothing) and a reader who is told "the source does
        # not say what its receiver holds" is being told the truth either way.
        if string_operand_is_string(receiver_kind):
            return None
        if receiver_kind is None:
            return (f"{dotted}() converts a string to a `char *`, and the "
                    f"source does not say what its receiver holds — this path "
                    f"has no way to tell a char * from a word here, and the "
                    f"conversion's answer IS the receiver's address, so "
                    f"lowering it anyway would hand a C callee an address "
                    f"assembled from whatever word the receiver happens to "
                    f"hold. Annotate the receiver (e.g. `s: String`) or bind "
                    f"it to a string literal")
        return (f"{dotted}() converts a string to a `char *`, and its receiver "
                f"is classified as {receiver_kind!r} rather than a string. On "
                f"this path a `String` is its own address, so the conversion is "
                f"the identity — and on anything else the same word is not an "
                f"address at all")
    if method in LENGTH_DEPENDENT_METHODS:
        return (f"{dotted}() is a real method of String, but it "
                f"{LENGTH_DEPENDENT_METHODS[method]}. "
                f"{string_method_remedy(method)}")
    return _shape_guarded_refusal(method, receiver_kind, dotted,
                                  receiver_is_fd, receiver_shape)


# The names whose missing half is a CODE POINT rather than a LENGTH, and so
# whose remedy sentence is a different one. A separate table rather than a
# marker inside `LENGTH_DEPENDENT_METHODS` because that table's values are
# quoted on their own elsewhere — `arm64_codegen._emit_str_lstrip`'s docstring
# cites the `strip` entry directly, and `test_formal_unicode.py` reads the
# reasons as text — so its shape is not this function's to change. And the two
# facts being kept apart are genuinely different: a length is something a
# `{ptr, len}` descriptor would carry, and a code point is not a property of
# the representation at all. `"é".upper()` is refused for want of a BUFFER
# and `"é".isalpha()` for want of a CHARACTER, and telling a reader the second
# wants the first is worse than telling them nothing, because it points them at
# a change that would not answer them.
CODEPOINT_REMEDY_METHODS = frozenset({
    "isalnum", "isalpha", "isascii", "isdecimal", "isdigit", "isidentifier",
    "islower", "isnumeric", "isprintable", "isspace", "istitle", "isupper",
    "encode", "decode", "translate", "maketrans",
})

# The sentence `value_method_refusal` ends a refusal with: what a reader would
# have to change. Written once because it is the same sentence for every
# length-dependent name, and split by the one fact that differs.
LENGTH_REMEDY = ("Answering it would need a string representation that "
                 "carries a length — a value-model change, shared by both "
                 "backends and the Lean proof, not a lowering of this one call")
CODEPOINT_REMEDY = ("Answering it would need a representation that carries "
                    "CHARACTERS rather than bytes, which is a different and "
                    "larger change than a length: a length says how many bytes "
                    "there are, and this question is about what each one of them "
                    "STANDS FOR")


def string_method_remedy(method: str) -> str:
    """The closing sentence of a string method's refusal, by what it is missing.

    Two sentences for one table, chosen by `CODEPOINT_REMEDY_METHODS`, and the
    choice is a fact about the METHOD rather than about the message: a reader
    who wants `isalpha` is not blocked by the same thing as a reader who wants
    `zfill`, and pointing both of them at the same change is how a refusal ends
    up describing a fix that would not answer the question.
    """
    return (CODEPOINT_REMEDY if method in CODEPOINT_REMEDY_METHODS
            else LENGTH_REMEDY)




# ── What a value-shaped method means, PER RECEIVER KIND ───────────────────
#
# Everything above this line is about STRING methods, and that framing is a
# trap for everything below it. The last fallback used to say "this backend
# lowers only append, close, write and the string methods …" for EVERY
# unrecognised method name, and for a receiver that is not a string that text
# is worse than useless: it reads as "add the method to the string table",
# which is exactly the mis-implementation to avoid. `ptr.value()` is 53 of the
# 76 files in the wave-4 sweep's largest finding group, and nothing about it is
# a string.
#
# A value on this path is ONE 64-bit word, so a method's meaning is a function
# of what that word holds, and the receiver's PROVENANCE says as much as its
# kind does. The five receiver shapes, and what each can honestly answer:
#
#   CHAR_P (kind `str`)  the bytes from the receiver to its NUL. The five
#       POINTER_BOUNDED_METHODS are a function of those bytes and are lowered.
#       Anything that needs to WRITE the bytes, or to know the length before
#       it can decide where the result ends, is out — see
#       LENGTH_DEPENDENT_METHODS, and the measured reason there is that a
#       literal is interned into __TEXT,__text with initprot 0x5 (read+exec).
#
#   LIST_BLOB (kind `list:K`)  a frame-allocated [count][elem…] blob, capacity
#       a compile-time bound (literal length + the count of `append` sites),
#       bounds-checked so overflow exits(1) loudly. `append` is lowered and is
#       the ONLY honest one: every other list method either writes the count
#       downwards (`pop`), needs a length to decide anything (`__contains__`),
#       or returns a new blob whose size nothing knows at compile time.
#
#   FRAME_ADDRESS  a multi-field struct, which on this path is the ADDRESS of
#       an out-of-line frame of 8-byte slots. A method on it is a method of a
#       type this model does not know, and D2 owns the field derivation. The
#       dominant stdlib case is a `Some[Writer]`, and the trap is specific and
#       worth writing down: `writer.write_string(s)` looks like the `write`
#       that IS lowered, and aliasing it would pass a FRAME ADDRESS as a file
#       descriptor. The C library answers EBADF, the program continues, and
#       the output is missing rather than wrong-looking.
#
#   PLAIN_WORD  an int, or a bool, or a float-truncated-to-int. The only
#       honest method is one that is the IDENTITY on a word, and that needs a
#       kind that says "this word is a bool" — which the kind model does not
#       have, because an unannotated word is an int (see the note on kinds)
#       and cannot be told apart from one.
#
#   DEREFERENCE_TARGET  a word that is an ADDRESS. `value()` is not an
#       identity here, it is a LOAD, and a load is not one instruction on this
#       path: see DEREFERENCE_METHODS for the three things a load needs and
#       this model has none of.
#
# The last two rows are why DEREFERENCE_METHODS and UNWRAP_METHODS below are
# separate tables. `Pointer.value()` and `Optional.unsafe_value()` are spelled
# alike and mean opposite things — one follows an address, the other asks which
# of two words was the empty one — and a model that grouped them by spelling
# would implement one of them as the other.

# The receiver kind each already-lowered value method REQUIRES, and the words
# to use when the receiver is something else. `append` is deliberately absent:
# its guard is in the backend, where `_scan_list_caps` has the function in hand
# and can compute the capacity, and a name the scan drops refuses there with a
# message about capacity rather than about kind. This table is the other half
# — `write` and `close`, which had NO guard at all.
#
# Measured, not assumed. `write` lowers to the C library's
# `write(fd, s, strlen(s))` and `close` to its `close(fd)`, and the
# docstrings said "the receiver of a file method IS a descriptor" because
# `open(...)` already lowers to the C library's `open(2)`. That is an
# assumption ABOUT THE SOURCE, and nothing checked it. On the pre-change tree
# all four of these BUILT on both architectures and each one passed something
# that is not a descriptor as fd:
#
#     s = "hello"; s.write("x")   # fd = a __TEXT,__text address
#     k = 7;      k.write("x")    # fd = 7
#     p = P();    p.write("x")    # fd = a frame address   (P is a struct)
#     xs = [1,2]; xs.write("x")   # fd = a frame address   (xs is a blob)
#
# None of them faults. `write(2)` on a bad descriptor returns -1, which
# nothing here checks, so the program runs, prints nothing, and exits 0. A
# silently-wrong lowering is the outcome this table exists to stop.
VALUE_METHOD_RECEIVERS = {
    "write": ("a file descriptor", "open(...) on this path, which lowers to "
                                  "the C library's open(2)"),
    "close": ("a file descriptor", "open(...) on this path, which lowers to "
                                   "the C library's open(2)"),
}



# ── the POINTER VALUE MODEL ─────────────────────────────────────────────────
#
# THE DECISION (wave 6, F2; the reasoning is in
# the pointer value model (landed in f69079be0), which is the long form of this comment).
#
# A formal value is one 64-bit word.  A pointer is one word.  So what does a
# pointer need beyond that?
#
# **Nothing is stored.**  A pointer's pointee is a COMPUTATION over its
# DECLARED STATIC TYPE, recovered under the same agree-or-refuse rule
# `frame_field_type_candidates` and `struct_field_declared_type` already
# implement for a struct field: use a declared type only when EVERY binding of
# the name agrees, and an absent answer IS the answer.  So there is no second
# word, no tag, no header, and — the thing that killed the `{ptr, len}`
# descriptor in the string decision — no lifetime: nothing is stored, so
# nothing can point into a callee's scratch.
#
# And where the pointee is recovered, it is often not a load at all.  The
# pointee's own representation on this path decides the shape of the answer,
# and a struct's representation is a frame ADDRESS:
#
#   * a SCALAR pointee (`UInt8`, `Int32`, `Int64`, `Byte`, `c_char`, …) is a
#     LOAD, and its WIDTH is the pointee's — one byte for `UInt8`, which is
#     precisely the over-read D1 refused over, and precisely the load that does
#     not fault.  See POINTEES for the widths and the names that are refused.
#   * a STRUCT pointee of this module is the IDENTITY: the address already IS
#     the struct's value on this path, exactly as `Pointer()` is (D4's
#     measurement), and `.field` off the result reads the frame slot.  This is
#     the same shape as the string decision's "the length is a computation" —
#     the representation supplies the answer and no instruction is spent.
#   * a FLOAT pointee is refused.  A formal value has no float kind distinct
#     from an int (the same absence as `__mlir_bool__`), so a 4-byte float load
#     would put float bits in a register the program then treats as an integer.
#     That is a wrong answer, not an approximation.
#   * a BLOB pointee (a list's frame, whose first word is its count) is refused:
#     a `List` is not named by a pointee type anywhere, and reading its first
#     word as a pointee value would answer with the length.
#   * a `SIMD[dtype, n]` pointee with n > 1 is refused: it is n words and a
#     formal value is one.
#   * a NULL pointer is not a separate case in the load: it is a fault, and the
#     program that dereferences one has a null check or has a bug.  See
#     `dereference_lowering`'s `null` refusal, which is a DIAGNOSTIC and not a
#     load — reading address 0 would fault on both architectures and a
#     fabricated 0 would be worse.
#
# WHY THIS IS NARROWER THAN THE STRING DECISION, and it is the honest half of
# the answer:  `strlen` recovers a string's length from a RUNTIME invariant
# (every string on this path is NUL-terminated), so it works for every string
# value however the program produced it.  A pointer has NO such invariant —
# the four things a word can point at on this path (interned `__TEXT,__text`
# bytes with a NUL, a blob whose first word is a count, a frame of 8-byte
# slots, and an extern C object about which this path knows nothing) have four
# incompatible layouts and no common header.  So the pointee is a STATIC fact
# about ONE spelling, and the answer exists exactly where a declaration in the
# same function names it.  Everywhere else the refusal is D2's own rule
# applied to a pointer, and it is the correct answer there.
#
# THE COST, stated rather than hidden:  coverage, not speed and not storage.
# A pointer that arrives as a callee argument, out of a frame field, or out of
# a container has no recorded pointee, so `p.value()` on it stays refused — and
# 14 of the 47 `unsafe_value` sites in the corpus are exactly that.  What is
# bought is that a load is never emitted at a width the model has not
# established, which is the one outcome this whole project calls the worst
# thing available.

# The type constructors whose name says "a pointer".  A pointer's type argument
# carries the pointee FIRST and the origin (and, in the older spellings, a
# `mut=` attribute) after it, so the pointee is the first argument that is not
# an attribute.  Measured over the corpus: `Pointer[MutUntrackedOrigin]` (775),
# `Pointer[c_char, StaticConstantOrigin]` (250), `Pointer[Int8]` (67),
# `Pointer[Int64]` (31), `Pointer[Byte]` (26) and 60 more spellings, plus
# `UnsafePointer[…]` and `_CPointer[…]`.
#
# `_CPointer` is a `comptime` ALIAS for `Optional[UnsafePointer[T, origin]]`
# (`std/ffi/__init__.mojo:1009`), not a struct, so the pointee is still the
# first type argument and no alias resolution is needed to read it — which is
# worth saying because wave 4's D4 found the binding half of this problem
# (`_PhiloxWrapper._rng: PhiloxRandom[10]` behind an import alias) and it does
# NOT apply to the one construct the sweep reaches.
#
# The ALIAS FAMILY is here for the same reason and is not a new fact: every name
# below is `= Pointer[…]` or `= Optional[Pointer[…]]` in the language's own
# `std/memory/pointer.mojo` (measured 2026-10-02 at lines 130-211), so each one
# is a pointer by definition and the table's question — "does this name say a
# pointer" — has the same answer for all of them.  They are here for the reason
# `_CPointer` is: a declared return type is a type EXPRESSION, and the alias is
# a module-level `comptime` binding this path does not resolve, so the NAME is
# the whole of the evidence there is.  The `//` in each declaration separates
# the keyword-only `mut` from the positional `T`, and `OptionalPointer`'s own
# signature ELIDES the `mut: Bool, //` parameter — so the pointee is still the
# first positional type argument, which is what the four call sites in the tree
# agree on (`std/os/env.mojo:78` `OptionalPointer[UInt8, ImmUntrackedOrigin]`
# for `char *`, `std/pwd/_linux.mojo:48` `OptionalPointer[_C_Passwd,
# UntrackedOrigin[mut=True]]` for `struct passwd *`, and
# `std/memory/memory.mojo:477`/`:483` with `mut=True` spelled as a keyword).
#
# Leaving them out is what made `std/os/env.mojo` REFUSE
# `external_call["getenv", OptionalPointer[UInt8, ImmUntrackedOrigin]]` with
# "this path has no value of that kind to put in the return register": a
# one-word nullable address, refused because the table had never heard of the
# name, and `external_call_return_kind`'s own docstring says a pointer "is an
# address, so `word`, and it needs no pointee" while the table it consults said
# the name was not one.  It is an `Optional[Pointer]`, which is one word with 0
# meaning None — the same answer `_CPointer` already gives for the same C
# function.  A name this path cannot read is the safe direction, so the absence
# was not a wrong answer, but it was a refusal of a construct the table's own
# rule already answers, on a file the sweep reaches (`env.mojo`, and every
# `getpwuid`/`PyObject_Malloc` in `pwd/` and `python/bindings.mojo` that spells
# its return type the same way).
#
# The three `*OpaquePointer` aliases are the exception to "the pointee is the
# first positional argument", and the exception is SAFE rather than tidy: they
# expand to `Pointer[NoneType, origin]`, so their first positional argument is
# the ORIGIN, and a name that is not a pointee is not in `POINTEE_WIDTHS` — so
# `opaque.value()` is refused by the width table rather than loaded at a width
# nothing established.  They are here for `external_call_return_kind`, where the
# question is only "is the whole register the answer", and an opaque pointer is.
#
# The spellings that MEAN a pointer here — `Pointer`, the `Mut`/`Imm` variants,
# and the two NULLABLE-POINTER aliases `std/memory/pointer.mojo` declares:
#
#     comptime OptionalPointer[mut, T, origin, address_space=…]
#         = Optional[Pointer[T, origin, …]]
#     comptime OpaquePointer[mut, origin, address_space=…]
#         = Optional[Pointer[None, origin, …]]      (and the pointee-less form)
#
# A name is in this table for ONE reason: its word IS the register it is passed
# in or returned in. That is the C ABI question (`external_call_return_kind`), and
# for a nullable pointer it is settled by the ABI itself — `char *getenv(...)`
# returns one word, and by C a null pointer IS the absent answer, because there
# is no second register and no tag for a caller to tell from. It is ALSO the
# pointer value model's question, and the two answers are not the same: at a C
# boundary a nullable pointer is one word, while as a value a MOJO function
# built it is an `Optional` whose tag lives a second frame away, so `if not
# ptr:` is not answerable from the word and `Some(null)` is not `None`
# (`bugs/FORMAL_stdlib_optional_needs_a_representation.md`).
#
# **So the other half of a nullable pointer is its own table, named for the
# question it answers**, and this is the note that says so at the point where a
# future reader adds one: `NULLABLE_POINTER_UNWRAP_ALIASES` below is what makes
# `value()` the UNWRAP rather than a LOAD, and adding a name to THIS table does
# not make its `value()` an unwrap. One name per question, and the name says
# which question it answers — which is what `bugs/FORMAL_nullable_pointer_
# aliases_is_defined_twice.md` is about, and what
# `test_formal_external_call.py`'s `no_module_level_name_is_bound_twice` keeps
# true from then on.
POINTER_TYPE_CTORS = ("Pointer", "UnsafePointer", "_CPointer", "CPointer",
                      "DTypePointer", "Reference",
                      "OptionalPointer", "MutPointer", "ImmPointer",
                      "OpaquePointer", "MutOpaquePointer", "ImmOpaquePointer")

# A pointee base name -> `(width in bytes, signed)`.  One table, read by both
# backends through `dereference_lowering`, so the two architectures cannot
# disagree about how wide a load is — which is the failure mode of every other
# per-backend constant in this file.
#
# A name that is NOT here is refused, and the absence is the safe direction: an
# unknown pointee has no established width, and a load whose width is not
# established is the one instruction this model must never emit (an 8-byte load
# of a `UInt8` returns a plausible number assembled from seven bytes of
# whatever follows, and faults outright at a page edge).
POINTEE_WIDTHS = {
    "Int8": (1, True), "UInt8": (1, False), "Byte": (1, False),
    "c_char": (1, True), "Bool": (1, False),
    "Int16": (2, True), "UInt16": (2, False),
    "c_short": (2, True), "c_ushort": (2, False),
    "Int32": (4, True), "UInt32": (4, False), "c_int": (4, True),
    "c_uint": (4, False), "SIMDSize": (4, False), "Int": (4, True),
    "UInt": (4, False),
    "Int64": (8, True), "UInt64": (8, False), "c_long": (8, True),
    "c_ulong": (8, False), "NoneType": (8, False),
    # IEEE binary64 is EIGHT BYTES and the load is bit-exact — one `LDR` of the
    # bit pattern, the same instruction an `Int64` pointee uses — so the width
    # was never the question. It is in this table rather than in
    # `POINTEES_REFUSED` because the refusal that was there was about the
    # CONTEXT (nothing carried the pointee's KIND out of the dereference, so
    # `Int(p.value())` read the exponent field) and that hole is closed:
    # `pointee_kind` below is the channel, `ValueKinds.kind_of`'s dereference
    # arm is where it is asked, and the two consumers a `Float64` could reach —
    # a call argument and a `return` under an integer annotation — are refused
    # by name. The signedness is `True` and is not consulted for an eight-byte
    # load (nothing narrows it); it is written down rather than left as a
    # default so a reader does not have to infer it.
    "Float64": (8, True),
    # A pointer-to-pointer is a load of an ADDRESS, so the pointee here is
    # another pointer and the width is the pointer's own.  This is the one
    # recursive entry, and it terminates because a pointer to a pointer to a
    # pointer still loads 8 bytes — the pointee's TYPE never changes the width
    # once it is a pointer, only whether the value is itself dereferenceable.
    "Pointer": (8, False), "UnsafePointer": (8, False), "_CPointer": (8, False),
}


def pointee_kind(pointee) -> str | None:
    """The KIND a load of this pointee produces, or None when it is not stated.

    **The channel `POINTEES_REFUSED`'s `Float64` row was standing in front of.**
    That row said the load "yields a word whose KIND is decided by the context
    it lands in", which was true of the tree it was written on and stopped being
    true the moment a KIND could flow: a `Pointer[Float64]` load is one word
    holding the bit pattern, and the question is no longer what the word IS but
    what each consumer is told it is. This function is the answer to the first
    question, and `ValueKinds.kind_of`'s dereference arm is where it is asked,
    so every consumer of a kind — the `printf` conversion check, the
    call-argument check, the return-annotation check, `Int(…)`'s own
    `FLOAT_TO_INT` arm — inherits it rather than each emitter re-deriving it.

    **One row, and `None` is the answer for everything else, which is the
    permissive direction and not an omission.** Every other pointee in
    `POINTEE_WIDTHS` is a one-word INTEGER, and `INT_KIND` is what this model
    already answers for a word, so a row saying `int` would change nothing; the
    other pointees in `POINTEES_REFUSED` (a `Float32`, a wide `SIMD`, a blob, a
    struct) have no kind on this path at all and never reach a load. Writing the
    integer rows out would be a second table to keep in step with
    `POINTEE_WIDTHS` for a claim that changes no answer.

    `Float64` and NOT `Float32` is not a preference: a `Float32` is four bytes
    of IEEE binary32 and this path has no kind that holds one, so its load is
    still refused by `POINTEES_REFUSED` and this function is never asked about
    it. A `BFloat16` is the same answer for the same reason.
    """
    if pointee == "Float64":
        return FLOAT_KIND
    return None

# The reverse of `POINTEE_WIDTHS` for the four widths it establishes: the pointee
# that IS that width, so a refusal can NAME the declaration which would answer it
# instead of interpolating the number into a type name.  That interpolation is
# how `_offset_scale`'s advice came to read `Pointer[Int8]` for an EIGHT-byte
# load (`Int8` is one byte — `POINTEE_WIDTHS` says so two hundred lines above)
# and `Pointer[Int2]` for a two-byte one, where no `Int2` exists in any table
# here: advice that declares a DIFFERENT width than the refusal is about.  The
# signed spelling is the one used, because the widths it is asked about are the
# signed loads (`Int16`/`Int32`/`Int64`); the width is what has to match, not
# the signedness, and every row's unsigned twin is in `POINTEE_WIDTHS` beside it.
WIDTH_POINTEES = {1: "Int8", 2: "Int16", 4: "Int32", 8: "Int64"}

# The pointee widths whose value is a FLOAT this path can hold, and the reason
# it is a separate name rather than a second entry in `POINTEE_WIDTHS`: a width
# is not a kind, and every reader of a dereference needs to tell a `Float64`
# load from an eight-byte integer load.  `pointer_dereference_kind` is the one
# reader that does, and `ValueKinds.kind_of` inherits it through the
# `pointee_kind` hook so both backends answer from here rather than each
# re-deriving "which pointees are doubles".
FLOAT_POINTEE_WIDTHS = {"Float64": 8}

# Pointee base names that are refused BY NAME, with the reason, rather than
# merely absent from POINTEE_WIDTHS.  A refusal that says "the pointee is not a
# width I know" is true but unhelpful when the answer is a specific fact, and
# these are the two that are specific facts: a narrow float and a SIMD.
POINTEES_REFUSED = {
    "Float16": "a Float16 is two bytes of IEEE binary16 and this path has no "
               "float kind to hold them",
    "Float32": "a Float32 is four bytes of IEEE binary32 and this path has no "
               "float kind distinct from an int, so the load would put float "
               "bits in a register the program then treats as an integer — a "
               "wrong answer, not an approximation",
    # **`Float64` USED TO BE HERE, and it is now LOADED** rather than refused:
    # the width of the load is `dereference_lowering`'s `("float", 8, False)`
    # answer, and the KIND its loaded word carries is `pointer_deref_kind`'s,
    # so a `Pointer[Float64].value()` is a double in every consumer that asks
    # what it holds (`Int(...)` becomes `FCVTZS`, `%f` places it as a double,
    # `%d` and an `Int` parameter are refused by the rules
    # `call_argument_kind_refusal` and `return_annotation_kind_refusal` state).
    # The row that stood here said the load was bit-exact and the KIND was the
    # missing piece; that piece is `pointer_deref_kind`, and keeping the row
    # would refuse a load this path can now place correctly.
    "SIMD": "a SIMD is n words and a formal value is one, so the load would "
            "have to drop n-1 of them; SIMD[dtype, 1] reduces to its scalar "
            "and is the only arity answerable here",
    "List": "a list is a BLOB on this path — a frame whose FIRST word is its "
            "count — so a load at the address would answer with the length, "
            "and there is no declared pointee anywhere in the corpus that "
            "names a list this way",
    "Dict": "a dict is a blob of (key, value) pairs, so a load at the address "
            "would answer with the first key's hash slot rather than with a "
            "pointee",
    "String": "a String local on this path is a bare char * whose bytes are "
              "interned in __TEXT,__text, and reading the STRUCT's fields "
              "would read a __TEXT,__text address as three integers",
    "StringSlice": "a StringSlice is a two-word {ptr, len} pair, so there is no "
                   "single load at its address that is the pointee",
}

# Pointee base names that are a FLOAT the dereference CAN carry, and the table
# that lets the load through.  A `Pointer[Float64]` load is bit-exact — one
# `LDR` of eight bytes holding the bit pattern, the same instruction an integer
# pointee uses — so the load was never the problem; what was missing was the
# WORD'S KIND.  `FLOAT_KIND` landed with the binary64 arithmetic, and
# `pointer_deref_kind` carries the pointee's kind into every context that reads
# the dereference, so `Int(p.value())` is the `FCVTZS` the source means rather
# than a read of the exponent field.  A name here is therefore a LOAD this path
# answers and a STORE it still refuses (`pointer_store_lowering`), because a
# store needs the RHS's kind and this path checks none there.
POINTEE_FLOAT_NAMES = frozenset(FLOAT_TYPE_NAMES)


def pointee_args(text: str) -> list:
    """The type ARGUMENTS of a declared type, as strings, or `[]`.

    `Pointer[UInt8, UntrackedOrigin[mut=False]]` →
    `['UInt8', 'UntrackedOrigin[mut=False]']`; `Pointer[mut=True, Int32]` →
    `['Int32']`, because `mut=True` is a KEYWORD ARGUMENT and not a type.
    Splitting on top-level commas and tracking bracket depth is the whole
    implementation, and a declared type is exactly the grammar that needs it:
    a generic's argument list is a comma-separated list of possibly-bracketed
    types, and nothing else.
    """
    text = (text or "").strip()
    open_at = text.find("[")
    if open_at < 0 or not text.endswith("]"):
        return []
    inner = text[open_at + 1:-1]
    out, depth, cur = [], 0, []
    for ch in inner:
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        out.append(tail)
    # A keyword argument (`mut=True`, `origin=…`) declares a parameter of the
    # type constructor, never a pointee, so it is dropped — and dropping it is
    # what makes `Pointer[mut=True, Scalar[dtype]]` and `Pointer[Scalar[dtype]]`
    # agree, which are the same type.
    return [a for a in out if "=" not in a.split("[")[0]]


def pointee_of_type_text(text: str):
    """`(pointee_base, why)` for a declared POINTER type, or `(None, why)`.

    The one reading of "what does this pointer point at", for both spellings a
    declaration arrives in — a `VarDecl.type_ann` / `FunctionDef.params`
    annotation, which the parser has already reduced to a string, and an
    `external_call["sym", T]` type argument, which is still an AST node (see
    `type_expr_text`, which renders the second into the first's shape so there
    is only one reader).

    `None` is the answer in every case, and each `why` says which:

      * the text does not name a pointer type constructor at all — so the
        receiver is not a pointer, and the caller must not treat it as one;
      * the type constructor has no type argument — `Pointer` with nothing in
        the brackets is a type this path cannot read, not a `void *` to guess
        at;
      * the first type argument does not reduce to a single identifier
        (`Scalar[dtype]`, `Self.T`, `T`, `_`, `Self.self_type`) — a TYPE
        PARAMETER, whose value is not knowable here, so the width is not
        established.  This is the untyped direction, and it is the direction
        D2's rule calls the answer rather than a failure.
    """
    base = annotation_base_name(text)
    if base is None:
        return (None, f"the declared type {text!r} does not reduce to a single "
                      f"type name, so it names no pointer and no pointee")
    if base not in POINTER_TYPE_CTORS:
        return (None, f"the declared type {text!r} names {base}, which is not a "
                      f"pointer type on this path — a pointer's pointee is a "
                      f"question about a pointer, and this is not one")
    args = pointee_args(text)
    if not args:
        return (None, f"{base} carries no type argument, so the pointee is not "
                      f"stated here; `Pointer` with nothing in the brackets is a "
                      f"type this path cannot read rather than a `void *` it "
                      f"could assume")
    inner = annotation_base_name(args[0])
    if inner is None:
        return (None, f"the pointee is {args[0]!r}, which is a type PARAMETER or "
                      f"a computed type rather than a type name — its value is "
                      f"not knowable here, so no load width is established")
    return (inner, args[0])


def type_expr_text(node):
    """Render a type EXPRESSION back to the string a declaration would spell.

    Needed because the parser reduces `var p: Pointer[UInt8]` to the string
    `"Pointer[UInt8]"` but leaves `external_call["getenv", _CPointer[UInt8,
    UntrackedOrigin[mut=False]]]`'s second template argument as a tree — and
    `std/os/env.mojo:80-85`, the one construct that reaches 54 stdlib files,
    writes the pointee exactly there.  Two readers for "what is this pointer's
    pointee" would be two answers, so the AST shape is rendered into the
    string shape and `pointee_of_type_text` is the only reader.

    `None` for anything outside the type-expression grammar (an
    `IntLiteral` index is a comptime VALUE, not a type; a call is not a type).
    The shapes handled are the ones the corpus writes: `UInt8`, `Self.T`,
    `Scalar[dtype]`, `_CPointer[UInt8, UntrackedOrigin[mut=False]]`,
    `SIMD[DType.int, 4]`.
    """
    if isinstance(node, F.IdentExpr):
        return node.name
    if isinstance(node, F.StringLiteral):
        # A declared type spelled as a STRING rather than as a type expression.
        # `external_call["getenv", "Pointer[UInt8]"]` is the same declaration as
        # the unquoted spelling, and the corpus uses both; refusing the quoted
        # one would make the answer depend on a spelling rather than on a type.
        return node.value
    if isinstance(node, F.MemberExpr):
        obj = type_expr_text(node.obj)
        return None if obj is None else f"{obj}.{node.member}"
    if isinstance(node, F.SubscriptExpr):
        obj = type_expr_text(node.obj)
        if obj is None:
            return None
        if node.attrs:
            # `UntrackedOrigin[mut=False]` — the ATTRIBUTES are the keyword
            # arguments and come after the type arguments, and `pointee_args`
            # drops keyword arguments, so spelling them is enough to be dropped
            # correctly rather than misread as a pointee.
            parts = []
            for key, val in node.attrs:
                v = getattr(val, "value", None)
                parts.append(f"{key}={v}" if isinstance(v, bool) else f"{key}=?")
            inner = ", ".join([str(i) for i in
                               _flatten_type_index(node.index)] + parts)
        else:
            inner = ", ".join(str(i) for i in _flatten_type_index(node.index))
        return f"{obj}[{inner}]"
    return None


def _flatten_type_index(index):
    """`[UInt8]` or `(UInt8, UntrackedOrigin[…])` -> `['UInt8', …]`."""
    if isinstance(index, F.TupleExpr):
        return [type_expr_text(e) or "?" for e in index.elements]
    one = type_expr_text(index)
    return [one] if one is not None else []


def _name_bindings(fn, name):
    """`[(ann_or_None, rhs)]` — every binding of `name` in `fn`, in source order.

    Source order and not last-write-wins because the rule is AGREE-OR-REFUSE:
    two bindings that name two pointees are a disagreement, and picking the
    later one is the silently-wrong answer.  A name bound once and never
    rebound is the case the corpus is made of; a name bound in a loop to the
    same type twice is still one answer.
    """
    out = []
    for node in iter_nodes(getattr(fn, "body", None)):
        if isinstance(node, F.VarDecl) and node.name == name:
            out.append((node.type_ann, node.value))
        elif isinstance(node, F.AssignStmt) and isinstance(node.target, F.IdentExpr) \
                and node.target.name == name:
            out.append((None, node.value))
    return out


def _rhs_pointee(fn, rhs, decls, functions, seen=()):
    """`(pointee_base, why)` for the value on the right of a binding, or `(None, why)`.

    The four places the corpus actually states a pointee, each measured:

      * `external_call["sym", T](…)` — the SECOND template argument is the
        declared return type.  This is `std/os/env.mojo:80-82`, the one
        construct the 54-file group reaches, and it states `_CPointer[UInt8,
        UntrackedOrigin[mut=False]]` four lines above the `ptr.value()` that
        used to be refused for having no recorded pointee.
      * `Pointer[T](…)` / `UnsafePointer[T, …](…)` — the construction.
      * `p.bitcast[T]()` / `rebind[T](…)` — the pointee CHANGES, and the
        declaration at the new spelling is the recorded one.
      * a call to a function of this image whose own RETURN ANNOTATION is a
        pointer — the callee's declaration, which is a real interprocedural
        answer and not an inference.  It is read only from the image's own
        function table, so a call to something this image does not contain
        refuses rather than guessing.

    `None` in every other case, and each `why` says which.  A name bound from
    a string literal, from an integer, or from a container is not a pointer
    this path can dereference, and the message says so rather than calling it
    an undeclared pointer.
    """
    if rhs is None:
        return (None, "the binding has no initialiser to read a pointee from")
    if isinstance(rhs, F.StringLiteral):
        return (None, "the receiver is a string literal, which on this path is "
                      "a bare char * into __TEXT,__text — a string's bytes are "
                      "addressed by a computation (strlen and the "
                      "pointer-bounded methods), not by a declared pointee")
    if isinstance(rhs, F.IdentExpr):
        if rhs.name in seen:
            return (None, f"the pointer is an alias cycle through {rhs.name!r}, "
                          f"so no binding in it declares a pointee")
        return _name_pointee(fn, rhs.name, decls, functions, seen + (rhs.name,))
    if isinstance(rhs, F.BinaryOp) and rhs.op in ("+", "-"):
        # `p + k` — the pointee is the pointee of the pointer side, unchanged.
        # The OFFSET is a different question and it is `_offset_scale`'s: C
        # scales a pointer offset by the pointee's size, and this path's ALU
        # does not (measured: `q = p + 3` on a string gives `base + 3`, which is
        # right for a 1-byte pointee and wrong for every other one).  So the
        # pointee is carried here and the scale is checked at the dereference,
        # where the width is finally known — reading the same width from two
        # places would be two widths.
        return _rhs_pointee(fn, rhs.left, decls, functions, seen)
    if isinstance(rhs, F.CallExpr):
        func = rhs.func
        # `q = p.value()` — a POINTER-TO-POINTER.  The result of a dereference
        # of a `Pointer[Pointer[T]]` is itself a pointer, and it is the only
        # way a pointer's value is a pointer.  So the new pointee is the TYPE the
        # receiver's own pointee was, read off the receiver's declared type
        # rather than off its pointee's BASE name — `Pointer[Pointer[UInt8]]`'s
        # base pointee is `Pointer`, which says nothing about `UInt8`, and
        # reading the base is how a two-level dereference would come back as
        # "the pointee is Pointer", which is the same word twice.
        if isinstance(func, F.MemberExpr) and func.member in DEREFERENCE_TRY_NAMES:
            text = _rhs_declared_text(fn, func.obj, decls, functions)
            args = pointee_args(text) if text else []
            if text and annotation_base_name(text) in POINTER_TYPE_CTORS and args:
                # `args[0]` is the RECEIVER's pointee TYPE, so for
                # `Pointer[Pointer[UInt8]]` it is `Pointer[UInt8]` and THAT is
                # what q is a pointer to: read one level in, which is why this
                # recurses into `pointee_of_type_text` rather than taking
                # `args[0]`'s base name.  A receiver whose pointee is not a
                # pointer type makes q a SCALAR, which the next refusal says.
                if annotation_base_name(args[0]) in POINTER_TYPE_CTORS:
                    return pointee_of_type_text(args[0])
                return (None, f"q = p.{func.member}() makes q the value at p, "
                              f"which here is a {args[0]} — a scalar, not a "
                              f"pointer, so q.value() is not a dereference")
            return (None, f"q = p.{func.member}() makes q the VALUE at p, and "
                          f"that value is a pointer only when p points at one — "
                          f"which this path cannot read from the receiver's "
                          f"declared type here")
        # external_call["sym", RetType](…) — the declared return type.
        if isinstance(func, F.SubscriptExpr) and isinstance(func.obj, F.IdentExpr) \
                and func.obj.name == "external_call":
            idx = func.index
            items = idx.elements if isinstance(idx, F.TupleExpr) else [idx]
            if len(items) >= 2:
                text = type_expr_text(items[1])
                if text is not None:
                    return pointee_of_type_text(text)
                return (None, "the external_call's declared return type is not "
                              "a type this path can read, so it establishes no "
                              "pointee")
            return (None, "external_call is called with no declared return type, "
                          "so it establishes no pointee")
        # p.bitcast[T]() / rebind[T](…) — the pointee CHANGES and the new
        # spelling is the declaration.  The parser hangs the template argument
        # off the FUNC, so the shape is `CallExpr(SubscriptExpr(MemberExpr(
        # p, "bitcast"), T))` and the base name check below would otherwise
        # read it as a pointer construction of a method.
        if isinstance(func, F.SubscriptExpr) and isinstance(func.obj, F.MemberExpr) \
                and func.obj.member in ("bitcast", "rebind"):
            text = type_expr_text(func.index)
            if text is not None:
                # The type argument of a pointer-level cast is the new POINTEE
                # (`p.bitcast[Int8]()`), and the only exception is the one
                # reading where it is a new POINTER type instead
                # (`rebind[Self._mlir_type](…)`, `unsafe_pointer.mojo:631`).
                # Both are answered the same way and neither is a guess: if it
                # names a pointer type it IS one, and if it does not it is the
                # pointee the cast produced.  A third reading — "unknown, so
                # refuse" — would make `bitcast[Int8]()` unanswerable while
                # `Pointer[Int8]` was answerable, which is a difference in
                # spelling rather than in type.
                if annotation_base_name(text) in POINTER_TYPE_CTORS:
                    return pointee_of_type_text(text)
                inner = annotation_base_name(text)
                if inner is not None:
                    return (inner, text)
                return (None, f"p.{func.obj.member}[{text}] names a type this "
                              f"path cannot read, so it establishes no pointee")
            return (None, f"p.{func.obj.member}[…] is called with a type "
                          f"argument this path cannot read, so it establishes "
                          f"no pointee")
        # Pointer[T](…) / UnsafePointer[T, …](…)
        if isinstance(func, F.SubscriptExpr):
            base = type_expr_text(func.obj)
            if base in POINTER_TYPE_CTORS:
                return pointee_of_type_text(f"{base}[{_index_text(func.index)}]")
            return (None, f"{base}[…] is a subscript this path cannot read as a "
                          f"pointer construction, so it establishes no pointee")
        if isinstance(func, F.IdentExpr) and func.name in POINTER_TYPE_CTORS:
            return (None, f"{func.name}(…) is called with no type argument here, "
                          f"so it establishes no pointee")
        if isinstance(func, F.MemberExpr) and func.member in ("bitcast", "rebind"):
            # The pointee CHANGES and the new spelling is the declaration.  The
            # new type is a template argument, so it hangs off the FUNC's
            # subscript, which the parser has already attached.
            inner = getattr(func, "index", None)
            if inner is not None:
                text = type_expr_text(inner)
                if text is not None:
                    return pointee_of_type_text(text)
        if isinstance(func, F.IdentExpr):
            callee = (functions or {}).get(func.name)
            if callee is not None and getattr(callee, "return_type", None):
                inner, why = pointee_of_type_text(callee.return_type)
                if inner is not None:
                    return (inner, why)
                return (None, f"{func.name}() is declared `-> "
                              f"{callee.return_type}`, which establishes no "
                              f"pointee: {why}")
            return (None, f"{func.name}() is a call to a function this image "
                          f"does not contain, so nothing here declares what it "
                          f"returns and no pointee is established")
        return (None, "the receiver is the result of a call whose return type "
                      "this path cannot read, so no pointee is established")
    return (None, "the receiver is bound from an expression that declares no "
                  "type, so no pointee is established")


def _index_text(index) -> str:
    if isinstance(index, F.TupleExpr):
        return ", ".join(type_expr_text(e) or "?" for e in index.elements)
    return type_expr_text(index) or "?"


def _name_pointee(fn, name, decls, functions, seen=()):
    """`(pointee_base, why)` for a NAME, or `(None, why)`.

    The agree-or-refuse rule, over the name's bindings.  A declared annotation
    is the strongest statement and is read first; a binding with no annotation
    falls to `_rhs_pointee`, which reads the four shapes that state a pointee
    in the corpus.  Every binding must AGREE: one disagreement refuses, and the
    `why` names both sides, because a reader who is told only that the bindings
    disagree cannot tell which one is the surprise.
    """
    param_ann = None
    if fn is not None:
        for p in (list(getattr(fn, "params", None) or [])):
            if isinstance(p, (tuple, list)) and p and p[0] == name \
                    and len(p) > 1 and isinstance(p[1], str):
                if param_ann is not None and param_ann != p[1]:
                    return (None, f"{name} is declared twice with different "
                                  f"types ({param_ann!r} and {p[1]!r}), so "
                                  f"there is no single pointee")
                param_ann = p[1]
    bindings = _name_bindings(fn, name) if fn is not None else []
    if param_ann is not None:
        bindings = [(param_ann, None)] + bindings
    if not bindings:
        # Nothing in this body says what the word is, which for an
        # UNANNOTATED PARAMETER is the common case rather than the end of it:
        # every call site of it is in this image, so the image is asked the same
        # question this function asks a declaration.  With nothing to decide
        # there, this sentence — which names the absence in the callee — is the
        # right one.
        return _pointee_from_the_image_or(
            fn, name, decls, functions, seen,
            f"nothing in this function binds {name!r} from anything this path "
            f"can read, so it is a word from the caller and its pointee is not "
            f"recorded here")
    found, found_why = None, None
    for ann, rhs in bindings:
        if ann:
            inner, why = pointee_of_type_text(ann)
        else:
            inner, why = _rhs_pointee(fn, rhs, decls, functions, seen)
        if inner is None:
            if found is not None:
                return (None, f"{name} is bound more than once and only one "
                              f"binding establishes a pointee: {found_why}, but "
                              f"another binding does not ({why}) — there is no "
                              f"single answer and one of them would be a guess")
            found_why = why
            continue
        if found is None:
            found, found_why = inner, why
        elif found != inner:
            return (None, f"{name} is bound more than once with two different "
                          f"pointes ({found} and {inner}), so a load from it "
                          f"has no single width and one of the two would be "
                          f"the wrong word")
    if found is None:
        # A parameter nothing in ITS OWN body declares is still a word this
        # image passes, and every call site of it is in the same function tree.
        return _pointee_from_the_image_or(
            fn, name, decls, functions, seen, found_why)
    return (found, found_why)


def _pointee_from_the_image_or(fn, name, decls, functions, seen, fallback_why):
    """`(pointee_base, why)` from the image's call sites, or `(None,
    fallback_why)` when there was nothing to decide.

    The one place `_name_pointee`'s two exits share, and it exists because
    "nothing to decide" and "refused" are both `(None, why)` one level down:
    a caller that only tested the base would silently keep its own sentence for a
    DISAGREEMENT between two call sites, which is the one case where the reader
    needs the other two sentences most.  `fallback_why` is what this function
    already knew — an absence in the callee — and it stays the answer whenever
    the image has nothing to add.
    """
    base, why = parameter_pointee_from_call_sites(fn, name, decls, functions,
                                                  seen)
    if base is not None or why:
        return (base, why)
    return (None, fallback_why)


def _name_declared_struct(fn, name, decls):
    """The one struct a name's own DECLARED type names, or None.

    A parameter annotation (`h: Boxed`) or a local's (`var h: Boxed`), read
    through `annotation_base_name` and looked up in `decls`.  This is the
    positive case of the agree-or-refuse rule — one declaration, so nothing to
    disagree about — and it is the reason a field read on a parameter can be
    answered at all when the unit declares two structs whose single fields share
    a name.
    """
    if not decls:
        return None
    anns = set()
    for p in (list(getattr(fn, "params", None) or [])):
        if isinstance(p, (tuple, list)) and p and p[0] == name \
                and len(p) > 1 and isinstance(p[1], str):
            anns.add(p[1])
    for ann, _rhs in _name_bindings(fn, name):
        if ann:
            anns.add(ann)
    if len(anns) != 1:
        return None
    base = annotation_base_name(anns.pop())
    return structs_declared(base, decls) if base else None


def _member_candidates(fn, node, decls):
    """The structs `recv.field` might read out of, or `[]`.

    D2's candidate list, taken from the BUILD PASS's own holder table
    (`fn._frame_candidates`, published by `_frame_receivers`) rather than
    re-derived, so the two cannot disagree about which struct a name might be.
    `self` falls back to the structs that declare a method of this name, which
    is the same thing for a lifted method.

    A candidate set of more than one is NOT an error here — `agree-or-refuse`
    is applied by the caller over the declared types — and a candidate set of
    ZERO is what `formal/build.py`'s absence of the table means, so the caller
    refuses and says why rather than assuming a struct.
    """
    base = node.obj
    base_name = base.name if isinstance(base, F.IdentExpr) else None
    if base_name is None or fn is None:
        return []
    # A DECLARED receiver type, which is the strongest statement available and
    # the positive case of the same agree-or-refuse rule: a parameter annotated
    # `h: Boxed` names ONE struct, so there is nothing to disagree about.  It
    # is checked BEFORE the holder table because the holder table is keyed by
    # NAME and this is keyed by TYPE, and the two disagree whenever a unit
    # declares two one-field structs with the same field name — measured while
    # landing this: `Boxed.p: Pointer[UInt8]` next to
    # `Boxed2.p: Pointer[Pointer[UInt8]]` produced "there is no single pointee"
    # for a function whose parameter said `h: Boxed` in as many words.
    declared = _name_declared_struct(fn, base_name, decls)
    if declared is not None:
        return [declared]
    cands = (getattr(fn, "_frame_candidates", None) or {}).get(base_name)
    if cands:
        return [cands] if isinstance(cands, dict) else list(cands)
    if base_name == "self":
        # A lifted method is emitted under `<Struct>_<method>`, and the
        # FunctionDef this is called with carries THAT name, so matching on
        # `fn.name` alone finds nothing for `self` inside a method — which is
        # the corpus's shape (`self.ptr.value()` is how every C library's
        # pointer wrapper reads its target).  Keying on both spellings is what
        # the build pass does (`method_owner_names` publishes the same pair),
        # and the SET matters: two structs with a method of one name are two
        # candidates and agree-or-refuse applies to them.
        fn_name = getattr(fn, "name", None)
        out = []
        for st in (decls or {}).values():
            for m in struct_methods(st):
                if getattr(m, "name", None) in (fn_name, None) or \
                        f"{st.name}_{getattr(m, 'name', None)}" == fn_name:
                    out.append(st)
                    break
        if out:
            return out
    # A VALUE holder: a one-field struct, whose receiver IS its field.  The
    # build pass publishes no frame slot for one, so there is no table entry,
    # and the candidates are every struct of this unit with exactly one field
    # of that name.  A SET and not one, because agree-or-refuse has to be able
    # to see two structs that both call their single field `p` and disagree
    # about its type — picking one would be the guess this whole section is
    # arranged to prevent.
    if decls:
        by_field = [st for st in decls.values()
                    if struct_field_count(st) == 1
                    and struct_field_name(struct_fields(st)[0]) == node.member]
        if by_field:
            return by_field
    return []


def _member_pointee(fn, node, decls, functions):
    """`(pointee_base, why)` for `recv.field` — D2's tables, consumed.

    The receiver is a FRAME SLOT or a nested frame read, so the declaration that
    says what the slot holds is the struct's own field declaration, and this is
    `frame_field_type_candidates`'s question one level out: the same
    agree-or-refuse rule over the same candidate list, asked about a field's
    TYPE rather than about whether the slot holds a frame.  It is called, not
    re-derived — the candidates come from `fn._frame_candidates`, which is the
    build pass's own holder table, so the two cannot disagree about which
    struct a name might be.

    TWO receiver shapes, and the difference is `struct_is_framed`'s rather than
    a new one:

      * a FRAMED holder (2+ fields) — `h.p` reads slot 1, so the field's
        declared type is the slot's type;
      * a VALUE holder (one field) — its receiver IS its field
        (`struct_is_framed`: "a one-field struct's receiver is its field"), so
        `h.p` is the word `h` holds and the declared type is again the field's.
        Handled here because the second shape is the corpus's `Boxed`-shaped
        holder and `fn._frame_candidates` has no entry for it — the build pass
        does not make a value struct's fields into frame slots, so there is no
        table to read and the candidates come from the same struct list by the
        field's own name.
    """
    cands = _member_candidates(fn, node, decls)
    if not cands:
        return (None, f"{dotted_receiver(node)} is a field read and this path "
                      f"cannot establish which struct's frame it reads out of, "
                      f"so the field's declared type — and with it the "
                      f"pointee — is not available")
    if isinstance(cands, dict):
        cands = [cands]
    rows = field_type_rows(cands, node.member, decls)
    found = set()
    for _sn, base_t, ann, why, _ev in rows:
        if base_t is None:
            return (None, f"{dotted_receiver(node)} is not typed: {why}")
        found.add(ann)
    if len(found) > 1:
        return (None, f"{dotted_receiver(node)} is typed "
                      f"{field_type_disagreement(cands, node.member, rows)}, so "
                      f"there is no single pointee")
    ann = found.pop()
    return pointee_of_type_text(ann)


def _member_declared_text(fn, node, decls):
    """The field's agreed declared annotation text, or None — the D2 table, one
    step up from `_member_pointee`.

    `_member_pointee` asks whether a field is a POINTER and what its pointee is;
    this asks the same agreed table for the annotation itself, so
    `receiver_declared_is_pointer` can tell `Pointer[UInt8]` from `ProcessState`
    on the same candidate list rather than re-walking the struct.  Returns `None`
    for a disagreement and for no declaration, which is the same refusal
    direction as `struct_field_declared_type`'s own.
    """
    cands = _member_candidates(fn, node, decls)
    if not cands:
        return None
    anns = {r[2] for r in field_type_rows(cands, node.member, decls) if r[2]}
    return anns.pop() if len(anns) == 1 else None


def dotted_receiver(node) -> str:
    """`recv.field` as written, for a diagnostic that quotes the source.

    Public because both backends use it: a dereference is an EXPRESSION, so its
    refusal lives in the emitter, and the emitter has to name the receiver the
    way the source spells it rather than as whatever the model recovered.
    Reaching into `formal/model.py` for a private helper would be the wrong
    dependency direction — `receiver_shape` and `receiver_declared_is_pointer`
    are the public ones beside it, and this is the third question about a
    receiver the same three functions answer between them.
    """
    if isinstance(node, F.MemberExpr):
        obj = dotted_receiver(node.obj)
        return f"{obj}.{node.member}" if obj else node.member
    if isinstance(node, F.IdentExpr):
        return node.name
    return "<expr>"


def pointer_pointee(fn, expr, decls: dict, functions: dict = None, seen=()):
    """`(pointee_base, why)` for a POINTER receiver, or `(None, why)`.

    THE entry point both backends ask before emitting any load, and the reason
    it is here rather than in either backend is the same as every other shared
    decision in this file: the load's WIDTH is a property of the program, not of
    the architecture, and two readers of "what does this pointer point at" are
    two widths.  `x86_64_model_test.py` exists to keep the two backends'
    *refusals* in step; this is the half that keeps their *instructions* in step,
    and it is the half that matters, because a disagreement here is not a
    diagnostic that differs but a `movzbl` on one side and a `movq` on the other
    over the same bytes.

    The four receiver shapes, and what each one is read from:

      * a NAME — its parameter annotation and its bindings, agree-or-refuse
        (`_name_pointee`);
      * `recv.field` — the struct's own field declaration, through D2's
        candidate table (`_member_pointee`);
      * a POINTER CONSTRUCTION or a `bitcast` in receiver position — the type
        argument itself (`_rhs_pointee`);
      * anything else — no declaration, which IS the answer.

    `decls` is `{name: StructDef}` for the structs this image declares, and
    `functions` is `{name: FunctionDef}` for the same image; both are the
    backend's own tables, so nothing here re-walks a tree another pass walked.

    **`seen` is the chain of `(id(fn), name)` pairs already being derived**, and
    it is threaded here rather than inside `_name_pointee` alone because a NAME
    with no declaration of its own now asks the IMAGE (`parameter_call_site_
    pointees`), which asks about the CALLER's arguments, which are names again:
    `a(p) → b(p) → a(p)` is three functions and one name. A pair already on the
    chain contributes no observation rather than looping, which is
    `parameter_call_site_pointers`' rule for the same reason.
    """
    if isinstance(expr, F.IdentExpr):
        return _name_pointee(fn, expr.name, decls, functions, seen)
    if isinstance(expr, F.MemberExpr):
        return _member_pointee(fn, expr, decls, functions)
    if isinstance(expr, F.CallExpr):
        return _rhs_pointee(fn, expr, decls, functions, seen)
    return (None, "the receiver is an expression that declares no type, so no "
                  "pointee is established")


def _declared_annotations(fn) -> dict:
    """`{name: {annotation, …}}` — every type this function DECLARES for a name.

    The declarations only: a parameter's annotation and every `var x: T` in the
    body.  A name bound by an assignment with no annotation is absent, and that
    absence is the answer every consumer here wants — a width or an integer-ness
    that no declaration states is not established, and this path refuses rather
    than guesses (`bugs/FORMAL_known_limits.md`'s rule).

    **Agree-or-refuse, not last-write-wins**, for the reason `_name_bindings`
    gives: two declarations that name two different pointees are a
    disagreement, and picking one is the silently-wrong answer.  So a name with
    two annotations has two entries here and every reader that wants ONE answer
    asks whether there is exactly one.

    Cached on `fn` because the emitters ask it from `_emit_binop`, which is the
    hottest site in both backends, and the answer cannot change: the AST is
    fixed by the time any of them runs.
    """
    cached = getattr(fn, "_declared_annotations", None)
    if cached is not None:
        return cached
    out = {}
    for p in (list(getattr(fn, "params", None) or [])):
        if isinstance(p, (tuple, list)) and len(p) > 1 and p[0] \
                and isinstance(p[1], str):
            out.setdefault(p[0], set()).add(p[1])
    for node in iter_nodes(getattr(fn, "body", None)):
        if isinstance(node, F.VarDecl) and node.name and node.type_ann:
            out.setdefault(node.name, set()).add(node.type_ann)
    fn._declared_annotations = out
    return out


def _only_declared(fn, name):
    """The one annotation `fn` declares for `name`, or None (0 or 2 of them).

    **Read, never popped.** The set is the cache `_declared_annotations`
    publishes, and two callers asking the same question must get the same
    answer: a `pop()` here left the second caller with an empty set, which is
    the one way this table could say "nothing is declared" about a name the
    function declares — and the two callers here are on opposite sides of one
    answer (the emitter scales, the model accounts for the scaling), so the
    second one to ask would have been the one to disagree.
    """
    anns = _declared_annotations(fn).get(name) or ()
    return next(iter(anns)) if len(anns) == 1 else None


def _is_integer_expression(fn, e, depth=0) -> bool:
    """True when `e` is an INTEGER by a declaration or a literal — never by
    inference.

    The conservative direction, and it is the only one available: this path's
    shared type reader (`formal.types.infer_expr`) answers a bare name with the
    DEFAULT INTEGER TYPE, so it cannot tell `k` (an `Int`) from `q` (a pointer)
    and using it here would scale `p + q`.  So a name counts only when the
    function DECLARES it as one of `INT_TYPE_CTORS`, a literal counts because a
    literal is its own value, and everything else — a call, a member read, a
    subscript, an undeclared name — is not an integer as far as this question
    is concerned.  A `p + k` whose `k` is undeclared is therefore NOT scaled,
    and the dereference that reads it is refused rather than answered at the
    wrong address, which is the same trade every other unestablished fact gets.
    """
    if depth > 8:
        return False
    if isinstance(e, (F.IntLiteral, F.BoolLiteral)):
        return True
    if isinstance(e, F.IdentExpr):
        ann = _only_declared(fn, e.name)
        return ann is not None and annotation_base_name(ann) in INT_TYPE_CTORS
    if isinstance(e, F.UnaryOp):
        return _is_integer_expression(fn, e.operand, depth + 1)
    if isinstance(e, F.BinaryOp) and e.op in ("+", "-", "*", "%", "//"):
        return (_is_integer_expression(fn, e.left, depth + 1)
                and _is_integer_expression(fn, e.right, depth + 1))
    return False


def _pointer_base_info(fn, expr, seen=()):
    """Find the base pointer declaration info for pointer arithmetic.
    Returns (name, pointee_width, pointee_name) or (None, None, None)."""
    if seen is None:
        seen = ()
    if isinstance(expr, F.IdentExpr):
        name = expr.name
        if name in seen:
            return (None, None, None)
        ann = _only_declared(fn, name)
        if ann is None:
            # Try to follow bindings
            for _ann2, rhs in _name_bindings(fn, name):
                if rhs is not None:
                    res = _pointer_base_info(fn, rhs, seen + (name,))
                    if res[0] is not None or res[1] is not None:
                        return res
            return (None, None, None)
        pointee, _why = pointee_of_type_text(ann)
        if pointee is None:
            return (None, None, None)
        info = POINTEE_WIDTHS.get(pointee)
        if info is None:
            return (None, None, None)
        return (name, info[0], pointee)
    if isinstance(expr, F.BinaryOp) and expr.op in ("+", "-"):
        # For pointer arithmetic, the base is in the left operand
        return _pointer_base_info(fn, expr.left, seen)
    if isinstance(expr, F.CallExpr) and isinstance(expr.func, F.SubscriptExpr) \
            and isinstance(expr.func.obj, F.MemberExpr) \
            and expr.func.obj.member in ("bitcast", "rebind"):
        # pass through
        if expr.args:
            return _pointer_base_info(fn, expr.args[0], seen)
    if isinstance(expr, F.CallExpr):
        # Try to see if it's a method call that returns a pointer
        return (None, None, None)
    return (None, None, None)


def _pointer_offset_scale(fn, e):
    """`(scale, why)` — what the ALU will multiply this offset by, and if it
    will not, the sentence that says which declaration is missing."""
    if not isinstance(e, F.BinaryOp) or e.op not in ("+", "-"):
        return (None, f"the address is a {type(e).__name__}, not a `p ± k` this "
                      f"path can scale")
    left = e.left
    name, width, pointee = _pointer_base_info(fn, e)
    if name is None and width is None:
        # Try old behavior for better error messages
        if not isinstance(left, F.IdentExpr):
            return (None, f"the address's base is a {type(left).__name__}, not a "
                          f"NAME this path has a declared pointee for")
        name = left.name
        ann = _only_declared(fn, name)
        if ann is None:
            return (None, f"`{name}` is declared nothing, or two things that "
                          f"disagree, so there is no pointee to scale by")
        pointee, _why = pointee_of_type_text(ann)
        if pointee is None:
            return (None, f"`{name}` is declared {ann!r}, which does not name a "
                          f"pointee, so there is no element width to scale by")
        info = POINTEE_WIDTHS.get(pointee)
        if info is None:
            return (None, f"the pointee of `{name}` is {pointee}, a width this "
                          f"model does not establish, so there is no element width "
                          f"to scale by")
        width = info[0]
    if width == 1:
        return (None, f"the pointee is one byte wide, and "
                      f"a one-byte element needs no scale")
    if not _is_integer_expression(fn, e.right):
        offset = _offset_text(e.right)
        base_name = name if name else _offset_text(left)
        return (None,
                f"the offset is `{offset}`, and this path scales only an offset "
                f"it can establish as an INTEGER by declaration, so there is "
                f"nothing to say whether `{offset}` counts ELEMENTS or BYTES — "
                f"`{base_name} {e.op} {offset}` has the POINTER and the ELEMENT WIDTH "
                f"off a declaration and only the offset is missing")
    return (width, None)


def _offset_text(e) -> str:
    """The offset expression as a BARE token, for a message to wrap in code.

    One reader, because a refusal that spells the offset two ways is a refusal
    whose text and whose variable name can drift, and the name is the part the
    reader has to act on.  Bare, because the caller composes it into the
    sentence — the offset appears twice in this refusal and a value that carried
    its own backticks made the first one read `` `p + `k` ``.
    """
    if isinstance(e, F.IdentExpr):
        return e.name
    return f"a {type(e).__name__}"


def pointer_offset_scale(fn, e):
    """The width an integer offset in `p ± k` must be scaled by, or None.

    **THE ONE PREDICATE, and it is one because the two readers would otherwise
    disagree in the direction that is a wrong answer rather than a refusal.**
    Both backends' `_emit_binop` ask it what to multiply the offset by, and
    `dereference_lowering`'s `_offset_scale` asks it whether the address it is
    about to load through is already scaled.  If the emitters scaled and the
    model did not know, the load is at the right address and the model thinks it
    is at the wrong one and refuses a correct program; if the model allowed and
    the emitters did not, `p + 1` loads eight bytes at `p+1` and reports them as
    the SECOND element — which is the defect this function exists to make
    impossible.

    Four conditions, all of them about a DECLARATION:

      * `p ± k` — an `Int`-width arithmetic operator with an integer offset.
        Anything else (a call, a subscript, a container) is somebody else's
        question;
      * `p` is a NAME, and the ONE annotation this function declares for it
        names a pointer type (`pointee_of_type_text`, the one reader of that
        question) whose pointee width `POINTEE_WIDTHS` establishes and which is
        not 1 — so there is something to scale BY;
      * `k` is an integer by `_is_integer_expression`, so `p + p` (which both
        backends intercept as a pointer difference before the ALU) and a
        `p + <anything the model cannot type>` are not scaled;
      * the name declares exactly one annotation.  Two is a disagreement and
        this returns None, which is the refusing direction.

    `None` for everything else, and the refusal that follows is
    `_offset_scale`'s own: an offset this cannot account for is not answered at
    a guessed address.  The measure behind the shape is the subscript path's,
    which has scaled since before the pointer value model existed:
    `formal/arm64_codegen.py`'s `p[i]` emits `movz X2, #width; mul X1, X1, X2`
    before the add, and this is the `p + k` spelling of the same arithmetic.

    `_pointer_offset_scale` is where the conditions live and this is its `[0]`.
    Keeping the split is what lets the two readers share ONE decision while the
    one that has to write a sentence can say which of the four refused, without
    a second list of conditions to fall out of step with this one.
    """
    return _pointer_offset_scale(fn, e)[0]


def _offset_scale(fn, expr, width, seen=()):
    """`(ok, why)` — is every integer offset in this address scaled by `width`?

    The second half of a dereference's correctness, and it is a separate question
    from the width because the ADDRESS and the LOAD have to agree about the
    element size.  Measured: on this tree `q = p + 3` on a `char *` produces
    `base + 3` — the ALU adds the raw integer, with no scaling — which is
    correct C for a one-byte pointee and wrong for every other one.  That was
    unobservable while the only pointers on this path were `char *`, and it
    becomes observable the moment `Pointer[Int64].value()` is answerable:
    `p + 1` on an `Int64` pointee would load eight bytes at `p+1` and report
    them as the SECOND element.

    **The ALU scales it now** (`pointer_offset_scale`, and the `movz`/`mul` pair
    both `_emit_binop`s emit), so the `p ± k` arm below is no longer a refusal
    for every width: it is a refusal for the offsets this path cannot ACCOUNT
    for, which is the honest remainder and is a different list from the one this
    function started with.  An offset the emitters scaled by exactly `width` is
    answered, because the address and the load now agree by construction rather
    than by the reader's care.

    So the check is here, at the point where the width is known, rather than
    being papered over in the emitter:

      * `width == 1` — the identity scale, so ANY number of offsets is correct
        and the whole of the corpus's `p + k` is answerable;
      * a callee in the address chain — UNSOUND unless the callee is a
        `bitcast`/`rebind` (which changes the type without moving the address),
        because a function that returns `p + 1` hides its arithmetic from here.
        This is the honest limit and it is recorded, not worked around;
      * `p ± k` scaled by this width — answered, by `pointer_offset_scale`;
      * `p ± k` the emitters did NOT scale — refused, and the refusal says which
        of the two facts is missing rather than claiming the ALU adds a raw
        integer, which stopped being true when the scale landed.
    """
    if width == 1:
        return (True, None)
    if isinstance(expr, F.IdentExpr):
        if expr.name in seen:
            return (False, f"the address is an alias cycle through {expr.name!r}")
        for _ann, rhs in _name_bindings(fn, expr.name):
            ok, why = _offset_scale(fn, rhs, width, seen + (expr.name,))
            if not ok:
                return (False, why)
        return (True, None)
    if isinstance(expr, F.BinaryOp) and expr.op in ("+", "-"):
        scaled, why_not = _pointer_offset_scale(fn, expr)
        if scaled == width:
            return (True, None)
        # The sentence names the condition that refused, because the conditions
        # are about DIFFERENT names and only one of those names is wrong.  And
        # the ADVICE differs with them, which is why it cannot be one sentence
        # appended to whatever the reason happened to be: the emitters scale
        # only when the scale WAS established, so hand-scaling the offset is
        # right when there is no scale and WRONG when there is one that is not
        # this load's width — there `p + k * 8` would be scaled a second time
        # on top of the scale already emitted.
        element = WIDTH_POINTEES.get(width)
        if why_not is None:
            # Every condition held, so the emitters ARE scaling — by `scaled`,
            # which is not the width this load wants.  The only branch where
            # hand-scaling is wrong advice, and the only one that says so,
            # because it is the only one where a scale exists.
            what = (f"it scales by the element size {scaled} bytes, and this "
                    f"load is {width} bytes wide")
            advice = (f"Declare the pointee as the {width}-byte element this "
                      f"load wants"
                      + (f" (`p: Pointer[{element}]`)" if element else "")
                      + f" — do NOT scale the offset by hand here, because this "
                        f"path already scales it by {scaled}")
        else:
            what = why_not
            advice = (f"Scale it by hand (`p + k * {width}`)"
                      + (f", or declare the pointer and the offset "
                         f"(`p: Pointer[{element}]`, `k: Int`)" if element else "")
                      + " so the arithmetic is one this path can do")
        return (False,
                f"the address is `p {expr.op} k` and the load is {width} bytes "
                f"wide, so the two have to agree about the element size — and "
                f"this path only scales an integer offset it can read a "
                f"POINTER and an ELEMENT WIDTH off a declaration for: {what}. "
                f"{advice} — see "
                f"the pointer value model (landed in f69079be0) §9")
    if isinstance(expr, F.CallExpr) and isinstance(expr.func, F.SubscriptExpr) \
            and isinstance(expr.func.obj, F.MemberExpr) \
            and expr.func.obj.member in ("bitcast", "rebind"):
        return (True, None)      # a retyping, not a move
    if isinstance(expr, F.CallExpr):
        return (False,
                f"the address is the result of a call, and a callee that "
                f"returns `p + k` hides its arithmetic from here — the scale "
                f"cannot be established for a {width}-byte pointee, and a load "
                f"at an address the caller cannot account for is a wrong answer")
    return (True, None)


# The spellings that are `Optional[Pointer[…]]` — a NULLABLE pointer — whose
# `value()` is the UNWRAP rather than a LOAD, and the reader that recognises one.
# Both halves are here rather than at the call site because `dereference_lowering`
# is not the only reader: `subscript_base_lowering` asks the same question about
# `p[i]`, and a second place that spelled the nullable-pointer test would be a
# second place for the two to disagree about what `OptionalPointer` is.
#
# The name says which question it answers, and that is the whole point of it:
# this is NOT the table that makes a nullable pointer one word at a C boundary
# (that is `POINTER_TYPE_CTORS`, and every name here is in it), it is the table
# that makes the `.value()` of one an unwrap rather than a load of its first
# byte. A reader adding a nullable pointer needs BOTH, and putting the name in
# one of them and expecting the other question to follow is the mistake the two
# names are here to make impossible.
#
# `_CPointer` is the stdlib's PREVIOUS name for the same type — measured
# 2026-10-02, `new-modular`'s `std/` no longer spells it anywhere, so the name is
# here because the corpus this path was measured on used it and because removing
# it would change the answer for a spelling that is still in the table's own
# docstrings, not because anything reads it today.
NULLABLE_POINTER_UNWRAP_ALIASES = ("OptionalPointer", "_CPointer")


def nullable_pointer_unwrap(fn, expr, decls: dict, functions: dict = None):
    """`(True, why)` when this receiver's DECLARED type is a nullable pointer.

    **And the reason it is asked before any pointee question is the whole of
    this function.**  A nullable pointer has BOTH a pointee and an unwrap, and
    Mojo's two answers are different numbers:

    * `Pointer[UInt8].value()` is the BYTE AT the address — a load;
    * `OptionalPointer[UInt8, o].value()` — that is `Optional[Pointer[UInt8, o]]`
      in the language's own definition (`memory/pointer.mojo:163-170`), so the
      method resolved is `Optional.value()`, which is the UNWRAP: the pointer
      itself, unchanged.

    `dereference_lowering` sees only the SPELLING `value`, and the receiver's
    declared type is the only thing in hand that tells the two apart, so a
    nullable pointer read as a pointer produced the byte where the source says
    the address.  Measured on this tree, `std/os/env.mojo`'s own `getenv` shape
    with the previous spelling and no other change:

        p = external_call["getenv", _CPointer[UInt8, UntrackedOrigin[mut=False]]](name)
        String(unsafe_from_utf8_ptr=p.value())

    BUILDS, RUNS, and dies of SIGSEGV (exit 139) — the image builds a `char *`
    out of the first BYTE of the string ("hello" → 104 → address 104), and
    address 104 is not mapped.  Nothing exits non-zero before that and no
    diagnostic says anything: the wrong answer is a pointer to the low bytes of
    a string.

    **The identity is the correct VALUE, and it is correct for a reason that is
    about the representation rather than about the source**: `Optional[T]`'s
    payload here is one word (`bugs/FORMAL_stdlib_optional_needs_a_representation.md`
    measures `Optional` at one field), so the pointer and its wrapper are the
    same storage, and unwrapping is the identity on it — exactly the identity
    `Pointer()` already is on this path (wave 4's D4) and the same one
    `dereference_lowering`'s own struct branch derives and refuses for a
    different reason.

    **What the identity does NOT give is the RAISE.**  `Optional.value()` on
    `None` raises in Mojo, and this backend has no raise: a nullable pointer
    whose word is 0 unwraps to 0 here, and the source would have stopped.  That
    is a control-flow difference and it is a real one, so it is stated rather
    than claimed away — and it is the same gap the `Optional` doc records for
    every other unwrap (`None` and `Some(0)` are the same word on this path).
    It is not a reason to emit the byte instead: the load is wrong for a
    POPULATED one too, which is the case the measurement above is.

    The declared type is read with `_rhs_declared_text`, the same narrow reader
    `dereference_lowering`'s SIMD branch uses, for the same reason: it recovers a
    parameter annotation, a local's annotation, and an `external_call`'s declared
    return type, which are the three shapes a nullable pointer arrives in, and
    returns None for everything else rather than re-deriving the derivation.
    """
    text = _rhs_declared_text(fn, expr, decls, functions)
    if not text:
        return (False, None)
    base = annotation_base_name(text)
    if base in NULLABLE_POINTER_UNWRAP_ALIASES:
        return (True, f"{text} is `Optional[Pointer[...]]` — the stdlib's own "
                      f"definition of {base} — so `value()` is "
                      f"`Optional.value()`, the UNWRAP, and a nullable "
                      f"pointer's payload is one word on this path: the "
                      f"receiver is already the pointer")
    if base == "Optional":
        args = pointee_args(text)
        if args and annotation_base_name(args[0]) in POINTER_TYPE_CTORS:
            return (True, f"{text} is `Optional[Pointer[...]]`, so `value()` is "
                          f"`Optional.value()`, the UNWRAP, and a nullable "
                          f"pointer's payload is one word on this path: the "
                          f"receiver is already the pointer")
    return (False, None)


def dereference_lowering(fn, expr, decls: dict, functions: dict = None,
                         structs_by_name: dict = None, index_scaled: bool = False):
    """`("load", width, signed)` | ("identity", 8, False) | ("frame", struct)
    | None — with a refusal.

    `index_scaled=True` says the CALLER scales the index it supplies, so
    `_offset_scale` must judge the base address alone. It is the flag for a
    SUBSCRIPT (`subscript_base_lowering` below) and it exists because the two
    callers ask different questions about the same arithmetic: `p.value()` reads
    at whatever address `p` already holds, so a `p + k` in that address has to
    have been scaled by whoever wrote it, while `p[i]` reads at `p + i*width` and
    the multiply is this path's own — asking `_offset_scale` to account for the
    index would refuse every `q[0]` on a `Pointer[Int32]` for the sake of an
    offset the emitter adds itself. Measured: without the flag,
    `var q: Pointer[Int32] = malloc(16); q[0]` is refused with "the address is
    the result of a call", which is true of `q` and irrelevant to `q[0]`.

    THE pointer value model's decision, and the one function both backends call
    in place of `DEREFERENCE_METHODS` for a receiver that is a pointer.  A
    string is `None`, and the `why` is the refusal to emit.

    Four answers, and the third is what makes this a value model rather than a
    load:

      * `("load", width, signed)` — a scalar pointee whose width the table
        established.  `width` is 1, 2, 4 or 8 and is never anything else: a
        pointee that is not in `POINTEE_WIDTHS`, not in `POINTEE_FLOAT_NAMES`
        and not in `POINTEES_REFUSED` has NO established width, and the refusal
        says so.  That is the whole point of the exercise, and it is what
        removes D1's SIGBUS: the old reasoning had only the 8-byte load
        available, which over-reads a `UInt8` pointee by seven bytes; with the
        pointee known the load is one byte, and one byte is the correct answer
        rather than an approximation.
      * `("float", 8, False)` — a `Float64` pointee.  The load is bit-exact
        (one `LDR` of eight bytes) and what makes it a DOUBLE rather than an
        integer is `pointer_deref_kind`, which every context around the
        dereference asks.  The shape is `"float"` and not `"load"` so
        `subscript_base_lowering` can refuse `p[i]`, whose element kind is the
        pointer's own (an integer) and whose eight right bytes would then be
        read as the wrong number.
      * `("identity", 8, False)` — the receiver is a NULLABLE POINTER and the
        `.value()` is the UNWRAP of it, not a load.  `nullable_pointer_unwrap`
        is asked first, before any pointee question, because a nullable pointer
        has a pointee AND an unwrap and the two answers are different numbers;
        see that function for the whole of why the load was the wrong one.
      * `None` — no pointee, a pointee with no width, a wide `SIMD` or a blob,
        or a STRUCT.  The struct case is the interesting one and its
        derivation is CORRECT (a struct's value is a frame address, so the
        receiver already is the pointee — the same identity `Pointer()` gives,
        and the same shape as the string decision's "the length is a
        computation"); it is refused because the machinery that reads fields
        off a frame address does not recognise a name bound through a pointer,
        and emitting the identity today returns 0 where the source says 22 on
        BOTH architectures.  The `why` spells that out, and the `why` is the
        same text on both architectures because it comes from here.

    The three-tuple shape is kept for every answer on purpose: every
    existing reader unpacks `shape, width, signed`, and the two that ignore the
    shape (`subscript_base_lowering` and both `_emit_dereference`) have to be
    taught to look at it.  A second arity for the new answer would make every
    reader a two-tuple branch, and the whole reason this function is shared is
    that the two architectures cannot come to different answers about a load.

    **The fourth answer, `("frame", struct, False)`, is the STRUCT pointee, and
    it is emitted rather than refused** (`pointer_frame_pointee` is its decision
    and the three places that consume it are the two backends'
    `_emit_dereference` and `pointer_frame_bindings`).  Nothing is loaded: the
    word in the receiver already IS the pointee, and the answer is that word —
    the same identity `Pointer()` gives and the same shape as a string's length
    being a computation rather than a field.  It is a load-width answer with no
    width in it, and the third element stays `False` so the two readers that
    ignore the shape are not handed a `struct` where they expect a bool.
    """
    unwrapped, unwrap_why = nullable_pointer_unwrap(fn, expr, decls,
                                                    functions)
    if unwrapped is True:
        return (("identity", 8, False), unwrap_why)
    inner, why = pointer_pointee(fn, expr, decls, functions)
    if inner is None:
        return (None, why)
    if inner in POINTEES_REFUSED:
        return (None, f"the pointee is {inner}, and {POINTEES_REFUSED[inner]}")
    if inner in POINTEE_FLOAT_NAMES:
        # A FLOAT pointee the load can carry: eight bytes, bit-exact, and the
        # answer's KIND is the pointee's.  The shape is `"float"` rather than
        # `"load"` so the two readers that unpack it can tell the one fact that
        # matters apart — a `p[i]` SUBSCRIPT must not lower through this, because
        # its element kind comes from the pointer's own kind (an integer) and the
        # eight right bytes would be read as the wrong number.  Both emitters'
        # `_emit_dereference` emit the width-8 `LDR` for it, which is the whole
        # instruction the load needs; what makes it a double is
        # `pointer_deref_kind`, which every context around it asks.
        if not index_scaled:
            scaled, scale_why = _offset_scale(fn, expr, 8)
            if not scaled:
                return (None, scale_why)
        return (("float", 8, False), why)
    if inner in POINTEE_WIDTHS:
        width, signed = POINTEE_WIDTHS[inner]
        if not index_scaled:
            scaled, scale_why = _offset_scale(fn, expr, width)
            if not scaled:
                return (None, scale_why)
        return (("load", width, signed), why)
    if inner in ("SIMD", "Scalar"):
        args = pointee_args(_rhs_declared_text(fn, expr, decls, functions) or "")
        n = args[1] if len(args) > 1 else None
        if (n == "1" and args and args[0] in POINTEE_WIDTHS
                and args[0] not in FLOAT_POINTEE_WIDTHS):
            width, signed = POINTEE_WIDTHS[args[0]]
            return (("load", width, signed),
                    f"the pointee is {inner}[{args[0]}, 1], which is one word "
                    f"and reduces to {args[0]}")
        return (None, f"the pointee is {inner}[…], and the element count is not "
                      f"spelled as the literal 1 — a formal value is one word, "
                      f"so a wider SIMD would have to drop words, and an "
                      f"element count this path cannot read is the untyped "
                      f"direction")
    st = (structs_by_name or {}).get(inner)
    if st is not None:
        # A STRUCT pointee is the IDENTITY, and this is the load-bearing
        # decision of the whole section, so the reasoning is long and it is
        # worth reading.
        #
        # The DERIVATION is right and it is the only thing that was ever in
        # doubt: a struct's value on this path is a frame ADDRESS, so the word
        # in the receiver already IS the pointee, exactly as `Pointer()` is
        # (wave 4's D4) and exactly as a string's length is a computation
        # rather than a field.  Nothing is loaded; the answer is the receiver.
        #
        # It WAS refused, and the refusal named its own reason honestly: the
        # machinery that reads fields off a frame address is `_frame_receivers`'
        # job, it decides which names hold frame addresses, and it recognised
        # them from a CONSTRUCTOR BINDING (`x = A()`) or from being a callee's
        # first parameter.  A name bound from `p.value()` was neither, so the
        # analysis did not see it and `q.b` fell to the value-member path and
        # read a word of nothing.  Measured, on both architectures, with the
        # identity lowering in place:
        #
        #     struct P3:  var a: Int64 / var b: Int64 / var c: Int64
        #     def f(p: Pointer[P3]) -> Int:  return Int(p.value().b)
        #     main:  t = P3(); t.b = 22;  printf(..., f(t))
        #
        # printed **0** on arm64 and on x86-64, where the source says 22.  So
        # the identity was refused for producing a wrong answer, not for being
        # unprovable — and a wrong answer is the outcome this model exists to
        # prevent, which is the right reason to refuse and not a reason to leave
        # it refused.
        #
        # What made it answerable is `pointer_frame_pointee`'s three consumers,
        # and they are the same three for both machines: `_frame_receivers`
        # seeds a name bound here into the holder tables
        # (`pointer_frame_bindings`), `_frame_return_status` counts a `return`
        # of one as returning a FRAME so the caller's block is reserved and the
        # callee copies into it, and both `_emit_dereference`s emit the
        # receiver and nothing else.  A frame reaching a caller is then a COPY
        # in the caller's own scratch — the returned-frame convention — rather
        # than an address of somebody else's, which is what the frame-lifetime
        # half of the old refusal was about and is why the answer is safe rather
        # than merely reachable.
        #
        # **A ONE-FIELD pointee is still refused**, and it is a different fact
        # rather than a half-answer: such a struct's value is the word ITSELF,
        # not an address of one, so there is nothing at the address and the
        # identity would be wrong rather than right.  `struct_is_framed` is the
        # one test for the two, as it is everywhere else on this path.
        if not struct_is_framed(st):
            return (None, f"the pointee is {inner}, a one-field struct whose "
                          f"value on this path is the word itself rather than "
                          f"memory, so there is nothing at the address to load "
                          f"and the honest reading is not a dereference at all")
        return (("frame", st, False),
                f"the pointee is {inner}, a STRUCT, and a struct's value on this "
                f"path is a frame ADDRESS rather than memory contents — so this "
                f"is not a load at all: the word in the receiver already is the "
                f"pointee, and the answer is the identity, the same one "
                f"`Pointer()` gives. It is emitted as that word and nothing else, "
                f"and the {inner} frame's fields are read off it through the "
                f"holder tables `_frame_receivers` publishes for it "
                f"(`pointer_frame_bindings`) — which is the one piece of "
                f"recognition the refusal above said was missing. A "
                f"`Pointer[{inner}]` is a frame address, so the channels that "
                f"would hand the CALLER an address of somebody else's frame are "
                f"still refused where they are for any holder: a `return` of one "
                f"goes through the returned-frame convention, which copies into "
                f"a block in the caller's own scratch, and a store of one into "
                f"a field or a container is `formal/build.py`'s frame-escape "
                f"refusal, exactly as it is for a constructed "
                f"{inner}")
    return (None, f"the pointee is {inner}, which is not a width this model "
                  f"establishes and not a struct this image declares, so no "
                  f"load at that address has a known width — and a load whose "
                  f"width is not established is the one instruction this path "
                  f"must not emit, because an 8-byte load of a 1-byte pointee "
                  f"returns a plausible number assembled from adjacent bytes and "
                  f"faults at a page edge. {_declared_note(why)}")


def pointer_deref_kind(fn, expr, decls: dict, functions: dict = None):
    """`FLOAT_KIND` when `expr` is a pointer dereference whose pointee is a
    float, else `None`.

    The reader that makes a `Pointer[Float64]` LOAD answerable rather than
    merely emittable: `dereference_lowering` decides the eight bytes and this
    decides what they MEAN, and the two are separate because they are asked at
    different times.  The lowering is asked when the dereference is emitted and
    has the receiver in hand; the kind is asked by every CONTEXT the
    dereference lands in — `Int(p.value())`, `p.value() + 1.0`, a `%d` format,
    a parameter the callee declared an `Int` — and those contexts ask through
    `ValueKinds.kind_of` before (and instead of) emitting the dereference at all.

    The receiver is read with the SAME `pointer_pointee` the lowering uses, so
    the two cannot disagree about what a pointer points at: two readers of that
    question is two widths, and here it would be two KINDS.  `None` is every
    other shape — a non-dereference, a non-pointer receiver, a pointee that is
    not a float — and it leaves every existing decision exactly where it was,
    which is why this is a hook consulted from `kind_of` and not a rewrite of
    the default.
    """
    if not isinstance(expr, F.CallExpr) or expr.args or expr.kwargs:
        return None
    func = getattr(expr, "func", None)
    if not (isinstance(func, F.MemberExpr)
            and func.member in DEREFERENCE_TRY_NAMES):
        return None
    inner, _why = pointer_pointee(fn, func.obj, decls, functions)
    return FLOAT_KIND if inner in POINTEE_FLOAT_NAMES else None


def _declared_note(why) -> str:
    return f"It was declared as {why!r}." if why and " " not in why else ""


def pointer_frame_pointee(fn, expr, decls: dict, structs_by_name: dict = None):
    """`(StructDef, why)` when this POINTER receiver points at a FRAME of a
    struct THIS IMAGE declares, else `(None, why)`.

    The decision `dereference_lowering`'s `("frame", …)` answer is made of, and
    the reason it is a function rather than three call sites: a pointer to a
    frame has to be recognised by the build pass (which seeds the holder
    tables), by the returned-frame fixpoint (which decides whether to reserve a
    block for it) and by both backends (which emit it), and four
    recognitions of one fact is four things that agree until the day they do
    not.  `pointer_pointee` is the ONE reader of what a pointer points at and
    this adds nothing to it but the two questions that follow from the answer:
    is the pointee a struct of this unit, and is that struct framed.

    **No image-wide call-site table is asked here, deliberately.**  `functions`
    is not a parameter, so a receiver whose pointee only the CALL SITES could
    establish — an unannotated parameter — has no pointee here and is refused,
    which is the safe direction and the one `dereference_lowering`'s own
    `parameter_call_site_pointees` hook widens elsewhere.  The alternative was a
    fourth recognitions problem of a sharper kind: the two backends have a
    `{name: FunctionDef}` table and the build pass has a LIST, so passing each
    what it has would make the two answer differently about an overloaded
    name's second definition.  One spelling of the rule, asked with what every
    caller has.

    A STRUCT OF ANOTHER MODULE is not a frame this pass can lay out: its field
    list is in that module's own compilation, not here, and a slot index read
    from a dylib's manifest would be a second source of layout truth.  So a
    pointee base name this image does not declare is not a frame, and the
    refusal says which of the three it is not.
    """
    inner, why = pointer_pointee(fn, expr, decls)
    if inner is None:
        return (None, why)
    st = (structs_by_name or decls or {}).get(inner)
    if st is None:
        return (None, f"the pointee is {inner}, which is not a struct this "
                      f"image declares: its field list lives in the module that "
                      f"declares it, so there is no layout here to read the "
                      f"pointee's fields through")
    if not struct_is_framed(st):
        return (None, f"the pointee is {inner}, a one-field struct whose value "
                      f"on this path is the word itself rather than a frame, so "
                      f"there is no frame at that address for a name to hold")
    return (st, why)


def pointer_frame_expression(fn, expr, decls: dict,
                             structs_by_name: dict = None):
    """`(StructDef, why)` when `expr` is a `p.value()` / `p.unsafe_value()`
    whose answer is a FRAME, else `(None, why)`.

    `pointer_frame_pointee` asked of the whole DEREFERENCE CALL rather than of
    its receiver, and it exists so that the three consumers can each hand it the
    expression they happen to have:

      * `pointer_frame_bindings` has a binding's VALUE;
      * `_frame_return_status` has a `return`'s value;
      * both backends' member-read arm has `expr.obj`.

    Each of those reaches the same fact by spelling the dereference differently,
    and `DEREFERENCE_TRY_NAMES` is the ONE spelling of "the two names this path
    cannot tell apart" — so a third spelling of the dereference is a third
    construct.
    """
    if not isinstance(expr, F.CallExpr) \
            or not isinstance(expr.func, F.MemberExpr) \
            or expr.func.member not in DEREFERENCE_TRY_NAMES:
        return (None, f"`{spelled(expr)}` is not a dereference on this path, so "
                      f"it is not the place a frame comes from")
    return pointer_frame_pointee(fn, expr.func.obj, decls, structs_by_name)


def pointer_frame_member_refusal(expr, st) -> str:
    """`p.value().f` where `f` is not a field of the struct the pointer names.

    The sibling of `member_access_refusal`, and it exists for the same reason
    that one does: **both backends raise it, and they must raise the SAME
    WORDS.** The emitters' fall-through for a field access whose base this path
    cannot classify is one message in this module for exactly that reason, and a
    construct that newly became answerable — a pointer to a frame of this image —
    would otherwise have had its "no such field" sentence written out four
    times (two machines × read and store), which is four texts that agree until
    the day one of them is edited.

    The frame is known here, which is what makes the sentence specific: the
    struct's own field summary is the evidence, and "which word is this" is a
    question about THAT struct's layout rather than about the path's ignorance.
    """
    return (f"{spelled(expr)} reads {expr.member!r} out of a {st.name} this "
            f"pointer points at, and that struct's "
            f"{struct_field_summary(st)} has no such field: this path has no "
            f"way to know which word that is, and reading the wrong one is a "
            f"wrong answer rather than a failure")


def pointer_frame_store_refusal(expr, st) -> str:
    """`p.value().f = v` where `f` is not a field of the struct the pointer
    names — `pointer_frame_member_refusal`'s store half, and a separate function
    for the same reason it is a separate sentence: storing to the wrong word is
    not the same failure as reading it, and a reader who is told "reading the
    wrong one is a wrong answer" is being sent to look at a read that is not
    what their program does."""
    return (f"{spelled(expr)} stores into {expr.member!r} of a {st.name} this "
            f"pointer points at, and that struct's "
            f"{struct_field_summary(st)} has no such field: this path has no "
            f"way to know which word that is, and storing to the wrong one is a "
            f"wrong answer rather than a failure")


def pointer_frame_bindings(fn, decls: dict, structs_by_name: dict = None):
    """`{name: [struct, …]}` for the locals in `fn` bound from a POINTER to a
    frame of a struct this image declares.

    A LIST per name, for `struct_constructor_bindings`' reason and not by
    imitation of it: `q = p.value()` on one path and `q = make()` on another is
    one name with two layouts, and the candidate list is what makes that a
    refusal (`struct_frame_slot_candidates`) instead of whichever binding
    happened to be walked last.  A second binding that agrees is deduped.

    This is the reader `_frame_receivers`' fixpoint seeds from, and it is
    enumerated rather than inferred for the reason its docstring gives: a name
    wrongly added becomes a name whose field accesses are memory accesses, and a
    name wrongly missing is the silent one.  The shapes it covers are the two
    `frame_binding_target` recognises (`var q = p.value()` and `q = p.value()`)
    and nothing else — a tuple target binds a frame in a position that is a
    different question, and `frame_binding_target` is already the one reader of
    which statements are bindings.
    """
    out: dict = {}
    for node in iter_nodes(getattr(fn, "body", None)):
        name = frame_binding_target(node)
        if not name:
            continue
        st, _why = pointer_frame_expression(fn, frame_binding_value(node),
                                            decls, structs_by_name)
        if st is None:
            continue
        got = out.setdefault(name, [])
        if st not in got:
            got.append(st)
    return out


def _rhs_declared_text(fn, expr, decls, functions):
    """The declared type TEXT a receiver was read from, for the SIMD arity note.

    Deliberately narrow: it recovers the annotation string for the two shapes
    `dereference_lowering`'s SIMD branch needs it for — a name's annotation and
    a `bitcast`/construction type argument — and returns `None` for everything
    else rather than re-deriving the whole derivation a second time.
    """
    if isinstance(expr, F.IdentExpr) and fn is not None:
        for p in (list(getattr(fn, "params", None) or [])):
            if isinstance(p, (tuple, list)) and p and p[0] == expr.name \
                    and len(p) > 1 and isinstance(p[1], str):
                return p[1]
        for ann, _rhs in _name_bindings(fn, expr.name):
            if ann:
                return ann
        for _ann, rhs in _name_bindings(fn, expr.name):
            if isinstance(rhs, F.CallExpr) and isinstance(rhs.func, F.SubscriptExpr) \
                    and isinstance(rhs.func.obj, F.IdentExpr) \
                    and rhs.func.obj.name == "external_call":
                idx = rhs.func.index
                items = idx.elements if isinstance(idx, F.TupleExpr) else [idx]
                if len(items) >= 2:
                    return type_expr_text(items[1])
    if isinstance(expr, F.CallExpr) and isinstance(expr.func, F.MemberExpr) \
            and expr.func.member in ("bitcast", "rebind"):
        return type_expr_text(getattr(expr.func, "index", None))
    if isinstance(expr, F.MemberExpr):
        # A field read — the same D2 agreed table `_member_pointee` reads, asked
        # for the annotation itself so the POINTER-TO-POINTER and SIMD branches
        # can look one level in.  Not a second derivation: same candidates, same
        # agreement rule.
        return _member_declared_text(fn, expr, decls)
    if isinstance(expr, F.BinaryOp) and expr.op in ("+", "-"):
        return _rhs_declared_text(fn, expr.left, decls, functions)
    if isinstance(expr, F.CallExpr) and isinstance(expr.func, F.SubscriptExpr):
        base = type_expr_text(expr.func.obj)
        if base in POINTER_TYPE_CTORS:
            return f"{base}[{_index_text(expr.func.index)}]"
    return None


# A DEREFERENCE, not an identity. `UnsafePointer.value()` in Mojo returns the
# pointee, so on this path it would be a load from the address in the receiver
# — and a load is not one instruction here, for three separate reasons, each of
# which alone is enough to refuse:
#
#   1. THE POINTEe's TYPE decides the load. `Pointer[UInt8]` is one byte and
#      `Pointer[SIMD[dtype, 4]]` is four words, and neither is an 8-byte load.
#      The width and signedness come from `Scalar[T]`, and NOTHING in this
#      value model records a pointer's pointee: `Pointer` is in
#      IDENTITY_TYPE_CTORS, so `ptr` is an opaque word and the model cannot
#      even name the question. Teaching it to would be a pointer value model.
#   2. An 8-byte load is not a safe over-read of a smaller object. Reading
#      8 bytes at the address of a 1-byte object whose page ends there faults
#      (SIGBUS on the next page) — and `std/os/env.mojo`'s `ptr.value()` is
#      `_CPointer[UInt8]`, so the under-read is not hypothetical.
#   3. A STRUCT's value on this path is a frame ADDRESS, not memory
#      contents, so for `Pointer[SomeStruct]` there is no image at the address
#      to load at all. One word cannot hold a struct.
#
# 53 of the 76 files in this group are this one method (`std/os/env.mojo`'s
# `ptr.value()`), which is why the refusal is this specific and not the old
# blanket one. Wave 2's B5 correctly flagged that treating the characterised
# group as string methods would have been catastrophic; this is why.
#
# WAVE 6 (F2) — the table is SPLIT, because the measurement says the two names
# in it are not one question, and the comment above the receiver-kind list
# ("`Pointer.value()` and `Optional.unsafe_value()` are spelled alike and mean
# opposite things … a model that grouped them by spelling would implement one of
# them as the other") is the rule this table was violating.  The re-derived
# census over the whole stdlib (528 `value` + `unsafe_value` sites) is:
#
#   * `value` is a DEREFERENCE in **one** of them — `std/os/env.mojo:85`.
#     Every other `value` in the corpus is an identity: an enum's integral
#     value (`status.value()`, `func_attribute.value()`), an ITERATOR's current
#     item (`next_back().value()`, `peek_back().value()`, `left().value()`), a
#     SIMD's scalar (`v[i].value()` — `SIMD.value()` returns
#     `Scalar[Self.dtype]`), or a struct field.  So a table whose `value` entry
#     says "it is a load from the address the receiver holds" is FALSE about
#     ~527 of 528 files it is reported against, which
#     `bugs/FORMAL_known_limits.md` opens by calling "worse than no message".
#   * `unsafe_value` is BOTH: ~33 of its 47 sites are `Optional.unsafe_value`,
#     which is an UNWRAP (see UNWRAP_METHODS), and ~14 are a pointer load.
#
# So the two names are separated, and `value` moves to its own table
# (IDENTITY_VALUE_METHODS) with a message that is true of every receiver: the
# name is spelled the same for an enum, an iterator, a SIMD and a pointer, and
# this path can see only the spelling.  A pointer receiver IS answerable now —
# see `dereference_lowering` and POINTEES below, which is where the pointee is
# recovered and the load's width comes from.
DEREFERENCE_METHODS = {
    "unsafe_value": "is spelled like two different questions and this path "
                    "cannot tell them apart: Mojo spells the UNCHECKED READ of "
                    "an UnsafePointer `unsafe_value` and the UNWRAP of an "
                    "`Optional` the same name, and the two ask opposite things "
                    "— one follows an address, the other asks which of two "
                    "words was the empty one. A receiver this path cannot "
                    "establish to be a pointer is refused here rather than "
                    "read as one; if it IS a pointer, `dereference_lowering` "
                    "below decides the load from the pointee's declared type, "
                    "and an Optional receiver is refused as an unwrap instead "
                    "(see UNWRAP_METHODS, which is the other half of this)",
}

# `p.m(i)` — a dereference WITH an offset — is refused by name rather than by the
# arity check inside `_emit_dereference`, because for `unsafe_load` the argument
# is the ordinary spelling (`i = 0` is its default) and "takes no arguments"
# would be a true statement sent to a reader who has written the ordinary form.
# `p[i]` is the same program with the offset in the subscript, and that lowering
# exists (`subscript_base_lowering`, the same width table); what it does not do
# yet is answer a METHOD call, which is what this row's next step is.
DEREFERENCE_OFFSET_METHOD_NAMES = frozenset({"unsafe_load"})

# `value` on its own.  A name this path cannot resolve, for a reason that is
# true of EVERY receiver and is not about dereferences at all:  an enum's
# `value()` is its integral, an iterator's is the item it holds, a `SIMD`'s is
# its scalar, and a pointer's is the pointee.  Four different answers behind one
# spelling, and the two backends see only the spelling — so this is refused by
# NAME, and what a reader has to supply is a declaration this path can use, not
# a different method.
IDENTITY_VALUE_METHODS = {
    "value": "is spelled the same for four different questions and this path "
             "can see only the spelling: an enum's `value()` is its integral "
             "value, an ITERATOR's is the item it currently holds, a "
             "`SIMD`'s is its scalar (`SIMD.value()` returns "
             "`Scalar[Self.dtype]`), and a POINTER's is the pointee. Measured "
             "over the whole stdlib, 527 of its 528 sites are the first three "
             "and exactly one is the fourth (`std/os/env.mojo:85`, a "
             "`_CPointer[UInt8]`), so a refusal that described this as a load "
             "from the receiver's address would be false about almost every "
             "file it is reported against. A pointer receiver IS answered when "
             "its pointee is declared (see `dereference_lowering`); an enum, "
             "an iterator and a SIMD each need a field list or an element type "
             "this path does not have, and they are three separate "
             "representations rather than one",
    # Mojo's OWN name for the read `value` performs on a POINTER, and the
    # spelling the stdlib actually uses: `UnsafePointer.unsafe_load(i = 0)` IS
    # `p.value()` with the index defaulted to 0. It was in NEITHER table, so no
    # backend routed it to `dereference_lowering` and the call reached
    # `value_method_refusal`'s generic arm — which said "adding it to either
    # table would be a guess about what it means on 'int'" about a receiver the
    # source had annotated `Pointer[UInt8]`. Measured on both architectures:
    # `def read8(p: Pointer[UInt8]) -> Int: return Int(p.unsafe_load())` is
    # refused, and the receiver is reported as holding an `int`. 116 spellings
    # of it in the stdlib, every one on a pointer, so the tables and the corpus
    # disagreed about a NAME rather than about a construct.
    #
    # It belongs HERE and not in `DEREFERENCE_METHODS` because that table's arm
    # in `dereference_refusal` claims "is a load from the address the receiver
    # holds" even for a receiver that is NOT established to be a pointer — true
    # of `unsafe_value`, which is genuinely ambiguous, and FALSE of a
    # `def read_it(n: Int)` that calls it. This arm asks the receiver first and
    # then says the receiver is not a pointer, which is the specific missing
    # fact rather than a claim about an address that is not there.
    "unsafe_load": "is Mojo's name for the UNCHECKED READ through a pointer — "
                   "on a pointer the same operation `value()` is, at the same "
                   "declared width, which is why it is in this table and reaches "
                   "the same `dereference_lowering`. An ARGUMENT makes it a "
                   "different construct: it reads at an offset from the "
                   "receiver, and the address and the load are one decision "
                   "there of which only the load half is answered, so "
                   "`dereference_operands_refusal` names that rather than "
                   "reporting an argument count",
}

# The method names the DEREFERENCE arm owns, as a set rather than as the keys of
# `DEREFERENCE_METHODS`, because a backend asks "is this name one I should try to
# lower as a load?" and the answer has to be the SAME set the refusal table uses
# — two lists of two names is two places for them to come apart, and coming
# apart here is a backend that emits a load for a method the model refuses (or
# refuses one it can lower), which is a wrong answer rather than a diagnostic.
DEREFERENCE_METHOD_NAMES = frozenset(DEREFERENCE_METHODS)

# The names a backend must TRY to lower through `dereference_lowering` before it
# falls back to a refusal — `DEREFERENCE_METHODS` plus `value`.
#
# `value` belongs here and not in `DEREFERENCE_METHODS` because on a POINTER it
# is the same load and has to be ANSWERED, while on the three other receivers
# the census found it is not a load at all and saying so is the honest refusal.
# One intercept and one model decision, and the model's answer is the right one
# for all four receivers — which is what keeps a backend from having to know, in
# advance, which of the four a given `.value()` is.  A backend that routed
# `value` straight to a refusal would leave `std/os/env.mojo:85` refused, which
# is the one site the whole 54-file group is made of; a backend that routed it
# straight to a LOAD would turn 527 enum, iterator and SIMD sites into loads of
# whatever word the receiver holds.
DEREFERENCE_TRY_NAMES = DEREFERENCE_METHOD_NAMES | frozenset(IDENTITY_VALUE_METHODS)


def receiver_declared_is_pointer(fn, expr, decls: dict) -> bool | None:
    """True / False / None — is this receiver's DECLARED type a pointer type?

    The three-valued question, and the three answers are all needed.  `True`
    means a declaration here says the receiver is a `Pointer[…]`/`UnsafePointer
    […]`, so a dereference message is the true one.  `False` means a
    declaration says it is something else — `var status: ProcessState`,
    `var v: SIMD[DType.int, 4]` — so a message about loading from an address
    would be false about the file it is reported against, and the four-questions
    one is the true one.  `None` means no declaration, and then the honest
    reading is the SAME one as `False`: of 528 `value` sites in the corpus, 527
    are not pointers, so a receiver this path cannot classify is much more
    likely to be one of those than the single pointer site.

    Separate from `pointer_pointee` on purpose: that one answers "what does this
    pointer point at" and returns `None` for a non-pointer, which is not the
    same question as "is this a pointer" — a receiver whose pointee is an
    undeclared type parameter is a pointer with an unknown pointee, and a
    receiver declared `SIMD[…]` is not a pointer at all, and only the second
    question tells them apart.
    """
    ann, inner_is_pointer = _receiver_declared_annotation(fn, expr, decls)
    if ann is None:
        return None if not inner_is_pointer else True
    base = annotation_base_name(ann)
    if base is None:
        return None
    return base in POINTER_TYPE_CTORS


def _receiver_declared_annotation(fn, expr, decls: dict):
    """`(annotation_text, pointee_known)` — what THIS image declares for a receiver.

    One reader for the annotation, because two readers of it are two answers:
    `receiver_declared_is_pointer` above asks whether it names a pointer and
    `subscript_base_lowering` asks whether it names an INTEGER (an integer has
    no elements, so `n[0]` on one is a refusal rather than a container walk), and
    the second question has to be asked about the same text the first one was.
    Split out of the first rather than written twice beside it.

    `pointee_known` is the MemberExpr half's own answer: a field whose
    POINTEE this image established is a pointer even when its declared text is
    absent, because the candidate table answered about it directly.
    """
    ann = None
    if isinstance(expr, F.IdentExpr) and fn is not None:
        for p in (list(getattr(fn, "params", None) or [])):
            if isinstance(p, (tuple, list)) and p and p[0] == expr.name \
                    and len(p) > 1 and isinstance(p[1], str):
                ann = p[1]
                break
        if ann is None:
            for a, _rhs in _name_bindings(fn, expr.name):
                if a:
                    ann = a
                    break
    elif isinstance(expr, F.MemberExpr):
        inner, _why = _member_pointee(fn, expr, decls, {})
        ann = _member_declared_text(fn, expr, decls)
        return (ann, inner is not None)
    elif isinstance(expr, F.CallExpr):
        ann = _rhs_declared_text(fn, expr, decls, {})
    if not isinstance(ann, str) or not ann.strip():
        return (None, False)
    return (ann, False)


def _parameter_position(fn, name):
    """`fn`'s 0-based position of the parameter spelled `name`, or None.

    POSITION and not the name, because a parameter list can hold the same name
    twice (`def f(p, p)` is not source anyone writes, but a comprehension's
    `for` variable and a parameter can collide) and the CALL SITE counts
    arguments, not names. `_frame_argument_slots` in `formal/build.py` reads the
    same list for the same reason.
    """
    for i, p in enumerate(list(getattr(fn, "params", None) or [])):
        if (p[0] if isinstance(p, (tuple, list)) else p) == name:
            return i
    return None


def parameter_call_site_pointers(fn, name, decls: dict, functions: dict,
                                 structs_by_name: dict = None, seen=()):
    """Which of the two subscript conventions this image uses for one
    unannotated parameter of `fn` — `("load", width, signed, spellings)`,
    `("disagree", groups)` or `None`.

    `None` means "nothing to decide on" and the caller keeps the container
    reading: no call site in this image, only the callee's own recursion, or
    every site answering with the container walk itself. `groups` is
    `{(shape, width): [call spelling, …]}`.

    **What an unannotated parameter means is a property of the IMAGE and not of
    the callee, and this is the function that says so.** Until it existed the
    only thing that chose between the two conventions was whether the callee's
    own declaration spelled a pointer type, so the same function indexed memory
    when the author wrote the annotation and walked a `[count][e…]` blob when
    the author did not — and nothing anywhere said the answer had changed.
    Measured on both architectures, byte-identical, the annotation the only
    difference:

        def _fill_ann(p: Pointer[Int64]): p[1] = 42    # b[1] == 42
        def _fill_u(p):               p[1] = 43       # b[2] == 43

    a bias of one WHOLE ELEMENT, so `p[0]` reads `b[1]` and `p[-1]` reads
    neither word. `tools/formal_untyped_param_subscript_census.py` is the census
    that decided the cost of fixing it, and
    `test_formal_run.py`'s `both_arch_an_untyped_parameter_indexes_the_same_
    pointer_as_an_annotated_one` is the regression.

    **It is the CONVENTION that travels, not the pointee, and it has to be.**
    A blob and a raw buffer are the same value on this path — `POINTEES_REFUSED`
    says it in as many words: "a list is a BLOB on this path — a frame whose
    FIRST word is its count" — so `var b: Pointer[Int64] = malloc(…)` followed
    by `b[0] = count` names the identical type whether the buffer is a
    `[count][e…]` container or eight scratch words, and the caller's own
    subscript on that name cannot tell them apart either. Reading the POINTEE
    would therefore answer "memory" for both, and would silently move every
    container that reaches a helper through an untyped parameter one element
    towards its count word — the same silent-wrong-answer shape, pointed the
    other way. So what a call site contributes is the answer this module already
    gives for that name **in the caller**: `subscript_base_lowering(caller,
    arg, …)`, the same function, asked about the argument in the function that
    holds it. One value, one convention, wherever it is named — which is the
    invariant, and it is checkable because both sides are in this image.

    Ask it once more and the recursion is `f`'s parameter ← an argument in `g` ←
    `g`'s parameter ← an argument in `h`, so `seen` carries the chain and a
    pair already being derived contributes no observation rather than looping.

    **The cost on this corpus is zero, measured.**
    `tools/formal_untyped_param_subscript_census.py` asks THIS function over the
    459 `.mojo` files of this repository and the stdlib: 284 subscripts read an
    unannotated parameter and **not one of them has a call site whose argument
    this image reads as memory**, so every one of them keeps the container
    reading. The change can only alter a program whose call sites already say
    something, which is what makes it landable without a sweep.

    A call from ANOTHER image is not visible here, so an exported function's
    unannotated parameter keeps the container reading for a caller this build
    never read. Carrying a parameter's kind across the boundary is the dylib
    manifest's job, beside `frame_params`, the way a cross-image frame holder's
    is carried now, and it is the one half of this that is still open.
    """
    if fn is None or not isinstance(name, str) or not name:
        return None
    callee = getattr(fn, "name", None)
    if not callee or not functions:
        return None
    if declared_parameter_annotation(fn, name) is not None:
        return None                      # the declaration already decided
    position = _parameter_position(fn, name)
    if position is None:
        return None
    key = (id(fn), name)
    if key in seen:
        return None                      # a cycle, not a contradiction
    seen = tuple(seen) + (key,)
    groups: dict = {}
    for caller in (functions or {}).values():
        for site in iter_nodes(getattr(caller, "body", None) or []):
            if not isinstance(site, F.CallExpr) \
                    or not isinstance(site.func, F.IdentExpr) \
                    or site.func.name != callee:
                continue
            args = list(getattr(site, "args", None) or [])
            if position >= len(args):
                # A call that does not reach this position says nothing about
                # what the parameter holds, and reading the ones that do as
                # though they spoke for it would be a claim about a call that is
                # not there.
                continue
            arg = args[position]
            if caller is fn and isinstance(arg, F.IdentExpr) \
                    and arg.name == name:
                # RECURSION passing the parameter on to itself: the same word,
                # the same ignorance. Not evidence of a second convention, and
                # treating it as one would refuse every recursive helper whose
                # entry call is in another image.
                continue
            shape, width, signed, _why = subscript_base_lowering(
                caller, arg, decls, functions, structs_by_name or decls, seen)
            if shape is None:
                continue                  # that site says nothing about it
            groups.setdefault((shape, width, bool(signed)),
                              []).append(call_spelling(site))
    if len(groups) > 1:
        return ("disagree", groups)
    if not groups:
        return None
    (shape, width, signed), spellings = next(iter(groups.items()))
    if shape != "load":
        # The container walk at every site: the answer this module already
        # gives, reached the long way round.
        return None
    return ("load", width, signed, spellings)


def parameter_call_site_pointees(fn, name, decls: dict, functions: dict,
                                 structs_by_name: dict = None, seen=()):
    """What THIS IMAGE passes for one unannotated parameter of `fn` —
    `("pointee", base, spellings)`, `("disagree", groups)`, `("silent", rows)`,
    or None.

    `None` means "nothing to decide on", exactly as in
    `parameter_call_site_pointers`: no call site in this image, only the callee's
    own recursion, or no position to look at.  `groups` is `{pointee: [call
    spelling, …]}` and `rows` is `[(call spelling, why that site says
    nothing), …]`.

    **What a parameter POINTS AT is a property of the IMAGE and not of the
    callee, and this is the function that says so.**  The pointer value model
    recovers a pointee from a *declaration* (`pointee_of_type_text`), so a
    parameter nothing declares — `def r8(p): return Int(p.value())`, which is
    how the stdlib spells a helper on this path — had no pointee at all, and
    `p.value()` was refused with the four-questions sentence on BOTH
    architectures.  Within one image every call site of the callee is in the
    same function tree, so the fact the callee cannot see IS derivable, and the
    rule is the one `parameter_call_site_pointers` already states for the
    SUBSCRIPT spelling of the same question: ask the caller what it already
    establishes for that argument, through the SAME reader
    (`pointer_pointee`), and take the answer only when there is exactly one.

    **All of them have to answer, which is where the other function's blob
    hazard is refused rather than inherited.**  `parameter_call_site_pointers`
    records a site that answers `None` as saying *nothing*, because there its
    `None` is the container walk and the other sites' answers are memory: a
    container reaching a helper through an untyped parameter and a raw buffer
    reaching it are the same word, and mixing them moves every such subscript a
    whole element.  Here a site that says nothing is a site whose argument this
    image cannot place — a blob is exactly that (`POINTEES_REFUSED`: "a list is
    a BLOB on this path — a frame whose FIRST word is its count"), and reading
    eight bytes at a blob's frame base reads its COUNT.  So one silent site
    makes the whole parameter undecided, and it is reported as its own state
    rather than dropped, because the reader standing at that call is the one who
    can fix it and the message has to be able to name it.

    A call from ANOTHER image is not visible here, so an exported function's
    unannotated parameter keeps the refusal — the same open half
    `parameter_call_site_pointers` names, and the same one: carrying a
    parameter's kind across a dylib edge is the manifest's job, beside
    `frame_params`.
    """
    if fn is None or not isinstance(name, str) or not name:
        return None
    callee = getattr(fn, "name", None)
    if not callee or not functions:
        return None
    if declared_parameter_annotation(fn, name) is not None:
        return None                      # the declaration already decided
    position = _parameter_position(fn, name)
    if position is None:
        return None
    key = (id(fn), name)
    if key in seen:
        return None                      # a cycle, not a contradiction
    seen = tuple(seen) + (key,)
    groups: dict = {}
    silent: list = []
    for caller in (functions or {}).values():
        for site in iter_nodes(getattr(caller, "body", None) or []):
            if not isinstance(site, F.CallExpr) \
                    or not isinstance(site.func, F.IdentExpr) \
                    or site.func.name != callee:
                continue
            args = list(getattr(site, "args", None) or [])
            if position >= len(args):
                # A call that does not reach this position says nothing about
                # what the parameter holds, for `parameter_call_site_pointers`'
                # reason: reading it as though it spoke for the position would
                # be a claim about a call that is not there.
                continue
            arg = args[position]
            if caller is fn and isinstance(arg, F.IdentExpr) \
                    and arg.name == name:
                # RECURSION passing the parameter on to itself: the same word
                # and the same ignorance, not a second pointee.
                continue
            inner, why = pointer_pointee(caller, arg, decls, functions, seen)
            if inner is None:
                silent.append((call_spelling(site), why))
                continue
            groups.setdefault(inner, []).append(call_spelling(site))
    if len(groups) > 1:
        return ("disagree", groups)
    if silent:
        # A site this image cannot read VETOES, even beside sites it can: the
        # parameter is a pointer where the reader can see one and an unplaced
        # word at the site it cannot, and a width derived from the sites that do
        # answer is a guess about that one.  The message names it, because the
        # reader standing at that call is the one who can fix it.
        return ("silent", (silent, groups))
    if not groups:
        return None
    base, spellings = next(iter(groups.items()))
    return ("pointee", base, spellings)


def parameter_pointee_from_call_sites(fn, name, decls: dict, functions: dict,
                                      seen=()):
    """`(pointee_base, why)` for a PARAMETER the image agrees about, or
    `(None, None)` for "nothing to decide on" and `(None, why)` for a refusal.

    The `_name_pointee` hook, and it is three lines over
    `parameter_call_site_pointees` because the four answers are four different
    sentences.  A pointee this returns is a base name and nothing else: the
    width, the signedness, a float, a blob and a struct pointee are
    `dereference_lowering`'s questions and it asks them of this answer exactly
    as it asks them of a declared one, so the two routes cannot reach different
    widths for the same bytes.
    """
    derived = parameter_call_site_pointees(fn, name, decls, functions, decls,
                                           seen)
    if derived is None:
        return (None, None)
    callee = getattr(fn, "name", None)
    kind = derived[0]
    if kind == "pointee":
        base, spellings = derived[1], derived[2]
        return (base, f"nothing in {callee}()'s own body declares what {name!r} "
                      f"points at, and every call site of {callee}() in this "
                      f"image passes an argument this module establishes as a "
                      f"pointer to {base} ({'; '.join(spellings)}) — one "
                      f"parameter has one pointee, so the load is at that "
                      f"width")
    if kind == "disagree":
        sides = [f"a pointer to {pointee} at {' and '.join(spellings)}"
                 for pointee, spellings in sorted(derived[1].items())]
        return (None, f"{callee}()'s parameter {name!r} is read through, and "
                      f"this image reaches it with two different pointees — "
                      f"{' and '.join(sides)}. The load's WIDTH is chosen per "
                      f"parameter, so `p.value()` would be compiled at one "
                      f"width and reached at the other at one of these calls, "
                      f"and the difference is a plausible number rather than a "
                      f"crash. Give {name!r} one pointee at every call site, "
                      f"or declare it — a `Pointer[…]` at the declaration "
                      f"settles it without changing a single call")
    rows, groups = derived[1]
    sites = "; ".join(f"{spelling} — {why}" for spelling, why in rows)
    if groups:
        sites += ("; and the site(s) this image CAN read pass "
                  + " or ".join(
                      f"{spelling} (a pointer to {pointee})"
                      for pointee, spellings in sorted(groups.items())
                      for spelling in spellings))
    return (None, f"{callee}()'s parameter {name!r} is read through, and this "
                  f"image cannot say what one of its call sites passes: "
                  f"{sites}. A parameter that is a pointer at the sites this "
                  f"image can read and something else at a site it cannot is a "
                  f"word of no particular width at that site, so a load sized "
                  f"from the others would be a guess about this one. Declare "
                  f"{name!r} a pointer type, or make every call site pass one")


def declared_parameter_annotation(fn, name):
    """The annotation `fn`'s OWN parameter list gives `name`, or None.

    Narrow on purpose, and narrow in the direction that matters: this is the
    declaration that `parameter_call_site_pointers` stands down for, so it reads
    the parameter list and nothing else. A `var x: T` in the body is a
    different question (`_only_declared`) and a local bound from a caller is a
    third.
    """
    for p in (list(getattr(fn, "params", None) or [])):
        if isinstance(p, (tuple, list)) and p and p[0] == name \
                and len(p) > 1 and isinstance(p[1], str) and p[1].strip():
            return p[1]
    return None


def call_spelling(call) -> str:
    """`f(2, 3)` — a call as the source spells it, for a refusal that quotes it.

    The callee goes through `expr_spelling` and not `call.func.name`, because a
    call whose name has to be looked through — `f[1](2, 3)` — has no `.name` on
    its func node, and a diagnostic that raises while quoting the call sites it
    exists to quote turns the safety check into the crash.
    """
    parts = [expr_spelling(a) for a in (call.args or [])]
    for k, v in (call.kwargs or []):
        parts.append(f"{k}={expr_spelling(v)}")
    return f"{expr_spelling(call.func)}({', '.join(parts)})"


def parameter_pointee_disagreement_refusal(callee, name, groups) -> str:
    """One parameter reached with two SUBSCRIPT CONVENTIONS.

    `frame_holder_disagreement_refusal` one layer down and the same rule — a
    parameter's being an X is a property of the WHOLE image, not of one call
    site — so the wording, the "phrased from BOTH sides" discipline and the
    reason for refusing rather than picking are all that function's. Both sides
    are named, because either call site can be the one the reader is standing at
    and a message naming the wrong one of the pair sends them to a call that is
    fine.

    `groups` is `{(shape, width, signed): [call spelling, …]}`. The container
    walk is `blob`; a memory read is `load` at a width.

    The measured wrong answers this replaces, both on both architectures and both
    a whole ELEMENT out rather than wild:

        def _fill(p) -> int:  p[0] = 43        # b + 8  (blob walk)
        var b: Pointer[Int64] = malloc(16)
        b[0] = 3                                # b + 0  (declared pointer)
        _fill(b)                                # b[1] == 43, not b[0]

    and with two widths rather than two conventions the difference is a SCALE:
    `Pointer[Int64]` gives `p + i*8` and `Pointer[UInt8]` gives `p + i*1`, and one
    callee cannot emit both.
    """
    sides = []
    for key, spellings in sorted(groups.items(), key=lambda kv: kv[0]):
        shape, width = key[0], key[1]
        what = ("a CONTAINER walk — element i at `base + 8 + i*8`, bounds-checked "
                "against whatever word is at offset 0"
                if shape != "load" else
                f"a memory read — element i at `base + i*{width}`, no check")
        sides.append(f"{what} at {' and '.join(spellings)}")
    return (f"{callee}()'s parameter {name!r} is subscripted, and this image "
            f"reaches it two ways that mean different addresses — "
            f"{' and '.join(sides)}. One parameter, two kinds of value: the "
            f"subscript convention is chosen per parameter, so `{name}[i]` would "
            f"be compiled as one reading and reached as the other at one of "
            f"these calls, and the offset between them is a whole ELEMENT rather "
            f"than a wild address — so the wrong answer reads like a plausible "
            f"one. Measured on both architectures: an unannotated parameter "
            f"reached with a `Pointer[Int64]` wrote `b[2]` where the annotated "
            f"spelling wrote `b[1]`, and the container walk's bounds check "
            f"trapped in a raw exit(1) syscall that does not flush stdio, so "
            f"the caller lost every line it had printed. Give {name!r} one kind "
            f"of value at every call site, or declare it — `Pointer[Int64]` at "
            f"the declaration makes the reading unambiguous without changing a "
            f"single call")


def subscript_base_lowering(fn, obj, decls: dict, functions: dict = None,
                            structs_by_name: dict = None, seen=(),
                            element_kind_ok: bool = False):
    """`(shape, width, signed, why)` — `(None, None, None, why)` to refuse.

    WHAT `obj[i]` READS, for a base that is not a string and not a dict key —
    the single decision `formal/arm64_codegen.py:_emit_subscript_addr` and its
    x86-64 twin used to each get wrong in the same way.

    Two spellings of one question, and only one of them was routed. `p.value()`
    asked `dereference_lowering` and got a load at the pointee's width, which is
    right; `p[i]` asked nothing and fell through to the BLOB walk, whose first
    word of the base is a COUNT. For a `Pointer[UInt8]` that count is the byte
    at offset 0, the bounds check then passes or fails on it, and the element
    address is `base + 8 + 8*count`:

        byteat("ab")   -1879048144   0x9002_2E68 — "ab" plus whatever follows
                                         it in __TEXT, read as a little-endian
                                         word. `0x68` is `h`; the answer is 97.
        malloc(64)     exit 1, no output — the count is 0, the check fails, and
                                         the Darwin exit(1) has no message.

    Both are a silent wrong answer, and one spelling of them is silent in a way
    nothing downstream can detect. See
    FORMAL_subscript_of_a_pointer_reads_a_blob_count.

    The three shapes, and the same arity for all of them so the caller reads one
    unpack:

      * `("load", width, signed, why)` — the base is a pointer whose pointee this
        module established a width for. The caller emits `base + i*width` and a
        load of `width` bytes, which is the same instruction pair
        `_emit_dereference` emits for `p.value()` — the SAME width rule, from
        the SAME reader, so the two spellings cannot disagree about what a
        `Pointer[UInt8]` holds.
      * `("blob", 8, False, None)` — nothing here says the base is a pointer, so the
        container reading stands, and a container element is a word. This is the
        answer for a list/tuple/dict base and for the many bases whose kind no
        declaration in this image establishes.
      * `(None, None, None, why)` — the base is DECLARED a pointer and the
        pointee is not established, or it is established but has no width. A
        bounds check against whatever word is at offset 0 of an address is never
        the answer, so this is a diagnostic rather than a number.

## What an unannotated parameter means — the question this function used to
    ## leave open, and the answer it now derives

    Until this was decided, an unannotated parameter meant "blob" by default,
    and the ONLY thing that chose between the two conventions was whether the
    callee's own declaration spelled a pointer type. So the same callee, handed
    the same pointer, indexed memory or walked a `[count][e…]` blob depending on
    a line of the DECLARATION, and nothing anywhere said the answer had changed.
    Measured on both architectures, byte-identical, with the annotation the only
    difference:

        def _fill_ann(p: Pointer[Int64]): p[1] = 42   ->  b[1] == 42
        def _fill_u(p):                p[1] = 43      ->  b[2] == 43

    The offset is a whole ELEMENT, so the wrong answer reads like a plausible
    one: `p[0]` is `b[1]`, and `p[-1]` is neither. The blob walk also emits the
    count check, so storing into a buffer whose count word was never written
    traps in a raw `exit(1)` syscall — which does not flush stdio, so a program
    that printed before the call loses every buffered line and looks like a
    CALLER-side frame bug.

    **The answer is now derived from the image, and it is the same fact either
    way**: `parameter_call_site_pointers` asks what every call site of the
    callee in this image passes, with the real `pointer_pointee` and the caller
    as its `fn`. One pointee agreed on → the pointer reading, at the same width
    the annotated spelling would have given. Call sites that do not agree →
    `parameter_pointee_disagreement_refusal`, which is
    `frame_holder_disagreement_refusal` one layer down and the same rule: a
    parameter's being an X is a property of the whole image, and either call
    site can be the one the reader is standing at, so both are named.

    What it costs, measured with `tools/formal_untyped_param_subscript_census.py`
    over the 459 `.mojo` files of this repository and the stdlib: **nothing**.
    284 subscripts read an unannotated parameter and not one of them has a call
    site that passes a pointer-typed argument, so every one of them keeps the
    container reading. A callee no call site in this image reaches — an exported
    host-module function, a dylib's own entry — keeps it too, which is where
    the CROSS-image half lives: carrying a parameter's kind in the dylib manifest
    beside `frame_params`, the way a cross-image frame holder's is carried now.

    ## What is deliberately NOT refused: a base whose kind nothing establishes

    The blob reading is a guess there, and it is a guess the corpus depends on —
    "refuse every unestablished base" would refuse every `p[i]` where `p` came
    from a caller whose argument this image cannot place. The census above is
    the number that decides it, and it is why the fallback stays.
    """
    how, why = dereference_lowering(fn, obj, decls, functions, structs_by_name,
                                    index_scaled=True)
    if how is not None:
        _shape, width, signed = how
        if _shape == "identity":
            return (None, None, None,
                    f"the base is a NULLABLE POINTER, so `{spelled(obj)}[i]` is "
                    f"the element AT the pointer and this path would have to "
                    f"load it at the pointee's width from an address that is "
                    f"either a live `char *` or 0 — there is no bounds check "
                    f"against the pointee here and the source's own "
                    f"`if not p:` is what establishes which. {_sentence(why)} "
                    f"Read through `p.value()[i]` once the unwrap is written "
                    f"out, which is the same program with the check spelled out")
        if _shape == "float":
            if element_kind_ok:
                # The caller has established the ELEMENT's kind: a READ, whose
                # kind `pointee_kind_of` answers FLOAT for a subscript exactly
                # as it does for `p.value()`, or a STORE whose value's kind
                # `pointer_store_lowering` has checked against the pointee. The
                # eight bytes are the element's own word either way, so this is
                # the same width the dereference loads at.
                return ("load", 8, False, why)
            return (None, None, None,
                    f"`{spelled(obj)}[i]` reads an element of a FLOAT pointee, "
                    f"and an element of this kind is answered only for a read "
                    f"or for a plain store of a double: an augmented assignment "
                    f"combines the element with integer arithmetic, and a `del` "
                    f"or a tuple-unpack target has no value whose kind this path "
                    f"can check as a double, so the eight bytes would be read or "
                    f"written as an integer. "
                    f"Read the element through `{spelled(obj)}[i]` into a local "
                    f"and combine it there, or read `{spelled(obj)}.value()` and "
                    f"index the result, which is the same address with the kind "
                    f"the pointee declared")
        if _shape != "load":
            return (None, None, None,
                    f"the base is a pointer to a STRUCT, and a struct's value "
                    f"on this path is the address of its frame, so `{spelled(obj)}"
                    f"[i]` would need to know the field at offset i*8 — a layout "
                    f"no declaration in this image states. {_sentence(why)}")
        return ("load", width, signed, why)
    if receiver_declared_is_pointer(fn, obj, decls) is True:
        return (None, None, None,
                f"`{spelled(obj)}[i]` reads through a POINTER, and the width of "
                f"the read is the pointee's — {_sentence(why)} Refused rather "
                f"than read as a container: a container base is "
                f"`[count][element]…`, so the count would come from offset 0 of "
                f"the address itself, the bounds check would be against whatever "
                f"byte is there, and the element address would be `base + 8 + "
                f"8*count`. Measured, on a pointer to a string: -1879048144, "
                f"which is the first four characters of the string read as a "
                f"little-endian word, and 97 is the byte. Declaring the pointee "
                f"— `var p: Pointer[UInt8]`, or a parameter annotated "
                f"`Pointer[Int32]` — is what makes it answerable")
    # The base's own DECLARED type says it is a number. An integer has no
    # elements, so the container reading is not a guess here and no annotation a
    # reader could add would change it. It is the one shape the corpus does not
    # reach (measured: 0 of the 198 subscripts whose base a declaration calls a
    # non-pointer declare an integer — they are `SIMD[…]`, `Span`, `Some`,
    # `Tuple`, `List[Int]`, all real containers), which is why the rule asks
    # about `INT_TYPE_CTORS` alone and not about "not a pointer".
    #
    # The MESSAGE is `non_container_element_refusal`',s, because this is that
    # construct: a local bound to an integer is refused by the emitters from
    # `own_shape_kind` before this line is reached, and a PARAMETER declared
    # `Int` — which `own_shape_kind` has nothing to say about, by construction —
    # would otherwise get a second diagnostic for the same mistake, differing
    # only in which line of the source they blame.
    ann, _inner_pointer = _receiver_declared_annotation(fn, obj, decls)
    base = annotation_base_name(ann) if ann else None
    if base in INT_TYPE_CTORS:
        return (None, None, None, non_container_element_refusal(
            "a subscript", spelled(obj),
            getattr(fn, "name", None) or "<module>",
            f"declared {ann!r}, which is an integer"))
    # An UNANNOTATED PARAMETER, whose kind the callee cannot see and the IMAGE
    # can: every call site of `fn` in this image is in `functions`, so the
    # pointer reading is derived from what is actually passed rather than from
    # whether the author remembered an annotation. `parameter_call_site_pointers`
    # is where the derivation and the measurement live; it returns None — and so
    # this arm falls through to the container reading — whenever the call sites
    # say nothing, which on this corpus is every one of them.
    if isinstance(obj, F.IdentExpr):
        derived = parameter_call_site_pointers(fn, obj.name, decls, functions,
                                               structs_by_name)
        if derived is not None:
            if derived[0] == "disagree":
                return (None, None, None,
                        parameter_pointee_disagreement_refusal(
                            getattr(fn, "name", "?") or "this function",
                            obj.name, derived[1]))
            _shape, width, signed, sites = derived
            return ("load", width, signed,
                    f"this image reads its argument as MEMORY at "
                    f"{' and '.join(sites)} — a declared pointer, subscripted at "
                    f"the pointee's width — so `{obj.name}[i]` is "
                    f"`{obj.name} + i*{width}` here too: one value, one "
                    f"convention, wherever the name is written. Measured: with "
                    f"the annotation the callee got this reading and without it "
                    f"the container walk, a bias of one whole ELEMENT")
    return ("blob", 8, False, None)


def subscript_container_name(obj, kind) -> str:
    """The word a diagnostic calls the container a subscript went out of range on.

    One reader for both backends and for the one message they share, because a
    subscript that says `list` on one architecture and `bytearray` on the other
    is two sentences for one limit — the reason `dict_store_overflow_message`
    and `list_append_overflow_message` live here rather than in either emitter.

    It answers from the KIND where the kind says, and from the NODE where it
    does not. A byte blob is a `bytearray` and `is_byte_blob_kind` is the one
    thing that says so; a tuple LITERAL is a `list`-prefixed blob on this path,
    so nothing in its kind distinguishes it from a list and the source is the
    only thing left that does. Everything else is a `list`, which is the word
    CPython uses for a blob of that shape and the word this file already uses
    for one (`subscript_base_lowering`'s "list/tuple/dict base").
    """
    if is_byte_blob_kind(kind):
        return "bytearray"
    if isinstance(obj, F.TupleExpr):
        return "tuple"
    return "list"


def subscript_out_of_range_message(sub: str, container: str) -> str:
    """The ONE text an out-of-range `obj[i]` writes to fd 2 before it stops the
    program — for BOTH backends, because two architectures printing two
    different sentences for one limit is how a reader ends up looking for a
    construct one of them invented.

    **What is missing here was never the CHECK.** Both emitters load the blob's
    own count word, add it to a negative index (Python's rule, so `-1` is the
    last element), and stop unless `count > index` UNSIGNED — which is what
    covers "still negative after the fold". Measured on both architectures with
    `formal/memcheck/list_subscript_past_end.mojo`:

        ./a.arm64 ; echo $?          10 / 30 / exit 1
        2>&1 1>/dev/null | wc -c    0

    Two in-range lines, then exit 1 with **nothing on either stream**. That is
    the worst of the three answers this path can give: not a wrong number a
    reader can compare, not a named refusal they can act on, but silence — and
    it is invisible to a stdout/exit-status oracle by construction, which is why
    the memcheck sweep reports the row `MATCH`. Every other bounded stop on this
    path (`list.append`'s capacity, a dict store's, a blob growth guard's, an
    `int()` parse, an arithmetic overflow) goes through `_emit_overflow_diagnostic`
    and says which bound it hit; the subscript's `oob_label` was the one that
    did not.

    **Why a message and not a compile-time refusal**, which is the question
    `list_append_overflow_message` answers for the append case and the same
    answer: the index is a run-time value. The bound is too — it is the
    container's element count, read from its header word — so no pass over the
    source can say the subscript is in range. `a[i]` where `i` is 1 on a
    three-element list is fine and `a[i]` where `i` is 9 is not, and they are the
    same line.

    **The index and the count are NOT spelled into the text**, and the reason is
    the one `_emit_overflow_diagnostic`'s own docstring records: it takes a
    CONSTANT, because a libc call is an unfollowable call and a proved function
    may contain at most one of those (`arm64_proof_gen.py::_unfollowable_calls`).
    Formatting a number at run time would spend that budget on a trap block — and
    it would spend it asymmetrically, since the x86-64 emitter's copy of the
    helper calls the C library's `write` and the arm64 one is a raw `SYS_write`
    for exactly this reason. So the message names the SUBSCRIPT as the source
    spelled it and the container as a word, and the reader is told the two facts
    that decide it: the negative-index rule, and where the bound lives.

    Both repairs in the text are measured, not reasoned about: `len(a)` is the
    count word and reads it, so a guard is a real bound; and a `for … in` walk
    over a blob is bounded by the same count, so it cannot go out of range at
    all. Neither changes the program's answer for the indices that were already
    in range, which is why adding the diagnostic cannot move a verdict.
    """
    return (f"formal: `{sub}` is out of range for this {container}: the "
            f"subscript asked for an element at or past the end of what the "
            f"{container} holds, or below `-len(...)`, and the bounds check "
            f"fired. A negative index is counted from the end first (`-1` is "
            f"the last element), and the bound that rejected the index is the "
            f"{container}'s own element count, read from its header word at RUN "
            f"time — which is why this is a message and not a refusal: no pass "
            f"over the source can decide an index it cannot read. CPython "
            f"answers the same program with `IndexError: {container} index out "
            f"of range` on stderr and stops there. Two spellings compute the "
            f"same program and cannot go out of range: guard the index against "
            f"`len(...)` before the subscript, or read the element with a "
            f"`for … in` walk, which is bounded by the count rather than by the "
            f"index.")


def dereference_refusal(method: str, why: str, is_pointer_receiver) -> str:
    """The refusal text for a receiver `dereference_lowering` would not answer.

    One message, chosen by WHICH question the receiver is, and chosen in the
    model so the two backends cannot describe one construct differently.  The
    width paragraph is shared because it is the reason the refusal exists: with
    a declared pointee the load is emitted at the pointee's width, and without
    one the only width available is 8 bytes, which over-reads a 1-byte pointee
    by seven and faults at a page edge.
    """
    if is_pointer_receiver or method in DEREFERENCE_METHODS:
        head = (f"{{dotted}}() is a load from the address the receiver holds, "
                f"and the load's width is the pointee's — {_sentence(why)}")
    else:
        about = (IDENTITY_VALUE_METHODS.get(method)
                 or DEREFERENCE_METHODS.get(method)
                 or "is a method this path cannot answer")
        head = (f"{{dotted}}() {_sentence(about)} The receiver is not "
                f"established to be a pointer here, and the answer a pointer "
                f"would give is a load whose width the pointee decides: "
                f"{_sentence(why)}")
    return (head + " Refused rather than emitted at the only width this path "
            "could choose without one, which is 8 bytes: that over-reads a "
            "1-byte pointee by seven bytes, returns a plausible number assembled "
            "from whatever follows it, and faults outright at a page edge. "
            "Declaring the pointee — `var p: Pointer[UInt8]`, a parameter "
            "annotated `Pointer[Int32]`, or a pointer-valued "
            "`external_call[\"sym\", Pointer[T]]` — is what makes it answerable")


def _sentence(text) -> str:
    """`text`, with a full stop if it lacks one.

    The tables hold fragments, because a table entry is a clause and the
    surrounding sentence is decided by the caller.  Joining two of them without
    this produces `…rather than one The receiver is not…`, and a refusal that
    runs two sentences together reads as one confused one.
    """
    text = (text or "").strip()
    return text if (not text or text[-1] in ".!?:") else text + "."


def dereference_operands_refusal(dotted: str, method: str, args) -> str | None:
    """A dereference call carrying operands this arm does not take, or None.

    `p.value()` takes none and `p[i]` carries the offset in the SUBSCRIPT, so a
    method call that brings its own is refused — but the words have to say which
    construct it is, because for `unsafe_load` the offset argument is the
    ORDINARY spelling (`unsafe_load(i = 0)` is the declaration) and a bare "takes
    no arguments" would send a reader who wrote the ordinary form looking for a
    syntax error that is not there.

    Shared, and for the reason every other refusal in this file is: the two
    backends each spelled this one from a private f-string, so the machines could
    describe one construct differently.
    """
    if not args:
        return None
    spelled = ", ".join(dotted_receiver(a) for a in args)
    if method in DEREFERENCE_OFFSET_METHOD_NAMES and len(args) == 1:
        recv = dotted.rsplit(".", 1)[0]
        return (f"{dotted}({spelled}) reads at an OFFSET from the receiver, and "
                f"this arm answers with the value AT the receiver's own address: "
                f"the address and the load are one decision in "
                f"`dereference_lowering`, and only the load half of it is "
                f"answered so far. `{recv}[{spelled}]` is the same program with "
                f"the offset in the subscript, which is the spelling both "
                f"backends lower today")
    return (f"{dotted}({spelled}) takes no arguments on this path: the "
            f"dereference this is answers with the value AT the receiver, and an "
            f"argument is not part of it")




# ── the STORE side of the pointer value model ──────────────────────────────
#
# `p.value() = v` is the mirror of `p.value()`, and it is here for the mirror's
# reason: the store's WIDTH is a property of the program and not of the
# architecture, so the two backends ask one function, exactly as they ask
# `dereference_lowering` for the load. A per-backend rule here would be two
# answers to "what does `p.value() = v` mean", and the two answers would be a
# `strb` on one machine and a `str x` on the other over the same bytes.
#
# WHY IT IS A SEPARATE FUNCTION AND NOT A FLAG ON `dereference_lowering`: the
# load's answer is "the WORD at the address", and the store's is "the BYTES at
# the address", and the two differ on the two cases that matter.  A NULLABLE
# POINTER's `.value()` is the UNWRAP for a load — the receiver already IS the
# answer, and reading memory there would answer with the FIRST BYTE of the
# pointee (`model.nullable_pointer_unwrap`, and the SIGSEGV it replaced) — while
# the STORE through the same spelling writes at the address the word holds, so
# the unwrap costs nothing and the store is answerable.  And a STRUCT pointee is
# the IDENTITY for a load, which is refused for a reason that has nothing to do
# with the address; for a store it is refused for a better one, which is that
# there is nothing AT the address to store into.  Those are two different
# refusals, and one flag would have had to invent which reader was asking.
#
# THE ONE RULE, and it is the same one `subscript_base_lowering` already applies
# to `p[i] = v`: **the store is the pointee's width, and it TRUNCATES.**  Both
# halves of that are established rather than chosen, and the alternative — a
# refusal whenever the value's width exceeds the pointee's — is not a stricter
# version of the same rule, it is a different one, and it is the one the
# SUBSCRIPT spelling would then disagree with:
#
#   * `p[i] = v` over a `Pointer[UInt8]` emits `strb` today, on both backends,
#     and has done since the byte store was added (measured: a full 64-bit store
#     into a one-byte element overwrote the seven bytes after it, which is a
#     silent corruption of a `malloc`'d buffer rather than anything that traps).
#     Refusing `p.value() = v` for the same value on the same pointee would make
#     the two spellings of one store answer differently, which is the exact
#     failure `subscript_base_lowering` was written to end.
#   * Truncation is C's. `*(UInt8 *)p = v` stores the low byte and discards the
#     rest, and a store NARROWER than its value never invents a bit and never
#     writes outside the pointee's extent — so it cannot be a wrong answer in
#     the way an unestablished WIDTH is.  What the load side refuses is a store
#     at a width nothing established, and the width here is established by the
#     same declaration the load reads.
#   * The load and the store must AGREE, and they do by construction: both read
#     `POINTEE_WIDTHS`, so `p.value() = 65; printf("%d", p.value())` on a
#     `Pointer[UInt8]` is 65 on both machines, which is the round trip
#     `test_formal_time.py`'s `structroute` group now asserts.
#
# WHAT IS REFUSED is what the LOAD refuses, and for the load's reasons, worded
# from the same argument so the two do not drift: a receiver with no recorded
# pointee, a pointee with no established width, a FLOAT / BLOB / wide-SIMD /
# STRUCT pointee, and an unscaled integer offset on a pointee wider than one byte
# (`_offset_scale`, the same reader, because the address and the store have to
# agree about the element size exactly as the address and the load do).
# `test_returned_frame_layout.py` and the sweep's refusal census keep the two
# backends on one wording.


def deref_receiver(expr):
    """The RECEIVER of a dereference EXPRESSION — `p` in `p.value()` — or None.

    One recogniser for both intercepts, because they are the same question asked
    of the same node: `p.value() = v` is a STORE through a pointee and
    `return p.value()` is a LOAD, and the spelling that decides it is
    `DEREFERENCE_TRY_NAMES` — the model's own table, read here rather than from
    a list spelled out again, because a third copy is a third thing to keep in
    step and the cost of it being wrong is a program refused for a spelling the
    other intercept accepts.

    `None` means "this is not a dereference", which is the common case: a plain
    name, a subscript, a field, an arithmetic expression.
    """
    if not isinstance(expr, F.CallExpr) or expr.args or expr.kwargs:
        return None
    func = getattr(expr, "func", None)
    if isinstance(func, F.MemberExpr) and func.member in DEREFERENCE_TRY_NAMES:
        return func.obj
    return None


def pointee_kind_of(fn, expr, decls: dict, functions: dict = None,
                    int_names=(), string_names=(), float_names=()):
    """The KIND a POINTER DEREFERENCE expression yields, or `None`.

    The hook `ValueKinds` asks so a pointee's kind flows into the dereference
    rather than being decided by the context around it.  This is the one reader
    of that answer for both backends, for the reason `pointer_pointee` is one
    reader of the WIDTH: two readers of "what does this dereference yield" is
    two kinds, and a disagreement between the architectures over a `double`
    would be `FCVTZS` on one and a bit move on the other.

    The two dereference SPELLINGS the load half answers — `p.value()`/
    `p.unsafe_value()`/`p.unsafe_load()` (via `deref_receiver`, the same
    recogniser the store half uses) and `p[i]` (a subscript) — are both here,
    and the subscript is not optional once a `Float64` pointee has a width:
    `subscript_base_lowering` reads the same `POINTEE_WIDTHS`, so leaving `p[i]`
    out would emit the load for it while `Int(p[i])` still bit-moved.

    **`None` for every kind but an integer or a double**, and that scoping is
    deliberate rather than an omission.  An integer pointee's kind was already
    the default (`INT_KIND`), so returning it changes nothing and keeps the
    answer general; a float pointee is the whole reason the hook exists.  A
    STRUCT pointee's dereference is the frame ADDRESS, which the frame tables
    own (`pointer_frame_pointee`) and which every `_expr_str_kind` consumer
    already reads as a word — returning `FRAME_KIND` here would reclassify a
    shape this hook is not about, on the strength of a declaration rather than
    of the dereference.  A blob/string/type pointee does not reach here at all
    (`dereference_lowering` refuses it), so `None` is the conservative direction
    for everything the hook does not claim.
    """
    recv = deref_receiver(expr)
    if recv is None and isinstance(expr, F.SubscriptExpr):
        recv = expr.obj
    if recv is None:
        return None
    inner, _why = pointer_pointee(fn, recv, decls, functions)
    if inner is None:
        return None
    kind = declared_type_kind(inner, int_names, string_names, decls,
                              float_names=float_names)
    return kind if kind in (INT_KIND, FLOAT_KIND) else None


def pointer_store_receiver(target):
    """The ADDRESS a store through a dereference writes to, or `None`.

    `p.value() = v` and `p.unsafe_value() = v`, and nothing else — the store
    half of `deref_receiver`, which is the same recogniser over the same node and
    is where the reason for having one lives.
    """
    return deref_receiver(target)


def pointer_store_lowering(fn, target, decls: dict, functions: dict = None,
                           structs_by_name: dict = None, value=None,
                           class_of=None):
    """`("store", width, signed)` | `None` — with a refusal.  The store mirror
    of `dereference_lowering`, and asked for the same reason.

    The three-tuple shape is the load's shape on purpose, for the reason
    `dereference_lowering` keeps it: every reader unpacks `shape, width, signed`
    and the shape is what tells a store from an identity.  `signed` is the
    POINTEE's declared signedness and is carried for that symmetry only — a
    store has no result to sign-extend, and the width is what it truncates to.

    **`value` and `class_of` are the KIND CHECK, and they are the third consumer
    that `POINTEES_REFUSED`'s `Float64` row was standing in front of.** The row
    was deleted when the pointee's kind started flowing out of a dereference
    (`pointee_kind`), and deleting it opened a hole the document that asked for
    the deletion did not name: with a `Float64` pointee no longer refused here,
    `p.value() = 1` stores the INTEGER 1 into a slot a double is read back from
    (measured, both architectures, green build, exit 0 — reading it back gives
    4.9e-324), and `p.value() = 2.5` into a `Pointer[Int64]` stores the double's
    BIT PATTERN as an integer. Both are silent wrong answers and both were
    refusals a moment before.

    So the rule is the same one `call_argument_kind_refusal` and
    `printf_kind_conversion_refusal` state at the other two boundaries — the
    stored value's KIND must agree with the pointee's — asked with the SAME
    three-way evidence (`printf_arg_float_evidence`, which each backend already
    hands its `printf` refusal). For an INTEGER pointee the direction is
    permissive: **None never refuses**, so an unannotated parameter stored into
    an integer slot is stored as before. For a DOUBLE pointee it is not: an
    unestablished value there is refused by name, because its word may be an
    integer's bits and nothing in the source rules that out (see
    `pointer_store_kind_disagreement`).
    """
    # A SUBSCRIPT target (`p[i] = v`) is the same store at `base + i*width`, and
    # the caller scales the index it supplies — `dereference_lowering`'s
    # `index_scaled`, so the two readers ask the same width question about the
    # same address. Only the base is judged here.
    if isinstance(target, F.SubscriptExpr):
        obj, index_scaled = target.obj, True
    else:
        obj, index_scaled = pointer_store_receiver(target), False
    inner, why = pointer_pointee(fn, obj, decls, functions)
    if inner is None:
        return (None, why)
    if class_of is not None and value is not None:
        disagreement = pointer_store_kind_disagreement(
            inner, value, class_of)
        if disagreement is not None:
            return (None, disagreement)
    if inner in POINTEES_REFUSED:
        # The table's own words, not a second copy of them.  They are written
        # for the LOAD — "the load would put float bits in a register" — and
        # the operative clause is the one before that (this path has no float
        # kind; a list is a blob), which is why the store quotes it rather than
        # paraphrasing it: a paraphrase would be a second answer to "why is a
        # float pointee refused", and the two would drift.
        return (None, f"the pointee is {inner}, and {POINTEES_REFUSED[inner]}")
    if inner in POINTEE_FLOAT_NAMES:
        # A BINARY64 pointee, and the STORE half of the load's enablement: a
        # store through a `Pointer[Float64]` writes the 64 bits of the VALUE's
        # word into a slot the program declared a DOUBLE.  The KIND CHECK above
        # is what decides it — `pointer_store_kind_disagreement` refuses a
        # stated disagreement in BOTH directions with the same evidence — so this
        # arm only has to answer the agreeing case at the load's own width.
        # A value whose kind this path cannot establish is refused by the check
        # above, not answered here: into a double slot an unestablished word
        # may be an integer's bits, and the store cannot say which. This arm
        # answers only a value the check has established as a double (or a
        # literal/name it can see is one), at the load's own width.
        width, signed = 8, False
        if not index_scaled:
            scaled, scale_why = _offset_scale(fn, obj, width)
            if not scaled:
                return (None, scale_why)
        return (("store", width, signed), why)
    if inner in POINTEE_WIDTHS:
        width, signed = POINTEE_WIDTHS[inner]
        if not index_scaled:
            scaled, scale_why = _offset_scale(fn, obj, width)
            if not scaled:
                return (None, scale_why)
        return (("store", width, signed), why)
    st = (structs_by_name or {}).get(inner)
    if st is not None:
        return (None, f"the pointee is {inner}, a STRUCT, and there is nothing "
                      f"AT the address to store into: a struct's value on this "
                      f"path is the address of its frame, so the receiver's word "
                      f"already is the struct rather than a pointer to one. "
                      f"{_sentence(why)} Build the struct where it lives and "
                      f"store its FIELDS, which is what the load side's "
                      f"`_frame_receivers` step is for")
    return (None, f"the pointee is {inner}, which is not a width this model "
                  f"establishes, and a store at a width nothing established is "
                  f"the one instruction this path must not emit — 8 bytes into a "
                  f"1-byte pointee overwrites seven bytes the program never "
                  f"wrote, and that is silent corruption rather than a fault. "
                  f"{_declared_note(why)}")


def subscript_float_element(fn, obj, decls: dict, functions: dict = None) -> bool:
    """True when `obj[i]` is an element of a FLOAT pointee — the one base whose
    subscript STORE needs the value's kind checked (`pointer_store_lowering`).

    The same `pointer_pointee` reader the load and the `.value()` store ask, so
    the three cannot disagree about which pointers hold doubles.
    """
    inner, _why = pointer_pointee(fn, obj, decls, functions)
    return inner in POINTEE_FLOAT_NAMES


def pointer_store_kind_disagreement(pointee, value, class_of) -> str | None:
    """Why this stored VALUE's kind contradicts the pointee's, or None.

    One rule at one boundary, and it is the third boundary: a `printf`
    conversion says how C will READ the word it is handed
    (`printf_kind_conversion_refusal`), a parameter annotation says how the
    CALLEE will (`call_argument_kind_refusal`), and a pointee says how a
    dereference's STORE will be read back. All three are the same claim about
    one word, and until this one existed a `Pointer[Float64]` was a boundary
    with no rule on it.

    **Both directions, because one direction is just as wrong as the other.**
    An integer into a double slot reads back as 4.9e-324 for the integer 1; a
    double into an integer slot reads back as the bit pattern, which is a
    plausible large number. Measured on BOTH architectures from green builds
    with this rule lifted, both exit 0.

    `class_of` is `printf_arg_float_evidence` and its answer is THREE-WAY for
    the reason every other consumer of it is: a `"float"` into an integer
    pointee and an `"int"` into a double pointee are both disagreements, and
    `None` — which is what an unannotated parameter, a name bound from an
    unclassified call and a kind this model has no spelling for all answer —
    is silence into an INTEGER pointee, and a refusal into a DOUBLE one: an
    integer slot reads any word back as a number, while a double slot reads an
    integer's bits as a denormal, so only the double case is unsafe to leave
    open. No `.mojo` file in the tree names `Pointer[Float64]` (checked with
    `git grep` at the tree root), so the refusal cannot reach the stdlib
    through that spelling; the integrator's stdlib gate confirms it.

    The advice is the source's own decision in both directions, and it is the
    conversion this path already has: `float(x)` is `SCVTF` and `Int(x)` is
    `FCVTZS`, so a reader told to write one of them is being told to write a
    construct that answers rather than to annotate their way out of it.
    """
    pointee_is_float = pointee_kind(pointee) == FLOAT_KIND
    got = class_of(value)
    if got is None:
        # SILENCE for an integer pointee, and that is the permissive direction
        # the sibling boundaries take. A DOUBLE pointee is different: the store
        # moves one 64-bit word, so an unestablished value whose bits are an
        # integer lands in a double slot and reads back as a denormal, and
        # nothing the source says rules that out. An unannotated parameter is
        # the usual case. So a double slot refuses an unestablished value by
        # name, and the advice is to state the kind, which is what the reader
        # can actually do.
        if not pointee_is_float:
            return None
        return (
            f"the pointee is `{pointee}` and this store writes {spelled(value)}, "
            f"whose kind this model cannot establish, so nothing in the source "
            f"says the word is a double. A store moves one 64-bit word, and if "
            f"that word is an integer's bits it reads back as a denormal "
            f"(`p.value() = 1` writes 0x1, not 1.0). State the kind where the "
            f"value is bound: annotate it (`n: Float64`), or write the conversion "
            f"`float(x)` so the store's kind is decided at its source"
        )
    if pointee_is_float and got == "float":
        return None
    if not pointee_is_float and got == "int":
        return None
    where = ("into a `Float64` pointee, and the value is an IEEE double" if
             pointee_is_float else
             f"into a `{pointee}` pointee, and the value is a number this "
             f"function bound to an integer")
    want = ("a double is what that slot is read back as" if pointee_is_float
            else "an integer is what that slot is read back as")
    # The clause the other half of the same defect was worded with, kept so one
    # message carries both measurements rather than two messages carrying one:
    # a store through a `Pointer[Float64]` writes the value's own BITS, so the
    # integer 1 is 0x1 — a denormal, not 1.0 — and the answer the reader is
    # given is `Int(x)`, which is `FCVTZS`.
    bits = (" So a store through a `Float64` pointee writes the value's own "
            "BITS: `p.value() = 1` would write 0x1, a denormal rather than "
            "1.0." if pointee_is_float else "")
    return (
        f"the pointee is `{pointee}` and this store writes {where}.{bits} "
        f"{spelled(value)} is a different kind of word from the one the "
        f"declaration says is there, and a store has no way to say so: it moves "
        f"one 64-bit word, so {want} and the number that comes back is the "
        f"other kind's bits. Measured on BOTH architectures from a green build "
        f"with this check lifted: `p.value() = 1` into a `Pointer[Float64]` "
        f"reads back as 4.9e-324 rather than 1.0, and `p.value() = 2.5` into a "
        f"`Pointer[Int64]` reads back as 4612811918334230528 — the double's "
        f"BIT PATTERN, a plausible large integer. Refused rather than "
        f"converted, because the conversion is the source's decision and this "
        f"path already has both of them: write `float(x)` for a double into an "
        f"integer pointee and `Int(x)` for an integer into a `Float64` one"
    )


def pointer_store_refusal(method: str, why: str) -> str:
    """The refusal text for a store `pointer_store_lowering` would not answer.

    `dereference_refusal`'s twin, and worded from the same paragraph: the width
    is the pointee's, and without a pointee the only width available is 8 bytes,
    which corrupts a narrow pointee instead of over-reading it.  "Over-reads"
    becomes "overwrites" because that is what a store does — the difference is
    the whole of what a store changes and a load does not, so a shared message
    would have to be wrong about one of them.
    """
    return (f"{{dotted}}() on the left of an assignment is a STORE to the "
            f"address the receiver holds, and the store's width is the "
            f"pointee's — {_sentence(why)} Refused rather than emitted at the "
            f"only width this path could choose without one, which is 8 bytes: "
            f"that overwrites 7 bytes of a 1-byte pointee the program never "
            f"wrote, and a `malloc`'d buffer is silently corrupted by it rather "
            f"than trapping. Declaring the pointee — a parameter annotated "
            f"`Pointer[UInt8]`, a local `var p: Pointer[Int32]`, or a "
            f"pointer-valued `external_call[\"sym\", Pointer[T]]` — is what "
            f"makes it answerable")


def read_only_text_store_refusal(dotted: str, receiver) -> str | None:
    """The refusal for a store whose RECEIVER is a string, or `None`.

    The one refusal this section needs that the load side does not, and it is
    here because the load side already refuses the same receiver for a
    neighbouring reason: `_emit_expr` skips the dereference intercept when
    `_expr_str_kind(recv)` is `STR_KIND`, because 527 of the corpus's 528
    `.value()` sites are an enum, an iterator or a SIMD rather than a pointer.
    So the store has to ask the same question, and for the same reason — and the
    answer here is about ADDRESSES rather than about the four questions one name
    can ask.

    A string literal's bytes are interned in `__TEXT,__text` (see
    `receiver_shape`), which is a READ-ONLY page in the image this backend
    builds.  Measured on the neighbouring path: `s[0] += 1` over a string
    literal died of SIGBUS on the assignment, which is why
    `_emit_subscript_aug` asks `string_binary_refusal` first.  A plain store
    through a pointer is new, and introducing it without this check would
    introduce a new SIGBUS with it — the capability is here so a module can
    build an argument for a C library function, and handing libc an address in
    the text section is the one argument it must never be handed.
    """
    if receiver is None:
        return None
    return (f"{dotted}() on the left of an assignment stores THROUGH the "
            f"receiver, and this receiver's bytes are the image's own text — a "
            f"string literal is a `char *` into `__TEXT,__text`, which is a "
            f"READ-ONLY page (measured, on the neighbouring subscript path: "
            f"`s[0] += 1` over a string literal died of SIGBUS, exit 138, on "
            f"the assignment). Copy the bytes somewhere writable first — a "
            f"`malloc`'d buffer, which is what every C out-parameter on this "
            f"path needs anyway — and store through that")


# An OPTIONAL UNWRAP — the opposite of a dereference. The question is not what
# is at the address but WHICH OF TWO WORDS was the empty one.
#
# **THE REPRESENTATION EXISTS, and this table used to say it did not.** That
# sentence was false and has been false since the niche landed: an `Optional[T]`
# is one word holding the payload, and `None` is a word `T` cannot produce
# (`optional_none_word`, mirrored in `lib/ProofLib.lean`). What is missing here
# is narrower and different: **this receiver's payload TYPE is not stated**, and
# the niche is a fact about that type rather than about the word. `Some(2)` is
# the same word whether `T` is a `Bool` (where 2 is out of domain, so 2 IS the
# empty word) or an `Int8` (where 2 is a perfectly good payload and the empty
# word is 256), so nothing about the value can say which comparison to emit.
#
# So a receiver that IS declared `Optional[T]` never reaches this table:
# `optional_unwrap_lowering` answers it, and a payload with no niche raises
# `optional_no_niche_refusal` — which names the payload type and the tagged
# two-word alternative, and is a far better message than anything here because
# it is about a DECISION rather than about a missing design. What reaches here
# is a receiver with no usable `Optional` type at all, and the reader's next
# action is one line of source: annotate it.
#
# This is the SHAPE the wave-3 by-reference work exposed, and it is worth
# separating from the dereference above because the receiver is not a word that
# happens to hold an address: `self.step` is a FRAME SLOT, so this is a method
# on a value read out of another function's frame, and the frame's field list
# is what says the slot is an Optional at all.
UNWRAP_METHODS = {
    "or_else": "is an Optional unwrap, and this target has a representation "
               "for one — the payload word, with `None` at the word the "
               "PAYLOAD'S TYPE cannot produce (`formal/model.py`'s "
               "`optional_none_word`, which answers `Optional[Bool]`, "
               "`Optional[String]`, `Optional[Int32]` and every "
               "reference-shaped payload, and refuses `Optional[Int]` naming the "
               "two-word representation that would cover it). This receiver is "
               "not one of those: nothing here states what its payload's type "
               "is, and the niche is a fact about that type rather than about "
               "the word — `Some(2)` is the same word whether the payload is a "
               "`Bool` (whose empty word is 2) or an `Int8` (whose is 256). "
               "Annotate the receiver `Optional[T]`",
    "unsafe_value": "is an Optional unwrap (see or_else), and the same "
                    "annotation answers it",
    "value_or": "is an Optional unwrap; see or_else",
    "or": "is an Optional unwrap; see or_else",
}

# A method on a WRITER, which is a multi-field struct and therefore a frame
# address on this path — NOT a file descriptor. This table exists because
# `write_string` is the single most tempting name in the tree to add next to
# the `write` that IS lowered, and adding it would be the catastrophic
# mis-implementation: `write` is honest only because `open()` makes its
# receiver a descriptor (see VALUE_METHOD_RECEIVERS), and a `Some[Writer]` is
# not one. The 317 `writer.write(` sites in the stdlib are all of this shape.
WRITER_METHODS = {
    "write_string": "is a method on a Writer — a multi-field struct, so on "
                    "this path the receiver is the ADDRESS of a frame of "
                    "8-byte slots, not a file descriptor. It is not the `write` "
                    "that is lowered: that one is honest only because "
                    "open(...) makes its receiver a descriptor, and nothing "
                    "here establishes that a Writer is one. Lowering it as a "
                    "write would pass a frame address as fd(2): the syscall "
                    "returns EBADF, nothing checks it, and the program's "
                    "output is missing rather than wrong-looking",
    "write_bytes": "is a method on a Writer; see write_string",
    "write_t": "is a method on a Writer; see write_string",
    "write_repr": "is a method on a Writer; see write_string",
    "flush": "is a method on a Writer; see write_string",
}

# An MLIR builtin dunder. `__mlir_bool__` IS implementable — a Bool is a word
# holding 0 or 1 on this path, because every source of one is emitted as
# `mov #1`/`mov #0` (see the BoolLiteral and True/False arms of each backend's
# `_emit_expr`) and every comparison is 0/1, so the call is the same test `if`
# already performs. It is refused only because it cannot be GUARDED: `if b:`
# works on any word, so lowering it kind-blind would make `s.__mlir_bool__()` on
# a String answer `(s != 0)` — a plausible-looking 1 for a pointer. The guard
# needs a BOOL kind distinct from INT, which the kind model does not have
# because an unannotated word is an int (see the note on kinds). That is a
# deliberate deferral, not an impossibility: one file of the 76, and the fix
# is a fifth kind constant threaded through ValueKinds and both backends'
# kind oracles, where `_unify` would have to decide what a bool-and-an-int is.
MLIR_BOOL_METHODS = {
    "__mlir_bool__": "is a real builtin and it is lowered as the same test `if` "
                     "already does — a Bool is a word holding 0 or 1 on this "
                     "path, so `x != 0` is its value — for every receiver "
                     "whose DECLARED type says `Bool` (`build."
                     "_lower_dialect_select`, in the shared pipeline, so both "
                     "architectures get it by construction). This receiver is "
                     "not one: the source states nothing about what this word "
                     "holds, and an unannotated word is an integer here, so "
                     "`(receiver != 0)` would answer 1 for a `char *` that "
                     "happens to be non-null. The missing thing is the DECLARED "
                     "TYPE and not a kind: `formal.types.BOOL_TYPE_NAMES` "
                     "names the annotations that carry it and "
                     "`model.annotation_is_bool` is the one reader of them. "
                     "Annotate the receiver `Bool`",
}


def receiver_shape(expr) -> str:
    """Where the receiver of a method call came from, as a word for a refusal.

    The KIND says what the word holds; the SHAPE says how the program got it,
    and the two answer different "what is missing" questions. A name that is a
    parameter is a word from the caller; a frame slot is a word read out of
    another function's frame, whose field list is what would say what it
    holds; a literal is a `char *` into read-only __TEXT,__text; a call result
    is whatever that call was declared to produce.

    Shared by both backends so the two architectures cannot disagree about
    which provenance a refusal names — the same rule the method tables follow.
    """
    if isinstance(expr, F.StringLiteral):
        return "a string literal"
    if isinstance(expr, F.MemberExpr):
        return "a frame slot"
    if isinstance(expr, F.CallExpr):
        return "the result of a call"
    if isinstance(expr, F.IdentExpr):
        return "a name"
    return "an expression this path does not classify"


def is_open_call(expr) -> bool:
    """True when `expr` is a call to the bare name `open`.

    Structural, and in the model so both backends answer it identically. It is
    the only thing that makes a word a FILE DESCRIPTOR on this path: `open(2)`
    is what the C library hands one back, and nothing else here produces one.
    """
    if not isinstance(expr, F.CallExpr):
        return False
    func = expr.func
    return isinstance(func, F.IdentExpr) and func.name in BUILTIN_FUNCTIONS \
        and BUILTIN_FUNCTIONS[func.name] == "file_open"


def _shape_guarded_refusal(method, receiver_kind, dotted, receiver_is_fd,
                           receiver_shape):
    """The receiver-kind half of `value_method_refusal`, or None when honest.

    Reached only for a method that is in NEITHER string table, so everything
    here is about a receiver that is not known to be a `char *`.
    """
    # The already-lowered container methods first: `write`/`close` are honest
    # on a file descriptor and are otherwise a syscall on a wrong fd, which is
    # the more expensive of the two mistakes because it does not even fault.
    if method in VALUE_METHOD_RECEIVERS:
        want, source = VALUE_METHOD_RECEIVERS[method]
        if receiver_is_fd:
            return None
        where = f"it is {receiver_shape}" if receiver_shape else "it is a value"
        if receiver_kind is None:
            return (f"{dotted}() lowers to the C library's {method}(2), so its "
                    f"receiver has to be {want} — and {where} whose value "
                    f"this path cannot establish to be one. Lowered anyway it "
                    f"would pass whatever the word holds as a file "
                    f"descriptor, which the C library answers with EBADF: the "
                    f"program runs, writes nothing and exits 0. Bind the "
                    f"descriptor with {source} and call the method on the "
                    f"name")
        return (f"{dotted}() lowers to the C library's {method}(2), so its "
                f"receiver has to be {want}, and this one is "
                f"{receiver_shape} classified as {receiver_kind!r} — a word "
                f"that is not a descriptor. Lowered anyway it would be "
                f"passed as fd(2), which the C library answers with EBADF: "
                f"the program runs, writes nothing, and exits 0. A method of "
                f"a struct (a Writer, say) reaches here and is NOT this "
                f"call — its receiver is a frame address. Bind the descriptor "
                f"with {source}")
    if method in DEREFERENCE_METHODS:
        # This arm is now only reached for a receiver the pointer value model
        # could NOT call a pointer — a backend intercepts the dereference BEFORE
        # it asks here (see `dereference_lowering`), so a receiver with a
        # declared pointee is answered and never gets this far.  What lands
        # here is a receiver whose pointee is not recorded, and the message says
        # that rather than asserting the receiver is a load.
        return (f"{dotted}() {DEREFERENCE_METHODS[method]}. Refused rather "
                f"than emitted as a call to a symbol spelled {dotted!r}, "
                f"which is what this used to do: the image built and then "
                f"died in the loader")
    if method in IDENTITY_VALUE_METHODS:
        return (f"{dotted}() {IDENTITY_VALUE_METHODS[method]}. Refused rather "
                f"than emitted as a call to a symbol spelled {dotted!r}, "
                f"which is what this used to do: the image built and then "
                f"died in the loader")
    if method in UNWRAP_METHODS:
        return (f"{dotted}() {UNWRAP_METHODS[method]}. Refused rather than "
                f"emitted as a call to a symbol spelled {dotted!r}, which is "
                f"what this used to do: the image built and then died in the "
                f"loader")
    if method in WRITER_METHODS:
        return (f"{dotted}() {WRITER_METHODS[method]}. Refused rather than "
                f"emitted as a call to a symbol spelled {dotted!r}, which is "
                f"what this used to do: the image built and then died in the "
                f"loader")
    if method in MLIR_BOOL_METHODS:
        return (f"{dotted}() {MLIR_BOOL_METHODS[method]}")
    if method in BUILTIN_VALUE_METHODS:
        # `append`, whose guard is in the backend: `_scan_list_caps` has the
        # function in hand and can compute the capacity, and a name the scan
        # drops refuses there with a message about CAPACITY — which is the
        # thing a reader has to fix. Refusing here would be both less accurate
        # and one more thing to keep in step between two architectures.
        #
        # `clear` is the other half and its guard IS a kind, so it is asked
        # here: storing zero at offset 0 of a word that is not a blob's header
        # writes zero into whatever address that word holds. A receiver this
        # image cannot establish to be a list therefore refuses, which is the
        # same default the whole kind model runs on and the reason the arm is a
        # table and not a flag.
        if method in BUILTIN_VALUE_METHOD_LIST_KINDS:
            if is_list_kind(receiver_kind):
                return None
            return list_clear_refusal(dotted, receiver_kind, receiver_shape)
        return None
    holds = repr(receiver_kind) if receiver_kind else "a word of unknown contents"
    return (f"{dotted}() is a method call on a value, and this backend "
            f"lowers only "
            f"{', '.join(sorted(BUILTIN_VALUE_METHODS))} (on "
            f"{_article_join(sorted({v[0] for v in VALUE_METHOD_RECEIVERS.values()}))}"
            f") and the string methods "
            f"{', '.join(sorted(POINTER_BOUNDED_METHODS))}"
            f" — the receiver is "
            f"{receiver_shape or 'a plain word'} on this path, and "
            f"{method!r} is not one of those methods of those receivers, so "
            f"adding it to either table would be a guess about what it means "
            f"on {holds}. Refused rather than emitted as a call to a symbol "
            f"spelled {dotted!r}, which is what this used to do: the image "
            f"built and then died in the loader")


def _article_join(items) -> str:
    """`['a file descriptor']` -> 'a file descriptor'; two of them read better
    joined than enumerated, and the fallback names a SET so the same word is
    not printed twice."""
    uniq = list(dict.fromkeys(items))
    if len(uniq) == 1:
        return uniq[0]
    return ", ".join(uniq[:-1]) + " or " + uniq[-1]

# The same question for a call by BARE NAME that is a builtin rather than a
# function: `open(path, "w")` is the C library's `open` underneath, but the C
# one takes an integer flags word and a bare name that is not a C symbol, so
# left to the extern path it became `BL _open` and, where a name did resolve,
# it passed the mode STRING as the flags word.
BUILTIN_FUNCTIONS = {
    "open": "file_open",
    # `debug_assert` is here rather than in an emitter's own `if name == ...`
    # arm because BOTH spellings have to be recognised by the SAME rule and the
    # rule is a language fact: see `debug_assert_call` and `debug_assert_is_call`.
    "debug_assert": "debug_assert",
}



# ── a `with` over a RESOURCE value ────────────────────────────────────────
#
# `with open(path, "w") as f:` is CPython's context-manager protocol, and the
# protocol is two calls on the object: `__enter__` binds the name and
# `__exit__` runs on the way out.  `formal/build.py::_one_with_item` lowers
# exactly those two calls, and it can only do it for a struct this image
# compiles — so the single most common `with` in the corpus was REFUSED, by name
# and with a correct explanation ("this build cannot answer what type it is,
# because it is not a construction of a struct this image compiles").
#
# The type IS answerable, and it is answerable from the same place every other
# fact about `open` comes from: `BUILTIN_FUNCTIONS` above says `open` lowers to
# the C library's `open(2)`, so its value on this path is a FILE DESCRIPTOR —
# one word, already the receiver `f.write(…)` and `f.close()` lower on
# (`BUILTIN_VALUE_METHODS`, guarded by `VALUE_METHOD_RECEIVERS`).  A descriptor's
# `__enter__` returns the descriptor and its `__exit__` closes it, which is
# `close(2)` on the same word.  So this table is the protocol for a value whose
# representation is already decided, and it says so with two names rather than
# with a rule per builtin.
#
# It is deliberately keyed by the BUILTIN NAME and not by the call's shape, so
# `mod.open(...)` — a dotted spelling of a name this module may or may not
# declare — is NOT here.  `with_expr_struct` resolves the dotted spelling for a
# struct because `mod.S(...)` constructs a type the image compiles and the
# image has a table of those; a dotted `open` names a function in another
# module, and `formal/model.py::dotted_struct_construction`'s argument is the
# same one: a callee this path cannot resolve must not be guessed at.
#
# What is NOT here is a resource this path has no value for.  A name absent from
# this table keeps `refuse_unlowerable_with`'s sentence, which is the honest
# answer for it rather than a gap this table left.
RESOURCE_CONTEXT_MANAGERS = {
    "open": "close",
}


def resource_context_manager_exit(expr) -> str | None:
    """The `__exit__` builtin for a `with` over a RESOURCE, or None.

    The one entry point for the question, and it asks about the CALL rather than
    about a callee name: `len(open)` is not a `with` over a descriptor, and a
    name-based test would say it was.  `with_expr_struct` is the sibling reader
    for the struct case and takes the same view of what an expression is.
    """
    if isinstance(expr, tuple):        # a parenthesised expression
        expr = expr[0] if expr else None
    callee = getattr(expr, "func", None)
    if callee is None:
        return None
    name = getattr(callee, "name", None)
    if not isinstance(name, str):
        return None
    return RESOURCE_CONTEXT_MANAGERS.get(name)

# The builtins each backend's CALL EMITTER intercepts by bare name and lowers
# itself, rather than leaving to a module symbol. It is the single published
# table both emitters' `if name == …` chains and `FRAME_VARIADIC_BUILTIN_CALLS`
# read, so the three agree by construction. What disagreeing cost is measured
# in `test_refusal_taxonomy.py::_no_def_callee_arm_checks` and in
# `test_formal_run.py`'s `print(p)` guard: a name the emitter lowers was one
# the model did not know was a callee.
#
# They did not agree by construction before, and the disagreement is not
# hypothetical — it is a refusal that names a callee wrongly. A name here is
# lowered by the backend, so handing it a FRAME ADDRESS is a wrong-category
# argument rather than an unbound name, and `FRAME_VARIADIC_BUILTIN_CALLS` is
# the set that says so. A name in ONE emitter's `if` chain and not in that set
# is a callee the emitter compiles and the model does not know about, which is
# exactly the shape that produced `print(p)` building, running, exiting 0 and
# printing the frame's own address as a decimal (6102330608 on arm64,
# 13027830976 on x86-64, a different number on every run).
#
# `{name: emitter method suffix}`, because both emitters name the methods
# identically (`_emit_len`, `_emit_print`, …) and the one that does not is a
# dispatch this table cannot express. `range` is spelled `_emit_range_list`
# because that emitter takes the ARGS LIST rather than the CallExpr, which is
# the same asymmetry `_emit_len` and `_emit_print` do not have; it is a
# property of the emitter, not of the builtin, so it lives here rather than in
# a caller that has to know it.
#
# `open` is NOT here: it is in `BUILTIN_FUNCTIONS` as `file_open`, because
# `open` is also a C library entry point and the two spellings are genuinely
# different facts. A reader asking "does the backend compile this" wants the
# BUILTIN half, and `BUILTIN_FUNCTIONS` plus this table between them are the
# whole answer.
EMITTER_BUILTINS = {
    "range": "range_list",
    "len": "len",
    "print": "print",
    "str": "str",
    "repr": "repr",
    # `ord`, `chr` and `hash` are here for a reason that is not "the backend can
    # do them": ONE of them can and two cannot, and all three reached the LINKER
    # as dangling symbols before, because a name absent from this table is a
    # call the backend does not compile and the extern path turns into a `BL` to
    # a symbol no library defines.  Intercepting them here is what lets the two
    # refusals be refusals — with the reason that is specific to each — instead
    # of a link-time message about a symbol, produced four stages after the one
    # that could have named the construct.  See the `ord`/`chr`/`hash` block.
    "ord": "text_builtin",
    "chr": "text_builtin",
    "hash": "text_builtin",
}


def emitter_lowers(name: str) -> bool:
    """True when a backend's call emitter lowers a call to `name` ITSELF.

    The one question `FRAME_VARIADIC_BUILTIN_CALLS` and the two emitters' `if
    name == …` chains all have to answer the same way, asked here once.
    """
    return name in EMITTER_BUILTINS


def builtin_function(name: str):
    """How a call to the bare name `name` lowers, or None if it is not one of
    the builtins this model represents."""
    return BUILTIN_FUNCTIONS.get(name)


def is_pure_expression(e) -> bool:
    """True when evaluating `e` can be neither observed nor fatal.

    Deliberately narrow, because a SELECT evaluates BOTH arms. An arm holding a
    call may print, mutate a blob, or hit a cap, and running it when its value is
    thrown away is a behaviour change, not an optimisation. So the allow-list is
    literals, locals, field reads, and arithmetic over them.

    Container literals are excluded even though a list display is
    side-effect-free in principle: a list arm reserves frame space for its blob,
    and reserving both arms' worth at once is a frame-pressure change for no
    benefit. Calls are excluded even for known-pure builtins, because the builtin
    set is exactly what grows over time and a stale allow-list here would
    silently change semantics when it does.

    **This is the ONE such reader and it lives here, not in an emitter.** It was
    `formal/arm64_codegen.py`'s `_is_pure_expr` method, and
    `formal/build.py`'s extremum lowering (`_lower_builtin_extremum`) needs the
    same answer for the same reason — it rewrites `max(a, b)` into a
    `TernaryExpr`, which mentions each operand twice, so an impure operand would
    be evaluated twice and a call would happen out of CPython's left-to-right
    order. Two copies of one allow-list is two answers that can drift on exactly
    the shapes that drift (the next builtin somebody makes pure), so the emitter
    now asks this and the arithmetic is in one place.
    """
    if isinstance(e, (F.IntLiteral, F.StringLiteral, F.BoolLiteral,
                      F.IdentExpr)):
        return True
    if isinstance(e, F.MemberExpr):
        return is_pure_expression(e.obj)
    if isinstance(e, F.UnaryOp):
        return is_pure_expression(e.operand)
    if isinstance(e, F.BinaryOp):
        return (is_pure_expression(e.left)
                and is_pure_expression(e.right))
    if isinstance(e, F.TernaryExpr):
        return (is_pure_expression(e.condition)
                and is_pure_expression(e.then_val)
                and is_pure_expression(e.else_val))
    return False


def extremum_call_is_a_select(name, nargs: int, nkwargs: int) -> bool:
    """Whether a call to `name` is the shape `max`/`min` lower as a select.

    **The counts half of the rule, published as its own function so there is
    ONE answer to "is this call of that name one this path lowers".** Two
    readers need it and they do not share an AST: `formal/build.py`'s
    `_lower_builtin_extremum` walks the fire AST, and
    `tools/formal_proof_breadth.py`'s `_unlowered_builtins_in` scans CPython
    `ast` because a census row that names the builtin it hit is a fact about the
    program the census emitted. A second copy of the arity rule in the census
    would go quiet the day the rewrite's guard changed, and it would go quiet in
    the direction that reads well: a ledger row saying a program stopped on
    `max` when it stopped on something else.

    False for a name that is not an extremum, so a caller can hand it every name
    it found without testing membership first. `nkwargs` counts KEYWORD
    arguments (`key=` and `default=`), which are what make the remaining shapes
    unanswerable rather than merely longer.
    """
    return (name in ("max", "min")
            and not nkwargs
            and nargs >= 2)
