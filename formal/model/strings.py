from . import *

# ── TEXT ENCODING: when is a BYTE count a CODE POINT count? ─────────────────
#
# `strlen` is the length of a NUL-terminated `char *`. A Python `str` is a
# sequence of CODE POINTS. For an ASCII string those are the same number, and
# every answer on this path has been right for that reason without anyone
# saying so. For anything else they are not, and the difference is not a
# rounding error — it is the whole question:
#
#     len("héllo")   CPython 5    strlen of its UTF-8 bytes  6
#     len("日本")     CPython 2    strlen of its UTF-8 bytes  6
#     "héllo".find("llo")   CPython 2    strstr offset  3
#
# All three BUILD, all three RUN, all three exit 0, and all three are wrong on
# both architectures. That is what makes this block necessary rather than
# tidying: a byte answer presented where CPython gives a code-point answer is a
# MISCOMPILE — a program that indexes by the answer then reads out of range,
# and a program that only prints it is wrong in a way no reader of the output
# would catch. The representation decision above (`bugs/formal/FORMAL_string_value_model.md`
# §"The decision": a formal value is one word and a string is a bare `char *`)
# does not change, and neither does anything above this value model; what
# changes is that the ONE question "is this byte count a code point count" is
# now asked, in one place, and answered one of three ways.
#
# The three ways, and why there are three:
#
#   ASCII_BYTES   every string this image can hold is ASCII, so a byte count
#                 IS a code point count. The ordinary `strlen` and nothing
#                 else changes, and this is the answer for every program in the
#                 corpus — which is why the non-ASCII answer is a refusal with
#                 a condition on it rather than a refusal.
#   CODEPOINTS    the build KNOWS this operand's text — it is a string literal,
#                 or `lstrip`/`find`/`count` of one — so the number of code
#                 points is `len()` of that text, computable HERE with no
#                 machine operation at all. This is a new capability, not a
#                 repair: `len("日本")` answered 2 on both backends after this
#                 and refused before it.
#   REFUSE        the operand's bytes are not something this build can see AND
#                 this image holds a string with a byte >= 0x80, so a `strlen`
#                 is not Python's `len()` and nothing else here computes one.
#
# The condition on the refusal is what keeps it from being a whole-corpus
# regression, and it is SOUND rather than convenient: on this path every string
# value is either a literal's interned bytes or an interior pointer into them
# (`string_has_static_storage`, the decision this backend landed on), so the set
# of possible string CONTENTS in an image is exactly the set of decoded string
# LITERALS compiled into it. If none of them has a byte >= 0x80 then no string
# in the image can, and `strlen` is right for all of them — including the ones
# whose value this build cannot name, which is the case a per-operand analysis
# could never answer.
#
# WHAT IS NOT HERE, and each is a decision rather than an omission:
#
#   * No runtime UTF-8 walk. The loop is four instructions per byte and both
#     backends would need their own copy, and this file's own history is the
#     argument: `lstrip`'s hand-written byte loop existed in two copies and had
#     one bug in each (see `STRIP_CHARS`), which is why it is a `strspn` call
#     now. A second copy of a byte walk is a second thing to be wrong.
#   * No libc wide-character call. `mbstowcs(NULL, s, 0)` IS a code point count,
#     and it answers in the CURRENT LOCALE: in the C locale it fails for every
#     byte >= 0x80 and returns `(size_t)-1`. A locale is not a decidable
#     answer, so it is not an answer.
#   * No `\u` / `\U` / `\N{}` ESCAPE decoding HERE. That is a front-end
#     question — `fire_compiler.decode_c_escapes`, shared by all three engines —
#     and it decodes all four of those spellings (plus a multi-digit octal run)
#     as of 2026-10-07, so text reaches this path already decoded and this
#     block only has to answer about the bytes it is handed.

# The two facts about a piece of TEXT, named so a reader can see which question
# a call site is asking. `ASCII` is the permissive one and it is a fact about
# the BYTES, not about the language: a 0x7F DEL is ASCII, a 0x80 is not, and no
# multi-byte sequence has a lead byte below 0xC2.
def text_is_ascii(text: str) -> bool:
    """True when every character of `text` is one byte in UTF-8."""
    return isinstance(text, str) and text.isascii()


def codepoint_count(text: str) -> int:
    """How many CODE POINTS `text` has — which is `len()`, said out loud.

    A named reader rather than a bare `len(text)` at four call sites, because
    the whole block above exists to say that this number and the number of
    bytes are different quantities and the difference is easy to reintroduce
    with a subscript.
    """
    return len(text)


def string_literal_text(node) -> str | None:
    """`node`'s DECODED text when it is a string literal, else None.

    The one reader of "what text does this expression carry", asked by every
    construct in this block. Decoded through `fire_compiler.decoded_literal`,
    which is the tree's one decoder (the same one both backends' `_intern_string`
    calls), so a text compared here and bytes emitted there cannot disagree —
    `fire.py`'s note on that function says the raw form is what a C compiler
    would have decoded and nothing else here does.
    """
    if isinstance(node, F.StringLiteral):
        return F.decoded_literal(node)
    return None


# The IMAGE's text fact, published rather than threaded: the consumers are a
# per-function walk inside a backend and a refusal asked from `build.py` before
# any emitter runs, and neither has the module's statements in hand. Same shape
# as `_MODULE_SYMBOLS` and NOT its rule — see `publish_non_ascii_strings`.
_NON_ASCII_STRINGS: list = []


def publish_non_ascii_strings(texts: list) -> None:
    """ADD `texts` to the current unit's non-ASCII string literals.

    **ACCUMULATES, where `publish_module_symbols` REPLACES, and the difference is
    the direction each mistake goes.** A module-global table must not accumulate,
    because a name one unit declares and another does not is a real conflict and
    a union would invent a binding — and two units compiled in one process must
    not see each other's globals at all. A non-ASCII string list must
    accumulate, because the question it answers is "can a string value in this
    IMAGE be non-ASCII", and the honest answer for a multi-module image is the
    union over every module in it: a string one module interns is a value another
    module can hold, through a return value or a parameter, however many of that
    other module's own literals are ASCII.

    Measured on both architectures, before this accumulated, with two imported
    modules where only the FIRST carries the accented literal:

        h2.mojo   def tag() -> String: return "héllo"
        h3.mojo   def plain() -> Int: return 3
        e2.mojo   from h2 import tag
                  from h3 import plain
                  def main(n): printf("len=%d n=%d", len(tag()), plain())

    `len(tag())` printed **6** where CPython prints 5, exit 0, on arm64 and on
    x86-64 — because `_prepare_functions` runs for the ENTRY first and for each
    imported module after it, so a REPLACE left the table holding whichever unit
    was compiled LAST, and `h3` has no non-ASCII literal. A replace is a correct
    answer to "what does THIS module hold" and a wrong one to "what can a string
    in this IMAGE be".

    The cost of accumulating is over-conservatism across two top-level builds in
    one process, which is to say none in practice: `fire.py` builds one image
    per invocation, and the entries are a refusal that a later build would have
    to earn back by being an all-ASCII image, which it can only be if no earlier
    one was not.
    """
    global _NON_ASCII_STRINGS
    have = set(_NON_ASCII_STRINGS)
    for text in texts or []:
        if text not in have:
            have.add(text)
            _NON_ASCII_STRINGS.append(text)


def non_ascii_strings() -> list:
    """The published non-ASCII literals, in the order they were first seen."""
    return list(_NON_ASCII_STRINGS)


def clear_non_ascii_strings() -> None:
    """Start a NEW IMAGE's accumulation over.

    The one caller that is not a test is `formal/build.py`'s `compile_formal`,
    at the top of the image: `publish_non_ascii_strings` accumulates because a
    union is the sound direction WITHIN an image, and this is what keeps that
    union from being per-PROCESS instead. Two images built by one harness must
    not see each other's literals, or the second refuses `len()` over text that
    never had any — a false refusal, which is the expensive direction here
    rather than the cheap one.
    """
    global _NON_ASCII_STRINGS
    _NON_ASCII_STRINGS = []


# How many examples a refusal quotes. A message that listed every one would be
# unbounded on a file with a large non-ASCII table in it, and the point of the
# examples is to let a reader recognise the case, not to inventory it.
_NON_ASCII_EXAMPLES = 3


def _non_ascii_examples(texts) -> str:
    shown = [repr(t) for t in list(texts)[:_NON_ASCII_EXAMPLES]]
    if not shown:
        return ""
    more = len(texts) - len(shown)
    tail = f" (and {more} more)" if more > 0 else ""
    return ", ".join(shown) + tail


def is_docstring_statement(node) -> bool:
    """True for a bare string `ExprStmt` — a docstring, and not a VALUE.

    **The one answer to "is a bare string statement a value on this path", and
    it is asked from two places that would otherwise each decide it.**
    `module_body` already acts on it (a bare string `ExprStmt` at file level is
    not body: Python stores it in `__doc__` and runs nothing), and the TEXT
    ENCODING scan below now acts on it too, because until it did the two
    disagreed and the disagreement cost this repository 229 files.

    The reason a docstring is not a value is not that it is dropped: measured,
    a FUNCTION docstring's bytes DO reach the image (`ZZFNDOCPROBEZZ` appears
    once in a built image whose module docstring's `ZZDOCSTRINGPROBEZZ` appears
    zero times, on this tree). It is that **nothing can name it.** `__doc__` is
    on `_UNRESOLVED_NAME_ALLOWED`, so a read of `f.__doc__` is materialised
    from that table rather than read out of the literal, and there is no other
    spelling: no name binds the statement, so no parameter, no return value and
    no container can carry a pointer to it. A string VALUE in this image is
    reachable by construction — `publish_non_ascii_strings`'s own argument is
    that "a string one module interns is a value another module can hold" — and
    a docstring is not one.

    So the distinction that matters for the encoding block is reachability, and
    this is the predicate for it. It is deliberately the WIDE test (any bare
    string statement, not only a body's first) because it is the one that is
    true: a bare string expression statement is discarded on every path, so
    there is no spelling in which it holds a value, and a narrow "first
    statement of a body" rule would be a second answer with a case the wide one
    does not cover.
    """
    return (isinstance(node, F.ExprStmt)
            and isinstance(getattr(node, "value", None), F.StringLiteral))


def non_ascii_strings_in(stmts: list, limit: int = 32) -> list:
    """The decoded TEXT of every non-ASCII string literal under `stmts`.

    `limit` bounds what is KEPT, not what is looked for: the callers only ever
    need to know that the set is non-empty and quote a few examples, and a file
    with a megabyte of non-ASCII text in it should not make the answer's size
    the size of the question. The walk is over the module's own statements —
    body, every function, every nested def — and it is the WHOLE unit, which is
    the soundness argument in the block comment above: interning is by content
    from these statements and nothing else can put a byte in the string pool.

    **The DECODED TEXT and not the node**, because this list exists to be quoted
    in a diagnostic: `repr()` of the dataclass is a line and a half of field
    assignments, and a reader who is being told which string in their file is
    non-ASCII needs the string.

    A BYTES literal (`b"…"`) is not one of these, and a RAW string is not
    scanned at all: `b"\\xff"`'s bytes are a blob's element width rather than a
    string's — a bytes blob is not a string on this path, its constructor
    element is ONE byte (`model.blob_elem_stride`, commit 37056734) — and a raw
    string's backslashes are content, so decoding it would invent the escapes it
    deliberately did not ask for.

    **A DOCSTRING is not one of these either, and that is the third exclusion
    with a measured reason rather than a typing one.** See
    `is_docstring_statement`, which is the predicate and the argument: a
    function docstring's bytes do reach the image, but no name binds them, so
    they are not a string a subscript, a `strlen` or a `%<width>s` can be taken
    of. Before this exclusion the scan counted them, and because the encoding
    block's answers are conditioned on "does this IMAGE hold a non-ASCII
    literal" rather than on the operand, one em-dash in a docstring refused
    every string operation in the module — the conservative direction, taken on
    a fact that is not there.
    """
    out: list = []
    stack = list(stmts or [])
    visited = set()
    texts = set()
    while stack:
        node = stack.pop()
        if id(node) in visited:
            continue
        visited.add(id(node))
        if is_docstring_statement(node):
            # NOT descended into, and this is the whole fix. A docstring's bytes
            # are in the image and nothing can name them
            # (`is_docstring_statement`), so publishing them made the encoding
            # block refuse every `s[i]`, `len(s)` and `printf("%<w>s", s)` in a
            # module whose only non-ASCII text was PROSE. Measured on
            # `formal/hostmods/os/_syscalls.mojo`, whose 31 non-ASCII literals
            # are 31 docstrings and not one value: `d[i]` came back as "this
            # image holds a string literal that is not ASCII", on both
            # architectures, and the refusal was asked over a file that holds
            # no non-ASCII string at all.
            #
            # `continue` rather than "skip the value and descend": an
            # `ExprStmt`'s only field IS its value (`value`, `line`, `col`), so
            # there is nothing else in it, and one branch here is one rule
            # rather than a shape to keep in step with the dataclass.
            continue
        if (isinstance(node, F.StringLiteral)
                and not getattr(node, "is_raw", False)
                and not getattr(node, "is_bytes", False)):
            text = F.decoded_literal(node)
            if not text_is_ascii(text) and text not in texts:
                texts.add(text)
                out.append(text)
                if len(out) >= limit:
                    return out
        if isinstance(node, (list, tuple, set, frozenset)):
            # A child can be a TUPLE of (name, node) pairs and not a node:  a
            # `CallExpr`'s own `kwargs` is declared `list of (str, Expr)`, so a
            # walk that only descends into dataclasses skips the VALUE of every
            # keyword argument — and `printf("%s", s="héllo")` put a non-ASCII
            # string in the image while the scan reported the image ASCII. That
            # is the unsound direction: the scan exists to make the encoding
            # block CONSERVATIVE, and a literal it cannot see makes it
            # permissive. Measured, both engines identical, before this arm:
            #   $ python3 -c '… non_ascii_strings_in(<that module>)'
            #   []
            stack.extend(node)
        elif isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif dataclasses.is_dataclass(node):
            for field in dataclasses.fields(node):
                value = getattr(node, field.name, None)
                if (dataclasses.is_dataclass(value)
                        or isinstance(value, (list, tuple, set, frozenset,
                                              dict))):
                    stack.append(value)
    return out


def string_codepoint_verdict(construct: str, operand, spelled: str):
    """`(verdict, why)` for a construct that needs a CODE POINT quantity.

    `LEN_FROM_STRLEN` — a byte count is a code point count here; emit the
    `strlen` as before. `LEN_FROM_CODPOINT_FOLD` — `why` is the INTEGER to
    materialise, and the build knew it without running anything.
    `(None, message)` — refuse, and `message` is `codepoint_refusal`'s.

    `operand` is the node whose text decides it and `construct` names the thing
    being asked for, because the two refusals differ in what a reader has to
    change: a wrong LENGTH is fixed by not asking for a length over text whose
    bytes the build cannot see, and a wrong POSITION additionally says the
    offset a `strstr` returns is a byte offset.
    """
    text = string_literal_text(operand)
    if text is not None:
        if text_is_ascii(text):
            return LEN_FROM_STRLEN, None
        return LEN_FROM_CODPOINT_FOLD, str(codepoint_count(text))
    if non_ascii_strings():
        return None, codepoint_refusal(construct, spelled)
    return LEN_FROM_STRLEN, None


def codepoint_refusal(construct: str, spelled: str) -> str:
    """Why a byte quantity is not this construct's answer, in one message.

    `construct` is the whole thing as the source spells it (`len(s)`,
    `s.find(p)`), so the first clause needs no assembly and the two machines
    cannot describe one source file differently. `spelled` is the OPERAND, and
    the half of the sentence that names it is what tells a reader which of the
    two things to change — a construct whose operand is a literal is folded and
    never reaches here, so reaching here means the operand's bytes are behind a
    `char *` at run time and no amount of annotating it will help.

    Shared by every construct in this block, for the same reason
    `string_concat_refusal` and `LENGTH_DEPENDENT_METHODS` share one message:
    there is ONE place a reader is told what the representation cannot do, and a
    second copy of that sentence is a second thing to fall out of step.
    """
    examples = _non_ascii_examples(non_ascii_strings())
    where = (f" This image holds a string literal that is not ASCII — {examples}"
             f" — so a `strlen` somewhere in it is not Python's `len()`."
             if examples else "")
    return (
        f"{construct} is refused: on this path it would answer in BYTES where "
        f"CPython answers in CHARACTERS. A string here is a bare `char *` to "
        f"NUL-terminated bytes, and a UTF-8 byte is not a Python character — "
        f"`é` is two bytes and one character, `日本` is six bytes and two — so "
        f"`strlen` counts bytes, a `strstr` offset counts bytes from the start "
        f"of the text, and a `%<width>s` pads to a byte width.{where} The "
        f"operand is {spelled}, and this build cannot see what text it holds: "
        f"it is a name, a parameter or a call, and its bytes are behind a "
        f"`char *` only at run time. Refused rather than emitting the byte "
        f"answer, because a byte count presented as a character count is the "
        f"most plausible wrong number in this file — a small positive integer, "
        f"stable across runs and identical on both architectures — and a "
        f"program that uses it as an index then reads out of range. What this "
        f"path CAN do: bind the operand to a string literal in the source, "
        f"where the number of characters in it is known at compile time and the "
        f"answer is folded — `len(\"日本\")` is 2 here and was refused before "
        f"this; or keep the text ASCII, which is what every other answer on "
        f"this path already assumes and the only thing that makes `strlen`, a "
        f"`strstr` offset and a `%s` width mean what Python means by them")




# ── `ord` / `chr` / `hash`: a character as a NUMBER, and back ───────────────
#
# All three are in `FRAME_VALUE_ONLY_CALLS` already — a frame address handed to
# any of them is a category error — and all three reached the LINKER as a
# dangling symbol instead, because none of them is in `EMITTER_BUILTINS`.  That
# is the wrong message four stages late, and it is the shape the bytearray/bytes
# representation question was filed for and then closed (commit 37056734) —
# "the message you get is not the one that tells you what to do":
#
#   build: the image would bind 1 symbol(s) that nothing provides, so it could
#   not be loaded: ord. … (Provider check: asked the C library (dlsym).)
#
# for `ord("A")` — an ASCII case, which is the point: this is not an encoding
# question, it is a question this path never answered, and the encoding work in
# the block above had nothing to add to it.  Measured on both architectures, all
# three the same way, ASCII operands included.
#
# ONE of the three has an answer here and two do not, and the reason is the
# direction the value has to travel:
#
#   ord  character -> NUMBER.  A number is one word, which is what a formal
#        value already is, and for a LITERAL the character is known at compile
#        time — so the fold is `ord()` of the decoded text, with no machine
#        instruction and no libc call.  This is a new capability and it is the
#        unicode-relevant one: `ord("é")` is 233 and `ord("\U0001F600")` is
#        128512, neither of which is reachable by reading a byte.
#
#   chr  NUMBER -> character.  The answer is a NEW one-character object, and a
#        string value on this path is a `char *` into an image section mapped
#        read+execute and interned by content, so there is nowhere to put one.
#        That is `LENGTH_DEPENDENT_METHODS`'s missing buffer reached from the
#        other direction — and it is why `ord` folds where `chr` cannot, which
#        looks asymmetric until you ask where each answer would live.
#
#   hash  text -> NUMBER, and the number is NOT A FUNCTION OF THE TEXT.  CPython
#        randomises `str` hashing per process unless `PYTHONHASHSEED` is fixed,
#        so there is no answer to be right about: two runs of the same program
#        disagree by design.  Refusing is not a gap here; it is the only honest
#        option, and it is why `hash` belongs in this block rather than in a
#        list of constructs nobody has reached yet.

# The two with no lowering, named so the emitters' dispatch and this comment
# cannot come apart.  `ord` is deliberately NOT here: it has an arm.
TEXT_BUILTINS_WITHOUT_A_LOWERING = ("chr", "hash")


def ord_fold(args: list):
    """The code point of `args[0]` when the build knows it, else None.

    `ord()` of one character, which is CPython's whole rule — `ord("")` and
    `ord("ab")` are both a `TypeError`, so a literal of any other length is not
    folded and `text_builtin_refusal` says which of the two reasons it is.

    The DECODED text, through `string_literal_text`, so `ord("\xe9")` is 233 and
    not the two bytes' worth of something else.  That is the whole interaction
    with the TEXT ENCODING block above and it is worth stating: a code point is
    not a byte, so this is one of the two places (the other being `chr`) where
    the encoding question is a question at all.
    """
    if len(args) != 1:
        return None
    text = string_literal_text(args[0])
    if text is None or codepoint_count(text) != 1:
        return None
    return ord(text)


def text_builtin_refusal(name: str, args: list) -> str:
    """Why `name(...)` is refused here, with the reason that is specific to it.

    One function for the three so the two machines cannot word one construct
    differently, and one message per name because the three reasons have nothing
    in common: `ord`'s is about what the build can SEE, `chr`'s is about where
    the answer would LIVE, and `hash`'s is that CPython does not define one.
    Spelling them as one sentence would make at least two of them false.
    """
    # NOT named `spelled`: that is this module's function for spelling an
    # expression, and a local of the same name shadows it inside the
    # comprehension below — which is a NameError at build time rather than a
    # wrong answer, and one that only fires on the REFUSAL path, so the six
    # `ord` rows that answer would have stayed green.
    shown = ", ".join(spelled(a) for a in args) if args else ""
    if name == "ord":
        text = string_literal_text(args[0]) if len(args) == 1 else None
        if text is not None:
            return (
                f"ord({shown}) is refused: CPython's `ord` takes exactly ONE "
                f"character and this literal has "
                f"{codepoint_count(text)}, which is a TypeError there rather "
                f"than a number. Nothing to lower, and lowering it anyway — to "
                f"the first byte, or to the last — would be a wrong answer in "
                f"the shape of a right one")
        return (
            f"ord({shown}) is refused: `ord` is the code point of ONE "
            f"character, and this build cannot see what character "
            f"{shown or 'the operand'} holds — it is a name, a parameter or "
            f"a call, and its bytes are behind a `char *` only at run time. "
            f"The answer would be a NUMBER, which is the easy direction (a "
            f"formal value is one 64-bit word), but the code point of a "
            f"multi-byte character is not any of its bytes: `ord(\"é\")` is 233 "
            f"where the byte is 195, and `ord(\"\\U0001F600\")` is 128512 where "
            f"the bytes are four. Reading the byte would be right for ASCII "
            f"and wrong everywhere else, which is the byte-versus-character "
            f"answer this path does not give. What it CAN do: `ord` a string "
            f"LITERAL, whose one character is known at compile time and is "
            f"folded — or keep the text ASCII, where the byte is the character "
            f"and the arithmetic is written out")
    if name == "chr":
        return (
            f"chr({shown}) is refused: its answer is a NEW one-character "
            f"`String`, and a string on this path is a bare `char *` to bytes "
            f"in the image's own text section — which is mapped read+execute "
            f"and interned BY CONTENT, so there is nowhere to put one and "
            f"nothing to intern it into. `ord`, the other direction, is folded, "
            f"and the asymmetry is the representation rather than the effort: a "
            f"number is one word and a character is an object. This is the same "
            f"missing buffer `upper()`/`join()`/`replace()` are refused for "
            f"(`LENGTH_DEPENDENT_METHODS`), reached from the other side. What "
            f"this path CAN do: build the character from its code point as "
            f"bytes the program already has — `String([n as UInt8])` over a "
            f"list you built — for a character below 128, where one byte is "
            f"the whole of it")
    if name == "hash":
        return (
            f"hash({shown}) is refused, and the reason is not a gap: "
            f"CPython RANDOMISES the hash of a `str` per process unless "
            f"`PYTHONHASHSEED` is fixed, so two runs of one program disagree "
            f"by design and there is no value of the text for this to be right "
            f"about. A build that folded one would answer with a number CPython "
            f"disagrees with, and a build that called libc would be right about "
            f"neither. If what the program wants is a DICTIONARY KEY, use the "
            f"string as one — `d[{shown or 'k'}]` — where the comparison is "
            f"the content compare and the hash never appears")
    return (f"{name}({shown}) is a text builtin this path does not lower, "
            f"and no reason is recorded for it, which is a table entry with no "
            f"arm rather than a construct")


def frame_container_operand_refusal(op: str, spelled: str, struct_names):
    """Why a CONTAINER operation on a FRAME ADDRESS is wrong. Always a refusal.

    The container family — `base[i]`, `base[a:b]`, `x in base`, `for x in
    base` — is the one that reads offset 0 of its operand and calls it a count,
    and it is the one that did not ask what the operand was.  `len` asks, and is
    refused by `frame_receiver_escape_refusal`; a subscript does not ask, so a
    bare name the frame-holder analysis holds to be a frame address went
    straight into the blob walk.  Measured on BOTH architectures, on a
    four-field struct whose four fields running statements had written
    11, 22, 33, 44:

        return r[0]                ->  22    (the SECOND field)
        return r[1]                ->  33    (the THIRD field)
        var t = r[0:2]; return 0   ->  arm64 exit 1, x86-64 exit 0
        for i in r: s = s + i      ->  arm64 99, x86-64 53

    Four shapes, three distinct wrong answers, and one pair of them disagreeing
    between the architectures — which is the whole of the badness at once.  The
    numbers are not off by a little: `r[0]` returned a FIELD, because the count
    it bounds-checked against was another field, so which field an index reaches
    is decided by the values in the frame rather than by the index.

    The refusal is unconditional — there is no kind under which this is right,
    and a function that could return None would be a hole for the next caller to
    fall through.  A frame is a block of 8-byte slots in declaration order; a
    blob is a count word followed by elements.  They have no common reading, and
    the coincidence that makes a one-word struct work (`struct_fits_one_word`:
    the receiver IS the field, so there is no frame) is not available to a
    MULTI-field struct, which is the only kind this fires for.

    `op` names the operation, because the reader needs to know which of the four
    sites to look at and the two architectures reach this from different code.
    """
    who = ", ".join(struct_names) if struct_names else "this struct"
    return (
        f"{spelled} is a CONTAINER operation on a {who} FRAME ADDRESS, and a "
        f"frame is not a container. Every one of these lowerings starts by "
        f"reading eight bytes at offset 0 of its operand and calling the result "
        f"a COUNT — that is the blob's header word, and a frame has no header: "
        f"offset 0 of a frame is the struct's FIRST FIELD. Everything after "
        f"that is decided by those eight bytes rather than by the source: the "
        f"bounds check compares the index against a field's value, and the "
        f"element walk reads `base + 8 + 8k`, so `r[0]` returns the SECOND "
        f"field. Measured on BOTH architectures, on a four-field struct with "
        f"11, 22, 33, 44 written into it: `r[0]` returned 22 and `r[1]` "
        f"returned 33, and a slice of it exited 1 on arm64 and 0 on x86-64 — "
        f"two numbers nobody wrote, and a disagreement between the "
        f"architectures about the same source. A struct's value on this path "
        f"has no subscript, no slice, no membership test and no iteration; "
        f"read the field you mean (`r.a`), or iterate a list you built. A "
        f"ONE-word struct is a different case and is not this one: its receiver "
        f"IS its only field, so there is no frame and the container reading of "
        f"it is the only reading there is")


def framed_construction_structs(expr, decls: dict) -> list:
    """`[StructDef]` when `expr` is a CONSTRUCTION of a FRAMED struct, else [].

    The half of `frame_value_expr_structs` that needs no analysis at all:
    `P(1, 2)` names a struct this module declares, and `struct_is_framed(P)` is
    a property of `P`'s own field list, so the answer is known at compile time
    with no holder fixpoint and no interprocedural edge. Kept as its own
    function because the container family wants THIS arm alone — every one of
    its four sites already handles the bare-name arm through the holder table,
    and the construction arm is the only thing missing.

    **Why it is a refusal rather than a lowering.** `P(1, 2)` on this path is
    the ADDRESS of a frame of 8-byte slots, and every container lowering starts
    by reading eight bytes at offset 0 of its operand and calling them a count.
    Offset 0 of a frame is the struct's FIRST FIELD, so the count is a field's
    value and each element is read one slot later than the field it names.
    Measured on BOTH architectures, from green builds: `for v in P(1, 2)`
    printed `v=2` (CPython: `v=1` then `v=2`), `P(1, 2)[0]` printed `2`
    (CPython: `1`), and `a, b = P(1, 2)` printed `a=2` (CPython: `a=1`) or, with
    `x = 2`, two numbers on arm64 and a different pair on x86-64.

    A ONE-field struct is excluded for the reason every other refusal in this
    family excludes it: its receiver IS its field, so there is no frame.
    """
    if not (decls and isinstance(expr, F.CallExpr)
            and isinstance(expr.func, F.IdentExpr)):
        return []
    st = decls.get(expr.func.name)
    return [st] if st is not None and struct_is_framed(st) else []


def frame_value_expr_structs(expr, candidates: dict, decls: dict) -> list:
    """`[StructDef]` when `expr` is statically a FRAMED struct's value, else [].

    **The ONE recognition of "this expression holds a frame address" that is not
    the holder table.** The holder table (`formal/build.py`'s `by_name`) answers
    it for a BARE NAME, which is the shape every one of its consumers has been
    asked about, and that is why this function exists rather than a wider
    `candidates`: a CONSTRUCTION of a struct this module declares is equally
    decidable, at compile time, with no fixpoint and no interprocedural edge —
    `struct_is_framed(P)` is a property of `P`'s own field list.

    Two shapes, and the second is the one this was written for:

      * a bare name in `candidates` — the holder analysis's answer, passed
        through unchanged so there is still exactly one table behind it;
      * a call to a bare name that is a struct in `decls` with more than one
        field — `P(1, 2)`, which on this path is the ADDRESS of a frame of
        8-byte slots, not a value. `framed_construction_structs` is that arm
        on its own, because the container family wants it without the name arm
        it already has.

    **Why the construction arm was missing is a measured wrong answer.**
    `a, b = P(1, 2)` on a two-field struct reached the blob unpack, which reads
    offset 0 as the arity and `base + 8 + 8k` per target, so it answered
    `a=2` where CPython answers `a=1` (and with `x = 2` it printed two numbers
    on arm64 and a DIFFERENT pair on x86-64, both exit 0). The holder table
    could not catch it because the expression has no name in it, and the four
    container lowerings that already ask the question are all bare-name-only by
    the deliberate rule their own docstrings give (`_refuse_frame_container_
    operand`: `h.x` is a field and reading that as a blob is what a declared
    `List` field is FOR, so only the ADDRESS is refused). A construction is not
    that exception — it is not a field, and it is unambiguously the address.

    A ONE-field struct is excluded for the reason every other refusal in this
    family excludes it: its receiver IS its field, so there is no frame and the
    container reading of it is the only reading there is.
    """
    if isinstance(expr, str):
        return list(candidates.get(expr) or ())
    if isinstance(expr, F.IdentExpr):
        return list(candidates.get(expr.name) or ())
    return framed_construction_structs(expr, decls)


def frame_unpack_operand_refusal(spelled: str, struct_names) -> str:
    """Why `a, b = <a struct's value>` is wrong. Always a refusal.

    The container family's FOURTH member, and the one it was missing: the
    others are `base[i]`, `base[a:b]`, `x in base` and `for x in base`, and all
    four already ask `_refuse_frame_container_operand` whether their operand is
    a frame address. A tuple assignment reads its operand the same way — the
    blob header word at offset 0 is the arity check, and each target is loaded
    from `base + 8 + 8k` — and asked nobody.

    Measured on BOTH architectures, from green builds, on a two-field struct
    holding `x = 2, y = 99`:

        p = P(2, 99)
        a, b = p
        printf("a=%d b=%d", a, b)

    | build | arm64 | x86-64 | CPython |
    |---|---|---|---|
    | arity happens to match (`x` is 2) | `a=99 b=0` | `a=99 b=171778048` | `a=2 b=99` |
    | arity does not match (`x` is 1) | exit 1, nothing printed | exit 1 | `a=1 b=2` |

    Four wrong answers in one construct, and the second row is the worse half:
    **the exit is decided by a FIELD'S VALUE**, so `p = P(1, 2); a, b = p`
    exits 1 with no message where CPython prints `a=1 b=2`, while
    `p = P(2, 99)` prints two numbers neither of which the source wrote. The
    two architectures disagree on the second target, so the same source is a
    different wrong answer per architecture — which is why this cannot be fixed
    by making the load agree.

    `spelled` names the RHS as the reader wrote it and `struct_names` is the
    holder table's own answer, the same argument list
    `frame_container_operand_refusal` takes, because the diagnosis is the same
    one and a second wording for it would be a second thing to keep true.
    """
    who = ", ".join(struct_names) if struct_names else "this struct"
    return (
        f"the right-hand side of a tuple assignment is {spelled}, which is a "
        f"{who} FRAME ADDRESS. This is the container family's fourth member and "
        f"the one that used to ask nothing: the blob unpack reads eight bytes at "
        f"offset 0 of its operand and calls them an ARITY, then loads each "
        f"target from `base + 8 + 8k`. A frame has no header — offset 0 is the "
        f"struct's first FIELD — so the arity check compares your target count "
        f"against a field's value and each target is loaded from one slot later "
        f"than the field it names. Measured on BOTH architectures on a "
        f"two-field struct holding `x = 2, y = 99`: `p = P(2, 99); a, b = p` "
        f"printed `a=99 b=0` on arm64 and `a=99 b=171778048` on x86-64 where "
        f"CPython prints `a=2 b=99`, and with `x = 1` the same program exits 1 "
        f"printing nothing where CPython prints `a=1 b=2` — so whether the "
        f"program runs at all is decided by a field's value. Unpack the fields "
        f"you mean, one per target (`a = p.x; b = p.y`), or unpack a list you "
        f"built")


# The relational operators, and the reason they are named here rather than
# spelled at the call sites: `==` and `!=` have a CORRECT answer on a frame
# address (it is CPython's inherited `object.__eq__`, and two live objects of
# one struct cannot share an address — `eq_no_declared_dunder_stays_identity` in
# `test_formal_run.py` is the guard), while the four ORDER operators have none
# at all.  A set rather than a constant for the same reason `_COMPARISON_OPS`
# is one: `in`/`not in` are in that tuple and are not in this.
_FRAME_ORDER_OPS = ("<", ">", "<=", ">=")


def frame_order_operand_refusal(op: str, operand, struct_names) -> str | None:
    """Why ORDERING a FRAME ADDRESS by `<`/`>`/`<=`/`>=` is wrong. A refusal.

    The sibling of `frame_container_operand_refusal` and
    `string_binary_refusal`, and the third arm of the same shape: a struct of
    more than one field is a POINTER to a frame of 8-byte slots
    (`struct_is_framed`), and every operator that reaches the flag-setting
    compare is therefore operating on an ADDRESS.  For `+`, `-`, `&`, `|`, `%`
    and the shifts the address is a wrong NUMBER; for `<`, `>` and their
    non-strict forms it is a wrong BRANCH, which is the worse of the two shapes
    because a correct program takes the wrong path and nothing downstream can
    tell.

    Measured on BOTH architectures, from a green build, on
    `struct Pair { var a: Int; var b: Int }` with a field-wise `__eq__` and two
    objects holding equal field values:

        printf("lt=%d gt=%d le=%d ge=%d", x < y, x > y, x <= y, x >= y)
        ->  lt=1 gt=0 le=1 ge=0

    Four relations decided, none of them by anything in the program — by which
    frame the allocator put `x` in relative to `y`.  Reordering two
    independent statements reverses every one of them.  CPython answers the
    same program with `TypeError: '<' not supported between instances of
    'Pair' and 'Pair'`, and the `__eq__` the struct declares says nothing about
    ordering, so there is no dunder to dispatch to either: a three-way compare
    over the fields has no lowering here, and a two-word compare of addresses is
    not an approximation of one — it is an answer about memory.

    **`==` and `!=` are deliberately NOT here**, and the reason is the guard
    above: an address compare is the right answer for a struct that declares no
    `__eq__`, and for one whose dunder cannot be lowered across two candidate
    layouts `formal/build.py` refuses the comparison by name rather than
    leaving it to this.  `is`/`is not` likewise stay: they ask whether two
    names hold one OBJECT, which on this path is the pointer.

    `operand` is the NODE, because the emitters' question is "is this a bare
    name the holder table holds", and `struct_names` is what its frame could be
    — the same list `frame_container_operand_refusal` prints, because a refusal
    that does not name the struct is one the reader has to re-derive.
    """
    if op not in _FRAME_ORDER_OPS or operand is None:
        return None
    who = ", ".join(struct_names) if struct_names else "this struct"
    return (
        f"`{op}` orders the ADDRESS of a {who} FRAME, and an address has no "
        f"order the source asked for: {spelled(operand)} here is not a value, "
        f"it is where a block of 8-byte slots happens to live. `<`, `>`, `<=` "
        f"and `>=` therefore compare two words that were never in the program, "
        f"and which way they come out is decided by where the allocator put "
        f"the two objects — reordering two independent statements reverses "
        f"every one of them. Measured on BOTH architectures, on two objects of "
        f"a two-field struct holding EQUAL field values, with a field-wise "
        f"`__eq__` declared: `lt=1 gt=0 le=1 ge=0`, four relations decided by "
        f"nothing in the program. This path has no three-way compare over a "
        f"struct's fields to lower a declared ordering to, and comparing "
        f"addresses in the other direction is not an approximation of one. "
        f"CPython refuses the same program (`'<' not supported between "
        f"instances`) for the same reason. `==` and `!=` are NOT this refusal: "
        f"an address compare is the right answer for a struct that declares no "
        f"comparison dunder, and one that does is dispatched to it. What to "
        f"write instead: compare a FIELD (`{spelled(operand)}.a < "
        f"{spelled(operand)}.b`), or declare an ordering method — this path "
        f"has no dispatch for one yet either, and the same refusal would name "
        f"that"
    )


def non_container_element_refusal(op: str, spelled: str, function: str,
                                  evidence: str = None) -> str:
    """Why an ELEMENT of a value that is not a container is refused. A refusal.

    The third arm of the family `frame_container_operand_refusal` and
    `string_iteration_refusal` belong to, and the only one whose operand is an
    ordinary WORD: the other two are a frame address and a `char *`, both of
    which the analysis can name, while `a = 5` is neither and so matched no arm
    of it. Every container lowering reads eight bytes at offset 0 of its base
    and calls the result a COUNT, then reads or writes at `base + 8 + 8k` — so
    for an integer the address is the integer:

        def main(n: Int) -> Int:
            var a = 5
            a[0] = 1
            printf("a=%d", a)

    which stores at address 5. Measured on BOTH architectures: the build is
    green and the image dies of SIGSEGV, exit 139. The read and the slice of the
    same base fault the same way, which is why this is asked from the emitters'
    subscript AND slice choke points rather than from the store alone. That is
    the whole of the badness — a program that compiles, links, runs, and faults
    on its fifth statement, which is the class of defect this backend's refusal
    discipline exists to convert into a message, and the class
    `frame_container_operand_refusal` was written for.

    **What is refused, and what is deliberately not.** A base that a statement
    of THIS function bound to something whose kind is an integer **on that
    statement's own evidence**. That qualifier is load-bearing and it is
    `ValueKinds.own_shape_kind`, which is what separates `a = 5` from three
    shapes that carry the same `INT_KIND` while being containers: an
    unannotated parameter (a word arriving from a caller is a word, so every
    container-taking function in the corpus has one), a CALL result whose callee
    declares no return type, and a loop variable over a name. The first is
    `def at(xs, i): return xs[i]`; the second is a `get(self) -> List[Int]`
    method's result; the third is `for row in rows: printf("%d", row[0])`. All
    three built and answered correctly before this refusal existed, so a
    classification that read the default as a claim would have refused correct
    programs — the failure mode a wrong answer causes everywhere else in this
    backend, and the one this backend exists to prevent. Both backends ask
    `own_shape_kind` at their choke points, so a read, a store and an augmented
    assignment all get this answer and the two architectures cannot disagree
    about which bases qualify.

    **`evidence` is the DECLARED half, and it is the same refusal.** A base no
    statement of the function bound — a PARAMETER, which is the case
    `own_shape_kind` has nothing to say about by construction — that the
    declaration calls an integer (`def f(e: Int): return e[0]`) is the same
    construct with the answer written down instead of inferred, and it is
    refused here rather than by a message of its own: one construct, one
    sentence, and the alternative is two diagnostics for one mistake that differ
    only in which line of the source they blame. Measured before either existed,
    on both architectures and byte-identical: that call answered the blob
    header's neighbour (7 where the caller held 53) and CPython raises
    `TypeError`, so there is no reading of it that is right. The clause is
    passed rather than derived because the two callers have it in different
    shapes — `own_shape_kind` has a NAME, the declaration has TEXT — and
    interpolating one of them into the other's wording is how a message ends up
    claiming a binding that did not happen.

    `op` is the only other thing that varies between the call sites — `a
    subscript`, `a slice` — and it is a parameter rather than a constant so the
    message says which of them the reader is looking at, for the same reason
    `frame_container_operand_refusal` takes one.
    """
    bound = evidence or f"a value this function bound to an integer"
    return (
        f"{op} of `{spelled}` asks for a container element, and `{spelled}` "
        f"is {bound}. Every container "
        f"lowering starts by reading eight bytes at offset 0 of its base and "
        f"calling the result a COUNT — that is the blob's header word — and "
        f"then reads or writes at `base + 8 + 8k`, so the element address "
        f"here is the integer itself plus 8. Measured on BOTH architectures, "
        f"this builds, links, and then dies of SIGSEGV at run time with the "
        f"build green, because it reads or stores through a number rather than "
        f"through an address into anything. Refused here rather than emitted: "
        f"an integer is the one kind of word on this path whose container "
        f"reading is not merely wrong but unmapped. What the same source can "
        f"do instead: index a list or tuple you built (`xs[i]` over "
        f"`[1, 2, 3]`), or take the container as a PARAMETER of {function}, "
        f"where the caller's value decides and the subscript is answered for "
        f"its callers too"
    )


#: The kinds a CONTAINER OPERATION cannot be lowered against when its base is a
#: struct FIELD. `None` is deliberately absent, and its absence is the whole of
#: the narrowing this family is for: an unclassified slot is a word this image
#: cannot read, and refusing it would refuse every `h.xs[i]` on a field whose
#: declaration is in another module.
#:
#: **`FRAME_KIND` was IN this set on 2026-10-04 and is deliberately OUT of it
#: again, and both positions have a measurement.**  It went IN on the argument
#: that a frame-valued field read as a container is a wrong ANSWER rather than a
#: fault, and the argument was answered with numbers rather than with taste:
#:
#:     struct Deep:  var x: Int;  var y: Int
#:     struct Wrap:  var d: Deep;  var t: Int
#:     w.d.x = 3 ; w.d.y = 4 ; printf("%d", w.d[0])
#:
#: | | arm64 | x86-64 |
#: |---|---|---|
#: | `w.d[0]` | **4**, exit 0 | **4**, exit 0 |
#: | `h.d[1]` where `Deep` declares `__getitem__` | **0**, exit 0 | **-1927469536**, exit 0 |
#:
#: Two architectures, two different wrong answers, exit 0. The arithmetic is why:
#: the blob walk reads `count = mem_read_u64(w + 0)`, which is `Deep`'s FIRST
#: FIELD, and then `addr = w + 8 + 8·count` — so which field an index reaches is
#: decided by the values in the frame rather than by the index. (CPython refuses
#: the shape outright, `TypeError: 'Deep' object is not subscriptable`, so there
#: is no oracle number; that is the other half of why a refusal and not a better
#: lowering. `frame_slot_element_refusal` below carries the full argument.)
#:
#: It is OUT because of the OTHER half of the same census, which is the one that
#: was misattributed the first time. Every `X.<field>[i]` site classified by its
#: SLOT's kind (`struct_field_kind`) rather than by its annotation alone, with a
#: type name a shared table already classifies left out of the module's own
#: struct table:
#:
#: | slot kind | sites |
#: |---|---|
#: | nothing reachable in the file (a module attribute, or a struct from another module) | 404 |
#: | an IDENTITY type ctor (`String` / `Pointer` / `UnsafePointer` / …) | 65 |
#: | a declared name this path has no kind for | 62 |
#: | a container (`List` / `Dict` / `Tuple` / …) | 3 |
#: | a frame | 2 |
#: | a POINTER | 1 |
#: | **an integer or a type tag** | **0** |
#:
#: 537 sites over 252 files, and **the whole frame row is two sites, both of them
#: `self._dict[key]`** in `std/collections/dict.mojo`'s own
#: `StringDict.__getitem__`/`__setitem__`. That is the same two sites the earlier
#: 2 642-site reading put at 7, and the difference is a name collision rather
#: than a corpus change: a `Dict[...]` annotation read through the module's own
#: `struct Dict` — which is how the KIND axis classifies it, deliberately, because
#: a field declared a struct of this module does hold that struct's address.
#:
#: **So widening this set refuses a dict lookup that WORKS, and that is the whole
#: reason it stays out.**  The two axes disagree on `self._dict` and both are
#: right: the kind axis (`struct_field_kind`) answers `FRAME_KIND` because the
#: annotation names this module's `struct Dict`, while the dict axis
#: (`ValueKinds::is_dict_value` → `frame_slot_field_is_dict` →
#: `declared_type_is_dict`) answers "a dict" from the same annotation read
#: against `DICT_TYPE_NAMES`. The dict axis is asked FIRST
#: (`_is_dict_key_subscript`, then the string path), and this set is asked before
#: both — so a `FRAME_KIND` member here fires on the two sites whose dict answer
#: is the one that keeps `std/collections/dict.mojo` compiling. `h.d[1]`'s wrong
#: numbers are real and are refused, one gate later, by
#: `frame_slot_element_refusal` — which is why the `__getitem__` row in
#: `test_formal_x86_64_parity.py` is refused under THIS arrangement too.
NON_CONTAINER_SLOT_KINDS = (INT_KIND, TYPE_KIND)

#: The kinds the BLOB fallback may not read an element out of, asked AFTER the
#: string and dict readings have been dispatched.  `FRAME_KIND` is the whole of
#: it, and the measurement behind it is `frame_slot_element_refusal`'s.
FRAME_SLOT_ELEMENT_KINDS = (FRAME_KIND,)


def frame_slot_element_refusal(op: str, base_kind, spelled_base: str) -> str | None:
    """Why a container operation on a FRAME-valued struct FIELD is refused, or None.

    **The THIRD member of the container-operand family, and the one the other
    two are blind to by construction.**  `_refuse_frame_container_operand`
    (`frame_container_operand_refusal`) is BARE-NAME only and
    `_refuse_scalar_container_operand` (`scalar_container_base_evidence` /
    `scalar_container_base_refusal`) covers the scalar field kinds; each says
    why.  A field whose DECLARED type is a framed struct of this module holds
    that struct's ADDRESS, so both of them decline it and the container walk
    reads it:

        struct Deep:
            var x: Int
            var y: Int
        struct Wrap:
            var d: Deep
            var t: Int
        var w = Wrap()
        w.d.x = 3
        w.d.y = 4
        printf("%d", w.d[0])

    which is this arithmetic, and the second line of it is the whole defect:

        count = mem_read_u64(w + 0)        # Deep's slot 0 == x == 3
        addr  = w + 8 + 8*count            # w + 32
        value = mem_read_u64(addr)

    `w + 32` is PAST `Deep`'s two slots, so the answer is whatever the frame's
    scratch region holds next to it.  Measured on both architectures: **4**, on
    both, and 3 is what a reader means by `w.d[0]` — `w.d` is `Deep`'s frame base
    and slot 0 of that frame is `x`.  CPython refuses the shape outright
    (`TypeError: 'Deep' object is not subscriptable`), so there is no oracle and
    the program is one no reader writes on purpose; that is exactly why it must
    not be answered with a number out of the frame's scratch region.

    **A REFUSAL and not a lowering, decided, with the alternatives named.**  A
    load at `base + 8i` is what `w.d.x` already is one level up, so it is
    available; it is declined for two reasons that are both facts rather than
    preferences.  First, CPython has no such operation
    (`TypeError: 'Deep' object is not subscriptable`), so there is no oracle for
    a lowering to be right about.  Second, and decisively: **when the declared
    struct declares `__getitem__` the subscript is a METHOD CALL and not a slot
    load**, so `base + 8i` is not one lowering but two, and the second is
    dispatch — a mechanism this backend does not have for a field's declared
    type.  Measured, and the measurement is why the alternative looks like a fix
    at all: `h.d[1]` with `Deep.__getitem__` returning `a + k` printed **0** on
    arm64 and **-1927469536** on x86-64, exit 0 on both.  Two architectures, two
    different wrong answers, and neither of them is `base + 8i`.

    The index is not a field NAME either, which is a third and weaker reason: slot
    `i` of the frame is the struct's `i`-th declared field for `i < len(fields)`,
    and past that it is a spill slot or scratch — a value with no field behind it,
    so a lowering would have to invent the bound that makes it an answer.  And the
    two sibling rules already refuse a non-container base (a bare name holding a
    frame, and a field declared an integer or a type tag), so a third answer for
    the same mistake is a decision this path would then have to keep consistent.
    Refusing also keeps the emitter side free of a new arm on BOTH architectures,
    which is why the two cannot come to answer this differently.

    **Asked AFTER the string and dict readings, and that placement is the
    corpus.**  `FRAME_KIND` is `frame_slot_element_refusal`'s only kind, and the
    emitters call it where the BLOB fallback begins — after
    `_is_dict_key_subscript` and after the string path.  It is not in
    `NON_CONTAINER_SLOT_KINDS`, which is asked before both, and the two axes
    disagree on the one base that makes that matter: `self._dict` is a FRAME on
    the kind axis (`struct_field_kind` reads its `Dict[...]` annotation against
    the module's own `struct Dict`) and a DICT on the dict axis
    (`ValueKinds::is_dict_value` → `frame_slot_field_is_dict` →
    `declared_type_is_dict` reads the same annotation against `DICT_TYPE_NAMES`).
    The dict axis is the one asked first, and it is the one that keeps
    `std/collections/dict.mojo`'s `StringDict` compiling.

    Measured with `tools/formal_frame_slot_subscript_census.py` over this
    repository and the stdlib, every `X.<field>[i]` site classified by its
    field's declared type:

    | declared kind | sites |
    |---|---|
    | the receiver this file cannot type (the emitter answers `None` too) | 803 |
    | a chain — `a.b.c[i]`, whose outer field's type is the type of the WORD | 470 |
    | `self.<field>`, with no declared type to read | 143 |
    | a container (`List` / `Dict` / `Tuple` / …) | 26 |
    | an unclassified slot | 1 |
    | **a framed struct of the module** | **2** |

    and **both of the two are the dict case**: `self._dict` in
    `std/collections/dict.mojo`'s `__getitem__` and `__setitem__`.  Which is why
    the set above is one kind and not two, and why the placement after the dict
    dispatch is load-bearing rather than tidier: the census says the corpus has
    nothing to lose, and the placement is what makes that true rather than a
    claim about it.  `NON_CONTAINER_SLOT_KINDS` carries the SECOND reading of the
    same corpus — classified by the slot's kind rather than by its annotation,
    which is the reading that found the `h.d[1]` numbers above and still leaves
    the frame row at the same two `self._dict[key]` sites.
    """
    if base_kind not in FRAME_SLOT_ELEMENT_KINDS:
        return None
    return (
        f"{op} of `{spelled_base}` asks for a container element, and "
        f"`{spelled_base}` is a struct field declared to hold a FRAME — the "
        f"address of another struct's block of slots, not a container. Every "
        f"container lowering starts by reading eight bytes at offset 0 of its "
        f"base and calling the result a COUNT, and offset 0 of a frame is that "
        f"struct's FIRST FIELD: `count` is the first element's own value, and "
        f"the element address computed from it lands past the frame's fields, "
        f"in whatever its scratch region holds next to it. Measured on BOTH "
        f"architectures, `{spelled_base}[0]` printed 4 where the frame's first "
        f"field was 3 — a wrong answer on both machines, which is what makes it "
        f"worse than a fault. Refused here rather than emitted. What the same "
        f"source can do instead: read the field by name, which is a load at the "
        f"frame's own offset and is answered for the frame's type — "
        f"`{spelled_base}`'s FIRST FIELD for `[0]`, its second for `[1]`"
    )


def scalar_container_base_evidence(expr, kind, vkinds=None) -> str | None:
    """Why `expr` is provably a SCALAR and not a container, or None.

    **The one reader of "this base cannot be a container", and therefore the one
    place the two architectures can be made to agree about it.** It answers
    `own_shape_kind`'s question for a base that is not a NAME, and it is the
    FIELD half of `frame_container_operand_refusal` and
    `non_container_element_refusal`, both of which are BARE-NAME-only, each
    saying why: `h.x` is a 64-bit field and reading it as a blob is what a
    declared `List` field is FOR. That reasoning is right about a field whose
    DECLARED type says nothing, and it is how a slot that says it holds a
    number reached the blob walk.

    Three arms, and every one of them is a CLAIM rather than a default — which
    is the whole difficulty, because `INT_KIND` is this model's default for a
    word and reading it as a claim is what `own_shape_kind` exists to prevent
    (its own table: an unannotated parameter, a call result and a loop target
    all carry `INT_KIND` while being containers, and all three built and
    answered correctly).

      * **A struct FIELD whose DECLARED type is a scalar** —
        `NON_CONTAINER_SLOT_KINDS`, and the gate is the kind rather than the
        base's SPELLING because a kind is returned only where the source says
        what the slot holds. Why `None` is excluded from that tuple is measured
        rather than argued, and so is why `FRAME_KIND` is: the census, its
        corrected reading and its earlier wrong one are all in
        `NON_CONTAINER_SLOT_KINDS`' own comment, and the short version is that
        the frame row is `self._dict[key]` in `std/collections/dict.mojo` — the
        one base in the corpus whose dict reading is dispatched before this
        function is asked. `frame_slot_element_refusal` owns the frame, asked
        after those readings, which is why this is three arms and not four.
      * **A scalar LITERAL.** `5[0]`, `1.5[i]`, `True[0]`. The node IS the
        value, so there is no default and no declaration to disagree with, and
        nothing about it can be a container. This arm is why the shape reached
        the emitter at all: a one-field struct's sole field collapses onto its
        receiver (`_rewrite_self_fields`) and the receiver then folds to the
        field's materialized class-level default, so `s.n[0]` arrives here
        spelled `5`.
      * **A TYPE VALUE.** `kind == TYPE_KIND`, which comes from
        `type_tag_for_name` and from the `declared_kind` hook — a field
        declared `DType`, or a construction's argument. It is never a fallback,
        and a tag word is as unmapped as an integer: a type has no elements and
        no count. This is the one arm both halves of the family reach for the
        same construct, which is why it is asked once here rather than once in
        each.

    **The frame is NOT refused here, and that is a placement rather than an
    omission.** A field declared a framed struct of this module holds that
    struct's ADDRESS, so reading it as a container is a wrong answer rather than
    a fault (`w.d[0]` printed `Deep`'s SECOND field where a reader means its
    first, on both architectures), and the whole of the reasoning for refusing it
    — the arithmetic, the `__getitem__` measurement, and why a load at `base + 8i`
    is not offered instead — is `frame_slot_element_refusal`'s. It is asked one
    step later because `self._dict[key]` classifies as a frame on the KIND axis
    and as a dict on the dict axis at the same time, and the dict reading is the
    one that keeps the stdlib's `StringDict` compiling. See
    `NON_CONTAINER_SLOT_KINDS`.

    **Not refused, and the reasons are the same two the rest of the family
    gives.** `None` for the kind — an unclassified base keeps the container
    reading, which is load-bearing for the 284 subscripts over an unannotated
    parameter that `subscript_base_lowering`'s own census measured.
    `INT_KIND` reached any other way is also None, because that is the default.
    A `StringLiteral` is not a scalar here: a string's subscript IS a byte
    load, and both emitters take that path above the container one.

    **A SUBSCRIPT OF A LIST WHOSE ELEMENTS ARE NUMBERS is the fourth arm, and it
    is the one the emitters cannot answer from `kind` alone.** `v = [1]`;
    `v[0][0]` asks the container walk for an element of `v[0]`, whose kind is
    `int` — but that kind is `subscript_element_kind(own_shape_kind("v"))`,
    i.e. it comes from the LITERAL's element kinds, and a list can be appended
    to after the literal. So this arm is guarded by two claims and neither is
    `kind`:

      * the BASE name's OWN SHAPE is a list whose element kind is a number
        (`ValueKinds.own_shape_kind`, which returns None for a conflict, an
        unannotated parameter, a call result and a loop target — so none of
        those is refused by this arm); and
      * that name is not a receiver of `append` anywhere in this function
        (`ValueKinds.appended_names`), because `v = [1]; v.append([2]); v[1][0]`
        is CORRECT on both architectures and the literal's element kind has
        stopped describing the list by then.

    Why it is needed at all, measured on both architectures: the inner subscript
    already produces a word, and asking THAT word for an element reads eight
    bytes at offset 0 (the word itself) as a COUNT and then dereferences the
    scalar plus 8 — SIGSEGV, exit 139, with a green build. The named-base
    refusal for the same mistake already exists and describes the fault
    exactly; it simply never asked this base shape.

    `vkinds` is optional because the early `formal/build.py` pass has already
    resolved its base to a struct FIELD and asks the question without a
    function's kind maps. None keeps this arm inert, which is the conservative
    direction: the emitters pass their own `ValueKinds`.
    """
    field = isinstance(expr, F.MemberExpr)
    if kind == TYPE_KIND:
        if field:
            return ("a struct field declared to hold a TYPE TAG — a hash of a "
                    "type's name — which is a number, and a tag has no "
                    "elements and no count")
        return ("a TYPE value — the tag word this path gives a type name, and a "
                "tag is a hash of a type's name — so it carries no count at "
                "offset 0 and no memory behind it either, and there is nothing "
                "for the container walk to read")
    if field and kind in NON_CONTAINER_SLOT_KINDS:
        return ("a struct field declared to hold an integer — a frame slot is "
                "ONE word, and a subscript needs a pointer plus a stride, so "
                "there is nothing in the slot to compute a stride from, which "
                "is why this is a refusal rather than a cheaper index — and it is "
                "classified as that because the SOURCE says so, not because "
                "the image could read it")
    if isinstance(expr, (F.IntLiteral, F.FloatLiteral, F.BoolLiteral)):
        return ("a number — the literal carries no count at offset 0 and no "
                "memory behind it, so there is nothing for the container walk "
                "to read")
    if (isinstance(expr, F.SubscriptExpr)
            and isinstance(expr.obj, F.IdentExpr) and vkinds is not None):
        name = expr.obj.name
        shape = vkinds.own_shape_kind(name)
        elem = subscript_element_kind(shape) if shape is not None else None
        if is_number_kind(elem) and name not in vkinds.appended_names():
            return (f"a subscript of `{name}`, whose every binding in this "
                    f"function is a list literal of numbers — so the element "
                    f"is ONE word, with no count at offset 0 and no memory "
                    f"behind it for the container walk to read")
    return None


def scalar_container_base_refusal(op: str, spelled_obj: str, evidence: str,
                                  function: str) -> str:
    """Why a base this path PROVES to be a scalar is refused as a container.

    The fourth arm of the family `frame_container_operand_refusal`,
    `string_iteration_refusal` and `non_container_element_refusal` belong to,
    and the one whose operand is neither an address nor a `char *` nor a word a
    statement of this function bound to a number: it is a word the SOURCE says
    is a number or a type, whatever the name it arrives under.

    **What it was, measured on both architectures, and the reason this is a
    refusal rather than a better lowering.** `s.n[0]` and `s.d[0]` on a struct
    whose only field is annotated `Int` / `DType`:

    | | arm64 | x86-64 |
    |---|---|---|
    | `var n: Int = 5` ; `printf("%d", s.n[0])` | refused — "subscript base must be a list/tuple name or literal … (got IntLiteral)", which is false about the file: the source says `s.n`, and `s.n` IS a field | **SIGSEGV, exit 139** |
    | `var d: DType = 5` ; `printf("%d", s.d[0])` | the same refusal | **SIGSEGV, exit 139** |
    | `var d: DType` + `__init__(out self, v: DType)`, `S(DType.int32)` | **SIGSEGV, exit 139** | **SIGSEGV, exit 139** |

    The node that gate was handed is, by then, the slot's MATERIALIZED default,
    so the literal in the arm64 sentence is a residue of the class-constant
    rewrite rather than anything the reader wrote — which is why
    `build._refuse_container_operands_on_scalar_slots` asks the same reader one
    pass EARLIER, where `s.n` is still `s.n`, and this is the second line
    rather than the only one (commit f0df70b2 for the early half, ba63213c for
    this one).  A
    container lowering reads eight bytes at offset 0 of its base and calls that a
    COUNT, so a `5` and a type tag are both read as a length and both used as an
    address.  CPython refuses all three rows above
    (`TypeError: 'int' object is not subscriptable`), so every one of them is a
    program no reader would write on purpose — which is the point: the answer
    is a refusal on both machines and one machine was dereferencing a `5`.

    `non_container_element_refusal` is not reused because it is a DIFFERENT
    claim: it says the base is a word a statement of this function bound to a
    number, and this one says the source establishes the base as a number or a
    type without naming a binding — which is the whole difference between
    `var a = 5; a[0]` and `s.n[0]`, and a reader who is handed the first
    message for the second is sent to look for a binding the program does not
    have.

    `op` is the parameter `non_container_element_refusal` takes and for its
    reason: one message, said four ways, so a read, a store, an augmented
    assignment, a slice, a membership test and a for-in iteration all answer
    with the same sentence and the two backends cannot part company.
    """
    return (f"{op} of `{spelled_obj}` asks for a container element, and "
            f"`{spelled_obj}` is {evidence}. Every container lowering starts by "
            f"reading eight bytes at offset 0 of its base and calling the "
            f"result a COUNT, then reads at `base + 8 + 8k`, so the element "
            f"address here is the scalar itself plus 8. Measured on BOTH "
            f"architectures: this builds, links, and dies of SIGSEGV at run "
            f"time with the build green, because it reads through a scalar "
            f"rather than through an address into anything. Refused rather "
            f"than emitted: a scalar's container reading is not merely wrong, "
            f"it is unmapped, and no subscript spelling of one means anything "
            f"else. What the same source can do instead: index a list or a "
            f"tuple you built, take the container as a PARAMETER of {function} "
            f"where the caller's value decides, or pass the value itself to the "
            f"function that wants it")



def string_iteration_refusal(where: str, function: str) -> str:
    """Why ITERATING a `char *` is refused. Always a refusal.

    The sibling of `frame_container_operand_refusal`, and the same mistake:
    the blob walk reads eight bytes at offset 0 of its operand and calls the
    result a COUNT, and a NUL-terminated string has no header word — the
    "count" is the first eight bytes of text. The bounds check then passes on
    those bytes and the element walk reads `base + 8 + 8k`, which is the
    middle of the string and then whatever the text section puts after it.

    Measured on the real binaries, on `for c in "abc"` (three iterations):

        x86-64   returns 97      -- 'a', the first byte, read as the count
        arm64    SIGBUS (-10)   -- and the two architectures disagree

    and on `[a + b for a in "abc" for b in "de"]` both exit 1, from the
    comprehension's capacity guard catching a count of 0x61626361-ish.

    There is no kind under which this is right, and it is not a case where a
    refusal loses a program that worked: `len(s)` answers (4, on both), and
    `s[i]` is a byte load on both. Iterating a string needs a LENGTH this
    representation does not carry, so the honest answer is to say so at build
    time rather than to return a number nobody wrote — or, on arm64, to die
    on a signal.
    """
    return (
        f"iterating a string is a CONTAINER operation on a char *, and a char "
        f"* has no count. This lowering reads eight bytes at offset 0 of the "
        f"iterable and calls the result the element COUNT — that is a blob's "
        f"header word, and a string's first eight bytes are TEXT: measured on "
        f"both architectures, `for c in \"abc\"` returned 97 on x86-64 ('a' as "
        f"the count) and died of SIGBUS on arm64. `len(s)` and `s[i]` both work "
        f"and are unaffected; to walk the characters, build a list of them "
        f"first ([c for c in <a list>]) or iterate that list")


def string_operand_is_string(kind) -> bool:
    """True when `kind` says the value is a `char *` to NUL-terminated bytes.

    The single question both string lowerings ask, so that `len` and `==`
    cannot end up disagreeing about which values are strings — the
    `string_method_yields_string` lesson, one level down.

    **THREE kinds answer it, and the second and third are why this is a function
    rather than a comparison.** `FOREIGN_BYTES_KIND` is a `char *` too — the same
    representation, the same `strcmp`, the same `%s`, the same `strlen` — and
    the ONLY construct whose CPython answer is not a property of the bytes is a
    CHARACTER COUNT, which `len_operand_lowering` refuses on its own row.
    `POINTER_KIND` is a C pointer a declared return type established, and it is a
    `char *` for every question asked HERE; the one place it differs is
    truthiness, which `truthy_lowering` asks before this predicate (a null test,
    not `strlen`). So the
    admission has to be here rather than in each consumer: spelled `== STR_KIND`
    in nine places, the other two kinds would have silently lost string methods,
    string equality, `%s` and `print` — and it would have lost them
    DIFFERENTLY on the two architectures the moment one copy was updated and the
    other was not, which is the failure `string_method_yields_string` was filed
    for. `subscript_element_kind` reads this same predicate for the same reason.
    """
    return kind in (STR_KIND, FOREIGN_BYTES_KIND, POINTER_KIND)


def is_non_pointer_string(kind) -> bool:
    """True when `kind` is a string THIS path reads as TEXT and not as a pointer.

    `string_operand_is_string` admits `POINTER_KIND` so a C pointer answers
    `String(ptr)`, `%s`, `print` and `==` on its bytes — the same questions a
    `char *` answers — but there is exactly ONE place the two must be told
    apart, and it is a METHOD call: a `POINTER_KIND` receiver's `value()` /
    `unsafe_load()` / `unsafe_value()` is a DEREFERENCE, decided by
    `dereference_lowering`, while a `str` or foreign-bytes receiver's is the
    four-questions refusal (`IDENTITY_VALUE_METHODS`) or a string read. The two
    backends' dereference intercept is the caller, so it asks this predicate
    rather than the wider one; everywhere else the pointer IS a string.
    """
    return string_operand_is_string(kind) and kind != POINTER_KIND




# ── `%s`, the one conversion that DEREFERENCES its argument ─────────────────
#
# Every other conversion reads the word it is handed and renders it: `%c`,
# `%f`, and `%p` on Darwin, which prints the address rather than the bytes at
# it.  `%s` is the exception, and it is the whole of why a format string is a
# thing this model has to READ rather than pass through: it walks bytes at the
# address until it finds a NUL, so handing it a number is not a wrong
# rendering — it is a walk off the end of whatever the number points into.
#
# The INTEGER conversions are the third thing this section has to be true
# about, and it was false here for a while: `%d` reads a C `int` out of a
# 64-bit word, so `printf("%d", 2**62)` printed `0` where CPython prints
# `4611686018427387904`. `printf_widened_format` gives every one of them an
# `ll` before the format is interned — see that function for the measurement,
# for the `%c`/`%s`/`%ld` exclusions and for the one shape it changes
# deliberately. The `%lld` and `%llu` names here are what a `print` builds for
# itself (`_print_call`) and what that rewrite produces for a `printf`, which
# is the whole of why the two now agree.
#
# The corpus spells the output call `printf` and nothing else, so the set is a
# set and not a pattern; a second member would be added with the callee that
# needs it.  The reason it is needed at all is that `print()` builds its OWN
# format — `_print_call` chooses `%s` or `%lld` from the operand's kind and
# refuses the case it cannot tell — while `printf` takes the format the SOURCE
# wrote and hands it to C unchecked.
PRINTF_TEXT_CONVERSIONS_CALLEES = frozenset({"printf"})

# The two argument classes SysV AMD64 sorts arguments into, as the two short
# strings the tables below spell them with. `str` is not one of them: a `char *`
# is an INTEGER argument (a pointer), which is why `%s` costs a GPR on this ABI
# and not an XMM.
INTEGER_CLASS = "integer"
SSE_CLASS = "sse"



# ── the FLOATING conversions, and the class each conversion puts its argument in ──
#
# SysV AMD64 classifies every argument as INTEGER or SSE and allocates the two
# classes from INDEPENDENT register files: an INTEGER argument consumes the next
# of the six GPRs, an SSE one the next of the eight XMMs, and only a class that
# has run out of registers goes to the stack. So a `double` at vararg position 0
# is XMM0 and does NOT consume RDI, which means the INTEGER argument after it is
# RDI and not RSI — a call that "passes the arguments in order" gets that case
# wrong in a way no amount of moving a single operand can repair.
#
# `aA` are the floating conversions; the `L`/`l` length modifiers and the `0`
# flags are already consumed by `_PRINTF_CONVERSION_RE`, which returns the
# CONVERSION character, so `%.17g`, `%le` and `%La` all arrive here as `g`, `e`
# and `a`. `%n` is not in it (it writes through a pointer) and `%p` is not
# (Darwin's `%p` renders the ADDRESS, which is an integer word).
PRINTF_FLOAT_CONVERSIONS = frozenset("aAeEfFgG")
#: The conversions whose C reading is NOT a number, and it is an exclusion
#: rather than an inclusion because a NUMBER conversion is every one that
#: renders the word it is handed. `%s` reads it as TEXT, `%p` renders the
#: ADDRESS (which is exactly what a container IS, so a container is the RIGHT
#: operand for it), and `%n` writes the count THROUGH the vararg rather than
#: rendering anything. Every other conversion — the integer family, `%c`, the
#: floating family, and a `*` width, which reads an `int` — is a number.
#:
#: Spelled once and read by `printf_container_conversion_refusal`, because the
#: question it answers ("does this conversion render a number") is the same one
#: that decides whether a container operand is being read as an address by
#: mistake or on purpose.
PRINTF_NON_NUMBER_CONVERSIONS = frozenset("spn")
# Eight XMM registers, and the boundary is the ABI's rather than this path's.
PRINTF_SSE_REGISTERS = 8
PRINTF_INTEGER_REGISTERS = 6


def printf_argument_classes(fmt_text) -> list | None:
    """`[INTEGER|SSE]` per vararg of a format string, or None if unparsed.

    Index `j` of the answer is vararg `j` — the argument after the format
    string — and it is the same index arithmetic
    `printf_conversion_specifiers` establishes, read from the same parse, so the
    two cannot disagree about where a conversion's argument is. A `*` width or
    precision consumes an argument and is classified INTEGER, which is what C
    says: a `*` reads an `int`.

    The format STRING is argument 0 and is INTEGER — it is a pointer, and it is
    the caller's one fixed argument rather than a vararg, so the answer starts
    at the first conversion and the caller is expected to prepend it.

    None for a format this does not parse, and that is the permissive direction
    and the same one `printf_conversion_specifiers` takes: a call whose
    conversions cannot be enumerated keeps whatever behaviour it had, rather
    than becoming a new refusal.
    """
    convs = printf_conversion_specifiers(fmt_text)
    if convs is None:
        return None
    return [SSE_CLASS if c in PRINTF_FLOAT_CONVERSIONS else INTEGER_CLASS
            for c in convs]


def printf_float_operand_indices(fmt_text) -> set | None:
    """Which vararg positions a floating conversion reads, or None if unparsed.

    The narrower question `printf_argument_classes` answers, and the one the
    emitter actually asks at the point where it moves a word into an XMM: given
    `"%f %lld %g"`, the answer is `{0, 2}` — position 1 is an integer and must
    NOT be moved. Asking for the classes and filtering is one reader of the
    same parse, not a second parser that could enumerate the conversions
    differently.
    """
    classes = printf_argument_classes(fmt_text)
    if classes is None:
        return None
    return {j for j, c in enumerate(classes) if c == SSE_CLASS}


def printf_float_conversion_refusal(callee: str, n_float: int) -> str:
    """Why a floating conversion this path does not place is refused.

    The ninth and later floating conversions are the boundary, and it is the
    ABI's: SysV AMD64 has eight XMM registers, so the ninth `double` is an
    OVERFLOW argument and lives in the caller's frame at a slot the register
    numbering no longer describes. That is a construct this path could place —
    the stack half of the calling convention is here — and it is not placed
    here, so it is refused by name rather than emitted into the wrong slot,
    which would print one operand's bits under another operand's conversion.
    """
    return (
        f"{callee}'s format string has {n_float} floating conversions, and "
        f"this path places the first {PRINTF_SSE_REGISTERS} of them: SysV "
        f"AMD64 passes a `double` in XMM0..XMM{PRINTF_SSE_REGISTERS - 1} and "
        f"the one after that in the caller's frame, at a slot this path does "
        f"not assign. Refused rather than emitted, because a conversion "
        f"reading another operand's word is a wrong answer that prints."
    )

# A printf conversion specification: `%`, the flags, an optional width and
# precision (each of which may be `*`, which is itself an argument), an
# optional length modifier, and the conversion character.  `%%` matches and is
# NOT a conversion — `print_literal` doubles every literal `%` precisely so this
# can tell the two apart, which is why the alternation holds both rather than
# making `%%` a separate branch.
_PRINTF_CONVERSION_RE = re.compile(
    r"%(?:%|[-+ #0\']*(?:[0-9]+|\*)?(?:\.(?:[0-9]+|\*)?)?"
    r"(?:hh|h|ll|l|L|z|j|t|q)?[a-zA-Z])")

# The QUANTIFIER of one conversion specification — the flags, the width and
# the precision — or None when it carries neither.
#
# A PRECISION is here with the width because it is the same defect: `%.3s` of
# `"héllo"` emits three BYTES on this path (half a character, and invalid UTF-8)
# where CPython emits three characters. `-` is a flag rather than a width, but
# it is in the capture because the whole quantifier is what the message quotes.
_PRINTF_QUANTIFIER_RE = re.compile(
    r"^%([-+ #0\']*)((?:[0-9]+|\*)?)(?:\.([0-9]+|\*))?")


def _printf_specs(fmt_text) -> list | None:
    """One record per CONVERSION SPECIFICATION in `fmt_text`, or None if unparsed.

    **`{quant, conv, stars, text, start, end}` per specification — one row each
    for a quantifier, a conversion character, a `*` count, the specification's
    own TEXT and its span in `fmt_text`.** The two public readers below answer
    different questions and index different things, which is why there are two
    of them: `printf_conversion_specifiers` is an ARGUMENT-indexed
    classification (a `*` consumes one and is INTEGER), and `printf_text_widths`
    is a SPECIFICATION-indexed quantifier. A third reader that needs both the
    quantifier and the character — the width refusal, which must ask "is this a
    `%s`" before it asks "is there a width" — was reading the quantifier out of
    one and about to read the character out of the other, and the two do not
    have the same LENGTH:

        %*s        letters ['*', 's']   widths ['*']

    so a positional pairing of the two lists puts the `%s`'s character on the
    `*`'s argument. One scan is the alternative to that and it is why this
    function exists.

    **`text`/`start`/`end` are here for the one reader that REWRITES a format
    rather than reading it** — `printf_widened_format`, which gives a `%d` an
    `ll` and has to put the new specification back where the old one was. It is
    the same scan rather than a second regex because a second regex is a second
    answer to "where does this specification end", which is the disagreement
    this function was introduced to end.

    `%%` matches and contributes nothing, which is the only skipping rule and is
    the one `printf_conversion_specifiers` documents. A `%%` is still ADVANCED
    over rather than re-scanned, so `a%%b%d` widens the `%d` and leaves the
    `%%` alone.

    None for text this does not parse, and that is the permissive direction both
    public readers already take — see their own docstrings.
    """
    if not isinstance(fmt_text, str):
        return None
    out = []
    pos = 0
    while True:
        at = fmt_text.find("%", pos)
        if at < 0:
            return out
        m = _PRINTF_CONVERSION_RE.match(fmt_text, at)
        if m is None:
            return None
        spec = m.group(0)
        conv = spec[-1]
        if conv != "%":
            qm = _PRINTF_QUANTIFIER_RE.match(spec)
            flags, width, prec = qm.groups() if qm else ("", None, None)
            if width == "*" or prec == "*":
                quant = "*"
            elif width or prec:
                quant = flags + (width or "") + ("." + prec if prec else "")
            else:
                quant = None
            out.append({"quant": quant, "conv": conv,
                        "stars": spec.count("*"),
                        "text": spec, "start": at, "end": m.end()})
        pos = m.end()


def printf_conversion_specifiers(fmt_text) -> list | None:
    """The conversion characters of `fmt_text`, in order, or None if unparsed.

    `%%` yields nothing, which is the only skipping rule.  A `*` width or
    precision DOES consume an argument and is counted here as a conversion
    whose character is `*` — deliberately, and it is what keeps the index
    arithmetic right: the position of a `%s` in the output is the position of
    its argument in the varargs list, and an off-by-one there would refuse the
    wrong argument, which is worse than not looking.

    None for text this does not parse, and that is the permissive direction: a
    format whose conversions cannot be enumerated is one the callers below say
    nothing about, so an unusual `%` in a corpus format string cannot become a
    new refusal.

    **`_printf_specs` is the scan and this is its projection** — see that
    function for why there is one scan rather than two readers of one regular
    expression.
    """
    specs = _printf_specs(fmt_text)
    if specs is None:
        return None
    out = []
    for s in specs:
        out.extend(["*"] * s["stars"])
        out.append(s["conv"])
    return out


def printf_text_widths(fmt_text) -> list | None:
    """The quantifier of each conversion in `fmt_text`, in argument order, or None.

    Same shape as `printf_conversion_specifiers` — one entry per CONSUMED
    argument — and None for text that does not parse, for the same permissive
    reason. The value is `None` for a conversion with no width and no precision,
    `"*"` for one whose quantifier reads its width or precision from an argument
    (which this build cannot see), and the quantifier's own TEXT otherwise —
    flags included, because `%-6s` and `%6s` pad on opposite sides and a
    message that quoted only the digits would not say which one is meant.

    **`_printf_specs` is the scan, and this is its projection** — kept as its
    own function because the trailing entries for extra `*`s are this reader's
    own arithmetic and not a property of any specification. The extra entries
    are what make the length disagree with `printf_conversion_specifiers` for
    `%*s`, and that disagreement is load-bearing rather than a defect: a `*`
    width IS the quantifier of the conversion that carries it, so the conversion
    itself contributes no second row here.

    **It has no caller in `formal/` any more, and that is said here rather than
    left for a reader to discover.** `printf_text_width_refusal` used to reach
    its quantifier through this list and now reads `_printf_specs` directly,
    because the refusal needs the conversion CHARACTER as well and the two
    projections do not have the same length. What is left is the SURFACE: this
    is the named reader for "what quantifiers does this format string carry",
    and `test_formal_unicode.py`'s in-process table pins its parsing — flags
    kept (`%-6s` and `%6s` pad on opposite sides), `*`, `%%`, the positional
    form and the unparsed form — which `_printf_specs` exercises only
    transitively through it. Deleting it with its ten rows would delete the
    coverage of the quantifier parse to save a wrapper, which is the wrong
    trade; the scan is already shared, so there is no second implementation to
    consolidate.
    """
    specs = _printf_specs(fmt_text)
    if specs is None:
        return None
    out = []
    for s in specs:
        out.append(s["quant"])
        out.extend([None] * (s["stars"] - (1 if s["quant"] == "*" else 0)))
    return out


#: The conversions whose C reading is an `int`/`unsigned int` — 32 bits on
#: every target this backend emits — paired with the 64-bit SPELLING of each.
#: `i` is `d` and `X` is `x`; both spellings exist in C and a program may use
#: either, so the table carries both rather than normalizing the source.
#:
#: `c` is deliberately ABSENT and that is a fact about the conversion rather
#: than an omission: `%c` converts an `int` to `unsigned char`, so the low
#: EIGHT bits are what it renders and widening it would change the character
#: rather than widen the number. `%s`, `%f`, `%p` and `%n` are absent for the
#: same kind of reason — none of them reads the word as a number at all.
PRINTF_32_BIT_INTEGER_CONVERSIONS = {
    "d": "lld", "i": "lli", "u": "llu", "o": "llo", "x": "llx", "X": "llX",
}

#: Every conversion that reads its vararg as a NUMBER — the integer set above,
#: the floating set, and the two that are a number read in another role. It is
#: DERIVED from the two tables rather than written out, because a third
#: hand-maintained list of conversion characters is a third thing that can fall
#: out of step with the two that decide how the operand is placed, and the
#: question this set answers ("does this conversion want a number?") is exactly
#: the question the other two answer one at a time.
#:
#: `c` is here and NOT in `PRINTF_32_BIT_INTEGER_CONVERSIONS` for the reason
#: that table gives: `%c` converts an `int` to `unsigned char`, so it reads the
#: word as a number and renders eight bits of it. Measured on both
#: architectures, `printf("[%c]", xs)` over a list printed `[?]`, which is the
#: low byte of the blob's own address.
#:
#: `*` is here because C says a `*` width reads an `int` — the argument behind
#: it is a number by the same rule every other row of this table follows, and
#: `printf("%*d", xs, 3)` over a list printed a field of thousands of spaces on
#: both architectures, which is the address read as a field width.
#:
#: **`a` and `A` are DELIBERATELY ABSENT, and CPython is why.** In C they are
#: the hexadecimal-float conversions and belong with `PRINTF_FLOAT_CONVERSIONS`
#: on the placement side. In CPython's `%`-formatting `%a` is `repr()` and
#: `%A` is `ascii()`, so `"%a" % [1, 2, 3]` is `'[1, 2, 3]'` — measured, not
#: remembered — and a program that writes it is CORRECT and is refused here for
#: a direction CPython does not refuse in. This set is therefore not
#: `PRINTF_FLOAT_CONVERSIONS` and the difference is a naming fact about two
#: languages rather than an omission; `%A` does not even exist in CPython
#: (`ValueError: unsupported format character 'A'`).
PRINTF_NUMBER_CONVERSIONS = (frozenset(PRINTF_32_BIT_INTEGER_CONVERSIONS)
                             | (PRINTF_FLOAT_CONVERSIONS - frozenset("aA"))
                             | frozenset("c*"))

#: CPython's OWN sentence for a NUMBER conversion of a container, per
#: conversion character, and it is a table because CPython's phrasing is not
#: uniform — measured over every member of `PRINTF_NUMBER_CONVERSIONS` on this
#: interpreter rather than taken from one example and generalised:
#:
#:     %-3d % [1,2,3]   TypeError: %d format: a real number is required, not list
#:     %-3o % [1,2,3]   TypeError: %o format: an integer is required, not list
#:     %-3c % [1,2,3]   TypeError: %c requires an int or a unicode character, not list
#:     %-3e % [1,2,3]   TypeError: must be real number, not list
#:     "%*d" % ([1,2],3)   TypeError: * wants int
#:
#: **It exists so the refusal can quote the interpreter rather than paraphrase
#: it**, which is the whole reason the doc that asked for this row said CPython's
#: message "is the model to mirror … and it is checkable". A paraphrase would be
#: a sentence this repository invented about what Python does, and the next
#: reader would have no way to tell it from a measured one.
#:
#: `%c` and `*` are worded as they are rather than folded into the `%d` shape
#: because those two are not "a number is required": `%c` also accepts a
#: one-character `str`, and `*` names the width argument instead of the
#: conversion. Both are the interpreter's own wording and quoting anything else
#: would be the "a list is required, not int" mistake this table exists to
#: avoid.
# CPython reworded these messages in 3.15, so the table is keyed by minor
# version: the check (`test_formal_run.check_printf_number_conversion_agreement`)
# selects the entry for the interpreter running the build, and refuses to
# guess a wording for a minor version nobody has measured.
PRINTF_CPYTHON_NUMBER_REFUSALS_3_14 = {
    "d": "%d format: a real number is required, not {t}",
    "i": "%i format: a real number is required, not {t}",
    "u": "%u format: a real number is required, not {t}",
    "o": "%o format: an integer is required, not {t}",
    "x": "%x format: an integer is required, not {t}",
    "X": "%X format: an integer is required, not {t}",
    "c": "%c requires an int or a unicode character, not {t}",
    "e": "must be real number, not {t}",
    "f": "must be real number, not {t}",
    "g": "must be real number, not {t}",
    "E": "must be real number, not {t}",
    "F": "must be real number, not {t}",
    "G": "must be real number, not {t}",
    "*": "* wants int",
}

PRINTF_CPYTHON_NUMBER_REFUSALS_3_15 = {
    "d": "format argument: %d requires a real number, not {t}",
    "i": "format argument: %i requires a real number, not {t}",
    "u": "format argument: %u requires a real number, not {t}",
    "o": "format argument: %o requires an integer, not {t}",
    "x": "format argument: %x requires an integer, not {t}",
    "X": "format argument: %X requires an integer, not {t}",
    "c": "format argument: %c requires an integer or a unicode character, not {t}",
    "e": "format argument: %e requires a real number, not {t}",
    "f": "format argument: %f requires a real number, not {t}",
    "g": "format argument: %g requires a real number, not {t}",
    "E": "format argument: %E requires a real number, not {t}",
    "F": "format argument: %F requires a real number, not {t}",
    "G": "format argument: %G requires a real number, not {t}",
    "*": "format argument 1: * requires int, not {t}",
}

PRINTF_CPYTHON_NUMBER_REFUSALS_VERSIONS = {
    (3, 14): PRINTF_CPYTHON_NUMBER_REFUSALS_3_14,
    (3, 15): PRINTF_CPYTHON_NUMBER_REFUSALS_3_15,
}

import sys as _sys
_PRINTF_CPYTHON_VERSION = (_sys.version_info.major, _sys.version_info.minor)
PRINTF_CPYTHON_NUMBER_REFUSALS_SUPPORTED_VERSIONS = frozenset(
    PRINTF_CPYTHON_NUMBER_REFUSALS_VERSIONS)
PRINTF_CPYTHON_NUMBER_REFUSALS = PRINTF_CPYTHON_NUMBER_REFUSALS_VERSIONS.get(
    _PRINTF_CPYTHON_VERSION, {})


def _printf_length_modifier(spec: str) -> str:
    """The LENGTH MODIFIER of one matched conversion specification, or "".

    `_PRINTF_CONVERSION_RE` matches the whole specification but names none of
    its parts, so the modifier is read off the tail: a conversion character is
    `[a-zA-Z]` and the modifier is the run of length letters immediately
    before it, out of the set the pattern accepts (`hh h ll l L z j t q`).
    Reading it off the TAIL rather than by re-matching is what keeps this and
    `_printf_specs` from disagreeing about where a specification ends — the
    `printf_conversion_specifiers` / `printf_text_widths` disagreement this
    scan already exists to prevent.
    """
    i = len(spec) - 2                      # the char before the conversion
    while i >= 0 and spec[i] in "hlLqjzt":
        i -= 1
    return spec[i + 1:-1]


def printf_widened_format(fmt_text) -> str | None:
    """`fmt_text` with every 32-bit INTEGER conversion given an `ll`, or None.

    **The rewrite that made `printf("%d", 2**62)` print the number the source
    wrote, and it is a REWRITE rather than a refusal because the answer is not
    in doubt.** A
    formal value is one 64-bit word (`doc/ABI.md`, "Scalar types"), the emitter
    passes the whole word, and libc's `%d` reads a C `int` out of it — so the
    conversion renders the low 32 bits and the program prints a number the
    source never wrote. Measured on both architectures from one source:

        a = 4611686018427387904            # 2**62
        printf("A=%d|", a)                 -> A=0
        printf("B=%lld|", a)               -> B=4611686018427387904

    and CPython's `print(a)` is `4611686018427387904`. The two spellings differ
    by exactly the low 32 bits read as `int`, which is why the defect is
    invisible to every program whose integers fit in 32 bits and to every
    differential test that compares EXIT STATUS.

    **Why the rewrite is the whole word and not a zero-extension.** The
    argument is already in a 64-bit register in full; libc's `%lld` reads all
    eight bytes of it. Nothing is widened, nothing is truncated, and the
    emitted instructions are the same two the operand already cost.

    **Why `%d` was RIGHT for a genuine 32-bit C `int` and stays right.**
    `strcmp`, `memcmp`, `atoi` and every other int-returning libc name the
    corpus reaches are listed in `BARE_C_RETURN_KINDS`, and the emitters
    sign-extend what it lists (`_emit_extern_return`, whose own comment says a
    W-register write zero-extends and `Int32` is signed), so the word libc reads
    with `%lld` is the sign-extended value and prints the same digits.
    Measured, both architectures, after this landed: `atoi("-2147483648")`
    prints `-2147483648` through `%d` and through `%lld`.

    ## What it deliberately does NOT touch, and each omission is a decision

    **ONLY a conversion with NO length modifier**, because a modifier is the
    source stating a width and this rewrite is about C's DEFAULT width being
    narrower than a formal value:

    * `%ld` / `%lld` / `%llu` / `%lu` / `%llx` — `long` and `long long`, 64-bit
      under LP64 on both targets this backend emits, which is exactly what
      this rewrite would have produced. `z`/`j`/`t` are `size_t`/`intmax_t`/
      `ptrdiff_t`, 64-bit for the same reason; `L` is `long double` and
      belongs to the floating conversions.
    * `%hd` / `%hhd` — 16- and 8-BIT, which is the source asking for a
      narrower type on purpose. There is no 16-bit value on this path to be
      narrower than, so widening them would answer a question nobody asked.
      Zero sites in this corpus either way.
    * **`%c`** — it converts an `int` to `unsigned char`, so the eight bits it
      renders are the eight bits it means.
    * `%s`, `%f`, `%p`, `%n`, `%%` — none reads its operand as a number.

    ## The one shape where `%d` was right by ACCIDENT, and what this does
    ## about it

    A C function returning `int` puts 32 bits in the return register and leaves
    the rest unspecified (AAPCS64 §6.9, SysV AMD64 §3.2.3), so its `-1` may
    arrive as `0xFFFF_FFFF_FFFF_FFFF` or as `0x0000_0000_FFFF_FFFF`. This path
    normalizes the ones it has a prototype for (`BARE_C_RETURN_KINDS`, total
    over `formal/hostmods/` and pinned by `test_formal_libc_symbol.py`'s
    `retkind` group); a name it does NOT list is handed on as it arrived, so for
    that word `%d` renders the low 32 bits and happens to be C's answer while
    the model's own value is `4294967295`.

    **The rewrite is unconditional anyway, because the alternative is to leave
    `%d` disagreeing with the model.** `print(a)` on that same word already
    prints `4294967295` — `_print_call` builds `%lld` — and `a < 0` already
    answers `no` and `a + 1` already answers `0`: measured, both architectures,
    on `strcasecmp("a", "b")`. **So the word this path holds for that value IS
    4294967295, and `%d` was the one rendering that did not say so.** Widening
    makes `printf` agree with `print` and with every operator on the same word,
    which is the property that lets a program swap one for the other; narrowing
    instead would preserve an accident and keep the two disagreeing.

    The residual defect is upstream of `printf` and is now FIXED (`778ee7ab`:
    `BARE_C_RETURN_KINDS` no longer misses a libc `int` return, so it is
    sign-extended). **Its exposure here was ZERO**, measured: every real libc bare callee reachable
    from this repository's 423 `.mojo` files and the stdlib has a row, and none
    of the 18 `printf` varargs over them is a bare call without one. So this
    rewrite changes no answer on this corpus, and the one program that could
    observe a change is one this corpus does not contain.

    **A format held in a NAME is not reachable here** (`fmt = "%d";
    printf(fmt, x)`), because a non-literal cannot be scanned. That is the
    permissive direction every format reader on this path already takes —
    `printf_format_refusal` is a no-op for a non-literal format for the same
    reason — and it is the one limit the bug doc's next step does not ask about.

    **One rewrite, asked of the format, and both backends apply it**
    (`formal/build.py::_widen_printf_integer_conversions`, in the pipeline both
    front ends share) — not a per-emitter substitution, because two emitters
    that each widened a format string would be two answers to one question on
    the day one of them was edited. The emitters' own `printf_format_refusal`
    then read the WIDENED text, so the `%s`/float/missing-operand refusals and
    this agree about what the format says.

    `None` for a format that does not parse — the permissive direction every
    other reader of a format string on this path takes — and `None` when there
    is nothing to widen, which is what lets a caller ask unconditionally and
    only rewrite when the answer is a different string.
    """
    if not isinstance(fmt_text, str) or "%" not in fmt_text:
        return None
    specs = _printf_specs(fmt_text)
    if specs is None:
        return None
    out, pos, widened = [], 0, 0
    for s in specs:
        if s["conv"] not in PRINTF_32_BIT_INTEGER_CONVERSIONS:
            continue
        if _printf_length_modifier(s["text"]):
            continue
        out.append(fmt_text[pos:s["start"]])
        out.append(s["text"][:-1] + PRINTF_32_BIT_INTEGER_CONVERSIONS[s["conv"]])
        pos = s["end"]
        widened += 1
    if not widened:
        return None
    out.append(fmt_text[pos:])
    return "".join(out)


def printf_callee_name(call) -> str | None:
    """The C NAME a `printf`-family call binds, or None.

    **One reader of "which call is a `printf`", because two answers is how the
    two architectures come to disagree about a format string.** `fire.py`'s
    `dylib --formal --backend=x86_64` measurement is the shape of the failure
    this prevents: the architecture flag was parsed and dropped, so a reader
    asking "is this call a `printf`" from the emitter's own resolved name got
    an answer for one machine and the other reader got the other one.

    Three spellings reach a format function on this path, and all three are
    here:

      * `printf(fmt, …)` — the corpus's own spelling, and the only one a
        program writes.
      * `external_call["printf", Int32](fmt, n)` — the same C function reached
        through the bracket, which `external_call_spec` resolves. Its own
        docstring records that this reaches the same line in the emitters with
        `name == "printf"`, so a gate that only read the bare spelling would
        miss every dylib-format call.
      * `printf[T](fmt, …)` — a comptime specialization, which
        `call_callee_name` looks through.

    `None` for anything else, including a `MemberExpr` callee: `mod.f(x)` is a
    different question and `call_callee_name`'s own table says why.
    """
    func = getattr(call, "func", None)
    if func is None:
        return None
    if is_external_call_template(func):
        symbol, _ret, why = external_call_spec(func)
        return None if why is not None else symbol
    return call_callee_name(func)


def printf_call_format_literal(call):
    """The format `F.StringLiteral` of a `printf`-family call, or None.

    **The ONE place a format argument is located**, asked by the rewrite that
    widens a `%d` (`printf_widened_format`) and available to any reader that
    needs the node rather than the text. The INDEX is
    `printf_format_arg_index`'s, which derives it from `VARIADIC_LIBC` rather
    than from a second table, so `sprintf`'s buffer argument cannot be mistaken
    for a format — which is the whole reason that function exists.

    `None` when the callee is not a format function, when there is no argument
    at the format index, or when the format is not a LITERAL. The last is the
    permissive direction every format reader on this path takes: a format in a
    variable cannot be scanned, and `printf_format_refusal` has said so in its
    own docstring since before this existed. **The widening therefore does not
    reach a format held in a name**, and that is a real limit rather than an
    oversight — it is recorded on `printf_widened_format` and in the bug doc.
    """
    if not isinstance(call, F.CallExpr):
        return None
    idx = printf_format_arg_index(printf_callee_name(call) or "")
    if idx is None:
        return None
    args = list(getattr(call, "args", None) or [])
    node = args[idx] if idx < len(args) else None
    return node if isinstance(node, F.StringLiteral) else None


def printf_text_width_refusal(callee: str, fmt_text, args: list,
                              text_of_arg) -> str | None:
    """Why a WIDTH on a `%s` of non-ASCII text is refused, or None.

    The third way a format string can mean something other than what it says,
    and the only one that is about the TEXT rather than about what kind of
    value it is.

    **A `%<width>s` pads to a BYTE width, because `printf` is a C function and
    C has no characters.** CPython's `"%6s" % "héllo"` pads to six CHARACTERS,
    which is one space; C's `printf("%6s", "héllo")` pads to six BYTES, which is
    none, because the text is already six bytes. Measured on both formal
    backends, `%6s` of the literal `"héllo"` printed `[héllo]` where CPython
    prints `[ héllo]`, and `%-6s` printed `[héllo]` where CPython prints
    `[héllo ]` — the same wrongness in both directions, and the left-aligned row
    is the one that makes it visible at all, because the right-aligned row looks
    like a truncation.

    `text_of_arg(arg)` is the emitter's own question — the DECODED TEXT of an
    argument, or None when the build cannot see it — and None is the permissive
    direction for the reason `printf_text_conversion_refusal`'s own None row is:
    the whole-image condition below is what decides, not this hook.

    **The condition is the image's, not the argument's**, and that is the same
    TEXT ENCODING argument as everywhere else in this file: a `%s` of a
    KNOWN non-ASCII literal is refused because its own text says so, and a `%s`
    whose argument's text the build cannot see is refused whenever the image
    holds a non-ASCII literal AT ALL — because only then can that argument be
    one, and a `%6s` whose operand might be `é` cannot be emitted with a byte
    width and hope. So an image of pure ASCII never sees this refusal, which is
    every program in the corpus, and an image with a non-ASCII table in it gets
    it for the one conversion it can be wrong about.

    ## ONLY a `%s`, and that test used to be missing — the refusal named `%s`
    ## for a conversion that was not one

    `printf_text_widths` returns the quantifier of EVERY conversion, so the loop
    below was reached by a `%f`, a `%d` and a `%c` as readily as by a `%s`, and
    the refusal it returned named a conversion the format string does not
    contain. Measured on the tree this landed in, on `test_formal_time.py`'s
    `clocks` group, whose program prints six decimal places of a float:

        printf("wall_bits=%.6f@@", time.time_seconds_bits())

        build: the `%.6s` conversion in printf's format string is refused: …
        This image holds a string literal that is not ASCII — "`round-half-even
        (a * 2^k / den)`, for `a < 2^30` and `k >= 0`. …"

    Two wrongnesses in one message: the format string says `%f` and the
    refusal says `%.6s`, and a `%<precision>f` is six DECIMAL PLACES of a
    number — there is no text in it, no character in it, and no encoding
    question anywhere near it. The refusal was refusing a number because a
    docstring in `IEEE754.mojo` holds an em-dash.

    So the character is read here, from `_printf_specs`, rather than assumed —
    and it is the scan's OWN row rather than `printf_conversion_specifiers`'
    because the two lists do not have the same length (`%*s` is `['*','s']` and
    `['*']`), so pairing them by position would ask about the `*`'s argument.
    The `*` rows are skipped exactly as before: a `*` width is an argument this
    build cannot see and there is nothing to quote.
    """
    if text_of_arg is None or callee not in PRINTF_TEXT_CONVERSIONS_CALLEES:
        return None
    specs = _printf_specs(fmt_text)
    if specs is None:
        return None
    # `arg` is the vararg the NEXT specification reads. A `*` width or precision
    # is itself a vararg and comes before the conversion's operand, so a
    # specification consumes `stars + 1` of them — which is also the arithmetic
    # `printf_text_widths`'s trailing entries approximate, and the reason this
    # walk is over the specifications and not over that list.
    arg = 0
    for s in specs:
        operand = arg + s["stars"]
        arg = operand + 1
        if s["conv"] != "s":
            continue
        width = s["quant"]
        if width is None or width == "*" or operand >= len(args):
            continue
        text = text_of_arg(args[operand])
        if text_is_ascii(text):
            continue
        if text is None and not non_ascii_strings():
            continue
        return codepoint_refusal(
            f"the `%{width}s` conversion in {callee}'s format string",
            spelled(args[operand]))
    return None


def printf_text_conversion_refusal(callee: str, fmt_text, args: list,
                                   text_of, text_of_arg=None) -> str | None:
    """Why a `%s` conversion of an argument that is not text is refused.

    `args` is the call's arguments with the format string ALREADY REMOVED, so
    index 0 of `args` is the first vararg and the conversion at position `j` of
    `printf_conversion_specifiers(fmt_text)` is `args[j]`.

    `text_of(arg)` is the emitter's own question about one argument, and it is a
    THREE-WAY answer, which is the whole of the narrowing:

    | `text_of` | meaning | refused |
    |---|---|---|
    | `True` | this argument is text | no |
    | `False` | this argument is NOT text | yes, and the message says "a value this function bound to an integer on that statement's own shape" |
    | a `str` | NOT text, and this is the evidence | yes, and the message quotes the evidence |
    | `None` | the source does not say | no |

    The `str` row exists because there is more than one KIND of positive
    evidence, and a message that asserted the integer default about all of them
    would be false about the one that is not: `one_word_value_text_evidence`
    refuses on a DECLARATION instead. One answer shape, two sentences, and the
    caller picks the evidence by what it knows.

    `None` is the permissive direction on purpose. An UNANNOTATED PARAMETER is
    a word this build cannot classify, and `def show(s): printf("[%s]", s)`
    called with `show("abc")` is a program that works — measured on both
    architectures, exit 0 and `[abc]`. Reading "not known to be text" as "not
    text" would refuse it, and with it every function in the corpus that takes
    a string it was never told about. That is the gap the note above
    `ValueKinds` records as the remaining one for `print`, it is a kind-table
    gap rather than a conversion gap, and this function does not make it worse.

    **`False` is positive evidence**, and the emitters produce it from
    `ValueKinds.own_shape_kind`: a statement of THIS function bound the name to
    an integer on that statement's own shape. `a = 5; printf("[%s]", a)` is the
    reproducer — measured on both architectures from a GREEN build it printed
    nothing and died of SIGSEGV, exit 139, because `%s` walked bytes at address
    5 looking for a NUL. `printf("[%s]", a)` where `a = 2 + 4` faults the same
    way and `own_shape_kind` covers it for the same reason, which is also why
    the same predicate answers the container-element question
    (`non_container_element_refusal`): one evidence test, two families, and two
    architectures that cannot disagree about which names carry it.

    A FRAME ADDRESS does not reach here: `_check_frame_escapes` has already
    refused a frame receiver in a call position — `frame_receiver_escape_refusal`'s
    `FRAME_C_VALUE_CALLS` branch, whose own measured consequence is a `%d` of a
    frame printing its address and exiting 0. A struct of ONE field has no frame
    address to be refused on, and that is what `one_word_value_text_evidence`
    below is for: the last of the three shapes `%s` walks off the end of was a
    one-field struct's value, and it is closed on a declaration rather than on
    the integer default.
    """
    if callee not in PRINTF_TEXT_CONVERSIONS_CALLEES:
        return None
    why = printf_text_width_refusal(callee, fmt_text, args, text_of_arg)
    if why is not None:
        return why
    convs = printf_conversion_specifiers(fmt_text)
    if convs is None:
        return None
    for j, conv in enumerate(convs):
        if conv != "s" or j >= len(args):
            continue
        answer = text_of(args[j])
        if answer is None or answer is True:
            continue
        evidence = (answer if isinstance(answer, str)
                    else "a value this function bound to an integer on that "
                         "statement's own shape")
        return (
            f"the `%s` conversion in {callee}'s format string reads "
            f"`{spelled(args[j])}` as text, and `{spelled(args[j])}` is "
            f"{evidence}. A string on this path is a "
            f"bare `char *` and an integer is a NUMBER, and `%s` is the one "
            f"conversion that DEREFERENCES what it is handed — it walks bytes "
            f"at the address until it finds a NUL. Measured on BOTH "
            f"architectures, this builds, links, runs, and then dies of "
            f"SIGSEGV, exit 139, with the build green, because there is no NUL "
            f"to find at a small integer. Refused here rather than emitted, "
            f"because a missing terminator is not a wrong rendering: it is a "
            f"walk off the end of whatever the number points into. What the "
            f"same source can do instead: bind the text and convert it "
            f"(`s = String(a)`, or read the field that holds it), or use a "
            f"conversion that does not dereference — `%lld` renders the number "
            f"itself"
        )
    return None


def identity_conversion_operand(expr):
    """The operand of a word-for-word CONVERSION of `expr`, or None.

    `type_constructor_kind`'s `("identity", …)` row, asked of an EXPRESSION
    rather than of a name: `String`, `str`, `StringLiteral`, `StringSlice`,
    `Pointer`, `UnsafePointer` and `CPointer` all move the operand's word and
    change nothing else about it on this path, so a question about the call's
    result is the same question asked about its operand — and a diagnostic that
    only understands the call spelling misses the operand spelling of one
    defect.

    Measured, both architectures, and both directions are the reason it is asked
    rather than assumed: `printf("[%d]", str(42))` prints `42` and
    `printf("[%d]", int("42"))` prints the POINTER, so the conversion moves the
    word and does not convert it — while `printf("[%s]", int("42"))` prints
    `42` and `printf("[%s]", str(42))` dies of SIGSEGV, exit 139. A `%s` of such
    a call is therefore decided entirely by its operand, which is what this
    function hands back.

    `None` for anything else — a conversion with no operand, with more than
    one, or one that is not this row — and None is the permissive direction for
    a caller: the question then falls to whatever the call's own spelling says.
    """
    if not isinstance(expr, F.CallExpr) or not isinstance(expr.func, F.IdentExpr):
        return None
    args = list(getattr(expr, "args", None) or [])
    if len(args) != 1 or getattr(expr, "kwargs", None):
        return None
    tk = type_constructor_kind(expr.func.name)
    if tk is None or tk[0] != "identity":
        return None
    return args[0]


def printf_arg_text_evidence(expr, vk, is_text=None, one_word_text=None,
                            container_of=None):
    """`True` / an evidence string / `None`: does this `printf` vararg hold text.

    THE decision, in one function, asked with the three facts only an emitter
    knows and a model function cannot derive: `vk` is this function's
    `ValueKinds`, `is_text(expr)` is the emitter's FLOW-SENSITIVE kind (its
    `_string_vars` map, which knows what this very function's emission has bound
    so far), and `one_word_text(name)` is `one_word_value_text_evidence` over the
    one-field candidates `formal/build.py` published for the name. Any of the
    three may be None, and a None hook leaves that source of evidence unasked —
    which is what makes `printf_text_conversion_refusal`'s `text_of` contract
    and this function the same contract.

    The shape of it, in order, and each step is there because the step before it
    cannot see what it is asking about:

      1. **A CONVERSION is its operand.** `String(x)`, `str(x)`, `int(x)`,
         `Pointer(x)` and their relatives move the word and change nothing else
         on this path — measured: `%d` of `String(7)` prints 7, and `%s` of
         `String(42)` dies of SIGSEGV — so the question about the call is the
         question about its operand, and asking it one level in is what lets one
         decision cover both spellings. (`identity_conversion_operand`, looped
         so a conversion of a conversion is one question too.)
      2. **A STRING LITERAL, or anything `is_text` calls text.** Unchanged.
      2b. **A CONTAINER, from its KIND.** `is_list_kind(vk.kind_of(arg))` is
         positive evidence that the operand is NOT text: a container's one word
         is its blob's address, whose first word is its count, so `%s` walked the
         count header as a C string. Asked here rather than after step 3 because
         a name bound to a list has no integer `own_shape` and would otherwise
         reach `one_word_text`'s permissive None. `is_list_kind` covers a list, a
         tuple, a set, a `bytearray` and a dict, so the answer is one answer.
      3. **A NAME, from the two positive-evidence sources**: a statement of this
         function bound it to an integer on that statement's own shape, or a
         one-field struct's declaration says what its only field holds. Both
         are evidence about a NAME, because a name is the one thing whose kind
         can come from a default rather than from the source — `ValueKinds`'
         own note on `INT_KIND` is the whole of why.
      4. **A CALL, or nothing.** `kind_of` answers `INT_KIND` for a callee it
         does not know, because a word is an integer everywhere else, and
         `printf("%%s", platform_name())` is a program that prints `darwin`.
         Reading that default as evidence would refuse every extern's result,
         so a call's kind is never evidence here — which is the same rule
         `_own_shape_of` applies and for the same reason.
      5. **Anything ELSE, from its own shape.** A literal, an arithmetic
         expression, a subscript, a field read: none of them can be seeded by a
         default, so `kind_of`'s `INT_KIND` here is the expression's own shape
         and `printf("[%s]", 42)` — which walks bytes at address 42 looking for
         a NUL — is the same defect the two tables above exist for.

    **A CONTAINER is refused here too, and it is the one shape where `%s` is
    worse than a number rather than merely as bad.** `%s` is the conversion that
    DEREFERENCES, so a container is a pointer it walks: measured on BOTH
    architectures from a GREEN build, `printf("[%s]", xs)` for `xs = [1, 2, 3]`
    printed `[]` and exited 0 where CPython raises `TypeError` — the blob's count
    bytes are not text and the walk stops at whichever zero byte it finds first,
    which is output that depends on a heap layout. `printf_arg_container_evidence`
    is the kind test (a `list`, `tuple`, `set` or `dict` all answer), and it is
    asked AFTER the two text checks so a name bound to a real string is text and
    not refused.
    """
    arg = expr
    for _ in range(4):
        inner = identity_conversion_operand(arg)
        if inner is None:
            break
        arg = inner
    if isinstance(arg, F.StringLiteral):
        return True
    if is_text is not None and is_text(arg):
        return True
    # **A CONTAINER is positive evidence that the operand is NOT text, and it is
    # the same defect as an integer at `%s` one step further out.** `%s` walks
    # bytes at the address it is handed looking for a NUL; a container's one word
    # is the address of its blob, whose FIRST word is its count, so `printf("%s",
    # xs)` walked the count header as a C string. The evidence is the KIND and
    # not a name's `own_shape`, because a literal, a construction and a name
    # bound to either are one answer — and `is_list_kind` also covers a dict and
    # a `bytearray`, which classify as `list:*` blobs on this path
    # (`ValueKinds.is_dict_value`'s docstring is the measurement). It is asked
    # before the name arm because a name bound to a list has no `own_shape` on
    # the integer axis and would otherwise fall through to `one_word_text`'s
    # permissive None. An unannotated parameter still answers `INT_KIND` (not a
    # container), so a program whose container-ness this build cannot see keeps
    # building.
    if vk is not None and is_list_kind(vk.kind_of(arg)):
        return ("a CONTAINER — its one word is the address of its blob, and the "
                "blob's first word is its count, so it is not a `char *` for "
                "`%s` to walk")
    if isinstance(arg, F.IdentExpr):
        if vk is not None and vk.own_shape_kind(arg.name) == INT_KIND:
            return ("a value this function bound to an integer on that "
                    "statement's own shape")
        return one_word_text(arg) if one_word_text is not None else None
    # **A LOWERED STRING METHOD is evidence, and step 4's blanket refusal of a
    # call's kind was FALSE of it.** The rule below declines a call because
    # `kind_of` answers `INT_KIND` for a callee it does not know — "a word is an
    # integer everywhere else" — and reading that DEFAULT as evidence would
    # refuse every extern's result, `printf("%s", platform_name())` being the
    # case it names. That reasoning is right and it does not reach this shape:
    # `POINTER_BOUNDED_METHODS` records what each string method YIELDS, as its
    # own table's comment insists ("the yield is what the classifier needs … a
    # method whose result is misclassified poisons every use site after it, and
    # the symptom is a wrong answer rather than a diagnostic"). `startswith`,
    # `endswith`, `find` and `count` are recorded as `INT_KIND` for that reason,
    # and that is a DECLARATION about the result rather than the unclassified-
    # callee default step 4 is refusing.
    #
    # Measured, and it was a SIGSEGV rather than a wrong number, on both
    # architectures from a green build:
    #
    #     def cat() -> String: return "qq"
    #     printf("%s|", cat().startswith("q"))    ->  exit 139
    #
    # because `%s` walks bytes at address 0 or 1 looking for a NUL. The
    # `printf("[%s]", 1 > 0)` control IS refused — step 5 covers a comparison,
    # whose shape cannot be seeded by a default — so the refusal machinery was
    # working and the one shape it declined was the one with the best evidence.
    #
    # **Both halves of the question are asked, and the receiver's kind is the
    # gate for the same reason `_string_method_kind`'s own docstring gives**: a
    # method on a receiver this build cannot call a `char *` proves nothing about
    # its result, so `x.count(y)` on an unclassified `x` stays None rather than
    # borrowing the string table's answer.
    if isinstance(arg, F.CallExpr):
        declared = _lowered_string_method_result(arg, vk, is_text)
        if declared is not None:
            return declared
        return None
    if vk is None:
        return None
    if vk.kind_of(arg) == INT_KIND:
        return ("an EXPRESSION whose own shape holds a number — a literal, an "
                "arithmetic result, a subscript, or a conversion that moves "
                "its operand's word — and not a name, so none of it came from "
                "the default an unclassified name gets")
    return None


def _lowered_string_method_result(call, vk, is_text):
    """Evidence for `%s` about `call`, when `call` is a lowered string method.

    The reader `printf_arg_text_evidence`'s step 4 delegates to, and it is a
    function rather than inline code because the DECISION is about what a
    method call denotes and there is more than one caller that needs to know —
    `string_method_yields_string` asks the same table for a different question
    (`STR_KIND` rather than `INT_KIND`) and the two must not come apart.

    Two conditions and both are required:

      * the method is in `POINTER_BOUNDED_METHODS`, which is the set this path
        LOWERS — a method in `LENGTH_DEPENTENT_METHODS` is refused by name at
        the emitter and never reaches a `printf`, so asking about its result
        would be answering for a construct that was declined one step earlier;
      * the receiver is text, asked through the emitter's flow-sensitive
        `is_text` first and `ValueKinds` second. `startswith` on a `char *`
        yields 0 or 1 and `startswith` on a word is not a call this path can make
        at all, so the receiver is what makes the table's row true rather than
        merely applicable.

    Returns the evidence STRING for a method that yields a number and None for
    one that yields text (a `char *` is text, which step 2 of the caller has
    already established, so claiming otherwise here would double-refuse it) and
    for every shape this does not cover.
    """
    func = getattr(call, "func", None)
    if not isinstance(func, F.MemberExpr):
        return None
    entry = POINTER_BOUNDED_METHODS.get(func.member)
    if entry is None or entry[1] != INT_KIND:
        return None
    if is_text is not None and is_text(func.obj):
        pass
    elif vk is None or vk.kind_of(func.obj) != STR_KIND:
        return None
    return (f"the result of `{spelled(call)}`, which is "
            f"`{func.member}`, a lowered string method this path records as "
            f"yielding a NUMBER")


def printf_arg_float_evidence(expr, vk, is_float=None) -> str | None:
    """`"float"` / `"int"` / `"container"` / None — this operand's conversion class.

    THE evidence for `printf_kind_conversion_refusal`, and it is a second
    function rather than an extension of `printf_arg_text_evidence` because the
    two axes have different evidence available: a `%s` handed an integer is
    caught by "this function bound the name to an integer", which is evidence a
    NAME can carry, while the floating axis needs `FLOAT_KIND`, and `FLOAT_KIND`
    is never a default — it comes from an annotation, a literal, a declared
    return type or a float initializer. So `"float"` needs no such hunt and
    `"int"` does, and folding them into one answer would have had to pick
    which axis's discipline governs the other.

    **No conversion is unwrapped, and that is the difference from
    `printf_arg_text_evidence`'s step 1.** There, `String(x)`/`int(x)` move the
    word and change nothing, so the question about the call is the question
    about its operand. Here `float(7)` is a DOUBLE and `Int(2.5)` is an
    integer, so the conversion is exactly where the answer changes: unwrapping
    would answer `printf("%d", Int(2.5))` about `2.5` and refuse a program that
    prints 2.

    The two sources of `"int"`, and both are POSITIVE:

      * a NAME this function bound to an integer on that statement's own shape
        (`ValueKinds.own_shape_kind`), which is the evidence `%s` uses and the
        reason an unannotated parameter is not enough — `INT_KIND` is this
        model's DEFAULT for a word, so reading it as a claim refuses correct
        programs;
      * an EXPRESSION that cannot be seeded by a default at all: a literal, an
        arithmetic result, a subscript. `printf("%.17g", 7)` is the reproducer
        and it is the same defect as `%d` of a double in the other direction —
        measured on BOTH architectures it printed
        `3.4584595208887258e-323`, which is the integer 7 read as the bit
        pattern of a double.

    A CALL is never evidence, for the reason `_own_shape_of` gives: `kind_of`
    answers `INT_KIND` for a callee it cannot see, and `printf("%.17g",
    get())` may well be handed a double by a caller this build knows nothing
    about.

    **`"container"` is the third class, and it is read from the operand's own
    KIND** (`ValueKinds.kind_of` through `is_list_kind`) rather than from a
    constructor's name, so a list, a `bytearray` and a `Dict` are one answer.
    `printf("%d", xs)` for `var xs = [1, 2, 3]` is a program whose own source is
    wrong in the other direction from `%s` of an integer: a blob's first word is
    its element COUNT and the vararg placement hands the C library the blob's
    ADDRESS, so `%d` renders the low 32 bits of a heap address. Measured on BOTH
    architectures it printed `1809329920` (arm64) / `1870638832` (x86-64) where
    CPython raises `TypeError: %d format: a real number is required, not list`.
    The kind is POSITIVE evidence — a `list:…` kind is never a default, unlike
    `INT_KIND` — which is why the same `kind_of` the `"int"` hunt must not trust
    is exactly what this class may: a default can only ever say "integer", so a
    container answer cannot be manufactured by an unclassified word.
    """
    if is_float is not None and is_float(expr):
        return "float"
    if isinstance(expr, F.CallExpr):
        # A CALL is never evidence, for the reason `_own_shape_of` gives, and
        # the CONTAINER question does not change that: `kind_of` answers
        # `list:…` for a callee whose declared return type is a container, but
        # it answers `INT_KIND` — this model's DEFAULT for a word — for one it
        # cannot see. Reading a container off a call would refuse
        # `printf("%d", get())` for a callee this build knows nothing about, so
        # the whole call shape is declined here, exactly as the FLOAT question
        # declines it below.
        return None
    if vk is not None and is_list_kind(vk.kind_of(expr)):
        # A CONTAINER: see `printf_kind_conversion_refusal`. The kind is the
        # evidence and it is the operand's OWN shape rather than a name's
        # `own_shape`, because `printf("%d", xs)`, `printf("%d", [1, 2, 3])` and
        # `printf("%d", d)` for a dict are one question asked of three spellings
        # and must not disagree.
        return "container"
    if isinstance(expr, F.IdentExpr):
        if vk is not None and vk.own_shape_kind(expr.name) == INT_KIND:
            return "int"
        return None
    if vk is None:
        return None
    return "int" if vk.kind_of(expr) == INT_KIND else None


def printf_arg_container_evidence(expr, vk) -> str | None:
    """The CONTAINER kind of a `printf` vararg, or None when it is not one.

    The evidence axis the NUMBER conversions were missing. `printf_arg_text_evidence`
    asks whether an operand is TEXT and `printf_arg_float_evidence` whether it is
    a FLOAT or an INTEGER, and neither asks whether it is a CONTAINER — so
    `printf("%d", xs)` placed the vararg from the format, read eight bytes of a
    blob as a decimal and printed the blob's heap ADDRESS on both architectures,
    from a green build, exit 0, where CPython raises

        TypeError: %d format: a list is required, not int

    It is the exact mirror of the refusal that already exists for the other
    direction (`printf("%s", 42)`, whose operand is a number where text is
    required), and it is the same table read from the other side.

    The evidence is `ValueKinds.kind_of` and nothing else, because a container
    is a KIND a word has and not a `None` a word is defaulted to: `is_list_kind`
    is the one predicate that recognises it — `List`, `Tuple`, `Set`, `Dict`,
    `bytearray` and `bytes` all classify as `list:…`, one spelling per element
    kind, so asking it of the KIND rather than of a constructor's name is what
    keeps `printf("%d", xs)`, `printf("%d", d)` and `printf("%d", b)` one answer
    instead of three.

    **A NAME's `own_shape` is deliberately not consulted**, and that is the one
    place this hook differs from the text hook: there the question is "did this
    function BIND the name to an integer on that statement's own shape", which
    is evidence a word cannot otherwise carry, while a container is derived from
    the construction or the declaration by `kind_of` itself. `None` is the
    permissive direction, as it is for both sibling hooks: an unclassifiable
    operand keeps whatever behaviour it had.
    """
    if vk is None:
        return None
    kind = vk.kind_of(expr)
    return kind if is_list_kind(kind) else None


def printf_kind_conversion_refusal(callee: str, fmt_text, args: list,
                                   class_of=None) -> str | None:
    """Why a conversion whose CLASS disagrees with its operand's kind is refused.

    The mirror of `printf_text_conversion_refusal`, and the same rule read from
    the other side: a `printf` conversion states what the C library will do
    with the word it is handed, and both halves have to agree. `%d`/`%c`/`%u`/
    `%x` read the vararg as an integer and `%f`/`%g`/`%e` read it as a double,
    so a double at `%d` is the bit pattern rendered as a decimal and an integer
    at `%f` is the same word read as an exponent. Neither is a rounding; both
    are a wrong number that prints, which is why this is a refusal and not a
    conversion. **Converting is the language's job and it is already there**:
    `Int(x)` is `FCVTZS` (`float_conversion_lowering`'s `FLOAT_TO_INT` arm) and
    `float(x)` is `SCVTF`, so the message names both rather than offering a
    guess.

    **A CONTAINER is the third disagreement**, and it is worse than either
    numeric one: `PRINTF_NUMBER_CONVERSIONS` is refused a container the same way
    a double is refused an integer conversion, because a blob has no C rendering
    at all — its first word is an element COUNT and the vararg placement passes
    its ADDRESS, so `%d` of a list renders the low bits of a heap address.
    `printf("%s", …)` is NOT these: it is `printf_text_conversion_refusal`'s
    question, and `%p`/`%n` are in neither set (Darwin's `%p` renders the address,
    which a blob does have).

    Measured, both architectures, before this existed:

        def f(x: Float64): printf("[%d]", x)      # x = 3.9
        def main(): f(3.9)

    printed `[858993459]`, which is `0x33333333` — the low 32 bits of 3.9's bit
    pattern — and `printf("[%c]", x)` printed `[3]`, which is `0x33`, the same
    two bytes as a character. The other direction printed
    `[3.4584595208887258e-323]` for `printf("%.17g", 7)`. Green builds, exit 0,
    wrong numbers on the screen.

    `class_of` is `printf_arg_float_evidence`'s four-way answer and the
    permissive direction is load-bearing: **None never refuses.** An
    unannotated parameter holding a double (`def show(x): printf("%f", x)`
    called `show(2.5)`) is a program this path prints correctly today, because
    both backends place a vararg from the FORMAT rather than from the operand's
    kind, so a word in the right register is enough. Reading "the source does
    not say" as "not a float" would refuse it.

    `None` for a format this does not parse, the same permissive direction
    `printf_conversion_specifiers` takes: a call whose conversions cannot be
    enumerated keeps whatever behaviour it had.
    """
    if class_of is None:
        return None
    convs = printf_conversion_specifiers(fmt_text)
    if convs is None:
        return None
    for j, conv in enumerate(convs):
        if j >= len(args):
            continue
        got = class_of(args[j])
        if got is None:
            continue
        if got == "container":
            if conv not in PRINTF_NUMBER_CONVERSIONS:
                continue
            return (
                f"the `%{conv}` conversion in {callee}'s format string reads "
                f"`{spelled(args[j])}` as a number, and `{spelled(args[j])}` is "
                f"a CONTAINER — a blob whose first word is its element COUNT and "
                f"whose remaining words are its elements, with no C spelling at "
                f"all. This path hands the format to the C library and a "
                f"container is passed as its ADDRESS, so `%{conv}` renders the "
                f"low bits of a heap address rather than any value the source "
                f"wrote. Measured on BOTH architectures, `printf(\"v=%d\", xs)` "
                f"for `var xs = [1, 2, 3]` printed 1809329920 (arm64) / "
                f"1870638832 (x86-64) from a green build, exit 0, where CPython's "
                f"`\"%d\" % [1, 2, 3]` raises `TypeError: %d format: a real "
                f"number is required, not list`. Refused rather than emitted, "
                f"because no conversion in the format asks for a container: use "
                f"`len(xs)` for the element count, `xs[i]` for one element, or "
                f"render a number the source builds (`String(len(xs))`, `%lld`)"
            )
        wants_float = conv in PRINTF_FLOAT_CONVERSIONS
        if (got == "float") == wants_float:
            continue
        what = ("a double" if got == "float"
                else "a value this function bound to an integer")
        return (
            f"the `%{conv}` conversion in {callee}'s format string reads "
            f"`{spelled(args[j])}` as "
            f"{'a double' if wants_float else 'an integer'}, and "
            f"`{spelled(args[j])}` is {what}. The two do not have to be "
            f"guessed at: `%{conv}` tells the C library how to interpret the "
            f"word it is handed, and the word's own kind says what it is, so a "
            f"disagreement is a rendering of the wrong value rather than a "
            f"rounding of the right one — measured on BOTH architectures, "
            f"`printf(\"[%d]\", x)` for a `Float64` `x` printed 3.9's bit "
            f"pattern as a decimal and `printf(\"[%.17g]\", 7)` printed the "
            f"integer as a denormal. Refused rather than converted, because "
            f"the conversion is the source's decision and this path already "
            f"has both of them: `Int(x)` truncates toward zero and `float(x)` "
            f"rounds to the nearest double"
        )
    return None


def printf_container_conversion_refusal(callee: str, fmt_text, args: list,
                                        kind_of=None) -> str | None:
    """Why a NUMBER conversion of a CONTAINER operand is refused.

    The mirror of `printf_text_conversion_refusal` on the axis the two other
    format checks do not cover. `printf_text_conversion_refusal` owns the `%s`
    that DEREFERENCES its operand; `printf_kind_conversion_refusal` owns the
    float/integer class disagreement. A container is neither a double nor an
    integer: its one word is the address of its blob, so a conversion that reads
    the word as a number renders the heap ADDRESS as a decimal. Measured on BOTH
    architectures, from a green build and exit 0:

        var xs = [1, 2, 3]
        printf("v=%d\\n", xs)

    prints `v=1809329920` on arm64 and `v=1870638832` on x86-64 — the address is
    a property of the run, the defect is not — where CPython raises `TypeError:
    %d format: a number is required, not list`. The two machines agreeing about
    nothing but disagreeing with the program is the shape this table exists for.

    `kind_of(arg)` is the emitter's own `ValueKinds.kind_of` over one argument,
    and the evidence is the operand's own KIND rather than a name's
    `own_shape`: a `[1, 2, 3]` literal, a `List[Int]()` construction and a name
    bound to either are one answer. `is_list_kind` covers a list, a tuple, a set,
    a `bytearray` AND a dict, because all of them classify as `list:*` blobs on
    this path (`ValueKinds.is_dict_value`'s docstring is the measurement: a dict
    and a list are the same word here), so `printf("%d", b)` for a `bytearray`
    and `printf("%d", d)` for a `Dict` are the same shape and get the same
    answer rather than three that disagree.

    A `%s` operand is NOT this function's: `printf_text_conversion_refusal` owns
    the conversion that dereferences, and a container reaching it has that
    function's own answer. This one is every conversion that READS THE WORD AS A
    NUMBER — the floating conversions plus every other non-`s` conversion — so
    the two refusals cannot both fire on one conversion.

    `None` never refuses, the same permissive direction the two siblings take:
    `kind_of` answers `INT_KIND` (not a container) for an unannotated parameter
    and for anything else this build cannot classify, so a program whose
    container-ness is not visible keeps whatever behaviour it had rather than
    being refused for a word.
    """
    if kind_of is None:
        return None
    convs = printf_conversion_specifiers(fmt_text)
    if convs is None:
        return None
    for j, conv in enumerate(convs):
        if j >= len(args) or conv == "s":
            continue
        kind = kind_of(args[j])
        if kind is None or not is_list_kind(kind):
            continue
        return (
            f"the `%{conv}` conversion in {callee}'s format string reads "
            f"`{spelled(args[j])}` as a number, and `{spelled(args[j])}` is a "
            f"CONTAINER — its one word is the address of its blob, so the C "
            f"library renders the heap address rather than a value. Measured on "
            f"BOTH architectures, `printf(\"%d\", xs)` for `xs = [1, 2, 3]` "
            f"printed the blob's address (1809329920 on arm64, 1870638832 on "
            f"x86-64) from a green build and exit 0, where CPython raises "
            f"`TypeError: %d format: a number is required, not list`. Refused "
            f"rather than emitted, because an address is not the number the "
            f"source asked for: pass the count (`len(xs)`), an element "
            f"(`xs[0]`), or render the container to text and use `%s`"
        )
    return None


def word_annotation_is_int(ann, int_names=None) -> bool:
    """Whether a type ANNOTATION says the word it names is an integer.

    One vocabulary, `formal/types.TYPE_NAMES`, read through the hook both
    backends already hand `ValueKinds` as `int_names` — so the two consumers
    below and the value model cannot come to disagree about which spellings
    mean an integer. **`Bool` is in it for the reason `declared_type_kind` maps
    it to `INT_KIND`**: a `Bool` on this path is one word holding 0 or 1, so a
    double's bit pattern in a `Bool` parameter is the same wrong answer as one in
    an `Int` parameter, and asking the narrower question here would leave the
    two out of step. It is NOT in `TYPE_NAMES` because that table's keys resolve
    to an `IntType` and a `Bool`'s width is not something a caller may choose.

    `Pointer[Int]` is **not** refused by this: the annotation is not one word
    (it is a subscript, so it arrives as a string only after the declarer's own
    split) and a pointer parameter is an ADDRESS rather than a value, which is a
    different question with a different reader (`pointer_pointee`).
    """
    if not isinstance(ann, str):
        return False
    text = ann.strip()
    if not text:
        return False
    names = TYPE_NAMES if int_names is None else frozenset(int_names)
    return text in names or text in BOOL_TYPE_NAMES


def call_argument_kind_refusal(callee: str, args: list, declared_params,
                               class_of, int_names=None) -> str | None:
    """Why an ARGUMENT's kind disagrees with the callee's own parameter type.

    `printf_kind_conversion_refusal`'s twin, and it is the second of the two
    consumers that `Pointer[Float64]`'s refusal names as the reason the load
    cannot go through yet. A `printf` conversion states how the C library will
    READ the word it is handed; a parameter annotation states how the CALLEE
    will. They are the same rule about the same word, and there was only ever one
    of them:

        def g(x: Int) -> Int:
            return x + 1

        def main(n: Int) -> Int:
            var d: Float64 = 3.9
            print(g(d))
            return 0

    Measured on BOTH architectures, `g(d)` printed **4615964438073389876** —
    `0x400F333333333334`, which is `3.9`'s bit pattern with `+ 1` applied to it
    as a word — where the interpreter (and CPython, whose annotations are not
    enforced either) answers **4.9**. Green build, exit 0, a number nobody
    wrote, on two machines that agreed with each other and not with the program.

    **The evidence discipline is `printf_kind_conversion_refusal`'s, unchanged and
    deliberately: `class_of` is `printf_arg_float_evidence`'s answer, and a
    `"container"` is simply not `"float"` (this rule asks only about doubles),
    and `None` never refuses.** An unannotated parameter is not evidence against
    a double — `def g(x): return x + 1` called `g(3.9)` is `4.9` here today and
    must stay `4.9` — so a disagreement is only ever claimed where the callee's
    own annotation says integer. That asymmetry is what makes the check safe to
    add to a path with 664 stdlib files behind it: it can only fire on a program
    that says something false about itself.

    `declared_params` is the callee's `params` in ARGUMENT order, one annotation
    string or None per position, and a shorter list than `args` is not an error:
    a varargs or a shape this reader cannot line up contributes no annotation and
    so no claim.
    """
    if class_of is None:
        return None
    for j, ann in enumerate(declared_params or ()):
        if j >= len(args):
            continue
        if not word_annotation_is_int(ann, int_names):
            continue
        if class_of(args[j]) != "float":
            continue
        return (
            f"`{callee}` declares its parameter {j} an "
            f"{ann.strip()}, and `{spelled(args[j])}` is an IEEE double — one "
            f"64-bit word holding a bit pattern, passed where the callee's own "
            f"source says it will be read as an integer. There is no implicit "
            f"conversion between them here, and there is no place for one: a "
            f"call's parameter list is a WORD position, so the double's bits "
            f"arrive as the integer and every arithmetic operation on them "
            f"inside the callee is exact on the wrong number. Measured on BOTH "
            f"architectures, `g(d)` for `d: Float64 = 3.9` and "
            f"`def g(x: Int) -> Int: return x + 1` printed 4615964438073389876 "
            f"— 3.9's bit pattern with 1 added to it as a word — where the "
            f"interpreter answers 4.9. Refused rather than passed, because "
            f"converting is the source's decision and this path already has it: "
            f"`Int(x)` truncates toward zero and `float(x)` rounds to the "
            f"nearest double"
        )
    return None


def return_annotation_kind_refusal(func_name: str, declared_return, value,
                                   class_of, int_names=None) -> str | None:
    """Why a returned value's kind disagrees with the function's OWN annotation.

    The second consumer, and the reason it is a separate function rather than a
    second argument to `call_argument_kind_refusal`: the class is not a
    disagreement at the point the value is produced but at the point a CALLER
    asks about it, and the annotation is read on the other side of that boundary.
    `func_kind` — which every backend already builds to answer "what does a call
    to this produce" — reads the DECLARED return type first, so a callee that
    returns a double under `-> Int` looks like an integer producer and every
    consumer of its result is right to believe it:

        def h() -> Float64:
            return 3.9

        def f() -> Int:
            return h()

        def main(n: Int) -> Int:
            print(f())
            return 0

    Measured on BOTH architectures, `print(f())` printed
    **4615964438073389875** — `0x400F333333333333`, which is `3.9` — where the
    interpreter answers **3.9**. Green build, exit 0.

    **This is the consumer that makes the pointer row load-bearing rather than
    cosmetic.** `Int(p.value())` and `return p.value()` under `-> Int` are the
    two shapes a `Pointer[Float64]` dereference reaches, and the kind hook that
    lets the LOAD through (`pointer_deref_kind`) is exactly what makes this
    refusal necessary: the dereference carries `FLOAT_KIND` now, so both shapes
    reach here and are refused by name instead of printing a bit pattern as a
    decimal, one call boundary away.

    **The annotation is the only evidence, and `None` never refuses** — the same
    asymmetry as `call_argument_kind_refusal` and for the same reason: an
    unannotated `return h()` may well be returning an integer this build cannot
    see, and a function declared `-> Float64` whose body returns an integer is a
    correct program that this must not refuse. So the check fires only where the
    source contradicts itself.
    """
    if class_of is None or value is None:
        return None
    if not word_annotation_is_int(declared_return, int_names):
        return None
    if class_of(value) != "float":
        return None
    return (
        f"`{func_name}` is declared to return {declared_return.strip()} and "
        f"returns `{spelled(value)}`, which is an IEEE double — one 64-bit word "
        f"holding a bit pattern, handed back where this function's own source "
        f"said it would produce an integer. The annotation is what a CALLER "
        f"asks about: `func_kind` reads the declared return type first, so every "
        f"consumer of this call is right to believe it produces an integer and "
        f"wrong about what it is holding. Measured on BOTH architectures, a "
        f"`-> Int` function returning a `-> Float64` call printed "
        f"4615964438073389875 — 3.9, as a decimal — where the interpreter "
        f"answers 3.9. Refused rather than truncated, because the conversion is "
        f"the source's decision and this path already has it: `Int(x)` truncates "
        f"toward zero and `float(x)` rounds to the nearest double"
    )


def one_word_value_text_evidence(candidates, int_names=(), string_names=(),
                                 decls=None):
    """`True` / `None` / an evidence string: is a ONE-FIELD struct's value text?

    The second piece of POSITIVE evidence `printf_text_conversion_refusal`
    accepts, and the last hole in the `%s` family: a struct of one field has no
    frame, so its receiver is not an address there is a frame check for — it IS
    the field — and `ValueKinds.own_shape_kind` cannot see it, because the
    statement that binds the name is a CONSTRUCTION and `_own_shape_of` counts a
    call as no evidence at all. So `printf("[%s]", c)` for `struct One: var x:
    Int` reached C with the integer in hand, and `%s` walked bytes at address 7
    looking for a NUL: SIGSEGV, exit 139, on BOTH architectures, from a green
    build. `formal/build.py`'s `_one_word_constructor_bindings` is the table
    that says the word IS such a struct, and it is the mirror of
    `_constructor_bindings` for the case where there is no block.

    The answer is the field's DECLARED type, and deliberately not
    `struct_field_kind`'s "materialized default" gate: that gate is about a FRAME
    slot, whose word is whatever the constructor stored, while a one-field
    struct's value is a plain word the call site supplied — `One(7)` and `One()`
    both put a non-pointer in it and both fault under `%s`, so the declared type
    is what decides and there is no default to consult.

    `True` when the declaration says a string, which is a WORKING case and is
    the reason this is not "a name in the one-word table is False for `%s`":
    `struct W: var s: String` makes `printf("[%s]", w)` print the bytes, and it
    did so before this function existed, on both architectures. Refusing it
    would be a working program traded for a diagnostic.

    `None` when the candidates do not agree, when one of them has no field kind
    this path can map, or when a candidate is not a one-field struct at all —
    the permissive direction `printf_text_conversion_refusal` argues for at
    length, and it is also what an UNANNOTATED parameter answers, so the two are
    the same hole rather than two.

    The string is the EVIDENCE, and it is returned rather than `False` so the
    refusal can name the declaration that made the call instead of asserting the
    integer default, which would be false about a name bound from a
    construction.
    """
    kinds = {}
    for st in (candidates or ()):
        if st is None or not struct_is_one_field(st):
            return None
        only = struct_sole_field_name(st)
        if only is None:
            return None
        ann = frame_slot_declared_annotation([st], only, decls)
        kind = declared_type_kind(ann, int_names, string_names, decls)
        if kind is None:
            return None
        ann_txt = f"`{ann.strip()}`" if isinstance(ann, str) else "nothing"
        kinds.setdefault(kind, []).append(f"{st.name}.{only} ({ann_txt})")
    if len(kinds) != 1:
        # Two one-field structs bound to one name whose fields hold different
        # things: there is no one answer, and picking one would be a claim
        # about whichever candidate was reached first.
        return None
    kind, (spelling, *_rest) = next(iter(kinds.items()))
    if string_operand_is_string(kind):
        return True
    return (
        f"a `{next(iter(candidates)).name}` receiver, whose whole value IS its "
        f"one field {spelling} — a struct of ONE field has no frame at all, so "
        f"there is no address here for any of the frame checks to look at, and "
        f"the declaration says that field holds no text"
    )


# The callees whose LAST NAMED argument is the format string, and therefore the
# only ones whose format can be found from `VARIADIC_LIBC`'s own count of named
# arguments.  `err`/`errx`/`warn`/`warnx` are deliberately NOT here: the table
# records ONE named argument for them, and BSD's spelling is
# `err(int eval, const char *format, ...)` — two — so for those the format is
# not at `named - 1` and this check must not guess it.  `open` is not a format
# function at all.  Every name is a member of `VARIADIC_LIBC`, which is what
# makes `printf_format_arg_index` total.
PRINTF_FORMAT_CALLEES = frozenset({
    "printf", "asprintf", "fprintf", "dprintf", "sprintf", "snprintf", "syslog",
})


def printf_format_arg_index(callee: str):
    """Which argument of `callee` is its format string, or None if not one.

    DERIVED from `VARIADIC_LIBC` rather than written down: the format is the
    last NAMED argument of every function in `PRINTF_FORMAT_CALLEES`, so the
    index is `named - 1` and there is no second table to fall out of step.  The
    two architectures ask this rather than hard-coding `args[0]`, which is what
    makes `sprintf`'s buffer argument impossible to mistake for a format.
    """
    bare = callee.lstrip("_")
    if bare not in PRINTF_FORMAT_CALLEES:
        return None
    named = variadic_named_args(bare)
    if named is None:                             # pragma: no cover
        return None
    return named - 1


def printf_missing_operand_refusal(callee: str, fmt_text, nargs: int):
    """Why a format that asks for more arguments than the call was given.

    `nargs` is the number of operands AFTER the format, which is what
    `printf_conversion_specifiers` enumerates against.

    **The construct:** in a C variadic call every conversion in the format is a
    request for one more argument. A format with a conversion and no argument
    behind it is a program that reads a word nobody wrote, and the C library
    will faithfully print whatever was in it — which is why the two machines
    disagree about `printf("50% done")`. `% d` is a conversion specification
    (the space flag, then `d`), which is the shape that appears in prose and is
    therefore the one a corpus is most likely to contain:

        arm64:   50 0one          x86-64: 50143074168one

    Both are reading a vararg that was never passed. **Neither backend is
    lenient and neither is faithful** — the reading was recorded as an arm64
    leniency and it is not: arm64's unnamed arguments come from the stack area
    at `[SP]` as it stands at the call (`VARIADIC_LIBC`'s own note), and on this
    host that word is zero, so `% d` prints the flag and a `0`. A program that
    put anything else there would print anything else. Measured on this tree, one
    program, both architectures, and the value changes between two identical
    calls in the same run on x86-64 (`160347000`, then `73896`) because SysV
    passes varargs in the caller-saved argument registers, which the previous
    call left full.

    So the answer is not to pick a backend's behaviour and make the other match
    it. The whole `printf` surface on this path is "handed through to libc", and
    a format string that cannot be satisfied is a program whose output is a
    number the source never wrote. That wants a refusal of its own rather than
    `gimple_runtime_refusal`'s library text, and it wants the DECISION to be one
    function in this file asked by both backends, because two backends
    disagreeing about a format string is precisely the failure this backend
    exists to prevent.

    **`fmt_text` that does not parse is NOT refused** (`convs is None`), which
    is `printf_conversion_specifiers`'s own permissive direction: a trailing
    `%` and a `%` followed by a non-conversion character are both undefined
    behaviour in C rather than something this model can count, and a new
    refusal there would be a refusal of a shape nobody has measured. What is
    refused is the shape whose arithmetic is exact: more conversions than
    operands.

    `print()` is unaffected by construction and must stay so. `print_literal`
    doubles every `%` in a literal, so `print("50% done")` reaches `printf` as
    `50%% done` — zero conversions, zero operands — and this check sees the
    generated call like any other and answers "nothing wrong". Sweeping the two
    spellings together would break the one that works.
    """
    idx = printf_format_arg_index(callee)
    if idx is None or not isinstance(fmt_text, str):
        return None
    convs = printf_conversion_specifiers(fmt_text)
    if convs is None or len(convs) <= nargs:
        return None
    missing = len(convs) - nargs
    return (
        f"{callee}'s format string {fmt_text!r} has {len(convs)} conversion "
        f"specification(s) and the call is given {nargs} operand(s) after it, "
        f"so {missing} of them read a vararg nobody passed. In a C variadic "
        f"call every conversion is a request for one more argument, and the C "
        f"library prints whatever word it finds there — this path hands the "
        f"format straight to it, so the number that appears is a leftover, not "
        f"anything the source wrote. Measured on BOTH architectures from this "
        f"same source: arm64 printed `50 0one` and x86-64 printed "
        f"`50143074168one` for `printf(\"50% done\")` — `% d` is a space flag "
        f"followed by `d`, so it is a conversion, and the two machines "
        f"disagree only about what was left in the register or stack slot it "
        f"reads. Refused rather than emitted, because a missing operand is not "
        f"a wrong rendering. Escape it (`%%`) if you meant a literal percent "
        f"sign, or pass the {missing} argument(s) the conversions ask for"
    )


def printf_format_refusal(callee: str, fmt_text, args: list, text_of,
                         text_of_arg=None, class_of=None, container_of=None):
    """Any reason `callee`'s FORMAT cannot be used, or None if it can.

    **The one entry point both backends ask**, and the reason it exists rather
    than two: there are now five ways a format string fails here — a `%s`
    handed something that is not text (`printf_text_conversion_refusal`), a
    conversion with no argument behind it
    (`printf_missing_operand_refusal`), a WIDTH on a `%s` whose argument is
    text that is not ASCII (`printf_text_width_refusal`), a conversion whose
    CLASS disagrees with the kind of the argument behind it
    (`printf_kind_conversion_refusal`), and a NUMBER conversion of a CONTAINER
    (`printf_container_conversion_refusal`) — and two emitters that each had to
    remember them is exactly how arm64 and x86-64 come to disagree about what a
    `printf` means. One function, one order, one message table.

    The order is the one that matters if two could fire: a missing operand and
    a `%s` of a non-text argument are both more basic facts about the CALL than
    the width is, and naming them first is the more useful refusal, since the
    fix is in the format rather than in the argument's text. The last two come
    last because they need the argument's VALUE rather than its text, and a
    format already known to be unusable is not worth a second, deeper question
    about the same call. They cannot both fire: the class check refuses only a
    disagreement with `%f`/`%g`/`%e`, and a container is refused only by the
    non-`s`, non-float conversions, whose class evidence is never `"float"`.

    `text_of_arg` is the fourth hook and it is the only one of the first two
    that is optional: it answers "what TEXT does this argument carry" (None for
    anything whose text this build cannot see) where `text_of` answers "is this
    argument text at all". The width question needs the first and the conversion
    question needs the second, and a caller that has no way to answer the first
    passes None — which is the permissive direction, exactly as `text_of`'s own
    None row is. **`class_of` is optional for the same reason**: it is
    `printf_arg_float_evidence`'s three-way answer, and a caller that has no
    `ValueKinds` to hand passes None, which never refuses. **`container_of` is
    the same**: it answers the OPERAND'S KIND (`ValueKinds.kind_of`) and a
    caller with no `ValueKinds` passes None.
    """
    return (printf_missing_operand_refusal(callee, fmt_text, len(args))
            or printf_text_conversion_refusal(callee, fmt_text, args, text_of,
                                             text_of_arg)
            or printf_container_conversion_refusal(callee, fmt_text, args,
                                                   container_of)
            or printf_kind_conversion_refusal(callee, fmt_text, args,
                                              class_of)
            or printf_container_conversion_refusal(callee, fmt_text, args,
                                                   container_of))





# ── `int(s, base)`: a PARSE, not a conversion ─────────────────────────────────
#
# A conversion takes one operand and `int(x)` for a NUMBER is one: it is an
# `IntN(...)` width/sign change and `INT_TYPE_CTORS` is the table of them. What
# is not a conversion is `int(s, base)`, where the first operand is TEXT and the
# second is a parameter of the same operation rather than a second value. The
# two backends each carried the refusal for that as a private copy of one arity
# test, which is why a construct the language has and the target can express was
# refused identically on both machines with a message about arity.
#
# The answer needs no new storage and no new value: it is a machine word, which
# is what a formal value already is, and `strtoll` is libc, already on the link
# line and already used for `strlen` and `strncmp`. What the lowering CANNOT
# skip is the validation — `strtoll` returns 0 for a string with no digits in it
# where CPython raises `ValueError` — so the emitters pass an `endptr` and stop
# the program when it is not at the end (see `int_parse_trap_message`).
#
# The one-operand `int(s)` is in the SAME table and was the worse defect: with
# one operand the old arity test did not fire, so a string was read as the NUMBER
# its bit pattern is and `int("41")` answered the ADDRESS OF THE LITERAL. The two
# architectures answered different addresses for the same program
# (`a=48694217` on arm64, `a=4449243` on x86-64, measured), which is the
# divergence this pair of backends is not allowed to have.

#: C's six whitespace characters, as the NUL-terminated string `strspn` measures
#: a run against. In `model.py` and not in either emitter because it is a fact
#: about CPython's `int(s)` that BOTH backends have to honour, and two copies of
#: a six-character set is two chances for them to disagree about whether
#: `int(" 41 ")` is 41.
C_WHITESPACE = " \t\n\v\f\r"

#: `0` is CPython's "detect the base from the prefix". It is named here because
#: the REFUSAL below has to name what it refuses, and it is not a base this path
#: accepts — see `int_parse_base_is_valid`.
INT_PARSE_BASE_AUTO = 0
INT_PARSE_BASE_MIN = 2
INT_PARSE_BASE_MAX = 36


def int_parse_base_is_valid(base) -> bool:
    """Whether `base` is a base both CPython's `int(s, base)` and `strtoll` take.

    `2..36`, and nothing else. **`0` is NOT valid**, which is the one decision
    here that a reader is most likely to disagree with, so it is measured rather
    than argued: CPython's auto-detection and C's are the same function with
    three different rules, and `strtoll` is the only implementation available on
    this path.

    | spelling | CPython | `strtoll(s, &end, 0)` |
    |---|---|---|
    | `"41"` | 41 | 41 |
    | `"0x1f"` | 31 | 31 |
    | `"0o17"` | 15 | stops at `o` — 0 |
    | `"0b1"` | 1 | stops at `b` — 0 |
    | `"017"` | `ValueError` | 15 |
    | `"00"` | 0 | 0 |
    | `"1_000"` | 1000 | 1 |
    | `"  41  "` | 41 | 41 (leading skipped, trailing needs the `strspn` the emitters do) |

    Three of those are a WRONG ANSWER rather than a missing one: `0o`/`0b` would
    answer 0 for a value that is 15 and 1, and `017` answers 15 where CPython
    raises. Answering them needs CPython's rule written out — skip whitespace,
    take a sign, apply it to the digits rather than to the string, then decide
    among four prefixes and validate the digit class — which is a mini-parser in
    two backends for a spelling whose only user in this repository is
    `mlir.py`'s `int(head, 0)` on a hex string, and `int(head, 16)` says the same
    thing. So base 0 is REFUSED by name, which is the direction this path takes
    everywhere else: `model.int_parse_base_refusal` states the bases that do
    work rather than approximating one that does not.
    """
    return (isinstance(base, int) and not isinstance(base, bool)
            and INT_PARSE_BASE_MIN <= base <= INT_PARSE_BASE_MAX)


def int_parse_lowering(name: str, operands: list, text_of) -> tuple:
    """`("parse", base)` | `("convert", None)` | `("refuse", reason)`.

    The decision is arch-free and it is HERE rather than in either backend's
    conversion emitter, for the reason every other rule on this path lives here:
    both backends carried the same refusal as two copies of one arity test, and
    two copies are how a construct ends up answered one way on arm64 and another
    on x86-64.

    `text_of(op)` is the emitter's THREE-WAY question "is this operand text",
    the same shape `printf_text_conversion_refusal` is written against and for
    the same reason:

    | `text_of` | meaning | `int(op)` | `int(op, base)` |
    |---|---|---|---|
    | `True` | the operand is a string | a parse in base 10 | a parse in `base` |
    | `False` | it is not, and the source says so | a conversion (unchanged) | refused |
    | `None` | the source does not say | a conversion (unchanged) | refused |

    **`None` is the permissive direction and it is load-bearing.** An
    unannotated parameter is a word this build cannot classify, and
    `int(n)` where `n` really is a number is the conversion this path has always
    performed; reading "not known to be text" as "text" would parse a number as
    digits, and reading it as "not text" for the ONE-operand form would refuse
    every numeric `int(x)` in the corpus. So the one-operand form keeps today's
    answer for an undecided operand and the two-operand form refuses, where the
    second operand's meaning makes guessing impossible in both directions.

    A base is a COMPILE-TIME constant here (`fold_literal_expr`, which also
    answers `0 - 1` and `1 * -1`), because `strtoll` takes it as an immediate in
    both lowerings and because a base computed at run time is a different
    question: it would need a register and, on arm64, a frame slot to survive
    the call. It is refused by name rather than approximated.
    """
    if len(operands) == 1:
        if text_of(operands[0]) is True:
            return ("parse", 10)
        return ("convert", None)
    if len(operands) != 2:
        return ("refuse", int_parse_arity_refusal(name, len(operands)))
    if text_of(operands[0]) is not True:
        return ("refuse", int_parse_non_text_refusal(name, spelled(operands[0])))
    base = fold_literal_expr(operands[1])
    if base is None:
        return ("refuse", int_parse_base_refusal(
            name, spelled(operands[1]),
            "it is not a constant the build knows, and the base is passed to "
            "`strtoll` as an immediate in both lowerings — a base read at run "
            "time would need a slot of its own to survive the call, and it is a "
            "different question from a stated one"))
    if not int_parse_base_is_valid(base):
        why = ("0 is CPython's \"detect the base from the prefix\", and this "
               "path cannot: `strtoll` is the only parser here and its "
               "auto-detection is not CPython's — `int(\"0o17\", 0)` is 15 and "
               "`strtoll` gives 0, `int(\"0b1\", 0)` is 1 and `strtoll` gives "
               "0, and `int(\"017\", 0)` RAISES where `strtoll` gives 15. Two "
               "of those are wrong answers rather than missing ones, and the "
               "alternative is CPython's prefix rule written out by hand in "
               f"both backends. Say the base: {INT_PARSE_BASE_MIN} through "
               f"{INT_PARSE_BASE_MAX} are exact, and `int(s)` is base "
               f"{INT_PARSE_BASE_MIN + 8}"
               if base == INT_PARSE_BASE_AUTO else
               f"{base} is not a base (CPython's `int(s, base)` takes "
               f"{INT_PARSE_BASE_MIN}..{INT_PARSE_BASE_MAX})")
        return ("refuse", int_parse_base_refusal(name, spelled(operands[1]),
                                                 why))
    return ("parse", int(base))


def int_parse_arity_refusal(name: str, got: int) -> str:
    """`f(x, y, z)` where a conversion or a parse takes at most two."""
    return (f"{name}(...) takes exactly one value to convert on this path "
            f"(got {got} argument(s))")


def int_parse_non_text_refusal(name: str, operand: str) -> str:
    """`int(x, base)` where the first operand is not text.

    A different refusal from the arity one on purpose: the arity message is
    about a count, and the count here is right. What is wrong is the CATEGORY —
    the second operand is a BASE, and a base is a parameter of a parse, so this
    is only a question when the first operand is a string. CPython raises
    `TypeError` for the same program.
    """
    return (f"{name}({operand}, ...) is refused on this path: the second "
            f"operand of this call is a BASE, so the first is a string to parse "
            f"and `{operand}` is not one this build knows to be text. "
            f"`{name}(x)` with one operand is still the number conversion it "
            f"always was; it is the second operand that makes this a parse, and "
            f"a parse of a number is not a question this path answers")


def int_parse_base_refusal(name: str, base: str, why: str) -> str:
    """A base this path cannot state to `strtoll`.

    The whole reason is the `why`, and it is a parameter rather than a sentence
    here because the two reasons are genuinely different facts about different
    things: a base read at RUN TIME is a register and a slot to keep across the
    call, and base 0 is a RULE this path does not have. Both are refusals and
    both are about the second operand, so one wording is one sentence each.
    """
    return f"{name}(s, {base}) is refused on this path: {why}."


def int_parse_trap_message(base: int) -> str:
    """The ONE text a failed parse writes to fd 2 before it stops the program.

    For BOTH backends, because two architectures printing two different sentences
    for one limit is how a reader ends up looking for a construct one of them
    invented — and the shape is `list_append_overflow_message`'s, which is the
    only other place on this path where a bounded operation that cannot be
    decided at build time stops at run time and says which bound it hit.

    **Why a stop and not an answer.** `strtoll` returns 0 and leaves `errno` set
    when it finds no digits, and returns the digits it managed when the rest of
    the string is not in the base; CPython raises `ValueError` for both. This
    path has no exception, so the two arms are refused rather than answered: the
    `endptr` is checked against the end of the string and the program stops if
    it is not there. `0` is not available as the answer either — `int("0")` is 0
    and `formal/hostmods/argparse.mojo`'s own `is_decimal` says so — so nothing
    here distinguishes "parsed zero" from "parsed nothing" but the endptr.
    """
    spelled_base = f"base {base}"
    return (f"ValueError: this program called int(s, ...) on a string that is "
            f"not an integer in {spelled_base}, and left it at least as it "
            f"found it. CPython raises ValueError for that program; this "
            f"formal image has no way to raise, so it stops here rather than "
            f"answer the 0 strtoll returns for a string with no digits in "
            f"it.\n")


def _is_zero_literal(e) -> bool:
    """True for the integer literal `0` and for `0 - 0`, and nothing else.

    NOT a string `"0"`: `s == "0"` asks whether a string is the
    one-character string, and that is a content comparison. `s == 0` asks
    whether a pointer is NULL, which on this target is a different question
    with a different answer, and the line between them is drawn by
    `string_is_null_test`.
    """
    if isinstance(e, F.IntLiteral):
        return e.value == 0
    if isinstance(e, F.UnaryOp) and e.op == "-":
        return isinstance(e.operand, F.IntLiteral) and e.operand.value == 0
    return False


def string_is_null_test(left, right) -> bool:
    """True for `p == 0` / `p != 0` where the other side is not also a zero.

    A POINTER'S NULL TEST, and the reason a function that can return NULL
    cannot be annotated `-> str` on this path without breaking its own caller.
    A string is a bare `char *`, a NULL string is 0, and "is it there" is
    written `x == 0` — which is what every function in
    `formal/hostmods/os` does with `getenv`, `realpath`, `strchr` and `getcwd`.
    With the annotation in place `x` is classified a string, one side of `==`
    is a string, and the comparison this would otherwise choose is
    `strcmp(x, "0") == 0` — a CONTENT comparison that dereferences the very
    NULL the test was written to detect.

    The decision lives beside `string_comparison_lowering` because the two
    answers are chosen from the same pair of operands, and a third caller
    asking the question separately is how two architectures come to disagree
    about whether a program works.

    Python has no such spelling — `s == 0` is False for every string there — so
    this is a RECORDED DIVERGENCE and not an approximation of an answer. What it
    is instead is the one reading that makes a pointer test mean what the
    pointer's own convention says, and the alternative is that every
    NULL-returning function on this path stays unannotated forever, which
    reopens `FORMAL_string_equality_of_two_unclassified_words` for every
    caller of one.
    """
    return ((_is_zero_literal(left) and not _is_zero_literal(right))
            or (_is_zero_literal(right) and not _is_zero_literal(left)))


def string_comparison_lowering(op: str, left_kind, right_kind,
                               left=None, right=None):
    """How `a {op} b` lowers when either side is a string: content, identity,
    or None when it is not a string comparison.

    `==` and `!=` are CONTENT, i.e. `strcmp(a, b) == 0` — the same libc call
    `startswith` already makes, for the same reason: it is the algorithm, so
    there is no second implementation of it here to be subtly wrong. The old
    lowering compared the two POINTERS, which is right for two interned
    literals — interning is by content, so equal literals are the same object
    — and wrong for every derived interior pointer, which is exactly what
    `lstrip` returns and what every sub-range method would:

        m = "  abc".lstrip()
        m == "abc"          # False on the pre-change tree, on BOTH backends

    A correct program taking the wrong branch, which is worse than a number
    being wrong: nothing downstream can tell.

    `is` and `is not` stay IDENTITY, i.e. the pointer compare they already
    were, and this is the one place where the pointer is the ANSWER rather than
    an approximation of it: `a is b` asks whether two names hold one object,
    and with interning by content two equal literals already are one object.
    Routing them through `strcmp` would make `x is y` true whenever the
    CONTENTS match, which is a different question spelled the same way. This
    function exists so that the two pairs cannot be routed together by accident
    in one backend and not the other — the cost of getting it wrong is a
    correct-looking comparison that answers the wrong question, on one
    architecture.
    """
    if not (string_operand_is_string(left_kind)
            or string_operand_is_string(right_kind)):
        return None
    if op in ("==", "!="):
        # The NULL test, asked BEFORE the content compare and only of a pair
        # whose SYNTAX the caller has in hand. `left`/`right` are optional
        # because a caller with no nodes cannot ask, and a caller with no nodes
        # is not deciding about `p == 0` — see `string_is_null_test` for why the
        # question exists and what it costs to get wrong. Every comparison site
        # in both backends passes them, so one architecture cannot be answering
        # `p == 0` and the other `strcmp(p, "0")`.
        if left is not None and right is not None \
                and string_is_null_test(left, right):
            return None
        return STRING_COMPARE_CONTENT
    if op in STRING_IDENTITY_OPS:
        return STRING_COMPARE_IDENTITY
    return None


def string_concat_refusal(op: str, left_kind, right_kind) -> str | None:
    """Why `a {op} b` cannot be lowered when BOTH sides are strings, or None.

    The name is historical and the docstring should not pretend otherwise:
    `+` was the only member when this was written, and it is still the one
    carrying the measured transcript. `-` joined it because address minus
    address is the same missing buffer as address plus address, and because
    leaving it out meant `s = s - t` was refused while `s -= t` was not — the
    same operator, two answers, from the same two backends. The augmented
    spellings are in the set because the AUGMENTED emitters are a separate code
    path from the binary ones and have to be caught by name.

    The measured state of `+`, on the pre-change tree and on both backends:

        s = "ab" + "cd"; printf("[%s]\\n", s)

    printed `[]` on arm64 and SEGFAULTED on x86-64. The reason is the
    representation and nothing else: a string is a POINTER, so `+` is integer
    addition of two addresses, and the sum is an address no mapping covers.
    Concatenation is not a longer string, it is a buffer of a size that is a
    function of both operands and that nothing knows at compile time — the same
    missing buffer that keeps `upper` and `replace` in
    LENGTH_DEPENDENT_METHODS. It is listed here rather than there because the
    failure it produces is worse than a refusal in that table: `strip` builds
    and prints a plausible wrong STRING, and this one prints a plausible wrong
    STRING on one architecture and crashes on the other, so the two backends
    do not even agree on whether the program works.
    """
    if op not in STRING_TWO_STRING_ARITHMETIC_OPS:
        return None
    if not (string_operand_is_string(left_kind)
            and string_operand_is_string(right_kind)):
        return None
    return (
        f"{op!r} on two strings is refused on this path. A string here is a "
        f"bare `char *`, so `{op}` is integer arithmetic on two addresses, and "
        f"what it produced was measured: `print(\"ab\" + \"cd\")` printed `[]` "
        f"on arm64 and segfaulted on x86-64. Concatenation needs a buffer whose "
        f"size is a function of both operands, and this path has no heap to "
        f"allocate one in and no writable copy of the receiver's bytes to lay it "
        f"down in — a string literal is interned into __TEXT,__text, which is "
        f"mapped read+execute. This is the same missing buffer that keeps "
        f"`upper`, `replace` and `join` refused; see LENGTH_DEPENDENT_METHODS")


# `+`/`+=` and `-`/`-=`: the operators whose refusal is about TWO strings and
# the buffer their result would need. Every other operator in the arithmetic
# table is refused on a single string operand too, and is not here.
STRING_TWO_STRING_ARITHMETIC_OPS = ("+", "+=", "-", "-=")




# ── f-strings and t-strings: a LITERAL whose text is not its value ─────────
#
# `fire_compiler.py`'s placeholder scan (`replace_tstrings_with_placeholders`)
# puts the WHOLE SOURCE TOKEN of an f-string or t-string into the string cache
# under a `__MOJO_STR_n__` name, so the `StringLiteral` the parser hands on
# carries `f"n={n}"` — prefix, quotes, braces and all — as its `value`. That is
# a deliberate shape, and one consumer reads it: `myinterpreter.eval_StringLiteral`
# sees the `f"` prefix, strips it and evaluates the `{...}` fields through the
# interpreter's own expression machinery, which is why `fire.py run` answers
# `n=7` where CPython answers `n=7`.
#
# The formal path decoded that value as TEXT, because `decoded_literal` is the
# reader every engine uses and an f-string is a `StringLiteral` like any other.
# So the interpolation was never evaluated and the program ran with the SOURCE
# SPELLING as its value. Measured on both architectures, exit 0 in every case,
# which is what makes this the class the whole backend's refusals exist for:
#
#     n = 7
#     print(f"n={n}")       ->  f"n={n}"   (CPython: n=7)
#     print(len(f"n={n}"))  ->  8           (CPython: 3)
#     if f"n={n}" == "n=7"  ->  false       (CPython: true)
#     print(f"{{lit}}")     ->  f"{{lit}}"  (CPython: {lit})
#
# The last one is the `{{` escape, so the wrong value is not even the same text
# twice. Composition is what is missing, and it is the same missing BUFFER
# `string_concat_refusal` above names: a string on this path is a bare
# `char *` interned into read+execute `__TEXT`, so there is nowhere to lay down
# `"n=" + decimal(n)` — not at compile time, because the field may be a runtime
# value, and not at run time, because there is no heap. So this is a REFUSAL,
# and it is asked over the whole module rather than at each use site, because
# every use site is a different one (a `print` fragment, a comparison, a
# subscript, a `len`, an intern) and a construct this path cannot represent
# should be declined by name rather than answered by whichever reader happened
# to see it first.
#
# Spelled as the parser's own flag rather than as a set of prefixes: the
# question is decided where the source token is, and an ordinary literal's
# `value` is its BODY — so a prefix test cannot tell `f"n={n}"` from `'f"n"'`,
# which is a four-character string.
def _eval_constant_field_expr(expr: str):
    """Evaluate a simple constant literal expression in an f-string field.

    Returns (ok, value). ok is True if foldable, value is the Python value.
    """
    if not isinstance(expr, str):
        return (False, None)
    expr_stripped = expr.strip()
    if not expr_stripped:
        return (False, None)
    # Try ast.literal_eval first (handles most cases)
    try:
        import ast
        try:
            val = ast.literal_eval(expr_stripped)
            return (True, val)
        except Exception:
            pass
    except Exception:
        pass
    return (False, None)


def fold_interpolated_literal(node) -> bool:
    """Rewrite an f-string with NO `{…}` fields into the plain literal it is.

    Also rewrites f-strings where EVERY field is a constant literal expression
    (like `f"n={5}"`, `f"{'a'}b{None}"`) into the plain literal they denote,
    since all values are known at compile time and no runtime buffer is needed
    for composition.

    `f"n=7"` has no replacement field, so its value is its text and CPython
    treats it exactly as `"n=7"` — the `f` prefix changes nothing. On this path
    there is no buffer, so a FIELD is refused (`interpolated_literal_refusal`),
    but a field-LESS literal needs no buffer at all: it is the same interned
    `__TEXT` bytes `"n=7"` already is, through the same `_intern_string`.
    Refusing it refuses correct source and a spelling the corpus writes, and the
    message then told the reader to rewrite a literal that was already a plain
    one.

    Returns True when `node` was rewritten IN PLACE and False when it still has a
    field (and must be refused) or is not an f-string. The rewrite is a plain
    `StringLiteral` step: `value` becomes the body, `is_interpolated` clears, and
    `is_raw` records an `r` in the prefix, because the body of `rf"a\\nb"` must
    stay four characters just as `r"a\\nb"` does (`fire_compiler.decoded_literal`
    is the one reader of that distinction). A `t"…"` template is NOT folded even
    with no fields: its value is a `Template`, not the text, so it stays on the
    refusal path.
    """
    if not is_interpolated_literal(node):
        return False
    spelled = getattr(node, "value", "")
    if not isinstance(spelled, str):
        return False
    quote_at = interpolated_literal_quote_start(spelled)
    prefix = spelled[:quote_at]
    if "t" in prefix or "T" in prefix:
        return False
    try:
        segs = interpolated_literal_segments(spelled)
    except CodegenError:
        return False
    # Check if all segments are literals, or all fields are constant literals
    result_parts = []
    for seg in segs:
        if seg[0] == "lit":
            result_parts.append(seg[1])
            continue
        elif seg[0] == "field":
            # field is ('field', expr, spec, conv)
            _kind, expr, spec, conv = seg
            # Don't fold if there are format specs or conversions
            if spec or conv:
                return False
            ok, val = _eval_constant_field_expr(expr)
            if not ok:
                return False
            # Convert to string as f-strings do by default
            if val is None:
                result_parts.append('None')
            elif isinstance(val, bool):
                result_parts.append('True' if val else 'False')
            elif isinstance(val, str):
                result_parts.append(val)
            elif isinstance(val, (int, float)):
                result_parts.append(str(val))
            else:
                result_parts.append(str(val))
            continue
        else:
            return False
    node.value = "".join(result_parts)
    node.is_interpolated = False
    node.is_raw = "r" in prefix or "R" in prefix
    return True


def is_interpolated_literal(node) -> bool:
    """Whether `node` is a `StringLiteral` that was WRITTEN as an f-string or a
    t-string.

    False for anything that is not a literal, and false for an ordinary string
    however it is spelled — the answer is `StringLiteral.is_interpolated`, which
    the parser sets from the source token and the node carries from there on. An
    interpolated literal's `value` is its source token (`f"n={n}"`) and an
    ordinary one's is its body, but nothing about the BODY says which it is, so
    a reader that asks the value sees `f"n"` in both cases: `s = 'f"n"'` was
    refused here as an f-string, and printed `n` on the other two engines.
    """
    return isinstance(node, F.StringLiteral) and bool(
        getattr(node, "is_interpolated", False))


def _is_string_prefix_letter(c: str) -> bool:
    """True for a character a Python string prefix may be spelled with.

    Explicit `==` comparisons rather than `c in 'fFrR…'`, for the reason
    `fire_compiler.py::_string_prefix_start` gives in full: this codegen's
    compiled `in`-for-char*-against-char* is a documented stub that always
    returns False, so under self-hosting an `in`-based check here would never
    advance and every prefixed literal would go unread.
    """
    return (c == 'f' or c == 'F' or c == 'r' or c == 'R'
            or c == 'b' or c == 'B' or c == 'u' or c == 'U'
            or c == 't' or c == 'T')


def interpolated_literal_quote_start(spelled: str) -> int:
    """Where the opening QUOTE of an interpolated literal's token begins.

    The prefix is a SET OF SPELLING FLAGS, not one character: `f`, `t`, `r`,
    `b` and `u` in any order and up to two of them, so `rf"…"` and `fr"…"` both
    open their quote at index **2** while `f"…"` opens it at 1. The reader below
    used to ask `spelled[1]`, which for `rf` is the `f`, and then reported a
    missing quote that was not missing — `bugs/formal/FORMAL_the_interpolated_literal_
    reader_assumes_a_one_character_prefix.md`. The lexer above it
    (`fire_compiler.py::_string_prefix_start` / `_prefix_is_interpolated`) has
    known the prefix width since 2026-10-05; this is the one answer the reader
    was missing, and it is a function rather than an index so the two layers
    name the same fact.

    **Two, not more, because that is what the language allows** and what
    `fire_compiler.py::_string_prefix_start` scans for: a legal prefix is one
    of `r`/`u`/`b`/`f`/`t` or a pair. The scan stops at the first character
    that is not a prefix letter — which is the quote — so a body that begins
    with `f` cannot be over-consumed.
    """
    i = 0
    while i < 2 and i < len(spelled) and _is_string_prefix_letter(spelled[i]):
        i += 1
    return i


def interpolated_literal_segments(spelled: str) -> list:
    """`[('lit', text) | ('field', expr, spec, conv)]` — an f-string's own parts.

    **The source token, split into the chunks and the `{…}` fields it is made
    of, with `{{` and `}}` honoured as the escapes they are.** That is the whole
    of what this answers, and it is asked of the TOKEN because that is what the
    parser preserved: an interpolated literal's `value` is `f"n={n}"` including
    the prefix and the quotes (`fire_compiler.py`'s
    `_strip_string_prefix_and_quotes`), so the fields are text inside a string
    rather than a parsed structure, and nothing else in the tree has read them.

    A `field` is `(expr, spec, conv)` rather than one string because those
    three are three different questions and this is the place that can tell them
    apart: `expr` is a value, `:spec` is a FORMAT (`>3`, `04d`) and `!conv` is a
    CONVERSION (`!r`, `!s`) — and neither of the latter two is a value on this
    path in any case, which is what
    `bugs/formal/FORMAL_string_composition_has_no_buffer.md` §7.3 says a lowering has
    to say rather than answering them as if they were an f-string's field.

    Brace-depth tracked, so `f"{d['k']}"` and `f"{ {'a': 1}['a'] }"` split
    correctly — a naive `find('}')` truncates the first one at the dict literal.

    **It refuses rather than guesses** on the two shapes it cannot read: a
    triple-quoted body whose closing delimiter it cannot confirm, and a nested
    `{` inside a field's own text at depth it cannot close. Both raise
    `CodegenError` with a message that says what it saw, because a segment
    reader that returned a plausible wrong split would feed a lowering the wrong
    literal text — and a composed string with a chunk boundary in the wrong
    place is a wrong answer, not a refusal.
    """
    if not isinstance(spelled, str) or len(spelled) < 3:
        raise CodegenError(
            f"cannot read an interpolated literal from {spelled!r}: it is not "
            f"even a quoted token, so there are no parts to compose")
    # The prefix is a SET OF SPELLING FLAGS, not one character — `rf"…"` and
    # `fr"…"` are two letters, and the quote is at index `quote_at`, not 1.
    # `interpolated_literal_quote_start` is the one reader of that width (the
    # lexer's own is `fire_compiler.py::_string_prefix_start`).
    quote_at = interpolated_literal_quote_start(spelled)
    quote = spelled[quote_at] if quote_at < len(spelled) else ""
    if quote != '"' and quote != "'":
        raise CodegenError(
            f"cannot read an interpolated literal from {spelled!r}: it has no "
            f"opening quote after its prefix, so where its text starts is not "
            f"knowable from the token")
    if spelled[quote_at:quote_at + 3] == quote * 3:
        term = quote * 3
    else:
        term = quote
    if not spelled.endswith(term) or len(spelled) < quote_at + 2 * len(term):
        raise CodegenError(
            f"cannot read an interpolated literal from {spelled!r}: it opens "
            f"with {term} and does not end with {term}, so where its text "
            f"stops is not knowable from the token")
    body = spelled[quote_at + len(term):-len(term)]
    out: list = []
    lit: list = []
    i, n = 0, len(body)
    while i < n:
        two = body[i:i + 2]
        if two == '{{':
            lit.append('{')
            i += 2
            continue
        if two == '}}':
            lit.append('}')
            i += 2
            continue
        c = body[i]
        if c == '}':
            # A lone `}` with nothing to escape. CPython 3.14's tokenizer
            # REFUSES `f"}"` ("single '}' is not allowed"), and this is asked
            # after that has already run, so reaching here means the text was
            # built rather than parsed — and a reader that silently dropped it
            # would compose a string with a character missing from it.
            raise CodegenError(
                f"cannot read the interpolated literal {spelled!r}: a single "
                f"'}}' is not allowed in an f-string — CPython's own tokenizer "
                f"refuses it — so this is not source text a program could have "
                f"written, and guessing where it was meant to end would "
                f"compose a string with a character missing from it")
        if c == '{':
            if lit:
                out.append(('lit', ''.join(lit)))
                lit = []
            j, depth = i + 1, 1
            while j < n and depth:
                if body[j] == '{':
                    depth += 1
                elif body[j] == '}':
                    depth -= 1
                j += 1
            if depth:
                raise CodegenError(
                    f"cannot read the interpolated literal {spelled!r}: the "
                    f"'{{' opened at character {i} is never closed, so the "
                    f"field's text is not knowable")
            inner = body[i + 1:j - 1]
            # `!conv` binds tighter than `:spec`, and both may be absent, and a
            # `!` or `:` INSIDE a bracket (`d['a:b']`) must not be mistaken for
            # either — so the split is done at bracket depth zero.
            k, bdepth, spec_at, conv_at = 0, 0, None, None
            while k < len(inner):
                ch = inner[k]
                if ch in '([{':
                    bdepth += 1
                elif ch in ')]}':
                    bdepth -= 1
                elif bdepth == 0 and ch == '!' and conv_at is None:
                    conv_at = k
                elif bdepth == 0 and ch == ':' and spec_at is None:
                    spec_at = k
                k += 1
            # The EXPRESSION ends at whichever comes first, so `!conv` is cut
            # off as well as read off — `inner[:spec_at]` alone would leave the
            # expression spelled `y !s`, which is neither a value nor what the
            # source wrote, and a lowering that tried to evaluate it would be
            # answering a different question.
            first = len(inner)
            for at in (conv_at, spec_at):
                if at is not None and at < first:
                    first = at
            expr = inner[:first].strip()
            if conv_at is None:
                conv = ""
            elif spec_at is not None and conv_at < spec_at:
                conv = inner[conv_at + 1:spec_at].strip()
            else:
                conv = inner[conv_at + 1:].strip()
            spec = inner[spec_at + 1:].strip() if spec_at is not None else ""
            out.append(('field', expr, spec, conv))
            i = j
            continue
        lit.append(c)
        i += 1
    if lit:
        out.append(('lit', ''.join(lit)))
    return out


def interpolated_literal_refusal(node, where: str = "") -> str:
    """Why an f-string/t-string literal is refused on this path.

    `where` is the line the literal is on when the caller has it, so the
    message can point at the source rather than at the construct: two f-strings
    in one program are two refusals a reader has to tell apart.

    **It says what the literal is MADE OF, and it no longer gives advice that
    produces different text.** Both halves are measurements:

      * the parts, read by `interpolated_literal_segments` above — how many
        fields, what each one interpolates, and whether any carries a format
        spec or a conversion, since those are three questions and the old
        sentence merged them into one;
      * the `print` advice, which was wrong and is gone.
        `bugs/formal/FORMAL_string_composition_has_no_buffer.md` §6 named it as "**NOT
        the fix** … the message's own advice is wrong", and it is: CPython's
        `print` puts a `sep` between its operands, so following "Print the parts
        as separate operands" on `f"n={n}"` with `n = 7` gives

            CPython f"n={n}"      ->  n=7
            CPython print("n=", n) ->  n= 7

        — measured here on both this path and `python3`, which agree on
        `print` and differ on the f-string. A reader who followed the advice got
        a program that builds, runs, exits 0 and prints something else, which is
        the outcome this backend exists to prevent. A fix DELETED the sentence
        (the map's §5.1 records that the instrument rows are keyed on "no
        buffer to compose one in" and not on the advice, precisely so that
        deleting it could not take 115 files silently back to `other refusal`),
        so nothing is lost by its absence and the diagnostic ends on the fact.
    """
    spelled = node.value if isinstance(node, str) else getattr(node, "value", "")
    # The article is spelled out rather than derived from the first letter:
    # "f-string" is pronounced "eff-string" and so takes "an", while the rule a
    # `kind[0] in "aeiou"` test would apply gives it "a" — and a message whose
    # first three words are wrong is a message a reader stops reading.
    #
    # The `t` is looked for across the WHOLE prefix rather than at index 0: a
    # t-string's prefix may be `tr`/`rt`, so `spelled[:1] in ("t", "T")` called
    # a `rt"…"` "an f-string". The prefix letters are read with the same helper
    # `interpolated_literal_segments` now uses, so both spell the width once.
    _prefix_end = (interpolated_literal_quote_start(spelled)
                   if isinstance(spelled, str) else 0)
    is_t = False
    for _ch in spelled[:_prefix_end]:
        if _ch == 't' or _ch == 'T':
            is_t = True
    kind = "a t-string" if is_t else "an f-string"
    at = f" on line {where}" if where else ""
    try:
        segs = interpolated_literal_segments(spelled)
    except CodegenError as e:
        # The reader refused, and the right thing to report is ITS reason: a
        # generic "this path has no buffer" would be true and would hide the
        # fact that the shape is not one this reader can even take apart.
        return f"{kind} literal{at} is refused on this path, and its text could "\
               f"not be taken apart either: {e}"
    fields = [s for s in segs if s[0] == 'field']
    chunks = [s for s in segs if s[0] == 'lit']
    made = _interpolated_shape_sentence(segs)
    tail = (
        f"{kind} literal{at} is refused on this path: its value is its "
        f"INTERPOLATED text, and this path has no buffer to compose one in. "
        f"{made} The parser keeps the whole source token (`{spelled}`) as the "
        f"literal's value, so what this build would have printed is the "
        f"spelling: with `n = 7`, `print(f\"n={{n}}\")` printed "
        f"`f\"n={{n}}\"` and exited 0 where CPython prints `n=7`. A string here "
        f"is a bare `char *` interned into read+execute __TEXT, so "
        f"`\"n=\" + decimal(n)` has nowhere to be laid down at compile time "
        f"(the field may be a runtime value) or at run time (there is no "
        f"heap); this is the same missing buffer that keeps string "
        f"concatenation and the length-dependent methods refused (see "
        f"`string_concat_refusal` and LENGTH_DEPENDENT_METHODS). Pass the "
        f"interpolated value to `printf` as an ARGUMENT — "
        f"`printf(\"n=%d\", n)` — which is the same text and is what this "
        f"path lowers; `print(\"n=\", n)` is NOT the same program, because "
        f"`print` inserts a space between its operands, and building the text "
        f"with `+` is the same missing buffer refused under another name.")
    if is_t:
        # §7.3 of the doc, landed rather than left as a note for a future
        # lowering: a t-string's `{name}` is a TEMPLATE and `text.format`
        # evaluates it, so it is not a field to be interpolated and refusing it
        # as though it were one describes a construct this path does not have.
        tail += (
            f" A t-string is refused for a further reason that has nothing to "
            f"do with the buffer: its `{{name}}` is a TEMPLATE, which is "
            f"`str.format`/`text.format` evaluating an argument against a "
            f"format string, so the answer is not the field's value and no "
            f"lowering that composes an f-string's fields would be right here.")
    return tail


def _interpolated_shape_sentence(segs: list) -> str:
    """What an interpolated literal is MADE OF, in one sentence.

    The fields are named because they are the thing a reader has to look up in
    their own source, and the count of chunks and their byte lengths is the
    thing that decides the §7.1 bound — `formal/
    FORMAL_string_composition_has_no_buffer.md` §7.1 asks for "a buffer with a
    compile-time-known bound", and the bound IS the chunk bytes plus the widest
    each field's declared type can render. So the diagnostic now prints the half
    of that arithmetic a reader can check without running anything.
    """
    fields = [s for s in segs if s[0] == 'field']
    chunks = [s for s in segs if s[0] == 'lit']
    if not fields:
        return (f"This one has NO field at all — {len(chunks)} literal chunk(s) "
                f"of {sum(len(c[1]) for c in chunks)} byte(s) — so its value is "
                f"a CONSTANT and this refusal is over a missing buffer rather "
                f"than a run-time value.")
    shown = ", ".join(f"`{f[1]}`" for f in fields[:4])
    if len(fields) > 4:
        shown += f", and {len(fields) - 4} more"
    chunk_bytes = sum(len(c[1]) for c in chunks)
    out = (f"It is made of {len(fields)} field(s) — {shown} — and "
           f"{len(chunks)} literal chunk(s) totalling {chunk_bytes} byte(s).")
    specs = [f for f in fields if f[2]]
    convs = [f for f in fields if f[3]]
    if specs:
        out += (f" {len(specs)} of the field(s) carries a FORMAT SPEC "
                f"(`:`), which is a rendering rather than a value.")
    if convs:
        out += (f" {len(convs)} of the field(s) carries a CONVERSION (`!`), "
                f"which is a rendering rather than a value.")
    return out


def fold_constant_interpolated_literals(stmts) -> int:
    """Rewrite every f-string that interpolates NOTHING into the string it denotes.

    **An f-string with no replacement field is a CONSTANT**: its value is its
    text with `{{`/`}}` unescaped, and nothing has to be composed at run time.
    The build refuses interpolated literals wholesale because there is no buffer
    to compose one in (`interpolated_literal_refusal`), and this is the one case
    that refusal cannot be about — the message itself says so
    (`_interpolated_shape_sentence`'s "This one has NO field at all … so its
    value is a CONSTANT"). Refusing it is a divergence: CPython prints `abc` for
    `print(f"abc")` where this path refused the program.

    **`t`-strings are NOT folded.** A `t"…"`'s value is a `Template` object and
    not a `str`, so there is no constant for it to become; the refusal's second
    reason covers that construct. Only an f-string prefix is rewritten.

    The rewrite is IN PLACE and it is the WHOLE literal: `value` becomes the
    composed text and `is_interpolated` becomes `False`, which is exactly the
    shape an ordinary string literal of the same text has. Every downstream
    reader — both backends' expression walks, the proof generators, the
    non-ASCII scan — then sees a plain literal and no other rule has to learn
    about this one. `is_raw` carries the `r` of an `rf"…"`, because
    `interpolated_literal_segments` leaves escape text undecoded (as it does for
    an ordinary literal) and the shared decoder `fire_compiler.decoded_literal`
    needs the flag to know `rf"a\\nb"` is four characters wide.

    `interpolated_literal_segments` is the ONE reader of the token, so a chunk
    boundary the reader refuses is not folded either: `CodegenError` is left
    for `refuse_interpolated_literals` to report as the reader's own reason,
    because guessing a text there would compose a string with a character in the
    wrong place. Returns the number folded, so the caller can report it.
    """
    folded = 0
    for node in iter_nodes(stmts):
        if not is_interpolated_literal(node):
            continue
        spelled = getattr(node, "value", "")
        if not isinstance(spelled, str):
            continue
        _prefix_end = interpolated_literal_quote_start(spelled)
        _is_t = False
        _is_raw = False
        for _ch in spelled[:_prefix_end]:
            if _ch == 't' or _ch == 'T':
                _is_t = True
            if _ch == 'r' or _ch == 'R':
                _is_raw = True
        if _is_t:
            continue
        try:
            segs = interpolated_literal_segments(spelled)
        except CodegenError:
            continue
        if any(s[0] == 'field' for s in segs):
            continue
        node.value = ''.join(s[1] for s in segs if s[0] == 'lit')
        node.is_interpolated = False
        node.is_raw = _is_raw
        folded += 1
    return folded


def integer_text_width(bits: int) -> int:
    """The widest decimal text a signed `bits`-wide integer renders as.

    **Including the sign, because that is what the value can be.** A 64-bit
    integer reaches `-9223372036854775808`, which is 20 characters; the largest
    positive one is 19. The derivation is `len(str(-(2 ** (bits - 1))))` rather
    than a table of digits because a table would be 4 remembered rows where one
    expression is right for every width, and because a reader checking this
    against `decimal` should find a formula.

    This is the number §7.1 of
    `bugs/formal/FORMAL_string_composition_has_no_buffer.md` needs and the corpus has
    never been asked for: a buffer with a COMPILE-TIME-KNOWN bound needs each
    field's WIDTH to be known at compile time, and an integer's width is a
    property of its declared type rather than of its value — which is the only
    reason the doc's step 1 can promise a bound at all.
    """
    if not isinstance(bits, int) or bits < 2:
        return 0
    return len(str(-(1 << (bits - 1))))


# The four widths this path actually declares. Keyed on the bit width rather
# than on a type name, because a name is a spelling the two backends share as
# vocabularies (`formal/types.py`) and a width is arithmetic — and because a
# `Int` alias or a `SIMD[UInt8, 4]` element is the same question asked of a
# different spelling.
INTEGER_TEXT_WIDTHS = {8: 4, 16: 6, 32: 11, 64: 20}

#: Export-rule answers `_export_rule_for` in `build.py` returns when the
#: defining module declares a name but no exclusion applies (DECLARED), or
#: never names it at all (ABSENT). Both are `reflect.EXCL_*`-shaped strings.
EXPORT_RULE_DECLARED = "declared"
EXPORT_RULE_ABSENT = "absent"

# What an f-string's FIELD has to be for a buffer's bound to be known before
# the program runs. Read out of the corpus by
# `test_formal_run.py::check_interpolated_literal_bound_census`, which is where
# the shape distribution behind this table is measured rather than assumed.
FIELD_SHAPES = ("int-literal", "str-literal", "name", "attribute", "call",
                "subscript", "other")


def interpolated_field_shape(expr: str) -> str:
    """Which of `FIELD_SHAPES` an f-string field's TEXT is written as.

    The field is text, not an AST node: `interpolated_literal_segments` reads it
    out of the source token because that is all the parser kept (see its
    docstring), so this is a reader over a spelling and it says so — it answers
    "what would have to be known about this text", never "what is this value".

    The four shapes that can be resolved WITHOUT the enclosing scope — an
    integer literal and a string literal, which carry their own width — and the
    four that cannot: a bare name and an attribute need a DECLARED type to be
    resolved at all, and a call, a subscript and anything else need the whole
    expression tree this path never built. **Which of the two kinds a field is
    is the number that decides whether a bound exists**, which is what the
    census measures and what `interpolated_literal_bound` turns into a verdict.
    """
    text = (expr or "").strip()
    if not text:
        return "other"
    try:
        int(text, 0)
        return "int-literal"
    except ValueError:
        pass
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return "str-literal"
    if text.endswith(")") and "(" in text:
        return "call"
    if "[" in text and "]" in text:
        return "subscript"
    if "." in text:
        return "attribute"
    if text.isidentifier():
        return "name"
    return "other"


def interpolated_literal_bound(spelled: str, field_width=None):
    """`(bound, why)` — the compile-time-known bound of a composed literal, or
    `(None, why)` naming the ONE obligation that stops there being one.

    **`bound` counts the NUL terminator**, because the composed value has to be
    one: a string on this path is a bare `char *` whose length is a `strlen`
    over its bytes (`formal/model.py`'s text-encoding block and
    `LENGTH_DEPENDENT_METHODS`), so a composition that is not terminated is a
    `len()` that walks past the end of it. That is the obligation
    `bugs/formal/FORMAL_string_value_model.md`'s "§The cost" states as "whoever adds
    the first method which can build a string at run time inherits the
    obligation" — and inheriting it is cheaper than a second word in every
    string value on this path.

    **`field_width(expr)` is the caller's resolver and is what makes this a
    function of the SOURCE rather than of a guess.** It returns the widest
    decimal rendering of that field — an integer for one it can bound, `None`
    for one it cannot — and the default resolver below bounds exactly two
    shapes, the two that carry their width with them:

        >>> interpolated_literal_bound('f"--backend={7}"')
        (12, None)
        >>> interpolated_literal_bound('f"--backend={name}"')[0] is None
        True
        >>> interpolated_literal_bound('f"--backend={name}"',
        ...                             lambda e: integer_text_width(64))
        (31, None)

    **The finding this exists to record is that the bound exists for exactly
    one class of field.** A field whose value is an INTEGER has a width that is
    a property of its declared type (`integer_text_width`), so the buffer's size
    is arithmetic. A field whose value is a STRING does not: its width is a
    `strlen` over bytes whose length is a property of the RUN, so no buffer in a
    frame — whose size is reserved at compile time, which is what
    `formal/arm64_codegen.py`'s blob cursor and `formal/model.py`'s
    `frame_blob_refusal` are — can be sized for it. §7.1 of the doc says the
    bound "is computable at compile time (chunk lengths are known; a field's
    width is its declared type's)", which is true of the integer field and false
    of the string one, and the false half is the half that decides how much of
    the feature is buildable. `test_formal_run.py::
    check_interpolated_literal_bound_census` is the measurement.

    **`why` is a single sentence naming the FIRST unmet obligation, in the order
    the obligations are independent of each other**: a t-string is refused for a
    reason no buffer fixes (§7.3), a `:` spec and a `!` conversion are
    RENDERINGS rather than values (§7.3 again, and the doc counts them
    separately for exactly this reason), and only then does the width come up.
    Reporting them in that order is what makes the sentence a next step rather
    than a restatement.
    """
    try:
        segs = interpolated_literal_segments(spelled)
    except CodegenError as e:
        return (None, f"its text could not be taken apart either: {e}")
    if (spelled or "")[:1] in ("t", "T"):
        return (None, "a t-string's `{name}` is a TEMPLATE, which is "
                      "`str.format` evaluating an argument against a format "
                      "string, so no bound over field VALUES is the right "
                      "question for it")
    if field_width is None:
        def field_width(expr):                                # noqa: E306
            shape = interpolated_field_shape(expr)
            if shape == "int-literal":
                return len(str(int(expr.strip(), 0)))
            return None
    total = 0
    for seg in segs:
        if seg[0] == "lit":
            total += len(seg[1].encode("utf-8"))
            continue
        _kind, expr, spec, conv = seg
        if spec:
            return (None, f"the field `{expr}` carries a FORMAT SPEC (`:"
                          f"{spec}`), which is a RENDERING rather than a value: "
                          f"its width depends on the spec and on the field's "
                          f"value, so it is not a compile-time constant")
        if conv:
            return (None, f"the field `{expr}` carries a CONVERSION "
                          f"(`!{conv}`), which is a RENDERING rather than a "
                          f"value")
        width = field_width(expr)
        if width is None:
            shape = interpolated_field_shape(expr)
            return (None, f"the field `{expr}` is a {shape} whose width is "
                          f"not known before the program runs — a name or an "
                          f"attribute is bounded only by its DECLARED type, "
                          f"and an integer's width is arithmetic "
                          f"(`integer_text_width`) while a STRING field's width "
                          f"is a `strlen` over the value, which no frame buffer "
                          f"reserved at compile time can be sized for")
        total += int(width)
    return (total + 1, None)      # the +1 is the NUL, and it is load-bearing




def refuse_interpolated_literals(stmts) -> None:
    """Fold a field-less f-string, and raise `CodegenError` on the first one WITH a field.

    Asked over the MODULE's statement list, once, by the one pipeline both
    front ends go through (`formal/build.py:_prepare_functions`) — the same
    place and for the same reason as `refuse_module_level_mlir_templates`: a
    refusal asked from either backend's expression walk would be two copies of
    one decision, and the executable and dylib paths would then be able to
    answer differently about one source file.

    `iter_nodes` is the shared walker, so a literal nested two levels down —
    `print("x", f"v={v}")`, a `f` field inside a format spec, a comprehension's
    element — is reached by the same walk the frame layout uses, and a node one
    of them would miss is not missed here.

    A module-level statement the walker does not descend into is not a hole:
    `iter_nodes` recurses through dataclass fields, and a `FunctionDef`'s body
    is one of them.
    """
    for node in iter_nodes(stmts):
        if is_interpolated_literal(node) and not fold_interpolated_literal(node):
            raise CodegenError(interpolated_literal_refusal(
                node, getattr(node, "line", "")))
