"""`re` — regular expressions, for the formal backends.

A backtracking regular-expression engine written in the subset of this
language the formal backends can lower, and the reasons it is shaped the way
it is are all measurements from this tree (2026-09-29, the `module:re` claim).

WHAT THIS IS FOR
----------------
`tools/formal_sweep.py` reported THIRTEEN files as `not-answerable/host-import`
on `re` alone, and six more through `fire_compiler.py`, which imports it. Every
one of them is a file this backend is asked to compile, so the count is a
measure of the module's absence rather than of a target limit: pattern matching
is pure computation over values this path already represents. That is what
makes this file possible, and it is why `re` in `formal/imports.py`'s
HOST_MODELLED was a lie and no longer is.

THE SUBSET, AND WHY IT IS THE SUBSET THE CORPUS USES
-----------------------------------------------------
`regex_compile.py` is this repository's regex compiler for the gimple
`runtime/fire_runtime.c` path, and its own docstring states the scope it was
written for: literals, `.`, classes with ranges and negation, the `\d \s \w`
shorthands and their negations, alternation, capturing / non-capturing /
named groups, and `* + ? {m,n}` in greedy and lazy form. Grepping how the
thirteen sweep files and `fire_compiler.py` actually spell their patterns
gives the same answer, plus four things `regex_compile.py` does not have:

  * `\\b` — `elaborate.py`, `reflect.py`, `consolidate_string_pool.py`;
  * `^` and `$` with `re.MULTILINE` — `reflect.py`'s `_PROTO_RE`;
  * `re.DOTALL` — `reflect.py`'s `_COMMENT_RE`, `spec_gen.py`;
  * `(?P<name>...)` with `m.group('name')` — `reflect.py`.

So this is `regex_compile.py`'s node set ported to a form this path can
execute, plus those four. It is a backtracker over a compiled node array, not
the C-runtime instruction set `regex_compile.py` emits, because the execution
here is Mojo compiled to machine code and the C interpreter does not exist.

WHAT IS NOT HERE, AND THE REASON IS THE SAME FOR ALL OF IT
----------------------------------------------------------
  * **Lookaround and backreferences.** `(?=`, `(?!`, `(?<=`, `(?P=name)`. They
    need the engine to hold a set of positions, and the only place this path
    can put one is a heap block this module would have to own across a call.
    A pattern that uses one is REFUSED with `STATUS_UNSUPPORTED`, which is a
    different answer from "no match" and the caller can see the difference.
  * **Compiled-pattern objects.** `_PROTO_RE = re.compile(...)` at module
    level is a module-level binding, and a formal value lives in a function's
    own stack scratch (`bugs/FORMAL_module_state_no_storage.md`), so there is
    nowhere for a compiled pattern to live between two calls. Every function
    here therefore takes the pattern SOURCE and compiles it itself, which is
    redundant work and the only spelling available. The cost is stated rather
    than hidden: a program that matches in a loop re-parses per match.
  * **A match OBJECT.** `m.group(1)` and `m.start()` are methods on an object
    that holds five numbers, and an object is more than one 64-bit word. The
    answers are available, one per call, and each function that has one
    returns it; see THE SHAPE below.
  * **`re.VERBOSE`** is implemented; `re.ASCII`/`re.UNICODE`/`re.LOCALE` are
    accepted and ignored, because this engine is byte-oriented and so is
    ASCII-only for `\\w`, `\\b` and `\\d` whatever the flag says. CPython's
    default for a `str` pattern is Unicode, so `\\w` matches U+00AA there and
    does not here. That is a real difference and it is a property of matching
    bytes rather than code points, which is what a `char *` IS on this path
    (`bugs/FORMAL_string_value_model.md`).
  * **`re.escape` and `re.sub` return `malloc`'d buffers** the CALLER owns,
    exactly as `os/_syscalls.mojo`'s string functions do, and exactly for the
    same reason: a `str` here is a bare `char *` into read-only text, and
    `malloc` is the only writable memory in the image. There is no `free` in
    this module; `os.os_free(p)` is the spelling that releases one.

THE SHAPE, AND IT IS NOT CPYTHON'S
----------------------------------
CPython's spelling is a compiled-pattern object, a match object, and methods
on both. On this path an object is more than one 64-bit word and a compiled
pattern has nowhere to live, so the same questions are asked as FUNCTIONS and
each returns one answer:

    status = re.search(out, pattern, subject, flags)
    out[0] is the whole match's start, out[1] its end,
    out[2] / out[3] are group 1's start and end, out[4] / out[5] group 2's, …

`out` is a list the CALLER allocates, and that is not a workaround: a list
built inside a function lives in that function's frame, so a returned list is
a read of a frame the caller does not own (limit 4 of `struct.mojo`'s
docstring, measured). `struct.pack_into` is the same shape for the same
reason, and it is the shape that is lifetime-sound.

A `STATUS` is returned rather than an answer that could be wrong:

    re.STATUS_NO()           0   the pattern is fine and did not match
    re.STATUS_OK()           1   matched; `out` holds the spans
    re.STATUS_LIMIT()        2   gave up: the pattern is bigger than this
                                  module compiles, the nesting is deeper than
                                  it descends, the backtracking stack filled,
                                  or the step budget ran out
    re.STATUS_UNSUPPORTED()  3   the pattern uses a construct this module
                                  does not implement (see above)

This is the rule the whole backend is built on — an honest refusal beats a
wrong answer — applied to a library rather than to a construct. A caller that
checks the status cannot be told a "did not match" that was really "gave up",
and a caller that does not check it has the same exposure it has everywhere
else in this path.

LIMITS, MEASURED, NOT ASSUMED
------------------------------
1. **`x << <literal>` IS CORRECT ON BOTH BACKENDS, AND IS NOW COVERED FOR ALL
   64 AMOUNTS.** It was not. `formal/arm64.py`'s `encode_lsl_xd_xn_imm` used
   base `0xd3780000` where its own docstring said `0xd3400000`, which puts
   `immr = 0b111000` in bits 21:16 and makes OR-ing a real `immr` in force its
   low three bits to 1 — so the shift that RAN was not the shift that was
   WRITTEN, for 56 of the 64 amounts (`1 << 12` ran as `1 << 4`, `1 << 0` as
   `1 << 8`, `1 << 31` as `1 << 7`). x86-64 was right for all of them and a
   VARIABLE shift amount was right on both, so the tell was "`<<` by a literal
   above 8". Found by writing this file and needing multi-byte field assembly;
   the encoder is fixed and `test_arm64_encoders.py` now differential-tests LSL,
   LSR and ASR against Apple's assembler for all 64 amounts — the coverage
   whose absence let it sit there. `>>` was always right, and still is.

2. **A FUNCTION'S FRAME IS A FIXED 128 KiB**, so recursion past about 61
   frames runs off the end of the 8 MiB main stack and SEGFAULTS with no
   refusal. Measured: `deep(61)` prints, `deep(62)` dies. The parser here is
   recursive and is therefore depth-capped at `MAXDEPTH`; the MATCHER is not
   recursive at all (it is a loop with an explicit stack in the arena), which
   is why a pattern with a `*` over a long subject is fine where a recursive
   matcher would not be. Filed as `bugs/FORMAL_formal_frame_size_bounds_recursion_depth.md`.

3. **`list.append()` IN A LOOP IS A SILENT EXIT(1)** and a list built by a
   comprehension stops at 256 elements, so every array in here is a list LITERAL
   or, as here, a `malloc`'d arena written through `memset`. The engine does
   not use a list at all, which is the whole reason it can be unbounded.

4. **A PATTERN IS AT MOST `MAXPATTERN` BYTES AND COMPILES TO AT MOST
   `MAXNODES` NODES**, and a backtracking run may hold `MAXSTACK` pending
   choices. Each is a refusal (`STATUS_LIMIT`), never a truncated match. The
   three numbers are the arena's fixed layout, so they are not tunable at run
   time; they are chosen to cover every pattern in the corpus with room and
   are stated here so a reader can check that claim rather than take it.

5. **A STRING IS A NUL-TERMINATED `char*`**, so a string that CONTAINS a NUL
   has no measurable length: `str_len` stops at the NUL. The one place that
   bites is `escape(0)`, whose answer under CPython is the one-byte string
   NUL. The BYTES returned are right — they are what CPython returns, and
   `Pointer[UInt8].value()` at offset 0 reads them — but the LENGTH is zero
   and a caller that measures with `str_len` sees an empty string. This is the
   string value model, not a decision of this module
   (`bugs/FORMAL_string_value_model.md`); `test_re_formal.py`'s
   `test_escape_every_byte` reads that one byte directly and says why.

6. **A LIST ON THIS PATH HAS NO READABLE CAPACITY** — `[7, 8, 9][0]` is 7 and
   not a count — and a store past its end is a SILENT `exit(1)` with nothing
   printed. So every function here that writes into a caller's list takes the
   capacity as an argument and answers `STATUS_LIMIT` when it is too small,
   rather than making "you did not size it right" a process exit. The size a
   caller needs is `2 * (re.ngroups(pattern) + 1)` for the three span
   functions and `1 + 2 * maxn` for `findall` and `split`, and it is the one
   thing a caller has to know that it cannot read back off the list.

7. **`re.sub` AND `re.split` DO NOT RE-COMPILE PER MATCH** and a backtracking
   engine is exponential in the worst case, so a run is given a step budget.
   Exceeding it is `STATUS_LIMIT`, not a wrong answer. The budget is
   `STEP_LIMIT()` and it is far above anything the corpus needs.
"""

from os._syscalls import str_len, str_alloc, str_put, str_copy



# ── THE ARENA ───────────────────────────────────────────────────────────────
#
# ONE `malloc`'d block holds the whole engine's mutable state: the compiled
# program, the character-class ranges, the group saves, the backtracking
# stack, and the parser's own words. One block, and not a list, for a reason
# measured on this path: `list.append()` inside a loop is a silent `exit(1)`
# and a list built by a comprehension stops at 256 elements, so an array whose
# length is not known until run time is neither of those. `malloc` is the
# answer, and it has no length limit this module has to respect.
#
# Every offset below is a literal or literal-only arithmetic, which is what
# makes a module-level name readable at all on this path: a binding whose
# value the build can FOLD is substituted at every read, and one it cannot is
# refused by name (`bugs/FORMAL_module_state_no_storage.md`). The public
# constants are re-exported as FUNCTIONS, because a reader in ANOTHER module
# cannot read a name at all — `MAXPATTERN()` is the spelling that lowers.
#
# Nothing here is freed. A caller that runs `re` in a loop leaks one arena per
# call, which is the same bargain `os.path.join` makes and for the same reason:
# there is no `free` in this module and `os.os_free(p)` is the spelling.

_PARSER = 0            # 32 words of 4 bytes; words 24-25 are `sub`'s own
                       # (_P_USED below) and the block ends where _PFRAMES does
_PFRAMES = 128         # the parser's per-piece frames, _PFRAMEW words each
_PFRAMEW = 8
_PDEPTHMAX = 24
_PPROG = 1088          # the compiled program, _NNODES nodes of 8 bytes
_NNODES = 640
_PRNG = 6208           # character-class ranges, 2 bytes each
_NRNG = 256
_PSAVE = 6720          # the group saves, _NSAVE words of 4 bytes
_NSAVE = 16            # two slots per group, _MAXG groups
_PSTACK = 6784         # the backtracking stack, _NSTACK entries of 16 bytes
_NSTACK = 1024

# A frame is one piece's private parser state, indexed by nesting depth: the
# group number its atom created, the node and range counts before that atom,
# the group count before the piece (which is also what the copies of a
# quantified atom restore), the source offsets it started and ended at, the
# offset just past its quantifier, and the limit to put back when a copy is
# done parsing the atom's source again.
_PF_GRP = 0
_PF_NN = 1
_PF_NR = 2
_PF_NG = 3
_PF_ASTART = 4
_PF_AEND = 5
_PF_AFTER = 6
_PF_OLIM = 7


def _pf(a, d: Int, w: Int) -> Int:
    """Frame `d`'s word `w` — the per-piece parser state that used to be a
    shared word in the arena and was therefore whatever the innermost nested
    parse happened to leave behind.

    Every one of these was a separate bug of the same shape before this
    existed, and each was found by a different corpus case, which is the part
    worth recording: `_P_ASTART` made the copies of `(?:ab)+` compile from the
    `b`; `_P_NG0` numbered `(a)?`'s own group 2; `_P_AFTER` left the parser
    pointing at the `)` of `(a+)?` and the pattern was then refused for having
    a stray `)`; `_P_GRP` lost the group number of a quantified group whose
    body had a repetition in it. A frame is indexed by nesting depth, so the
    value a piece reads is its own and a nested parse cannot reach it.
    """
    return _g4(a, _PFRAMES + (d * _PFRAMEW + w) * 4)


def _spf(a, d: Int, w: Int, v: Int) -> Int:
    _s4(a, _PFRAMES + (d * _PFRAMEW + w) * 4, v)
    return 0

# Parser words, as indices; each occupies 4 bytes from _PARSER.
_P_POS = 0
# `_P_ERR` HOLDS A STATUS, not a boolean: `_prepare` returns this word
# directly, so "unsupported" is 3 and "too big" is 2 and a plain 0 is a
# pattern that compiled. It was 1 and 2 — and 1 is STATUS_OK, so every
# refusal in the engine was reported to the caller as success with blanked
# spans (measured: `a**`, `a)` and `[z-a]` all came back "OK, no match").
_P_ERR = 1
_P_NN = 2
_P_NG = 3
_P_NR = 4
_P_FLAGS = 5
_P_DEPTH = 6
_P_PATLEN = 7
_P_LIMIT = 8
_P_SUPP = 9
_P_LO = 10
_P_HI = 11
_P_GRP = 12
# Words 9, 14, 15, 16 and 24 used to be `_P_OLIM`, `_P_ASTART`, `_P_AEND`,
# `_P_NG0` and `_P_AFTER`: a piece's source span, the group count to restore for
# its copies, the limit to put back when a copy is done, and the offset just
# past its quantifier. All five are per-PIECE state, and living in the arena as
# shared words is the bug class `_pf` ends. They are frame words now, and the
# numbering below is what is left, compacted.
_P_GREEDY = 13
_P_STEPS = 14
_P_PC = 15
_P_SP = 16
_P_TOP = 17
_P_MSTART = 18
_P_MEND = 19
_P_ENTRY = 20
_P_NEXT = 21
_P_PHASE = 22
_P_CLROUT = 23
# Words 24 and 25 are `sub`'s OUTPUT-BUFFER state: how much of the caller's
# buffer is written, and whether this pass measures it or writes it. They were
# a trailing `used, w` parameter of SEVEN functions of the template walk, which
# is what put three of them over the six integer argument registers the x86-64
# ABI passes (`sub: 7 parameters exceeds the 6 …`), so the whole module was
# refused there and with it the 45 files that import it. Per-call state in the
# arena is where the rest of this engine keeps it, and the walk is not
# re-entrant — one `sub` call owns one arena — so there is nothing to lose.
_P_USED = 24
_P_W = 25

# Opcodes. A node is 8 bytes: op, a, b, c, p0 (2 bytes), p1 (2 bytes).
OP_CHAR = 1
OP_ANY = 2
OP_CLASS = 3
OP_SPLIT = 4
OP_JMP = 5
OP_SAVE = 6
OP_BOL = 7
OP_EOL = 8
OP_WORDB = 9
OP_MATCH = 10
OP_FAIL = 11

# The flag bits are CPython's own, so a caller that already has them passes
# them straight through.
F_IGNORECASE = 2
F_MULTILINE = 8
F_DOTALL = 16
F_VERBOSE = 64

_MAXG = 8
_MAXPAT = 128
_MAXDEPTH = 20


# ── BYTES IN AND OUT OF THE ARENA ───────────────────────────────────────────
#
# A byte is read with `Pointer[UInt8].value()` and written with a one-byte
# `memset`, and BOTH spellings are forced:
#   * `p[i]` on a pointer is not a byte load — it takes the list-blob path,
#     which reads a COUNT from offset 0 and bounds-checks against it, so a
#     program that indexes a string for a character gets a plausible number
#     built out of adjacent bytes
#     (`bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md`);
#   * `value()` needs a DECLARED pointee, so the receiver is a local
#     `var q: Pointer[UInt8] = p + i` and never an inline `(p + i).value()`.
# A multi-byte field is assembled with `<<` and taken out with `>>`, both by a
# literal amount. This file was WRITTEN with `* 256` and friends and a comment
# saying it had to be, because `encode_lsl_xd_xn_imm` had base `0xd3780000`
# where its own docstring said `0xd3400000`, and 56 of the 64 shift amounts
# encoded to a different instruction (`1 << 12` ran as `1 << 4`). The encoder is
# fixed and all 64 amounts are now differential-tested against Apple's
# assembler (`test_arm64_encoders.py`), so the workaround is gone rather than
# left in beside the thing that made it unnecessary.

def _b(p, i: Int) -> Int:
    """The byte at `p[i]`, 0..255."""
    var q: Pointer[UInt8] = p + i
    return Int(q.value())


def _sb(p, i: Int, v: Int) -> Int:
    """The byte `v & 255` at `p[i]`. Returns 0."""
    memset(p + i, v & 255, 1)
    return 0


def _g2(p, i: Int) -> Int:
    """Two bytes at `p[i]`, little-endian."""
    x = _b(p, i)
    y = _b(p, i + 1)
    return x + (y << 8)


def _s2(p, i: Int, v: Int) -> Int:
    """Two bytes of `v` at `p[i]`. Returns 0."""
    _sb(p, i, v)
    _sb(p, i + 1, v >> 8)
    return 0


def _g4(p, i: Int) -> Int:
    """Four bytes at `p[i]`, little-endian, UNSIGNED."""
    x = _b(p, i)
    y = _b(p, i + 1)
    z = _b(p, i + 2)
    w = _b(p, i + 3)
    return x + (y << 8) + (z << 16) + (w << 24)


def _s4(p, i: Int, v: Int) -> Int:
    """Four bytes of `v` at `p[i]`, two's complement. Returns 0."""
    _sb(p, i, v)
    _sb(p, i + 1, v >> 8)
    _sb(p, i + 2, v >> 16)
    _sb(p, i + 3, v >> 24)
    return 0


def _g4s(p, i: Int) -> Int:
    """Four bytes at `p[i]` as a SIGNED value."""
    v = _g4(p, i)
    if v >= 2147483648:
        return v - 4294967296
    return v


def _arena() -> Pointer[UInt8]:
    """A zeroed block big enough for the whole engine's state.

    The size is the sum of the layout constants above and it is spelled HERE
    and only here. It was also a module constant, and the two disagreed: the
    constant was 23168 and the `malloc` said 22208, because growing the arena
    for the parser frames moved one and not the other. A reader taking the
    constant for the arena's size would be off by a kilobyte, which is the
    whole point of writing it down once.
    """
    var p: Pointer[UInt8] = malloc(23168)
    memset(p, 0, 23168)
    return p


def _pa(a, w: Int) -> Int:
    """Parser word `w` (an index, not an offset)."""
    return _g4(a, _PARSER + w * 4)


def _pas(a, w: Int) -> Int:
    """Parser word `w` as a SIGNED value — for `_P_HI`, which is -1 for an
    open-ended `{m,}` repeat. Read with `_pa` it comes back as 4294967295 and
    `hi < 0` is false, so the open-ended repeats compiled as a loop over four
    billion copies (measured: `re.ngroups("a*")` never returned)."""
    return _g4s(a, _PARSER + w * 4)


def _spa(a, w: Int, v: Int) -> Int:
    """Set parser word `w`. Returns 0."""
    return _s4(a, _PARSER + w * 4, v)


def _flg(a, f: Int) -> Int:
    """1 if flag `f` is set in the pattern's flags word."""
    if (_pa(a, _P_FLAGS) & f) == f:
        return 1
    return 0


# ── NODES ───────────────────────────────────────────────────────────────────

def _nn(a, op: Int, x: Int, y: Int, z: Int) -> Int:
    """A new node, or 0 with `_P_ERR` set when the program is full."""
    n = _pa(a, _P_NN)
    if n >= _NNODES:
        _spa(a, _P_ERR, 2)
        return 0
    o = n * 8
    _sb(a, _PPROG + o, op)
    _sb(a, _PPROG + o + 1, x)
    _sb(a, _PPROG + o + 2, y)
    _sb(a, _PPROG + o + 3, z)
    _sb(a, _PPROG + o + 4, 0)
    _sb(a, _PPROG + o + 5, 0)
    _sb(a, _PPROG + o + 6, 0)
    _sb(a, _PPROG + o + 7, 0)
    _spa(a, _P_NN, n + 1)
    return n


def _na(a, n: Int) -> Int:
    return _b(a, _PPROG + n * 8 + 1)


def _nb(a, n: Int) -> Int:
    return _b(a, _PPROG + n * 8 + 2)


def _nc(a, n: Int) -> Int:
    return _b(a, _PPROG + n * 8 + 3)


def _np0(a, n: Int) -> Int:
    return _g2(a, _PPROG + n * 8 + 4)


def _np1(a, n: Int) -> Int:
    return _g2(a, _PPROG + n * 8 + 6)


def _sp0(a, n: Int, v: Int) -> Int:
    return _s2(a, _PPROG + n * 8 + 4, v)


def _sp1(a, n: Int, v: Int) -> Int:
    return _s2(a, _PPROG + n * 8 + 6, v)


def _term(a, op: Int, x: Int, y: Int, z: Int, nxt: Int) -> Int:
    """A node that ends a fragment, with its continuation in p0.

    A CHAR cannot fall through to "the next node" and be right: the piece
    after it is not necessarily the next node, because a concatenation is a
    chain of fragments and each fragment ends where the NEXT one begins. So
    every fragment ends with a node whose p0 says where to go, and p0 == 0
    still means "the next node" for the nodes nothing chains.
    """
    n = _nn(a, op, x, y, z)
    _sp0(a, n, nxt)
    return n


# ── CHARACTER CLASSES ───────────────────────────────────────────────────────
#
# A class is a run of (lo, hi) byte pairs in the arena, and its CLASS node
# holds the run's offset, its length, and whether the set is negated.
# Negation is NOT folded into the ranges, so `\D`, `\S`, `\W` inside a class
# and `[^\d]` are one case: the complement is added as ranges, which is what
# `regex_compile.py` does and for the same reason (a negated set over 0..255 is
# two or five ranges, not a flag on a run).

def _addr(a, lo: Int, hi: Int) -> Int:
    """Append the range `lo..hi` to the class being built; the new count."""
    n = _pa(a, _P_NR)
    if n >= _NRNG:
        _spa(a, _P_ERR, 2)
        return n
    _sb(a, _PRNG + n * 2, lo)
    _sb(a, _PRNG + n * 2 + 1, hi)
    _spa(a, _P_NR, n + 1)
    return n + 1


def _add_d(a, c: Int) -> Int:
    """`\d` (`c` 0) or its complement over 0..255 (`c` 1)."""
    if c == 0:
        return _addr(a, 48, 57)
    c = _addr(a, 0, 47)
    return _addr(a, 58, 255)


def _add_s(a, c: Int) -> Int:
    """`\s` or its complement."""
    if c == 0:
        c = _addr(a, 9, 13)
        return _addr(a, 32, 32)
    c = _addr(a, 0, 8)
    c = _addr(a, 14, 31)
    return _addr(a, 33, 255)


def _add_w(a, c: Int) -> Int:
    """`\w` or its complement."""
    if c == 0:
        c = _addr(a, 48, 57)
        c = _addr(a, 65, 90)
        c = _addr(a, 95, 95)
        return _addr(a, 97, 122)
    c = _addr(a, 0, 47)
    c = _addr(a, 58, 64)
    c = _addr(a, 91, 94)
    c = _addr(a, 96, 96)
    return _addr(a, 123, 255)


# ── ESCAPES ─────────────────────────────────────────────────────────────────
#
# `c` has already been read. The shorthands are intercepted by the caller,
# because outside a class they are one opcode and inside one they are ranges.

def _hexval(c: Int) -> Int:
    """0..15 for a hex digit, -1 otherwise."""
    if c >= 48 and c <= 57:
        return c - 48
    if c >= 97 and c <= 102:
        return c - 87
    if c >= 65 and c <= 70:
        return c - 55
    return 0 - 1


def _escbyte(a, code, c: Int, incls: Int) -> Int:
    """The byte an escape denotes, or -1 with `_P_ERR` set.

    An escape of an ASCII LETTER that this module does not define is an error,
    which is CPython's own rule since 3.12 (`re.compile(r"\q")` raises) — and
    matching the letter instead would be a match where CPython refuses to
    compile.

    A backslash and DIGITS is CPython's octal-or-group-reference rule, and the
    two halves of it are not the same thing: inside a character class it is
    always octal (`[\1]` is the byte 1), and outside one it is a group
    reference unless THREE octal digits follow (`\101` is `A`, `\12` is an
    error about group 12). Measured, all of them:
    `\101`->'A', `\100`->'\x40', `\123`->'S', `\012`->'\n', `\07`->'\x07',
    `\12`->error, `\19`->error, `\1`->error, `\400`->error (out of range).
    """
    if c == 110:
        return 10
    if c == 116:
        return 9
    if c == 114:
        return 13
    if c == 102:
        return 12
    if c == 118:
        return 11
    if c == 97:
        return 7
    if c == 98:
        return 8
    if c == 120:
        v = 0
        k = 0
        while k < 2:
            d = _p_peek(a, code)
            if _hexval(d) < 0:
                _spa(a, _P_ERR, 3)
                return 0 - 1
            v = v * 16 + _hexval(d)
            _p_adv(a, code)
            k = k + 1
        return v
    if c >= 48 and c <= 57:
        v = c - 48
        nd = 1
        while nd < 3:
            d = _p_peek(a, code)
            if d < 48 or d > 55:
                break
            v = v * 8 + (d - 48)
            _p_adv(a, code)
            nd = nd + 1
        if c != 48 and nd < 3 and incls == 0:
            _spa(a, _P_ERR, 3)
            return 0 - 1
        if v > 255:
            _spa(a, _P_ERR, 3)
            return 0 - 1
        return v
    if c >= 65 and c <= 90:
        _spa(a, _P_ERR, 3)
        return 0 - 1
    if c >= 97 and c <= 122:
        _spa(a, _P_ERR, 3)
        return 0 - 1
    return c


# ── PARSER PRIMITIVES ───────────────────────────────────────────────────────

def _p_at(a, code, k: Int) -> Int:
    """The byte at POS+k, or -1 past the limit."""
    i = _pa(a, _P_POS) + k
    if i >= _pa(a, _P_LIMIT):
        return 0 - 1
    return _b(code, i)


def _p_peek(a, code) -> Int:
    return _p_at(a, code, 0)


def _p_adv(a, code) -> Int:
    """The byte at POS, then POS + 1. -1 past the limit."""
    i = _pa(a, _P_POS)
    if i >= _pa(a, _P_LIMIT):
        return 0 - 1
    _spa(a, _P_POS, i + 1)
    return _b(code, i)


def _p_ws(a, code) -> Int:
    """One VERBOSE whitespace run or `#` comment. 1 if it consumed anything."""
    if _pa(a, _P_POS) >= _pa(a, _P_LIMIT):
        return 0
    c = _b(code, _pa(a, _P_POS))
    if c == 35:
        while 1:
            if _pa(a, _P_POS) >= _pa(a, _P_LIMIT):
                return 1
            if _b(code, _pa(a, _P_POS)) == 10:
                return 1
            _spa(a, _P_POS, _pa(a, _P_POS) + 1)
    if c == 32 or c == 9 or c == 10 or c == 13 or c == 11 or c == 12:
        _spa(a, _P_POS, _pa(a, _P_POS) + 1)
        return 1
    return 0


def _skip(a, code) -> Int:
    """VERBOSE: whitespace and `#` comments. Never called inside a class."""
    if _flg(a, F_VERBOSE) == 0:
        return 0
    k = _p_ws(a, code)
    while k == 1:
        k = _p_ws(a, code)
    return 0


def _p_more(a, code) -> Int:
    """1 if another piece starts at POS."""
    _skip(a, code)
    if _pa(a, _P_POS) >= _pa(a, _P_LIMIT):
        return 0
    c = _p_peek(a, code)
    if c == 124:
        return 0
    if c == 41:
        return 0
    return 1


# ── ATOMS ───────────────────────────────────────────────────────────────────

def _clsnode(a, which: Int, neg: Int, u: Int, nxt: Int) -> Int:
    """A CLASS node for a shorthand, with its OWN negation flag.

    Outside a character class the negation stays a FLAG and the ranges added
    are the positive ones, which is one shape; inside a class it is folded into
    the ranges, which is `regex_compile.py`'s shape and is the same set either
    way. Doing both at once — adding the complement AND setting the flag —
    negates twice, and `\D+` then matched the digits.
    """
    off = _pa(a, _P_NR)
    if which == 0:
        _add_d(a, 0)
    elif which == 1:
        _add_s(a, 0)
    else:
        _add_w(a, 0)
    cnt = _pa(a, _P_NR) - off
    return _term(a, OP_CLASS, off, cnt, neg, nxt)


def _p_atom(a, code, nxt: Int) -> Int:
    """One atom, continuing at `nxt`."""
    _skip(a, code)
    if _pa(a, _P_POS) >= _pa(a, _P_LIMIT):
        _spa(a, _P_ERR, 3)
        return 0 - 1
    c = _p_adv(a, code)
    if c == 40:
        return _p_group(a, code, nxt)
    if c == 91:
        return _p_cls(a, code, nxt)
    if c == 46:
        return _term(a, OP_ANY, 0, 0, 0, nxt)
    if c == 94:
        return _term(a, OP_BOL, _flg(a, F_MULTILINE), 0, 0, nxt)
    if c == 36:
        return _term(a, OP_EOL, _flg(a, F_MULTILINE), 0, 0, nxt)
    if c == 92:
        return _p_esc(a, code, nxt)
    if c == 41:
        _spa(a, _P_ERR, 3)
        return 0 - 1
    if c == 42:
        _spa(a, _P_ERR, 3)
        return 0 - 1
    if c == 43:
        _spa(a, _P_ERR, 3)
        return 0 - 1
    if c == 63:
        _spa(a, _P_ERR, 3)
        return 0 - 1
    return _term(a, OP_CHAR, c, 0, 0, nxt)


def _p_esc(a, code, nxt: Int) -> Int:
    """An escape OUTSIDE a character class. The backslash is consumed."""
    e = _p_adv(a, code)
    if e < 0:
        _spa(a, _P_ERR, 3)
        return 0 - 1
    if e == 100:
        return _clsnode(a, 0, 0, 0, nxt)
    if e == 68:
        return _clsnode(a, 0, 1, 0, nxt)
    if e == 115:
        return _clsnode(a, 1, 0, 0, nxt)
    if e == 83:
        return _clsnode(a, 1, 1, 0, nxt)
    if e == 119:
        return _clsnode(a, 2, 0, 0, nxt)
    if e == 87:
        return _clsnode(a, 2, 1, 0, nxt)
    if e == 98:
        return _term(a, OP_WORDB, 1, 0, 0, nxt)
    if e == 66:
        return _term(a, OP_WORDB, 0, 0, 0, nxt)
    if e == 65:
        return _term(a, OP_BOL, 0, 0, 0, nxt)
    if e == 90:
        return _term(a, OP_EOL, 0, 0, 0, nxt)
    if e == 122:
        return _term(a, OP_EOL, 0, 0, 0, nxt)
    # A backslash and DIGITS is NOT intercepted here: `_escbyte` decides,
    # because outside a class it is a group reference only when fewer than
    # three octal digits follow, and `\101` is the letter A. Refusing every
    # `\` + digit made `\101` an error and it is not.
    c = _escbyte(a, code, e, 0)
    if c < 0:
        return 0 - 1
    return _term(a, OP_CHAR, c, 0, 0, nxt)


def _p_close(a, code) -> Int:
    """Consume the `)` that ends a group. 0 if there is not one.

    Every group needs it and nothing else did it: the body's parse stops AT the
    `)` and leaves it there, so the concatenation after the group read it as
    the next piece, `(a)(b)` compiled to one group, and `{2}` after a group was
    not a quantifier at all — the parser was still inside the group.
    """
    if _p_peek(a, code) != 41:
        _spa(a, _P_ERR, 3)
        return 0
    _p_adv(a, code)
    return 1


def _p_group(a, code, nxt: Int) -> Int:
    """A `(`, already consumed."""
    _spa(a, _P_GRP, 0)
    c = _p_peek(a, code)
    if c == 63:
        _p_adv(a, code)
        c = _p_peek(a, code)
        if c == 58:
            _p_adv(a, code)
            return _p_group0(a, code, nxt)
        if c == 80:
            _p_adv(a, code)
            if _p_peek(a, code) != 60:
                _spa(a, _P_ERR, 3)          # (?P= — a backreference
                return 0 - 1
            _p_adv(a, code)
            c = _p_peek(a, code)
            if c == 61 or c == 33:
                _spa(a, _P_ERR, 3)          # (?<= and (?<! — a lookbehind
                return 0 - 1
            while 1:
                d = _p_peek(a, code)
                if d == 62:
                    break
                if d < 0:
                    _spa(a, _P_ERR, 3)
                    return 0 - 1
                _p_adv(a, code)
            _p_adv(a, code)
            return _p_group1(a, code, nxt)
        _spa(a, _P_ERR, 3)                  # lookahead, conditionals, inline
        return 0 - 1
    return _p_group1(a, code, nxt)


def _p_group0(a, code, nxt: Int) -> Int:
    """`(?: … )` — a group with no number.

    The body's continuation is the JMP and the JMP goes to `nxt`, in that
    order. It was the other way round — the body ended at the JMP AND the JMP
    pointed at the body — which is a LOOP that consumes nothing, so
    `(?:a)+` matched nothing at all while `(a)+` matched (measured: a group
    with a number builds its own two SAVEs and so never shared the JMP).
    """
    t = _nn(a, OP_JMP, 0, 0, 0)
    _sp0(a, t, nxt)
    b = _p_alt(a, code, t)
    if _p_close(a, code) == 0:
        return 0 - 1
    return b


def _p_group1(a, code, nxt: Int) -> Int:
    """A capturing group: SAVE the start, the body, SAVE the end."""
    d = _pa(a, _P_DEPTH)
    if d >= _MAXDEPTH:
        _spa(a, _P_ERR, 2)
        return 0 - 1
    _spa(a, _P_DEPTH, d + 1)
    g = _pa(a, _P_NG) + 1
    if g > _MAXG:
        _spa(a, _P_ERR, 2)
        _spa(a, _P_DEPTH, d)
        return 0 - 1
    _spa(a, _P_NG, g)
    supp = 0
    if _pa(a, _P_SUPP) > 0:
        supp = 1
        _spa(a, _P_SUPP, _pa(a, _P_SUPP) - 1)
    gend = _nn(a, OP_SAVE, 2 * g, 1, 0)
    gs = _nn(a, OP_SAVE, 2 * g, 0, 0)
    _sp0(a, gend, nxt)
    b = _p_alt(a, code, gend)
    _spa(a, _P_DEPTH, d)
    if b < 0:
        return 0 - 1
    if _p_close(a, code) == 0:
        return 0 - 1
    _sp0(a, gs, b)
    # AFTER the body, not before it: the body's own pieces each begin by
    # clearing `_P_GRP`, so a write before the parse would not survive it. This
    # word is the one piece of per-piece state still shared, and it is safe for
    # the same reason the rest became frames — the reader writes its frame word
    # before recursing and reads it after, and this one is written by the
    # innermost thing that has an opinion about it.
    _spa(a, _P_GRP, g)
    if supp == 1:
        return b
    return gs


def _p_clsrange_bad(a, code) -> Int:
    """`[\d-x]`: a shorthand is not a range endpoint. -1, or the count."""
    if _p_peek(a, code) == 45:
        if _p_at(a, code, 1) != 93:
            _spa(a, _P_ERR, 3)
            return 0 - 1
    return _pa(a, _P_NR)


def _p_clsitem(a, code, c: Int) -> Int:
    """One item of a character class, ranges included. The new range count."""
    if c == 92:
        _p_adv(a, code)
        e = _p_peek(a, code)
        if e == 100:
            _p_adv(a, code)
            _add_d(a, 0)
            return _p_clsrange_bad(a, code)
        if e == 68:
            _p_adv(a, code)
            _add_d(a, 1)
            return _p_clsrange_bad(a, code)
        if e == 115:
            _p_adv(a, code)
            _add_s(a, 0)
            return _p_clsrange_bad(a, code)
        if e == 83:
            _p_adv(a, code)
            _add_s(a, 1)
            return _p_clsrange_bad(a, code)
        if e == 119:
            _p_adv(a, code)
            _add_w(a, 0)
            return _p_clsrange_bad(a, code)
        if e == 87:
            _p_adv(a, code)
            _add_w(a, 1)
            return _p_clsrange_bad(a, code)
        if e < 0:
            _spa(a, _P_ERR, 3)
            return 0 - 1
        _p_adv(a, code)
        c = _escbyte(a, code, e, 1)
        if c < 0:
            return 0 - 1
    else:
        _p_adv(a, code)
    if _p_peek(a, code) == 45:
        d = _p_at(a, code, 1)
        if d != 93 and d >= 0:
            _p_adv(a, code)
            if d == 92:
                _p_adv(a, code)
                e = _p_peek(a, code)
                if e == 100 or e == 68 or e == 115 or e == 83 or e == 119 or e == 87:
                    _spa(a, _P_ERR, 3)
                    return 0 - 1
                if e < 0:
                    _spa(a, _P_ERR, 3)
                    return 0 - 1
                _p_adv(a, code)
                d = _escbyte(a, code, e, 1)
            else:
                _p_adv(a, code)
            if d < 0:
                return 0 - 1
            if d < c:
                _spa(a, _P_ERR, 3)
                return 0 - 1
            return _addr(a, c, d)
    return _addr(a, c, c)


def _p_cls(a, code, nxt: Int) -> Int:
    """`[ … ]`, the `[` already consumed."""
    off = _pa(a, _P_NR)
    neg = 0
    if _p_peek(a, code) == 94:
        _p_adv(a, code)
        neg = 1
    first = 1
    while 1:
        c = _p_peek(a, code)
        if c == 93 and first == 0:
            _p_adv(a, code)
            return _term(a, OP_CLASS, off, _pa(a, _P_NR) - off, neg, nxt)
        if c < 0:
            _spa(a, _P_ERR, 3)
            return 0 - 1
        first = 0
        if _p_clsitem(a, code, c) < 0:
            return 0 - 1
    return 0 - 1


# ── QUANTIFIERS ─────────────────────────────────────────────────────────────
#
# A quantifier is read AFTER its atom, which is what lets a counted repeat
# re-parse the atom once per copy: an atom cannot be spliced into a
# concatenation twice, because a node has one forward edge, and the only thing
# that can be repeated is its SOURCE. So `_p_piece` records the atom's span,
# compiles it once to find out what it is, rewinds the program, and lets
# `_p_repeat` compile one copy per repetition.

def _p_lazy(a, code) -> Int:
    """A `?` after a quantifier makes it lazy. Returns 1."""
    if _p_peek(a, code) == 63:
        _p_adv(a, code)
        _spa(a, _P_GREEDY, 0)
    else:
        _spa(a, _P_GREEDY, 1)
    return 1


def _p_quant(a, code) -> Int:
    """The quantifier at POS, consumed. 0 if there is none."""
    c = _p_peek(a, code)
    if c == 42:
        _p_adv(a, code)
        _spa(a, _P_LO, 0)
        _spa(a, _P_HI, 0 - 1)
        return _p_lazy(a, code)
    if c == 43:
        _p_adv(a, code)
        _spa(a, _P_LO, 1)
        _spa(a, _P_HI, 0 - 1)
        return _p_lazy(a, code)
    if c == 63:
        _p_adv(a, code)
        _spa(a, _P_LO, 0)
        _spa(a, _P_HI, 1)
        return _p_lazy(a, code)
    if c == 123:
        save = _pa(a, _P_POS)
        _p_adv(a, code)
        lo = 0
        got = 0
        while 1:
            d = _p_peek(a, code)
            if d < 48 or d > 57:
                break
            lo = lo * 10 + (d - 48)
            _p_adv(a, code)
            got = 1
        if got == 0:
            _spa(a, _P_POS, save)
            _spa(a, _P_LO, 1)
            _spa(a, _P_HI, 1)
            return 0
        hi = lo
        if _p_peek(a, code) == 44:
            _p_adv(a, code)
            # -1 is the "no upper bound" sentinel, and it must NOT be the
            # accumulator: `hi * 10 + d` starting from -1 is -10 + 3, which is
            # still negative, so `{2,3}` parsed as `{2,}` and `a{2,3}` matched
            # four characters where CPython matches three (measured, and the
            # whole `{m,n}` family was wrong with it — `a{2,2}` matched three).
            hi = 0
            got2 = 0
            while 1:
                d = _p_peek(a, code)
                if d < 48 or d > 57:
                    break
                hi = hi * 10 + (d - 48)
                _p_adv(a, code)
                got2 = 1
            if got2 == 0:
                hi = 0 - 1
        if _p_peek(a, code) != 125:
            _spa(a, _P_POS, save)
            _spa(a, _P_LO, 1)
            _spa(a, _P_HI, 1)
            return 0
        _p_adv(a, code)
        if lo > 64 or hi > 64:
            _spa(a, _P_ERR, 2)
            return 0 - 1
        _spa(a, _P_LO, lo)
        _spa(a, _P_HI, hi)
        return _p_lazy(a, code)
    _spa(a, _P_LO, 1)
    _spa(a, _P_HI, 1)
    return 0


def _clr(a, g: Int, tgt: Int) -> Int:
    """Two SAVEs that blank group `g` and continue at `tgt`. The first node.

    TWO and not one, because a backtrack entry remembers ONE word to put back
    and a group that did not match has TWO words to blank. A single node that
    cleared both would restore one of them on the way out and leave the group
    half-matched, which is a wrong span rather than a missing one.
    """
    n = _nn(a, OP_SAVE, 2 * g, 2, 0)
    m = _nn(a, OP_SAVE, 2 * g, 3, 0)
    _sp0(a, n, m)
    _sp0(a, m, tgt)
    return n


def _clr0(a, g: Int) -> Int:
    """A blanking pair whose LAST node's target is not known yet.

    The head, which is where a SPLIT's skip branch goes. `_clrset` finishes it
    once the target exists — the target is the next optional copy's SPLIT, and
    that is allocated after this one.
    """
    n = _nn(a, OP_SAVE, 2 * g, 2, 0)
    m = _nn(a, OP_SAVE, 2 * g, 3, 0)
    _sp0(a, n, m)
    _spa(a, _P_CLROUT, m)
    return n


def _clrset(a, tgt: Int) -> Int:
    """Point the last `_clr0` at `tgt`, and remember it as the skip chain."""
    _sp0(a, _pa(a, _P_CLROUT), tgt)
    return _pa(a, _P_CLROUT)


def _p_copy(a, code, d: Int, cont: Int, grp: Int) -> Int:
    """One repetition's body, compiled from the atom's source span.

    `grp` is the group number the ATOM created, and it is passed as 0 on
    every copy so the copies do not each number a group of their own — the
    body's own group parses to the same number each time, because `ng0` puts
    the counter back where the piece started.

    EVERY copy brackets the body with a start SAVE and an end SAVE, and that
    is what makes the reported group the LAST repetition rather than a mixture
    of the first and the last: `(a|b)+c` on `ababc` has group 1 at (3, 4) —
    the `b` — while a start SAVE emitted once, before the loop, stayed at 0
    (measured). `{m,n}` is the same shape with m mandatory copies in front, so
    `(ab){2}` reports (2, 4) and not (0, 4).

    Everything else this needs — the atom's source span, the group count to
    restore, and the pattern limit to put back — is read out of the PIECE'S OWN
    frame at `d`, because every copy re-enters `_p_piece` (through the group
    body it just parsed) and by then a shared word is holding something from the
    inside of the atom. See `_pf`; the limit is the fourth of those and it is
    what made `(\w+)?` come back refused, with the parser left pointing past
    the end of the pattern and the limit two bytes short of it.
    """
    cn = cont
    gs = 0
    if grp > 0:
        ge = _nn(a, OP_SAVE, 2 * grp, 1, 0)
        _sp0(a, ge, cont)
        cn = ge
        gs = _nn(a, OP_SAVE, 2 * grp, 0, 0)
    _spa(a, _P_POS, _pf(a, d, _PF_ASTART))
    _spa(a, _P_LIMIT, _pf(a, d, _PF_AEND))
    _spa(a, _P_NG, _pf(a, d, _PF_NG))
    if grp > 0:
        _spa(a, _P_SUPP, 1)
    else:
        _spa(a, _P_SUPP, 0)
    h = _p_alt(a, code, cn)
    _spa(a, _P_LIMIT, _pf(a, d, _PF_OLIM))
    if h < 0:
        return 0 - 1
    if grp > 0:
        _sp0(a, gs, h)
        return gs
    return h


def _p_repeat(a, code, d: Int, nxt: Int) -> Int:
    """The repetition, for the atom whose span is in the parser words.

    `X{m,n}` is m copies in a chain and then n-m OPTIONAL copies. Each
    optional copy is a SPLIT whose one branch is the copy and whose other goes
    to the NEXT optional copy — and that next SPLIT does not exist yet when the
    copy is parsed, which is why both links go through a JMP that is patched
    afterwards. Drawing the shape directly is what makes the mistake easy here:
    with the copy's exit wired straight to its own SPLIT, `a{2,3}` looped and
    matched four characters where CPython matches three.
    """
    # Read the whole frame ONCE, before the first copy: a copy is a nested
    # parse and will move `_P_LO`, `_P_HI` and `_P_GREEDY` under us.
    lo = _pas(a, _P_LO)
    hi = _pas(a, _P_HI)
    gred = _pa(a, _P_GREEDY)
    grp = _pf(a, d, _PF_GRP)
    after = _pf(a, d, _PF_AFTER)
    tramp = _nn(a, OP_JMP, 0, 0, 0)
    prev = tramp
    head = 0 - 1
    i = 1
    while i <= lo:
        j = _nn(a, OP_JMP, 0, 0, 0)
        b = _p_copy(a, code, d, j, grp)
        if b < 0:
            return 0 - 1
        if head < 0:
            head = b
        _sp0(a, prev, b)
        prev = j
        i = i + 1
    if hi < 0:
        j = _nn(a, OP_JMP, 0, 0, 0)
        lsp = _nn(a, OP_SPLIT, 0, 0, 0)
        b = _p_copy(a, code, d, lsp, grp)
        if b < 0:
            return 0 - 1
        if gred == 1:
            _sp0(a, lsp, b)
            _sp1(a, lsp, j)
        else:
            _sp0(a, lsp, j)
            _sp1(a, lsp, b)
        if lo == 0 and grp > 0:
            if gred == 1:
                _sp1(a, lsp, _clr(a, grp, j))
            else:
                _sp0(a, lsp, _clr(a, grp, j))
        if head < 0:
            head = lsp
        _sp0(a, prev, lsp)
        prev = j
    else:
        skip = 0 - 1
        while i <= hi:
            j = _nn(a, OP_JMP, 0, 0, 0)
            sk = _nn(a, OP_JMP, 0, 0, 0)
            s = _nn(a, OP_SPLIT, 0, 0, 0)
            b = _p_copy(a, code, d, j, grp)
            if b < 0:
                return 0 - 1
            if gred == 1:
                _sp0(a, s, b)
                _sp1(a, s, sk)
            else:
                _sp0(a, s, sk)
                _sp1(a, s, b)
            if skip >= 0:
                _sp0(a, skip, s)
            if lo == 0 and i == 1 and grp > 0:
                c = _clr0(a, grp)
                if gred == 1:
                    _sp1(a, s, c)
                else:
                    _sp0(a, s, c)
                skip = _pa(a, _P_CLROUT)
            else:
                skip = sk
            if head < 0:
                head = s
            _sp0(a, prev, s)
            prev = j
            i = i + 1
        if skip >= 0:
            _sp0(a, skip, nxt)
    if grp > _pa(a, _P_NG):
        _spa(a, _P_NG, grp)
    if head < 0:
        if grp > 0:
            _sp0(a, tramp, _clr(a, grp, nxt))
        else:
            _sp0(a, tramp, nxt)
        _spa(a, _P_POS, after)
        return tramp
    _sp0(a, prev, nxt)
    # PAST the quantifier, which is where the next piece starts. The atom's
    # end would leave the parser looking at the `+` it just consumed, and the
    # concatenation that follows would then try to make a piece of it —
    # measured: every `+` and `*` reported an unsupported pattern.
    _spa(a, _P_POS, after)
    return head


def _p_piece(a, code, nxt: Int) -> Int:
    """A quantifier and its atom, or a bare atom.

    The ATOM is parsed first and the quantifier read afterwards, because the
    quantifier is written after the atom: reading it first left the parser past
    the atom, and `a+` then compiled to a program that matched the empty string
    (measured, and the fix is the order of these two calls).

    With a quantifier the atom's compiled nodes are then DISCARDED and
    re-parsed from its source span, once per repetition, because a node has one
    forward edge and a repetition needs as many. The atom is a GROUP in that
    case and its own SAVE instructions belong around the whole repetition, not
    inside each copy, which is what the frame's group number is for.

    Every value this needs across the nested parse — the atom's node and range
    counts, its source span, the group count, the group number the atom
    created, and where its quantifier ended — lives in THIS piece's frame,
    indexed by the nesting depth it claimed. See `_pf` for the four bugs that
    is the fix for.
    """
    _skip(a, code)
    d = _pa(a, _P_DEPTH)
    if d >= _PDEPTHMAX:
        _spa(a, _P_ERR, 3)
        return 0 - 1
    start = _pa(a, _P_POS)
    _spf(a, d, _PF_NN, _pa(a, _P_NN))
    _spf(a, d, _PF_NR, _pa(a, _P_NR))
    _spf(a, d, _PF_NG, _pa(a, _P_NG))
    _spf(a, d, _PF_ASTART, start)
    _spf(a, d, _PF_AEND, start)
    _spf(a, d, _PF_AFTER, start)
    _spf(a, d, _PF_OLIM, _pa(a, _P_LIMIT))
    # `_P_GRP` is cleared here as well as the frame word: it is the word
    # `_p_group1` writes, and an atom that is NOT a group has to read 0 or the
    # next piece inherits the previous one's group number. Without this,
    # `(\w+)\s*` compiled the `\s*` as if it were `(\s*)` and bracketed it
    # with the same group's SAVEs, so the group reported the span of the
    # whitespace instead of the word (measured).
    _spa(a, _P_GRP, 0)
    _spf(a, d, _PF_GRP, 0)
    _spa(a, _P_DEPTH, d + 1)
    h = _p_atom(a, code, nxt)
    if h < 0:
        _spa(a, _P_DEPTH, d)
        return 0 - 1
    # The span is recorded AFTER the atom, not before it: the atom's own parse
    # runs `_p_piece` again for every piece inside it, and each of those
    # records its own span. Recording this one's start first and reading it
    # back out of a shared word afterwards meant the LAST nested piece's start
    # won, so the copies of `(?:ab)+` were compiled from the `b` and the `a`
    # was never emitted (measured: the match was `b`, CPython's is `ababab`).
    _spf(a, d, _PF_AEND, _pa(a, _P_POS))
    grp = _pa(a, _P_GRP)
    _spf(a, d, _PF_GRP, grp)
    # `_P_DEPTH` STAYS at d + 1 across the repetition, so a copy's own pieces
    # claim d + 1 and not d. Dropping it to d here handed every copy the
    # enclosing piece's frame and the second copy of `X{2,n}` was compiled from
    # the first copy's span.
    keep = _pa(a, _P_POS)
    q = _p_quant(a, code)
    if q == 0:
        _spa(a, _P_POS, keep)
        _spa(a, _P_DEPTH, d)
        return h
    if q < 0:
        # A quantifier that REFUSED. `0` is "there is none here" and -1 is
        # "there is one and this module will not have it", and before these
        # were told apart the refusal fell through to the repetition below with
        # the quantifier's own limits never written: `a{70,80}` past the
        # arena's repeat cap then built a program out of whatever was in the
        # parser words and the image died with nothing printed.
        _spa(a, _P_POS, keep)
        _spa(a, _P_DEPTH, d)
        return 0 - 1
    _spf(a, d, _PF_AFTER, _pa(a, _P_POS))
    _spa(a, _P_NN, _pf(a, d, _PF_NN))
    _spa(a, _P_NR, _pf(a, d, _PF_NR))
    _spa(a, _P_NG, _pf(a, d, _PF_NG))
    _spf(a, d, _PF_OLIM, _pa(a, _P_LIMIT))
    if _pa(a, _P_ERR) != 0:
        _spa(a, _P_DEPTH, d)
        return 0 - 1
    r = _p_repeat(a, code, d, nxt)
    _spa(a, _P_DEPTH, d)
    return r


def _p_cat(a, code, nxt: Int) -> Int:
    """Pieces one after another, each with the next as its continuation."""
    t = _nn(a, OP_JMP, 0, 0, 0)
    head = 0 - 1
    tprev = 0
    more = _p_more(a, code)
    while more == 1:
        h = _p_piece(a, code, t)
        if h < 0:
            return 0 - 1
        if head < 0:
            head = h
        else:
            _sp0(a, tprev, h)
        if _p_more(a, code) == 1:
            tprev = t
            t = _nn(a, OP_JMP, 0, 0, 0)
        else:
            _sp0(a, t, nxt)
            return head
    if head < 0:
        _sp0(a, t, nxt)
        return t
    return head


def _p_alt(a, code, nxt: Int) -> Int:
    """`a|b|c`: a chain of SPLITs, each the failure branch of the one before.

    A SPLIT takes its first branch and remembers its second, so option k+1
    hangs off option k's SPLIT's p1, and the LAST option's p1 is a FAIL: with
    every option tried and none matched, the alternation has failed, and
    continuing to the continuation from there would report a match that
    consumed nothing. That was not hypothetical — with a one-option
    alternation, which is every literal in the language, pointing p1 at the
    continuation made `re.search("b", "abc")` match the empty string at 0.

    A one-option alternation gets NO SPLIT at all, for the same reason plus
    the node count: it is the concatenation.
    """
    j = _nn(a, OP_JMP, 0, 0, 0)
    b = _p_cat(a, code, j)
    if b < 0:
        return 0 - 1
    _sp0(a, j, nxt)
    if _p_peek(a, code) != 124:
        return b
    entry = _nn(a, OP_SPLIT, 0, 0, 0)
    _sp0(a, entry, b)
    pend = entry
    while 1:
        _p_adv(a, code)
        s = _nn(a, OP_SPLIT, 0, 0, 0)
        _sp1(a, pend, s)
        j2 = _nn(a, OP_JMP, 0, 0, 0)
        b2 = _p_cat(a, code, j2)
        if b2 < 0:
            return 0 - 1
        _sp0(a, j2, nxt)
        _sp0(a, s, b2)
        pend = s
        if _p_peek(a, code) != 124:
            _sp1(a, pend, _nn(a, OP_FAIL, 0, 0, 0))
            return entry


# ── COMPILING ───────────────────────────────────────────────────────────────

def _prepare(a, code, flags: Int) -> Int:
    """Zero the parser, compile `code`. 0, or 1 unsupported, 2 too big.

    Node 0 is a JMP to node 2 and node 1 is the MATCH the whole program's
    dangling references point at, so the three entry points differ by one
    number: a search starts at 2, a `match` and a `fullmatch` at 0.
    """
    n = str_len(code)
    if n > _MAXPAT:
        return 2
    i = 0
    while i < 24:
        _spa(a, i, 0)
        i = i + 1
    _spa(a, _P_PATLEN, n)
    _spa(a, _P_FLAGS, flags)
    _spa(a, _P_LIMIT, n)
    _spa(a, _P_GREEDY, 1)
    # Node 0 is the anchor `match` and `fullmatch` enter at: a BOL that is only
    # true at position 0, with the program as its continuation. Without it
    # `re.match("b", "abc")` finds the `b` at 1, which is `re.search`.
    _nn(a, OP_BOL, 0, 0, 0)
    _nn(a, OP_MATCH, 0, 0, 0)
    e = _p_alt(a, code, 1)
    if _pa(a, _P_ERR) != 0:
        return _pa(a, _P_ERR)
    # Nothing may be LEFT OVER. A concatenation stops at a `)` or a `|` and
    # never looks at either again, so without this `a)` compiled to `a` and
    # matched, where CPython refuses to compile it at all (measured).
    if _pa(a, _P_POS) != _pa(a, _P_LIMIT):
        _spa(a, _P_ERR, 3)
        return 3
    _spa(a, _P_ENTRY, e)
    _sp0(a, 0, e)
    return 0


# ── MATCHING ────────────────────────────────────────────────────────────────
#
# A backtracker with its stack in the arena and NO recursion, which is the
# whole reason the engine is written this way: a formal frame is a fixed
# 128 KiB, so recursion past about 61 frames runs off the end of the stack
# (see the module docstring), and a recursive matcher for `a*` over a subject
# of length N is N frames deep. This one is a loop, and its stack is a region
# of a heap block, so `.*` over a kilobyte costs a kilobyte of stack and not
# 128 MiB of call frames.
#
# An entry is (pc, sp, slot, old): where to resume, where in the subject, and
# the group save to put back. `slot` is -1 for a choice point. The save is what
# makes backtracking correct for captures: a failed branch leaves stale values
# in the save slots, and every SAVE records what was there so the pop can put
# it back.

def _isw(c: Int) -> Int:
    """1 if `c` is one of the bytes `\\w` and `\\b` call a word character."""
    if c == 95:
        return 1
    if c >= 48 and c <= 57:
        return 1
    if c >= 65 and c <= 90:
        return 1
    if c >= 97 and c <= 122:
        return 1
    return 0


def _ceq(a, subj, sp: Int, ch: Int, flags: Int) -> Int:
    """1 if subject[sp] matches the literal byte `ch`, honouring IGNORECASE."""
    c = _b(subj, sp)
    if c == ch:
        return 1
    if (flags & F_IGNORECASE) == 0:
        return 0
    u = ch
    if u >= 97 and u <= 122:
        u = u - 32
    l = ch
    if l >= 65 and l <= 90:
        l = l + 32
    if c == u:
        return 1
    if c == l:
        return 1
    return 0


def _clr1(a, ni: Int, c: Int) -> Int:
    """1 if `c` is in node `ni`'s ranges, negation not applied."""
    off = _na(a, ni)
    n = _nb(a, ni)
    k = 0
    while k < n:
        if c >= _b(a, _PRNG + (off + k) * 2) and c <= _b(a, _PRNG + (off + k) * 2 + 1):
            return 1
        k = k + 1
    return 0


def _clsm(a, ni: Int, c: Int, flags: Int) -> Int:
    """1 if `c` is in node `ni`'s class, honouring negation and IGNORECASE."""
    hit = _clr1(a, ni, c)
    if hit == 0 and (flags & F_IGNORECASE) != 0:
        u = c
        if u >= 97 and u <= 122:
            u = u - 32
        l = c
        if l >= 65 and l <= 90:
            l = l + 32
        if _clr1(a, ni, u) == 1:
            hit = 1
        if hit == 0 and _clr1(a, ni, l) == 1:
            hit = 1
    if _nc(a, ni) == 1:
        if hit == 1:
            return 0
        return 1
    return hit


def _bol(a, subj, sp: Int, flags: Int) -> Int:
    """1 at a position `^` matches: 0, or after a newline under MULTILINE."""
    if sp == 0:
        return 1
    if (flags & F_MULTILINE) != 0:
        if _b(subj, sp - 1) == 10:
            return 1
    return 0


def _eol(a, subj, sp: Int, n: Int, flags: Int) -> Int:
    """1 at a position `$` matches.

    Without MULTILINE that is the end of the subject, or the position before a
    newline that is the LAST byte — which is the case people are surprised by
    and which a real test pins.
    """
    if sp == n:
        return 1
    if (flags & F_MULTILINE) != 0:
        if _b(subj, sp) == 10:
            return 1
        return 0
    if sp == n - 1:
        if _b(subj, sp) == 10:
            return 1
    return 0


def _worb(a, subj, sp: Int, n: Int, want: Int) -> Int:
    """1 at a position `\\b` (`want` 1) or `\\B` (`want` 0) matches."""
    before = 0
    if sp > 0:
        before = _isw(_b(subj, sp - 1))
    after = 0
    if sp < n:
        after = _isw(_b(subj, sp))
    if want == 1:
        if before != after:
            return 1
        return 0
    if before == after:
        return 1
    return 0


def _zero_saves(a) -> Int:
    """Every group unmatched. One call per start position, not per step."""
    i = 0
    while i < _NSAVE:
        _s4(a, _PSAVE + i * 4, 0 - 1)
        i = i + 1
    return 0


def _push(a, top: Int, pc: Int, sp: Int, slot: Int, old: Int) -> Int:
    o = top * 16
    _s4(a, _PSTACK + o, pc)
    _s4(a, _PSTACK + o + 4, sp)
    _s4(a, _PSTACK + o + 8, slot)
    _s4(a, _PSTACK + o + 12, old)
    return 0


def _st_char(a, subj, n: Int, flags: Int) -> Int:
    """CHAR: consume one byte if it is the literal."""
    sp = _pa(a, _P_SP)
    if sp >= n:
        return 0
    if _ceq(a, subj, sp, _b(a, _PPROG + _pa(a, _P_PC) * 8 + 1), flags) == 1:
        _spa(a, _P_SP, sp + 1)
        return 1
    return 0


def _st_class(a, subj, n: Int, flags: Int) -> Int:
    """CLASS: consume one byte if it is in the set."""
    sp = _pa(a, _P_SP)
    if sp >= n:
        return 0
    if _clsm(a, _pa(a, _P_PC), _b(subj, sp), flags) == 1:
        _spa(a, _P_SP, sp + 1)
        return 1
    return 0


def _st_any(a, subj, n: Int, flags: Int) -> Int:
    """ANY: consume one byte unless it is a newline and DOTALL is off."""
    sp = _pa(a, _P_SP)
    if sp >= n:
        return 0
    if _b(subj, sp) != 10 or (flags & F_DOTALL) != 0:
        _spa(a, _P_SP, sp + 1)
        return 1
    return 0


def _next(a, pc: Int) -> Int:
    """Where a fragment-ending node goes: its p0, or the next node."""
    t = _np0(a, pc)
    if t == 0:
        return pc + 1
    return t


def _st_split(a, pc: Int) -> Int:
    """SPLIT: remember the second branch, take the first."""
    top = _pa(a, _P_TOP)
    if top >= _NSTACK:
        return 3
    _push(a, top, _np1(a, pc), _pa(a, _P_SP), 0 - 1, 0)
    _spa(a, _P_TOP, top + 1)
    _spa(a, _P_PC, _np0(a, pc))
    return 2


def _st_save(a, pc: Int) -> Int:
    """SAVE: record a group boundary, and remember what was there."""
    top = _pa(a, _P_TOP)
    if top >= _NSTACK:
        return 3
    base = _b(a, _PPROG + pc * 8 + 1)
    kind = _b(a, _PPROG + pc * 8 + 2)
    sp = _pa(a, _P_SP)
    nxt = _next(a, pc)
    if kind == 1:
        w = base + 1
        v = sp
    elif kind == 2:
        w = base
        v = 0 - 1
    elif kind == 3:
        w = base + 1
        v = 0 - 1
    else:
        w = base
        v = sp
    _push(a, top, nxt, sp, w, _g4s(a, _PSAVE + w * 4))
    _spa(a, _P_TOP, top + 1)
    _s4(a, _PSAVE + w * 4, v)
    _spa(a, _P_PC, nxt)
    return 2


def _st_match(a, mode: Int, n: Int) -> Int:
    """MATCH: the whole program matched, if the mode allows where it ends.

    The whole match's own span is recorded here and not in the save area: the
    save area holds one pair per CAPTURING group and the whole match is not a
    group, so slot 0 would be a fiction that only the reader of the arena could
    mistake for a real one.

    Mode 3 is CPython's NOT-EMPTY: the match must consume something. It is
    what the scan below needs after an empty match, and it is not a spelling
    of anything CPython exposes — it is `re.finditer`'s rule that after an
    empty match the next one starts at the SAME position and must be non-empty,
    which measured as `finditer("a*?", "aaa")` giving (0,0) (0,1) (1,1) (1,2)
    (2,2) (2,3) (3,3).
    """
    if mode == 2:
        if _pa(a, _P_SP) == n:
            _spa(a, _P_MEND, _pa(a, _P_SP))
            return 1
        return 0
    if mode == 3:
        if _pa(a, _P_SP) > _pa(a, _P_MSTART):
            _spa(a, _P_MEND, _pa(a, _P_SP))
            return 1
        return 0
    _spa(a, _P_MEND, _pa(a, _P_SP))
    return 1


def _step(a, subj, n: Int, mode: Int, flags: Int) -> Int:
    """One opcode. 0 failed (backtrack), 1 matched, 2 advanced, 3 out of room."""
    pc = _pa(a, _P_PC)
    op = _b(a, _PPROG + pc * 8)
    if op == 1:
        if _st_char(a, subj, n, flags) == 1:
            _spa(a, _P_PC, _next(a, pc))
            return 2
        return 0
    if op == 3:
        if _st_class(a, subj, n, flags) == 1:
            _spa(a, _P_PC, _next(a, pc))
            return 2
        return 0
    if op == 2:
        if _st_any(a, subj, n, flags) == 1:
            _spa(a, _P_PC, _next(a, pc))
            return 2
        return 0
    if op == 4:
        return _st_split(a, pc)
    if op == 5:
        _spa(a, _P_PC, _np0(a, pc))
        return 2
    if op == 6:
        return _st_save(a, pc)
    if op == 7:
        if _bol(a, subj, _pa(a, _P_SP), flags) == 1:
            _spa(a, _P_PC, _next(a, pc))
            return 2
        return 0
    if op == 8:
        if _eol(a, subj, _pa(a, _P_SP), n, flags) == 1:
            _spa(a, _P_PC, _next(a, pc))
            return 2
        return 0
    if op == 9:
        if _worb(a, subj, _pa(a, _P_SP), n, _b(a, _PPROG + pc * 8 + 1)) == 1:
            _spa(a, _P_PC, _next(a, pc))
            return 2
        return 0
    if op == 11:
        return 0
    return _st_match(a, mode, n)


def _back(a) -> Int:
    """Unwind one choice. 0 if there is none left."""
    top = _pa(a, _P_TOP)
    if top == 0:
        return 0
    top = top - 1
    _spa(a, _P_TOP, top)
    o = top * 16
    _spa(a, _P_PC, _g4(a, _PSTACK + o))
    _spa(a, _P_SP, _g4(a, _PSTACK + o + 4))
    slot = _g4s(a, _PSTACK + o + 8)
    if slot >= 0:
        _s4(a, _PSAVE + slot * 4, _g4(a, _PSTACK + o + 12))
    return 1


def _run(a, subj, sp0: Int, n: Int, mode: Int, budget: Int) -> Int:
    """Match from one start position. 1 matched, 0 not, 2 out of budget.

    `mode` 0 is a search (entry at node 2), 1 is `match` (entry at node 0,
    which is the JMP that puts the program at position 0) and 2 is
    `fullmatch`, which is the same plus "and it ends at the end".

    `pc`, `sp` and the stack depth live in the arena rather than in locals.
    That is not a style choice: this function was the one shape the register
    allocator could not give a home to (see the module docstring), and moving
    the three words out of the frame is what made it lowerable at all.
    """
    if mode == 1 or mode == 2:
        _spa(a, _P_PC, 0)
    else:
        _spa(a, _P_PC, _pa(a, _P_ENTRY))
    _spa(a, _P_SP, sp0)
    _spa(a, _P_TOP, 0)
    _spa(a, _P_MSTART, sp0)
    steps = 0
    flags = _pa(a, _P_FLAGS)
    while 1:
        steps = steps + 1
        if steps > budget:
            _spa(a, _P_STEPS, steps)
            return 2
        r = _step(a, subj, n, mode, flags)
        if r == 3:
            _spa(a, _P_STEPS, steps)
            return 2
        if r == 1:
            _spa(a, _P_STEPS, steps)
            return 1
        if r == 0:
            if _back(a) == 0:
                _spa(a, _P_STEPS, steps)
                return 0
    return 0


def _steplim() -> Int:
    """How many VM steps one call may take. A FUNCTION, not a constant.

    A module-level name that is the RIGHT-HAND SIDE of an assignment is
    treated as a local by the register allocator and gets no home — measured,
    and the third of the three allocator limits in the module docstring. A
    read at a use site, and a read inside a call, are both fine; so this is
    the one shape that works, and `STEP_LIMIT` below is the same number
    through it rather than a second literal.
    """
    return 400000


def _vm(a, subj, at: Int, n: Int, mode: Int) -> Int:
    """The first match at or after `at`. The group saves are left in the arena.

    `mode` 1 and 2 try ONE start position, not every one: `re.match` and
    `re.fullmatch` are anchored, and trying sp0 = 1 after sp0 = 0 failed made
    `re.fullmatch("", "abc")` report a match, because an empty match at the end
    of the subject ends where a full match must end.
    """
    budget = _steplim()
    sp0 = at
    while sp0 <= n:
        _zero_saves(a)
        r = _run(a, subj, sp0, n, mode, budget)
        if r == 1:
            return 1
        if r == 2:
            return 2
        if mode != 0:
            return 0
        budget = budget - _pa(a, _P_STEPS)
        if budget <= 0:
            return 2
        sp0 = sp0 + 1
    return 0


def _slab(a, g: Int) -> Int:
    """Group `g`'s start offset in the save area."""
    return _PSAVE + g * 8


# ── ANSWERS ─────────────────────────────────────────────────────────────────

def _put_spans(out, a, g: Int) -> Int:
    """The whole match and groups 1..g-1 into `out`, two words each."""
    out[0] = _pa(a, _P_MSTART)
    out[1] = _pa(a, _P_MEND)
    k = 1
    while k <= g:
        out[2 * k] = _g4s(a, _slab(a, k))
        out[2 * k + 1] = _g4s(a, _slab(a, k) + 4)
        k = k + 1
    return 0


def _fits(out, n: Int, need: Int) -> Int:
    """1 if `out` has room for `need` words.

    `out` is unused on purpose: a list on this path is a plain array with no
    readable count, so the capacity can only be something the caller says.
    """
    if n >= need:
        return 1
    return 0


def _blanks(out, n: Int) -> Int:
    """`out`'s first `n` words filled with "no match".

    A caller that ignores the status then reads -1 rather than whatever the
    arena happened to hold. The count is the PATTERN'S group count rather than
    a fixed 18, and on the refusal paths it is the CAPACITY rather than that,
    because a list subscript out of range on this path is a silent `exit(1)`
    with nothing printed and this is the code that would have caused it.
    """
    i = 0
    while i < n:
        out[i] = 0 - 1
        i = i + 1
    return 0


def _empty() -> Pointer[UInt8]:
    """A one-byte buffer holding the empty string, for the failure answers."""
    return str_alloc(0)


def _slice(s, lo: Int, hi: Int) -> Pointer[UInt8]:
    """`s[lo:hi]`, in a `malloc`'d buffer the CALLER owns."""
    if hi <= lo:
        return _empty()
    return str_copy(str_alloc(hi - lo), s + lo, hi - lo)


def _gspan(a, g: Int) -> Int:
    """Group `g`'s end, or -1."""
    if _g4s(a, _slab(a, g)) < 0:
        return 0 - 1
    return _g4s(a, _slab(a, g) + 4)


# ── THE PUBLIC SURFACE ───────────────────────────────────────────────────────
#
# Each of these compiles the pattern itself, because a compiled pattern has
# nowhere to live between calls on this path. `out` is always the caller's
# list, and every function that writes into one takes its CAPACITY as the
# second argument and refuses with `STATUS_LIMIT` rather than writing past it.
#
# The capacity is a parameter and is NOT read out of the list because a list
# here is a plain array — `st = [7, 8, 9]; st[0]` is 7, not a count — and a
# store past its end is a SILENT `exit(1)` with nothing printed (measured). A
# library that reports a caller's sizing mistake by exiting the process is
# reporting it in the one way the caller cannot act on, so the size the caller
# was going to get wrong anyway is now the one thing it has to pass.

def search(out, n: Int, pattern: String, subject: String, flags: Int) -> Int:
    """The first match anywhere in `subject`. The status; `out` the spans.

    `n` is `out`'s capacity and must be at least
    `2 * (re.ngroups(pattern) + 1)`, which is the one size a caller has to
    know; a smaller one is `STATUS_LIMIT` and `out` is blanked, never a store
    past the end.
    """
    a = _arena()
    e = _prepare(a, pattern, flags)
    if e != 0:
        _blanks(out, n)
        return e
    g = _pa(a, _P_NG)
    if _fits(out, n, 2 * (g + 1)) == 0:
        _blanks(out, n)
        return STATUS_LIMIT()
    _blanks(out, 2 * (g + 1))
    r = _vm(a, subject, 0, str_len(subject), 0)
    if r == 1:
        _put_spans(out, a, g)
    return r


def match_at(out, n: Int, pattern: String, subject: String, flags: Int) -> Int:
    """A match anchored at position 0. `re.match`, not `re.search`."""
    a = _arena()
    e = _prepare(a, pattern, flags)
    if e != 0:
        _blanks(out, n)
        return e
    g = _pa(a, _P_NG)
    if _fits(out, n, 2 * (g + 1)) == 0:
        _blanks(out, n)
        return STATUS_LIMIT()
    _blanks(out, 2 * (g + 1))
    r = _vm(a, subject, 0, str_len(subject), 1)
    if r == 1:
        _put_spans(out, a, g)
    return r


def fullmatch(out, n: Int, pattern: String, subject: String, flags: Int) -> Int:
    """A match that starts at 0 and ends at the end of the subject."""
    a = _arena()
    e = _prepare(a, pattern, flags)
    if e != 0:
        _blanks(out, n)
        return e
    g = _pa(a, _P_NG)
    if _fits(out, n, 2 * (g + 1)) == 0:
        _blanks(out, n)
        return STATUS_LIMIT()
    _blanks(out, 2 * (g + 1))
    r = _vm(a, subject, 0, str_len(subject), 2)
    if r == 1:
        _put_spans(out, a, g)
    return r


def group_start(pattern: String, subject: String, flags: Int, k: Int) -> Int:
    """Where group `k` starts in the first match, or -1."""
    a = _arena()
    e = _prepare(a, pattern, flags)
    if e != 0:
        return 0 - 1
    if _vm(a, subject, 0, str_len(subject), 0) != 1:
        return 0 - 1
    if k < 1 or k > _pa(a, _P_NG):
        return 0 - 1
    return _g4s(a, _slab(a, k))


def group_end(pattern: String, subject: String, flags: Int, k: Int) -> Int:
    """Where group `k` ends in the first match, or -1."""
    a = _arena()
    e = _prepare(a, pattern, flags)
    if e != 0:
        return 0 - 1
    if _vm(a, subject, 0, str_len(subject), 0) != 1:
        return 0 - 1
    if k < 1 or k > _pa(a, _P_NG):
        return 0 - 1
    return _gspan(a, k)


def group_text(status, n: Int, pattern: String, subject: String, flags: Int,
               k: Int) -> Pointer[UInt8]:
    """Group `k`'s text, in a buffer the CALLER owns. `""` if there is none.

    `k` 0 is the WHOLE match, as in CPython's `m.group(0)`, and it is answered
    from the two words the VM records at MATCH rather than from the save area
    — the whole match is not a group and pretending it is would put a span in
    the save slots that no group owns.

    `n` is `status`'s capacity and must be at least 1, like every other list
    this module writes into. It is the same rule for one word as for six, and
    having it for one word is what keeps the rule a rule.
    """
    if n < 1:
        return _empty()
    a = _arena()
    e = _prepare(a, pattern, flags)
    if e != 0:
        status[0] = e
        return _empty()
    r = _vm(a, subject, 0, str_len(subject), 0)
    if r != 1:
        status[0] = r
        return _empty()
    if k == 0:
        status[0] = 1
        return _slice(subject, _pa(a, _P_MSTART), _pa(a, _P_MEND))
    if k < 1 or k > _pa(a, _P_NG):
        status[0] = 0
        return _empty()
    status[0] = 1
    return _slice(subject, _g4s(a, _slab(a, k)), _gspan(a, k))


def _scan(a, subj, n: Int, pos: Int) -> Int:
    """The next match of the scan `findall`, `split` and `sub` perform.

    0 no more, 1 a match (in the arena), 2 gave up. The position to continue
    at is `_P_NEXT`, and after an EMPTY match it is the SAME position with
    `_P_PHASE` set: the next call is the non-empty match CPython requires there.
    That rule is not a detail — `finditer("a*?", "aaa")` alternates empty and
    non-empty at every position, and a scan that simply steps past an empty
    match gets `['a', 'a', 'a']` where CPython gets `['', 'a', '', 'a', ...]`.
    """
    if _pa(a, _P_PHASE) == 1:
        _spa(a, _P_PHASE, 0)
        r = _vm(a, subj, pos, n, 3)
        if r == 1:
            _spa(a, _P_NEXT, _pa(a, _P_MEND))
            return 1
        if r == 2:
            return 2
        # No non-empty match HERE, so the next one starts at the next
        # position — the scan continues rather than stopping, which is the
        # difference between `findall("a*", "bbb")` giving four empty strings
        # and giving one.
        pos = pos + 1
    r = _vm(a, subj, pos, n, 0)
    if r == 0:
        return 0
    if r == 2:
        return 2
    if _pa(a, _P_MEND) > _pa(a, _P_MSTART):
        _spa(a, _P_NEXT, _pa(a, _P_MEND))
        _spa(a, _P_PHASE, 0)
        return 1
    _spa(a, _P_NEXT, _pa(a, _P_MSTART))
    _spa(a, _P_PHASE, 1)
    return 1


def findall(out, n: Int, pattern: String, subject: String, flags: Int,
          maxn: Int) -> Int:
    """Every match, up to `maxn` of them. `out[0]` the status, `out[1..]` spans.

    The span recorded is what `re.findall` would return as a STRING: the whole
    match when the pattern has no group, group 1 when it has exactly one. A
    pattern with two or more groups has `findall` return tuples, which is more
    than one span, so the whole match is recorded and the difference is stated
    at this function rather than papered over.

    The scan is CPython's, empty matches included; see `_scan`.
    """
    a = _arena()
    if _fits(out, n, 1 + 2 * maxn) == 0:
        out[0] = STATUS_LIMIT()
        return 0
    out[0] = 0
    e = _prepare(a, pattern, flags)
    if e != 0:
        out[0] = e
        return 0
    n = str_len(subject)
    g = _pa(a, _P_NG)
    pos = 0
    cnt = 0
    while cnt < maxn and pos <= n:
        r = _scan(a, subject, n, pos)
        if r == 0:
            break
        if r == 2:
            out[0] = 2
            return cnt
        if g == 1:
            s0 = _g4s(a, _slab(a, 1))
            s1 = _gspan(a, 1)
        else:
            s0 = _pa(a, _P_MSTART)
            s1 = _pa(a, _P_MEND)
        out[1 + cnt * 2] = s0
        out[2 + cnt * 2] = s1
        cnt = cnt + 1
        pos = _pa(a, _P_NEXT)
    out[0] = 1
    return cnt


def sub(status, pattern: String, repl: String, subject: String,
        flags: Int, count: Int) -> Pointer[UInt8]:
    """`re.sub`, in a buffer the CALLER owns. `count` 0 means every match.

    The template understands `\\1`..`\\9`, `\\g<1>`, `\\g<name>` and `\\\\`,
    which is what the corpus uses. It does NOT re-expand a general Python
    string escape in the replacement, because a string literal on this path is
    interned VERBATIM (`os/__init__.mojo`'s `linesep` is the measurement), so
    a `\\n` the caller wrote is two characters and stays two characters.

    **`status` IS NOT THE `n`-TH ARGUMENT every other writer here takes, and
    that is a fact rather than an oversight.** `out` in `search`/`findall`/
    `split` is written up to `2 * (ngroups + 1)` times at RUN time, so its size
    is something only the caller knows and the module has to be told; `status`
    is exactly one word at index 0, always, so there is no size to get wrong
    and no check to make. It was a parameter anyway, unread, and a second
    parameter past the sixth is what the x86-64 ABI refuses — so the one
    argument here that carried no information is the one that goes.
    """
    a = _arena()
    e = _prepare(a, pattern, flags)
    if e != 0:
        status[0] = e
        return _empty()
    n = str_len(subject)
    r = _sublen(a, subject, n, repl, count)
    if r < 0:
        status[0] = 0 - r
        return _empty()
    d = str_alloc(r)
    _subfill(a, d, subject, n, repl, count)
    status[0] = 1
    return d


def _subwalk(a, subj, n: Int, repl: String, count: Int, dst) -> Int:
    """One pass of `sub`. With `_P_W` 0 it measures, with 1 it writes.

    One function for both because the template walk is the part that is easy to
    get subtly wrong, and a second copy of it to measure would be a second
    thing to be wrong about. `dst` is the caller's buffer; how much of it is
    written is `_P_USED`, set by `_sublen` and `_subfill` before the walk and
    advanced by every helper in it.
    """
    pos = 0
    prev = 0
    nsub = 0
    while pos <= n:
        if count > 0 and nsub >= count:
            break
        r = _scan(a, subj, n, pos)
        if r == 2:
            return 0 - 2
        if r == 0:
            break
        s0 = _pa(a, _P_MSTART)
        s1 = _pa(a, _P_MEND)
        _emit(a, subj, prev, s0, dst)
        _repcopy(a, dst, repl, subj)
        prev = s1
        nsub = nsub + 1
        pos = _pa(a, _P_NEXT)
    return _emit(a, subj, prev, n, dst)


def _emit(a, subj, lo: Int, hi: Int, dst) -> Int:
    """Subject bytes `lo..hi` into the result. The new `used`."""
    u = _pa(a, _P_USED)
    if hi <= lo:
        return u
    if _pa(a, _P_W) == 1:
        u = str_put(dst, u, subj + lo, hi - lo)
    else:
        u = u + (hi - lo)
    _spa(a, _P_USED, u)
    return u


def _repcopy(a, dst, repl: String, subj) -> Int:
    """The template, expanded, into the result. The new `used`.

    THE OUTPUT-BUFFER STATE IS IN THE ARENA (`_P_USED`, `_P_W`), and every
    helper that advances it publishes it there and returns it. It was a
    trailing `used, w` parameter instead, threaded through all seven of these
    functions, which is what put three of them past the six integer argument
    registers the x86-64 ABI passes and made this module unbuildable there —
    see the comment on `_P_USED`. `dst` stays a parameter: it is the CALLER's
    buffer, one word wide, and it is the one thing here that is not per-call
    state this module owns.
    """
    i = 0
    nr = str_len(repl)
    used = _pa(a, _P_USED)
    w = _pa(a, _P_W)
    while i < nr:
        c = _b(repl, i)
        if c == 92:
            i = i + 1
            if i >= nr:
                if w == 1:
                    _sb(dst, used, 92)
                used = used + 1
                break
            d = _b(repl, i)
            if d == 103:                      # \g<…>
                used = _gref(a, dst, repl, subj, i + 1)
                i = _gskip(repl, i + 1)
            elif d == 92:
                if w == 1:
                    _sb(dst, used, 92)
                used = used + 1
                i = i + 1
            elif d >= 48 and d <= 57:
                used = _gput(a, dst, d - 48, subj)
                i = i + 1
            else:
                if w == 1:
                    _sb(dst, used, d)
                used = used + 1
                i = i + 1
        else:
            if w == 1:
                _sb(dst, used, c)
            used = used + 1
            i = i + 1
    _spa(a, _P_USED, used)
    return used


def _gskip(repl, i: Int) -> Int:
    """The index just past a `\\g<…>` whose `<` is at `i`."""
    while i < str_len(repl):
        if _b(repl, i) == 62:
            return i + 1
        i = i + 1
    return i


def _gref(a, dst, repl: String, subj, i: Int) -> Int:
    """`\\g<n>` or `\\g<name>`. A name is not looked up: the number is read."""
    v = 0
    got = 0
    while i < str_len(repl):
        c = _b(repl, i)
        if c == 62:
            break
        if c >= 48 and c <= 57:
            v = v * 10 + (c - 48)
            got = 1
            i = i + 1
        else:
            i = i + 1
    if got == 0:
        return _pa(a, _P_USED)
    return _gput(a, dst, v, subj)


def _gput(a, dst, g: Int, subj) -> Int:
    """Group `g`'s text, if that group exists and matched.

    The existence test lives HERE and not at the two call sites, so there is
    one of it: a `\9` in a template with three groups is a no-op rather than a
    second spelling of the same question.
    """
    if g >= _pa(a, _P_NG):
        return _pa(a, _P_USED)
    lo = _g4s(a, _slab(a, g))
    hi = _gspan(a, g)
    return _emit(a, subj, lo, hi, dst)


def _sublen(a, subj, n: Int, repl: String, count: Int) -> Int:
    """The result's length, or the negated status if there is not one."""
    _spa(a, _P_USED, 0)
    _spa(a, _P_W, 0)
    r = _subwalk(a, subj, n, repl, count, 0)
    if r < 0:
        return 0 - r
    return r


def _subfill(a, dst, subj, n: Int, repl: String, count: Int) -> Int:
    _spa(a, _P_USED, 0)
    _spa(a, _P_W, 1)
    return _subwalk(a, subj, n, repl, count, dst)


def split(out, n: Int, pattern: String, subject: String, flags: Int,
          maxn: Int) -> Int:
    """`re.split`, as the SPANS of its pieces, up to `maxn`. `out[0]` status.

    The captured groups are pieces, in order, exactly as CPython puts them:
    `re.split(r'(\s)', 'a b')` is `['a', ' ', 'b']`, and the middle piece here
    is group 1's span. A group that did not participate is STILL a piece, with
    the span (-1, -1): `re.split("(a)?b", "b")` is `['', None, '']` and the
    count is three, so dropping it would be a shorter answer rather than a
    different one. (-1, -1) reads back as the empty string, which is what a
    caller can do with a piece that has no span.

    The scan is CPython's, empty matches included; see `_scan`.
    """
    a = _arena()
    if _fits(out, n, 1 + 2 * maxn) == 0:
        out[0] = STATUS_LIMIT()
        return 0
    out[0] = 0
    e = _prepare(a, pattern, flags)
    if e != 0:
        out[0] = e
        return 0
    n = str_len(subject)
    g = _pa(a, _P_NG)
    pos = 0
    prev = 0
    cnt = 0
    while cnt < maxn and pos <= n:
        r = _scan(a, subject, n, pos)
        if r == 0:
            break
        if r == 2:
            out[0] = 2
            return cnt
        s0 = _pa(a, _P_MSTART)
        s1 = _pa(a, _P_MEND)
        if cnt < maxn:
            out[1 + cnt * 2] = prev
            out[2 + cnt * 2] = s0
            cnt = cnt + 1
        k = 1
        while k <= g and cnt < maxn:
            out[1 + cnt * 2] = _g4s(a, _slab(a, k))
            out[2 + cnt * 2] = _gspan(a, k)
            cnt = cnt + 1
            k = k + 1
        prev = s1
        pos = _pa(a, _P_NEXT)
    if cnt < maxn:
        out[1 + cnt * 2] = prev
        out[2 + cnt * 2] = n
        cnt = cnt + 1
    out[0] = 1
    return cnt


def _special(c: Int) -> Int:
    """1 if `re.escape` puts a backslash in front of this byte.

    CPython 3.7+ escapes exactly these 24, and the set is measured rather than
    remembered: `re.escape` is applied to each of the 256 code points and the
    ones that come back changed are these.
    """
    if c == 9 or c == 10 or c == 11 or c == 12 or c == 13 or c == 32:
        return 1
    if c == 35 or c == 36 or c == 38 or c == 40 or c == 41 or c == 42:
        return 1
    if c == 43 or c == 45 or c == 46 or c == 63 or c == 91 or c == 92:
        return 1
    if c == 93 or c == 94 or c == 123 or c == 124 or c == 125 or c == 126:
        return 1
    return 0


def escape(s) -> Pointer[UInt8]:
    """`re.escape`, in a buffer the CALLER owns."""
    n = str_len(s)
    d = str_alloc(n * 2)
    i = 0
    used = 0
    while i < n:
        c = _b(s, i)
        if _special(c) == 1:
            str_put(d, used, "\\", 1)
            used = used + 1
        used = str_put(d, used, s + i, 1)
        i = i + 1
    return d


def ngroups(pattern: String) -> Int:
    """How many capturing groups the pattern has, or 0 if it will not compile."""
    a = _arena()
    if _prepare(a, pattern, 0) != 0:
        return 0
    return _pa(a, _P_NG)


def nl() -> Pointer[UInt8]:
    """A one-byte buffer holding a newline, for a caller building a subject.

    A string literal on this path is interned verbatim and its escapes are NOT
    unescaped, so a `\\n` written in a program is the two characters `\\` and
    `n` — measured, and written down at `os/__init__.mojo`'s `linesep`. A
    pattern can still MATCH a newline (`\\n` in a pattern is an escape and is
    parsed as one); it is a subject that has to be BUILT to contain one.
    """
    var p: Pointer[UInt8] = str_alloc(1)
    memset(p, 10, 1)
    return p


# ── FLAGS AND LIMITS, as functions because a name is not readable ───────────

def IGNORECASE():
    """`re.IGNORECASE`."""
    return 2


def MULTILINE():
    """`re.MULTILINE`."""
    return 8


def DOTALL():
    """`re.DOTALL`."""
    return 16


def VERBOSE():
    """`re.VERBOSE`."""
    return 64


def ASCII():
    """`re.ASCII` — accepted and ignored; this engine is byte-oriented."""
    return 256


def UNICODE():
    """`re.UNICODE` — accepted and ignored; this engine is byte-oriented."""
    return 32


def STATUS_OK():
    return 1


def STATUS_NO():
    return 0


def STATUS_LIMIT():
    return 2


def STATUS_UNSUPPORTED():
    return 3


def MAXGROUPS():
    """How many capturing groups a pattern may have."""
    return 8


def MAXPATTERN():
    """The longest pattern, in bytes."""
    return 128


def MAXSTACK():
    """How many pending backtracking choices a run may hold."""
    return 1024


def STEP_LIMIT():
    """How many VM steps one call may take before it reports LIMIT."""
    return _steplim()




