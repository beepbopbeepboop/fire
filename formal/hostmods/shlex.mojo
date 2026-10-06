"""`shlex.quote` — the one pure function of CPython's `shlex`, for this path.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name in
a search root and that wins outright over the host-module list, so this file is
what `import shlex` binds to. `shlex` leaves `HOST_UNREACHABLE` when it lands,
by the rule that set is documented with: a name LEAVES by being written, and an
entry left behind would refuse a file after the module that answers it is
sitting in the tree — a false statement rather than a conservative one.

WHY THIS ONE, AND WHY IT IS THE CHEAPEST ROW IN THE CENSUS
----------------------------------------------------------
`tools/formal_sweep_causes.py --host` ranks the host-import rows by files
blocked, and after `glob` landed this was the top of what was left that is both
unclaimed and reachable: **one file**, `tools/suite.py`, which spells
`shlex.quote` three times (`tools/suite.py:3524`, `:4525`, `:4526`) and
`test_suite.py` twice more against the same helper. One file is a small win and
that is the honest number — the value of writing it is that the row is then
CLOSED rather than open, and this module has no dependency on anything.

WHAT IS HERE, AND WHY THESE TWO
-------------------------------
CPython's `shlex` is a state machine over a stream plus four pure helpers. The
pure helpers are this module; the reader is not, and `formal/imports.py`'s entry
for `shlex` already says why (`shlex.shlex` is a GENERATOR over `readline`,
which is the `fnmatch.iglob` shape, so it is not in reach by the same argument).

    quote   x3 call sites, all in `tools/suite.py`, all formatting a SHELL line
    split   pure too, and see below

`split` is NOT here, for the reason `textwrap.mojo` gives for `wrap`: it returns
a LIST of strings, and a list on this path lives in the frame of the function
that made it and cannot cross a dylib boundary
(`bugs/FORMAL_listdir_no_run_time_sequence.md`). Nothing in this repository calls
it, so a module that exported it would advertise a name whose answer does not
survive the boundary — the same trap `textwrap.mojo` names for
`fnmatch.filter`.

A transcription of it WAS here first, as a module-private `_split`, on the
reasoning that `test_formal_shlex.py` needs a reader for `quote`'s output. That
was wrong and the test found it: **a private name is not exported**, so the
group that called it was refused with the export rule's own sentence, and the
function had no caller in the tree. The round trip is checked without it —
`test_formal_shlex.py`'s `roundtrip` group hands the module's answer to
**CPython's own `shlex.split`** and requires the input back, which is a stronger
oracle than a second transcription of the same function in the same tree could
be. The lesson is the one `formal/imports.py` states for `HOST_MODELLED`: a name
that cannot be reached from a caller is not a capability, it is a comment.

  * `join` — `" ".join(map(quote, argv))`, so it is a generator AND a list, two
    of the three words this path does not have. Absent.
  * `shlex` — the class, a configured parser with instance state. Absent for
    `textwrap.TextWrapper`'s reason (`formal/model.py`;
    `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`).
  * `split` (the public name) — absent, above.

THE ALGORITHM, AND THE THREE THINGS IN IT THAT ARE LOAD-BEARING
---------------------------------------------------------------
CPython 3.14's `shlex.quote` is not the older `_find_unsafe` scan; it is a
`bytes.translate` over a SAFE SET with a fast path, and the two halves behave
differently in three ways that a transcription has to keep apart:

    def quote(s):
        if not s:
            return "''"
        safe_chars = (b'%+,-./0123456789:=@'
                      b'ABCDEFGHIJKLMNOPQRSTUVWXYZ_'
                      b'abcdefghijklmnopqrstuvwxyz')
        if s.isascii() and not s.encode().translate(None, delete=safe_chars):
            return s
        return "'" + s.replace("'", "'\"'\"'") + "'"

1. **THE EMPTY STRING IS ITS OWN CASE**, and it is `''` — the two-character
   string of two apostrophes — not the empty string. `if not s: return "''"`
   fires before the safe-set walk, so `quote("")` never reaches the second half.
   A transcription that folded the empty string into "every byte is safe" would
   answer `""`, which is a shell syntax error rather than an empty argument.

2. **THE FAST PATH RETURNS THE INPUT UNCHANGED, and the slow path WRAPS.**
   There is no "strip the unsafe bytes" step anywhere in this function; a byte
   that is not in the set causes the WHOLE string to be single-quoted, and a
   byte ≥ 0x80 is never in the set. So the decision is a scan for "is every byte
   safe", and the answer is either the input or the quoted form. `s.isascii()`
   is redundant with the set — every non-ASCII byte is outside it, so the
   encoding's high bytes fail the walk anyway — and it is dropped here for that
   reason rather than kept as a second test that could disagree with the first.

3. **`'` INSIDE THE STRING BECOMES THE FIVE BYTES `'"'"'`,** so a string that
   already contains an apostrophe does not end its own quoting. `quote("a'b")`
   is the nine-byte `'a'"'"'b'`, and that is the case every transcription of this
   function gets wrong, because the obvious spelling — replacing `'` with `\'` —
   is not a shell escape at all: inside single quotes a backslash is a literal
   backslash, so the answer would be `a\'b` and the shell would pass
   `a\` and `b` as two arguments.

WHAT IS SAFE, EXACTLY
--------------------
The set is a byte set and it is written out in `_is_safe` rather than built with
`memset`, because it is four CONTIGUOUS RUNS and one literal, and a `memset`
per run would be four calls to spell one comparison:

    %  +  ,  -  .  /        0x25, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F
    0-9                   0x30..0x39
    :  =  @                0x3A, 0x3D, 0x40
    A-Z                   0x41..0x5A
    _                     0x5F
    a-z                   0x61..0x7A

and, because it is a byte walk, everything above 0x7A is unsafe INCLUDING
`{ | } ~` (0x7B, 0x7C, 0x7D, 0x7E) and every byte of a UTF-8 sequence.
`test_formal_shlex.py` sweeps all 256 byte values through both spellings, which
is the check that catches a set built from the memorable half of it — `#`, `!`,
`$`, `&`, `*`, `;`, `<`, `>`, `?`, `[`, `]`, `^`, `` ` ``, `{`, `|`, `}`, `~` and
the space are all UNSAFE and all of them are in the corpus for exactly that
reason.

A STRING ON THIS PATH IS BYTES, and that is not a difference here. CPython's `s`
is a decoded `str` and its `.isascii()` asks about CODE POINTS; here `s` is a
NUL-terminated `char *` and the walk asks about BYTES. The two agree on the
answer for every input, and the reason is that the safe set is ASCII-only: a
non-ASCII code point encodes to at least one byte ≥ 0x80, every such byte is
outside the set, and so both spellings quote. The two would differ only if the
set contained a high byte, which it cannot.
"""

from os._syscalls import str_alloc, str_put, str_len, str_prefix


def _is_safe(c) -> int:
    """1 if byte `c` is in CPython's `safe_chars` set, else 0.

    The four contiguous runs and the five singletons of the module docstring's
    table, and nothing else. `>` and `<` are deliberately absent (0x3E and 0x3C
    fall between `=` and `@`), as are `` ` ``, `~`, `{`, `|`, `}` and the space.
    """
    if c >= 48 and c <= 57:        # 0-9
        return 1
    if c >= 97 and c <= 122:       # a-z
        return 1
    if c >= 65 and c <= 90:        # A-Z
        return 1
    if c == 37 or c == 43 or c == 44 or c == 45 or c == 46 or c == 47:
        return 1                    # % + , - . /
    if c == 58 or c == 61 or c == 64:
        return 1                    # : = @
    if c == 95:                    # _
        return 1
    return 0


def _all_safe(s, n) -> int:
    """1 if all `n` bytes of `s` are safe, else 0. The fast path's whole test."""
    var i = 0
    while i < n:
        var p: Pointer[UInt8] = s + i
        if _is_safe(p.value()) == 0:
            return 0
        i = i + 1
    return 1


def quote(s) -> str:
    """`shlex.quote(s)`: `s` as ONE shell word, or `s` itself if it needs none.

    CPython's body is in the module docstring and the three load-bearing parts
    of it are named there; the shape here is the same three steps in the same
    order, because the ORDER is what makes the empty string land on `''` rather
    than on the fast path and what keeps a high byte from being "almost safe".

    Returns a fresh buffer the caller owns, like every function in this tree —
    including on the FAST path, where CPython returns `s` itself. That is a
    deliberate difference and it is not observable through the ABI: a caller
    here formats the answer into a log line or a command string and never
    mutates it, and returning the caller's own buffer would let a future caller
    that DOES mutate it corrupt the string it passed in. `test_formal_shlex.py`
    checks the answers, not the pointer.
    """
    n = str_len(s)
    # Case 1: the empty string. CPython's `if not s: return "''"` is before the
    # safe-set walk, and an empty string passes every byte test there, so this
    # branch is the only thing standing between `quote("")` and `""` — which is
    # a shell SYNTAX ERROR, not an empty argument.
    if n == 0:
        return "''"
    # Case 2: every byte safe, so the string is already one shell word. The
    # answer is a copy rather than `s`; see the docstring.
    if _all_safe(s, n) == 1:
        return str_prefix(s, n)
    # Case 3: wrap in single quotes and expand every apostrophe. The worst case
    # is 5 bytes per input byte (an apostrophe becomes five) plus the two
    # wrapping quotes, so `5 * n + 2` is the bound and not an estimate.
    out = str_alloc(5 * n + 2)
    var used = 0
    used = str_put(out, used, "'", 1)
    var i = 0
    while i < n:
        var p: Pointer[UInt8] = s + i
        if p.value() == 39:         # `'` -> `'"'"'`
            used = str_put(out, used, "'\"'\"'", 5)
        else:
            # EVERY OTHER BYTE, copied through — which is what keeps a UTF-8
            # sequence intact inside the quotes, since no byte of one is `'`.
            used = str_put(out, used, s + i, 1)
        i = i + 1
    used = str_put(out, used, "'", 1)
    memset(out + used, 0, 1)
    return out
