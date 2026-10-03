"""`tempfile` — the DIRECTORY half, over `os`, with the file-object half absent.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import tempfile` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other resolver
in the tree lists — see `_HOSTMODS_ROOT` for why these did NOT go at the
repository root, where the first three of them captured `import os` in the
compiler's own sources.

`tempfile` WAS IN `HOST_UNREACHABLE`, under "a terminal". **Both halves of
that sentence have since been measured away.** The terminal half (`shutil`'s
`get_terminal_size`) is still true and is why nothing here asks for a terminal.
The `TMPDIR` half is false: `formal/hostmods/os/__init__.mojo` has `getenv`,
`getcwd`, `mkdir` and `os.path` has `isdir`, `join` and `abspath` — 75
filesystem operations against the real filesystem are what
`test_formal_os.py` runs — so a temporary directory is a directory, and a
uniquely named one is eight random bytes and a `mkdir` that fails when the name
is taken. That is the whole capability, it is the part 51 files in this
repository's own corpus call, and it is what this module is.

THE RANKING THAT PUT THIS FILE FIRST, and what it cost to answer honestly
-----------------------------------------------------------------------
`python3 tools/formal_sweep_causes.py --host bugs/sweeps/sweep-arm-7.txt` is
the ranking (the tool gained the mode with this module). `tempfile` is the
largest host-import row in the sweep by a factor of 2.3 — **111 files, and 109
of them name something this module publishes**, so the row is work and not
closure, which is the distinction the `--host` table's `uses` column exists to
draw. Those 109 files, by the name each one binds:

| name | files | what this module does about it |
|---|---|---|
| `mkdtemp` | 51 | **answered**, as `mkdtemp(prefix)` — see THE SIGNATURE below |
| `TemporaryDirectory` | 64 | **absent**, and the reason is the second half of the module |
| `NamedTemporaryFile` | 9 | **absent** (a FILE OBJECT) |
| `mkstemp` | 2 | **absent** (a two-element TUPLE) |
| nothing | 2 | closure: they import `tempfile` and never use it |

**AND THE HONEST ACCOUNTING, because "38 files" is the number that matters:
this module moves ZERO of the 111 files to `pass`, and it is still worth
landing.** What it does is move them out of `not-answerable/host-import` — a
class that means "this target cannot build this file" — and into a refusal that
names the thing the file actually needs, which is what every other module in
this directory is for (`test_formal_core_hostmods.py`'s own table: `type_system.py`
stopped being "imports 'enum'" and became a refusal about `Type.origin`'s
dataclass default). `bugs/FORMAL_platform_reachable_row_measured.md` §2 records
the same accounting for `platform`, and `bugs/FORMAL_host_import_row_5_measured.md`
goes further and says of four other modules in this row that writing them is not
worth the day. **This one is different, and the difference is that the capability
behind it is REAL and reachable**: `mkdtemp`'s body below is `os` calls that
exist and are tested. It is not refused for want of a syscall or a representation.

THE SIGNATURE, WHICH IS NOT CPYTHON'S, AND WHY IT IS THIS ONE
-------------------------------------------------------------
CPython's is `mkdtemp(suffix=None, prefix=None, dir=None)` — three parameters,
two of them defaulted, and the first one POSITIONAL is the suffix. What is here
is `mkdtemp(prefix)`.

  * **No parameter may be omitted at a call across a dylib boundary.** The
    argument register is not written for a default this image cannot see, and
    the backend refuses it by name rather than passing a stack address:
    `bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`, whose
    measurement is why `os.mkdir(path, mode)` and `shutil.rmtree(path, maxdepth)`
    are spelled with every argument. So a three-parameter `mkdtemp` here is a
    function **no caller in this corpus can call**: all 51 spell `mkdtemp(prefix=…)`
    and would be refused with `missing required argument 'suffix'`.
  * **A keyword argument at such a call DOES work**, measured on both shapes
    that matter: `os.makedirs(path="kwdir", mode=511)` builds and creates the
    directory, and `tfprobe.one(prefix="P")` builds and answers. So the one
    parameter is named `prefix` and the corpus's spelling is the one that works.
  * **`mkdtemp(".c")` means PREFIX `.c` here and SUFFIX `.c` in CPython.** That
    is a real divergence and it is the price of the shape above, stated here
    rather than left to be discovered: there is no corpus call site that passes
    a first positional argument (measured — every one of the 51 spells
    `prefix=`), and a caller that means CPython's suffix is refused by name
    (`unexpected keyword argument 'suffix'`) rather than given the wrong answer.
    The alternatives were a three-parameter mirror nobody can call and a second
    invented name (`mkdtemp_in(suffix, prefix, dir)`) for a case no caller in
    this tree has; `formal/hostmods/io.mojo`'s rule is the tie-breaker — "a
    number is here when a caller needs it, checked rather than assumed".

WHAT IS HERE
------------
  * `gettempdir` — CPython's candidate walk, `TMPDIR`/`TEMP`/`TMP` then
    `/tmp`, `/var/tmp`, `/usr/tmp`, then the working directory, with the
    writability test stated below because it is the one place this differs.
  * `gettempprefix`, `TMP_MAX` — CPython's two constants, as functions, because
    a module-level name is not exported as a word across a dylib boundary
    (`formal/hostmods/os/__init__.mojo` says so). `gettempprefix` is the name
    that says what `mkdtemp`'s prefix is when the caller does not give one, and
    `TMP_MAX` is the budget `mkdtemp` spends; both are in CPython's `__all__`.
  * `mkdtemp(prefix)` — a real directory, mode 448 (`0o700`), an eight-character
    random name over CPython's own alphabet, and CPython's retry loop.

THE TWO PLACES THIS IS NOT CPYTHON, EACH MEASURED
--------------------------------------------------
  * **THE WRITABILITY TEST IS `access(dir, W_OK)`, not a write probe.** CPython
    3.11+ decides a candidate is usable by CREATING a file in it, writing four
    bytes to it and unlinking it, and it randomizes the probe's name to prevent
    denial of service. **That probe cannot be written here**, and the reason is
    a spelling rather than a capability: it needs `open(path, flags, mode)` with
    three arguments, and this path lowers `open` itself and refuses the C
    library's own three-argument spelling of it
    (`formal/hostmods/os/_syscalls.mojo`'s `fs_open_ro`, which is the one place
    that fact is written down). `access(2)` IS CPython's own test: it is what
    `_get_default_tempdir` used up to 3.10, and the two agree on every candidate
    this host has. They differ in exactly one case, which is stated rather than
    papered over: a directory that `access` calls writable and the FILESYSTEM
    refuses to write in — a full filesystem, a read-only mount reached through a
    writable-looking path — where CPython moves to the next candidate and this
    accepts one. `mkdtemp` into such a directory then returns `""` (see THE
    RETURN-VALUE RULE), which is a reportable failure rather than a wrong path.
  * **NOTHING IS CACHED.** CPython computes the answer once per process, in the
    module global `tempdir`, behind a lock. A module-level name has no storage
    on this path (`bugs/FORMAL_module_state_no_storage.md`), so every call walks
    the candidates again. Two consequences, both in the safe direction and both
    stated: a caller that changes `TMPDIR` and asks again gets the NEW answer
    where CPython would still answer with the first one, and two calls in one
    program cost a handful of `stat`s. `tempfile.tempdir` — CPython's cache,
    readable and assignable — is absent for the same reason, and
    `tempfile.gettempdirb` / `gettempprefixb` are absent because a `bytes`
    object is a buffer plus a length and a value here is one 64-bit word.

THE RETURN-VALUE RULE, WHICH IS NOT CPYTHON'S AND CANNOT BE
----------------------------------------------------------
CPython's `mkdtemp` RAISES (`FileNotFoundError`, `FileExistsError`,
`PermissionError`) and there are no exceptions on this path (FORMAL.md
phase 7), so `mkdtemp` returns the new directory's path on success and **`""`
on every failure**, which is `shutil`'s rule stated in its own module docstring
for the same reason: `""` is the one string no caller would pass to `open` by
accident. `gettempdir` returns `""` where CPython raises `FileNotFoundError`,
and for the same reason — an empty path is not a directory.

WHAT IS NOT HERE, AND WHY — each measured, and none of them approximated
----------------------------------------------------------------------
  * `TemporaryDirectory` (64 files in the corpus, the largest single use of this
    module) — **its whole contract is what happens on the way OUT of a `with`.**
    `formal/hostmods/contextlib.mojo` measured that `with EXPR as TARGET`
    evaluates `EXPR`, evaluates the body, and binds `TARGET` to the expression:
    there is no dispatch through an `__exit__` to hook, and that is why
    `nullcontext` is one function there. A `TemporaryDirectory` modelled as
    "create the directory, return its path" would therefore build, run, print
    the right answers, and **leave the tree behind** — which is the module's
    own decision about `closing`, in its own words: "a name that answers the
    easy half of its contract and drops the half that matters is the one thing a
    mirror of CPython must not export." The half that matters here is the
    removal, so the name is absent rather than half-present.
    `bugs/FORMAL_tempfile_context_manager_needs_a_way_out_of_a_with.md` has the
    census, the measurement and the next step.
  * `NamedTemporaryFile`, `TemporaryFile` (9 files) — a FILE OBJECT: a `FILE *`
    and a cursor and a buffer, which is more than one 64-bit word, and
    `formal/hostmods/io.mojo` says the same thing one level up about `sys.stdout`.
    Its `__exit__` also closes and unlinks, so it carries the `with` problem
    above as well. What CAN be reached is `fopen(path, "wx")`
    (`formal/hostmods/os/_syscalls.mojo`'s `fs_fopen`), which is exclusive
    creation on this target and is measured in `test_formal_tempfile.py`'s
    `exclusive` group; a caller that wants a file rather than a file OBJECT is
    one `mkstemp`-shaped call away and the shape is named in that bug doc.
  * `mkstemp` (2 files) — its answer is `(fd, name)`, a two-element tuple, and a
    tuple is a frame blob that cannot cross a dylib boundary: the same limit
    that keeps `shutil.disk_usage` and `os.path.split` from returning their own
    answers (`bugs/FORMAL_time_struct_shaped_answers.md`). Splitting it into
    `mkstemp_fd` and `mkstemp_path` is possible and is NOT done here, for
    `io.mojo`'s reason again: no caller in this corpus could use either, and a
    half of a CPython answer with a name of its own is a second thing to keep
    true.
  * `SpooledTemporaryFile` — the file object, plus a threshold and a rollover.
  * `mktemp`, `mktempdir` — **the INSECURE ones**, and deliberately: CPython
    documents both as returning a name that is almost certainly not in use,
    vulnerable to a race, and "should never be used in a security-sensitive
    environment" — deprecated for exactly that reason (3.12 deprecated
    `mktemp()`/`mktempdir()`; they raise `PendingDeprecationWarning`). A mirror
    that shipped them would be shipping a name whose documented failure mode is
    the one this module exists to avoid.
  * `tempdir`, `_get_candidate_names`, `_RandomNameSequence`, `_sanitize_params`,
    `_infer_return_type`, `_get_default_tempdir` — private in CPython, and named
    here only because one of them (`_get_default_tempdir`) is the algorithm
    `gettempdir` above implements.
"""

from os import getenv_or, getcwd, mkdir
from os.path import isdir, abspath, join
from os._syscalls import fs_access, fs_arc4random
from os._syscalls import str_len, str_build

# CPython's `tempfile.characters`, the alphabet `_RandomNameSequence` draws its
# eight characters from. Read out of this interpreter's own `tempfile` by
# `test_formal_tempfile.py`, which fails if the two disagree — a module-level
# string constant in a dylib is a `__DATA` slot the image lays out, and reading
# its bytes needs the `Pointer[UInt8]` spelling below (`hashlib.mojo`'s
# `HEX_DIGITS + (b >> 4)` is the same trick).
CHARACTERS = "abcdefghijklmnopqrstuvwxyz0123456789_"

# CPython's `tempfile.template`, the default prefix of every name it makes.
TEMPLATE = "tmp"


def _W_OK() -> int:
    """`access(2)`'s `W_OK`: 2, which is also CPython's `os.W_OK`.

    POSIX numbers `F_OK`/`X_OK`/`W_OK`/`R_OK` as 0/1/2/4 and Darwin does not
    renumber them; `test_formal_tempfile.py` reads all of them out of this
    interpreter's own `os` and compares.

    Written out here rather than imported, and the reason is stated because it
    is a duplicate somebody should consolidate rather than a decision to
    duplicate: `formal/hostmods/shutil.mojo` publishes the same three bits as
    `shutil.R_OK`/`W_OK`/`X_OK` (which is where the corpus reads them from, since
    `shutil.which` needs one), and CPython puts all three in `os`. The two
    copies belong in `formal/hostmods/os/__init__.mojo`, which is CPython's home
    for them; what is not done about it here is importing `shutil` for one
    constant, which would put the whole copying module — 661 lines and a
    recursive `copytree` — into this module's import closure to read a number
    that is 2.
    """
    return 2


def _char_at(i) -> int:
    """The byte at index `i` of `CHARACTERS`.

    A string is a bare `char *` into a read-only section, so a subscript on it
    reads a blob count rather than a character
    (`bugs/FORMAL_string_value_model.md`); the `Pointer[UInt8]` annotation is
    the spelling that makes `p[i]` a one-byte load at one byte of width.
    """
    var p: Pointer[UInt8] = CHARACTERS + i
    return p.value()


def TMP_MAX() -> int:
    """`tempfile.TMP_MAX`: how many names `mkdtemp` may spend before giving up.

    **20**, which is CPython's value on this interpreter and NOT the 10000 that
    `tempfile` carried for twenty years. CPython lowered it when it moved the
    name generator off a Mersenne Twister, and its own comment says why: eight
    characters over a 37-character alphabet are "over 40 random bits", so
    "with 20 attempts, it is less than 1e-120" — the budget is small BECAUSE the
    names are wide, and a module that kept 10000 would be spending a thousand
    times the calls to reach a probability no caller can observe.

    A number this tree cannot read from the host, because there is no CPython at
    run time to read it from, and a mirror that guesses it would be a mirror
    that is wrong the day CPython moves it again. So it is written down, and
    `test_formal_tempfile.py` reads this interpreter's own `tempfile.TMP_MAX`
    and compares — which makes a change in CPython a RED TEST here rather than
    a constant nobody has looked at since.
    """
    return 20


def gettempprefix() -> str:
    """`tempfile.gettempprefix()`: `"tmp"`, CPython's `template`.

    The default prefix of every name `mkdtemp` makes when the caller does not
    pass one. CPython returns `os.fsdecode(template)` and this returns the
    literal, which is the same string on a POSIX target — `fsdecode` is the
    identity for `str`, and the `bytes` half of it is absent (see the module
    docstring).
    """
    return TEMPLATE


def _usable(dir) -> str:
    """`dir` as an absolute path if a temporary file can be made in it, else `""`.

    CPython's per-candidate test, which is `isdir` plus writability. `abspath`
    is applied first because CPython applies it first (`_get_default_tempdir`,
    which skips it only for the literal `"."`), and it matters for the answer as
    a string: a caller that gets `/tmp` and a caller that gets `/tmp/` are
    different strings, and the path this returns is what a caller will join a
    name onto.
    """
    if str_len(dir) == 0:
        return ""
    var p = abspath(dir)
    if isdir(p) == 0:
        return ""
    if fs_access(p, _W_OK()) != 0:
        return ""
    return p


def gettempdir() -> str:
    """`tempfile.gettempdir()`: the first usable candidate, or `""`.

    CPython's `_candidate_tempdir_list` in its order — the three environment
    variables that are set and non-empty, then `/tmp`, `/var/tmp`, `/usr/tmp`,
    then the working directory — and CPython's per-candidate test (`_usable`
    above, which is `isdir` and `W_OK` where CPython writes and unlinks a
    probe file; the module docstring has the measurement and the one case where
    the two differ).

    `""` where CPython raises `FileNotFoundError`, which is this path's
    stand-in for an exception and is a string no caller can pass to `open` by
    accident.
    """
    var d = getenv_or("TMPDIR", "")
    if str_len(d) == 0:
        d = getenv_or("TEMP", "")
    if str_len(d) == 0:
        d = getenv_or("TMP", "")
    var r = _usable(d)
    if str_len(r) > 0:
        return r
    r = _usable("/tmp")
    if str_len(r) > 0:
        return r
    r = _usable("/var/tmp")
    if str_len(r) > 0:
        return r
    r = _usable("/usr/tmp")
    if str_len(r) > 0:
        return r
    return _usable(getcwd())


def _name8() -> str:
    """Eight random characters from CPython's alphabet, NUL-terminated.

    `arc4random_buf(3)`, eight bytes, each reduced modulo the alphabet's length
    — CPython's own alphabet, which is what makes the NAME this module produces
    the same shape as CPython's: `prefix` + eight characters of
    `[a-z0-9_]` + `suffix`, and a name length a caller can rely on.

    The reduction is modulo 37 over a byte rather than CPython's
    `floor(random() * 37)` over a 53-bit float, so the distribution over the
    alphabet is not perfectly uniform (30 of the 37 characters come up 7 times
    in 256 and 7 come up 6). The property `mkdtemp` needs is that a name is not
    already taken, and that comes from the `mkdir` below failing when it is —
    not from the distribution.

    Returned in a buffer this module owns, so it is freed here rather than
    leaked: `free`ing a string LITERAL is a SIGABRT that takes the process's
    whole buffered stdout with it (`shutil.mojo`'s `copytree` records the
    measurement), and a `str_append` onto this one is the only thing that reads
    it.
    """
    var b: Pointer[UInt8] = str_alloc(9)
    fs_arc4random(b, 8)
    var i = 0
    while i < 8:
        var v = b[i]
        # 37 = the alphabet's length, by repeated subtraction: integer division
        # is not a spelling this path gives every int, and the loop runs at most
        # six times for a byte.
        var k = 0
        while v >= 37:
            v = v - 37
            k = k + 1
        b[i] = _char_at(k)
        i = i + 1
    return b


def mkdtemp(prefix) -> str:
    """`tempfile.mkdtemp(prefix=…)`: a new directory's path, or `""`.

    CPython's algorithm, in its order (`tempfile.mkdtemp` and `_mkstemp_inner`):
    the directory is the one `gettempdir` names, the name is `prefix` + eight
    random characters, the mode is 448 (`0o700`, so the directory is readable,
    writable and searchable only by the user who made it), and a name that is
    **already taken** is retried rather than reported — up to `TMP_MAX` times.

    The retry loop is what makes the answer correct rather than likely, and it
    is why the name generator's quality does not matter: a collision is a
    `mkdir` that fails with `EEXIST`, which is CPython's own `FileExistsError`
    arm, and the next draw is a different name. **This loop cannot SEE `EEXIST`**
    — the C library's error accessor is `__error` and a leading underscore in a
    callee name is not a symbol this image can bind
    (`formal/hostmods/os/_syscalls.mojo`'s header), so every `mkdir` failure is
    retried and the budget bounds it. On a host where the failure is not a
    collision — the directory does not exist, or is not writable — this spends
    the budget and returns `""` where CPython raises on the first attempt. The
    first of those two is caught earlier instead: `gettempdir` returns `""` and
    so does this, without drawing a name.

    `prefix` is REQUIRED and is the module docstring's subject: a call across a
    dylib boundary cannot omit an argument
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`), so this is
    `mkdtemp(prefix=…)` rather than CPython's three-parameter signature, and a
    first POSITIONAL argument means the prefix here where it means the suffix in
    CPython.

    The returned path is `abspath` of what was created, as CPython's is.
    """
    var base = gettempdir()
    if str_len(base) == 0:
        return ""
    var seq = 0
    while seq < TMP_MAX():
        var name = str_build(prefix, "", _name8())
        var path = join(base, name)
        if mkdir(path, 448) == 0:
            return abspath(path)
        seq = seq + 1
    return ""