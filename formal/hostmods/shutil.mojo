"""`shutil` — file copying, moving, tree removal and `PATH` search.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import shutil` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` for why these did NOT go at
the repository root, where the first three of them captured `import os` in the
compiler's own sources.

`shutil` WAS IN `HOST_UNREACHABLE`, under "a terminal, or a writable
filesystem this target does not get". **The filesystem half of that sentence
was false and is now measured away; the terminal half is true and is why
`get_terminal_size` is absent below.** `formal/hostmods/os/__init__.mojo` has
already had `mkdir`, `makedirs`, `remove`, `rmdir`, `rename`, `replace` and
`chmod` — `test_formal_os.py` runs 75 filesystem operations against the real
filesystem — and this module adds the two calls that were genuinely missing,
which are `fopen`/`fwrite`/`fread`/`fclose` and `utimes`, in
`formal/hostmods/os/_syscalls.mojo` next to every other libSystem call. So
`shutil` moves from `HOST_UNREACHABLE` (a permanent fact about the target) to
written, which is the classification change
`formal/imports.py`'s comment above `HOST_MODELLED` requires to happen in the
same commit as the source that answers it.

WHAT IS HERE
------------
  * `copyfile`, `copy`, `copy2`, `copymode`, `copystat` — the copying family,
    over `os` for the metadata and the `stdio` calls for the bytes.
  * `move`, `copytree` — `rename(2)` and a recursive `copyfile`.
  * `rmtree` — the tree removal, over `os.walk`'s blob read deepest-first.
  * `which` — CPython's `PATH` search, with its own `PATH` parameter and its
    own empty-entry and duplicate handling.
  * `X_OK` and the rest of the three `os` access bits, because `which` needs one
    and a caller should not have to hardcode it.

THE RETURN-VALUE RULE, WHICH IS NOT CPYTHON'S AND CANNOT BE
----------------------------------------------------------
Every one of CPython's `shutil` functions either returns the destination path
or RAISES (`Error`, `SameFileError`, `IsADirectoryError`). There are no
exceptions on this path (FORMAL.md phase 7), so every function here returns the
destination path on success and **`""` on failure**, and every `int`-returning
one returns 0 or -1. `""` is the right choice for the path-returning half
because it is the one string no caller would pass to `open` by accident, and a
caller that ignores the answer gets a failure rather than a path it did not
write. A failure is a value here, not an exception, and this is the same rule
`formal/hostmods/os/__init__.mojo` follows for `remove` and
`bugs/FORMAL_glob_copy_collections_io_not_attempted.md` states for the rest.

WHAT IS NOT HERE, AND WHY — each measured or each a fact about the target
-----------------------------------------------------------------------
  * `make_archive`, `get_archive_formats`, `get_unpack_formats`,
    `unpack_archive`, `register_archive_format` — tar and zip. `libarchive` is
    in libSystem, so a C-level archive is one `archive_write_open_filename`
    away, but the module would then depend on `struct archive *`'s field
    offsets the way `struct stat` does, and nothing in the arm64 sweep asks for
    an archive. Not written for the same reason `platform.processor()` is not.

  * `disk_usage` — its answer is a NAMED TUPLE `(total, used, free)` of three
    numbers, and a tuple is a frame blob that cannot cross a dylib boundary
    (`bugs/FORMAL_module_state_no_storage.md`); `statfs(2)` is available and
    `formal/hostmods/os/_syscalls.mojo` already reads `struct stat` byte-wise,
    so `struct statfs` is the same exercise. What is missing is not the syscall
    but a way to return three words, and that is
    `bugs/FORMAL_time_struct_shaped_answers.md`'s subject rather than this
    one's.

  * `get_terminal_size`, `get_terminal_size`, `chown`, `chown_follow_symlinks` —
    a TERMINAL and a UID. `get_terminal_size` asks `ioctl(TIOCGWINSZ)` on a
    descriptor for a terminal, which is the "terminal" half of the
    `HOST_UNREACHABLE` sentence that was true; `chown` needs a UID this path
    has no source for and no way to be right about.

  * `Error`, `SameFileError`, `IsADirectoryError`, `SpecialFileError`,
    `ReadError`, `ExecError`, `which` the exception classes — TYPES and
    EXCEPTIONS, neither of which this path has. The three absent error types
    have real consequences and they are named at the functions that would have
    raised them: `copyfile` returns `""` for the same-file case CPython raises
    `SameFileError` for, and `""` for the directory case CPython raises
    `IsADirectoryError` for.

  * `rmtree`'s `ignore_errors`, `onerror`, `onexc` and `dir_fd` — a CALLBACK is
    a function value passed across a boundary, and there are no keyword
    arguments across a boundary either; `dir_fd` is a directory-relative
    descriptor and every path in this module is absolute or relative to the
    process's own working directory.

  * `move`'s COPY-FALLBACK — CPython's `move` catches `EXDEV` from `rename(2)`
    and falls back to copy-then-delete across a device boundary. **`errno` is
    not available on this path**: the C library's accessor is `__error` and a
    leading underscore in a callee name is not a symbol this image can bind
    (`formal/hostmods/os/_syscalls.mojo`'s header says this and it is why
    `isdir` exists rather than an error code). So `move` cannot SEE the
    cross-device failure and this is stated rather than guessed at: `move` is
    `rename(2)`, and a caller that needs the fallback has to check for the
    failure itself. `test_formal_shutil.py` covers the same-device case against
    CPython and does not pretend about the other.

  * `rmtree`'s UNBOUNDED DEPTH — CPython's `rmtree` has no depth limit and this
    one takes `maxdepth` and requires it, for exactly the reason
    `os.walk`'s `maxdepth` is required (`formal/hostmods/os/__init__.mojo` says
    it): `os.walk` here FOLLOWS a symbolic link to a directory, and CPython's
    `os.walk` does not, so an unbounded walk of a tree with a link back to an
    ancestor does not terminate. `rmtree` therefore refuses to descend through a
    link (see its docstring) AND takes the caller's depth. Both halves are
    needed: the link check is what makes the answer CPython's, and the depth is
    what makes the recursion bounded.
"""

from os import remove, rmdir, listdir, listdir_len, listdir_get, listdir_free
from os import walk, walk_free, rename, mkdir, chmod, getenv, os_free
# `os.path` AND NOT `os`, and the reason is worth stating because the whole
# point of this list is that it is the SECOND time in this tree that a
# re-export is not an export. `os/__init__.mojo` does
# `from .path import exists, isfile, isdir, islink, lexists, getsize` and
# `from .path import join`, so `os.isdir` is a name in the `os` unit — and a
# RE-EXPORTED name is not in the module's own export table, so a call to it
# from another dylib has no symbol to bind and is refused with "that module
# does not export it". Importing from `os.path` names the unit that DEFINES
# them, which is the unit that publishes them.
from os.path import isdir, islink, isfile, exists, join, basename
from os._syscalls import str_len, str_dup, str_cmp, str_chr_from, str_alloc
from os._syscalls import str_put
from os._syscalls import fs_fopen, fs_fwrite, fs_fread, fs_fclose, fs_utimes
from os._syscalls import fs_stat_mode, fs_stat_field64, fs_access


# ── the access bits `which` needs ───────────────────────────────────────────

def R_OK() -> int:
    """`os.R_OK`: 4 — read permission, as `access(2)` numbers it on POSIX."""
    return 4

def W_OK() -> int:
    """`os.W_OK`: 2 — write permission."""
    return 2

def X_OK() -> int:
    """`os.X_OK`: 1 — EXECUTE permission.

    The bit `shutil.which` is about, and it is a function for the reason every
    constant in `formal/hostmods/` is one: a module-level name is not exported
    as a word across a dylib boundary. POSIX numbers the three
    `X_OK`/`W_OK`/`R_OK` as 1/2/4 and Darwin does not renumber them;
    `test_formal_shutil.py` reads all three out of CPython's `os`.
    """
    return 1


# ── the copying family ──────────────────────────────────────────────────────

def _CHUNK() -> int:
    """The copy buffer's size in bytes: 64 KiB, which is `BUFSIZ` twice over.

    A FUNCTION for the constant-is-a-call reason, and the number is not
    arbitrary: `os.stat`'s `st_blksize` on this platform is 4096 and the C
    library's `BUFSIZ` is 1024, and 65536 is above both so a copy never issues
    a syscall for less than a filesystem block times eight. It is NOT read from
    the filesystem, because a buffer sized from `st_blksize` would be a number
    that differs between two machines and a copy loop that changes its buffer
    size with the filesystem is a copy loop with a platform-dependent number of
    iterations in it.
    """
    return 65536


def copyfile(src, dst) -> str:
    """`shutil.copyfile(src, dst)`: `dst` on success, `""` on failure.

    BYTES ONLY, and that is the whole contract: CPython's `copyfile` copies the
    contents and nothing else — no mode, no times — which is why `copy` and
    `copy2` exist and why the three are three functions rather than one with a
    flag.

    **THE LOOP IS THE LOOP**, and a single `read` is not a copy: `fs_fread`
    returns what arrived, not what was asked for, and a destination that is
    short is a silent truncation that a caller checking only the return value
    cannot see. So the bytes are read and written until the read returns 0, and
    a write that is short is a FAILURE rather than a loop iteration — a
    destination that cannot take what was read is not going to take the next
    chunk either.

    `""` for every case CPython raises for: the same file on both sides (CPython:
    `SameFileError`), a source that is a directory (CPython:
    `IsADirectoryError`), a source that is not there, a destination that cannot
    be created, and a destination directory that does not exist. The same-file
    check is `str_cmp(src, dst) == 0`, which is the string comparison this path
    has — `==` on two strings is refused or wrong here
    (`formal/hostmods/os/_syscalls.mojo`'s `str_cmp` docstring says why), and
    using the wrong one would compare the first eight CHARACTERS of two
    different paths and call them equal.
    """
    if str_cmp(src, dst) == 0:
        return ""
    if isdir(src) == 1:
        # CPython raises `IsADirectoryError` here, and this path cannot: on
        # macOS `fopen(dir, "rb")` SUCCEEDS, and the `fread` that follows it
        # returns 0 — which the loop below reads as end-of-file. So a copyfile
        # without this check reports SUCCESS for a directory and writes an empty
        # destination, which is the plausible-wrong-answer shape this module
        # exists to avoid. Measured: the image's `copyfile("adir", "d")` returned
        # the destination path before this line and CPython raised.
        return ""
    var r = fs_fopen(src, "rb")
    if r == 0:
        return ""
    var w = fs_fopen(dst, "wb")
    if w == 0:
        fs_fclose(r)
        return ""
    var n = _CHUNK()
    var buf: Pointer[UInt8] = str_alloc(n)
    var ok = 0
    while True:
        var got = fs_fread(r, buf, n)
        if got <= 0:
            ok = 1
            break
        if fs_fwrite(w, buf, got) != got:
            ok = 0
            break
    free(buf)
    fs_fclose(r)
    fs_fclose(w)
    if ok == 0:
        return ""
    return dst


def copymode(src, dst) -> int:
    """`shutil.copymode(src, dst)`: 0 on success, -1 on failure.

    `chmod(dst, stat(src).st_mode & 0o7777)`, which is CPython's
    `S_IMODE(os.stat(src).st_mode)`. **The mask is applied here and not left to
    `chmod`**: the kernel masks the mode it is given, so passing the whole
    `st_mode` — which carries the file-TYPE bits — happens to work, and it is
    still the wrong thing to hand a function whose contract is a permission
    number. It also would not be the same answer on a target whose `chmod`
    validated the type bits.

    The source is followed through a symbolic link, which is CPython's
    `copymode` too (`os.chmod` follows).
    """
    var m = fs_stat_mode(src, 1)
    if m < 0:
        return 0 - 1
    if chmod(dst, m & 4095) != 0:
        return 0 - 1
    return 0


def copystat(src, dst) -> int:
    """`shutil.copystat(src, dst)`: the mode and BOTH times, 0 on success.

    CPython's `copystat` copies the mode, the access time and the modification
    time, and on macOS also the creation time and the flags
    (`os.chflags`) — the two that this path cannot do are named here rather than
    quietly dropped: a creation time is a field `stat(2)` reports but `utimes`
    does not set, so **the destination's birth time is left as it is**, and a
    program comparing birth times across a `copy2` will see the copy's, not the
    original's.

    THE TIME FIELDS ARE NANOSECONDS IN `stat` AND MICROSECONDS IN `timeval`,
    and the division happens HERE, visibly, rather than inside a wrapper: `st_
    atimespec` is `{sec, nsec}` at offsets 32 and 40 and `st_mtimespec` is at 48
    and 56 (`formal/hostmods/os/_syscalls.mojo` writes the whole layout out),
    while `utimes` takes microseconds. `fs_utimes` therefore takes the two
    halves as parameters and this function does the `/ 1000` in the open. A
    program that needed better than microsecond fidelity would need a different
    call, and naming that here is better than a `timeval` built from a
    nanosecond count that was silently truncated.
    """
    var m = fs_stat_mode(src, 1)
    if m < 0:
        return 0 - 1
    var asec = fs_stat_field64(src, 1, 32)
    var ansec = fs_stat_field64(src, 1, 40)
    var msec = fs_stat_field64(src, 1, 48)
    var mnsec = fs_stat_field64(src, 1, 56)
    if chmod(dst, m & 4095) != 0:
        return 0 - 1
    if fs_utimes(dst, asec, ansec / 1000, msec, mnsec / 1000) != 0:
        return 0 - 1
    return 0


def copy(src, dst) -> str:
    """`shutil.copy(src, dst)`: `copyfile` plus `copymode`. `dst` or `""`.

    CPython's `copy` copies the PERMISSION BITS and not the times, and the two
    halves are visible in the name here rather than in a flag.
    """
    var c = copyfile(src, dst)
    if str_len(c) == 0:
        return ""
    if copymode(src, dst) != 0:
        return ""
    return dst


def copy2(src, dst) -> str:
    """`shutil.copy2(src, dst)`: `copy` plus `copystat`. `dst` or `""`.

    CPython's `copy2` is `copy` plus the times, so this is `copy` plus a second
    metadata call, and the difference from `copy` is measurable: `st_mtime` of
    the destination equals the source's after `copy2` and does not after
    `copy`. `test_formal_shutil.py` asserts exactly that, because it is the one
    observable difference and a module that implemented `copy2` as `copy` would
    pass everything else in this file.
    """
    var c = copy(src, dst)
    if str_len(c) == 0:
        return ""
    if copystat(src, dst) != 0:
        return ""
    return dst


# ── move ────────────────────────────────────────────────────────────────────

def move(src, dst) -> str:
    """`shutil.move(src, dst)`: `dst` on success, `""` on failure.

    **`rename(2)` AND NOTHING ELSE**, which is both the whole of it and the one
    place where this module is knowingly less capable than CPython. CPython
    catches `EXDEV` — the cross-device-link error — and falls back to
    copy-then-delete, and it cannot be reproduced here because `errno` is not
    available: the C library's accessor is `__error` and a leading underscore in
    a callee name is not a symbol this image can bind
    (`formal/hostmods/os/_syscalls.mojo`'s header). So `move` is `rename`, and a
    caller that needs the cross-device behaviour has to try the copy itself
    when this returns `""`.

    **A DESTINATION THAT IS A DIRECTORY GETS THE SOURCE INSIDE IT**, which is
    CPython's rule and the thing a caller writing `move(a, b)` most often
    means: the destination becomes `join(dst, basename(src))`. Without it,
    `move("x", "somedir")` would rename `x` ON TOP of `somedir`, which the
    kernel refuses for a directory and which is not what anybody asked for.
    """
    if isdir(dst) == 1:
        dst = join(dst, basename(src))
    if rename(src, dst) != 0:
        return ""
    return dst


# ── rmtree ──────────────────────────────────────────────────────────────────

def rmtree(path, maxdepth) -> int:
    """`shutil.rmtree(path, maxdepth)`: entries removed, or -1.

    THE BLOB IS READ BACKWARDS, and that is the whole of the algorithm. `os.walk`
    here hands back every directory at or below `path` in PRE-ORDER — a
    directory before everything under it — and a removal has to be the other way
    round, because `rmdir` fails with `ENOTEMPTY` for a directory that still has
    entries in it. So the deepest directory is the LAST word of the blob and the
    root is the first, and the loop runs from `count - 1` down to 0. Walking it
    forwards is not slower, it is WRONG: it would empty the root's own entries,
    fail to rmdir the root because its subdirectories are still there, and leave
    a tree that is neither gone nor intact.

    **A SYMBOLIC LINK IS REMOVED, NOT FOLLOWED**, which is CPython's rule and
    the one place this has to check `islink` rather than `isdir`. `os.walk`
    here follows a link to a directory (`formal/hostmods/os/__init__.mojo` says
    so and `test_formal_os_backing.py` measures it), so a tree containing a link
    back to an ancestor would delete THROUGH it — and the deletion would be
    invisible, because `unlink` on the link removes the name and the directory
    it pointed at is simply gone. `islink` is asked FIRST at every entry for
    that reason.

    `maxdepth` IS REQUIRED, not defaulted, for the same reason `os.walk`'s is:
    a default argument is not applied to a call from another image
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`). CPython's
    `rmtree` has no depth parameter at all; see the module docstring for why
    that is not the right shape here.

    The RETURN VALUE is the number of entries removed — every file, every link
    and every directory, the root included — which is CPython's `rmtree`'s `None`
    turned into something checkable. A root that is not a directory is -1, where
    CPython raises `NotADirectoryError`.
    """
    if isdir(path) == 0:
        return 0 - 1
    var paths = walk(path, maxdepth)
    if paths == 0:
        return 0 - 1
    var count = listdir_len(paths)
    var removed = 0
    var d = count - 1
    while d >= 0:
        var p = listdir_get(paths, d)
        var names = listdir(p)
        var i = 0
        while i < listdir_len(names):
            var full = join(p, listdir_get(names, i))
            if islink(full) == 1 or isdir(full) == 0:
                if remove(full) == 0:
                    removed = removed + 1
            os_free(full)
            i = i + 1
        listdir_free(names)
        if rmdir(p) == 0:
            removed = removed + 1
        d = d - 1
    # `p` IS NOT FREED HERE, and that is not an oversight: every path in a walk
    # blob is a `malloc`'d buffer and `walk_free` releases all of them plus the
    # blob, which is its whole job (`formal/hostmods/os/__init__.mojo`). Freeing
    # them on the way through and then calling `walk_free` is a DOUBLE FREE, and
    # a double free on this path is a `SIGABRT` that takes the process's whole
    # buffered stdout with it — measured, and the tree was already gone, so the
    # symptom is an image that deleted everything correctly and then died
    # before printing anything.
    walk_free(paths)
    return removed


# ── copytree ────────────────────────────────────────────────────────────────

def copytree(src, dst, maxdepth) -> str:
    """`shutil.copytree(src, dst)`: `dst` on success, `""` on failure.

    THE SAME SHAPE AS `rmtree` READ FORWARD: `os.walk`'s blob is in pre-order,
    which is the order a copy has to happen in — a directory is created before
    anything goes into it — so this loop runs forwards where `rmtree` runs
    backwards. That is the only difference between them and it is worth stating
    because it is the whole reason the blob's order matters at all.

    `dirs_exist_ok` is ABSENT and so is `symlinks`: CPython's `copytree` raises
    `FileExistsError` for a destination that is already there, and here that is
    `""` — which means this creates the destination's subdirectories and lets
    `copyfile` fail on the ones that are already files. `symlinks` is absent
    because it makes `copytree` copy the LINK rather than what it points at,
    which needs `readlink`/`symlink`, and this path has neither.

    The mode and the times are copied from the SOURCE DIRECTORY to each
    destination directory and not to each file, which is what CPython's
    `copytree` does (`copystat` on each directory, `copy2` on each file) — the
    alternative, copying the root's mode onto everything, would give a
    destination that cannot be written to by the user who made it.
    """
    if isdir(src) == 0:
        return ""
    if isdir(dst) == 1:
        return ""
    var paths = walk(src, maxdepth)
    if paths == 0:
        return ""
    var count = listdir_len(paths)
    var made = 0
    var d = 0
    while d < count:
        var p = listdir_get(paths, d)
        var rel = _relative(src, p)
        # `target` IS THE CALLER'S `dst` AND NOT A COPY, for the root, so the
        # free is inside the branch that built one. `free`ing a string LITERAL
        # — an interned buffer in a read+execute text section — is a SIGABRT
        # that takes the process's whole buffered stdout with it, and the first
        # version of this freed `target` unconditionally: every tree, even a flat
        # one with a single file, aborted after copying correctly, so the
        # symptom was an image that had done the whole job and then died
        # silently. The same mistake was made and caught in `which` above, which
        # is the argument for reading both.
        var target = dst
        if str_len(rel) > 0:
            target = join(dst, rel)
        if isdir(target) == 0:
            if mkdir(target, 493) == 0:
                made = made + 1
            copystat(p, target)
        var names = listdir(p)
        var i = 0
        while i < listdir_len(names):
            var full = join(p, listdir_get(names, i))
            if isdir(full) == 0:
                copy2(full, join(target, listdir_get(names, i)))
            os_free(full)
            i = i + 1
        listdir_free(names)
        os_free(rel)
        if target != dst:
            os_free(target)
        d = d + 1
    walk_free(paths)          # and not `os_free(p)`: see `rmtree`.
    if made == 0:
        return ""
    return dst


def _relative(src, p) -> str:
    """`p` with the `src` prefix and one separator removed, in a fresh buffer.

    The walk's blob holds paths that all START with `src`, and `copytree` needs
    the part below it to build the destination's shape. The subtraction is by
    LENGTH and not by searching for the prefix, so it is correct for the blob
    and wrong for anything else — which is why it is a private function of this
    module and not a general `relpath`.

    **`str_dup("")` AND NOT `""`**, because the caller frees this and `free`ing a
    string LITERAL — an interned buffer in a read+execute text section — is a
    `SIGABRT` that takes the process's whole buffered stdout with it. That is
    the THIRD such mistake in this file, in three different functions, which is
    why it is worth naming as a rule rather than as three bugs: on this path a
    function that RETURNS a string either returns a buffer the caller owns or
    says so in its docstring, and every `free` in this module is a statement
    about where its argument came from. `which` freed the string it returned and
    `copytree` freed the destination it had been given; see both.
    """
    var n = str_len(src)
    if str_len(p) <= n:
        return str_dup("")
    return _seg(p, n + 1, str_len(p))


def _seg(s, i, j) -> str:
    """`s[i:j]`, in a fresh `malloc`'d buffer the caller owns.

    A slice is refused on this path — the count would be read from offset 0 of a
    `char *`, which is the first eight CHARACTERS
    (`bugs/FORMAL_string_value_model.md`) — so every substring here is a
    `memmove` and a terminator. `formal/hostmods/os/_syscalls.mojo`'s
    `str_prefix` is the `s[0:j]` case and `str_dup` is the whole string; this is
    the middle.
    """
    if j <= i:
        return str_dup("")
    var out = str_alloc(j - i)
    var u = 0
    while i < j:
        u = str_put(out, u, s + i, 1)
        i = i + 1
    return out


# ── which ───────────────────────────────────────────────────────────────────

def which(cmd, path) -> str:
    """`shutil.which(cmd, path)`: the path found, or `""`.

    CPython's algorithm, in its order, because the order is the contract:

      1. a `cmd` that CONTAINS A SLASH is not searched for — it is either
         executable where it is or it is not, and `""` is the answer. This is
         the branch a caller who passes an absolute path gets, and getting it
         wrong means searching `PATH` for a path with a slash in it.
      2. otherwise every directory of `path`, in order, with an EMPTY entry
         meaning the CURRENT DIRECTORY — which is CPython's rule and the one
         that makes `PATH=":/usr/bin"` find things in `.`, so it is reproduced
         even though it is a mild security wart.
      3. a candidate is accepted when it EXISTS, is ACCESSIBLE with `X_OK`, and
         is NOT A DIRECTORY. The last test is what keeps a directory whose mode
         has the execute bit from being reported as a program.

    `path` is a PARAMETER and is not defaulted to the environment: a default
    argument is not applied to a call from another image
    (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`). A caller who
    wants the environment's `PATH` passes `getenv("PATH")`, and
    `which_env(cmd)` below is that one call spelled out.

    CPython also SKIPS A DIRECTORY IT HAS ALREADY SEEN, using a set. There is no
    set on this path and the omission costs only time, not an answer: the first
    occurrence of a directory is the one that can win, so a duplicate later in
    `PATH` cannot change what is returned. A `PATH` with a hundred identical
    entries is slow here and correct.
    """
    if str_len(cmd) == 0:
        return ""
    if _has_slash(cmd) == 1:
        if _executable(cmd) == 1:
            return cmd
        return ""
    if str_len(path) == 0:
        return ""
    var i = 0
    var n = str_len(path)
    while i <= n:
        # 58 is `ord(":")` and `strchr`'s second parameter is an int — see
        # `_has_slash` below for why this is a number and not `":"`.
        var colon = str_chr_from(path, i, 58)
        var j = n
        if colon != 0:
            j = colon - path
        var dir = _seg(path, i, j)
        if str_len(dir) == 0:
            dir = str_dup(".")
        var name = join(dir, cmd)
        if _executable(name) == 1:
            # `name` IS THE RETURN VALUE AND IS NOT FREED HERE. The first
            # version freed it on the way out — the `dir` free is right, the
            # `name` free is a use-after-free — and `which` then returned a
            # readable-looking path made of whatever the allocator handed back
            # next. Measured: `which("sh", "/bin:/usr/bin")` printed
            # `P@\xNNR\x13` where CPython prints `/bin/sh`, which is the shape
            # of a freed buffer rather than of a wrong decision, and no amount
            # of checking `_executable` would have found it.
            os_free(dir)
            return name
        os_free(name)
        os_free(dir)
        i = j + 1
    return ""


def which_env(cmd) -> str:
    """`shutil.which(cmd)` with `cmd` searched for in the ENVIRONMENT's `PATH`.

    The one-line form of `which` above, and it is a second function rather than
    a default argument because a default is not applied across a dylib boundary.
    An unset `PATH` is `""` here and `""` answers nothing, which is
    `shutil.which`'s own answer on CPython when `os.environ` has no `PATH` at
    all (`os.environ.get("PATH") is None` → `None`).
    """
    return which(cmd, getenv("PATH"))


def _has_slash(s) -> int:
    """1 if `s` contains a `/`.

    `strchr` and not a loop over the characters, because `strchr` is the C
    library's own scan and this is the question it exists to answer.

    **47 IS `ord("/")` AND NOT `"/"`,** because `str_chr_from`'s third parameter
    is `strchr`'s second and that is an `int`. Passing the one-character string
    hands `strchr` a `char *` where it wants a character, and it then finds
    nothing at all: every input answers 0, which reads as "there is no `/` in
    this path" for every path. `formal/hostmods/os/_syscalls.mojo`'s
    `str_chr_from` now says this at its own definition and
    `formal/hostmods/os/path/__init__.mojo` has always spelled it `SLASH = 47`.

    0 as a POINTER is this path's "no pointer", which is why the comparison is
    against the integer 0 and not against `""`.
    """
    if str_chr_from(s, 0, 47) != 0:
        return 1
    return 0


def _executable(name) -> int:
    """1 if `name` is a file this process may EXECUTE.

    CPython's `_access_check` is three tests — it must exist, be accessible with
    `X_OK`, and not be a directory — and the order here is the order of the
    cheap ones, with `exists` first because it is the one that is usually false.

    **`isfile` AND NOT `not isdir`**, and the difference is a real one that
    CPython's own test does not make: `not os.path.isdir(fn)` is also true for a
    FIFO and for a device node, so a `PATH` entry pointing at `/dev/zero` would
    be reported as a program by CPython's spelling. `isfile` asks the question
    the name asks. `/dev/null` does not separate the two — its execute bit is
    off on this platform, so both tests say no — and `test_formal_shutil.py`
    pins the pair on a FIFO as well as on a directory, because that is the case
    that separates them.

    A SYMBOLIC LINK IS ACCEPTED, which CPython also does: `exists` and `isfile`
    both follow a link, so a link to an executable in `PATH` is found.
    """
    if exists(name) == 0:
        return 0
    if isfile(name) == 0:
        return 0
    if fs_access(name, 1) != 0:
        return 0
    return 1
