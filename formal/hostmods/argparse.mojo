"""`argparse` — command-line parsing, for the formal backend.

CPython's `argparse` is "a shape over the source language rather than a runtime
facility" (`formal/imports.py`'s HOST_MODELLED comment, which names `argparse`
among the reachable-in-principle modules). Nothing in it needs a second
process, a thread or a library outside libSystem: parsing a command line is
scanning strings, and every operation it performs is one this backend can
already lower. That is what makes this file possible, and it is why `argparse`
in HOST_MODELLED was a lie and no longer is.

It lives in `formal/hostmods/` beside this backend's `os`, `sys` and `struct`,
which `formal/imports.py` adds to every file's search roots as its last entry.
It did NOT live at the repository root, where the first three of these modules
were written: the root is a search root for four independent resolvers, so a
Mojo `sys` there captured `import sys` in the compiler's own sources. See
`formal/imports.py`'s `_HOSTMODS_ROOT`.

WHY THE API IS NOT `ArgumentParser()`
--------------------------------------
Three properties of this target decide it, and every one of them is measured
rather than assumed — the reproductions are in the bug doc named at each.

  1. A parser is an OBJECT THAT ACCUMULATES STATE. `ArgumentParser()` returns
     something `add_argument` is then called on and `parse_args` reads back.
     A module dylib can return one 64-bit word and nothing else: a struct or a
     list is a blob carved out of the frame that made it, so handing one back
     hands over an address that is dead on return
     (`bugs/FORMAL_module_state_no_storage.md`, measurements (2) and (3)).
  2. A module has no state of its own. A module-level name that is not a
     literal-only constant has nowhere to live, so a parser cannot be a module
     global either (same document, measurement (1)). Every function here is a
     pure function of its arguments.
  3. The command line is GONE before the first statement runs. The entry stub
     (`ARM64Codegen.compile`, and `X86_64Codegen`'s twin) loads the test input
     into X0 and branches to the entry function, so `argc`/`argv` from the
     kernel's start are overwritten before `main` is called — the same
     document, measurement (4). `parse_args()` reading `sys.argv` has no
     source on this target at all, not merely no storage.

So the shape here is the one the value model allows and the one that is
actually TESTABLE: **the caller owns the state.** A parser is described by a
string the caller writes; the command line is a list the caller already has
(`argv`); the result is written into a buffer the caller supplies; every value
that comes back is one word or a `char *`. This is the same substitution the
backend already makes for `bytes` (a list of ints — see `struct.mojo`) and for
a `Namespace`, which is a mapping from dest to value, here a text encoding of
that mapping.

THE SPEC: WHAT `add_argument` CALLS BECOME
------------------------------------------
One record per action. Records are separated by `;`, fields by `|`, and there
are ten fields, always in this order; a record may stop early and the rest are
empty:

    0 names      option strings separated by spaces, or a positional's name
    1 action     store | store_true | store_false | append | count
    2 type       str | int
    3 nargs      empty (one) | ? | * | + | R | an integer
    4 choices    comma separated, or empty
    5 required   0 | 1
    6 default    the default as text; empty means the action's own default
    7 dest       empty to derive it (`--no-cache` -> `no_cache`)
    8 metavar    empty to derive it (`{choices}`, else dest.upper())
    9 help       the help text

`R` is `nargs=REMAINDER`. A `;` or `|` in help text or in a choice IS
expressible: a field ESCAPES them (`\;`, `\|`), and a backslash in the text is
itself written `\\`. Only the ESCAPED bytes are separators, so every reader that
walks a record or a field skips a backslash and the byte after it. `_esc_end`
below is the ONE scan that does this and every one of those readers goes
through it — `_fend` and `_rend` for the two separator sets, and the two
`choices` readers with `,` added. `_ftext` is the only place the backslashes are
removed, because it is one of only two readers that produce TEXT out of a field
(the other is `_quote_choices`, and both go through `_unesc_upto`); the rest
measure or compare raw bytes, which is right for them because no field but
`help` can contain a separator (an option string, a type name, a nargs letter, a
comma-joined choice list, a flag, a default, a dest and a metavar have none) and
because a spec written before this rule existed contains no backslash at all and
so reads identically.

This is a rule on the WRITER, not a hidden convention: `add(spec, record)`
appends a record the caller has already written, and it cannot tell a `|` that
separates two fields from one that is help text, so the caller escapes. A VALUE
containing `;` is still refused rather than written, because a value that
quietly split a field would be a wrong answer with nothing left to detect it —
and a value is written by this module into the NAMESPACE buffer, not by a caller
into a spec, so the escape rule does not reach it.

`add(spec, record)` appends one record and returns a new spec, which
is the alternative to one long literal — string `+` is refused on this path
(`bugs/FORMAL_string_value_model.md`), so a spec cannot be concatenated in the
source.

`add_argument` on the CPython side also takes `prog`, `description` and
`formatter_class`. `prog` is `basename(argv[0])` here, which is what CPython
derives it from. `description` is a parameter of `parse` and `help_text`,
because no error path prints it — CPython's does not either; the usage line and
the message only. `formatter_class` has no observable effect here and is not
implemented, because the only thing it changes is whether text is WRAPPED, and
nothing here wraps.

THE RESULT: WHAT `Namespace` BECOMES
------------------------------------
`parse` writes the namespace into the caller's buffer as `;`-separated fields,
in DECLARATION order (which is the order CPython's namespace has them in: the
defaults are set for every action before the command line is looked at, and a
later assignment to an existing key keeps its position). Three shapes, and they
are distinguishable:

    name=value        one value
    name;name=value   two values — a list-valued action, one field per value
    name              seen, with no value: an empty list
    (absent)          not seen: the value is None

`get`/`get_at` read a value as text, `get_int`/`get_int_at` as an integer,
`count` says how many values an action has and `has` whether it was seen at
all. Every stored value is TEXT, including `store_true` (0 or 1) and `count` (a
decimal number), because the buffer holds `char *` and a bare word in it would
be unclassifiable — see `get`'s own note.

`-h`/`--help` IS THE ONE ACTION THIS MODULE ADDS ITSELF, exactly as CPython's
`add_help=True` does, and it is why a usage line here starts `[-h]`. Those two
option strings are reserved and a spec that declares them is refused at parse
time.

WHAT IS NOT HERE, AND WHY
-------------------------
  * **BOTH BACKENDS TODAY, and not because of anything in this source.** This
    module calls the C library (`malloc`, `strlen`, `memcmp`, `snprintf`), and
    a module dylib that makes a call into it builds and RUNS under
    `--backend=x86_64` as well as `--backend=arm64`, measured on this tree.
    It used to say otherwise here and in five sibling modules, citing a bug doc
    that does not exist; `formal/hostmods/os/__init__.mojo` gives the corrected
    claim and the evidence at length. A host with no x86-64 support at all still
    skips the x86-64 half of `test_formal_argparse.py`, with the reason
    printed.
  * **`type=float` is REFUSED, and that is not an oversight.** A value on this
    path is one 64-bit word holding an INTEGER: `2.5` as a literal is the
    integer 2, `1.0` is 1, and `atof("3.5")` is 1 — measured, and the reason is
    in `formal/model.py`'s `_FLOAT_SCALARS`. An `argparse` that accepted
    `--limit-gb 2.5` and answered 2 would be a module computing something other
    than what its name says, so `parse` returns `ST_UNSUPPORTED` and says why.
    One file in the corpus (`tools/memcap.py`) wants it.
  * **`sys.argv` is not a source here at all** (measurement (4) above), so
    there is no `parse_args()` with no argument. The caller passes `argv`, and
    `argv[0]` is the program name exactly as CPython's `prog` is derived from
    it.
  * **Subparsers, mutually exclusive groups, `fromfile_prefix_chars`,
    `store_const`, `version` and `BooleanOptionalAction` are not implemented.**
    Measured: no file the sweep lists for `argparse` uses any of them. They are
    absent rather than approximated — a subparser is a second parser reachable
    from the first, which is precisely the state this target has none of.
  * **THE WIDTH IS 78 AND CANNOT BE ASKED FOR, BUT EVERYTHING IS WRAPPED AT
    IT.** `help_text` reproduces CPython's layout — usage, blank, description,
    blank, `positional arguments:`, the positionals two-column, blank,
    `options:`, the options two-column — AND folds all three of the things that
    can overflow it: a help string at `max(width - help_position, 11)`, the
    description at the full width, and a usage line past the width onto indented
    continuation lines. The width is 78 because that is what
    `shutil.get_terminal_size().columns - 2` gives when `COLUMNS` is unset and
    stdout is not a terminal, and it is the only width this target can know: a
    terminal is a host object (`shutil` and `os.get_terminal_size` are in
    HOST_UNREACHABLE). So a program run in a WIDE terminal gets CPython's
    80-column layout, not its own — a difference of 2 columns and no more, and
    the one thing here that is a property of the target rather than of this
    module. The wrapping itself is `textwrap`'s (see `_wrap_into`, with
    `_get_lines` for the usage line, which is a different algorithm), and
    `test_formal_argparse.py` compares all of it byte for byte against CPython
    over 14 parsers.

ERRORS
------
CPython raises `SystemExit(2)` from `ArgumentParser.error`, printing the usage
line and then `prog: error: message`. There is no `raise` on this path and no
`sys.exit` (a settled decision, `bugs/FORMAL_known_limits.md` 1.1), so `parse`
RETURNS 2 with the same text in its `err` buffer, and the caller ends the
process with the one spelling that works on this target:

    rc = argparse.parse(spec, argv, argc, out, err, desc)
    if rc == 1:
      write(1, err, strlen(err))        # --help: print it, exit 0
      exit(0)
    if rc != 0:
      write(2, err, strlen(err))        # the usage line and the message
      exit(2)

Every message and every exit status below is checked against CPython's own
`argparse` on the same command lines by `test_formal_argparse.py`, which builds
the arm64 image, RUNS it, and diffs its output and status against a CPython
program generated from the same declarations.
"""

from os._syscalls import str_alloc, str_len, str_put, str_copy, str_prefix
from os._syscalls import str_dup, str_eq_n

# ── the spec's field positions ────────────────────────────────────────────────
#
# A record is ten `|`-separated fields. They are POSITIONAL rather than named
# because a name at this position would be a module-level constant, which is
# exactly the construct `struct.mojo` declines to use for `struct.Struct`; the
# cost of spelling the numbers is paid once, in this block.

F_NAMES = 0
F_ACTION = 1
F_TYPE = 2
F_NARGS = 3
F_CHOICES = 4
F_REQUIRED = 5
F_DEFAULT = 6
F_DEST = 7
F_METAVAR = 8
F_HELP = 9

# ── the action classes ───────────────────────────────────────────────────────
#
# `store` is 0 so an EMPTY action field means the default, which is what CPython
# does with an action string it never sees.

A_STORE = 0
A_TRUE = 1
A_FALSE = 2
A_APPEND = 3
A_COUNT = 4

# ── nargs ────────────────────────────────────────────────────────────────────

N_ONE = 0
N_OPT = 1
N_STAR = 2
N_PLUS = 3
N_REM = 4
N_INT = 5

# ── types ────────────────────────────────────────────────────────────────────

T_STR = 0
T_INT = 1
T_FLOAT = 2
T_BAD = 3

# ── what `parse` returns ─────────────────────────────────────────────────────
#
# 0 parsed; 1 a help action fired and `err` holds its text (exit 0); 2 an error
# and `err` holds the usage line and the message (exit 2); 3 the spec asks for
# something this module does not implement; 4 a value or the result does not
# fit in the caller's buffer. 2 is CPython's own error status and the other
# three are this target's, documented at each definition.

ST_OK = 0
ST_HELP = 1
ST_ERROR = 2
ST_UNSUPPORTED = 3
ST_TOOBIG = 4

# ── the error classes `parse` reports, and how they travel ────────────────────
#
# The option-consuming step is a separate function (this target has no closures
# and no module state, so the whole of CPython's `consume_optional` cannot
# share `parse`'s locals) and it cannot be handed a message buffer as well as
# everything else within the six argument registers the SMALLER of the two ABIs
# passes — see `struct.mojo`'s limit 2. So it returns a PACKED negative number,
# `-(1 + class * 4096 + action)`, and `parse` rebuilds the message. Every class
# below is one CPython `ArgumentError` message.

E_EXPECT1 = 1        # expected one argument
E_ATMOST = 2         # expected at most one argument
E_ATLEAST = 3        # expected at least one argument
E_EXPECTN = 4        # expected <n> argument(s)
E_BADVAL = 5         # invalid int value / invalid choice
E_AMBIG = 6          # ambiguous option: <a> could match <b, c>
E_IGNORED = 7        # ignored explicit argument '<v>'
E_UNRECOG = 8        # an 'O' that names no action: it becomes an extra
E_EXTRAS = 9         # the tail of a combined short argument: also an extra
E_TOOBIG = 10        # a value or the namespace did not fit
E_HELP = 100         # -h/--help

# The action index rides in the low 12 bits of a packed error, so it is 4096
# wide; `E_EXTRAS` puts an OFFSET there instead, which is the position of the
# unrecognised tail inside `argv[start]`.

# ── the pattern characters ───────────────────────────────────────────────────
#
# CPython's `_parse_known_args` classifies every argument string as 'A' (an
# argument), 'O' (an optional) or '-' (the `--` separator) and then matches
# positionals against that pattern. Reproducing its RESULTS means reproducing
# the pattern, not inventing another scheme.

PAT_A = 65
PAT_O = 79
PAT_DASH = 45

# ── the width a terminal would have told us ──────────────────────────────────
#
# `shutil.get_terminal_size().columns - 2`, which is 78 when `COLUMNS` is unset
# and stdout is not a terminal — the case a piped program is in, and the case
# every measurement in the test corpus is taken in. See WHAT IS NOT HERE for why
# there is no other answer.

TEXT_WIDTH = 78
MAX_HELP_POSITION = 24

# ── the size of every buffer the caller supplies ─────────────────────────────
#
# `out` and `err` are written by index on this path, and a subscripted STORE is
# bounds-checked against the blob's count field, which a `malloc`'d buffer does
# not have. So every write is a `memmove`/`memset` at an offset and every buffer
# needs a bound both ends of the call can agree on: a module constant is the
# only one, since a default argument is not applied to a call from another
# image (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`).

BUF_CAP = 8192

# ── separators, as BYTES and not as spellings ────────────────────────────────
#
# A newline cannot reach a caller through a printf-style format, so every
# separator below is a byte value written with `memset`/`memmove` rather than a
# character in a literal. That reason is CURRENT. The reason this file used to
# give — "a string literal on this path is interned verbatim and its escapes are
# NOT unescaped, measured: `"a\nb"` is four bytes, and `sys.mojo` says so at its
# writers" — is NOT, and had stopped being true at `9023031b` (the decoder every
# engine now shares), which `sys.mojo`'s writers and
# `test_formal_sys.py::test_a_literal_inside_a_module_is_decoded_too` both pin:
# a literal IS decoded, inside a module as well as inside a program, on both
# architectures. The idiom below is kept because it is correct and because these
# separators are written at a computed offset anyway;
# `bugs/FORMAL_sys_mojos_escape_note_is_stale.md` §"what remains" is what
# simplifying the rest of the tree's corpora would take.

# A BYTE WRITTEN WITH `memset` IS SPELLED INLINE unless the module already has
# a NAME for the value it is — which the `PAT_` bytes in `_build_pat` are, and
# which the separators below are not: NUL, newline and space are written dozens
# of times each here and each carries the character in a comment at its use.
#
# **The reason this comment used to give was false, and the measurement that
# replaces it is stronger than the one it quoted.** It said a named byte is
# REFUSED with "'PAT_DASH' has no home: the register allocator collected no home
# for it" — true when it was measured, and false since
# `formal/build.py`'s `_substitute_module_constants` began substituting a module
# constant at every read BEFORE any emitter runs. A folded name never reaches an
# emitter, so it needs no register, no spill slot and no `__DATA` slot, and
# there is nothing for the allocator to run out of.
#
# Measured on this tree, 2026-10-02, with `_build_pat`'s two bytes spelled
# `PAT_A` and `PAT_DASH` and this module built as a DYLIB on both architectures
# (`formal.imports.build_module_dylib` — the shape an importing program reaches
# it by, which is not the shape a file built as a program of its own reaches it
# by): both build, and `__TEXT` — code, constants and data — is BYTE-IDENTICAL
# to the inline spelling on arm64 and on x86-64. The only bytes that differ in
# either image are the install-name strings, which carry the content digest in
# the filename. So the name costs nothing measurable, and what is left of the old
# rule is the sentence above.
SEP_FIELD = 59        # ';'
SEP_KV = 61           # '='

LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"

# The help action CPython adds and this module adds with it. They are literals
# here rather than a synthesised record, because a record for them would have to
# be spliced into the spec — and a spec is the caller's, and the caller's spec
# is what `n_actions` counts and what a program reads. Kept as two constants so
# that the usage line and the help listing cannot disagree about them.
HELP_INVOCATION = "-h, --help"
HELP_TEXT = "show this help message and exit"

# An EXPLICIT `default=None`, which is not the same as leaving the field empty:
# `store_true` with `default=None` has the value None in CPython and False when
# the default is left out, and an empty field cannot say which was meant. One
# reserved word carries the difference, and it is reserved because a default of
# the two bytes `~` is not a thing anyone writes.
NONE_TEXT = "~"


# ── Reading the spec ─────────────────────────────────────────────────────────
#
# A record is a run of bytes ending at `;` or NUL; a field is a run ending at
# `|` or the end of its record. Everything below walks those two levels without
# copying, because the hot path — matching one option string against every
# declared one — asks the same questions thousands of times.

def _esc_end(p, stops) -> int:
    """Offset from `p` to the first byte of `stops` that is not ESCAPED.

    A backslash escapes the byte after it, so a `;` or a `|` inside a field can
    be written `\;` / `\|` and is not a separator. That is the whole rule, and
    what it costs is this function: `strcspn` alone cannot express it, so the
    scan is a loop that jumps to the next byte worth looking at and then steps
    over an escape.

    `stops` is the separator SET as a NUL-terminated string, because `strcspn`
    takes one; the backslash is part of the scan rather than of `stops` so that
    every caller gets the escape rule and cannot forget it.

    THE COST ON THE COMMON PATH, measured rather than assumed, because this is
    the number the doc this fixes asks for: `_fld` is asked for every field of
    every record on every parse, and it used to be one `strcspn` plus one
    `strspn` per field. It is STILL one `strcspn` plus two `strspn`, and every
    one of the three is O(1) — `strcspn` stops at the first byte in `stops` or
    at the NUL, and `strspn` stops at the first byte out of it. The scan cannot
    ask "is the byte at `j` the NUL" with `str_len`, which is the obvious way to
    write it and which is O(the rest of the spec): a field is three bytes long
    and the spec is five hundred, so that strlen would have made `_fld`
    quadratic in the number of fields for no gain. `strspn(p + j, stops) == 0`
    says the same thing in one byte read, because `strcspn` above cannot have
    stopped anywhere else.

    A lone backslash at the very end of a field escapes nothing: the field ends
    AT it, and the byte after it is not read. Reading it would be the one way
    this loop could walk off the end of the buffer, and a spec is caller memory.
    That test IS a `str_len`, and it runs only on the escape path — which is the
    other half of why the two are not symmetric.
    """
    i = 0
    while True:
        j = i + strcspn(p + i, stops)      # at a stop byte, or at the NUL
        if strspn(p + j, stops) == 0:
            return j                        # the NUL ends the run
        if strspn(p + j, "\\") == 0:
            return j                        # a real separator
        if str_len(p + j + 1) == 0:
            return j                        # a dangling escape: nothing follows
        i = j + 2                           # step over `\` and the byte it escapes


def _fend(p) -> int:
    """Offset from `p` to the end of the field, honouring escapes."""
    return _esc_end(p, "\\|;")


def _rend(p) -> int:
    """Offset from `p` to the end of the RECORD, honouring escapes.

    A record's separators are only `;`, so the field scan's `|` must not stop it
    — hence a second name over the same function rather than a second scan.
    """
    return _esc_end(p, "\\;")


def _esc_at(p) -> int:
    """1 if the byte at `p` is a backslash."""
    return strspn(p, "\\")


def _unesc_upto(dst, u, p, n) -> int:
    """`n` bytes of `p` at `dst[u:]`, ESCAPES REMOVED, NUL-terminated. New `u`.

    **The one copy-with-unescape in this module**, and it is one because there
    are exactly two readers that turn a field's RAW bytes into TEXT — `_ftext`
    for a help string, `_quote_choices` for a choice inside an error message —
    and a `str_put` of the raw range at either of them would print the very
    backslash the writer put there to keep the byte out of the separator set.

    Copied a RUN at a time rather than a byte, because a help string is sixty
    characters and `_cp` is a `memmove` plus a `memset`; the loop only runs per
    ESCAPE, so the common field is one `_cp`.
    """
    i = 0
    start = 0
    while i < n:
        if _esc_at(p + i) == 1:
            u = _cp(dst, u, p + start, i - start)
            i = i + 1
            start = i
        i = i + 1
    return _cp(dst, u, p + start, n - start)


def _rec(spec, i):
    """Pointer to record `i` of `spec`, or 0 if there is no such record."""
    p = spec
    k = 0
    while k < i:
        d = _rend(p)
        if strspn(p + d, ";") == 0:
            return 0
        p = p + d + 1
        k = k + 1
    return p


def _nrec(spec) -> int:
    """How many records `spec` holds. An empty spec is one (empty) record."""
    n = 1
    p = spec
    while True:
        d = _rend(p)
        if strspn(p + d, ";") == 0:
            return n                    # NUL: no more records
        n = n + 1
        p = p + d + 1


def _fld(rec, f):
    """Pointer to field `f` of `rec`, or 0 if the record ended first.

    The delimiter has to be FOUND before it can be recognised: `strspn` asks
    whether a byte at a pointer is one of a set, and the first byte of a field
    is almost never a `|`. So each step measures the run up to the next
    delimiter with `_fend` and then asks whether the byte there is the field
    separator — which is what makes an ESCAPED `|` inside an earlier field not
    end that field.
    """
    p = rec
    k = 0
    while k < f:
        d = _fend(p)
        if strspn(p + d, "|") == 0:
            return 0                    # ';' or NUL: no such field
        k = k + 1
        p = p + d + 1
    return p


def _flen(rec, f) -> int:
    """Length of field `f`, or 0 when there is no such field.

    The RAW length, backslashes included: `_feq` compares the bytes the spec
    holds, and the only reader that turns a field into text is `_ftext`. A
    length that counted escape bytes as two would be right for neither.
    """
    p = _fld(rec, f)
    if p == 0:
        return 0
    return _fend(p)


def _feq(rec, f, s):
    """1 if field `f` is exactly the literal `s`."""
    p = _fld(rec, f)
    if p == 0:
        return 0
    n = _fend(p)
    if n != str_len(s):
        return 0
    return str_eq_n(p, s, n)


def _ftext(rec, f):
    """Field `f` as a NUL-terminated buffer the caller owns; "" if absent.

    **THE ONE PLACE BACKSLASHES ARE REMOVED**, and that is not an accident of
    where this function sits: a field's escapes are load-bearing all the way
    through the readers above — `_fend` has to skip them to find the field's end
    at all, and a `strcspn` that ignored them would truncate the help text at
    exactly the separator the writer escaped. So the escapes survive to here and
    are dropped in the copy, which is the only step that produces TEXT.

    The fast path is the old one-instruction `str_prefix`, taken whenever the
    field holds no backslash — which is every field of every spec written before
    the rule existed, and every field but `help` of every spec since.
    """
    p = _fld(rec, f)
    if p == 0:
        return ""
    n = _fend(p)
    if strcspn(p, "\\") >= n:
        return str_prefix(p, n)
    d = str_alloc(n + 1)
    _unesc_upto(d, 0, p, n)
    return d


def _haschar(s, chars):
    """1 if ANY byte of `s` is one of `chars`.

    `strspn` alone answers "does it START with one", which is a different
    question and the reason `os/_syscalls.mojo`'s `str_at` tests `> 0` rather
    than `== 1`. This is the "somewhere in there" form of the same test, and a
    hand-written byte comparison is not an option: a subscript on a `char *`
    reads a blob count rather than a byte
    (`bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md` — `byteat("ab")`
    returned -1879048144).
    """
    i = 0
    n = str_len(s)
    while i < n:
        if strspn(s + i, chars) > 0:
            return 1
        i = i + 1
    return 0


def _isdigit(p):
    """1 if the byte at `p` is a decimal digit."""
    return strspn(p, DIGITS)


def _isdigits(p, lim):
    """1 if the first `lim` bytes at `p` are one or more digits and nothing
    else.

    The bound is a PARAMETER and not `strspn(p, DIGITS)`, because `p` points
    into the middle of a record: the bytes after an `nargs` field are `|` and
    the rest of the record, so a whole-string test answers "not all digits" for
    every field that has a successor — which is all of them but the last.
    """
    if p == 0:
        return 0
    n = 0
    while n < lim and strspn(p + n, DIGITS) > 0:
        n = n + 1
    if n == 0 or n != lim:
        return 0
    return 1


def _alpha_index(p, set):
    """Which character of the 26-letter `set` the byte at `p` is, or -1.

    How this module identifies a LETTER without ever loading a byte: 26
    one-byte `strncmp`s. It is not a clever way to do it, and it is here
    because the obvious way does not exist — see `_haschar` for what a byte
    subscript reads on this target.
    """
    k = 0
    while k < str_len(set):
        if strncmp(p, set + k, 1) == 0:
            return k
        k = k + 1
    return 0 - 1


def _upper(s):
    """`s` with ASCII letters upper-cased — CPython's `dest.upper()`.

    ASCII only, said here rather than left to be discovered: a byte >= 0x80 is
    passed through unchanged, because a `str` on this path is a bare `char *`
    and nothing in it says what encoding a byte is in.
    """
    n = str_len(s)
    d = str_alloc(n + 1)
    u = 0
    i = 0
    while i < n:
        k = _alpha_index(s + i, LOWER)
        if k >= 0:
            u = str_put(d, u, UPPER + k, 1)
        else:
            u = str_put(d, u, s + i, 1)
        i = i + 1
    memset(d + u, 0, 1)
    return d


# ── One action's fields ──────────────────────────────────────────────────────

def _isopt(rec):
    """1 if `rec` declares an optional (its first name starts with `-`).

    `strspn` answers how MANY leading `-` there are — two for `--jobs` and one
    for `-v` — so the answer is compared against zero and not returned as it
    stands. Returning it raw made every double-dash option look like a
    positional, and it looked like one in the usage line, in the argument
    matching and in the error messages, all at once.
    """
    if _name_len(rec, 0) == 0:
        return 0
    if strspn(_name_ptr(rec, 0), "-") > 0:
        return 1
    return 0


def _nname(rec):
    """How many names (option strings, or the one positional name) `rec` has."""
    p = _fld(rec, F_NAMES)
    if p == 0:
        return 0
    end = _fend(p)
    if end == 0:
        return 0
    n = 0
    i = 0
    while i < end:
        if strspn(p + i, " ") > 0:
            n = n + 1
        i = i + 1
    return n + 1


def _name_ptr(rec, k):
    """Pointer to the k-th name of `rec`, or 0 if there is no k-th."""
    p = _fld(rec, F_NAMES)
    if p == 0:
        return 0
    end = _fend(p)
    i = 0
    c = 0
    while i < end:
        if k == c:
            return p + i
        if strspn(p + i, " ") > 0:
            c = c + 1
        i = i + 1
    if k == c:
        return p + end
    return 0


def _name_len(rec, k) -> int:
    """Length of the k-th name of `rec`.

    Stops at a space (names are space separated) or at the end of the field.
    Both are found with `strspn`, so no byte is ever loaded by subscript.

    `-> int` is LOAD-BEARING, for the reason `os/__init__.mojo` gives for every
    function in that module: `strcspn`/`strspn` are unbound libc externs whose
    return is a word of unknown provenance, so without the annotation the
    `return n` below classifies this callee's result as neither a number nor a
    string, and `_name_len(rec, k) == nlen` in `_lookup` then reads as a
    comparison of two unclassified words — which lowers to an ADDRESS compare
    and is refused (`formal/model.py`'s `string_compare_word_refusal`). Both
    operands really are lengths, so `-> int` is what lets the call site classify
    the result.
    """
    p = _name_ptr(rec, k)
    if p == 0:
        return 0
    start = _fld(rec, F_NAMES)
    lim = _fend(start) - (p - start)
    n = 0
    while n < lim and strspn(p + n, " ") == 0:
        n = n + 1
    return n


def _acts(rec):
    """The action class of `rec`. Anything unrecognised is `store`."""
    if _feq(rec, F_ACTION, "store_true") == 1:
        return A_TRUE
    if _feq(rec, F_ACTION, "store_false") == 1:
        return A_FALSE
    if _feq(rec, F_ACTION, "append") == 1:
        return A_APPEND
    if _feq(rec, F_ACTION, "count") == 1:
        return A_COUNT
    return A_STORE


def _tys(rec):
    """The value type of `rec`: `T_STR`, `T_INT`, `T_FLOAT` or `T_BAD`."""
    if _flen(rec, F_TYPE) == 0:
        return T_STR
    if _feq(rec, F_TYPE, "int") == 1:
        return T_INT
    if _feq(rec, F_TYPE, "float") == 1:
        return T_FLOAT
    return T_BAD


def _nk(rec):
    """The nargs CLASS of `rec`, or -1 for a malformed one.

    `-1` is not a class CPython has: it is what an `nargs` field that is
    neither empty, `?`, `*`, `+`, `R` nor all digits produces, and CPython
    raises `ValueError("invalid nargs value")` there. Here it is refused at
    parse time rather than guessed at.
    """
    if _flen(rec, F_NARGS) == 0:
        return N_ONE
    if _feq(rec, F_NARGS, "?") == 1:
        return N_OPT
    if _feq(rec, F_NARGS, "*") == 1:
        return N_STAR
    if _feq(rec, F_NARGS, "+") == 1:
        return N_PLUS
    if _feq(rec, F_NARGS, "R") == 1:
        return N_REM
    if _isdigits(_fld(rec, F_NARGS), _flen(rec, F_NARGS)) == 1:
        return N_INT
    return 0 - 1


def _nint(rec):
    """The integer nargs of `rec`. Only meaningful when `_nk` is `N_INT`."""
    return atoi(_fld(rec, F_NARGS))


def _derived(p, n, strip):
    """`p[0:n]` with leading `-` removed (when `strip`) and `-` as `_`.

    What CPython's `add_argument` does to a name to get a `dest`. The result is
    a fresh buffer: the name it reads is part of a read-only literal, and there
    is nowhere else on this path to put a rewritten one.
    """
    d = str_alloc(n + 1)
    u = 0
    i = 0
    lead = strip
    while i < n:
        if strspn(p + i, "-") > 0:
            if lead == 1:
                i = i + 1
                continue
            u = _putlit(d, u, "_")
        else:
            lead = 0
            u = str_put(d, u, p + i, 1)
        i = i + 1
    memset(d + u, 0, 1)
    return d


def _dest(spec, i):
    """The dest of action `i`, derived the way CPython derives it.

    For an optional, CPython uses the first option string that starts with two
    dashes and only falls back to the first one — `add_argument("-v",
    "--verbose")` has the dest `verbose`, not `v`, which is the one piece of
    `add_argument` that is not obvious from the outside. For a positional it is
    the name with `-` as `_` and nothing stripped.
    """
    rec = _rec(spec, i)
    if _flen(rec, F_DEST) > 0:
        return _ftext(rec, F_DEST)
    if _isopt(rec) == 1:
        k = 0
        while k < _nname(rec):
            if _name_len(rec, k) > 2 and strncmp(_name_ptr(rec, k), "--", 2) == 0:
                return _derived(_name_ptr(rec, k), _name_len(rec, k), 1)
            k = k + 1
    return _derived(_name_ptr(rec, 0), _name_len(rec, 0), _isopt(rec))


def _action_name(spec, i):
    """`_get_action_name` for action `i`: how an error message names it.

    An optional is named by ALL its option strings joined with `/`
    (`argument -j/--jobs: ...`); a positional by its dest. Both are measured
    against CPython by the test, and the `/` join is the one that surprises
    somebody reading a real message.
    """
    rec = _rec(spec, i)
    if _isopt(rec) == 0:
        return _dest(spec, i)
    d = str_alloc(str_len(_name_ptr(rec, 0)) * _nname(rec) + 4)
    u = 0
    k = 0
    while k < _nname(rec):
        if k > 0:
            u = _putlit(d, u, "/")
        u = str_put(d, u, _name_ptr(rec, k), _name_len(rec, k))
        k = k + 1
    memset(d + u, 0, 1)
    return d


def _brace(choices):
    """`{a,b,c}` — the metavar CPython derives from a `choices` list."""
    n = str_len(choices)
    d = str_alloc(n + 3)
    u = _putlit(d, 0, "{")
    u = str_put(d, u, choices, n)
    memset(d + u, 125, 1)      # '}'
    memset(d + u + 1, 0, 1)
    return d


def _metavar(spec, i):
    """The metavar of action `i`: declared, else `{choices}`, else dest.upper().

    CPython's `_metavar_formatter`, in that order, with the same three
    defaults. `_get_default_metavar_for_optional` is `dest.upper()` and
    `_get_default_metavar_for_positional` is `dest`, which is why a positional
    shows up in a usage line in lower case and an optional in upper.
    """
    rec = _rec(spec, i)
    if _flen(rec, F_METAVAR) > 0:
        return _ftext(rec, F_METAVAR)
    if _flen(rec, F_CHOICES) > 0:
        return _brace(_ftext(rec, F_CHOICES))
    d = _dest(spec, i)
    if _isopt(rec) == 1:
        return _upper(d)
    return d


def _required(spec, i):
    """1 if action `i` is required.

    Declared in field 5 for an OPTIONAL. For a POSITIONAL it follows from the
    nargs, because CPython's `_get_positional_kwargs` sets `required=True` for
    every nargs except `?`, `*`, REMAINDER and SUPPRESS: so a bare positional is
    required, `nargs="*"` is not, and a program that writes
    `add_argument("stems", nargs="*")` and reads `args.stems` is relying on that
    distinction — as is the error a missing bare positional produces, which is
    the one half of this a parser gets wrong quietly rather than loudly.
    """
    rec = _rec(spec, i)
    if _isopt(rec) == 1:
        return _feq(rec, F_REQUIRED, "1")
    k = _nk(rec)
    if k == N_OPT or k == N_STAR or k == N_REM:
        return 0
    return 1


def _is_int(s):
    """1 if `s` is a decimal integer CPython's `int()` would accept here.

    Optional surrounding spaces and one leading sign, then digits, and nothing
    else. CPython also accepts underscores between digits (`int("1_0") == 10`);
    that is not implemented, and a value with one is REFUSED rather than read as
    `10`, because a parser that silently answered a different number is the
    failure mode this backend's refusals exist to prevent.
    """
    i = 0
    n = str_len(s)
    while i < n and strspn(s + i, " ") > 0:
        i = i + 1
    if i < n and strspn(s + i, "+-") > 0:
        i = i + 1
    if _isdigit(s + i) == 0:
        return 0
    while i < n and _isdigit(s + i) > 0:
        i = i + 1
    while i < n and strspn(s + i, " ") > 0:
        i = i + 1
    if i != n:
        return 0
    return 1


def _in_choices(rec, v):
    """1 if `v` is one of action `rec`'s comma-separated choices.

    CPython's `_check_value`, compared as TEXT. CPython compares the CONVERTED
    value, so with `choices=["1","2"], type=int` it compares integers; the two
    agree on every value that passed `_is_int`, and a choice list that is not
    accepted by `_check` upstream is refused at parse time rather than compared
    here.
    """
    if _flen(rec, F_CHOICES) == 0:
        return 1
    p = _fld(rec, F_CHOICES)
    end = _fend(p)
    i = 0
    while i < end:
        j = _esc_end(p + i, "\\,|;")
        if _ceq(p + i, j, v) == 1:
            return 1
        i = i + j + 1
    return 0


def _ceq(p, n, v) -> int:
    """1 if the `n` RAW bytes at `p` are `v` once ESCAPES are removed.

    The CHOICES comparison, and it is a LOCKSTEP walk rather than an unescape
    into a buffer for two reasons that point the same way. It cannot unescape
    first because `_has_choice` is the hot path — every value of every
    `choices` action is compared against every declared choice, so a scratch
    buffer per comparison is an allocation in the middle of a parse. And it
    cannot compare raw bytes because the choice is stored ESCAPED (`alpha\|beta`)
    while the value on the command line is not (`alpha|beta`): `str_eq_n` over
    the raw range would find no such choice and refuse a value CPython accepts.

    The length test is the walk's own, and it is what makes the two lengths
    comparable at all — `n` counts raw bytes and `str_len(v)` counts unescaped
    ones, so they are equal only for a choice with no escape in it, which is
    every choice a spec written before this rule existed holds.
    """
    m = str_len(v)
    i = 0
    j = 0
    while i < n and j < m:
        if _esc_at(p + i) == 1:
            i = i + 1
            if i >= n:
                break
        if str_eq_n(p + i, v + j, 1) == 0:
            return 0
        i = i + 1
        j = j + 1
    if i < n:
        return 0
    if j < m:
        return 0
    return 1


# ── Finding an action by one of its option strings ──────────────────────────

def _lookup(spec, name, nlen):
    """1-based index of the action declaring exactly `name`, else 0."""
    na = _nrec(spec)
    i = 0
    while i < na:
        if _isopt(_rec(spec, i)) == 1:
            k = 0
            while k < _nname(_rec(spec, i)):
                if _name_len(_rec(spec, i), k) == nlen and str_eq_n(
                        _name_ptr(_rec(spec, i), k), name, nlen) == 1:
                    return i + 1
                k = k + 1
        i = i + 1
    return 0


def _lookup_pfx(spec, name, nlen):
    """1-based index when exactly one option string starts with `name`.

    0 when none does and -1 when more than one does, which is CPython's
    ambiguous-option case. The COUNT matters and not just the first hit:
    `--jo` matching both `--jobs` and `--job-count` is an error, not a choice
    between them, and CPython's message lists every match.
    """
    na = _nrec(spec)
    hit = 0
    cnt = 0
    i = 0
    while i < na:
        if _isopt(_rec(spec, i)) == 1:
            k = 0
            while k < _nname(_rec(spec, i)):
                m = _name_len(_rec(spec, i), k)
                if m >= nlen and str_eq_n(
                        _name_ptr(_rec(spec, i), k), name, nlen) == 1:
                    cnt = cnt + 1
                    hit = i + 1
                k = k + 1
        i = i + 1
    if cnt == 0:
        return 0
    if cnt > 1:
        return 0 - 1
    return hit


def _is_reserved(name, nlen):
    """1 if `name` is `-h` or `--help`, which this module adds itself."""
    if nlen == 2 and str_eq_n(name, "-h", 2) == 1:
        return 1
    if nlen == 6 and str_eq_n(name, "--help", 6) == 1:
        return 1
    return 0


def _short_exact(spec, arg):
    """1 if the first two bytes of `arg` are a declared option string.

    The single-dash case of CPython's `_get_option_tuples`, which is what makes
    `-j5` parse as `-j 5` and `-vvv` as `-v -v -v`. It asks about the first two
    BYTES of `arg`, which is what `strncmp(arg, name, 2)` compares against a
    declared name — no slice is built.
    """
    if str_len(arg) < 2:
        return 0
    if strncmp(arg, "--", 2) == 0:
        return 0
    if _lookup(spec, arg, 2) > 0:
        return 1
    return 0


def _looks_negative(s):
    """1 if `s` is `-123` — CPython's `_negative_number_matcher`, digits only.

    The second arm of CPython's pattern (`-\\d*\\.\\d+`) cannot occur here: a
    float is not a value on this path at all, so there is no such argument to
    recognise, and refusing `type=float` keeps that honest rather than
    approximate.
    """
    if str_len(s) < 2:
        return 0
    if strspn(s, "-") == 0:
        return 0
    if _isdigits(s + 1, str_len(s) - 1) == 1:
        return 1
    return 0


def _has_negative_options(spec):
    """1 if any declared option string looks like a negative number.

    CPython's `_has_negative_number_optionals`, and it matters for the same
    reason: with such an option declared, `-3` is an option and not a
    positional.
    """
    na = _nrec(spec)
    i = 0
    while i < na:
        if _isopt(_rec(spec, i)) == 1:
            k = 0
            while k < _nname(_rec(spec, i)):
                if _looks_negative(str_prefix(_name_ptr(_rec(spec, i), k),
                                             _name_len(_rec(spec, i), k))) == 1:
                    return 1
                k = k + 1
        i = i + 1
    return 0


def _classify(spec, arg):
    """CPython's `_parse_optional`, reduced to its verdict: 'A' or 'O'.

    The steps are CPython's, in CPython's order, and the order is load-bearing:
    an exact hit wins over the `=` split, which wins over the prefix search,
    which loses to a negative number and to an argument containing a space. The
    last step is CPython's "meant to be an optional but there is no such option"
    case, which is still an 'O' — it becomes an extra, and the message saying so
    is what the user sees.
    """
    n = str_len(arg)
    if n == 0:
        return PAT_A
    if strspn(arg, "-") == 0:
        return PAT_A
    if _is_reserved(arg, n) == 1:
        return PAT_O
    if _lookup(spec, arg, n) > 0:
        return PAT_O
    if n == 1:
        return PAT_A
    eq = strcspn(arg, "=")
    if eq < n and _lookup(spec, arg, eq) > 0:
        return PAT_O
    if _short_exact(spec, arg) == 1:
        return PAT_O
    if _lookup_pfx(spec, arg, n) != 0:
        return PAT_O
    if _looks_negative(arg) == 1 and _has_negative_options(spec) == 0:
        return PAT_A
    if strspn(arg, " ") > 0:
        return PAT_A
    return PAT_O


# ── Reading the namespace back ────────────────────────────────────────────────
#
# The namespace is a `;`-separated list of `name=value` fields, and every one
# of these walks it by index. A field's name ends at `=` or `;`, whichever
# comes first; a field with no `=` is a bare name, which is a seen action with
# no value.

def _fstart(out, k):
    """Pointer to field `k` of the namespace, or 0 if there are fewer."""
    p = out
    i = 0
    while i < k:
        q = strchr(p, SEP_FIELD)
        if q == 0:
            return 0
        p = q + 1
        i = i + 1
    return p


def _nfields(out):
    """How many `;`-separated fields the namespace has."""
    n = 1
    i = 0
    while i < str_len(out):
        if strspn(out + i, ";") > 0:
            n = n + 1
        i = i + 1
    return n


def _fname_len(p) -> int:
    """Length of field `p`'s NAME: up to `=` or `;`, whichever comes first.

    `-> int` for the reason `_name_len` gives: the answer is a `strcspn` length,
    and an unannotated callee makes `_fname_len(p) == str_len(dest)` a
    comparison of two words of unknown kind, which is refused rather than
    lowered as a string equality the operands never were.
    """
    n = strcspn(p, ";")
    eq = strcspn(p, "=")
    if eq < n:
        return eq
    return n


def _fval(p):
    """Pointer to field `p`'s value, or 0 when the field is a bare name."""
    n = _fname_len(p)
    if n >= strcspn(p, ";"):
        return 0
    return p + n + 1


def _has(out, dest):
    """1 if any field of the namespace is named `dest`."""
    i = 0
    n = _nfields(out)
    while i < n:
        p = _fstart(out, i)
        if p == 0:
            return 0
        if _fname_len(p) == str_len(dest) and str_eq_n(
                p, dest, str_len(dest)) == 1:
            return 1
        i = i + 1
    return 0


def get_at(out, dest, k):
    """The k-th value recorded for `dest`, as a buffer the caller owns.

    `""` when there is no k-th value. A fresh buffer each time, because a value
    inside the namespace is followed by `;` rather than by a NUL and there is
    nowhere on this path to put a terminator that is not the caller's own
    decision to make.
    """
    i = 0
    seen = 0
    n = _nfields(out)
    while i < n:
        p = _fstart(out, i)
        if p == 0:
            return ""
        if _fname_len(p) == str_len(dest) and str_eq_n(
                p, dest, str_len(dest)) == 1:
            v = _fval(p)
            if v != 0:
                if seen == k:
                    return str_prefix(v, strcspn(v, ";"))
                seen = seen + 1
        i = i + 1
    return ""


def get(out, dest):
    """The value of `dest`, as text. `""` when it has none.

    EVERY value in the namespace is text, `store_true`'s 0/1 and `count`'s
    number included. The alternative — storing the word an integer is and reading
    it back as a pointer — has no representation here: the classifier that
    decides whether a subscript holds a `char *` or a number is exactly the thing
    that cannot know, and a wrong guess is a wrong answer rather than a
    diagnostic. `get_int` is how a program gets a number.
    """
    return get_at(out, dest, 0)


def get_int_at(out, dest, k):
    """The k-th value of `dest` as an integer, or 0 if it is not one.

    `atoi`, which is the same conversion for a string that `_is_int` has already
    accepted on the way in. An unchecked `atoi` would be wrong rather than
    approximate — `atoi("12x")` is 12 — so the check happens where the value is
    stored and not here.
    """
    v = get_at(out, dest, k)
    if _is_int(v) == 0:
        return 0
    return atoi(v)


def get_int(out, dest):
    """The value of `dest` as an integer, or 0. See `get_int_at`."""
    return get_int_at(out, dest, 0)


def count(out, dest):
    """How many VALUES `dest` has. 0 both for "no value" and for "empty list".

    Which is why `has` exists: the two are different facts, and a program that
    wants to tell `None` from `[]` asks `has`.
    """
    n = 0
    i = 0
    f = _nfields(out)
    while i < f:
        p = _fstart(out, i)
        if p == 0:
            return n
        if _fname_len(p) == str_len(dest) and str_eq_n(
                p, dest, str_len(dest)) == 1:
            if _fval(p) != 0:
                n = n + 1
        i = i + 1
    return n


def has(out, dest):
    """1 if `dest` was given a value — CPython's `hasattr(ns, dest)`.

    Every action that was not required gets a default, so this is 1 for almost
    everything; it is 0 exactly for the actions whose value is `None`, which is
    what a program asking `if args.pass_list:` is asking.
    """
    return _has(out, dest)


# ── Building the namespace ───────────────────────────────────────────────────
#
# `str_put` terminates what it writes, so a field is assembled by putting each
# piece in turn: the next piece's `str_put` overwrites the previous NUL. A `;`
# is written with `memset` because `str_put` writes a string and `;` alone is
# not one — and `str_len` of the finished buffer is the authoritative "how much
# has been written", which is what keeps this out of `parse`'s state.

def _putf(out, name, value):
    """Append one `name=value` field, or a bare `name` when `value` is 0.

    0 on success; -1 if it would not fit in `BUF_CAP`, or if the value contains
    the field separator — which cannot be represented and is refused rather than
    written, because a value that quietly split a field would be a wrong answer
    with nothing left to detect it.
    """
    u = str_len(out)
    if u > 0:
        if u + 1 >= BUF_CAP:
            return 0 - 1
        memset(out + u, 59, 1)      # ';'
        memset(out + u + 1, 0, 1)
        u = u + 1
    if u + str_len(name) >= BUF_CAP:
        return 0 - 1
    u = str_put(out, u, name, str_len(name))
    if value == 0:
        return 0
    if _haschar(value, ";") == 1:
        return 0 - 1
    if u + 1 + str_len(value) >= BUF_CAP:
        return 0 - 1
    memset(out + u, 61, 1)      # '='
    memset(out + u + 1, 0, 1)
    str_put(out, u + 1, value, str_len(value))
    return 0


def _puti(out, name, n):
    """Append one `name=<decimal>` field. 0 on success, -1 if it will not fit.

    The integer-to-text step, for `store_true`, `store_false` and `count`, whose
    values are numbers on the command line and are stored as digits so that
    every value in the namespace is a `char *`. `snprintf` is the C library's
    own conversion rather than a hand-written one, for the reason
    `os/_syscalls.mojo` gives for `strcat`: a second implementation of a
    routine that already exists is a second thing to be wrong.
    """
    var b: Pointer[UInt8] = str_alloc(24)
    snprintf(b, 24, "%d", n)
    return _putf(out, name, b)


def _dropf(out, dest):
    """Remove every field named `dest`.

    Needed for exactly one case: an option with `nargs="?"` given without a
    value, where CPython's `_get_values` answers `action.const` — `None`, since
    there is no `const` in this subset — so the declared default must NOT
    survive. In place and forward-only, because only fields are removed and the
    write position can never pass the read one.
    """
    n = str_len(out)
    r = 0
    w = 0
    first = 1
    while r < n:
        end = r + strcspn(out + r, ";")
        if _fname_len(out + r) != str_len(dest) or str_eq_n(
                out + r, dest, str_len(dest)) == 0:
            if first == 0:
                memmove(out + w, ";", 1)
                memset(out + w + 1, 0, 1)
                w = w + 1
            memmove(out + w, out + r, end - r)
            memset(out + w + end - r, 0, 1)
            w = w + end - r
            first = 0
        r = end
        if r < n:
            r = r + 1
    memset(out + w, 0, 1)
    return 0


# ── Defaults ─────────────────────────────────────────────────────────────────
#
# `parse_known_args` gives the namespace every action's default before it looks
# at the command line, and a later assignment to an existing key keeps its
# position — which is why the namespace here is in DECLARATION order rather than
# in the order the arguments happened to appear.

def _default_for(spec, i):
    """The value action `i` has when it never appears, or 0 for None.

    0 means None, which is CPython's None and the only thing it means here: no
    field at all. Every other answer is a buffer this call made or a literal,
    and neither needs freeing.
    """
    rec = _rec(spec, i)
    if _flen(rec, F_DEFAULT) > 0:
        if _feq(rec, F_DEFAULT, NONE_TEXT) == 1:
            return 0                    # `default=None`, said so explicitly
        if _acts(rec) == A_APPEND and _feq(rec, F_DEFAULT, "[]") == 1:
            return 0                    # `default=[]`: an append starts empty
        return _ftext(rec, F_DEFAULT)
    if _acts(rec) == A_TRUE:
        return "0"
    if _acts(rec) == A_FALSE:
        return "1"
    return 0


def _emit_defaults(spec, out):
    """Write every action's default into `out`. 0 on success, -1 if it will not
    fit.

    An action whose default is None writes NO field, which is what makes
    `has(out, dest)` Python's `hasattr`. `count` and `append` write nothing:
    CPython's `_CountAction` default is None (it is 0 only after the first
    `-v`), and an `append` starts from its own list.
    """
    na = _nrec(spec)
    i = 0
    while i < na:
        rec = _rec(spec, i)
        a = _acts(rec)
        if a == A_APPEND:
            # `default=[]` — the one `append` default in this repository's
            # corpus, and it means an EMPTY LIST, which is the bare-name shape
            # rather than no field. `_AppendAction.__call__` appends to what
            # the default left, so getting this wrong shows up as the first
            # value being missing from the list rather than as a crash.
            if _feq(rec, F_DEFAULT, "[]") == 1:
                if _putf(out, _dest(spec, i), 0) < 0:
                    return 0 - 1
            i = i + 1
            continue
        d = _default_for(spec, i)
        if d != 0:
            if _putf(out, _dest(spec, i), d) < 0:
                return 0 - 1
        i = i + 1
    return 0


# ── Splitting the run of arguments among the positionals ─────────────────────
#
# CPython matches positionals with regular expressions built from each action's
# nargs (`_get_nargs_pattern`) and picks the LONGEST prefix of the remaining
# positionals that matches (`_match_arguments_partial`). Those patterns are only
# ever over `-`, `A` and `O`, and no positional pattern can match an `O` except
# REMAINDER's `.*` — so the whole of it is a greedy split of a run of `A`s, and
# that is what these four functions compute. `_split` answers "can these k
# positionals consume m arguments", `_take` answers "how many does positional
# `i` of that slice get", and together they let `parse` apply the split without
# an array to hold it in.

def _min_nargs(spec, i):
    """The fewest arguments positional `i` can be given."""
    k = _nk(_rec(spec, i))
    if k == N_ONE:
        return 1
    if k == N_PLUS:
        return 1
    if k == N_INT:
        return _nint(_rec(spec, i))
    return 0


def _rest_min(spec, p, k, i):
    """How many arguments the positionals after `i` in a k-slice must have."""
    m = 0
    j = i + 1
    while j < p + k:
        m = m + _min_nargs(spec, j)
        j = j + 1
    return m


def _take(spec, p, k, i, avail):
    """How many of `avail` arguments positional `i` takes in slice `[p, p+k)`.

    The greedy order of `_get_nargs_pattern`'s quantifiers, read off it: an
    optional takes one if the rest can still be satisfied, a `*` takes
    everything the rest does not need, a `+` takes that much but not less than
    one, a fixed count takes exactly that count, and a REMAINDER positional
    takes everything that is left — including arguments past the run, which is
    what `.*` means.
    """
    j = _nk(_rec(spec, i))
    need = _rest_min(spec, p, k, i)
    if j == N_REM:
        return avail
    if j == N_ONE:
        return 1
    if j == N_INT:
        return _nint(_rec(spec, i))
    if j == N_OPT:
        if avail - 1 >= need:
            return 1
        return 0
    if j == N_PLUS and avail - need < 1:
        return 1
    return avail - need


def _split(spec, p, k, m):
    """How many of `m` arguments the k positionals at `p` would leave over.

    -1 when they cannot match at all. Greedy left to right, and a slice is
    viable only if no positional is ever asked for more than what is left after
    the ones that follow it — which is exactly the condition a regex with
    backtracking would find, without the backtracking.
    """
    avail = m
    i = p
    while i < p + k:
        t = _take(spec, p, k, i, avail)
        if avail - t < _rest_min(spec, p, k, i):
            return 0 - 1
        if t < _min_nargs(spec, i):
            return 0 - 1
        avail = avail - t
        i = i + 1
    return avail


# ── The usage line ───────────────────────────────────────────────────────────
#
# CPython's `_format_usage`, for the case where the line fits the width. The
# wrapped case is not implemented and says so at the top of this file.

def _args_part(spec, i):
    """CPython's `_format_args` for action `i`, as a buffer the caller owns."""
    rec = _rec(spec, i)
    k = _nk(rec)
    m = _metavar(spec, i)
    ml = str_len(m)
    if k == N_ONE:
        return str_dup(m)
    if k == N_OPT:
        return _wrap1(m, "[", "]")
    if k == N_STAR:
        return _wrap2(m, "[", " ...]")
    if k == N_PLUS:
        return _wrap3(m, "", " [", " ...]")
    if k == N_REM:
        return "..."
    n = _nint(rec)
    d = str_alloc(ml * n + 1)
    u = 0
    c = 0
    while c < n:
        if c > 0:
            u = _putlit(d, u, " ")
        u = str_put(d, u, m, ml)
        c = c + 1
    memset(d + u, 0, 1)
    return d


def _wrap1(m, a, b):
    """`a + m + b` in a fresh buffer."""
    d = str_alloc(str_len(m) + 3)
    u = str_put(d, 0, a, 1)
    u = str_put(d, u, m, str_len(m))
    u = str_put(d, u, b, 1)
    memset(d + u, 0, 1)
    return d


def _wrap2(m, a, b):
    """`a + m + b` where `b` is the five characters ` ...]` — the `*` shape."""
    d = str_alloc(str_len(m) + 7)
    u = str_put(d, 0, a, 1)
    u = str_put(d, u, m, str_len(m))
    u = str_put(d, u, b, 5)
    memset(d + u, 0, 1)
    return d


def _wrap3(m, a, b, c):
    """`a + m + b + m + c` in a fresh buffer — the `+` shape."""
    d = str_alloc(str_len(m) * 2 + 7)
    u = str_put(d, 0, a, str_len(a))
    u = str_put(d, u, m, str_len(m))
    u = _putlit(d, u, b)
    u = str_put(d, u, m, str_len(m))
    u = _putlit(d, u, c)
    memset(d + u, 0, 1)
    return d


def _usage_part(spec, i):
    """One action's piece of the usage line, brackets included.

    CPython prints `option_strings[0]` and never the `/`-joined form, so
    `-v --verbose` contributes `[-v]`: `Action.format_usage` is `return
    self.option_strings[0]`, and `_get_actions_usage_parts` uses it for every
    optional.
    """
    rec = _rec(spec, i)
    first = str_prefix(_name_ptr(rec, 0), _name_len(rec, 0))
    if _isopt(rec) == 0:
        return _args_part(spec, i)
    if _takes_value(rec) == 0:
        if _required(spec, i) == 1:
            return first
        return _wrap1(first, "[", "]")
    ap = _args_part(spec, i)
    d = str_alloc(str_len(first) + str_len(ap) + 4)
    u = str_put(d, 0, first, str_len(first))
    u = _putlit(d, u, " ")
    u = str_put(d, u, ap, str_len(ap))
    memset(d + u, 0, 1)
    if _required(spec, i) == 1:
        return d
    return _wrap1(d, "[", "]")


def _usage_sides(spec, opt, pos):
    """The usage line's two halves: the optionals into `opt`, the rest into `pos`.

    Optionals in declaration order and then positionals in declaration order:
    CPython's `_get_actions_usage_parts`, and the order is visible in every usage
    line. `-h` comes first, because CPython's help action is the first action it
    adds.

    **Two buffers rather than one, and that is `_format_usage`'s shape rather
    than a choice**: a usage line too long for the width is folded with the
    optionals and the positionals folded SEPARATELY (`opt_parts` and
    `pos_parts`, two `get_lines` calls), so a line may end on an optional and the
    positionals begin the next one. One joined string cannot express that, which
    is why the parts are built here once and read twice rather than rebuilt per
    line.
    """
    na = _nrec(spec)
    u = _putlit(opt, 0, "[-h]")
    i = 0
    while i < na:
        if _isopt(_rec(spec, i)) == 1:
            p = _usage_part(spec, i)
            u = _putlit(opt, u, " ")
            u = str_put(opt, u, p, str_len(p))
        i = i + 1
    memset(opt + u, 0, 1)
    u = 0
    i = 0
    while i < na:
        if _isopt(_rec(spec, i)) == 0:
            p = _usage_part(spec, i)
            if u > 0:
                u = _putlit(pos, u, " ")
            u = str_put(pos, u, p, str_len(p))
        i = i + 1
    memset(pos + u, 0, 1)
    return 0


def _part_len(s, i, n):
    """The length of the usage part at `s[i:]`, its brackets included.

    `_format_usage`'s `part_regexp` — `\S+`, except that a `[` opens a part
    which runs to the `]` that closes it. `[-j JOBS]` is ONE part, and a
    splitter that broke it on the space would let a folded line end between an
    option and the metavar that belongs to it.
    """
    if strncmp(s + i, "[", 1) == 0:
        k = i + 1
        while k < n and strncmp(s + k, "]", 1) != 0:
            k = k + 1
        if k < n:
            return k + 1 - i
    k = i
    while k < n and strspn(s + k, " ") == 0:
        k = k + 1
    return k - i


def _get_lines(out, s, indent_len, prefix_len):
    """The usage parts in `s` folded at TEXT_WIDTH into `out`. The LINE COUNT.

    `_format_usage`'s `get_lines`, which is not `textwrap`: a usage line folds
    over PARTS, so a line break can only land between two of them and a part is
    never split. That is why this function exists beside `_wrap_into` instead of
    calling it — the two rules disagree, and CPython uses both.

    `out` is written from 0 and NUL-terminated, so the caller copies it with
    `str_put` and gets its length from `str_len`; that is also how the LINE COUNT
    comes back, which `_format_usage` needs (`if len(lines) > 1`) to decide
    whether the optionals and the positionals have to be folded separately.

    `prefix_len` is the length of the `usage: ` prefix when the first line
    carries NO indent — CPython writes the indent and then strips it off line 0
    (`lines[0] = lines[0][indent_length:]`), which is the same thing said once.
    """
    u = 0
    lines = 0
    line_len = indent_len - 1
    if prefix_len > 0:
        line_len = prefix_len - 1
    placed = 0
    n = str_len(s)
    i = 0
    while i < n:
        while i < n and strspn(s + i, " ") > 0:
            i = i + 1
        if i >= n:
            break
        pl = _part_len(s, i, n)
        if line_len + 1 + pl > TEXT_WIDTH and placed > 0:
            u = _nl_at(out, u)
            lines = lines + 1
            placed = 0
            line_len = indent_len - 1
        if placed == 0:
            if not (lines == 0 and prefix_len > 0):
                u = _pad(out, u, indent_len)
            lines = lines + 1
        else:
            u = _putlit(out, u, " ")
        u = str_put(out, u, s + i, pl)
        placed = placed + 1
        line_len = line_len + 1 + pl
        i = i + pl
    if placed > 0:
        u = _nl_at(out, u)
    return lines


def _with_prog(prog, parts):
    """`prog` then the parts in `parts`, space-separated. A fresh buffer."""
    d = str_alloc(BUF_CAP)
    u = str_put(d, 0, prog, str_len(prog))
    if str_len(parts) > 0:
        u = _putlit(d, u, " ")
        u = str_put(d, u, parts, str_len(parts))
    memset(d + u, 0, 1)
    return d


# ── wrapping: `textwrap`'s greedy fill, at the one width this target knows ────
#
# CPython's help formatter does not decide where a line ends; it asks
# `textwrap.wrap`, and the answer is a byte-for-byte property of that function's
# chunker and its greedy loop. So this is a re-implementation of ONE function
# rather than a layout of its own, and it is here rather than in the callers
# because two of them need it with two different indents (`_entry` and the
# description). The usage line's fold is NOT this one — `_get_lines` below is
# `_format_usage`'s own, simpler rule over parts rather than characters.
#
# Every value here is a plain integer and a `char *`: there are no tuples, no
# lists and no closures on this path, so a "current line" is an OFFSET INTO THE
# OUTPUT plus a length, and a chunk is an (offset, length) pair carried in
# locals. Nothing is copied before it is written — a chunk goes from `text` to
# `buf` in one `str_put` — and the trailing whitespace `drop_whitespace` removes
# is not removed at all: it is simply not written over, because the newline goes
# at the offset before it.

# `TextWrapper.tabsize`, kept because it is a property of the wrapping rather
# than of this target: the formatter squashes whitespace BEFORE `textwrap` runs
# (see `_squashed`), so on this path nothing expands a tab — and if a caller ever
# wraps without squashing first, the tab stop is the number that decides where.
TAB_STOP = 8

MIN_WRAP_WIDTH = 11  # CPython's `max(self._width - help_position, 11)`

USAGE_PREFIX = "usage: "


def _ws_set():
    """The bytes `\s` matches in ASCII, as a set `strspn` can be given.

    A literal cannot spell them: a string literal's escapes are NOT unescaped on
    this path, so `\t` here would be a backslash and a `t`. Every separator in
    this module is a `memset` byte for that reason, and this is the one place a
    SET of them is wanted rather than a single value.
    """
    s = str_alloc(8)
    memset(s, 32, 1)          # space
    memset(s + 1, 9, 1)       # tab
    memset(s + 2, 10, 1)      # newline
    memset(s + 3, 11, 1)      # vertical tab
    memset(s + 4, 12, 1)      # form feed
    memset(s + 5, 13, 1)      # carriage return
    memset(s + 6, 0, 1)
    return s


def _cat3(a, b, c):
    """`a` then `b` then `c`, NUL-terminated. A fresh buffer each call."""
    s = str_alloc(str_len(a) + str_len(b) + str_len(c) + 1)
    u = str_put(s, 0, a, str_len(a))
    u = str_put(s, u, b, str_len(b))
    u = str_put(s, u, c, str_len(c))
    memset(s + u, 0, 1)
    return s


def _letter_set():
    """`[^\d\W]` — a letter or an underscore, which is `wordsep_re`'s `letter`.

    Not the whole of `\w`: a DIGIT is a word character and not a letter, and the
    difference decides whether `a-1` is one chunk or two.
    """
    return _cat3(LOWER, UPPER, "_")


def _word_set():
    """`\w` without the unicode: letters, digits and `_`, as one set."""
    return _cat3(_letter_set(), DIGITS, "")


def _punct_set():
    """`wordsep_re`'s `word_punct` — the characters an em-dash may follow."""
    return _cat3(_word_set(), "!\"'&.,?", "")


def _is_letter(p, lt):
    """1 if the byte at `p` is a letter or `_`."""
    return strspn(p, lt)


def _is_wordchar(p, wd):
    """1 if the byte at `p` is a letter, a digit or `_`."""
    return strspn(p, wd)
    

def _is_wordpunct(p, wd, pt):
    """1 if the byte at `p` is `word_punct`: a word character or one of `!"'&.,?`."""
    if strspn(p, wd) > 0:
        return 1
    return strspn(p, pt)


def _emdash_at(text, j, n, wd):
    """1 if a run of 2 or more `-` starts at `j` and a word character follows it.

    The `--` in `Look, goof-ball -- use the -b option!` is a chunk of its own in
    CPython's chunker, and this is the test for it: an em-dash is two or more
    hyphens followed by a word character.
    """
    k = j
    while k < n and strncmp(text + k, "-", 1) == 0:
        k = k + 1
    if k - j < 2 or k >= n:
        return 0
    return _is_wordchar(text + k, wd)


def _chunk_end(text, j, n, ws, wd, lt, pt):
    """The index just past the WORD chunk that starts at `j`.

    `TextWrapper._split`'s word branch, read rule by rule for the ASCII this
    target has. `wordsep_re` is `\S+?` as SHORT as possible, finished by one of
    three things, and this is those three:

      * the end of a word — a whitespace byte, or the end of the text;
      * a hyphenated word — a `-` with two letters (or letter-`-`-letter)
        before it and a letter, an optional `-` and a letter after it. That is
        what splits `--no-cache` into `--no-` and `cache` and leaves `a-1` and
        `-x` whole;
      * an em-dash — a run of two or more `-` after a `word_punct`, which ends
        the chunk BEFORE the run.

    The em-dash run is itself a chunk when the chunk STARTS at one, which is the
    first arm here and not a special case of the rest.
    """
    if j > 0 and strncmp(text + j, "-", 1) == 0 \
            and _is_wordpunct(text + j - 1, wd, pt) > 0 \
            and _emdash_at(text, j, n, wd) == 1:
        k = j
        while k < n and strncmp(text + k, "-", 1) == 0:
            k = k + 1
        return k
    pos = j + 1
    while pos <= n:
        if pos == n or strspn(text + pos, ws) > 0:
            return pos
        if pos > j and strncmp(text + pos, "-", 1) == 0 \
                and _is_wordpunct(text + pos - 1, wd, pt) > 0 \
                and _emdash_at(text, pos, n, wd) == 1:
            return pos
        if strncmp(text + pos, "-", 1) == 0 and pos - 1 > j:
            lb = 0
            if pos >= 2 and _is_letter(text + pos - 1, lt) > 0 \
                    and _is_letter(text + pos - 2, lt) > 0:
                lb = 1
            if pos >= 3 and _is_letter(text + pos - 1, lt) > 0 \
                    and strncmp(text + pos - 2, "-", 1) == 0 \
                    and _is_letter(text + pos - 3, lt) > 0:
                lb = 1
            la = 0
            if pos + 2 < n and _is_letter(text + pos + 1, lt) > 0:
                if _is_letter(text + pos + 2, lt) > 0:
                    la = 1
                elif strncmp(text + pos + 2, "-", 1) == 0 \
                        and _is_letter(text + pos + 3, lt) > 0:
                    la = 1
            if lb == 1 and la == 1:
                return pos + 1
        pos = pos + 1
    return n


def _hyphen_break(text, j, clen, space_left):
    """Where to break a word too long for the line it is on: at its last `-`.

    `TextWrapper._handle_long_word`'s `break_on_hyphens` refinement, which
    prefers a break at a hyphen to filling the line exactly. The regex's own
    conditions are kept: the hyphen must be inside the piece (`h > 0` in the
    original is "not at the start of the chunk") and something before it must
    not itself be a hyphen, so a run of dashes is not a break.
    """
    end = space_left
    if clen > space_left:
        h = -1
        k = 0
        while k < space_left and k < clen:
            if strncmp(text + j + k, "-", 1) == 0:
                h = k
            k = k + 1
        if h > 0:
            bare = 0
            m = 0
            while m < h:
                if strncmp(text + j + m, "-", 1) != 0:
                    bare = 1
                m = m + 1
            if bare == 1:
                end = h + 1
    return end


def _nl_at(buf, at):
    """A newline (and the NUL that keeps the buffer terminated) at `buf[at]`.

    `_nl` at an offset that is not the end, which is what dropping a line's
    trailing whitespace amounts to: the newline goes where the whitespace began
    and the whitespace bytes are simply not there any more.
    """
    memset(buf + at, 10, 1)
    memset(buf + at + 1, 0, 1)
    return at + 1


def _squashed(text):
    """`text` with every whitespace byte a single space, then stripped.

    **`HelpFormatter._split_lines` and `_fill_text` do this before `textwrap`
    ever sees the text**, and the order is the whole content of this function:

        text = self._whitespace_matcher.sub(' ', text).strip()

    So a TAB in a help string is a SPACE here — `textwrap`'s own `expandtabs`
    never runs, because by the time its `wrap` is called there is no tab left in
    the string, and a help string is therefore expanded to one space and not to a
    tab stop. Both call sites go through the same two lines in CPython, which is
    why this is one function rather than one per caller, and why the folding a tab
    produces is the folding a space produces.

    The `strip` is the other half and is just as observable: `_format_action`
    tests `action.help.strip()` and `_format_text` strips before filling, so a
    help text with a leading or trailing space does not carry it into the column.
    """
    n = str_len(text)
    if n == 0:
        return str_alloc(2)
    ws = _ws_set()
    d = str_alloc(n + 2)
    u = 0
    i = 0
    while i < n:
        if strspn(text + i, ws) > 0:
            u = str_put(d, u, " ", 1)
        else:
            u = str_put(d, u, text + i, 1)
        i = i + 1
    # `str.strip()`: drop the whitespace runs at both ends, keeping the spaces
    # between two non-whitespace bytes exactly one for one.
    start = 0
    while start < u and strspn(d + start, ws) > 0:
        start = start + 1
    end = u
    while end > start and strspn(d + end - 1, ws) > 0:
        end = end - 1
    tail = str_alloc(u - start + 2)
    v = str_put(tail, 0, d + start, end - start)
    memset(tail + v, 0, 1)
    return tail


def _wrap_into(buf, u, text, width, ind0, indn, wsub):
    """`text` wrapped to `width` at `buf[u:]`, one line each. The new `u`.

    `wsub` is how many columns of the indent count AGAINST the width, and it is a
    parameter because `textwrap` counts all of an indent it is handed while
    `_format_action` hands it none: the help column is `%*s` added to each
    wrapped line AFTER the wrap, so a help text is wrapped at the full
    `help_width` and then indented, and an implementation that counted the
    indent would fold one word early. The description passes 0 for the same
    reason — `_format_text`'s indent is `current_indent`, which is 0 at the top
    level — and would pass 2 inside a section, where `textwrap` really would
    count it.

    `textwrap.wrap(text, width, initial_indent=ind0, subsequent_indent=indn)`
    with every default left at its default — which is what `HelpFormatter` asks
    for: it calls `textwrap.wrap` and `textwrap.fill` with no keyword of its own,
    so `drop_whitespace`, `break_long_words` and `break_on_hyphens` are all at
    their defaults. (`expand_tabs` is at its default too, and does nothing here:
    the formatter squashes whitespace before it gets here — `_squashed`.)

    The loop is `_wrap_chunks` with the chunk LIST flattened into integers: a
    line is open or it is not, and while it is open its length is enough to
    decide every branch the original takes, because nothing here re-reads what it
    has already written. Four rules carry the whole of it, and all four are
    textwrap's:

      * `wsub` columns of the indent count against the width, which is
        `width - len(indent)` when the caller passed the indent to `textwrap`
        and `width` when it added the indent afterwards;
      * a chunk is added while `cur_len + len(chunk) <= width - len(indent)`,
        which is why the whitespace between two words has to fit too;
      * a chunk that does not fit ends the line, UNLESS it is longer than the
        whole width — then the word is BROKEN (`_handle_long_word`) after its
        last hyphen that fits, and the REMAINDER of the chunk is still that
        chunk: it is not re-split, which is the one thing a flattened loop has to
        carry explicitly;
      * whitespace at the start of a line is dropped and at the end of one is
        dropped, and a line with nothing else on it is not a line at all — the
        last rule is why a paragraph of nothing but spaces produces no output.

    The text is `_squashed` first, which is what CPython's formatter does first.
    """
    if str_len(text) == 0:
        return u
    text = _squashed(text)
    n = str_len(text)
    ws = _ws_set()
    lt = _letter_set()
    wd = _word_set()
    pt = _punct_set()
    i = 0
    forced = -1          # the end of a chunk left over from a broken word
    forced_word = 0      # …and whether that chunk was a word or whitespace
    open_line = 0
    emitted = 0          # lines written, which is `_wrap_chunks`' `lines`
    first = 1
    content = 0          # `buf` offset where the open line's content began
    keep = 0             # …and where its content ends without trailing space
    while i < n:
        if forced > i:
            k = forced
            word = forced_word
            forced = -1
        elif strspn(text + i, ws) > 0:
            k = i
            while k < n and strspn(text + k, ws) > 0:
                k = k + 1
            word = 0
        else:
            k = _chunk_end(text, i, n, ws, wd, lt, pt)
            word = 1
        clen = k - i
        # Whitespace at the start of a line is dropped, and `emitted == 0` is
        # the whole of that exception: a paragraph that starts with a space
        # keeps it. Asked BEFORE the line is opened, because "at the start of a
        # line" is what it is.
        if word == 0 and open_line == 0 and emitted > 0:
            i = k
            continue
        if open_line == 0:
            if first == 1:
                u = str_put(buf, u, ind0, str_len(ind0))
            else:
                u = str_put(buf, u, indn, str_len(indn))
            content = u
            keep = u
            open_line = 1
        if (u - content) + clen <= width - wsub:
            u = str_put(buf, u, text + i, clen)
            if word == 1:
                keep = u
            i = k
            continue
        # It does not fit.
        if clen > width - wsub:
            if width - wsub < 1:
                space_left = 1
            else:
                space_left = width - wsub - (u - content)
            if space_left > 0:
                end = _hyphen_break(text, i, clen, space_left)
                if word == 1:
                    # A WORD: it is content, and whitespace already on the line
                    # is interior now, so it stays.
                    u = str_put(buf, u, text + i, end)
                    keep = u
                # A WHITESPACE piece is dropped by the same rule that drops a
                # line's trailing whitespace, so a line made only of it is not
                # written at all.
                if keep > content:
                    u = _nl_at(buf, keep)
                    emitted = emitted + 1
                else:
                    u = keep
                open_line = 0
                first = 0
                i = i + end
                forced = k
                forced_word = word
                continue
        if keep > content:
            u = _nl_at(buf, keep)
            emitted = emitted + 1
        else:
            u = keep
        open_line = 0
        first = 0
        if word == 0:
            i = k
    if open_line == 1 and keep > content:
        u = _nl_at(buf, keep)
    return u


def _basename(p):
    """The part of `p` after its last `/`, as a buffer the caller owns.

    CPython's `prog` default is `os.path.basename(sys.argv[0])`, and `argv[0]`
    is the one thing about a command line that survives to here.
    """
    n = str_len(p)
    i = n - 1
    while i >= 0:
        if strspn(p + i, "/") > 0:
            return str_copy(str_alloc(n - i - 1), p + i + 1, n - i - 1)
        i = i - 1
    return str_dup(p)


def _usage_line(spec, argv, err):
    """`usage: prog <parts>` into `err`, folded when it does not fit. The length.

    `_format_usage` in full, including the half it usually skips: a usage line
    longer than the width is folded onto indented continuation lines, with the
    prog sharing the first line when it is short enough and sitting on a line of
    its own when it is not, and with the optionals and the positionals folded
    SEPARATELY so a line can end between them. The width test is against the
    one-line form, so that form is built — once — to be measured.
    """
    opt = str_alloc(BUF_CAP)
    pos = str_alloc(BUF_CAP)
    _usage_sides(spec, opt, pos)
    prog = _basename(argv[0])
    u = _putlit(err, 0, USAGE_PREFIX)
    flat = str_alloc(BUF_CAP)
    f = str_put(flat, 0, prog, str_len(prog))
    if str_len(opt) > 0:
        f = _putlit(flat, f, " ")
        f = str_put(flat, f, opt, str_len(opt))
    if str_len(pos) > 0:
        f = _putlit(flat, f, " ")
        f = str_put(flat, f, pos, str_len(pos))
    memset(flat + f, 0, 1)
    if str_len(USAGE_PREFIX) + f <= TEXT_WIDTH:
        u = str_put(err, u, flat, f)
        return _nl_at(err, u)
    if (str_len(USAGE_PREFIX) + str_len(prog)) * 4 <= TEXT_WIDTH * 3:
        # A SHORT prog: it shares the first line with the optionals, and the
        # continuation lines are indented past `usage: <prog> `.
        indent = str_len(USAGE_PREFIX) + str_len(prog) + 1
        head = _with_prog(prog, opt)
        if str_len(opt) == 0:
            head = _with_prog(prog, pos)
        _get_lines(err + u, head, indent, str_len(USAGE_PREFIX))
        u = u + str_len(err + u)
        _get_lines(err + u, pos, indent, 0)
        u = u + str_len(err + u)
        return u
    # A LONG prog: it gets a line of its own, and the parts are folded after it.
    indent = str_len(USAGE_PREFIX)
    u = _putlit(err, u, prog)
    u = _nl_at(err, u)
    allp = str_alloc(BUF_CAP)
    g = str_put(allp, 0, opt, str_len(opt))
    if str_len(pos) > 0:
        g = _putlit(allp, g, " ")
        g = str_put(allp, g, pos, str_len(pos))
    memset(allp + g, 0, 1)
    block = str_alloc(BUF_CAP)
    # One fold of everything, and the SEPARATE folds only if that took more than
    # one line — which is CPython's own test, and the reason a usage line whose
    # parts fit on one continuation line is not split at the optional/positional
    # boundary for no visible reason.
    if _get_lines(block, allp, indent, 0) > 1:
        _get_lines(err + u, opt, indent, 0)
        u = u + str_len(err + u)
        _get_lines(err + u, pos, indent, 0)
        u = u + str_len(err + u)
    else:
        u = str_put(err, u, block, str_len(block))
    return u


def _invocation(spec, i):
    """`_format_action_invocation` for action `i`: what the help list prints.

    An optional is its option strings joined with `, ` and, when it takes a
    value, a space and its metavar form; a positional is its metavar. `-h` and
    `--help` print as `-h, --help`.
    """
    rec = _rec(spec, i)
    if _isopt(rec) == 0:
        return _metavar(spec, i)
    d = str_alloc(str_len(_name_ptr(rec, 0)) * _nname(rec) + 40)
    u = 0
    k = 0
    while k < _nname(rec):
        if k > 0:
            u = _putlit(d, u, ", ")
        u = str_put(d, u, _name_ptr(rec, k), _name_len(rec, k))
        k = k + 1
    if _takes_value(rec) == 0:
        memset(d + u, 0, 1)
        return d
    ap = _args_part(spec, i)
    u = _putlit(d, u, " ")
    u = str_put(d, u, ap, str_len(ap))
    memset(d + u, 0, 1)
    return d


def _max_invocation(spec):
    """The longest invocation any action has, plus the 2 of the section indent.

    `_HelpFormatter.add_argument`'s `_action_max_length`, which is what decides
    the column the help text starts in. The indent is counted because the
    formatter indents every section by two, and `-h` counts because CPython's
    help action is an action like any other when the width is computed.
    """
    m = str_len(HELP_INVOCATION) + 2
    i = 0
    while i < _nrec(spec):
        n = str_len(_invocation(spec, i)) + 2
        if n > m:
            m = n
        i = i + 1
    return m


def _helppos(spec):
    """The column the help text starts in: `_format_action`'s `help_position`.

    `min(action_max_length + 2, max_help_position)`, with `max_help_position` at
    argparse's own default of 24.
    """
    p = _max_invocation(spec) + 2
    if p > MAX_HELP_POSITION:
        return MAX_HELP_POSITION
    return p


def _entry(err, u, inv, h, helppos):
    """One `  invocation   help` entry of the help listing. The new length.

    `_format_action`'s three cases: a short invocation is padded out to the help
    column and its help follows on the same line; a long one is printed on its
    own and the help is indented under it; and an action with no help text is
    the invocation and nothing else.

    **And the help text is WRAPPED**, which is the part that used to be missing
    (`bugs/FORMAL_argparse_help_wrapping_not_implemented.md`). The help column is
    `help_width = max(self._width - help_position, 11)` — the floor is CPython's
    — the first line starts where the header left it, and every line after it is
    indented to the help column.

    **TWO conditions, not one**, which is the detail that made this wrong once:
    `if not action.help:` decides whether the invocation is PADDED, and
    `if action.help and action.help.strip():` decides whether the help is
    PRINTED. A help text of nothing but spaces is therefore padded like a real
    one and then prints nothing — and CPython emits the padded spaces, so the
    difference is visible at the end of the line.
    """
    if str_len(h) == 0:
        u = _putlit(err, u, "  ")
        u = str_put(err, u, inv, str_len(inv))
        return _nl(err, u)
    width = helppos - 4
    hw = TEXT_WIDTH - helppos
    if hw < MIN_WRAP_WIDTH:
        hw = MIN_WRAP_WIDTH
    if str_len(inv) <= width:
        u = _putlit(err, u, "  ")
        u = str_put(err, u, inv, str_len(inv))
        u = _pad(err, u, width - str_len(inv))
        u = _putlit(err, u, "  ")
        if _has_nonspace(h) == 1:
            return _wrap_help(err, u, h, hw, helppos, 0)
        # `elif not action_header.endswith('\n'): parts.append('\n')` — the
        # header of this case does not end in one, so the newline is added here.
        return _nl(err, u)
    u = _putlit(err, u, "  ")
    u = str_put(err, u, inv, str_len(inv))
    u = _nl(err, u)
    if _has_nonspace(h) == 0:
        return u
    return _wrap_help(err, u, h, hw, helppos, helppos)


def _wrap_help(err, u, h, hw, helppos, ind0):
    """`h` wrapped into the help column at `err[u:]`. The new `u`.

    `_format_action`'s two `indent_first` cases, and nothing else:
    `indent_first = 0` when the invocation shared the line with the first line of
    the help and `indent_first = help_position` when it did not, with every line
    after the first written at `'%*s' % (help_position, '')`. The continuation
    indent is therefore a string of `helppos` spaces, and `ind0` is how many of
    them the FIRST line gets.
    """
    if ind0 > 0:
        u = _pad(err, u, ind0)
    cont = _spaces(helppos)
    # 0, not `helppos`: `_format_action` wraps at `help_width` and adds the
    # column afterwards, so the indent is not one of the columns the width is
    # made of. See `_wrap_into`'s `wsub`.
    return _wrap_into(err, u, h, hw, "", cont, 0)


def _has_nonspace(t):
    """1 if `t` holds a byte that is not whitespace.

    `_format_text` prints nothing for a text that is empty once it is stripped,
    and stripping is a question about whitespace — so it is asked with the
    whitespace SET `_wrap_into` builds rather than with a second notion of what
    whitespace is.
    """
    if str_len(t) == 0:
        return 0
    ws = _ws_set()
    i = 0
    while i < str_len(t):
        if strspn(t + i, ws) == 0:
            return 1
        i = i + 1
    return 0


def _spaces(n):
    """`n` spaces, NUL-terminated. The continuation indent of a wrapped block."""
    s = str_alloc(n + 2)
    memset(s, 32, n)
    memset(s + n, 0, 1)
    return s


def _pad(buf, u, n):
    """`n` spaces at `buf[u:]`. The new `u`.

    Written with `memset` because a literal cannot hold a run of spaces whose
    length is not known here, and `str_put` would terminate what it wrote.
    """
    if n > 0:
        memset(buf + u, 32, n)      # spaces
        memset(buf + u + n, 0, 1)
        u = u + n
    return u


def _nl(buf, u):
    """A newline at `buf[u:]`, keeping the buffer terminated. The new `u`."""
    memset(buf + u, 10, 1)      # newline
    memset(buf + u + 1, 0, 1)
    return u + 1


def _positional_section(spec, err, u, helppos):
    """The `positional arguments:` block. The new `u`.

    Nothing at all when there are no positionals: CPython's formatter adds no
    item for an empty group, so the heading never appears.
    """
    n = _nrec(spec)
    first = 1
    i = 0
    while i < n:
        if _isopt(_rec(spec, i)) == 0:
            if first == 1:
                u = _putlit(err, u, "positional arguments:")
                u = _nl(err, u)
                first = 0
            u = _entry(err, u, _invocation(spec, i),
                       _ftext(_rec(spec, i), F_HELP), helppos)
        i = i + 1
    if first == 1:
        return u
    return _nl(err, u)


def _option_section(spec, err, u, helppos):
    """The `options:` block, `-h` first. The new `u`.

    Always present, because CPython's help action is an option and the group it
    belongs to is never empty.
    """
    u = _putlit(err, u, "options:")
    u = _nl(err, u)
    u = _entry(err, u, HELP_INVOCATION, HELP_TEXT, helppos)
    n = _nrec(spec)
    i = 0
    while i < n:
        if _isopt(_rec(spec, i)) == 1:
            u = _entry(err, u, _invocation(spec, i),
                       _ftext(_rec(spec, i), F_HELP), helppos)
        i = i + 1
    return _nl(err, u)


def _help_into(spec, argv, desc, err):
    """The whole help text into `err`. The length written.

    CPython's `format_help`: the usage, the description, `positional arguments:`
    and its entries, `options:` and its entries, each block followed by a blank
    line, and the whole thing ending in exactly one newline — which is what
    `format_help`'s `help.strip(chr(10)) + chr(10)` amounts to. The description
    and every help text are WRAPPED at the width, which is the part this used not
    to do.
    """
    u = _usage_line(spec, argv, err)
    u = _nl(err, u)
    if _has_nonspace(desc) == 1:
        # `_format_text`: the description is `textwrap.fill(text, max(width -
        # current_indent, 11), initial_indent=indent, subsequent_indent=indent)`
        # and `current_indent` is 0 here, so both indents are empty and the
        # width is the full one. A description of nothing but whitespace prints
        # nothing at all, which is what `text.strip()` is asked above.
        # `_wrap_into` ends the last line itself, so this ONE newline is the
        # blank line `_format_text`'s `'\n\n'` leaves after the text.
        u = _wrap_into(err, u, desc, TEXT_WIDTH, "", "", 0)
        u = _nl(err, u)
    helppos = _helppos(spec)
    u = _positional_section(spec, err, u, helppos)
    u = _option_section(spec, err, u, helppos)
    # `format_help` ends with `help.strip(chr(10)) + chr(10)`, so the trailing
    # blank line the last section added is REMOVED. Truncating and not just
    # reporting the shorter length matters: a caller that writes `strlen(err)`
    # — which is the natural thing to do, and what the test's generated program
    # does — would otherwise emit the blank line CPython does not print.
    u = u - 1
    memset(err + u, 0, 1)
    return u


def _compose(spec, argv, msg, err):
    """The usage line, then `prog: error: message`. The length written.

    `ArgumentParser.error` exactly: `print_usage(sys.stderr)` and then
    `'%(prog)s: error: %(message)s'`.
    """
    u = _usage_line(spec, argv, err)
    prog = _basename(argv[0])
    u = str_put(err, u, prog, str_len(prog))
    u = _putlit(err, u, ": error: ")
    u = str_put(err, u, msg, str_len(msg))
    memset(err + u, 10, 1)      # newline
    return u + 1


# ── Does this action hold a list or a single value? ──────────────────────────

def _is_list(rec):
    """1 if action `rec` accumulates values rather than replacing one.

    What decides whether a value is APPENDED to the namespace or SETS it, and
    it is not the action class alone: `nargs="*"` on a positional holds a list
    whatever it does with each value, and `append` holds a list whatever its
    nargs. Getting this wrong is not a small difference — it is `count` on the
    namespace instead of a count — so it is one function both callers ask.
    """
    if _acts(rec) == A_APPEND:
        return 1
    k = _nk(rec)
    if k == N_STAR or k == N_PLUS or k == N_REM:
        return 1
    if k == N_INT and _nint(rec) > 1:
        return 1
    return 0


def _takes_value(rec):
    """1 if action `rec` can be given a value at all.

    `store_true`, `store_false` and `count` are CPython actions with `nargs=0`:
    they take no argument, which is why `-v` needs none and why
    `-vvv` is three of them. Everything else takes one unless its own nargs
    says otherwise.
    """
    a = _acts(rec)
    if a == A_TRUE or a == A_FALSE or a == A_COUNT:
        return 0
    return 1


# ── Consuming one optional ───────────────────────────────────────────────────
#
# CPython's `consume_optional`, as a function of its own. This target has no
# closures and no module state, so this cannot share `parse`'s locals; and it
# cannot be handed a message buffer as well as everything else, because six is
# the smaller of the two ABIs' integer argument registers (`struct.mojo`'s limit
# 2). So it returns a PACKED error and `parse` rebuilds the text.

def _opt_kind(spec, argv, argc, i):
    """The pattern character of `argv[i]`: 79 'O', 45 '-', or 65 'A'.

    The same classification `parse` builds into its pattern array, asked one
    argument at a time. The scan for an earlier `--` is what makes everything
    after it an argument, and `--` itself gets a character of its own because
    CPython's pattern does — a positional's value list can then drop it, which
    is what happens to `['a', '--', 'b']`.
    """
    if i >= argc:
        return PAT_A
    if strncmp(argv[i], "--", 3) == 0:
        return PAT_DASH
    j = 1
    while j < i:
        if strncmp(argv[j], "--", 3) == 0:
            return PAT_A
        j = j + 1
    if _classify(spec, argv[i]) == PAT_O:
        return PAT_O
    return PAT_A


def _err(cls, ai):
    """A packed error: negative, and unpackable as class and action index."""
    return 0 - 1 - cls * 4096 - ai


def _short2(a, p):
    """The two-character option string `-` + `p[0]`, as a fresh buffer.

    CPython's peel builds exactly this (`char + explicit_arg[0]`, where `char`
    is the argument's FIRST character), so `-vq` is `-v` and then `-q`. Looking
    the second one up by the first two bytes of the WHOLE argument finds `-v`
    again, and that is how `-vq` came to record `-v` twice, leave `-q` at its
    default, and turn `-vx` — which must report `unrecognized arguments: -x` —
    into a successful parse.
    """
    d = str_alloc(3)
    u = str_put(d, 0, a, 1)
    u = str_put(d, u, p, 1)
    memset(d + u, 0, 1)
    return d


def _take_opt(spec, argv, argc, start, out, seen):
    """Consume the optional at `argv[start]`, writing its value into `out`.

    Returns the index the walk continues at, or a packed negative error whose
    class is one of the `E_` constants — including `E_HELP`, `E_UNRECOG` and
    `E_EXTRAS`, which are how `-h` and the two kinds of unrecognised argument
    reach `parse`. `seen` is an `na + 2` byte scratch in which a consumed
    action's byte is set to `s`; that is the only thing `required` needs.

    The steps are CPython's, in CPython's order: `_parse_optional`'s resolution
    (exactly, then split at `=`, then a two-byte short option, then a unique
    prefix), then `consume_optional`'s peel of a single-dash argument while the
    options it names take no value, then `match_argument` against the pattern
    that follows, then `_get_values` and `_check_value`.
    """
    na = _nrec(spec)
    arg = argv[start]
    alen = str_len(arg)
    if _is_reserved(arg, alen) == 1:
        return _err(E_HELP, 0)
    eq = strcspn(arg, "=")
    nlen = alen
    if eq < alen:
        nlen = eq
    act = _lookup(spec, arg, nlen)
    expl = 0
    sep = 0
    if act > 0 and eq == alen:
        expl = 0
    if act > 0 and eq < alen:
        expl = arg + eq + 1
        sep = 1
    if act == 0 and _short_exact(spec, arg) == 1:
        act = _lookup(spec, arg, 2)
        expl = arg + 2
        sep = 0
    if act == 0:
        act = _lookup_pfx(spec, arg, nlen)
        if act < 0:
            return _err(E_AMBIG, 0)
    if act == 0:
        return _err(E_UNRECOG, 0)
    ai = act - 1
    rec = _rec(spec, ai)
    name = _dest(spec, ai)
    # The peel loop: each pass consumes one option out of a single-dash
    # argument, either by taking the value that follows or, for an option that
    # takes none, by moving on to the next character.
    while True:
        memset(seen + ai, 115, 1)
        if expl != 0:
            if _takes_value(rec) == 1:
                if _take_value(spec, ai, expl, out) < 0:
                    return _err(E_BADVAL, ai)
                return start + 1
            if sep == 1 or strspn(expl, "-") > 0:
                return _err(E_IGNORED, ai)
            # CPython appends one `(action, [], option_string)` tuple per
            # peeled flag and then `take_action`s each of them, so `-vvv`
            # counts to 3 and not to 1.
            if _take_value(spec, ai, "", out) < 0:
                return _err(E_TOOBIG, ai)
            rest = expl
            expl = expl + 1
            nxt = _lookup(spec, _short2(arg, rest), 2)
            if nxt == 0:
                return _err(E_EXTRAS, rest - arg)
            ai = nxt - 1
            rec = _rec(spec, ai)
            name = _dest(spec, ai)
            if str_len(expl) == 0:
                expl = 0
                sep = 0
            elif strspn(expl, "=") > 0:
                expl = expl + 1
                sep = 1
            else:
                sep = 0
            if expl == 0:
                break
            continue
        break
    if _takes_value(rec) == 0:
        # A flag with no argument still TAKES the action: CPython calls
        # `take_action(action, [])`, so `-q` records True and a third `-v`
        # records 3. Returning without recording would leave `store_true` at
        # its default forever and `count` at 0 no matter how often it was
        # given — a wrong answer with no symptom at all.
        if _take_value(spec, ai, "", out) < 0:
            return _err(E_TOOBIG, ai)
        return start + 1
    got = 0
    i = start + 1
    while i < argc and _opt_kind(spec, argv, argc, i) == PAT_A:
        got = got + 1
        i = i + 1
    k = _nk(rec)
    if k == N_ONE:
        if got < 1:
            return _err(E_EXPECT1, ai)
        if _take_value(spec, ai, argv[start + 1], out) < 0:
            return _err(E_BADVAL, ai)
        return start + 2
    if k == N_OPT:
        if got > 0:
            if _take_value(spec, ai, argv[start + 1], out) < 0:
                return _err(E_BADVAL, ai)
            return start + 2
        _dropf(out, name)
        return start + 1
    if k == N_STAR or k == N_PLUS:
        if got < 1 and k == N_PLUS:
            return _err(E_ATLEAST, ai)
        if _take_list(spec, ai, argv, start + 1, got, out) < 0:
            return _err(E_BADVAL, ai)
        if got == 0 and _flen(rec, F_DEFAULT) == 0:
            if _putf(out, name, 0) < 0:
                return _err(E_TOOBIG, ai)
        return start + 1 + got
    if k == N_REM:
        _take_list(spec, ai, argv, start + 1, argc - start - 1, out)
        return argc
    want = _nint(rec)
    if got < want:
        return _err(E_EXPECTN, ai)
    if _take_list(spec, ai, argv, start + 1, want, out) < 0:
        return _err(E_BADVAL, ai)
    return start + 1 + want


def _take_value(spec, ai, v, out):
    """Convert one value for action `ai` and record it. 0, or -1.

    `_get_value` then `_check_value` then the action. -1 covers both refusals
    and the caller turns it into CPython's `invalid int value` or
    `invalid choice`, which is the right message either way because `_tys` has
    already refused every type but `str` and `int`.
    """
    rec = _rec(spec, ai)
    if _tys(rec) == T_INT:
        if _is_int(v) == 0:
            return 0 - 1
        v = _trim_int(v)
    if _in_choices(rec, v) == 0:
        return 0 - 1
    name = _dest(spec, ai)
    a = _acts(rec)
    if a == A_TRUE:
        return _putset(out, name, "1")
    if a == A_FALSE:
        return _putset(out, name, "0")
    if a == A_COUNT:
        var b: Pointer[UInt8] = str_alloc(24)
        snprintf(b, 24, "%d", get_int(out, name) + 1)
        return _putset(out, name, b)
    if _is_list(rec) == 1:
        return _putf(out, name, v)
    return _putset(out, name, v)


def _take_list(spec, ai, argv, from, got, out):
    """Convert `got` values for action `ai` and record each. 0, or -1."""
    i = 0
    while i < got:
        if _take_value(spec, ai, argv[from + i], out) < 0:
            return 0 - 1
        i = i + 1
    return 0


def _trim_int(s):
    """`s` with CPython's surrounding spaces and an explicit `+` removed.

    `atoi` reads a signed integer with leading spaces and stops at the first
    byte it cannot use, so this only has to drop what would make the CONVERTED
    value differ from the text: the trailing spaces and the `+`, which `atoi`
    accepts and the stored value should not carry.
    """
    n = str_len(s)
    i = 0
    while i < n and strspn(s + i, " ") > 0:
        i = i + 1
    j = n - 1
    while j > i and strspn(s + j, " ") > 0:
        j = j - 1
    if strspn(s + i, "+") > 0:
        i = i + 1
    if i > j:
        return "0"
    return str_prefix(s + i, j - i + 1)


def _putset(out, name, value):
    """Record `value` for `name`, replacing what is there. 0, or -1.

    What CPython's `setattr` does to a namespace attribute, and the difference
    from `_putf` is not cosmetic: a second `-v` on a `store_true` REPLACES the
    value, it does not add a second one, and that is what makes `-vvv` count to
    3 for `action="count"` and to `True` for `store_true`.

    The replacement goes where the first old field was, so the namespace stays
    in DECLARATION order however many times an option is repeated. It is built
    in a scratch and copied back rather than written over the old bytes, because
    the new field can be LONGER than the one it replaces and there is nothing to
    write into past the end of.
    """
    n = str_len(out)
    nf = _nfields(out)
    fi = 0 - 1
    i = 0
    while i < nf:
        p = _fstart(out, i)
        if p == 0:
            break
        if _fname_len(p) == str_len(name) and str_eq_n(
                p, name, str_len(name)) == 1:
            fi = i
            break
        i = i + 1
    nb = str_alloc(BUF_CAP)
    nu = str_put(nb, 0, name, str_len(name))
    if value != 0:
        nu = _putlit(nb, nu, "=")
        nu = str_put(nb, nu, value, str_len(value))
    memset(nb + nu, 0, 1)
    if fi < 0:
        # No field for this name yet: APPEND. Copying `nb` to the FRONT of the
        # buffer instead silently discards every field already written, which
        # is not a crash and not one wrong value — it is a namespace that
        # quietly loses every action declared before this one.
        return _putf(out, name, value)
    tmp = str_alloc(BUF_CAP)
    u = 0
    first = 1
    i = 0
    while i < nf:
        p = _fstart(out, i)
        if p == 0:
            break
        e = strcspn(p, ";")
        if i == fi:
            if first == 0:
                u = _cp(tmp, u, ";", 1)
            u = _cp(tmp, u, nb, nu)
            first = 0
        elif _fname_len(p) != str_len(name) or str_eq_n(
                p, name, str_len(name)) == 0:
            if first == 0:
                u = _cp(tmp, u, ";", 1)
            u = _cp(tmp, u, p, e)
            first = 0
        i = i + 1
    if u + 1 >= BUF_CAP:
        return 0 - 1
    memset(tmp + u, 0, 1)
    memmove(out, tmp, u + 1)
    return 0


def _putlit(buf, u, s):
    """The literal `s` at `buf[u:]`. The new `u`.

    So that no length in this file is spelled by hand. A miscounted length is
    the quietest possible failure — a truncated message, or a message with the
    next piece's bytes in it — and there are enough of them here to be worth a
    helper rather than a review.
    """
    return str_put(buf, u, s, str_len(s))


def _cp(dst, u, src, n):
    """`n` bytes of `src` at `dst[u:]`, NUL-terminated. The new `u`."""
    memmove(dst + u, src, n)
    memset(dst + u + n, 0, 1)
    return u + n


# ── The public surface ───────────────────────────────────────────────────────

def add(spec, record):
    """`spec` with `record` appended as one more action, as a new buffer.

    The way to build a spec without writing one long literal, because string `+`
    is refused on this path (`bugs/FORMAL_string_value_model.md`) — so a caller
    writes `s = argparse.add(s, "--jobs|-j|store|int|||8")` once per action. The
    result is a `malloc`'d buffer the caller owns, like every other string this
    backend's modules return. A `record` containing `;` is returned unchanged:
    it would split one action into two, which is not what the caller asked for.
    """
    if _haschar(record, ";") == 1:
        return spec
    if str_len(spec) == 0:
        return str_dup(record)
    d = str_alloc(str_len(spec) + str_len(record) + 2)
    u = str_put(d, 0, spec, str_len(spec))
    u = _putlit(d, u, ";")
    u = str_put(d, u, record, str_len(record))
    memset(d + u, 0, 1)
    return d


def n_actions(spec):
    """How many actions `spec` declares."""
    return _nrec(spec)


def usage(spec, argv, err):
    """The usage line alone — CPython's `format_usage()`. The length written."""
    n = _usage_line(spec, argv, err)
    memset(err + n, 10, 1)      # newline
    return n + 1


def help_text(spec, argv, desc, err):
    """The full help — CPython's `format_help()`. The length written.

    `desc` is the parser's `description`, which CPython's `ArgumentParser` took
    on the constructor. It is a parameter rather than part of the spec because
    no error path prints it, and putting it in the spec would mean every caller
    had to write an empty field for it.
    """
    return _help_into(spec, argv, desc, err)


def error(spec, argv, msg, err):
    """CPython's `ArgumentParser.error`: the usage line, then the message.

    Returns `ST_ERROR`, which is 2 — the status CPython exits with. The caller
    ends the process with `exit(2)`, the only spelling that works on this target
    (`bugs/FORMAL_known_limits.md` 1.1); this function does not exit because a
    module that ends its caller's process cannot also be tested against CPython.
    """
    _compose(spec, argv, msg, err)
    return ST_ERROR


def parse(spec, argv, argc, out, err, desc):
    """Parse `argv` against `spec`. The status; see the block of `ST_` above.

    `argv[0]` is the program name and is never consumed as an argument, which is
    the one respect in which `argv` differs from what CPython's `parse_args`
    takes: there is no `sys.argv` here to default to
    (`bugs/FORMAL_module_state_no_storage.md`, measurement (4)), and passing the
    whole vector is what lets `prog` be `basename(argv[0])` as it is there.

    `out` and `err` are caller buffers of at least `BUF_CAP` bytes each. `out`
    receives the namespace (see THE RESULT); `err` receives the help text on
    status 1, and the usage line plus the message on status 2.

    The body is CPython's `_parse_known_args` with `consume_positionals`
    inlined, because this target has no closures: the state it shares with
    `consume_optional` — which positional is next, which actions have been seen,
    and the index the walk has reached — is a local of this one function plus
    the `seen` scratch it makes.
    """
    na = _nrec(spec)
    memset(out, 0, BUF_CAP)
    memset(err, 0, BUF_CAP)
    rc = _check(spec, na, err)
    if rc != ST_OK:
        return rc
    if _emit_defaults(spec, out) < 0:
        return _toobig(err)
    pat = str_alloc(argc + 2)
    _build_pat(spec, argv, argc, pat)
    ex = str_alloc(BUF_CAP)
    seen = str_alloc(na + 2)
    pmsg = str_alloc(BUF_CAP)
    pstart = 0
    while pstart < na and _isopt(_rec(spec, pstart)) == 1:
        pstart = pstart + 1
    maxopt = _last_opt(pat, argc)
    start = 1
    while True:
        more = 0
        if start <= maxopt:
            more = 1
        nextopt = argc
        i = start
        while i <= maxopt:
            if strspn(pat + i, "O") > 0:
                nextopt = i
                break
            i = i + 1
        if more == 0 or start != nextopt:
            m = 0
            i = start
            while i < nextopt:
                if strspn(pat + i, "A") > 0:
                    m = m + 1
                i = i + 1
            np = 0
            j = pstart
            while j < na and _isopt(_rec(spec, j)) == 0:
                np = np + 1
                j = j + 1
            k = np
            while k > 0:
                if _split(spec, pstart, k, m) >= 0:
                    break
                k = k - 1
            pe = start
            if k > 0:
                left = m
                j = pstart
                while j < pstart + k:
                    left = left - _take(spec, pstart, k, j, left)
                    j = j + 1
                if left == 0 and nextopt < argc:
                    if strspn(pat + nextopt, "O") > 0:
                        while k > 0:
                            j = pstart + k - 1
                            if _take(spec, pstart, k, j, _avail_at(
                                    spec, pstart, k, j, m)) != 0:
                                break
                            k = k - 1
                used = m - left
                if _nk(_rec(spec, pstart + k - 1)) == N_REM:
                    pe = argc
                else:
                    got = 0
                    pe = start
                    i = start
                    while i < nextopt and got < used:
                        if strspn(pat + i, "A") > 0:
                            got = got + 1
                            pe = i + 1
                        i = i + 1
                j = pstart - 1
                rem = 0
                left = used
                i = start
                alim = pstart + k - 1
                if _nk(_rec(spec, pstart + k - 1)) == N_REM:
                    alim = pstart + k - 2
                while i < nextopt:
                    if strspn(pat + i, "A") == 0:
                        i = i + 1
                        continue
                    while rem == 0 and j < alim:
                        j = j + 1
                        rem = _take(spec, pstart, k, j, left)
                        left = left - rem
                    if rem == 0:
                        break
                    memset(seen + j, 115, 1)
                    if _tys(_rec(spec, j)) == T_INT and _is_int(argv[i]) == 0:
                        _verr(spec, j, argv[i], pmsg)
                        _compose(spec, argv, pmsg, err)
                        return ST_ERROR
                    if _in_choices(_rec(spec, j), argv[i]) == 0:
                        _verr(spec, j, argv[i], pmsg)
                        _compose(spec, argv, pmsg, err)
                        return ST_ERROR
                    if _take_value(spec, j, argv[i], out) < 0:
                        return _toobig(err)
                    rem = rem - 1
                    i = i + 1
                # A REMAINDER positional's pattern is `.*`, which matches
                # every remaining argument INCLUDING the `--` and the ones
                # after it — so it does not consume a run of `A`s, it takes
                # everything from here to the end of `argv`. That is why
                # `["--limit", "2", "--", "ls", "-l"]` leaves the separator in
                # `cmd`, which is CPython's answer and the reason this is a
                # separate loop rather than the one above.
                rr = pstart + k - 1
                if _nk(_rec(spec, rr)) == N_REM:
                    if j < pstart:
                        i = start
                    memset(seen + rr, 115, 1)
                    while i < argc:
                        if _tys(_rec(spec, rr)) == T_INT and _is_int(argv[i]) == 0:
                            _verr(spec, rr, argv[i], pmsg)
                            _compose(spec, argv, pmsg, err)
                            return ST_ERROR
                        if _take_value(spec, rr, argv[i], out) < 0:
                            return _toobig(err)
                        i = i + 1
                # A `*` or REMAINDER positional that was given NOTHING is `[]`
                # and not None — `_get_values`' second arm — so it gets the
                # bare-name shape. A `?` gets its default and no field, which
                # is why the test is on the nargs and not on "no values".
                jj = pstart
                while jj < pstart + k:
                    if _nk(_rec(spec, jj)) == N_STAR or _nk(
                            _rec(spec, jj)) == N_REM:
                        if _has(out, _dest(spec, jj)) == 0:
                            memset(seen + jj, 115, 1)
                            _putf(out, _dest(spec, jj), 0)
                    jj = jj + 1
                pstart = pstart + k
            if more == 1 and pe > start:
                start = pe
                continue
            start = pe
            if more == 0:
                i = pe
                while i < argc:
                    _exadd(ex, argv[i])
                    i = i + 1
                break
        if strspn(pat + start, "O") == 0:
            i = start
            while i < nextopt:
                _exadd(ex, argv[i])
                i = i + 1
            start = nextopt
        st = _take_opt(spec, argv, argc, start, out, seen)
        if st < 0:
            c = _errcls(st)
            ai = _errai(st)
            if c == E_HELP:
                _help_into(spec, argv, desc, err)
                return ST_HELP
            if c == E_UNRECOG:
                _exadd(ex, argv[start])
                start = start + 1
                continue
            if c == E_EXTRAS:
                _exadd(ex, _dash_rest(argv[start], ai))
                start = start + 1
                continue
            _opt_error(spec, argv[start], _badval(spec, argv, argc, start),
                        ai, c, pmsg)
            _compose(spec, argv, pmsg, err)
            return ST_ERROR
        start = st
    if _required_error(spec, na, seen, pmsg) == 1:
        _compose(spec, argv, pmsg, err)
        return ST_ERROR
    if str_len(ex) > 0:
        memset(pmsg, 0, BUF_CAP)
        u = _putlit(pmsg, 0, "unrecognized arguments: ")
        u = str_put(pmsg, u, ex, str_len(ex))
        memset(pmsg + u, 0, 1)
        _compose(spec, argv, pmsg, err)
        return ST_ERROR
    if _reorder(spec, na, out) < 0:
        return _toobig(err)
    return ST_OK


def _build_pat(spec, argv, argc, pat):
    """Classify every argument string into `pat`, one byte each. 0.

    CPython's `_parse_known_args` first pass, and reproducing its RESULTS means
    reproducing this: 'O' where `_parse_optional` returns an optional, 'A' where
    it returns None, and '-' for the `--` that ends option parsing. `dseen` is
    checked FIRST, so everything after a `--` is an argument whatever it looks
    like — `-- -x` is a positional and not an unrecognised option, which is the
    whole point of the separator.
    """
    i = 1
    dseen = 0
    while i < argc:
        if dseen == 1:
            memset(pat + i, PAT_A, 1)
        elif strncmp(argv[i], "--", 3) == 0:
            memset(pat + i, PAT_DASH, 1)
            dseen = 1
        else:
            memset(pat + i, _classify(spec, argv[i]), 1)
        i = i + 1
    memset(pat + argc, 0, 1)
    return 0


def _last_opt(pat, argc):
    """The index of the LAST optional in `pat`, or -1 if there is none.

    `max_option_string_index` from CPython's walk, which is what decides
    whether the walk has an optional left to consume before the final
    `consume_positionals`.
    """
    m = 0 - 1
    i = 1
    while i < argc:
        if strspn(pat + i, "O") > 0:
            m = i
        i = i + 1
    return m


def _reorder(spec, na, out):
    """Rewrite the namespace in DECLARATION order. 0, or -1 if it will not fit.

    CPython's namespace has its keys in the order the actions were DECLARED —
    `parse_known_args` sets every action's default before it reads the command
    line, and a later assignment to an existing key keeps its position — while
    this module writes a field when the VALUE arrives, and for a positional that
    is after every option whatever the declaration order says. One pass at the
    end puts the fields where CPython would have them, and it is the only place
    that knows both the declaration order and where each value ended up.

    Every field in the buffer is named after a declared dest, so nothing is
    dropped by this; the `seen` order is not affected, because `get`, `count`
    and `has` all ask by name.
    """
    tmp = str_alloc(BUF_CAP)
    u = 0
    first = 1
    i = 0
    while i < na:
        d = _dest(spec, i)
        j = 0
        f = _nfields(out)
        while j < f:
            p = _fstart(out, j)
            if p == 0:
                break
            if _fname_len(p) == str_len(d) and str_eq_n(
                    p, d, str_len(d)) == 1:
                if first == 0:
                    u = _cp(tmp, u, ";", 1)
                u = _cp(tmp, u, p, strcspn(p, ";"))
                first = 0
            j = j + 1
        i = i + 1
    if u + 1 >= BUF_CAP:
        return 0 - 1
    memset(tmp + u, 0, 1)
    memmove(out, tmp, u + 1)
    return 0


def _errcls(st):
    """The error class of a packed negative return from `_take_opt`."""
    return (0 - 1 - st) / 4096


def _errai(st):
    """The action index of a packed negative return from `_take_opt`."""
    c = _errcls(st)
    return (0 - 1 - st) - c * 4096


def _avail_at(spec, p, k, j, m):
    """How many arguments are left when the slice reaches positional `j`."""
    left = m
    i = p
    while i < j:
        left = left - _take(spec, p, k, i, left)
        i = i + 1
    return left


def _quote_choices(rec, buf, u):
    """`rec`'s choices as CPython's message spells them: `'a', 'b'`.

    `_check_value` builds the list with `', '.join(repr(str(choice)) …)`, so
    each choice carries its own quotes — which is why `(choose from a, b)` is
    not the message and `(choose from 'a', 'b')` is.
    """
    p = _fld(rec, F_CHOICES)
    end = _fend(p)
    first = 1
    i = 0
    while i < end:
        j = _esc_end(p + i, "\\,|;")
        if first == 0:
            u = _putlit(buf, u, ", ")
        u = _putlit(buf, u, "'")
        u = _unesc_upto(buf, u, p + i, j)
        u = _putlit(buf, u, "'")
        first = 0
        i = i + j + 1
    return u


def _verr(spec, j, v, msg):
    """A positional's value error, in CPython's wording."""
    memset(msg, 0, BUF_CAP)
    u = _putlit(msg, 0, "argument ")
    n = _action_name(spec, j)
    u = str_put(msg, u, n, str_len(n))
    u = _putlit(msg, u, ": ")
    rec = _rec(spec, j)
    if _tys(rec) == T_INT:
        u = _putlit(msg, u, "invalid int value: '")
    else:
        u = _putlit(msg, u, "invalid choice: '")
    u = str_put(msg, u, v, str_len(v))
    if _tys(rec) == T_INT:
        u = _putlit(msg, u, "'")
    else:
        u = _putlit(msg, u, "' (choose from ")
        u = _quote_choices(rec, msg, u)
        u = _putlit(msg, u, ")")
    memset(msg + u, 0, 1)
    return 0


def _dash_rest(arg, off):
    """`-` followed by `arg[off:]` — CPython's `char + explicit_arg` extra."""
    d = str_alloc(str_len(arg) - off + 2)
    u = _putlit(d, 0, "-")
    u = str_put(d, u, arg + off, str_len(arg) - off)
    memset(d + u, 0, 1)
    return d


def _exadd(ex, v):
    """Append `v` to the extras list in `ex`, space separated."""
    u = str_len(ex)
    if u > 0:
        memset(ex + u, 32, 1)      # ' '
        memset(ex + u + 1, 0, 1)
        u = u + 1
    str_put(ex, u, v, str_len(v))
    return 0


def _check(spec, na, err):
    """Refuse a spec this module cannot honour. `ST_OK`, or the status.

    Four refusals, and each is a fact about this target rather than about
    argparse: a `float` type (a value here is one integer word), a `type` or
    `nargs` outside this subset's spellings, and a declaration of `-h`/`--help`,
    which this module adds itself and which CPython reports as a conflicting
    option string.
    """
    i = 0
    while i < na:
        rec = _rec(spec, i)
        t = _tys(rec)
        if t == T_FLOAT:
            _refuse(err, "type=float is not available on this target: a value "
                      "is one 64-bit integer word, so a float would be "
                      "silently truncated. See formal/model.py's "
                      "_FLOAT_SCALARS.")
            return ST_UNSUPPORTED
        if t == T_BAD:
            _refuse(err, "type must be str or int")
            return ST_UNSUPPORTED
        if _nk(rec) < 0:
            _refuse(err, "nargs must be empty, ?, *, +, R or a count")
            return ST_UNSUPPORTED
        if _isopt(rec) == 1:
            k = 0
            while k < _nname(rec):
                if _is_reserved(_name_ptr(rec, k), _name_len(rec, k)) == 1:
                    _refuse(err, "conflicting option string: this module adds "
                              "-h/--help itself")
                    return ST_UNSUPPORTED
                k = k + 1
        i = i + 1
    return ST_OK


def _refuse(err, msg):
    """Put a module-level refusal message into `err`."""
    memset(err, 0, BUF_CAP)
    u = str_put(err, 0, msg, str_len(msg))
    memset(err + u, 0, 1)
    return 0


def _toobig(err):
    """The message and status for a result that does not fit `BUF_CAP`."""
    _refuse(err, "the result does not fit in the caller's buffer "
                 "(argparse.BUF_CAP bytes)")
    return ST_TOOBIG


def _required_error(spec, na, seen, msg):
    """1 if a required action was never seen, with CPython's message in `msg`.

    `the following arguments are required: --side, --key` — every missing one,
    in declaration order, joined with `, `, each named the way
    `_get_action_name` names it.
    """
    first = 1
    u = 0
    memset(msg, 0, BUF_CAP)
    i = 0
    while i < na:
        if _required(spec, i) == 1 and strspn(seen + i, "s") == 0:
            if first == 1:
                u = _putlit(msg, 0, "the following arguments are required: ")
                first = 0
            else:
                u = _putlit(msg, u, ", ")
            n = _action_name(spec, i)
            u = str_put(msg, u, n, str_len(n))
        i = i + 1
    if first == 1:
        return 0
    memset(msg + u, 0, 1)
    return 1


def _opt_error(spec, arg, v, ai, cls, msg):
    """CPython's `ArgumentError` message for one optional. Writes `msg`.

    Rebuilt here rather than returned by `_take_opt`, which cannot be handed a
    message buffer as well as its six arguments: six is the smaller of the two
    ABIs' integer argument registers, and a seventh would build on arm64 and be
    REFUSED on x86-64 (`struct.mojo`'s limit 2, measured). `arg` is `argv[start]`
    and `v` the argument string the error is about, which is the explicit
    `=value` tail of `arg` or the argument after it.
    """
    memset(msg, 0, BUF_CAP)
    u = 0
    if cls == E_AMBIG:
        u = _putlit(msg, 0, "ambiguous option: ")
        u = str_put(msg, u, arg, str_len(arg))
        u = _putlit(msg, u, " could match ")
        u = _matches(msg, u, spec, arg, str_len(arg))
        memset(msg + u, 0, 1)
        return 0
    n = _action_name(spec, ai)
    u = _putlit(msg, 0, "argument ")
    u = str_put(msg, u, n, str_len(n))
    u = _putlit(msg, u, ": ")
    if cls == E_EXPECT1:
        u = _putlit(msg, u, "expected one argument")
    if cls == E_ATMOST:
        u = _putlit(msg, u, "expected at most one argument")
    if cls == E_ATLEAST:
        u = _putlit(msg, u, "expected at least one argument")
    if cls == E_EXPECTN:
        want = _nint(_rec(spec, ai))
        var b: Pointer[UInt8] = str_alloc(24)
        snprintf(b, 24, "%d", want)
        u = _putlit(msg, u, "expected ")
        u = str_put(msg, u, b, str_len(b))
        u = _putlit(msg, u, " argument")
        if want != 1:
            u = _putlit(msg, u, "s")
    if cls == E_BADVAL:
        u = _putlit(msg, u, "invalid ")
        if _tys(_rec(spec, ai)) == T_INT:
            u = _putlit(msg, u, "int value: '")
        else:
            u = _putlit(msg, u, "choice: '")
        u = str_put(msg, u, v, str_len(v))
        if _tys(_rec(spec, ai)) == T_INT:
            u = _putlit(msg, u, "'")
        else:
            u = _putlit(msg, u, "' (choose from ")
            u = _quote_choices(_rec(spec, ai), msg, u)
            u = _putlit(msg, u, ")")
    if cls == E_IGNORED:
        u = _putlit(msg, u, "ignored explicit argument '")
        eq = strcspn(arg, "=")
        w = arg + eq + 1
        u = str_put(msg, u, w, str_len(w))
        u = _putlit(msg, u, "'")
    memset(msg + u, 0, 1)
    return 0


def _badval(spec, argv, argc, start):
    """The argument string an optional's value error is about.

    Three shapes, and CPython reports the string it VALIDATED in each: the tail
    after an `=`, the tail of an attached single-dash value (`-jq`, whose value
    is `q` and not the `4` that follows it), or the argument after it, which is
    where a separate value is. `_get_values` is reached with `explicit_arg`
    already split off, so the message names that and not whatever is next.
    """
    a = argv[start]
    eq = strcspn(a, "=")
    if eq < str_len(a):
        return a + eq + 1
    if str_len(a) > 2 and _short_exact(spec, a) == 1:
        return a + 2
    if start + 1 < argc:
        return argv[start + 1]
    return ""


def _matches(msg, u, spec, name, nlen):
    """The comma-joined option strings `name` prefixes. The new `u`.

    CPython's ambiguous-option message lists every match, so the list is built
    rather than the first one reported.
    """
    na = _nrec(spec)
    first = 1
    i = 0
    while i < na:
        if _isopt(_rec(spec, i)) == 1:
            k = 0
            while k < _nname(_rec(spec, i)):
                m = _name_len(_rec(spec, i), k)
                if m >= nlen and str_eq_n(_name_ptr(_rec(spec, i), k),
                                          name, nlen) == 1:
                    if first == 0:
                        u = _putlit(msg, u, ", ")
                    u = str_put(msg, u, _name_ptr(_rec(spec, i), k), m)
                    first = 0
                k = k + 1
        i = i + 1
    return u
