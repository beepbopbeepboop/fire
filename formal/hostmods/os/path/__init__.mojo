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

  * NO PARAMETER HAS A DEFAULT. A call from another image USED not to
    materialize a callee's default arguments — the caller had no signature to
    read them from, so a defaulted parameter arrived as a stack address — and
    that is fixed (`formal/imports.py`'s `external_declarations`). `relpath` is
    the one function here that CPython gives a default to, and it still requires
    its argument: a choice rather than a limit, and the step that gives it back
    is written down in
    `bugs/FORMAL_hostmod_defaults_left_required_after_the_cross_dylib_fix.md`
    because it wants a sweep behind it.
    (`FORMAL_default_argument_not_applied_across_a_dylib`, fixed; its doc is
    deleted, as a fixed bug's is.)

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
from .._syscalls import fs_access, fs_open_ro, fs_lseek, fs_close
from .._syscalls import fs_opendir, fs_closedir, fs_realpath, fs_cwd, fs_getenv

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

def exists(p):
    """1 if `p` resolves to something, following symbolic links.

    `access(p, F_OK)`, which is the C library's own answer to the question and
    follows a link to what it points at, so a dangling link is 0 — which is
    what CPython's `os.path.exists` says too. (`lexists`, which is the same
    question WITHOUT following links, is not here: `lstat` reports through an
    out-parameter struct, and see the note in `os/_syscalls.mojo`.)
    """
    if fs_access(p, 0) == 0:
        return 1
    return 0


def isdir(p):
    """1 if `p` is a directory, following symbolic links.

    `opendir` succeeding IS the question: the C library fails it with ENOTDIR
    for anything that is not a directory, and follows a symbolic link to one,
    which is CPython's `os.path.isdir` exactly. The descriptor is closed
    again here rather than handed back, so the answer costs no resource the
    caller has to remember to release.
    """
    d = fs_opendir(p)
    if d == 0:
        return 0
    fs_closedir(d)
    return 1


def isfile(p):
    """1 if `p` is something that exists and is not a directory.

    WHAT IT DECIDES, precisely: `exists(p) and not isdir(p)`. That is
    CPython's answer for a regular file, for a symbolic link to one, and for a
    path that does not exist (0, correctly). It is NOT the same for a FIFO, a
    socket or a device node, which CPython calls 0 and this calls 1.

    The reason is the one `os/_syscalls.mojo` records at length: the exact
    answer is `S_ISREG(st_mode)`, `stat` reports through an out-parameter
    struct, and a struct is a frame blob whose first word is a COUNT — so
    reading a mode out of it means a bounds check against a device number and
    a field offset the source never states. Rather than assemble a plausible
    number out of adjacent bytes, this says the largest fact it can actually
    establish and says that here. Use `isdir` to separate the two cases.
    """
    if isdir(p) == 1:
        return 0
    return exists(p)


def getsize(p):
    """The size of `p` in bytes, or -1 if it cannot be opened.

    `lseek(fd, 0, SEEK_END)` on a read-only descriptor, which is the size as
    a VALUE — there is no struct to read and no field offset to guess. For a
    regular file this is exactly `os.path.getsize`; for a directory it is
    whatever the C library's `lseek` reports for a directory descriptor, which
    is a number about the directory rather than a file size.
    """
    fd = fs_open_ro(p)
    if fd < 0:
        return 0 - 1
    n = fs_lseek(fd, 0, 2)
    fs_close(fd)
    return n


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

    `start` is REQUIRED rather than defaulting to `"."`. A default argument is
    applied to a call from another image now — `formal/imports.py`'s
    `external_declarations` gives the emitter the callee's declaration, so the
    omitted register is filled from the default rather than left holding
    whatever the caller last put there — so this is a choice, not a limit, and
    the step that gives the default back is in
    `bugs/FORMAL_hostmod_defaults_left_required_after_the_cross_dylib_fix.md`.
    Pass `"."` for CPython's one-argument form.

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
