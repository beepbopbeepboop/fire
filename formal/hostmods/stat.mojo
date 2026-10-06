"""`stat` — file-mode constants, the `S_IS*` predicates and `filemode`.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import stat` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` for why these did NOT go at
the repository root, where the first three of them captured `import os` in the
compiler's own sources.

WHAT CPython's `stat` IS, AND WHY IT IS A LEAF
----------------------------------------------
The module is thirty-odd MODE CONSTANTS, eight `S_IS*` PREDICATES over a mode
integer, `S_IFMT`/`S_IMODE` over the same integer, and `filemode`, which turns
a mode integer into a ten-character string. There is no `stat()` call here at
all: CPython puts the syscall in `os.stat` and this module is only the
vocabulary for reading its answer. That makes it the only host module in this
directory with no dependency on the C library and no dependency on `os` —
which is the reason it is worth writing first, and the reason nothing in it can
be a fact about a filesystem this image happens to be sitting on. Every answer
is a function of an integer, so `test_formal_stat.py` can compare it against
CPython's own over a corpus that includes the modes no real file has.

  * A CONSTANT IS A CALL. `stat.S_IRUSR` is a module-level name, and a
    module-level name is not exported as a word across a dylib boundary —
    there is no storage for one, because every value a formal program can name
    lives in a function's own stack scratch
    (`bugs/FORMAL_module_state_no_storage.md`). So `S_IRUSR()` is a
    zero-argument function and `stat.S_IRUSR` is spelled `S_IRUSR()`. This is
    the same rule `os.sep()` follows and the same reason
    (`formal/hostmods/os/__init__.mojo` says it at length). The
    expression `mode | stat.S_IXUSR` therefore reads
    `mode | stat.S_IXUSR()`, which is what `build_mojo_cli.py:465` will have to
    spell — and it is worth knowing that BEFORE a compiler wants it, because
    that line is the reason this module exists: it is the one file in the
    arm64 sweep whose only host import was `stat`.

  * THE PREDICATES ARE NOT FUNCTIONS OVER A MODE, THEY ARE `(mode & S_IFMT)
    == S_IFxxx`, which is one `and` and one compare.

  * A PREDICATE RETURNS 1 OR 0, never a bool. `bool` is a type this path
    erases to a word (`bugs/FORMAL_bool_...` — see `test_formal_os.py`'s
    `isfile`, which has the same shape), and every host module here returns
    the integer.

  * NO FUNCTION HERE NEEDS MORE THAN ONE PARAMETER, which is why this module
    builds on x86-64 as well as arm64: SysV x86-64 passes six integer
    arguments in registers, and a seventh is refused rather than spilled
    (`bugs/FORMAL_x86_64_argument_registers.md`, which is what keeps
    `fnmatch.mojo` in `test_formal_hostmods_census.py`'s known-red list).

  * A MODE IS SIXTEEN BITS, AND A MODE OUTSIDE THAT IS -1, NOT A MASKED
    ANSWER. CPython's `stat` spells its parameter `mode_t`, which on this
    platform is an unsigned SHORT, so every one of its functions raises
    `OverflowError` for anything outside 0..65535 — measured, not quoted:
    `stat.S_IFMT(0o200000)`, `stat.S_IMODE(-1)` and `stat.filemode(0xFFFFFFFF)`
    all raise, and 65535 is the largest mode any of them answers. A 64-bit word
    here is a `mode_t` widened, so the widening is visible to the program and
    has to be given an answer. CPython's answer is an exception and this path
    has none (FORMAL.md phase 7), so the answer is a STATUS, which is what a
    failure is everywhere else in this directory (`os.remove` returns -1
    rather than raising `FileNotFoundError`). Masking the low sixteen bits
    instead would be the failure this module exists to avoid: `S_IFMT(0o200000)`
    would print as `S_IFMT(0)` and agree with nothing, and `filemode(0x100000)`
    would be a perfectly plausible ten-character string about a mode that does
    not exist.

WHAT IS HERE
------------
  * Every `S_I*` permission constant and every `S_IF*` type constant this
    platform spells. The `ST_*` indices too (`ST_MODE` … `ST_CTIME`): they are
    the positions `os.stat_result` puts its fields in, and a caller that
    indexes a result needs them.
  * `S_IFMT(mode)` and `S_IMODE(mode)`, which CPython spells as functions, so
    the spelling matches.
  * `S_ISREG`, `S_ISDIR`, `S_ISLNK`, `S_ISSOCK`, `S_ISBLK`, `S_ISCHR`,
    `S_ISFIFO` — the seven this platform compiles.
  * `filemode(mode)`, CPython's own table including its two corner rules: a
    mode with no type bits at all is `?` in the first column, and a setuid /
    setgid / sticky execute bit prints as `s` / `s` / `t` rather than as both a
    letter and an `x`.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `S_ISDOOR`, `S_ISPORT`, `S_ISWHT` — CPython DEFINES them and on this
    platform they answer `False` for every input, which is measurable rather
    than a guess: `stat.S_ISDOOR(x)` is `False` for all fifteen modes in
    `test_formal_stat.py`'s `absent` reasoning, `S_ISPORT` and `S_ISWHT`
    likewise, because macOS's `stat(2)` has no such file type and CPython's C
    implementation of the three is compiled out. Answering "no" is what CPython
    does here and would be right; answering "no" on a platform that HAS
    whiteouts would be a plausible wrong answer, and a plausible wrong answer
    to "is this a whiteout" is the failure `formal/hostmods/time.mojo` refuses
    to ship. So the three predicates are ABSENT and a caller spelling one gets
    the export map's refusal naming the name. Their CONSTANTS (`S_IFDOOR()`,
    `S_IFPORT()`, `S_IFWHT()`) are here, because a constant is a number and this
    platform's number is measured — `S_IFDOOR` and `S_IFPORT` are 0 and
    `S_IFWHT` is 0o160000 here, and a reader who wants to compare a mode
    against them is comparing numbers, which is a question this path can
    answer.

  * `os.stat_result`, `os.statvfs_result`, `os.lstat` — those are `os`, not
    `stat`, and a stat result is a STRUCT, which is a frame blob that cannot
    cross a dylib boundary (`bugs/FORMAL_time_struct_shaped_answers.md`).
    `formal/hostmods/os/_syscalls.mojo` already has the `stat(2)` call and the
    byte-wise reader for its fields (`fs_stat_field64`, `fs_stat_mode`), so
    what is missing there is the `os.stat(...)` SHAPE — a named tuple — and
    that is `bugs/FORMAL_time_struct_shaped_answers.md`'s subject, not this
    one's. This module deliberately does not re-export the syscall under a
    second name: one reader of `struct stat` in this tree is the answer.

  * `FILE_ATTRIBUTE_*` — WINDOWS attribute bits, on a platform whose
    `stat(2)` has no such field. `test_formal_stat.py` asserts they are absent
    rather than exporting a plausible number under a name CPython has and this
    target does not mean.
"""

from os._syscalls import str_alloc, str_put


# ── the permission bits ─────────────────────────────────────────────────────
#
# 9 bits, three classes of three, and the class order in `filemode` below is
# this order. The values are POSIX's and are the same on every platform this
# backend targets; `test_formal_stat.py` reads each one out of CPython's own
# `stat` module rather than from this comment.

def S_ISUID() -> int:
    """`S_ISUID`: 0o4000 — the set-user-ID bit, the execute bit's class-mate."""
    return 2048

def S_ISGID() -> int:
    """`S_ISGID`: 0o2000 — the set-group-ID bit."""
    return 1024

def S_ISVTX() -> int:
    """`S_ISVTX`: 0o1000 — the sticky bit.

    Named `ISVTX` and not `ISVTX`/`ISTTY` because that is how CPython spells
    it, and a mirror that renamed a name would be wrong in the one way a
    caller cannot check for itself.
    """
    return 512

def S_IRUSR() -> int:
    """`S_IRUSR`: 0o400 — read by the owner."""
    return 256

def S_IWUSR() -> int:
    """`S_IWUSR`: 0o200 — written by the owner."""
    return 128

def S_IXUSR() -> int:
    """`S_IXUSR`: 0o100 — executed by the owner."""
    return 64

def S_IRGRP() -> int:
    """`S_IRGRP`: 0o40 — read by the group."""
    return 32

def S_IWGRP() -> int:
    """`S_IWGRP`: 0o20 — written by the group."""
    return 16

def S_IXGRP() -> int:
    """`S_IXGRP`: 0o10 — executed by the group."""
    return 8

def S_IROTH() -> int:
    """`S_IROTH`: 0o4 — read by others."""
    return 4

def S_IWOTH() -> int:
    """`S_IWOTH`: 0o2 — written by others."""
    return 2

def S_IXOTH() -> int:
    """`S_IXOTH`: 0o1 — executed by others."""
    return 1

def S_IRWXU() -> int:
    """`S_IRWXU`: 0o700 — all three for the owner."""
    return 448

def S_IRWXG() -> int:
    """`S_IRWXG`: 0o070 — all three for the group."""
    return 56

def S_IRWXO() -> int:
    """`S_IRWXO`: 0o007 — all three for others."""
    return 7

def S_IREAD() -> int:
    """`S_IREAD`: 0o400 — the historical spelling of `S_IRUSR`.

    CPython exports it and so does this module; it is an ALIAS, not a new bit,
    and the fact that it is one is why `test_formal_stat.py` checks it against
    `S_IRUSR`'s value rather than against a table.
    """
    return 256

def S_IWRITE() -> int:
    """`S_IWRITE`: 0o200 — the historical spelling of `S_IWUSR`."""
    return 128

def S_IEXEC() -> int:
    """`S_IEXEC`: 0o100 — the historical spelling of `S_IXUSR`."""
    return 64

def S_ENFMT() -> int:
    """`S_ENFMT`: 0o4000, the encoding flag `ls -l` prints as `@`.

    A Darwin extension rather than a POSIX one, exported because CPython
    exports it and this platform's number is the same number CPython reports.
    Nothing below reads it: `filemode` prints the mode's permissions and type
    only, which is what CPython's own `filemode` prints.
    """
    return 1024


# ── the file-type bits ──────────────────────────────────────────────────────
#
# The high twelve bits of a mode, and the mask that selects them. `S_IFDOOR`
# and `S_IFPORT` are 0 on this platform, which is a fact about macOS and not a
# mistake in the table: both are 0 in CPython's own `stat` here, and the two
# predicates that go with them are not compiled (see the docstring's "WHAT IS
# NOT HERE").

def S_IFREG() -> int:
    """`S_IFREG`: 0o100000 — a regular file."""
    return 32768

def S_IFDIR() -> int:
    """`S_IFDIR`: 0o040000 — a directory."""
    return 16384

def S_IFLNK() -> int:
    """`S_IFLNK`: 0o120000 — a symbolic link."""
    return 40960

def S_IFSOCK() -> int:
    """`S_IFSOCK`: 0o140000 — a socket.

    `S_IFSOCK == S_IFREG | S_IFDIR`, which is why `filemode` below tests it
    BEFORE `S_IFREG`: a plain `== S_IFMT` chain in the wrong order answers `?`
    for every socket. CPython's own table says so in a comment and gets the
    order right; this module copies the order, not the idea.
    """
    return 49152

def S_IFCHR() -> int:
    """`S_IFCHR`: 0o020000 — a character special file."""
    return 8192

def S_IFBLK() -> int:
    """`S_IFBLK`: 0o060000 — a block special file."""
    return 24576

def S_IFIFO() -> int:
    """`S_IFIFO`: 0o010000 — a FIFO."""
    return 4096

def S_IFWHT() -> int:
    """`S_IFWHT`: 0o160000 — a whiteout.

    The CONSTANT is here, `filemode` has a row for it, and `S_ISWHT` is not:
    see the docstring at the top of this file. The three answers differ and it
    is worth being exact about which is which, because the answer is not
    uniform across CPython's own implementation and this module has to be a
    mirror of what `stat.filemode` actually IS:

      * `stat.filemode(0o160000)` is `'w---------'` — the effective
        implementation is `_stat.filemode`, the C one, which
        `stat.py`'s `from _stat import *` installs OVER the table in the Python
        source. The Python table has no whiteout row; the C one does. Reading
        `stat.py` instead of asking `stat.filemode` gives a module that prints
        `?` where CPython prints `w`, which is what the first version of this
        one did and what `test_formal_stat.py`'s exhaustive sweep caught on its
        first run.
      * `stat.S_IFWHT(x)` is `False` for every `x` on this platform.
      * `stat.S_IFWHT` is the number 0o160000.

    Three names, three different answers, and only one of them is what a reader
    of `stat.py` would have predicted.
    """
    return 57344

def S_IFDOOR() -> int:
    """`S_IFDOOR`: 0 on this platform — a Solaris door.

    Zero here, and zero in CPython's own `stat` on this platform, so this is
    the platform's answer rather than a placeholder. There is no predicate for
    it, for the reason the docstring gives.
    """
    return 0

def S_IFPORT() -> int:
    """`S_IFPORT`: 0 on this platform — a Solaris event port.

    Zero here, and zero in CPython's own `stat` on this platform. See
    `S_IFDOOR`.
    """
    return 0


# ── the `os.stat_result` field indices ──────────────────────────────────────
#
# Nine indices into the tuple `os.stat()` returns. CPython exports them, so
# this does; a caller that reads a result by index needs them and a caller that
# uses them as attribute names needs the same numbers.

def ST_MODE() -> int:
    """`ST_MODE`: 0 — the file's mode, `S_IS*`'s argument."""
    return 0

def ST_INO() -> int:
    """`ST_INO`: 1 — the inode number."""
    return 1

def ST_DEV() -> int:
    """`ST_DEV`: 2 — the device the inode lives on."""
    return 2

def ST_NLINK() -> int:
    """`ST_NLINK`: 3 — how many names the inode has."""
    return 3

def ST_UID() -> int:
    """`ST_UID`: 4 — the owning user id."""
    return 4

def ST_GID() -> int:
    """`ST_GID`: 5 — the owning group id."""
    return 5

def ST_SIZE() -> int:
    """`ST_SIZE`: 6 — the size in bytes."""
    return 6

def ST_ATIME() -> int:
    """`ST_ATIME`: 7 — the access time, in seconds."""
    return 7

def ST_MTIME() -> int:
    """`ST_MTIME`: 8 — the modification time, in seconds."""
    return 8

def ST_CTIME() -> int:
    """`ST_CTIME`: 9 — the status-change time, in seconds.

    The LAST index CPython exports. `ST_BIRTHTIME` and `ST_BLOCKS` exist on
    Darwin and CPython 3.14 does not export them from `stat`, so neither does
    this module: a name this platform has but CPython does not is a number
    nobody has an oracle for, and `test_formal_stat.py`'s `absent` group pins
    that they are refused.
    """
    return 9


# ── the two accessors, and the seven predicates ─────────────────────────────

def mode_ok(mode) -> int:
    """1 when `mode` is a `mode_t`, 0 when it is out of one.

    The whole of the domain question in one function, and every entry point in
    this module asks it before it reads a bit. `mode_t` is an unsigned short on
    this platform, so the range is 0..65535 and the two tests are `>= 0` and
    `<= 65535` — written out rather than folded into one compare because a
    negative word and a word too large are the same failure and are checked the
    same way, and because a single `mode < 0 || mode > 65535` would be a
    logical operator this path lowers over a value whose kind it cannot always
    establish.
    """
    if mode < 0:
        return 0
    if mode > 65535:
        return 0
    return 1


def S_IFMT(mode) -> int:
    """`stat.S_IFMT(mode)`: the file type, as the twelve bits that hold it.

    A FUNCTION and not a constant, because CPython spells it as one — it is
    `_stat.S_IFMT`, a mask applied to an argument — and a module that renamed
    it to a zero-argument `S_IFMT()` would answer a different question under a
    name a caller is using for this one.

    -1 for a mode that is not a `mode_t`, where CPython raises `OverflowError`;
    see the docstring at the top of this file for why that is a status here.
    """
    if mode_ok(mode) == 0:
        return 0 - 1
    return mode & 61440


def S_IMODE(mode) -> int:
    """`stat.S_IMODE(mode)`: the permission bits and nothing else.

    The low NINE bits, so `S_IMODE(0o100644)` is `0o644` and not `0o100644`.
    The mask is `0o7777`, which is CPython's own: it covers the three
    permission classes and the setuid / setgid / sticky bits, and stops before
    the type bits at 0o100000.

    -1 for a mode that is not a `mode_t`, where CPython raises `OverflowError`.
    """
    if mode_ok(mode) == 0:
        return 0 - 1
    return mode & 4095


def S_ISREG(mode) -> int:
    """1 when `mode` says the thing this name asks, 0 when it does
    not, and -1 for a mode that is not a `mode_t`.

    THREE answers, not two. `0` is "no"; `-1` is "that was never a mode",
    which CPython reports as an `OverflowError` and this path reports as a
    status (FORMAL.md phase 7 — there are no exceptions here). Collapsing
    the third into the second is the plausible-wrong-answer shape this
    module's own docstring is about.
    """
    if mode_ok(mode) == 0:
        return 0 - 1
    if (mode & 61440) == 32768:
        return 1
    return 0

def S_ISDIR(mode) -> int:
    """1 when `mode` says the thing this name asks, 0 when it does
    not, and -1 for a mode that is not a `mode_t`.

    THREE answers, not two. `0` is "no"; `-1` is "that was never a mode",
    which CPython reports as an `OverflowError` and this path reports as a
    status (FORMAL.md phase 7 — there are no exceptions here). Collapsing
    the third into the second is the plausible-wrong-answer shape this
    module's own docstring is about.
    """
    if mode_ok(mode) == 0:
        return 0 - 1
    if (mode & 61440) == 16384:
        return 1
    return 0

def S_ISLNK(mode) -> int:
    """1 when `mode` says the thing this name asks, 0 when it does
    not, and -1 for a mode that is not a `mode_t`.

    THREE answers, not two. `0` is "no"; `-1` is "that was never a mode",
    which CPython reports as an `OverflowError` and this path reports as a
    status (FORMAL.md phase 7 — there are no exceptions here). Collapsing
    the third into the second is the plausible-wrong-answer shape this
    module's own docstring is about.
    """
    if mode_ok(mode) == 0:
        return 0 - 1
    if (mode & 61440) == 40960:
        return 1
    return 0

def S_ISSOCK(mode) -> int:
    """1 when `mode` says a SOCKET.

    Tested before `S_ISREG` in `filemode` because `S_IFSOCK` contains both
    `S_IFREG` and `S_IFDIR` in its bits; here the compare is against the
    twelve type bits alone, so the order does not matter for these seven.

    1 when `mode` says the thing this name asks, 0 when it does
    not, and -1 for a mode that is not a `mode_t`.

    THREE answers, not two. `0` is "no"; `-1` is "that was never a mode",
    which CPython reports as an `OverflowError` and this path reports as a
    status (FORMAL.md phase 7 — there are no exceptions here). Collapsing
    the third into the second is the plausible-wrong-answer shape this
    module's own docstring is about.
    """
    if mode_ok(mode) == 0:
        return 0 - 1
    if (mode & 61440) == 49152:
        return 1
    return 0

def S_ISBLK(mode) -> int:
    """1 when `mode` says the thing this name asks, 0 when it does
    not, and -1 for a mode that is not a `mode_t`.

    THREE answers, not two. `0` is "no"; `-1` is "that was never a mode",
    which CPython reports as an `OverflowError` and this path reports as a
    status (FORMAL.md phase 7 — there are no exceptions here). Collapsing
    the third into the second is the plausible-wrong-answer shape this
    module's own docstring is about.
    """
    if mode_ok(mode) == 0:
        return 0 - 1
    if (mode & 61440) == 24576:
        return 1
    return 0

def S_ISCHR(mode) -> int:
    """1 when `mode` says the thing this name asks, 0 when it does
    not, and -1 for a mode that is not a `mode_t`.

    THREE answers, not two. `0` is "no"; `-1` is "that was never a mode",
    which CPython reports as an `OverflowError` and this path reports as a
    status (FORMAL.md phase 7 — there are no exceptions here). Collapsing
    the third into the second is the plausible-wrong-answer shape this
    module's own docstring is about.
    """
    if mode_ok(mode) == 0:
        return 0 - 1
    if (mode & 61440) == 8192:
        return 1
    return 0

def S_ISFIFO(mode) -> int:
    """1 when `mode` says the thing this name asks, 0 when it does
    not, and -1 for a mode that is not a `mode_t`.

    THREE answers, not two. `0` is "no"; `-1` is "that was never a mode",
    which CPython reports as an `OverflowError` and this path reports as a
    status (FORMAL.md phase 7 — there are no exceptions here). Collapsing
    the third into the second is the plausible-wrong-answer shape this
    module's own docstring is about.
    """
    if mode_ok(mode) == 0:
        return 0 - 1
    if (mode & 61440) == 4096:
        return 1
    return 0


# ── filemode ────────────────────────────────────────────────────────────────
#
# CPython's own `_filemode_table`, in its own order, with its own two corner
# rules. A mode with NO type bits is `?` in the first column and a permission
# class with no bit set among the three is `-`; and the execute column prints
# ONE character for two bits, so setuid-and-execute is `s` and not `sx`. Both
# rules are load-bearing: a module that printed `rwxs` where CPython prints
# `rws` would be right about every mode that has both bits and wrong about
# every mode that has one of them, which is the majority.

def _filemode_type(mode) -> str:
    """Column 0 of `filemode`: the file type as a ONE-CHARACTER string.

    CPython's `_filemode_table` order, which is not the numeric order and
    cannot be: `S_IFSOCK == S_IFREG | S_IFDIR`, so a chain that tested
    `S_IFREG` first would answer `?` for every socket on the platform. The
    order here is the order in that table.

    A mode with no type bits at all gives `?`, which is CPython's own answer
    (`stat.filemode(0) == '?---------'`) rather than a `ValueError` — CPython
    raises only for a type that is not one of its seven, and after the twelve
    type bits are masked there is no such value, so that branch is
    unreachable and is not reimplemented.

    ONE character in a buffer of two, so the caller can append it with
    `str_put(out, u, s, 1)`: a string on this path is a NUL-terminated
    `char *`, so even one character needs somewhere to live
    (`bugs/FORMAL_string_value_model.md`).
    """
    var p: Pointer[UInt8] = str_alloc(1)
    var t = mode & 61440
    if t == 40960:
        memset(p, 108, 1)
    elif t == 49152:
        memset(p, 115, 1)
    elif t == 32768:
        memset(p, 45, 1)
    elif t == 24576:
        memset(p, 98, 1)
    elif t == 16384:
        memset(p, 100, 1)
    elif t == 8192:
        memset(p, 99, 1)
    elif t == 4096:
        memset(p, 112, 1)
    elif t == 57344:
        memset(p, 119, 1)
    else:
        memset(p, 63, 1)
    return p


def _filemode_cls(mode, cls) -> str:
    """The three permission columns of one class, as a THREE-CHARACTER string.

    `cls` is 0 for the owner, 1 for the group and 2 for others, and it is what
    the table below selects on: three sets of three bits, plus each class's own
    setid (or sticky) bit and the two characters that bit can turn the execute
    column into. `'x'` is 120, `'s'` 115, `'S'` 83, `'t'` 116 and `'T'` 84,
    and only `other` substitutes `t`/`T` for `s`/`S` — which is POSIX's rule
    and CPython's table, and the reason this is a table rather than one class
    computed three times.

    TWO PARAMETERS AND NOT SEVEN, which is deliberate rather than tidiness:
    SysV x86-64 passes six integer arguments in registers and refuses a
    seventh (`bugs/FORMAL_x86_64_argument_registers.md`, the filing that keeps
    `fnmatch.mojo` out of the x86-64 half of
    `test_formal_hostmods_census.py`). Passing the six masks as arguments would
    have made this module arm64-only for no gain.

    ONE CHARACTER PER COLUMN, which is what CPython's own table does: a
    setuid file with the execute bit prints `s`, not `S` and not `sx`, and a
    module that printed the two bits separately would be right about a mode
    with neither and wrong about every mode with exactly one — which is the
    common case, and the reason this is a copy of the table rather than an
    independent reading of POSIX's three bit classes.

    THE WRITES GO THROUGH `memset`, not `p[0] = c`. `formal/hostmods/json.mojo`'s
    `put_byte` is the same shape for the same reason: a subscript STORE is
    not part of the pointer value model, while a `memset` of one byte is a
    call into the C library and means exactly what it says.
    """
    var r = 0
    var w = 0
    var x = 0
    var setid = 0
    var setchar = 115
    var setupper = 83
    if cls == 0:
        r = 256
        w = 128
        x = 64
        setid = 2048
    elif cls == 1:
        r = 32
        w = 16
        x = 8
        setid = 1024
    else:
        r = 4
        w = 2
        x = 1
        setid = 512
        setchar = 116
        setupper = 84
    var p: Pointer[UInt8] = str_alloc(3)
    if (mode & r) == r:
        memset(p, 114, 1)
    else:
        memset(p, 45, 1)
    if (mode & w) == w:
        memset(p + 1, 119, 1)
    else:
        memset(p + 1, 45, 1)
    if (mode & x) == x:
        if (mode & setid) == setid:
            memset(p + 2, setchar, 1)
        else:
            memset(p + 2, 120, 1)
    elif (mode & setid) == setid:
        memset(p + 2, setupper, 1)
    else:
        memset(p + 2, 45, 1)
    return p


def filemode(mode) -> str:
    """`stat.filemode(mode)`: the ten characters `ls -l` prints for a mode.

    Column 0 is the file type and columns 1-9 are `rwx` for the owner, the
    group and others, with CPython's setuid / setgid / sticky substitutions:
    `s` when the bit and the execute bit are both set, `S` (or `T`) when only
    the bit is, and `x` when only the execute bit is. `stat.filemode(0)` is
    `'?---------'` and `stat.filemode(0o100644)` is `'-rw-r--r--'`; both are
    in `test_formal_stat.py`'s corpus and both are compared character by
    character against CPython's own answer.

    `""` for a mode that is not a `mode_t`, which is CPython's `OverflowError`
    turned into an answer. The empty string rather than a ten-character one:
    there is no mode, so there is nothing to print, and a caller testing
    `filemode(m) == ""` is asking exactly the question a masked answer would
    have hidden.

    The returned string is `malloc`'d and the CALLER OWNS it. This path has no
    reference counting and no module storage, so a buffer nothing outside
    points at is a leak; `str_alloc`/`str_put` come from `os/_syscalls.mojo`
    for the reason `platform.mojo` imports from there, and `test_formal_stat.py`
    is what says this table is CPython's rather than a plausible neighbour of
    it — over ALL 65,536 modes there are, not a sample of them.
    """
    if mode_ok(mode) == 0:
        return ""
    var out: Pointer[UInt8] = str_alloc(10)
    var u = 0
    u = str_put(out, u, _filemode_type(mode), 1)
    u = str_put(out, u, _filemode_cls(mode, 0), 3)
    u = str_put(out, u, _filemode_cls(mode, 1), 3)
    u = str_put(out, u, _filemode_cls(mode, 2), 3)
    return out
