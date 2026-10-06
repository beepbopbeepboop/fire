"""`fcntl` — file locks, descriptor flags and the `F_*` command numbers.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import fcntl` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` for why these did NOT go at
the repository root, where the first three of them captured `import os` in the
compiler's own sources.

This module is here because of ONE LINE, spelled the same way in the three
files that want it (`tools/ab_run_one.py:105`, `tools/control.py:66`,
`tools/integrate.py:181`). Note that `fcntl` was in NEITHER tier of
`formal/imports.py` — the sweep classified the import as `host-import` because
no `fcntl.mojo` existed for the resolver to find, so the classification change
this file makes is not a removal from anything:

    fcntl.flock(fd, fcntl.LOCK_EX)

A whole-file advisory lock, a libc call this path can make, and a set of
constants that are numbers. It is the smallest host module in this directory
and it is worth having for the reason the sweep row is worth having: the
`fcntl` row of `not-answerable/host-import` was three files, and all three of
them then stop on `subprocess` instead — which is a fact about the target with
an owner, rather than a fact about the target with none. **That is the whole
yield, and it is worth saying plainly: writing `fcntl` moves ZERO files to
PASS.** See `bugs/FORMAL_platform_reachable_row_measured.md` §2 for the same
arithmetic on the `platform` row, which is where the rule this row follows was
established.

WHAT IS HERE
------------
  * `flock(fd, operation)` — BSD whole-file locks. `LOCK_SH`, `LOCK_EX`,
    `LOCK_NB`, `LOCK_UN`, and the four combinations a caller writes.
  * the POSIX record-lock COMMAND NUMBERS — `F_RDLCK`, `F_WRLCK`, `F_UNLCK`,
    `F_GETLK`, `F_SETLK`, `F_SETLKW` and the three `F_OFD_*` variants. They are
    numbers and a mirror with a hole in a command table is not a mirror; the
    `lockf` CALL that uses them is absent, and the reason is spelled out where
    `lockf` would have been.
  * `FD_CLOEXEC` — the constant, and `getfd` / `setfd` / `getfl` / `setfl` —
    the four descriptor-flag calls that use it. They were absent for a while
    because the third argument of `fcntl(2)` is VARIADIC and this path did not
    know `fcntl` was one of the C entry points that takes its variadic
    arguments in a stack area rather than in registers, so the flag word was
    emitted into X2 and the syscall applied whatever was at `[sp]`: a `setfd`
    that reported success and changed nothing. The measurement is in the
    comment where the four are defined.
  * every `F_*` COMMAND NUMBER as a function, including the ones with no
    function here (`F_SETOWN`, `F_GETOWN`, `F_FULLFSYNC`, `F_GETPATH`,
    `F_SETNOSIGPIPE`, `F_RDAHEAD`, `F_NOCACHE`, `F_GETLEASE`, `F_SETLEASE`,
    `F_FASYNC`, `F_DUPFD`, `F_DUPFD_CLOEXEC`), because they are NUMBERS and a
    module that exported half of a command table would be a mirror with a hole
    in it.

WHAT IS NOT HERE, AND WHY
------------------------
  * `lockf`, and `F_SETLK`'s pointer argument. `lockf`'s C call is
    `fcntl(fd, F_SETLK, &lock)` and the third argument is a POINTER through the
    same variadic tail. The tail now works (see above), so what is left is the
    pointer: this path cannot spell a variadic argument that is a pointer, and
    `formal/hostmods/os/_syscalls.mojo`'s `fs_fcntl` takes three INTEGER
    arguments for that reason. The struct itself is not the obstacle — it is
    five fields at offsets 0, 2, 8, 16 and 24 — so this is one extension of the
    argument-passing convention away, not a capability; it is written down in
    `bugs/FORMAL_a_pointer_through_a_variadic_argument.md`.

  * `ioctl(fd, request, arg)`. `ioctl` is not a lock and not a flag: it is a
    DEVICE's private protocol, and the request number means whatever the driver
    on the other end says it means. A formal image links libSystem and nothing
    else, so there is no driver whose request numbers this tree could state, and
    `ioctl(TIOCGWINSZ)` — which `shutil.get_terminal_size` wants — is a
    `struct winsize` this source does not declare. Absent rather than a wrapper
    around a number nobody can check.

  * `F_GETOWN` / `F_SETOWN` AS FUNCTIONS, and `F_SETOWN_EX` /
    `F_GETOWN_EX` (whose struct is `struct f_owner_ex`, a layout of its own).
    The command NUMBERS are here; the calls are not, because signal ownership is
    a process-wide affair and this path has no signal delivery to own — the same
    reason `signal` is in `HOST_UNREACHABLE`.

  * `LOCK_NB` ON A RECORD LOCK. POSIX's non-blocking record lock is `F_SETLK`
    (which never blocks) where `flock`'s is an OR of `LOCK_NB`; the two APIs
    differ and a module that spelled both as one flag would be right about one
    of them. `test_formal_fcntl.py`'s `consts` group says so at `F_SETLK`.

  * `F_OFD_*` on anything but a file. The open-file-description locks need a
    descriptor that is not shared with another thread, which is a property of
    the program's own threading and there is no threading here
    (`concurrent.futures` and `threading` are both `HOST_UNREACHABLE`). The
    command numbers are exported so a caller spelling one is answered.

THE TWO THINGS A LOCK MODULE GETS WRONG, AND BOTH ARE HERE
---------------------------------------------------------
  * **A LOCK IS PER OPEN FILE DESCRIPTION, NOT PER PROCESS**, so `flock` on two
    descriptors this process opened separately CONFLICTS with itself, and
    `test_formal_fcntl.py`'s `flock` group is built on exactly that: the
    process holding one descriptor must see the other one fail with `LOCK_NB`.
    A module whose `flock` were implemented over `F_SETLK` would pass a
    same-process test and be wrong against every other process, because
    `F_SETLK` with `l_pid == 0` means the CALLING process and POSIX record locks
    are per-process.
  * **`flock` and `F_SETLK` DO NOT INTERACT — ON LINUX. ON macOS THEY DO**, and
    that is measured rather than assumed: macOS implements `flock` over `fcntl`
    record locks with a different `l_type`, so a `flock` on a second descriptor
    is refused while a POSIX `F_WRLCK` is held on the first.
    `test_formal_fcntl.py`'s `independence` group asserts the platform's own
    answer rather than Linux's, precisely so that a reader who has the other
    platform in their head is caught.

NO EXCEPTIONS AND NO ERROR CODES
--------------------------------
`fcntl.flock` returns 0 on success and raises `BlockingIOError` or `OSError`
otherwise. There are no exceptions on this path (FORMAL.md phase 7) and `errno`
cannot be bound — the C library's accessor is `__error` and a leading underscore
in a callee name is not a symbol this image can load
(`formal/hostmods/os/_syscalls.mojo`'s header) — so **every function here
returns 0 on success and -1 on failure**, and the caller cannot tell the two
failure reasons apart. `test_formal_fcntl.py`'s `absent` group pins the whole
of that: a caller that wants CPython's `BlockingIOError` has to test for -1
itself, and that is the module's documented answer rather than a gap.
"""

# `flock` and `fcntl` ARE CALLED THROUGH `_syscalls.mojo` AND NOT DIRECTLY, for
# the NAME COLLISION rule that file's header states as its first reason:
# `flock` is a libc function AND the name this module's API wants, so a
# `def flock(fd, operation)` that called `flock(fd, operation)` would emit a call
# to ITSELF with the wrong arity — silently, and as a hang. `fs_flock` and
# `fs_fcntl` are the wrappers, beside every other libSystem call in the tree.
from os._syscalls import fs_flock, fs_fcntl


# ── `flock`'s four operations ───────────────────────────────────────────────

def LOCK_SH() -> int:
    """`LOCK_SH`: 1 — a SHARED lock, and several holders may have one."""
    return 1

def LOCK_EX() -> int:
    """`LOCK_EX`: 2 — an EXCLUSIVE lock.

    **This is the number the three files that want this module want**, and it is
    a function like every constant here for the reason at the top of this file:
    `fcntl.LOCK_EX` is spelled `fcntl.LOCK_EX()` on this path.
    """
    return 2

def LOCK_NB() -> int:
    """`LOCK_NB`: 4 — do not block. OR it into the operation.

    `LOCK_EX | LOCK_NB` is "take it if you can" and is the only spelling of
    non-blocking `flock` there is. Without it the call BLOCKS, which on this
    path means an image that stops with no output rather than one that fails:
    `test_formal_fcntl.py`'s group is careful to always OR it in for the cases
    where a block would be a hang.
    """
    return 4

def LOCK_UN() -> int:
    """`LOCK_UN`: 8 — release whatever this descriptor holds."""
    return 8


def flock(fd, operation) -> int:
    """`fcntl.flock(fd, operation)`: 0 on success, -1 on failure.

    `flock(2)` and NOT `fcntl(2)` with `F_SETLK`, and the two are different
    locks — see this file's docstring for the two ways that matters and for the
    assertion in the test that pins it. `LOCK_NB` is what keeps a caller's
    question answerable; without it a contended lock is a hang.

    **A LOCK IS PER OPEN FILE DESCRIPTION**, so this process can hold a lock on
    one descriptor and be refused on a second one it opened itself. That is not
    a defect in this module, it is the property that makes `flock` usable as a
    cross-process mutex, and it is what the test's `self_conflict` case asserts.
    """
    return fs_flock(fd, operation)


# ── the descriptor flags ────────────────────────────────────────────────────

def FD_CLOEXEC() -> int:
    """`FD_CLOEXEC`: 1 — close this descriptor when the process execs.

    The number, and the two calls that set and read it (`setfd` / `getfd`) are
    below with the rest of the descriptor-flag calls.

    The number is here because it IS CPython's number and a mirror with a hole
    in a command table is not a mirror.
    """
    return 1


# `F_GETFD`, `F_SETFD`, `F_GETFL` and `F_SETFL` were all reachable in principle —
# the command numbers are here and `fs_fcntl` is the call — and **the third
# argument of `fcntl(2)` did not arrive.**  That sentence is in the past tense
# because it is fixed, and what it was is the single most useful thing this file
# has to say about the target, so the measurement is kept rather than deleted.
#
# `fcntl(2)` is `int fcntl(int fd, int cmd, ...)`. On Apple arm64 the unnamed
# arguments do NOT go in argument registers: the caller reserves an area and the
# i-th unnamed argument goes at offset 8*(i-1) from SP as it stands at the call.
# `formal/model.py`'s `VARIADIC_LIBC` is where a callee is recorded as variadic
# and how many of its arguments are named, and `fcntl` was not in it — so the
# third argument was emitted into X2, which is the generic convention and not
# this target's, and nothing was written into the area at all.
#
# MEASURED, on arm64, on a descriptor this path opened itself, BEFORE:
#
#   fcntl(fd, F_GETFD, 0)              -> 0       (CPython: 1, but see below)
#   fcntl(fd, F_SETFD, FD_CLOEXEC)     -> 0       (success)
#   fcntl(fd, F_GETFD, 0)              -> 0       (UNCHANGED: the flag did not
#                                                take, so `setfd` reported
#                                                success and did nothing)
#   fcntl(fd, F_GETFL, 0)              -> 0
#   fcntl(fd, F_SETFL, 4)              -> 0
#   fcntl(fd, F_GETFL, 0)              -> 192     (CPython: 4)
#
# AFTER (both architectures, and the entry is `"fcntl": 2` in `VARIADIC_LIBC`):
#
#   fcntl(fd, F_SETFD, FD_CLOEXEC)     -> 0       (success)
#   fcntl(fd, F_GETFD, 0)              -> 1       (the flag took)
#   fcntl(fd, F_SETFL, 4)              -> 0
#   fcntl(fd, F_GETFL, 0)              -> 4       (CPython: 4)
#
# **x86-64 never had this.** SysV x86-64 passes variadic arguments in the same
# registers as fixed ones, so the positional emission above is the whole
# convention there and only the arm64 table entry was missing. A test that ran
# one architecture would have called this fixed before and after.
#
# `getfd` reading 0 where CPython reads 1 on a FRESH descriptor is NOT this
# bug and is still true: CPython's `os.open` sets `FD_CLOEXEC` by default and
# this path's `open(p, "r")` does not, and cannot until `open` grows a flag for
# it. It is a difference in the OPEN, not in the read, and
# `test_formal_fcntl.py`'s `fdflags` group says so in the one place where the
# two are compared.
#
# `printf` was never evidence against this: its arguments demonstrably arrive,
# because `printf` IS in the table. That is the whole asymmetry — a variadic
# callee that is in the table works, and one that is not does not, silently.


def F_RDLCK() -> int:
    """`F_RDLCK`: 1 — a READ lock on a byte range.

    **The same number as `F_GETFD`.** That is not a mistake: `F_RDLCK` and
    `F_GETFD` are commands for two different APIS (`fcntl`/`lockf` and
    `fcntl`/`FD_CLOEXEC`), so they never appear in the same call and the
    collision is harmless. `test_formal_fcntl.py`'s `consts` group compares all
    thirty numbers against CPython's own, which is what makes this a fact and
    not a worry.
    """
    return 1

def F_UNLCK() -> int:
    """`F_UNLCK`: 2 — unlock a byte range."""
    return 2

def F_WRLCK() -> int:
    """`F_WRLCK`: 3 — a WRITE lock on a byte range."""
    return 3

def F_GETLK() -> int:
    """`F_GETLK`: 7 — would the range lock? The answer comes back IN the
    caller's `struct flock` with `l_type` set to `F_UNLCK` if it could be, and
    to the conflicting type if not.

    Number only: the answer comes back through the variadic pointer argument
    that cannot be spelled here — see the `lockf` paragraph above.
    """
    return 7

def F_SETLK() -> int:
    """`F_SETLK`: 8 — set a range lock, or return IMMEDIATELY if it is held.

    **THIS IS POSIX'S NON-BLOCKING LOCK**, where `flock`'s is `LOCK_NB` OR'd
    into the operation. The two APIs differ and a module that spelled both as one
    flag would be right about one of them and wrong about the other, which is
    why `test_formal_fcntl.py` says so at the constant.
    """
    return 8

def F_SETLKW() -> int:
    """`F_SETLKW`: 9 — set a range lock, WAITING for it.

    **THE ONE NUMBER IN THIS MODULE THAT NAMES AN OPERATION THAT CAN STOP AN
    IMAGE.** There is no `F_SETLKWTIMEOUT` here, and there could not be: it
    needs a `struct timespec` through the same variadic pointer argument, and
    there is no way to say "at most this long" on this path. `test_formal_fcntl.py`
    ORs `LOCK_NB` into every `flock` it takes for the same reason: a blocking
    call is an image that stops with no output, which the harness can only
    report as a timeout.
    """
    return 9

def F_GETFD() -> int:
    """`F_GETFD`: 1 — read the descriptor's flags. Number only; see `getfd`'s
    absence, which is measured, at the top of this file."""
    return 1

def F_GETPATH() -> int:
    """`F_GETPATH`: 50 — BSD, return the path the descriptor was opened with,
    through the variadic pointer argument. Number only."""
    return 50

# ── the record locks: THE NUMBERS, AND NOT `lockf` ─────────────────────────
#
# `F_RDLCK`, `F_WRLCK`, `F_UNLCK`, `F_GETLK`, `F_SETLK` and `F_SETLKW` are
# NUMBERS and are here. **`lockf` IS NOT**, and the reason is a spelling rather
# than a capability, which is the distinction worth drawing:
#
#   `lockf`'s C call is `fcntl(fd, F_SETLK, &lock)` — the third argument is a
#   POINTER, passed through `fcntl`'s VARIADIC tail. This path cannot spell a
#   variadic argument that is a pointer: `formal/hostmods/os/_syscalls.mojo`'s
#   header says a variadic libc call cannot be spelled here at all (`str_build`
#   is three fixed-arity calls and no format string for exactly this reason),
#   and `fs_fcntl` therefore takes three INTEGER arguments, which is enough for
#   `F_GETFD` and `F_SETFD` and not enough for a `struct flock *`.
#
# The struct itself is not the obstacle — `struct stat` is read byte-wise in this
# tree and `struct flock` is five fields at offsets 0, 2, 8, 16 and 24 — so
# `lockf` is ONE extension of the argument-passing convention away, not a
# capability. `bugs/FORMAL_a_pointer_through_a_variadic_argument.md` is where
# that is written down, and it is the same gap that keeps
# `platform.architecture()` (a `read` into a buffer the caller fills) and
# `struct tm` out of `formal/hostmods/time.mojo`.

# ── the descriptor flags: THE CALLS ──────────────────────────────────────────
#
# These four are here NOW, and the reason they were not is the most useful thing
# in this file, so it is written down rather than deleted:
#
# `fcntl(2)` is `int fcntl(int fd, int cmd, ...)`. The third parameter is
# VARIADIC, and on Apple arm64 a variadic argument is NOT passed in an argument
# register: the caller reserves an area and the i-th unnamed argument goes at
# offset 8*(i-1) from SP as it stands at the call. `formal/model.py`'s
# `VARIADIC_LIBC` says which C entry points are variadic and how many of their
# arguments are named, `arm64_codegen`'s `_emit_variadic_area` lays the area out
# from that table, and **`fcntl` was not in the table**. So `fcntl(fd, cmd, arg)`
# was emitted with `arg` in X2 — positionally, correctly, into the register the
# generic convention uses — and nothing at all in the area, and the callee read
# whatever the caller had at `[sp]`. Measured, before the table entry existed:
#
#   fcntl(fd, F_SETFD, FD_CLOEXEC)  -> 0   (success) … and nothing changed
#   fcntl(fd, F_GETFD)              -> 0   (before AND after the set)
#   fcntl(fd, F_SETFL, O_NONBLOCK)  -> 0
#   fcntl(fd, F_GETFL)              -> 192 (CPython: 4)
#
# A `setfd` built on that would report success and change nothing, which is the
# silent wrong answer about a descriptor this file refused to ship rather than
# ship. `bugs/FORMAL_a_variadic_call_drops_its_third_argument.md` recorded the
# measurement; the entry `"fcntl": 2` in `VARIADIC_LIBC` is the fix, and
# `test_formal_fcntl.py`'s `fdflags` group is what says it took.
#
# x86-64 was never affected and that is not luck: SysV x86-64 passes variadic
# arguments in the same registers as fixed ones, so the positional emission above
# is the whole convention there. The bug was ARM64-only, and a test that ran one
# architecture would have called it fixed.

def getfd(fd: int) -> int:
    """`fcntl(fd, F_GETFD)`: the descriptor's flag word, or -1.

    On this target the function's own return value IS the answer, because
    `fcntl(2)` returns the old value of the word for a GET and -1 for a
    failure — which is why this is not `0` on a descriptor that was never
    opened, and why -1 cannot be told from a legitimate word here (see the
    module header on `errno`).
    """
    return fs_fcntl(fd, F_GETFD(), 0)

def setfd(fd: int, flags: int) -> int:
    """`fcntl(fd, F_SETFD, flags)`: 0 on success, -1 on failure.

    `flags` is a WORD (`FD_CLOEXEC` or 0), not a set of bits to OR in here:
    `F_SETFD` replaces the word, and a caller that wants close-on-exec ORs the
    constant into what `getfd` returned, which is the whole of why `getfd` is
    here rather than only the setter.
    """
    return fs_fcntl(fd, F_SETFD(), flags)

def getfl(fd: int) -> int:
    """`fcntl(fd, F_GETFL)`: the descriptor's STATUS flags (`O_*`), or -1.

    CPython's `os.O_*` constants are not mirrored here and do not need to be:
    they are the C library's, not this module's, and a caller that wants
    `O_NONBLOCK` spells it or compares against a number it got from elsewhere.
    What this mirrors is the fcntl answer, and `test_formal_fcntl.py` compares
    it against CPython's own `fcntl.fcntl(fd, fcntl.F_GETFL)` on the same file.
    """
    return fs_fcntl(fd, F_GETFL(), 0)

def setfl(fd: int, flags: int) -> int:
    """`fcntl(fd, F_SETFL, flags)`: 0 on success, -1 on failure.

    `F_SETFL` SETS the listed status flags and is not required to clear the
    others on every platform, so the portable way to turn one off is to read the
    word with `getfl`, clear the bit, and set the result back. macOS replaces
    the word; this docstring states the weaker promise rather than the stronger
    one, because the weaker one is the one a caller can rely on.
    """
    return fs_fcntl(fd, F_SETFL(), flags)

# ── the command numbers with no function here ───────────────────────────────
#
# Every one of these is a NUMBER, and a module that exported half of a command
# table would be a mirror with a hole in it. `test_formal_fcntl.py`'s `consts`
# group reads each one out of CPython's own `fcntl` and compares, which is the
# only assertion that says this table is CPython's.

def F_DUPFD() -> int:
    """`F_DUPFD`: 0 — duplicate a descriptor, without close-on-exec."""
    return 0

def F_SETFD() -> int:
    """`F_SETFD`: 2 — set the descriptor flags. See `setfd`."""
    return 2

def F_GETFL() -> int:
    """`F_GETFL`: 3 — read the status flags. See `getfl`."""
    return 3

def F_SETFL() -> int:
    """`F_SETFL`: 4 — set the status flags. See `setfl`."""
    return 4

def F_GETOWN() -> int:
    """`F_GETOWN`: 5 — who gets `SIGIO` on this descriptor. Number only."""
    return 5

def F_SETOWN() -> int:
    """`F_SETOWN`: 6 — set that owner. Number only."""
    return 6

def F_OFD_SETLK() -> int:
    """`F_OFD_SETLK`: 90 — an open-file-description lock, non-blocking.

    Number only, and the reason is at the top of this file: an OFD lock is
    per open file description and needs a descriptor no other thread shares.
    """
    return 90

def F_OFD_SETLKW() -> int:
    """`F_OFD_SETLKW`: 91 — the blocking OFD lock. Number only."""
    return 91

def F_OFD_GETLK() -> int:
    """`F_OFD_GETLK`: 92 — query an OFD lock. Number only."""
    return 92

def F_DUPFD_CLOEXEC() -> int:
    """`F_DUPFD_CLOEXEC`: 67 — duplicate a descriptor WITH close-on-exec."""
    return 67

def F_SETOWN_EX() -> int:
    """`F_SETOWN_EX`: 102 — set the owner the `f_owner_ex` way. Number only."""
    return 102

def F_GETOWN_EX() -> int:
    """`F_GETOWN_EX`: 103 — read it back. Number only."""
    return 103

def F_FASYNC() -> int:
    """`F_FASYNC`: 64 — BSD, set by `O_ASYNC` and read by `F_GETFL`. Number
    only, and CPython exports it as an integer on this platform."""
    return 64

def F_NOCACHE() -> int:
    """`F_NOCACHE`: 48 — do not cache this file's data. Number only."""
    return 48

def F_RDAHEAD() -> int:
    """`F_RDAHEAD`: 45 — BSD read-ahead hint. Number only."""
    return 45

def F_FULLFSYNC() -> int:
    """`F_FULLFSYNC`: 51 — `fsync` with the drive's write cache included. Number
    only: there is no function here because it is set through `F_SETFL` with
    `O_SYNC`, and `F_SETFL` is absent for the reason at the top of this file."""
    return 51

def F_SETNOSIGPIPE() -> int:
    """`F_SETNOSIGPIPE`: 73 — clear the descriptor's `SIGPIPE`. Number only."""
    return 73

def F_GETNOSIGPIPE() -> int:
    """`F_GETNOSIGPIPE`: 74 — read it back. Number only."""
    return 74

def F_SETLEASE() -> int:
    """`F_SETLEASE`: 106 — BSD file lease. Number only.

    A LEASE is "you may break my lease to truncate this, and I will be told",
    which needs `F_SETSIG`/`F_GETSIG` and a notification nobody on this image
    could receive. The number is here because CPython exports it.
    """
    return 106

def F_GETLEASE() -> int:
    """`F_GETLEASE`: 107 — read the lease back. Number only."""
    return 107
