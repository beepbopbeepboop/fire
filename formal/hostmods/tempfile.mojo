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
uniquely named one is a template of six `X`s and a `mkdtemp(3)` that fills them
in and fails if the name is taken. That is the whole capability, it is the part
51 files in this repository's own corpus call, and it is what this module is.

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
| `TemporaryDirectory` | 64 | **answered**, with its removal on the way out — see `TemporaryDirectory` below, and the `with` protocol in `formal/build.py` that made it a contract rather than a half-answer |
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
  * `gettempprefix`, `TMP_MAX`, `CHARACTERS` — CPython's published names, as
    functions where a function is the spelling that crosses the boundary
    (`formal/hostmods/os/__init__.mojo` says why a module-level name does not),
    because a caller in this corpus reads them. `gettempprefix` is the name that
    says what `mkdtemp`'s prefix is when the caller does not give one, and
    `TMP_MAX` and `CHARACTERS` are CPython's own two answers about ITS name
    generator — which `mkdtemp` no longer is (see the bullet below).
  * `mkdtemp(prefix)` — a real directory, mode `0o700`, a name of `prefix` plus
    six characters the C library chose, and `mkdtemp(3)`'s own retry. **The
    retry used to be spelled out here and could not be right**: this path cannot
    read `errno`, so a loop here retried every failure as if it were a collision
    (`bugs/FORMAL_mkdtemp_retries_a_mkdir_it_cannot_read_the_reason_for.md`).
    `mkdtemp`'s own docstring is where the name's shape and what changed are
    written down.

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
    RETURN-VALUE RULE), which is a reportable failure rather than a wrong path —
    and since it is `mkdtemp(3)` that fails, it fails on the FIRST attempt, which
    is what CPython does with the same filesystem.
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
  * `TemporaryDirectory`'s **`suffix=` and `dir=` arguments** — the two of its
    parameters that are not answered here. `dir=` would be a field this struct
    keeps and `__enter__` honours, and it is absent because every corpus
    spelling that uses it (`dir=os.environ.get("TMPDIR")`, three sites) is
    refused upstream by `os.environ` (`bugs/FORMAL_module_state_no_storage.md`)
    — `io.mojo`'s rule again: a parameter is here when a caller needs it,
    checked rather than assumed. `suffix=` cannot be honoured by ANY
    implementation here: it goes at the END of the name, and this path has no
    writable buffer to append into (`formal/model.py`'s
    `LENGTH_DEPENDENT_METHODS` is the same absence that keeps `mkdtemp` a
    one-parameter function). Both are CPython parameters, so a caller that
    passes one is refused with `unexpected keyword argument` naming it rather
    than given a wrong answer.
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

from os import getenv_or, getcwd
from os.path import isdir, abspath, join
from os._syscalls import fs_access, fs_mkdtemp
from os._syscalls import str_len, str_build
from shutil import rmtree

# CPython's `tempfile.characters`, the alphabet `_RandomNameSequence` draws its
# eight characters from. Read out of this interpreter's own `tempfile` by
# `test_formal_tempfile.py`, which fails if the two disagree — a module-level
# string constant in a dylib is a `__DATA` slot the image lays out, and reading
# its bytes needs the `Pointer[UInt8]` spelling below (`hashlib.mojo`'s
# `HEX_DIGITS + (b >> 4)` is the same trick).
#
# **NOT THIS MODULE'S NAME ALPHABET ANY MORE, and that is a change of
# implementation rather than a subtraction from the API.** CPython publishes
# `tempfile.characters` and a caller in this corpus may read it, so it stays and
# `test_formal_tempfile.py`'s `constants` group still compares it with this
# interpreter's. The names `mkdtemp` makes stopped coming from it when `mkdtemp`
# became one `mkdtemp(3)` call: the C library substitutes the template's six `X`s
# from ITS OWN alphabet, so the name is `prefix` + six characters of `[A-Za-z0-9]`
# and the alphabet below no longer describes it. `mkdtemp`'s docstring says so
# where a reader of a name will land.
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


def TMP_MAX() -> int:
    """`tempfile.TMP_MAX`: how many names CPython's `mkdtemp` may spend.

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

    **CPython's budget, published; NOT this module's any more.** `mkdtemp` below
    is one `mkdtemp(3)` call, and the retry is the C library's — it retries on
    `EEXIST` and gives up on anything else, which is the distinction this
    module's own loop could not make
    (`bugs/FORMAL_mkdtemp_retries_a_mkdir_it_cannot_read_the_reason_for.md`).
    So the number stays because CPython publishes it, not because anything here
    counts to it.
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


def mkdtemp(prefix) -> str:
    """`tempfile.mkdtemp(prefix=…)`: a new directory's path, or `""`.

    **ONE `mkdtemp(3)` CALL**, over a template of `prefix` + `XXXXXX` in the
    directory `gettempdir` names. This used to be CPython's algorithm spelled
    out here — draw eight characters, `mkdir`, retry on failure — and the retry
    was the defect: this path cannot read `errno`, because the C library's error
    accessor is `__error` and a leading underscore in a callee name is not a
    symbol this image can bind (`formal/hostmods/os/_syscalls.mojo`'s header),
    so every failure was treated as a collision. A directory that cannot be made
    — a full filesystem, a read-only mount reached through a writable-looking
    path — cost the whole `TMP_MAX` budget and answered `""` where CPython
    raises on the first attempt
    (`bugs/FORMAL_mkdtemp_retries_a_mkdir_it_cannot_read_the_reason_for.md`).
    `mkdtemp(3)` makes the same distinction with the error code to itself: it
    retries a name that is ALREADY TAKEN and fails immediately on anything else.

    **WHAT CHANGED AND WHAT DID NOT**, because the two are easy to confuse and
    the difference is the price of the fix:

      * the NAME is `prefix` + SIX characters of `[A-Za-z0-9]` — the C library's
        alphabet, over the six `X`s of the template — where it was `prefix` +
        eight characters of CPython's 37-character alphabet. `CHARACTERS` and
        `TMP_MAX` are still published because CPython publishes them; neither
        describes a name this function makes now.
      * the MODE is still `0o700`, because `mkdtemp(3)` creates the directory
        with exactly that mode — the assertion moved from "what this module
        passes to `mkdir`" to "what the platform creates", and
        `test_formal_tempfile.py`'s `mkdtemp` group still reads the mode back
        with `os.stat` on both architectures.
      * the SUFFIX parameter CPython takes is still absent, for the module
        docstring's reason: a call across a dylib boundary cannot omit an
        argument, so this is `mkdtemp(prefix=…)`, and a first POSITIONAL
        argument means the prefix here where it means the suffix in CPython.
      * `""` is still the answer for every failure, because there is no `raise`
        on this path (FORMAL.md phase 7) — and it is now reached in ONE call
        rather than after a budget of them.
      * a prefix that makes the NAME ITSELF impossible still answers `""` where
        CPython raises: `prefix="b-/"` puts a separator inside the template, so
        the parent does not exist and no amount of retrying helps. That case is
        `test_formal_tempfile.py`'s `name` group, and it is unchanged.

    The returned path is absolute because the template is: `gettempdir` answers
    `abspath` of a candidate, so `join(base, …)` is already absolute and CPython
    composes its answer the same way (`_mkstemp_inner` joins onto an
    `abspath`'d directory). There is no second `abspath` call here, and the
    `join` is the only path arithmetic: `base` is what the module says the
    directory is, so a caller comparing `dirname(answer)` with `gettempdir()`
    gets the same string on both sides.
    """
    var base = gettempdir()
    if str_len(base) == 0:
        return ""
    var tmpl = join(base, str_build(prefix, "XXXXXX", ""))
    return fs_mkdtemp(tmpl)

struct TemporaryDirectory:
    """`tempfile.TemporaryDirectory(...)` — a directory that is REMOVED on the
    way out of the `with` that made it.

    **This is the whole contract, and it is why the name used to be absent.**
    `with EXPR as TARGET` used to evaluate `EXPR`, evaluate the body, and bind
    `TARGET` to the expression: there was no dispatch through an `__exit__` to
    hook, so a `TemporaryDirectory` modelled as "create the directory, return
    its path" built, ran, printed the right answers and LEFT THE TREE BEHIND —
    the module's own rule about `closing`, in its own words: "a name that
    answers the easy half of its contract and drops the half that matters is
    the one thing a mirror of CPython must not export." 64 of the 111 files the
    corpus ranking counts use this one name.

    **It is a struct with `__enter__` and `__exit__` because that is now what
    a `with` lowers to** (`formal/build.py`'s `_rewrite_with_statements`, and
    `formal/model.py`'s `struct_is_context_manager` for the rule): `__enter__`
    produces the name the body sees, `__exit__` runs on the way out, and a
    `with` whose value is not enterable and exitable is refused rather than
    quietly skipping the exit. Two consequences worth stating, because both are
    why this is shaped the way it is:

      * **a context manager here must be a struct of more than one field.** A
        one-field struct's receiver IS that field, so there is no address to
        dispatch a method on and no room for the second thing. CPython's own
        `TemporaryDirectory` keeps three attributes, so the honest mirror is
        representable and this one is: `prefix` and `delete` are two of its
        arguments, and `name` is its `.name`.
      * **the directory is created by `__enter__`, not by the construction.**
        A field's class-level initializer must be a LITERAL on this path (a call
        in one is refused: "the default is not a literal, and this constructor
        has no scope to evaluate it in"), and a `__init__` is lowered by inlining
        its `self.<field> = <bare parameter>` stores at the construction site, so
        a `__init__` whose body calls `mkdtemp` is refused too. `__enter__` is an
        ordinary method and may do anything, and it runs before the body — so for
        every `with` the directory exists for the whole block and is gone after
        it. **The one divergence from CPython is an object used OUTSIDE a
        `with`**: CPython creates the directory in `__init__`, so `t.name` is
        readable before `with t:`, and here `t.name` is `""` until `__enter__`
        runs. No caller in this corpus does that (measured: every one of the 64
        uses is `with tempfile.TemporaryDirectory() as d:`), and the alternative
        — creating the directory in the construction and not being able to remove
        it — is the failure this file was written to refuse.

    `delete=0` is CPython 3.12's `delete=False`: keep the directory. It is a real
    field and `__exit__` reads it, rather than a second field invented to reach
    the two a context manager needs.
    """
    var prefix: str = ""
    var delete: Int = 1
    var name: str = ""

    fn __enter__(self) -> str:
        """Create the directory and hand its path to the `with`'s name.

        `gettempprefix()` when the caller gave no prefix, which is CPython's own
        default; `mkdtemp` is the whole of the creation and returns `""` on every
        failure (THE RETURN-VALUE RULE above), so a `with` whose directory could
        not be made binds the empty string rather than a path that is not there.
        """
        var p = self.prefix
        if str_len(p) == 0:
            p = gettempprefix()
        self.name = mkdtemp(p)
        return self.name

    fn __exit__(self) -> int:
        """Remove what `__enter__` created — the whole point of the class.

        `rmtree` and not `rmdir`: a temporary directory in this corpus is a
        directory a program WRITES INTO (64 callers, every one of them building
        something under `d`), and `rmdir` fails with `ENOTEMPTY` on a directory
        that has entries in it, which would leave exactly the tree this contract
        exists to remove. `maxdepth` is spelled because a call across a dylib
        boundary cannot omit an argument
        (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`).

        The answer is `shutil.rmtree`'s — the number of entries removed, so a
        `delete=0` manager and a failed removal are both distinguishable by a
        caller that looks — and it is not CPython's `None`.
        """
        if self.delete == 0:
            return 0
        return rmtree(self.name, 64)
