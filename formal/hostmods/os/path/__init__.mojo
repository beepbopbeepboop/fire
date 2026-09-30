"""`os.path` — path manipulation, for the formal backend.

The spelling is CPython's `os.path` for every function below, with two
deviations that are properties of this target and are stated on each one:

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

  * A RESULT IS EITHER AN INTERIOR POINTER OR A `malloc`'d BUFFER. A string
    here is a bare NUL-terminated `char *` with no growable buffer of its own
    (bugs/FORMAL_string_value_model.md), so a function that returns part of its
    argument returns a pointer into it — no allocation, and the string it
    points into has to outlive the call — and a function that builds a new
    string returns memory from `malloc` that the CALLER OWNS. `os_free` in the
    `os` module releases one. The functions that copy say so; the ones that
    alias say that too, because which one you got decides whether there is
    anything to free.

  * NO PARAMETER HAS A DEFAULT. A call from another image does not materialize
    a callee's default arguments — the caller has no signature to read them
    from — so a defaulted parameter arrives as a stack address. `relpath` is
    the one function here that CPython gives a default to, and it requires its
    argument instead. (bugs/FORMAL_default_argument_not_applied_across_a_dylib.md)

  * NO ARGUMENT IS VARIADIC AND NO RESULT IS A RUN-TIME-LENGTH SEQUENCE. `*p`
    is refused on this path, so `join` is `join(a, b)`, `join3(a, b, c)` and
    `join_all(parts)`; and a list's capacity is the number of `append` SITES in
    the function that builds it, so nothing here can return a list whose length
    is only known at run time. That is what `split` returning a two-element
    tuple is for, and it is the whole reason there is no `listdir` here.

The pure-string half — `join`, `split`, `dirname`, `basename`, `splitext`,
`normpath`, `isabs`, `splitdrive`, `commonprefix` — is CPython's
`posixpath`/`genericpath` algorithm for a POSIX target, transcribed, and
`test_formal_os.py` checks it against CPython's own answers on the same inputs
rather than against a table written here.

`os.path` also carries the four predicates CPython re-exports from
`genericpath` (`exists`, `isfile`, `isdir`, `getsize`) and the `os` module
re-exports them from here, so both spellings reach one definition.
"""

from .._syscalls import str_alloc, str_trunc, str_put, str_append
from .._syscalls import str_dup, str_prefix, str_build, str_repeat
from .._syscalls import str_len, str_eq_n, str_starts, str_at
from .._syscalls import str_rfind, str_rindex_of, str_rstrip_len, str_lead
from .._syscalls import str_chr_from
from .._syscalls import fs_access
from .._syscalls import fs_opendir, fs_closedir, fs_realpath, fs_cwd, fs_getenv
from .._syscalls import fs_stat_mode
from .._syscalls import fs_stat_field16, fs_stat_field32, fs_stat_field64

# The two bytes this module asks about by value. They are NUMBERS because a
# character argument to a C library call is an `int` there and a `char *` here:
# spelling one as a string literal passes the literal's ADDRESS, the callee
# truncates it to an `int`, and the answer is about a different byte. Measured
# on both backends — `strrchr(s, "/")` returns NULL where `strrchr(s, 47)`
# returns the pointer. Where a SET of characters is what is wanted instead
# (`str_at`, `str_rindex_of`) a string is the right spelling and these two
# numbers are not used.
SLASH = 47
DOT = 46


# ── Joining ────────────────────────────────────────────────────────────────

def join(a, b):
    """`a` and `b` joined with `/`, as CPython's `os.path.join(a, b)` joins them.

    CPython's rules, in its order: an absolute `b` discards `a` entirely; an
    empty `a` contributes nothing and not even a separator; a trailing
    separator on `a` is not doubled. The result is `b` itself in the first two
    cases — an ALIAS, with nothing to free — and a fresh buffer in the third.
    """
    if str_starts(b, "/") == 1:
        return b
    if str_len(a) == 0:
        return b
    if str_at(a, str_len(a) - 1, "/") == 1:
        return str_append(str_dup(a), b)
    return str_build(a, "/", b)


def join3(a, b, c):
    """`join(join(a, b), c)`.

    Not a convenience: `*c` is refused on this path, and this is the
    three-argument spelling a caller with three components has to write. Same
    rules, applied left to right, which is the order CPython applies them.
    """
    return join(join(a, b), c)


def join_all(parts):
    """Every element of the list `parts`, joined with `/`.

    The list spelling of `join`, for a caller that has its components in a
    list. The walk is a `for` over the list rather than an index into it
    because `len(parts)` is refused: the kind of an unannotated parameter is a
    word, and `len` of a word has no count to read. A `for` is a blob walk and
    needs to know nothing.

    An empty list is `""`, as in CPython. Each step is a `join`, so the result
    is `parts[0]` itself when there is one element, and a fresh buffer
    otherwise.
    """
    out = ""
    n = 0
    for x in parts:
        if n == 0:
            out = x
        else:
            out = join(out, x)
        n = n + 1
    if n == 0:
        return ""
    return out


def split(p):
    """`(head, tail)` — CPython's `os.path.split` for a POSIX path.

    `head` is everything up to and including the last `/`, with trailing
    separators removed UNLESS the whole of it is separators (`"//a"` splits
    into `("//", "a")`, and so does CPython's); `tail` is the rest. Trailing
    separators on `p` therefore end up in neither half, which is CPython's
    behaviour and not an accident of the transcription: `"a/b/"` is
    `("a", "")`.

    Two tuples and a tuple is a frame blob, so this is the one shape a
    two-valued result can take on a path where a list's length must be known
    when it is built.
    """
    n = str_len(p)
    i = str_rindex_of(p, "/", n) + 1
    head_len = i
    if head_len > 0 and str_lead(p, "/") < head_len:
        head_len = str_rstrip_len(p, head_len)
    if head_len == 0:
        head = ""
    else:
        head = str_prefix(p, head_len)
    if i >= n:
        tail = ""
    else:
        tail = str_prefix(p + i, n - i)
    return (head, tail)


def dirname(p):
    """CPython's `os.path.dirname`: the `head` of `split(p)`.

    The empty string for `""`, `"."` when there is no separator at all, and
    `"/"` for a path under the root. An alias only when the answer is the
    input itself, which happens for `""`; every other answer is a copy.
    """
    h = split(p)
    return h[0]


def basename(p):
    """CPython's `os.path.basename`: the `tail` of `split(p)`.

    An ALIAS into `p` whenever the answer is non-empty — it is a pointer to
    the byte after the last separator — so there is nothing to free, and `p`
    has to outlive the result. An empty answer is the literal `""`.
    """
    n = str_len(p)
    i = str_rindex_of(p, "/", n) + 1
    if i >= n:
        return ""
    return p + i


def splitdrive(p):
    """`(drive, rest)` — always `("", p)` on a POSIX target.

    CPython's `posixpath.splitdrive` is exactly this: there is no drive letter
    to split off, and pretending otherwise would be a Windows answer on a
    target that has none. `p` is returned as it arrived, not copied.
    """
    return ("", p)


def splitext(p):
    """`(root, ext)` — CPython's `os.path.splitext`.

    The extension starts at the last `.` of the BASENAME, and only if that dot
    is not one of a leading run of dots: `splitext(".bashrc")` is
    `(".bashrc", "")`, not `("", ".bashrc")`, and that test is what keeps a
    dotfile from being read as a name with an extension.

    `ext` is an ALIAS into `p` when it is non-empty, and `root` is a copy.
    """
    n = str_len(p)
    base = str_rindex_of(p, "/", n) + 1
    dot = str_rfind(p + base, ".")
    if dot < 0:
        return (p, "")
    di = base + dot
    if di <= base:
        return (p, "")
    if di - base <= str_lead(p + base, "."):
        return (p, "")
    if di == 0:
        root = ""
    else:
        root = str_prefix(p, di)
    return (root, p + di)


def normpath(path):
    """CPython's `posixpath.normpath`, rule for rule.

    Duplicate separators collapse, `.` components vanish, `..` removes the
    component before it, and a trailing separator is dropped. Three rules of
    CPython's are easy to miss and are each reproduced here rather than
    approximated:

      * A `..` pops only a component that is not itself `..`. So `"../.."` is
        `"../.."` and not `"."` — a second `..` has nothing above it to remove
        and is KEPT.
      * A `..` in an ABSOLUTE path with nothing before it is DROPPED, not kept:
        `"/.."` is `"/"`, while `".."` is `".."`.
      * EXACTLY TWO leading separators are significant, and three are not:
        `"//a"` is `"//a"` and `"///a"` is `"/a"`. That is POSIX's
        implementation-defined leading-double-slash, and CPython keeps it, so
        a transcription that collapses every run of separators to one is wrong
        on two inputs out of the thirty-two in this module's test.

    The result is a fresh buffer, except for the degenerate answers: `"."`,
    `"/"` and `"//"` are literals.
    """
    n = str_len(path)
    if n == 0:
        return "."
    # How many leading separators to write back: one, or two when the path
    # starts with exactly two. The third is what makes it one again.
    lead = 0
    if str_starts(path, "/") == 1:
        lead = 1
        if n > 1 and str_at(path, 1, "/") == 1:
            if n == 2 or str_at(path, 2, "/") == 0:
                lead = 2
    out = str_alloc(n + 2)
    used = 0
    if lead == 2:
        used = str_put(out, used, "//", 2)
    elif lead == 1:
        used = str_put(out, used, "/", 1)
    parts = 0
    last_sep = 0 - 1
    last_dotdot = 0
    i = 0
    while i < n:
        while i < n and str_at(path, i, "/") == 1:
            i = i + 1
        if i >= n:
            break
        t = str_chr_from(path, i, SLASH)
        c0 = i
        # The offset of a pointer into a NUL-terminated string is
        # `len(s) - len(p)`, not `len(p)`: both end at the same NUL, so the
        # difference of the two lengths is what precedes the pointer. Reading
        # it the other way round makes every component the whole rest of the
        # string, and `test_formal_os.py` sees it on the first input.
        c1 = n if t == 0 else n - str_len(t)
        clen = c1 - c0
        if clen == 1 and str_eq_n(path + c0, ".", 1) == 1:
            i = c1
            continue
        is_dotdot = 0
        if clen == 2 and str_eq_n(path + c0, "..", 2) == 1:
            is_dotdot = 1
            if parts == 0 and lead == 0:
                pass                    # nothing to pop, and relative: keep it
            elif parts == 0:
                i = c1
                continue                # absolute with nothing to pop: drop it
            elif last_dotdot == 1:
                pass                    # a `..` above a `..` is kept, not a pop
            else:
                if last_sep < 0:
                    used = 0
                    if lead > 0:
                        used = lead
                else:
                    used = last_sep
                parts = parts - 1
                last_dotdot = 0
                if parts == 0 or lead > 0:
                    last_sep = 0 - 1
                else:
                    last_sep = str_rindex_of(out, "/", used)
                str_trunc(out, used)
                i = c1
                continue
        if parts > 0:
            last_sep = used
            used = str_put(out, used, "/", 1)
        used = str_put(out, used, path + c0, clen)
        parts = parts + 1
        last_dotdot = is_dotdot
        i = c1
    if parts == 0:
        if lead == 2:
            return "//"
        if lead == 1:
            return "/"
        return "."
    return out


def isabs(p):
    """1 if `p` is absolute — if it begins with `/` on this target."""
    return str_starts(p, "/")


def commonprefix(a, b):
    """The longest common PREFIX of `a` and `b`, character-wise.

    CPython's is character-wise rather than path-wise, so `commonprefix("a/b",
    "a/c")` is `"a/"` and not `"a"`. A fresh buffer unless the answer is the
    empty string.
    """
    la = str_len(a)
    lb = str_len(b)
    m = la if la < lb else lb
    i = 0
    while i < m and str_eq_n(a + i, b + i, 1) == 1:
        i = i + 1
    if i == 0:
        return ""
    return str_prefix(a, i)


# ── Asking the filesystem ──────────────────────────────────────────────────
#
# The format bits of `st_mode`, and the three constants they are asked about.
# NUMBERS rather than names because a module-level constant is not exported as
# a word across a dylib boundary (the note at the top of this file), so a named
# constant is not a thing a function in another image can read. `test_formal_os.py`
# checks every value below against CPython's own `os.stat` on the same path.
#
#   S_IFMT   61440   the mask that selects the format bits
#   S_IFREG  32768   a regular file          S_IFDIR  16384  a directory
#   S_IFLNK  40960   a symbolic link
#
# 0x8000 / 0x4000 / 0xA000 are the POSIX values and they are what this target's
# `struct stat` carries; `os/_syscalls.mojo` writes the layout out in full and
# says where each of these was read from.

def isfile(p):
    """1 if `p` is a regular file, following symbolic links — CPython's
    `os.path.isfile` exactly.

    `S_ISREG(st_mode)` from `stat`, so it is a value read out of the C library's
    own answer rather than a fact assembled from two other questions. That
    distinction is the whole history of this function: it used to be
    `exists(p) and not isdir(p)`, which agrees with CPython for a regular file,
    a directory, a link to either and a path that is not there, and DISAGREES
    for a device node, a FIFO and a socket — three of which are ordinary things
    to ask about. `test_formal_os.py` asserts the agreement now rather than the
    disagreement.

    A link to a regular file is a regular file here, as in CPython, because the
    link is followed: `follow` is 1. `islink` is the question that is not
    followed.
    """
    m = fs_stat_mode(p, 1)
    if m < 0:
        return 0
    if (m & 61440) == 32768:
        return 1
    return 0


def isdir(p):
    """1 if `p` is a directory, following symbolic links.

    `opendir` succeeding IS the question: the C library fails it with ENOTDIR
    for anything that is not a directory, and follows a symbolic link to one,
    which is CPython's `os.path.isdir` exactly. The descriptor is closed
    again here rather than handed back, so the answer costs no resource the
    caller has to remember to release.

    The `st_mode` route would answer this too, and does not: `opendir` needs no
    layout to be right, so this is the one predicate here that cannot be wrong
    about a target's `struct stat`.
    """
    d = fs_opendir(p)
    if d == 0:
        return 0
    fs_closedir(d)
    return 1


def islink(p):
    """1 if `p` is a symbolic link, WITHOUT following it — CPython's
    `os.path.islink` exactly.

    `S_ISLNK(lstat(p))`. The `l` is the whole function: `stat` follows the link
    and reports the mode of what it points at, so `islink` on a link to a
    regular file would be 0 with `stat` and 1 with `lstat`, and only the second
    is the question. A path that is not a link, and a path that is not there,
    are both 0.
    """
    m = fs_stat_mode(p, 0)
    if m < 0:
        return 0
    if (m & 61440) == 40960:
        return 1
    return 0


def lexists(p):
    """1 if `p` is a path the system knows about, links NOT followed.

    CPython's `os.path.lexists`, and the difference from `exists` is a dangling
    symbolic link: `exists` follows the link, finds nothing at the far end and
    says 0; `lexists` asks whether the NAME resolves and says 1. So
    `lexists` is `lstat` succeeding, and `exists` is `access(p, F_OK)`, and the
    two disagree on exactly the links whose target is not there.
    """
    m = fs_stat_mode(p, 0)
    if m < 0:
        return 0
    return 1


def samefile(a, b):
    """1 if `a` and `b` are the same file, following symbolic links.

    `st_dev` and `st_ino` agreeing, which is what CPython's
    `os.path.samefile` compares and the only definition of "the same file" a
    POSIX system has: a hard link and the path it was made from have the same
    pair, and two paths that happen to have the same name in different
    directories do not.

    A path that cannot be stat'd is 0 rather than an error, so a caller that
    wants to know which of the two is bad asks `exists` on each. There is no
    exception on this path to raise the one CPython raises.
    """
    da = fs_stat_field64(a, 1, 0)
    ia = fs_stat_field64(a, 1, 8)
    if da < 0 or ia < 0:
        return 0
    db = fs_stat_field64(b, 1, 0)
    ib = fs_stat_field64(b, 1, 8)
    if db < 0 or ib < 0:
        return 0
    if da != db:
        return 0
    if ia != ib:
        return 0
    return 1


def exists(p):
    """1 if `p` resolves to something, following symbolic links.

    `access(p, F_OK)`, which is the C library's own answer to the question and
    follows a link to what it points at, so a dangling link is 0 — which is
    what CPython's `os.path.exists` says too. (`lexists` above is the same
    question WITHOUT following links.)
    """
    if fs_access(p, 0) == 0:
        return 1
    return 0


def getsize(p):
    """The size of `p` in bytes, or -1 if it cannot be stat'd.

    `st_size` out of `stat`, which is what CPython's `os.path.getsize` reads —
    for a regular file, a directory, a device node, a FIFO, a socket and a
    symbolic link alike, and for a path that does not exist it is -1 where
    CPython raises.

    IT USED TO BE `lseek(fd, 0, SEEK_END)` on a read-only descriptor, and the
    reason it was is gone the moment `stat`'s out-parameter became readable: an
    exact answer was available and this was the largest one that was not a
    struct. Keeping the `lseek` spelling anyway would have been a HANG, not a
    deviation — `open(O_RDONLY)` on a FIFO blocks until a writer arrives, so
    `getsize` on a FIFO would never return. A hang is the one outcome a
    path library cannot have. `lseek` is still what `os/_syscalls.mojo` uses,
    there to CHECK the layout on every call rather than to answer.

    So this now depends on the offsets in `os/_syscalls.mojo` being this
    target's, and says -1 rather than a wrong number when they are not. That is
    the trade this module makes everywhere: a documented limitation beats an
    answer nothing can check.
    """
    return fs_stat_field64(p, 1, 96)


# ── The `stat(2)` fields, one function each ────────────────────────────────
#
# CPython's `os.stat_result` is a struct with ten fields, and a struct is a
# frame blob whose first word is a COUNT on this path — so there is no
# `stat_result` here and there is not going to be one without a struct value
# form. What there is instead is one function per field, each with the offset
# it reads spelled as a parameter, and each -1 for a path that cannot be stat'd
# or for a target whose `struct stat` those offsets do not describe (which
# `os/_syscalls.mojo` checks on every call against `lseek`).
#
# `follow` is 1 for `stat` and 0 for `lstat`, so every one of these has both
# spellings available: `stat_ino(p, 0)` is the inode of a symbolic link itself
# and `stat_ino(p, 1)` the inode of what it points at. `os.lstat_*` are the
# same functions reached under the other name.

def stat_mode(p, follow):
    """`st_mode` — the whole mode word, permissions and format bits both."""
    return fs_stat_mode(p, follow)


def stat_size(p, follow):
    """`st_size` — 64 bits at offset 96.

    The same number `getsize` returns for a regular file, and the `follow`
    argument is the whole difference: `stat_size(p, 0)` is the LENGTH OF A
    SYMBOLIC LINK, which is what CPython's `os.lstat(p).st_size` says, and it
    is not a file size at all.
    """
    return fs_stat_field64(p, follow, 96)


def stat_ino(p, follow):
    """`st_ino` — the inode number, which with `st_dev` identifies the file."""
    return fs_stat_field64(p, follow, 8)


def stat_dev(p, follow):
    """`st_dev` — the device the inode lives on, 32 bits at offset 0.

    Read at 32 bits and not at 64 because that is its width in the layout: the
    next four bytes are padding, and a 64-bit read of a 32-bit field is a
    number assembled out of the field and whatever the compiler put after it.
    """
    return fs_stat_field32(p, follow, 0)


def stat_nlink(p, follow):
    """`st_nlink` — how many names this inode has, 16 bits at offset 6."""
    return fs_stat_field16(p, follow, 6)


def stat_uid(p, follow):
    """`st_uid` — the owning user id, 32 bits at offset 16."""
    return fs_stat_field32(p, follow, 16)


def stat_gid(p, follow):
    """`st_gid` — the owning group id, 32 bits at offset 20."""
    return fs_stat_field32(p, follow, 20)


def stat_blocks(p, follow):
    """`st_blocks` — 512-byte blocks allocated, 64 bits at offset 104."""
    return fs_stat_field64(p, follow, 104)


def stat_blksize(p, follow):
    """`st_blksize` — the filesystem's preferred I/O size, at offset 112."""
    return fs_stat_field64(p, follow, 112)


# ── Making a path absolute ─────────────────────────────────────────────────

def abspath(p):
    """CPython's `os.path.abspath`: `p` made absolute, without resolving links.

    An absolute `p` is only normalized; a relative one is joined to the
    working directory first. A fresh buffer unless the answer is the literal
    `"/"` or `"."`.
    """
    if isabs(p) == 1:
        return normpath(p)
    return normpath(str_build(fs_cwd(), "/", p))


def realpath(p):
    """CPython's `os.path.realpath`: absolute, normalized, links resolved.

    The C library's own `realpath`, which allocates, so the answer is a fresh
    buffer the caller owns. Every symbolic link is resolved and every `..` is
    removed against the real tree, so the result exists whenever the path does.

    ONE DEVIATION, and it is a fallback rather than a different answer: when
    the C library cannot resolve the path at all — which includes a path whose
    FINAL component does not exist — this returns `abspath(p)`. CPython's
    `realpath` also returns a usable string for a path that does not exist (it
    resolves the part that can be resolved and keeps the rest), so this is
    closer to CPython than an empty string would be, and closer than pretending
    the resolution succeeded. A caller that needs to know whether the path
    exists should ask `exists`.
    """
    r = fs_realpath(p)
    if r == 0:
        return abspath(p)
    return r


def relpath(path, start):
    """`path` relative to `start` — CPython's `os.path.relpath`.

    Both are made absolute, the components they share are dropped, one `..` is
    written for each component of `start` that is left over, and the rest of
    `path` is appended. `"."` is the answer when the two are the same path, as
    in CPython. A fresh buffer unless the answer is the literal `"."`.

    `start` is REQUIRED rather than defaulting to `"."`: a default argument is
    not applied to a call from another image, so a defaulted `start` arrives as
    whatever the caller left in the argument register. Pass `"."` for CPython's
    one-argument form. (bugs/FORMAL_default_argument_not_applied_across_a_dylib.md)

    There is no `ValueError` for a relative `path` on a target that cannot
    change directory, which CPython raises on Windows; on a POSIX target the
    two arguments are made absolute against the working directory either way.
    """
    a = abspath(path)
    b = abspath(start)
    na = str_len(a)
    ia = 0
    ib = 0
    while True:
        ca = _next_component(a, ia)
        cb = _next_component(b, ib)
        if ca[1] < 0 or cb[1] < 0:
            break
        if _same_component(a, ca, b, cb) == 0:
            break
        ia = ca[1]
        ib = cb[1]
    ups = 0
    while True:
        cb = _next_component(b, ib)
        if cb[1] < 0:
            break
        ups = ups + 1
        ib = cb[1]
    # A leading `/` is not a component. CPython splits both arguments on `/`
    # and drops the empty pieces, so the leading separator of an absolute path
    # never appears in the answer; the index walk above skips separators when
    # it takes a component, so the one that is left to skip is the one before
    # the first component of `path` is appended. Without this,
    # `relpath("x", "/")` comes back as `/Users/…` where CPython says
    # `Users/…` — one separator too many, in every answer with a `..` in it.
    if ia < na and str_at(a, ia, "/") == 1:
        ia = ia + 1
    if ups == 0 and ia >= na:
        return "."
    out = str_alloc(ups * 3 + (na - ia) + 2)
    used = 0
    if ups > 0:
        if ia < na:
            used = str_put(out, used, str_repeat("../", ups), ups * 3)
        else:
            # Nothing of `path` is left to append, so the last `..` is written
            # on its own rather than as "../" with its separator cut off.
            used = str_put(out, used, str_repeat("../", ups - 1), (ups - 1) * 3)
            used = str_put(out, used, "..", 2)
    if ia < na:
        # No separator here: `str_repeat("../", ups)` already ends in one, and
        # adding a second is the "..//Users/…" that the test caught.
        used = str_put(out, used, a + ia, na - ia)
    if used == 0:
        return "."
    return out


def _next_component(s, i):
    """`(start, end)` of the next `/`-separated component of `s` at or after
    `i`, or `(-1, -1)` when there is none.

    The component walk `relpath` needs, and it is a pair of indices rather
    than a list of components because a list's length has to be known when it
    is built on this path. `end` is exclusive and is the index of the
    separator, so the next call's `i` is already positioned past it.
    """
    n = str_len(s)
    while i < n and str_at(s, i, "/") == 1:
        i = i + 1
    if i >= n:
        return (0 - 1, 0 - 1)
    t = str_chr_from(s, i, SLASH)
    if t == 0:
        return (i, n)
    return (i, n - str_len(t))


def _same_component(a, ca, b, cb):
    """1 if the components of `a` and `b` at `ca` and `cb` are the same.

    Spelled with a bounded compare rather than `str_eq`, because the two
    components are at DIFFERENT offsets in two different strings, and `==`
    between two strings on this path is a CONTENT comparison of what follows
    each pointer — which would answer a different question than the one being
    asked.
    """
    if ca[1] - ca[0] != cb[1] - cb[0]:
        return 0
    return str_eq_n(a + ca[0], b + cb[0], ca[1] - ca[0])


def expanduser(p):
    """CPython's `os.path.expanduser`: a leading `~` replaced from `$HOME`.

    `"~"` is the home directory and `"~/x"` is `x` inside it. A `~name` for
    some other user is returned UNCHANGED, because reading the password
    database is not something this target can do — and returning it unchanged
    is what CPython does when it cannot resolve the name either.

    A fresh buffer, except when `p` has no leading `~` at all: then `p` comes
    back as it arrived.
    """
    if str_starts(p, "~") == 0:
        return p
    if str_len(p) > 1 and str_starts(p + 1, "/") == 0:
        return p
    h = fs_getenv("HOME")
    if h == 0:
        return p
    if str_len(p) == 1:
        return h
    return str_build(h, "", p + 1)
