"""`tempfile` — the part of it this target can compute, and the part it cannot.

`formal/imports.py` had `tempfile` in `HOST_UNREACHABLE` under "a terminal",
and §1 of this file is the measurement that retired that: **the terminal is
unavailable and the directory is not.** The sweep's own log counts 111 files
refused for `tempfile` — the largest host-import row in the corpus, 2.4x the
next one — and 128 files in this repository import it. What they actually call,
read with `ast` over every `.py` the sweep covers **except
`test_formal_tempfile.py`, which is the file that pins these numbers and must
not be one of the things it counts**:

| name | call sites | reachable here? |
|---|---|---|
| `TemporaryDirectory` | 142 | **no** — a context manager and a class |
| `mkdtemp` | 92 | **YES**, and it is COMPUTED, not admitted |
| `NamedTemporaryFile` | 64 | **no** — a file object, i.e. a stream |
| `TemporaryFile` | 3 | **no** — a stream |
| `mkstemp` | 3 | **yes, and NOT written** — see §4 |
| `gettempdir` | 1 | **YES**, and it is COMPUTED |

So **44** of the 128 use nothing but the names this module answers
(`mkdtemp`, `gettempdir`, `mkstemp`), and those are the files that move. The
other 84 use `TemporaryDirectory`, `NamedTemporaryFile` or `TemporaryFile` and
are unmoved by it, and §3 says why in the terms that made them unreachable.
`test_formal_tempfile.py` recomputes all six counts and the 44 from the source,
so this table cannot go stale without a test failing.

**Zero admitted contracts, deliberately.** `mkdtemp` asks the C library to make
a fresh directory and hands back the path it made — the same shape as
`formal/hostmods/fcntl.mojo`'s real `flock(2)`, which is why `fcntl` LEFT
`HOST_ADMITTED` when it became computable. A path that exists is not a claim of
trust; a path this file made up would be, and `mkdtemp` never invents one: if
`mkdtemp(3)` fails, this returns `""` and says so.

WHAT IS COMPUTED, AND AGAINST WHAT
----------------------------------
`gettempdir` is CPython's `_candidate_tempdir_list` walk, in CPython's order,
with `os.getenv` and `confstr` standing in for what it uses:

    $TMPDIR, $TEMP, $TMP, then /tmp, /var/tmp, /usr/tmp, then getcwd() —
    the first candidate that is writable, or "" when none is.

CPython picks the first candidate it can CREATE A FILE IN; this picks the first
`access(dir, W_OK)` accepts. That is the one approximation in the module and it
is stated here rather than hidden: the two disagree only about a directory that
is writable according to `access` and not writable in fact (a full or read-only
mount), which is not a case this project's filesystem presents. `access` is
`os.access`, which `formal/hostmods/os/__init__.mojo` already exposes, so this
is not a second implementation of anything — it is CPython's walk over
`os`'s own primitives.

`mkdtemp(prefix, suffix, dir)` builds CPython's own template,
`dir + "/" + prefix + "XXXXXX" + suffix`, and calls `mkdtemp(3)`, which
substitutes the six `X`s with a name it invents and writes the finished path
back through the buffer. That is a REAL answer about a REAL directory, and
`test_formal_tempfile.py` checks CPython's INVARIANTS on it rather than
comparing the path to CPython's — the six characters are random on both sides
and no test can make two runs of `mkdtemp` agree.

WHAT IS NOT HERE, AND WHY
------------------------
  * **`TemporaryDirectory`** (142 call sites), `NamedTemporaryFile` (64) and
    `TemporaryFile` (3).  A context manager needs `with`, a class needs a
    record, and a file object needs a stream — and this path has none of the
    three: there is no exception unwinder (FORMAL.md phase 7), and a stream is a
    descriptor, a cursor and a buffer, which `formal/hostmods/io.mojo` and
    `formal/hostmods/sys.mojo` both say at length is not one 64-bit word. This
    is `concurrent.futures.ThreadPoolExecutor` and `copy.copy` arriving from the
    other direction: a name whose promise is an OBJECT, on a path where an
    object is not a value.

  * **`mkstemp`** (3 call sites). It is reachable — `mkstemps(3)` is in
    libSystem and does exactly what CPython's `mkstemp(suffix=…)` needs — and it
    is NOT written, because its only failure check cannot be trusted today:
    `mkstemps` returns C's `int`, and a bare C call's 32-bit return reaches this
    backend's comparison as a ZERO-EXTENDED word, so `< 0` is false for the
    `-1` the host returned.
    `bugs/FORMAL_a_bare_c_call_returning_a_32_bit_int_is_compared_as_a_zero_extended_word.md`
    has the measurement, the disassembly and the fix. Writing the function with
    a check known to be false would put a silently wrong runtime test into the
    module 111 sweep files are refused on.

  * **`mktemp`**, `NamedTemporaryFile(delete=False)`'s no-unlink mode,
    `SpooledTemporaryFile`, `TemporaryFile` and `gettempprefix`. The first is
    deprecated in CPython for a race it cannot fix and there is no call site;
    the rest are the object half of §3.

  * **`gettempdirb`** and `tempdir`/`template`/`_once_lock`. `tempdir` is the
    CACHE CPython's `gettempdir` builds on first call; this computes the walk
    every time, which is the same answer for one process and no state to store.

THE SUFFIX, AND WHY IT IS ONLY RIGHT FOR AN EMPTY ONE
----------------------------------------------------
This is §5 of the bug doc above, and it is here because a caller reading only
this file would otherwise assume `suffix=` works:

    mkdtemp("/tmp/xXXXXXX.txt")  ->  creates /tmp/xXXXXXX.txt, LITERALLY

`mkdtemp(3)` substitutes the last six bytes and nothing else, so a suffix after
them is part of the name and two calls collide on one directory. CPython gets
this right because it does not use `mkdtemp(3)` at all — it builds the name from
a random sequence and calls `os.mkdir`, whose `EEXIST` it can read. The entry
point that takes a suffix is `mkstemps(3)`, and `mkstemps` is the callee the bug
doc shows is mis-compared on its return.

**So `suffix` is accepted, and ignored for anything but the empty string.**
That is a divergence from CPython and it is a WRONG ANSWER for a non-empty
suffix, so it is stated in the module docstring, in `mkdtemp`'s own, and pinned
by a test — the alternative, refusing the call, would take the 91 sites that pass
no suffix at all down with the 3 that do.
"""

from os import getenv_or
from os._syscalls import fs_mkdtemp, fs_access, fs_cwd, str_build, str_len

# `access(2)`'s mode words, as `os.access` already spells them. Repeated here
# because they are this module's own condition and `formal/hostmods/os` exposes
# `access(path, mode)` rather than three constants — one spelling of the
# predicate, and the numbers are the C library's, not a choice.
_ACCESS_EXISTS = 0
_ACCESS_WRITE = 2


def _empty(s: str) -> int:
    """Whether `s` is the empty string.

    `str_len(s) == 0` and NOT `s == ""`, and the reason is a refusal rather than
    a preference: on this path a value is classified by KIND, and a local or a
    bare parameter is a NUMBER unless its type says otherwise, so `d == ""` is
    "compares a NUMBER with a string" and `formal/model.py` refuses it — a
    `strcmp` would dereference a word as a pointer. `strlen` is the same
    computation with no kind to guess, which is what
    `formal/hostmods/os/_syscalls.mojo` says about it.
    """
    if str_len(s) == 0:
        return 1
    return 0


def _writable(dir: str) -> int:
    """1 when `access(dir, W_OK)` SUCCEEDS, i.e. when CPython's walk keeps it.

    **`access` returns 0 on success**, so the test is `== 0` and NOT `!= 0`:
    written the other way round, `/usr/tmp` — which does not exist on this host,
    so `access` refuses it — is the one candidate the walk keeps, and
    `mkdtemp` then fails in a directory that is not there. That is a wrong
    answer produced by a sign, and it is why the whole walk reads the other way
    here rather than at each call site.

    The one approximation in this module, and `test_formal_tempfile.py` measures
    it against CPython on the machine's own `TMPDIR`: both walks have to pick
    the same directory, and when they do not the test says which one they picked
    rather than failing on a `!=` nobody can act on.
    """
    if fs_access(dir, _ACCESS_WRITE) == 0:
        return 1
    return 0


def gettempdir() -> str:
    """`tempfile.gettempdir()`: the first usable directory in CPython's order.

    `$TMPDIR`, `$TEMP`, `$TMP`, `/tmp`, `/var/tmp`, `/usr/tmp`, then the current
    directory — CPython's `_candidate_tempdir_list` exactly, in order, and the
    order is observable because `/tmp` exists on every host this runs on and the
    environment wins when it is set.

    `""` when no candidate is writable. CPython raises `FileNotFoundError`
    there, and there is no exception on this path (FORMAL.md phase 7), so the
    answer is the empty string — which every caller below turns into "" as
    well, rather than a path nothing points at.
    """
    var d: str = getenv_or("TMPDIR", "")
    if _empty(d) == 0 and _writable(d) != 0:
        return d
    d = getenv_or("TEMP", "")
    if _empty(d) == 0 and _writable(d) != 0:
        return d
    d = getenv_or("TMP", "")
    if _empty(d) == 0 and _writable(d) != 0:
        return d
    if _writable("/tmp") != 0:
        return "/tmp"
    if _writable("/var/tmp") != 0:
        return "/var/tmp"
    if _writable("/usr/tmp") != 0:
        return "/usr/tmp"
    d = fs_cwd()
    if _empty(d) == 0 and _writable(d) != 0:
        return d
    return ""


def mkdtemp(prefix: str = "", suffix: str = "", dir: str = "") -> str:
    """`tempfile.mkdtemp(prefix, suffix, dir)`: the path of a fresh directory.

    **The real `mkdtemp(3)`, not a `mkdir` loop**, and `mkdtemp(3)` is what
    makes this exact rather than approximate. CPython's own loop retries
    `TMP_MAX` times when a name is taken, and telling "already taken" from
    "could not be made" means reading `errno`, whose accessor is `__error` — a
    leading underscore, which is not a symbol this path can bind
    (`formal/hostmods/os/_syscalls.mojo` says so and works around it). The C
    library's call does that retry with the error code to itself.

    The six characters in the middle are THE C LIBRARY'S and not this module's,
    so the returned path is a real answer about a real directory rather than a
    value this file chose — and two calls never collide, because the C library
    does not retry a name it just used.

    `""` when no name could be made, which is CPython's `FileNotFoundError`
    flattened (FORMAL.md phase 7). `os.makedirs` is the answer for a caller that
    wanted the directory to exist and can make it itself.

    **`suffix` is accepted and only correct when it is EMPTY** — the module
    docstring's last section has the measurement. Kept as a parameter because
    CPython has one and 91 of this tree's call sites pass `prefix=` and nothing
    else; refused outright it would take those with the three that pass a suffix.
    """
    var d: str = dir
    if _empty(d) != 0:
        d = gettempdir()
    return fs_mkdtemp(str_build(str_build(d, "/", prefix), "XXXXXX", suffix))