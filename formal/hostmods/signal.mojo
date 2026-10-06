"""signal.mojo — the signal NUMBER VOCABULARY, for the formal backend.

`formal/imports.py` resolves an import in four passes and the FIRST is "a Mojo
source `<name>.mojo` in a search root WINS OUTRIGHT, even over the host-module
list". This file is that source for the name `signal`, so `import signal` is no
longer the refusal

    imports 'signal', which is a host module (CPython standard library), which
    has no Mojo source for this backend to compile

It lives in `formal/hostmods/` — the last search root, and the only one no other
resolver in this tree lists. See `_HOSTMODS_ROOT`.

WHAT CPython's `signal` IS, AND WHY SO LITTLE OF IT IS HERE
------------------------------------------------------------
CPython's `signal` is three things stacked on one name: a VOCABULARY of signal
numbers, a set of FUNCTIONS that change this process's signal dispositions and
timers, and an `IntEnum` whose members let a number be turned back into a name.
The first is data the target has, the second is process state, and the third
needs a value that is more than one word. Only the first is modelled, and it is
the first because it is the one a program READS.

  * THE NUMBERS are module-level LITERALS, not functions, and that is the whole
    point of this file's shape. A hostmod's module-level literal is folded into
    its dylib manifest and substituted at the importer's use site
    (`formal/build.py::_publish_imported_constants`), so `signal.SIGTERM` reads
    as the number 15 with no call and no symbol — which is the spelling every
    caller in this repository uses. Measured: 9 files reach this module and 5 of
    them name nothing else unmodelled, and the alternative spelling
    (`signal.SIGTERM()`) is one every one of those 9 files would have to be
    edited to use. `formal/hostmods/ast.mojo` says the opposite about its own
    literals — that they "are NOT importable from it" — and that is still true
    of a module that does not also declare a public function: a dylib with
    nothing but constants cannot be linked at all
    (`bugs/FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md`), and
    `strsignal` below is what makes this one linkable.
  * `strsignal(sig)` is the C library's own `strsignal(3)`, called through the
    same extern-call path `formal/hostmods/sys.mojo` documents for `exit`. It is
    not a table of 31 strings, which is the shape that would have rotted: this
    platform's `strsignal(15)` is `"Terminated: 15"` — with the number in the
    text, unlike Linux's `"Terminated"` — and the answer has to be whatever the
    C library under the image says, not whatever was typed here.
  * `raise_signal(sig)` is `kill(getpid(), sig)`, which is what CPython's own
    source does, and it is here because it is the one signal FUNCTION whose
    answer is a scalar and whose effect is the caller's own process.

THE NUMBERS ARE THIS PLATFORM'S, AND THE ORACLE IS THE HOST'S
--------------------------------------------------------------
A signal number is a fact about the C library's `<signal.h>`, and it differs
between platforms: `SIGIOT` is an alias of `SIGABRT` on both, `SIGSTKFLT` is 16
on Linux and does not exist here at all, and `SIGCHLD` is 17 on Linux and 20
here. So these are macOS's numbers — the numbers of the two architectures this
backend emits for — and they are NOT CPython's numbers on a Linux host.

`test_formal_signal.py` therefore compares each name against CPython's LIVE
`signal` module, name by name, which is the same oracle every other hostmod test
in this tree uses (`test_formal_stat.py`'s `S_I*` corpus is the precedent, and
`formal/hostmods/stat.mojo` says "this platform" for the same reason). It does
not skip on a non-Darwin host: a disagreement there is a true statement about
this file, and hiding it behind a skip is how a platform-specific model becomes
a platform-independent one by accident.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `signal(signum, handler)` — a DISPOSITION. Two halves are missing and each
    on its own is enough: the disposition table belongs to the process and not
    to any word this path can hand around, and `handler` is a CALLABLE, which is
    the shape `formal/hostmods/subprocess.mojo` already admits through a
    contract and which a struct-of-more-than-one-field cannot be here. A
    `signal()` that recorded the number and did nothing would be the worst shape
    in this tree: the program would believe it had installed a handler.
  * `getsignal`, `sigpending`, `sigwait`, `pthread_sigmask`, `pthread_kill`,
    `siginterrupt`, `set_wakeup_fd`, `pause` — every one of them either reads or
    writes process state a caller cannot hold, or is blocked on something that
    never arrives.
  * `alarm`, `setitimer`, `getitimer` — an ITIMER the kernel arms against this
    process. `getitimer` is the sharpest omission: its answer is a
    `(delay, interval)` PAIR, and a pair is a frame-allocated blob that dies on
    return (`bugs/FORMAL_time_struct_shaped_answers.md` says the same about
    `time.get_clock_info`). `alarm(seconds)` alone would return a scalar and be
    the more useful of the two, and is left out for a reason of its own that is
    not capability: the name `alarm` is also the C library function that
    implements it, so a module-level `alarm` here is a call to itself, and the
    only way to write it is to reach the libc symbol through a spelling nothing
    on this path has.
  * `valid_signals()` — a LIST of every signal the platform has. A list is a
    run-time-length container; `os.listdir` answers one only as a `malloc`'d
    blob whose shape the caller has to be told, and there is no caller here that
    could be. The vocabulary is above instead, which is the part a program reads.
  * `Signals`, `Sigmasks`, `Handlers`, `ItimerError` — four types. `Signals` is
    the one worth naming, because `signal.Signals(15).name` is a real and useful
    spelling (it is how a child that died of a signal gets named, and
    `test_struct_formal.py` writes it): it is an `IntEnum` constructed FROM a
    number and read back as a NAME, so it needs the number and the name to be
    one value with two readings, and on this path a value is one 64-bit word
    that a struct's frame address cannot survive. The numbers are here; the
    reverse lookup is not.
  * `default_int_handler` — a callable, as above.

THE TWO THINGS THAT ARE NOT QUITE CPYTHON, STATED HERE
------------------------------------------------------
  * A constant here is an `int` where CPython's is a `Signals` member. That is
    the `enum` measurement `formal/hostmods/enum.mojo` already records — "an
    enum member on this path is a CLASS-LEVEL CONSTANT and the base is erased" —
    read from the other side: the member's `.value` is the number and
    `str(signal.SIGTERM)` is `"15"` on CPython 3.11+ because `IntEnum.__str__`
    is `int.__str__`, so a plain `int` agrees with the host on every read an
    `int` can express. `.name` is the one it cannot, and it is above.
  * `strsignal` and `raise_signal` return 0 where CPython returns `None`.
    `None` folds to the word 0 on this path (`formal/model.py`, `NONE_WORD`).
"""

# ── the signal numbers ──────────────────────────────────────────────────────
#
# Every name CPython 3.14's `signal` exports, at this platform's number for it,
# including the two that are NOT signal numbers and would be misread as such:
# `SIG_DFL` and `SIG_IGN` are DISPOSITIONS (0 and 1) and `SIG_BLOCK`,
# `SIG_UNBLOCK`, `SIG_SETMASK` are `sigprocmask` HOWs (1, 2, 3) — so `SIG_IGN`
# and `SIG_BLOCK` are both the word 1, which is a fact about the C library and
# not a mistake. `NSIG` is 32, the count, not a signal. No `SIG_ERR`: CPython
# 3.14 does not export it (`hasattr(signal, "SIG_ERR")` is False, measured).
SIGHUP = 1
SIGINT = 2
SIGQUIT = 3
SIGILL = 4
SIGTRAP = 5
SIGABRT = 6
SIGEMT = 7
SIGFPE = 8
SIGKILL = 9
SIGBUS = 10
SIGSEGV = 11
SIGSYS = 12
SIGPIPE = 13
SIGALRM = 14
SIGTERM = 15
SIGURG = 16
SIGSTOP = 17
SIGTSTP = 18
SIGCONT = 19
SIGCHLD = 20
SIGTTIN = 21
SIGTTOU = 22
SIGIO = 23
SIGXCPU = 24
SIGXFSZ = 25
SIGVTALRM = 26
SIGPROF = 27
SIGWINCH = 28
SIGINFO = 29
SIGUSR1 = 30
SIGUSR2 = 31

# `SIGIOT` is CPython's compatibility alias for `SIGABRT` and has been since
# 3.x; it is a separate NAME for the same number, and dropping it would make a
# `getattr(signal, "SIGIOT")` fail where CPython's succeeds.
SIGIOT = 6

NSIG = 32

# Dispositions. `SIG_DFL` is the C library's `(void (*)(int))0`, which as a
# value is the word 0, and this path's own representation of `None` is also the
# word 0 — so a `SIG_DFL` read and a `None` read are the same word. Nothing
# dispatches on it here, because `signal()` is absent, so the fold is not
# observable; it is stated rather than left to be discovered.
SIG_DFL = 0
SIG_IGN = 1

# `sigprocmask`'s HOWs, which CPython re-exports from the same header.
SIG_BLOCK = 1
SIG_UNBLOCK = 2
SIG_SETMASK = 3

# `setitimer`'s WHICH, which CPython also re-exports. Absent `setitimer` (see
# the module docstring) but present as data: they are numbers, and a program may
# legitimately pass one to something else.
ITIMER_REAL = 0
ITIMER_VIRTUAL = 1
ITIMER_PROF = 2


# Every call into libSystem this module makes is spelled in `os/_syscalls.mojo`
# and imported from there, so that the question "what does this tree ask of the
# operating system" has the one short answer that file's header promises. It is
# not tidiness for `kill`/`getpid`, which this module could call directly under
# their own names: it is REQUIRED for `strsignal`, whose name this module is
# obliged to declare because CPython declares it too, and a unit that both
# declares a name and calls the C library's function of that name emits a call
# to ITSELF (measured — `os/_syscalls.mojo`'s `fs_strsignal`).
from os._syscalls import fs_strsignal, fs_getpid, fs_kill


def strsignal(sig) -> str:
    """`signal.strsignal(signum)`: the C library's description of `sig`.

    The platform's own `strsignal(3)`, which is what CPython calls. Not a table
    of 31 strings written here: on this platform `strsignal(15)` is
    `"Terminated: 15"` — the number is IN the text — while Linux's is
    `"Terminated"`, so a table would have been right on one platform and a
    plausible wrong answer on the other. Anything but a signal number has no
    answer at all, and the C library's answer for that is the empty string.
    """
    return fs_strsignal(sig)


def raise_signal(sig) -> int:
    """`signal.raise_signal(signum)`: send `sig` to THIS process — `kill(getpid(), sig)`.

    What CPython's own source does, and the one signal function whose answer is
    a scalar AND whose effect is observable by the caller, so it is here rather
    than filed with the dispositions above. 0 on success.

    The disposition `sig` meets is this image's own, so the outcome is the
    platform's: `SIGCONT` at a running process continues and returns 0, and a
    signal whose disposition is the default one ends the image. Nothing in this
    tree installs a disposition (`signal()` is absent), so there is no way to
    ask for the second case without asking for the first.
    """
    return fs_kill(fs_getpid(), sig)
