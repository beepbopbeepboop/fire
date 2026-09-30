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

  * THERE IS NO RUN-TIME-LENGTH SEQUENCE AND NO DIRECTORY LISTING. A list's
    capacity is the number of `append` SITES in the function that builds it, so
    a list whose length is only known at run time cannot be built — and
    `readdir` reports a name in a buffer whose bytes cannot be read on this
    path anyway. `listdir` and `walk` are therefore absent, and their absence
    is a refusal at the call site with a name in it rather than a function
    that returns something plausible. (bugs/FORMAL_listdir_no_run_time_sequence.md)

  * `environ` IS ITS THREE FUNCTIONS. A process environment is a `char **` in
    the C library's data, and enumerating it needs a buffer walk this path
    cannot do. `getenv`, `putenv` and `unsetenv` are the whole of what can be
    reached, and they are what `os.environ.get(k)` and `os.environ[k]` have to
    become.

  * **NO FUNCTION HERE HAS A DEFAULT ARGUMENT.** This one is a backend
    defect rather than a property of the target, it is measured, and it is
    filed as `bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`.
    A call to a function in ANOTHER image does not materialize the callee's
    defaults: the caller has no signature to read them from, so the argument
    register is whatever the caller last left in it. Measured, same source
    either way:

        # dmod.mojo          def need_two(a, b=511): return b
        # in ONE file:       need_two(1)            ->  511
        # across a dylib:    need_two(1)            ->  1867609072

    A default that arrives as a stack address is worse than no default,
    because `mkdir(path, mode)` with a garbage mode SUCCEEDS and leaves a
    directory nobody can enter. So the parameters that CPython gives defaults
    are REQUIRED here: `mkdir(path, mode)`, `makedirs(path, mode)` and
    `relpath(path, start)` are all spelled with every argument, and the one
    place a default is genuinely wanted — `getenv`'s — is a SECOND function,
    `getenv_or(name, default)`, so the two-argument form has a name of its own
    rather than a signature that silently does nothing.
"""

from ._syscalls import str_alloc, str_len, str_at, str_prefix, str_starts
from ._syscalls import fs_cwd, fs_getenv, fs_setenv, fs_unsetenv
from ._syscalls import fs_chdir, fs_chmod, fs_rename, fs_unlink, fs_rmdir
from ._syscalls import fs_mkdir, fs_free
from .path import exists, isfile, isdir, islink, lexists, getsize

# ── The constants CPython spells as attributes ──────────────────────────────
#
# Functions, and the reason is at the top of this file. Each returns the
# interned literal, so there is nothing to free and no two calls can disagree.

def sep():
    """The path separator: `"/"`."""
    return "/"


def curdir():
    """The current directory, as a name: `"."`."""
    return "."


def pardir():
    """The parent directory, as a name: `".."`."""
    return ".."


def extsep():
    """The extension separator: `"."`."""
    return "."


def pathsep():
    """The separator between entries of a search path: `":"`."""
    return ":"


def linesep():
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


def devnull():
    """The bit bucket: `"/dev/null"`."""
    return "/dev/null"


# ── The working directory ──────────────────────────────────────────────────

def getcwd():
    """The current working directory, in a fresh buffer the caller owns.

    `""` if the C library cannot report it, which on this target means the
    path is longer than `PATH_MAX`. CPython raises `OSError` there; there is no
    exception to raise, and the empty string is the answer that cannot be
    mistaken for a directory.
    """
    return fs_cwd()


def chdir(path):
    """Change the working directory. 0 on success, -1 on failure.

    CPython raises `OSError`; see the note at the top of this module.
    """
    return fs_chdir(path)


# ── The environment ────────────────────────────────────────────────────────

def getenv(name):
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


def getenv_or(name, default):
    """`getenv(name)`, with `default` as the answer when it is unset.

    A separate function rather than a default argument on `getenv`, and the
    reason is at the top of this module: a default that is not applied is not
    an error, it is a wrong value.
    """
    v = fs_getenv(name)
    if v == 0:
        return default
    return v


def putenv(name, value):
    """Set the environment variable `name`. 0 on success, -1 on failure.

    Always overwrites, which is `os.environ.__setitem__` rather than
    `os.putenv`'s `overwrite=False` default — there is no way to spell the other
    one through a fixed signature, and the overwriting behaviour is the one a
    caller assigning into `environ` means.
    """
    return fs_setenv(name, value, 1)


def unsetenv(name):
    """Remove the environment variable `name`. 0 on success, -1 if it was
    not set."""
    return fs_unsetenv(name)


# ── Creating, removing and renaming ────────────────────────────────────────

def remove(path):
    """Remove the file at `path`. 0 on success, -1 on failure.

    `os.remove` and `os.unlink` are the same call on a POSIX target and are
    both here; the C library's `unlink` is reached through `os/_syscalls.mojo`
    because a unit that both defined `remove` and called libc's `remove` would
    emit a call to itself.

    CPython raises `FileNotFoundError` for a path that is not there. This
    returns -1 and the caller tests it; the reason is at the top of this file.
    """
    return fs_unlink(path)


def unlink(path):
    """`remove(path)`, under the other name CPython gives it."""
    return fs_unlink(path)


def rmdir(path):
    """Remove the DIRECTORY at `path`. 0 on success, -1 on failure."""
    return fs_rmdir(path)


def mkdir(path, mode):
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


def makedirs(path, mode):
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


def _prefix_end(path, i, n):
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


def _make_one(path, j, mode):
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


def rename(src, dst):
    """Rename `src` to `dst`, atomically, replacing `dst` if it is there.

    0 on success, -1 on failure. CPython's `os.rename` raises; see the top of
    this module. Note that on a POSIX target this overwrites, so it is
    `replace` as much as `rename`.
    """
    return fs_rename(src, dst)


def replace(src, dst):
    """`rename(src, dst)`, under CPython's other name for the same call."""
    return fs_rename(src, dst)


def chmod(path, mode):
    """Set the permission bits of `path`. 0 on success, -1 on failure."""
    return fs_chmod(path, mode)


# ── Releasing what the path functions allocated ────────────────────────────

def os_free(p):
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
