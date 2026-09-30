"""`os` — the operating-system interface, for the formal backend.

This file, `os/path/__init__.mojo` and `os/_syscalls.mojo` live in
`formal/hostmods/`, which `formal/imports.py` adds to every file's search
roots as its last entry — so `import os` and `import os.path` reach them from
any file this backend compiles, and no other resolver in the tree can. They did
NOT live at the repository root, where they were first written: the root is a
search root for four independent resolvers (`imports.py`'s `Resolver`,
`module_loader.py`, the interpreter's sibling-module loader, and the gimple
backend), so a Mojo `os` there captured `import os` in `fire.py`,
`module_loader.py` and `gimple_codegen.py` — the compiler's own source — and
the compiled path lowered `os.sep` as a module-level name with no storage.
See `formal/imports.py`'s `_HOSTMODS_ROOT`.

What CPython's `os` is, restricted to what a freestanding arm64 image that
links libSystem and nothing else can actually be asked for. The shape of the
restriction is the same everywhere in this module and is worth stating once,
because it is not a matter of taste:

  * ARM64 ONLY TODAY, and not because of anything in this source. A module
    dylib that makes a call into the C library is arm64-only on this backend:
    the same two-line module builds and RUNS with `--backend=arm64` and
    produces an image the loader refuses with ``main executable failed strict
    validation`` under `--backend=x86_64``, which is the unclaimed-trailing-byte
    failure `formal/macho_linker.py`'s `_assert_no_unclaimed_bytes` exists for.
    Every function below needs the C library, so all of them are arm64-only
    until that is fixed; `test_formal_os.py` skips a non-arm64 host and the
    reason it has to is here. Filed as
    `bugs/FORMAL_x86_64_dylib_with_an_extern_call_does_not_load.md`.

  * A CONSTANT IS A CALL. `os.sep` is a module-level name, and a module-level
    name is not exported as a word across a dylib boundary — there is no
    storage for one, because every value a formal program can name lives in a
    function's own stack scratch. So `sep()` is a zero-argument function and
    `os.sep` is spelled `sep()`. Same for `curdir`, `pardir`, `extsep`,
    `pathsep`, `linesep` and `devnull`.

  * A FAILURE IS A STATUS, NOT AN EXCEPTION. There is no `try`/`except` on
    this path (FORMAL.md phase 7), so every call that can fail returns what the
    C library returns: 0 or -1. A function documented as "0 on success, -1 on
    failure" is exactly that, and a caller that needs CPython's exception has
    to test the status itself. This is a real difference from CPython and it
    is why `remove` below does not raise `FileNotFoundError`.

  * **A DIRECTORY LISTING IS A BLOB, NOT A LIST.** `listdir` and `walk` are
    here and they are exact — same entries, same order, same `.`/`..` rule as
    CPython — but they answer with a `malloc`'d blob whose word 0 is the count
    and whose other words are the names, and `listdir_len` / `listdir_get` /
    `walk_free` are how it is read. The reason is a representation, and it is
    a real one: a list's capacity is the number of `append` SITES in the
    function that builds it, so a list whose length is known only at run time
    cannot be built, and a container on this path lives in the frame of the
    function that made it, which a return value does not outlive. What makes
    `listdir` answerable anyway is `malloc` — an allocation that outlives the
    function — and a `readdir` name that is now readable, because a read of
    the `struct dirent` used to be a bounds check against the inode number at
    offset 0. A run-time-length blob is not a Python list and nothing here
    pretends otherwise; see `listdir`'s own docstring for the layout and
    bugs/FORMAL_listdir_no_run_time_sequence.md for what is still missing.

  * **EVERY FUNCTION HERE SAYS WHAT IT RETURNS.** `-> str` or `-> int` on all
    of them, which is not documentation: the annotation is what puts `char *` in
    the module dylib's manifest signature, and a call site reads that to decide
    whether the value it got back is a string. Without it a call result is a
    word of unknown provenance, and `f() == g()` on two of those was an
    ADDRESS comparison — two equal strings compared unequal, silently, on both
    backends (bugs/FORMAL_string_equality_of_two_unclassified_words.md). The
    four functions in `os.path` that return a TUPLE carry no annotation, for
    the reason that file gives.

  * `environ` IS ITS THREE FUNCTIONS. A process environment is a `char **` in
    the C library's data, and enumerating it needs a buffer walk this path
    cannot do. `getenv`, `putenv` and `unsetenv` are the whole of what can be
    reached, and they are what `os.environ.get(k)` and `os.environ[k]` have to
    become.

  * **NO FUNCTION HERE HAS A DEFAULT ARGUMENT.** That USED to be forced by a
    backend defect rather than a property of the target, and it is worth
    keeping the shape because the same reasoning applies to every module in
    this directory. A call to a function in ANOTHER image used not to
    materialize the callee's defaults: the caller had no signature to read
    them from, so the argument register was whatever the caller last left in
    it. Measured, same source either way:

        # dmod.mojo          def need_two(a, b=511): return b
        # in ONE file:       need_two(1)            ->  511
        # across a dylib:    need_two(1)            ->  1867609072

    A default that arrives as a stack address is worse than no default,
    because `mkdir(path, mode)` with a garbage mode SUCCEEDS and leaves a
    directory nobody can enter. `formal/imports.py`'s `external_declarations`
    now hands the emitter the callee's own declaration, so the register is
    filled from the default and the measurement above no longer reproduces
    (`FORMAL_default_argument_not_applied_across_a_dylib`, fixed; its doc is
    deleted, as a fixed bug's is). Every parameter CPython gives a default is
    still spelled REQUIRED here — that is a choice now, not a limit, and
    restoring the defaults is written down as its own step in
    `bugs/FORMAL_hostmod_defaults_left_required_after_the_cross_dylib_fix.md`
    because it wants a sweep to confirm it, not a comment to assert it. The one
    place a default was always wanted — `getenv`'s — is a SECOND function,
    `getenv_or(name, default)`, so the two-argument form has a name of its own
    rather than a signature that silently does nothing.
"""

from ._syscalls import str_alloc, str_len, str_at, str_prefix, str_starts
from ._syscalls import fs_cwd, fs_getenv, fs_setenv, fs_unsetenv
from ._syscalls import fs_chdir, fs_chmod, fs_rename, fs_unlink, fs_rmdir
from ._syscalls import fs_mkdir, fs_free, str_build, str_dup
from ._syscalls import fs_readdir, fs_rewinddir, fs_closedir
from ._syscalls import fs_dirent_name, fs_name_is_dot, fs_opendir
from .path import exists, isfile, isdir, islink, lexists, getsize
from .path import join

# ── The constants CPython spells as attributes ──────────────────────────────
#
# Functions, and the reason is at the top of this file. Each returns the
# interned literal, so there is nothing to free and no two calls can disagree.

def sep() -> str:
    """The path separator: `"/"`."""
    return "/"


def curdir() -> str:
    """The current directory, as a name: `"."`."""
    return "."


def pardir() -> str:
    """The parent directory, as a name: `".."`."""
    return ".."


def extsep() -> str:
    """The extension separator: `"."`."""
    return "."


def pathsep() -> str:
    """The separator between entries of a search path: `":"`."""
    return ":"


def linesep() -> str:
    """The line separator: a single newline byte.

    BUILT, not written `"\\n"`. A string literal on this path is interned
    verbatim and its escapes are not unescaped, so a literal `"\n"` is the two
    characters `\` and `n` — measured, and recorded in
    bugs/FORMAL_pointer_value_model.md as a pre-existing `printf`
    string-escape question. A `memset` of the byte value is the way to say
    "newline" on this target, and the buffer is already a `str_alloc`'d one, so
    it is zeroed and then one byte of it is set.

    The caller owns the buffer, like every other string here.
    """
    var b: Pointer[UInt8] = str_alloc(1)
    memset(b, 10, 1)
    return b


def devnull() -> str:
    """The bit bucket: `"/dev/null"`."""
    return "/dev/null"


# ── The working directory ──────────────────────────────────────────────────

def getcwd() -> str:
    """The current working directory, in a fresh buffer the caller owns.

    `""` if the C library cannot report it, which on this target means the
    path is longer than `PATH_MAX`. CPython raises `OSError` there; there is no
    exception to raise, and the empty string is the answer that cannot be
    mistaken for a directory.
    """
    return fs_cwd()


def chdir(path) -> int:
    """Change the working directory. 0 on success, -1 on failure.

    CPython raises `OSError`; see the note at the top of this module.
    """
    return fs_chdir(path)


# ── The environment ────────────────────────────────────────────────────────

def getenv(name) -> str:
    """The value of the environment variable `name`, or `""` when it is unset.

    CPython's `os.getenv(name)`. For `os.getenv(name, default)` use
    `getenv_or`, which is a separate function rather than a default argument
    because a default argument is not applied to a call from another image (see
    the note at the top of this module).

    A variable that is set to the empty string returns the empty string, which
    is not the same as being unset — as in CPython, and it is why the two
    cannot be told apart through this function.
    """
    return getenv_or(name, "")


def getenv_or(name, default) -> str:
    """`getenv(name)`, with `default` as the answer when it is unset.

    A separate function rather than a default argument on `getenv`, and the
    reason is at the top of this module: a default that is not applied is not
    an error, it is a wrong value.
    """
    v = fs_getenv(name)
    if v == 0:
        return default
    return v


def putenv(name, value) -> int:
    """Set the environment variable `name`. 0 on success, -1 on failure.

    Always overwrites, which is `os.environ.__setitem__` rather than
    `os.putenv`'s `overwrite=False` default — there is no way to spell the other
    one through a fixed signature, and the overwriting behaviour is the one a
    caller assigning into `environ` means.
    """
    return fs_setenv(name, value, 1)


def unsetenv(name) -> int:
    """Remove the environment variable `name`. 0 on success, -1 if it was
    not set."""
    return fs_unsetenv(name)


# ── Creating, removing and renaming ────────────────────────────────────────

def remove(path) -> int:
    """Remove the file at `path`. 0 on success, -1 on failure.

    `os.remove` and `os.unlink` are the same call on a POSIX target and are
    both here; the C library's `unlink` is reached through `os/_syscalls.mojo`
    because a unit that both defined `remove` and called libc's `remove` would
    emit a call to itself.

    CPython raises `FileNotFoundError` for a path that is not there. This
    returns -1 and the caller tests it; the reason is at the top of this file.
    """
    return fs_unlink(path)


def unlink(path) -> int:
    """`remove(path)`, under the other name CPython gives it."""
    return fs_unlink(path)


def rmdir(path) -> int:
    """Remove the DIRECTORY at `path`. 0 on success, -1 on failure."""
    return fs_rmdir(path)


def mkdir(path, mode) -> int:
    """Create the directory `path` with permission bits `mode`. 0 or -1.

    `mode` is REQUIRED, not defaulted to 0777: a default argument is not
    applied to a call from another image, and a directory created with an
    arbitrary mode is a real directory with unusable permissions. Pass 511 for
    0777, which is what CPython's default is — the C library masks it with the
    process umask either way.

    -1 with EEXIST when the directory is already there, which is the same
    signal `makedirs` below uses to decide it has nothing to do.
    """
    return fs_mkdir(path, mode)


def makedirs(path, mode) -> int:
    """Create `path` and every directory above it that is missing.

    `mode` is required, for the reason `mkdir` gives. 0 when the whole path
    exists afterwards, -1 otherwise. An intermediate
    component that is already a directory is not an error, so this is
    CPython's `makedirs(path, exist_ok=True)` and there is no spelling of the
    other one: a target with no exceptions cannot report "FileExistsError" to
    a caller that did not ask for it, and inventing a status nobody can
    distinguish from a real failure would be worse than being permissive.

    The walk is over the string's own separators, so a path whose parent does
    not exist and cannot be created returns -1 from the first `mkdir` that
    fails rather than carrying on.
    """
    n = str_len(path)
    if n == 0:
        return 0 - 1
    i = 1 if str_starts(path, "/") == 1 else 0
    while i <= n:
        j = _prefix_end(path, i, n)
        if j > i:
            if _make_one(path, j, mode) < 0:
                return 0 - 1
        i = j + 1
    return 0


def _prefix_end(path, i, n) -> int:
    """Index of the next `/` at or after `i` in `path`, or `n` if there is none.

    The step `makedirs` takes between components. Returning the index of the
    separator rather than the end of the component means the caller can tell a
    component that is there from a trailing separator that is not one, which is
    the difference between creating `"a/b"` and creating `""`.
    """
    j = i
    while j < n and str_at(path, j, "/") == 0:
        j = j + 1
    if j > n:
        j = n
    return j


def _make_one(path, j, mode) -> int:
    """Create the directory `path[0:j]` unless it is already there.

    Existence is asked with `isdir` rather than with `errno`, and the reason is
    in `os/_syscalls.mojo`: the C library's error accessor is a name this path
    cannot bind. `isdir` is a fact about the path rather than a code, so it is
    the better question anyway — a component that exists as something other
    than a directory is a failure either way, and this reports it by failing.
    """
    seg = str_prefix(path, j)
    if isdir(seg) == 1:
        return 0
    return fs_mkdir(seg, mode)


def rename(src, dst) -> int:
    """Rename `src` to `dst`, atomically, replacing `dst` if it is there.

    0 on success, -1 on failure. CPython's `os.rename` raises; see the top of
    this module. Note that on a POSIX target this overwrites, so it is
    `replace` as much as `rename`.
    """
    return fs_rename(src, dst)


def replace(src, dst) -> int:
    """`rename(src, dst)`, under CPython's other name for the same call."""
    return fs_rename(src, dst)


def chmod(path, mode) -> int:
    """Set the permission bits of `path`. 0 on success, -1 on failure."""
    return fs_chmod(path, mode)


# ── Listing a directory ───────────────────────────────────────────────────
#
# A LISTDIR IS A BLOB, and the shape is the one every container on this path
# already has — `[count][element]…` — so it is not a new representation. What
# is new is that the blob is `malloc`'d rather than frame-resident, which is
# what a length only known at RUN TIME needs: a frame blob dies with the
# function that built it, so it cannot be returned, and
# `bugs/FORMAL_listdir_no_run_time_sequence.md` records that as the reason
# there was no `listdir` at all. The allocation is the whole difference, and
# `malloc` was always there.
#
#     word 0      count, as an Int64
#     word 1..n   one `char *` per entry, in `readdir` order
#
# The four functions below are the whole of the API, and the split is not
# taste: this path has no way to return a container whose length is a run-time
# value AND hand the caller a Python-level list, so the result is a word and
# the length and the elements are read out of it by name. `len(names)` does not
# work — a pointer has no count for the builtin to read — and `names[i]` does
# not either, because the subscript would be asking the blob-walk question
# about a pointer. `listdir_len` and `listdir_get` ask them of the blob, which
# IS the shape those operations are about.

def listdir(path) -> int:
    """The entries of the directory `path`, or 0 when there is no such
    directory.

    A BLOB, not a list: `listdir_len` says how many entries there are,
    `listdir_get` hands back entry `i`, and `listdir_free` releases the whole
    thing. The caller OWNS the result and every name in it.

    `.` and `..` are NOT in it, as in CPython. The order is the C library's
    `readdir` order, which is the filesystem's own and not sorted — CPython's
    order is the same one, so a caller that wants a sorted listing has to sort
    it, exactly as in CPython.

    A path that is not a directory, and a path that does not exist, are both 0,
    and there is no exception to raise (FORMAL.md phase 7). The two are not
    told apart: the C library's error accessor is a name this path cannot bind,
    and the question a caller actually has — "is there anything here" — is
    answered by 0 either way.

    TWO PASSES OVER THE DIRECTORY, and the reason is the size. The C library
    will not say how many entries there are without reading them, and a blob
    has to be exactly as long as its contents: a blob with room to spare would
    have a length that is a property of the program rather than of the
    directory, and every caller of it would be wrong in a way nothing
    downstream could detect. So this counts, `rewinddir`s, and copies. The cost
    is one extra pass over the directory's names, which is a few hundred
    `readdir` calls, and the benefit is that the count in word 0 is a fact
    about the directory.
    """
    d = fs_opendir(path)
    if d == 0:
        return 0
    n = _listdir_count(d)
    var b: Pointer[Int64] = malloc(8 * (1 + n))
    memset(b, 0, 8 * (1 + n))
    b[0] = 0
    _listdir_fill(d, b)
    fs_closedir(d)
    return b


def _listdir_count(d) -> int:
    """How many entries the open descriptor `d` will yield, `.`/`..` dropped.

    Reads the directory to the end and rewinds it, so `d` is ready for
    `_listdir_fill`. Split out of `listdir` because it is a different question
    with a different failure mode — it allocates nothing and cannot overflow
    anything — and one function that did both would have two reasons to fail in
    a diagnostic that could only name one.
    """
    n = 0
    var e: Pointer[UInt8] = fs_readdir(d)
    while e != 0:
        if fs_name_is_dot(fs_dirent_name(e)) == 0:
            n = n + 1
        e = fs_readdir(d)
    fs_rewinddir(d)
    return n


def _listdir_fill(d, b: Pointer[Int64]) -> int:
    """Copy the entries of `d` into the blob `b` at word 1 on. Returns the
    count written.

    `b`'s size is the caller's decision and is `8 * (1 + count)`, so this
    cannot write past it — the caller counted with the same rule. `b` is
    ANNOTATED `Pointer[Int64]` and that is what makes `b[0]`, `b[1 + b[0]]` and
    the stores between them eight-byte operations on the words a blob's
    elements are; without it every one of them is a blob walk over a pointer.
    """
    n = 0
    var e: Pointer[UInt8] = fs_readdir(d)
    while e != 0:
        nm = fs_dirent_name(e)
        if fs_name_is_dot(nm) == 0:
            b[1 + n] = nm
            n = n + 1
        e = fs_readdir(d)
    b[0] = n
    return n


def listdir_len(names: Pointer[Int64]) -> int:
    """How many entries a `listdir` blob holds, or -1 for something that is not
    one.

    Word 0, which is where every container on this path keeps its count, so
    this is `len(names)` for a value that has a count to read. The -1 is for a
    0 — what `listdir` returns for a path that is not a directory — and it is
    the only way to tell "an empty directory" (0) from "no directory" (-1)
    through a single word, which is why this is a function and not a word the
    caller reads.
    """
    if names == 0:
        return 0 - 1
    return names[0]


def listdir_get(names: Pointer[Int64], i) -> str:
    """Entry `i` of a `listdir` blob, or `""` when `i` is out of range.

    An ALIAS, not a copy: the name is one of the buffers the blob owns, so it
    lives as long as the blob does and must NOT be passed to `os_free` on its
    own — `listdir_free` releases it. A negative `i` is out of range here, not
    a count from the end: this is a blob of pointers, not a Python list, and
    the two index conventions are one more thing a caller would have to know.
    """
    if names == 0:
        return ""
    if i < 0:
        return ""
    if i >= names[0]:
        return ""
    return names[1 + i]


def listdir_free(names: Pointer[Int64]) -> int:
    """Release a `listdir` blob and every name in it. 0.

    Every name is its own `malloc`'d buffer — a `readdir` result does not
    outlive the next `readdir`, so `fs_dirent_name` copies — and the blob is
    another one, so a listing is `1 + n` allocations and this is all of them.

    0 for a 0, so the same call releases "nothing" and a caller that never had
    a directory does not have to test first.
    """
    if names == 0:
        return 0
    i = 0
    while i < names[0]:
        free(names[1 + i])
        i = i + 1
    free(names)
    return 0


# ── Walking a tree ────────────────────────────────────────────────────────
#
# `walk` is `listdir` applied recursively, and the shape of its answer is
# decided by the same thing that decides `listdir`'s: a blob in `malloc`'d
# memory rather than a frame blob, because the number of directories below a
# root is not known until the tree has been read.
#
# The blob holds DIRECTORY PATHS, one per word from word 1 on, in PRE-ORDER:
# a directory comes before everything under it, and each level's entries come
# in the order `listdir` gave them. `listdir_len` and `listdir_get` read it, so
# a walk and a listing are read the same way, and `walk_free` releases one.
#
# CPython's `os.walk` yields `(dirpath, dirnames, filenames)` triples, and this
# yields PATHS rather than triples, for the reason every other collection here
# does: a tuple is a frame blob on this path and cannot be returned. The caller
# calls `listdir` on each path it gets, and that is where the entries of that
# one directory are. A walk is therefore `for each path: listdir(path)`, spelled
# as an index over the blob because a list of a run-time length is what this
# whole arrangement exists to avoid.

def walk(root, maxdepth) -> int:
    """Every directory at or below `root`, down to `maxdepth` levels, or 0 when
    `root` is not a directory.

    `maxdepth` is REQUIRED rather than defaulted, for the reason every
    parameter in this module is (see the note at the top of this file): a
    default argument is not applied to a call from another image. `walk(root, 0)`
    is the root alone and `walk(root, 1)` is the root and its immediate
    subdirectories, which is CPython's `topdown` depth counted the same way.

    THE CALLER OWNS THE RESULT and every path in it; `walk_free` releases it.
    Each path is a fresh `malloc`'d buffer, including the root, so a caller
    that wants to keep one past the walk has to copy it — and `listdir_get`'s
    note about aliasing does not apply here, because there is nothing to alias.

    TWO PASSES, the same bargain `listdir` makes and for the same reason: one
    to count the directories so the blob is exactly the right size, one to copy
    them. The count is what the C library will not give us, and a blob with
    room to spare has a length that is a property of the program.

    ONE DIVERGENCE FROM `os.walk`, and it is pinned rather than papered over:
    this FOLLOWS a symbolic link to a directory and CPython's `os.walk` does
    NOT unless it is given `followlinks=True`. The test is `isdir`, and
    `isdir` follows, which is right for `isdir` and is why a link to a
    directory appears here as a directory to descend into. Two consequences,
    both real: a tree with a link back up to an ancestor is walked forever,
    which is a `maxdepth` question and `maxdepth` is the caller's; and the
    same directory appears once per path that reaches it. Making it CPython's
    rule would mean asking `islink` as well as `isdir` at every entry, which is
    one more call per entry and a different answer for `walk(root, 0)`.
    `test_formal_os_backing.py`'s `listdir_and_walk` case runs against
    `os.walk(followlinks=True)` and has a `dl` in the fixture tree, so the
    question is asked on every run rather than described here.
    """
    if isdir(root) == 0:
        return 0
    n = 1 + _walk_dirs(root, maxdepth)
    var b: Pointer[Int64] = malloc(8 * (1 + n))
    memset(b, 0, 8 * (1 + n))
    # `_walk_fill` starts at word 1 and returns the NEXT FREE WORD, so the
    # count is one less than what it returns. The subtraction is here rather
    # than in the callee because the callee writes the paths and this writes
    # the count, and a blob's count is the blob's own business — getting it
    # wrong puts a PATH in word 0, which reads as a count of billions and turns
    # every read of this blob into a walk off the end of the heap. Measured,
    # from the version that did exactly that: `walk(root, 0)` segfaulted on the
    # first `listdir_get`.
    b[0] = _walk_fill(root, maxdepth, b, 1) - 1
    return b


def _walk_dirs(root, maxdepth) -> int:
    """How many directories are strictly below `root` within `maxdepth` levels.

    Reads the tree and allocates a path for every entry it tests, then frees
    it: the counting pass must not leak, and it must not keep what it measured
    either, so every path it builds dies inside it.
    """
    if maxdepth <= 0:
        return 0
    names = listdir(root)
    n = 0
    i = 0
    while i < listdir_len(names):
        p = str_build(root, "/", listdir_get(names, i))
        if isdir(p) == 1:
            n = n + 1 + _walk_dirs(p, maxdepth - 1)
        free(p)
        i = i + 1
    listdir_free(names)
    return n


def _walk_fill(root, maxdepth, b: Pointer[Int64], i) -> int:
    """Write `root` at blob word `i` and everything under it, and return the
    next free word.

    The `i` is a PARAMETER and the next index is the RETURN because there is
    no way to hand back two things: a recursion that appended to a blob needs
    to say both how far it got and whether the blob is the caller's, and
    passing the index in and returning the next one is the only shape that
    carries both.

    The recursion's depth is `maxdepth`, which the CALLER bounds. Nothing here
    bounds it, and a tree deep enough to exhaust the stack is a tree no
    directory walk on any system should be pointed at; `maxdepth` is where that
    decision is made, and it is made by the caller who knows the tree.
    """
    b[i] = str_dup(root)
    i = i + 1
    if maxdepth <= 0:
        return i
    names = listdir(root)
    j = 0
    while j < listdir_len(names):
        p = str_build(root, "/", listdir_get(names, j))
        if isdir(p) == 1:
            i = _walk_fill(p, maxdepth - 1, b, i)
        free(p)
        j = j + 1
    listdir_free(names)
    return i


def walk_free(paths: Pointer[Int64]) -> int:
    """Release a `walk` blob and every path in it. 0.

    Every path in a walk is a fresh buffer, so this is the same shape as
    `listdir_free` and for the same reason, and 0 for a 0 so the same call
    releases "nothing" and a caller that never had a directory does not have to
    test first.
    """
    if paths == 0:
        return 0
    i = 0
    while i < paths[0]:
        free(paths[1 + i])
        i = i + 1
    free(paths)
    return 0


# ── Releasing what the path functions allocated ────────────────────────────

def os_free(p) -> int:
    """Release a string one of these functions allocated.

    `os.path.join`, `abspath`, `normpath`, `relpath` and the rest return a
    `malloc`'d buffer when the answer is not part of their input, and this is
    how a caller gives it back. The result of `os.path.basename` is a POINTER
    INTO its argument and must not be passed here; each function says which it
    returned.

    Not releasing is a leak and not a wrong answer, which is why nothing above
    calls this on its own: the strings `os` hands back are the caller's to
    keep, and dropping one while a derived string still points into it is the
    caller's decision.
    """
    return fs_free(p)
