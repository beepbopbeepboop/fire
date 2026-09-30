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

`R` is `nargs=REMAINDER`. A `;` or `|` in help text or in a choice is not
expressible; a VALUE containing `;` is refused rather than written, because a
value that quietly split a field would be a wrong answer with nothing left to
detect it. `add(spec, record)` appends one record and returns a new spec, which
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
  * **ARM64 ONLY TODAY, and not because of anything in this source.** This
    module calls the C library (`malloc`, `strlen`, `memcmp`, `snprintf`), and
    a module dylib that makes a call into it builds and RUNS with
    `--backend=arm64` while the loader refuses the same image under
    `--backend=x86_64` on this host with ``main executable failed strict
    validation``. Measured on the two-line program above, and it is the same
    defect `formal/hostmods/os/__init__.mojo` records at the top of its own
    docstring — filed as
    `bugs/FORMAL_x86_64_dylib_with_an_extern_call_does_not_load.md`.
    `test_formal_argparse.py` builds arm64 for the same reason
    `test_formal_sys.py` does.
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
  * **HELP TEXT IS NOT WRAPPED AND A LONG USAGE LINE IS NOT FOLDED.**
    `help_text` reproduces CPython's layout — usage, blank, description, blank,
    `positional arguments:`, the positionals two-column, blank, `options:`,
    the options two-column — at the width 78 that
    `shutil.get_terminal_size().columns - 2` gives when `COLUMNS` is unset and
    stdout is not a terminal. Nothing is wrapped, because the width cannot be
    ASKED for: a terminal is a host object (`shutil` and
    `os.get_terminal_size` are in HOST_UNREACHABLE), so 78 is the only width
    this target can know. A parser whose usage line is longer than that gets it
    on one line where CPython would fold it; filed as
    `bugs/FORMAL_argparse_help_wrapping_not_implemented.md`.

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
# needs a bound both ends of the call can agree on. A module constant is the
# only such bound: a default argument is a bound only the callee's own file
# knows, and a caller in another image has to be able to READ the bound to
# agree on it — which is what `BUF_CAP` being spelled here, and the same value
# on both sides of the call, buys. A default argument used not to be applied
# across the boundary at all (`FORMAL_default_argument_not_applied_across_a_dylib`,
# fixed; its doc is deleted, as a fixed bug's is), but the reason to keep the
# constant is that both ends must AGREE, not that one of them can guess.

BUF_CAP = 8192

# ── separators, as BYTES and not as spellings ────────────────────────────────
#
# A string literal on this path is interned verbatim and its escapes are NOT
# unescaped — measured: `"a\nb"` is four bytes, and `sys.mojo` says so at its
# writers — so a newline cannot be written as a literal and every separator
# below is a byte value written with `memset`/`memmove`.

# A BYTE WRITTEN WITH `memset` IS SPELLED INLINE, and these names are only for
# the places module-constant folding does reach (a call argument, a return). The
# reason is measured and it is not a subtlety: `memset(pat + i, PAT_DASH, 1)`
# is REFUSED with "'PAT_DASH' has no home: the register allocator collected no
# home for it, so the emitter and the allocation walk disagree about this
# function's locals", while the identical call with `45` written inline builds
# and runs. A name that reads well is not worth a build that does not compile,
# and every separator below is named in a comment at each use.
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

def _rec(spec, i):
    """Pointer to record `i` of `spec`, or 0 if there is no such record."""
    p = spec
    k = 0
    while k < i:
        q = strchr(p, SEP_FIELD)
        if q == 0:
            return 0
        p = q + 1
        k = k + 1
    return p


def _nrec(spec):
    """How many records `spec` holds. An empty spec is one (empty) record."""
    n = 1
    i = 0
    while i < str_len(spec):
        if strspn(spec + i, ";") > 0:
            n = n + 1
        i = i + 1
    return n


def _fld(rec, f):
    """Pointer to field `f` of `rec`, or 0 if the record ended first.

    The delimiter has to be FOUND before it can be recognised: `strspn` asks
    whether a byte at a pointer is one of a set, and the first byte of a field
    is almost never a `|`. So each step measures the run up to the next
    delimiter and then asks whether the byte there is the field separator.
    """
    p = rec
    k = 0
    while k < f:
        d = strcspn(p, "|;")
        if strspn(p + d, "|") == 0:
            return 0                    # ';' or NUL: no such field
        k = k + 1
        p = p + d + 1
    return p


def _flen(rec, f):
    """Length of field `f`, or 0 when there is no such field."""
    p = _fld(rec, f)
    if p == 0:
        return 0
    return strcspn(p, "|;")


def _feq(rec, f, s):
    """1 if field `f` is exactly the literal `s`."""
    p = _fld(rec, f)
    if p == 0:
        return 0
    n = strcspn(p, "|;")
    if n != str_len(s):
        return 0
    return str_eq_n(p, s, n)


def _ftext(rec, f):
    """Field `f` as a NUL-terminated buffer the caller owns; "" if absent."""
    p = _fld(rec, f)
    if p == 0:
        return ""
    return str_prefix(p, strcspn(p, "|;"))


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
    end = strcspn(p, "|;")
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
    end = strcspn(p, "|;")
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


def _name_len(rec, k):
    """Length of the k-th name of `rec`.

    Stops at a space (names are space separated) or at the end of the field.
    Both are found with `strspn`, so no byte is ever loaded by subscript.
    """
    p = _name_ptr(rec, k)
    if p == 0:
        return 0
    start = _fld(rec, F_NAMES)
    lim = strcspn(start, "|;") - (p - start)
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
    end = strcspn(p, "|;")
    i = 0
    while i < end:
        j = strcspn(p + i, ",|;")
        if j == str_len(v) and str_eq_n(p + i, v, j) == 1:
            return 1
        i = i + j + 1
    return 0


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


def _fname_len(p):
    """Length of field `p`'s NAME: up to `=` or `;`, whichever comes first."""
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


def _parts_into(spec, buf):
    """Every action's usage part into `buf`, a single space between them.

    Optionals in declaration order and then positionals in declaration order:
    CPython's `_get_actions_usage_parts`, and the order is visible in every
    usage line. `-h` comes first, because CPython's help action is the first
    action it adds.
    """
    na = _nrec(spec)
    d = str_alloc(BUF_CAP)
    u = _putlit(d, 0, "[-h]")
    i = 0
    while i < na:
        if _isopt(_rec(spec, i)) == 1:
            p = _usage_part(spec, i)
            u = _putlit(d, u, " ")
            u = str_put(d, u, p, str_len(p))
        i = i + 1
    i = 0
    while i < na:
        if _isopt(_rec(spec, i)) == 0:
            p = _usage_part(spec, i)
            u = _putlit(d, u, " ")
            u = str_put(d, u, p, str_len(p))
        i = i + 1
    memset(d + u, 0, 1)
    memmove(buf, d, u + 1)
    return 0


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
    """`usage: prog <parts>` into `err`. The length written.

    `_format_usage` for the case where the result fits the width, which is the
    case for every parser in the corpus this module was measured against.
    """
    pb = str_alloc(BUF_CAP)
    _parts_into(spec, pb)
    prog = _basename(argv[0])
    u = _putlit(err, 0, "usage: ")
    u = str_put(err, u, prog, str_len(prog))
    u = _putlit(err, u, " ")
    u = str_put(err, u, pb, str_len(pb))
    memset(err + u, 10, 1)      # newline
    return u + 1


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
    """One `  invocation   help` line of the help listing. The new length.

    `_format_action`'s three cases: a short invocation is padded out to the help
    column and its help follows on the same line; a long one is printed on its
    own and the help is indented under it; and an action with no help text is
    the invocation and nothing else.
    """
    if str_len(h) == 0:
        u = _putlit(err, u, "  ")
        u = str_put(err, u, inv, str_len(inv))
        return _nl(err, u)
    width = helppos - 4
    if str_len(inv) <= width:
        u = _putlit(err, u, "  ")
        u = str_put(err, u, inv, str_len(inv))
        u = _pad(err, u, width - str_len(inv))
        u = _putlit(err, u, "  ")
        u = str_put(err, u, h, str_len(h))
        return _nl(err, u)
    u = _putlit(err, u, "  ")
    u = str_put(err, u, inv, str_len(inv))
    u = _nl(err, u)
    u = _pad(err, u, helppos)
    u = str_put(err, u, h, str_len(h))
    return _nl(err, u)


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

    CPython's `format_help` for a parser whose entries and description fit the
    width: the usage, the description, `positional arguments:` and its entries,
    `options:` and its entries, each block followed by a blank line, and the
    whole thing ending in exactly one newline — which is what `format_help`'s
    `help.strip(chr(10)) + chr(10)` amounts to.
    """
    u = _usage_line(spec, argv, err)
    u = _nl(err, u)
    if str_len(desc) > 0:
        u = str_put(err, u, desc, str_len(desc))
        u = _nl(err, u)
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
            memset(pat + i, 65, 1)      # 'A'
        elif strncmp(argv[i], "--", 3) == 0:
            memset(pat + i, 45, 1)
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
    end = strcspn(p, "|;")
    first = 1
    i = 0
    while i < end:
        j = strcspn(p + i, ",|;")
        if first == 0:
            u = _putlit(buf, u, ", ")
        u = _putlit(buf, u, "'")
        u = str_put(buf, u, p + i, j)
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
