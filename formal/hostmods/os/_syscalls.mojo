"""The C library this module needs, and nothing else.

Every call into libSystem that `os` and `os.path` make is spelled here, once,
and nowhere else. Three reasons, in the order they mattered while writing it.

1. A NAME COLLISION IS A SILENT RECURSION. A call is extern exactly when the
   name is not a function of the unit being compiled
   (`formal/arm64_codegen.py:_emit_call`, `name not in self._functions`), so a
   unit that both defines `getcwd` and calls the C library's `getcwd` emits a
   call to ITSELF with the wrong arity. `getcwd`, `chdir`, `chmod`, `remove`,
   `unlink`, `rename`, `getenv`, `mkdir` and `realpath` are all both libc
   functions and the names this module's API wants, so the wrappers live in
   their own unit and the API modules see a function call.

2. THE SET IS AUDITABLE. A formal image links libSystem and nothing else
   (FORMAL.md §1), so "what does this module ask of the operating system" is a
   question with a short, complete answer, and it is the answer in this file.
   Every name below was measured to bind on this target before it was relied
   on.

3. THE STRING PRIMITIVES ARE NOT STRING FEATURES. Concatenation, `strip`,
   `replace` and `split` are refused on this path because a string is a bare
   NUL-terminated `char *` in a read-only text section with no heap to grow
   into (bugs/FORMAL_string_value_model.md). That does NOT make a new string
   impossible: `malloc` is in libSystem, and a buffer it hands back IS
   writable. So a string this module returns is either an INTERIOR POINTER
   into its input (no allocation, and the caller's buffer outlives the call) or
   a `malloc`'d buffer that the caller owns for as long as it wants it. That
   is the whole of the string story, and it is why there is no `+` here: the
   concatenation is `str_build`, which is a `malloc` and three `memmove`s.

WHAT IS NOT HERE, AND WHY — each measured on this target before it was left
out rather than guessed at:

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

  * BYTE READS. `p[0]` on a `Pointer[UInt8]` is NOT a one-byte load. It takes
    the blob path in `_emit_subscript_addr`, which reads a COUNT from offset 0
    and bounds-checks against it: `byteat("ab")` returns -1879048144, which is
    `ab` plus whatever follows it in the text section, read as a little-endian
    word. A wrong answer, silently. `str_at` below therefore asks "what byte is
    at i" with `strspn`, which is a real character test and needs no load:
    `strspn(s + i, chars) == 1` holds exactly when `s[i]` is in `chars`.
    (bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md.)

  * `len()`. It is a builtin whose kind comes from the call site, and a value
    that arrived from a call is classified as a word, so `len(p)` on a
    `char *` this module received is refused. `str_len` is `strlen`, which is
    the same computation with no kind to guess.

  * `ord`/`chr`/`str`. There is no builtin by those names here; a call to one
    is an unbound extern, and `str(65)` segfaults.

  * `errno`. The C library's accessor is `__error`, and a leading underscore in
    a callee name is not a symbol this path can bind — the image fails to load
    for a name nothing provides. Callers that need to distinguish "already
    there" from "could not be made" ask `isdir` instead, which is a fact rather
    than an error code.

  * `stat`, and therefore `st_mode`/`st_dev`/`st_ino`/`st_size`. `stat` takes
    its answer in an out-parameter struct, and a struct is a frame blob whose
    word 0 is a COUNT: subscripting it is a bounds check against a device
    number, and the layout, the padding and the field offsets are all
    unstated by the source. Anything that read it that way would be assembling
    a plausible number out of adjacent bytes. `getsize` uses `lseek` instead,
    which returns the size as a value; `isfile` says what it actually decides.
"""

# ── Memory: a buffer, and the only two ways a string is built here ──────────
#
# `malloc` is the heap this path does not otherwise have. A buffer it returns
# is ordinary writable memory, and `memmove`/`memset`/`strcat` write into it
# normally — that is the whole reason a new string can exist on a target whose
# string representation has no growable buffer of its own.

def str_alloc(n):
    """A writable, ZEROED buffer of at least `n` bytes plus a terminator.

    `n + 1` rather than `n`: every buffer here holds a NUL-terminated string,
    and a caller that asks for a copy of `n` bytes still needs somewhere to
    put the terminator. The result is a `Pointer[UInt8]` on purpose — that
    annotation is what tells the rest of the path this word is a string and
    not a number, and it is what `printf("%s", …)` reads.

    Zeroed, not just allocated. `malloc` returns whatever was there, and three
    of the four ways a string is built here start with a `memmove` or a
    `strcat` — a `strcat` onto an uninitialised buffer appends after the
    garbage, and the result is a string with someone else's bytes in the
    middle of it. Paying one `memset` to make every buffer's initial content
    defined is cheaper than finding that once per buffer.
    """
    var p: Pointer[UInt8] = malloc(n + 1)
    memset(p, 0, n + 1)
    return p


def str_copy(dst, src, n):
    """`n` bytes of `src` into `dst`, then a NUL. Returns `dst`.

    `memmove`, not `memcpy`: the two ranges may overlap, and a caller copying
    a prefix out of a string that starts at the same buffer is not a mistake
    worth a wrong answer.
    """
    memmove(dst, src, n)
    memset(dst + n, 0, 1)
    return dst


def str_trunc(dst, used):
    """Cut the NUL-terminated string in `dst` back to `used` bytes.

    The only way a string gets SHORTER on this path. There is no `rstrip` and
    no slice: a string is a bare `char *` into a read-only text section, so
    there is nowhere to write a terminator earlier except into a buffer this
    module allocated — which is why every function that trims copies first and
    why the result is a fresh string rather than the receiver.
    """
    memset(dst + used, 0, 1)
    return dst


def str_put(dst, used, src, n):
    """Append `n` bytes of `src` at `dst + used`, NUL-terminating. New `used`.

    The append form of `str_copy`, and it re-terminates because a scan over a
    partly built string has to stop at the end of what is written, not at
    whatever the buffer contained before.
    """
    memmove(dst + used, src, n)
    memset(dst + used + n, 0, 1)
    return used + n


def str_append(dst, src):
    """`src` onto the end of the NUL-terminated string in `dst`. Returns `dst`.

    `strcat` for the same reason `str_copy` is `memmove`: the C library's
    algorithm is the answer, and a second implementation of it is a second
    thing to be wrong.
    """
    strcat(dst, src)
    return dst


def str_dup(s):
    """A `malloc`'d copy of `s`. The caller owns it.

    This is the only allocation in the module that a caller has to think about.
    Everything else that returns a string either returns its argument or an
    interior pointer into it, and the notes on each say which.
    """
    return str_copy(str_alloc(str_len(s)), s, str_len(s))


def str_prefix(s, n):
    """The first `n` bytes of `s`, in a fresh buffer the caller owns.

    What a string SLICE would be. `s[0:n]` is refused on this path — the count
    would be read from offset 0 of a `char *`, which is the first eight
    CHARACTERS (bugs/FORMAL_string_value_model.md) — so every substring here is
    built with `memmove` and a terminator instead. `n` may exceed the length of
    `s`, which copies the whole string; every caller bounds it first.
    """
    return str_copy(str_alloc(n), s, n)


def str_build(a, sep, b):
    """`a + sep + b`, in a fresh buffer. The caller owns it.

    String `+` is refused on this path, so this is the spelling of
    concatenation everywhere above this line. Three fixed-arity calls, no
    format string, and nothing variadic — a variadic libc call cannot be
    forwarded through a wrapper with a fixed signature, which is one more
    reason the buffering lives beside the libc calls rather than one layer up.
    """
    d = str_alloc(str_len(a) + str_len(sep) + str_len(b))
    used = str_put(d, 0, a, str_len(a))
    used = str_put(d, used, sep, str_len(sep))
    used = str_put(d, used, b, str_len(b))
    return d


def str_repeat(s, k):
    """`s` written `k` times, in a fresh buffer. The caller owns it.

    `k <= 0` gives the empty string. Used for the `../` of a `relpath` and for
    nothing else, so it is not a general repeat.
    """
    d = str_alloc(str_len(s) * k)
    used = 0
    i = 0
    while i < k:
        used = str_put(d, used, s, str_len(s))
        i = i + 1
    return d


# ── Reading a string ───────────────────────────────────────────────────────
#
# Every one of these is a C library call that walks to the NUL, which is
# exactly the algorithm Python uses. A hand-written scan would be a second
# implementation of a routine that already exists, and the project has already
# paid for one of those (the `lstrip` loop that two backends got differently).

def str_len(s):
    """`strlen(s)`."""
    return strlen(s)


def str_eq_n(a, b, n):
    """1 if the first `n` bytes agree, else 0."""
    if memcmp(a, b, n) == 0:
        return 1
    return 0


def str_starts(s, p):
    """1 if `s` begins with `p`. An empty `p` is 1, as in Python."""
    if strncmp(s, p, str_len(p)) == 0:
        return 1
    return 0



def str_at(s, i, chars):
    """1 if `s[i]` is one of the bytes of `chars`.

    A character test with no byte load, which is the only way to ask this
    question on this target (see the module docstring). `i` is assumed to be
    in range; every caller above has already bounded it.

    The test is `strspn(...) > 0` and NOT `== 1`. `strspn` returns the LENGTH
    of the run of set bytes from the pointer, so `== 1` asks whether that run
    is exactly one byte — which is false for the second of two adjacent
    separators, and answers "not a separator" for a character that is one. That
    is not a subtle difference: `str_at("//", 1, "/")` is 1 and the `== 1`
    spelling says 0, so a path of nothing but separators walks its components
    forever.
    """
    if strspn(s + i, chars) > 0:
        return 1
    return 0



def str_rfind(s, p):
    """Index of the LAST occurrence of `p` in `s`, or -1.

    A scan, not a library call, and the reason is measured: this target's C
    library does not provide `strrstr` (the link audit asks the library with
    `dlsym` and it is not there), so the obvious spelling of "last occurrence"
    emits a call to a symbol nothing defines. A bounded compare at each
    offset needs only `memcmp`, which does bind, and the answer is the
    question rather than an approximation of it. An empty needle is the length
    of the haystack, which is what the loop gives and what Python returns.
    """
    n = str_len(s)
    lp = str_len(p)
    last = 0 - 1
    i = 0
    while i + lp <= n:
        if str_eq_n(s + i, p, lp) == 1:
            last = i
        i = i + 1
    return last


def str_rindex_of(s, chars, m):
    """Index of the last byte of `s[0:m]` that is in `chars`, or -1.

    The bounded "last separator" question, and it is the one every path
    function above asks. The C library's `strrchr` has no bound, and the
    bounded question is what `dirname` asks of `"a/b/"` — where the answer
    must not be the trailing slash itself. Asking it through `strchr` would
    mean a length-limited copy of the string first, which is an allocation per
    call; asking it by index is a scan over at most `m` bytes, and a path is
    short.

    `chars` is a SET and is matched byte-wise, so this is `str_rchr` with a
    bound and with "/" written as a string rather than as the number 47 — see
    `str_at` for why the set is the right shape for the question.
    """
    i = m - 1
    while i >= 0:
        if str_at(s, i, chars) == 1:
            return i
        i = i - 1
    return 0 - 1


def str_lead(s, chars):
    """How many bytes of `s`, from the start, are in `chars`. `strspn`."""
    return strspn(s, chars)


def str_rstrip_len(s, m):
    """The length of `s[0:m]` with trailing `/` removed.

    Does not copy and does not allocate: it answers the LENGTH, and the caller
    copies once with it. A shorter result than the caller expects is its own
    business — this only removes separators.
    """
    while m > 0 and str_at(s, m - 1, "/") == 1:
        m = m - 1
    return m


def str_chr_from(s, i, c):
    """Pointer to the first `c` at or after `s[i]`, or 0."""
    return strchr(s + i, c)



def fs_cwd():
    """The current working directory, in a fresh buffer the caller owns.

    A `malloc`'d copy rather than the descriptor's own buffer, so the caller
    can hold it past the next `chdir`. `PATH_MAX` is the buffer, because that
    is the length the C library refuses to exceed; a longer path cannot be
    reported by `getcwd` at all, and the empty string is what comes back
    rather than an error nobody on this path can catch.
    """
    var b: Pointer[UInt8] = str_alloc(4096)
    if getcwd(b, 4096) == 0:
        memset(b, 0, 1)
    return b


# ── The filesystem and the process ─────────────────────────────────────────
#
# Each of these was built and RUN on this target before it was written down
# here, and each returns what the C library returns: 0 or -1 for a call that
# reports failure, 0 for a POINTER that is not there. A negative status is
# not Python's exception, and there is no exception on this path (FORMAL.md
# phase 7); `os.remove` below says what it does instead.

def fs_access(p, mode):
    """`access(p, mode)`. `mode` 0 is F_OK: does the path resolve at all."""
    return access(p, mode)


def fs_chdir(p):
    """`chdir(p)`: 0 on success, -1 on failure."""
    return chdir(p)


def fs_chmod(p, mode):
    """`chmod(p, mode)`: 0 on success, -1 on failure."""
    return chmod(p, mode)


def fs_close(fd):
    """`close(fd)`."""
    return close(fd)


def fs_closedir(d):
    """`closedir(d)` on a descriptor from `fs_opendir`."""
    return closedir(d)


def fs_getcwd(buf, n):
    """`getcwd(buf, n)`: `buf`, or 0 if the path does not fit in `n`."""
    return getcwd(buf, n)


def fs_getenv(name):
    """`getenv(name)`: the value, or 0 when the variable is not set."""
    return getenv(name)


def fs_setenv(name, value, overwrite):
    """`setenv(name, value, overwrite)`: 0 on success, -1 on failure."""
    return setenv(name, value, overwrite)


def fs_unsetenv(name):
    """`unsetenv(name)`: 0 on success, -1 on failure."""
    return unsetenv(name)


def fs_lseek(fd, off, whence):
    """`lseek(fd, off, whence)`."""
    return lseek(fd, off, whence)


def fs_mkdir(p, mode):
    """`mkdir(p, mode)`: 0 on success, -1 with EEXIST if it is already there."""
    return mkdir(p, mode)


def fs_open_ro(p):
    """`open(p, O_RDONLY)`: a descriptor, or -1.

    Spelled `open(p, "r")` and not `open(p, O_RDONLY)`: this path lowers
    `open` itself, building the flags word from the mode string, and refuses
    any other spelling — including the C library's own three-argument `open`,
    which is the one call here that has no bare-name spelling. What comes back
    is the same descriptor number, and `lseek` and `close` take it.
    """
    return open(p, "r")


def fs_opendir(p):
    """`opendir(p)`: a descriptor, or 0.

    This is what answers `isdir`, and it answers it exactly: `opendir` fails
    with ENOTDIR for anything that is not a directory, and follows a symbolic
    link to one, which is what `os.path.isdir` does.
    """
    return opendir(p)


def fs_realpath(p):
    """`realpath(p, NULL)`: a `malloc`'d absolute path, or 0.

    The C library allocates, so the caller owns the result and it is already
    absolute, normalized and free of symbolic links and `..`.
    """
    return realpath(p, 0)


def fs_rename(a, b):
    """`rename(a, b)`: atomic, and it replaces `b` if `b` is there."""
    return rename(a, b)


def fs_rmdir(p):
    """`rmdir(p)`: 0 on success, -1 on failure."""
    return rmdir(p)


def fs_unlink(p):
    """`unlink(p)`: 0 on success, -1 on failure."""
    return unlink(p)


def fs_free(p):
    """`free(p)`, for a buffer this module allocated that the caller is done
    with. Nothing above calls it: the strings `os` and `os.path` return are
    the caller's to keep, and releasing one while a derived string still points
    into it is the caller's decision, not this module's."""
    return free(p)
