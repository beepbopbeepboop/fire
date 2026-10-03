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

  * BOTH BACKENDS, and the BINDING is the whole story. This used to say that a
    module dylib which makes a call into the C library is arm64-only on this
    backend, citing a bug doc that does not exist, and six sibling modules
    repeated it. It is false, and the cost of it was not a stale sentence: the
    case that would have caught a real defect was skipped on x86-64 for exactly
    this reason. Measured on this tree — a program importing `os`, building
    with `--backend=x86_64` and running under `arch -x86_64`, with every answer
    compared against CPython's — is what `test_formal_os_backing.py` does for
    all 51 of its cases, `os` and `os.path` and `os.listdir` included. What the
    x86-64 backend does need is to bind the right SYMBOL: macOS's C library
    exports several of the entry points below TWICE, once with a 32-bit `ino_t`
    and once with a 64-bit one, and on x86-64 the bare name is the 32-bit
    `readdir(3)`/`stat(2)`, whose `struct dirent`/`struct stat` is a different
    layout. That table is `model.target_libc_symbol`'s, and what it cost before
    it was there is
    `bugs/FORMAL_x86_64_byte_read_of_a_libc_returned_pointer_reads_the_wrong_bytes.md`.
    (A host with no x86-64 support at all still skips the x86-64 half of the
    suites, with the reason printed.)

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

  * **`environ` IS A VIEW, AND IT IS A FUNCTION.** A process environment is a
    `char **` in the C library's data, and the first version of this module
    said that enumerating it "needs a buffer walk this path cannot do" and left
    the whole of `os.environ` as `getenv`/`putenv`/`unsetenv`. That was wrong on
    both counts and it is worth recording how, because the second one is the
    reason this file has a `dlsym` in it. The buffer walk is a loop over an
    array of pointers, which is what `listdir` above does over `readdir`, and
    the array itself is reachable: `os/_syscalls.mojo`'s `fs_environ_vec` asks
    the dynamic loader for `environ` at RUN time, which is a different question
    from the one that was assumed — binding a DATA symbol needs support this
    path does not have, and asking the loader for one needs nothing it does not
    already have. So `environ()` is a snapshot blob in `malloc`'d memory with
    `count`/`key`/`value`/`find`/`get`/`has`/`set`/`del`/`keys`/`items`/`free`
    over it, and `getenv`/`putenv`/`unsetenv` stay because they are CPython's
    own functions and they answer the C library's environment rather than the
    view's — a difference CPython draws in the same place, and one
    `test_formal_os_backing.py`'s `environ_view` case measures both halves of.

  * **`os.environ` IS SPELLED `os.environ()`,** for the reason the constants
    above are functions: a module-level name is not published across a dylib
    boundary as a value, and a dict-like view is not publishable as one however
    it is represented. Every CPython operation on it has its own function, and
    the table that maps them is at the head of the section below. Two of them
    have no CPython spelling on this path and say so: `os.environ[k]` raises
    `KeyError` and there is no unwinder to raise into, so `[]` is `get` and
    answers 0.

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
from ._syscalls import fs_mkdir, fs_free, str_build, str_dup
from ._syscalls import fs_readdir, fs_rewinddir, fs_closedir
from ._syscalls import fs_dirent_name, fs_name_is_dot, fs_opendir
from ._syscalls import fs_environ_vec, str_find, str_cmp
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

    A LITERAL, `"\\n"`, and it is worth saying why that is not the obvious
    spelling here: this function used to allocate a buffer and `memset` the
    byte 10 into it, because a string literal on this path was interned
    VERBATIM and its escapes were not decoded — so `"\\n"` really was the two
    characters `\\` and `n`. That stopped being true at `9023031b`, which gave
    the formal backends `fire_compiler.decode_c_escapes`, the decoder every
    other engine already called, and `formal/hostmods/*.mojo` are compiled into
    dylibs, so the question is whether a literal is decoded INSIDE A MODULE and
    not only inside a program. Measured, on both architectures, and pinned by
    `test_formal_sys.py::test_a_literal_inside_a_module_is_decoded_too`:
    `sys.write_stderr("a\\nb")` called from inside a module writes three bytes
    and returns 3.

    This is the function three other modules cited as the measurement of the old
    rule (`ast.mojo`'s character sets, `re.mojo`'s `nl`), so it is the one place
    that must not keep asserting a limitation that is gone. Their corpora keep
    the `str_alloc` + `memset` idiom for now — it is correct, and
    `bugs/FORMAL_sys_mojos_escape_note_is_stale.md` §"what remains" says what
    simplifying them would take.
    """
    return "\n"


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
#
# `getenv`/`putenv`/`unsetenv` are the three POSIX calls, and they are ONE KEY at
# a time.  Everything under them is `os.environ`, CPython's dict-like view over
# the process environment, and the whole of it is below.

def getenv(name) -> str:
    """The value of the environment variable `name`, or `""` when it is unset.

    CPython's `os.getenv(name)`. For `os.getenv(name, default)` use
    `getenv_or`, which is a separate function rather than a default argument
    because a default argument is not applied to a call from another image (see
    the note at the top of this module).

    A variable that is set to the empty string returns the empty string, which
    is not the same as being unset — as in CPython, and it is why the two
    cannot be told apart through this function.  `environ_get` below DOES tell
    them apart, because it answers about a dict rather than about the C
    library's `getenv(3)`.
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

    **THIS DOES NOT TOUCH A VIEW**, and that is CPython's own rule rather than
    a limitation here: `os.putenv(k, v)` changes what `os.getenv(k)` returns and
    leaves `os.environ` holding what it held.  Both halves of that disagreement
    are measured on every run of `test_formal_os_backing.py`'s `environ_view`
    case — `late-getenv` is the moved answer and `late-view-has` is the one that
    did not — against CPython's own.  A caller that wants both answers to move
    assigns into the view: `environ_set` below, which is `os.environ[k] = v`
    and does call `putenv`.
    """
    return fs_setenv(name, value, 1)


def unsetenv(name) -> int:
    """Remove the environment variable `name`. 0 on success, -1 if it was
    not set."""
    return fs_unsetenv(name)


# ── `os.environ`: a dict-like view over the process environment ────────────
#
# THE SPELLING, and it is not `os.environ`.  A module-level name is not
# published across a dylib boundary as a value (the note at the top of this
# file), so `os.environ` is `os.environ()` — the same bargain as `os.sep` being
# `sep()`, and for the same reason.  What it returns is a BLOB in `malloc`'d
# memory, so it outlives the call that made it, which is the whole of what
# `listdir` above needs a heap for.
#
#     word 0        n, the number of pairs, as an Int64
#     word 1 + 2i   key `i`,   a `malloc`'d NUL-terminated buffer
#     word 2 + 2i   value `i`, a `malloc`'d NUL-terminated buffer
#
# so a view is `1 + 2n` words and every buffer in it is the view's own.  The
# `[count][element]…` shape is `listdir`'s, deliberately: a second convention in
# one module is a second thing to be wrong, and `test_formal_os.py`'s `blob`
# group exists to say so out loud.
#
# CPython's SPELLING, and what each operation is called here.  A caller who
# knows one column can read the other; the pairs are the view and the accessors
# are the only way to ask them a question.
#
#     len(os.environ)          environ_count(e)
#     k in os.environ          environ_has(e, k)
#     os.environ.get(k)        environ_get(e, k)          0 when unset
#     os.environ.get(k, d)     environ_get_or(e, k, d)
#     os.environ.keys()        environ_keys(e, i) for i < environ_count(e)
#     os.environ.items()       environ_items(e)           the view itself
#     os.environ[k] = v        e2 = environ_set(e, k, v)  see that function
#     del os.environ[k]        environ_del(e, k)          0, or -1 when unset
#     os.environ.pop(k, None)  environ_get(e, k) then environ_del(e, k)
#     os.environ.setdefault(k, v)
#                              environ_get_or(e, k, v) then environ_set if 0
#     os.getenv(k[, d])        getenv(k) / getenv_or(k, d)  — the C library's
#                              answer, NOT the view's, which is the difference
#                              CPython draws in the same place
#
# `[]` IS `get` HERE, and that is a RECORDED DIVERGENCE rather than an
# omission: `os.environ[k]` raises `KeyError` on a name that is not there and
# `os.environ.get(k)` answers `None`, and this path has no unwinder to raise
# into (the note at the top of this file), so both are the 0 that means "no such
# key".  A caller that needs CPython's exception has to test the answer, which
# is what every other failure in this module asks for.

def environ() -> Pointer[Int64]:
    """The process environment as a dict-like view. The caller OWNS it.

    A SNAPSHOT, and CPython's `os.environ` is one too: it is built from the
    environment the process started with, and the difference it makes is the
    one `putenv`'s own docstring above is about.  What is different is WHEN the
    snapshot is taken, and the answer is that the two agree for every program
    that does not write to the environment before it reads it — the only way to
    do that here is `putenv`, which changes no view.  So `environ()` gives
    CPython's answer for every program whose first environment question is also
    its first environment write, and `test_formal_os_backing.py`'s
    `environ_view` case asks CPython for its side of the comparison rather
    than naming an expected string.

    `0` when the host will not name the environment at all, which
    `os/_syscalls.mojo`'s `fs_environ_vec` says how it finds it and why it can
    come back empty.  Every function below answers about a 0 the way
    `listdir_len`/`listdir_get` answer about a 0, so a caller that checks once
    can forget.

    A FRESH blob on every call, and `1 + 2n` allocations every time: call it
    once and keep it.  There is no module-level snapshot to hand out instead,
    because a module-level name is not published as a value (the note at the top
    of this file) and a value that outlives the function that made it has to be
    in the heap, which this is.

    TWO PASSES, the same bargain `listdir` and `walk` make and for the same
    reason: one to count the variables so the blob is exactly the right size,
    one to copy them.  The count is the one thing the C library will not give
    us, and a blob with room to spare has a length that is a property of the
    program rather than of the environment.
    """
    envp = fs_environ_vec()
    if envp == 0:
        return 0
    n = _environ_count(envp)
    var b: Pointer[Int64] = malloc(8 * (1 + 2 * n))
    memset(b, 0, 8 * (1 + 2 * n))
    _environ_fill(envp, b, n)
    return b


def _environ_count(envp: Pointer[Pointer[UInt8]]) -> int:
    """How many entries the NUL-terminated array `envp` holds.

    The array is `char **` with a 0 word at the end, which is what the kernel
    gives a process and what every walk of it stops at.  Nothing here reads the
    CONTENTS: a variable with an empty value is still a variable, and one entry
    per element of the array is the count `environ_count` reports.
    """
    n = 0
    i = 0
    while envp[i] != 0:
        n = n + 1
        i = i + 1
    return n


def _environ_fill(envp: Pointer[Pointer[UInt8]], b: Pointer[Int64], n) -> int:
    """Copy `envp`'s `n` entries into the blob `b` as key/value pairs.

    ONE `=` SPLITS AN ENTRY, and the first one: a key cannot contain `=` in a
    well-formed environment and a value can, so splitting at the first is what
    makes `A=b=c` the key `A` and the value `b=c` — which is what `execve` says
    and what CPython reports.  An entry with no `=` at all is a key with an
    EMPTY value, which is the reading that keeps the pair count the same as the
    entry count; nothing produces one, and pretending otherwise by dropping it
    would make `environ_count` disagree with the environment it claims to be.
    """
    i = 0
    while i < n and envp[i] != 0:
        s = envp[i]
        at = str_find(s, "=", 0)
        if at < 0:
            b[1 + 2 * i] = str_dup(s)
            b[2 + 2 * i] = str_alloc(0)
        else:
            b[1 + 2 * i] = str_prefix(s, at)
            b[2 + 2 * i] = str_copy(str_alloc(str_len(s) - at - 1),
                                    s + at + 1, str_len(s) - at - 1)
        i = i + 1
    b[0] = n
    return n


def environ_count(e: Pointer[Int64]) -> int:
    """How many pairs a view holds, or -1 for something that is not one.

    Word 0, which is where every container on this path keeps its count, so
    this is `len(os.environ)` for a value that has a count to read.  -1 for a
    0 — what `environ()` returns when the host will not name the environment —
    and it is the only way to tell an empty environment from no environment
    through a single word.
    """
    if e == 0:
        return 0 - 1
    return e[0]


def environ_key(e: Pointer[Int64], i) -> str:
    """The KEY of pair `i`, or `""` when `i` is out of range.

    An ALIAS, not a copy: the key is one of the buffers the view owns, so it
    lives as long as the view does and must NOT be passed to `os_free` on its
    own — `environ_free` releases it.  `environ_value`'s note is the same, and
    a negative `i` is out of range here rather than a count from the end: this
    is a blob of pairs, not a Python list, and the two index conventions are one
    more thing a caller would have to know.
    """
    if e == 0:
        return ""
    if i < 0:
        return ""
    if i >= e[0]:
        return ""
    return e[1 + 2 * i]


def environ_value(e: Pointer[Int64], i) -> str:
    """The VALUE of pair `i`, or `""` when `i` is out of range.

    An ALIAS, not a copy, for the reason `environ_key` gives.  `""` for an
    out-of-range index and `""` for a variable set to the empty string are the
    same word, and `environ_has` is how a caller tells them apart — which is
    exactly the distinction CPython draws between a missing key and a present
    one holding nothing.
    """
    if e == 0:
        return ""
    if i < 0:
        return ""
    if i >= e[0]:
        return ""
    return e[2 + 2 * i]


def environ_find(e: Pointer[Int64], k) -> int:
    """The index of the pair whose key is `k`, or -1.

    The ONE scan every other function here is written in terms of, published so
    a caller can walk pairs with it instead of asking the same question twice.
    The comparison is `strcmp`, which is the same byte order Python compares
    `str` in (see `os/_syscalls.mojo`'s `str_cmp`), so the answer for a key is
    the key's and not a hash of it.

    The FIRST match wins, and a view cannot have two pairs with the same key:
    `environ_set` replaces rather than appends, which is what a dict does.
    """
    if e == 0:
        return 0 - 1
    i = 0
    while i < e[0]:
        if str_cmp(e[1 + 2 * i], k) == 0:
            return i
        i = i + 1
    return 0 - 1


def environ_get(e: Pointer[Int64], k) -> str:
    """The value `os.environ[k]` would give, or 0 when the key is not there.

    AN ALIAS into the view, and a 0 rather than a `KeyError`: see the note at
    the head of this section.  The 0 is distinguishable from the empty string,
    which is the one thing `getenv` above cannot do — a variable set to nothing
    and a variable that is not set are both `""` through `getenv(3)` and are
    `""` and 0 through here.
    """
    i = environ_find(e, k)
    if i < 0:
        return 0
    return environ_value(e, i)


def environ_get_or(e: Pointer[Int64], k, default) -> str:
    """`environ_get(e, k)`, with `default` as the answer when it is unset.

    A separate function rather than a default argument, for the reason
    `getenv_or` above gives: a default that is not applied across a dylib
    boundary is a wrong value and not an error.
    """
    v = environ_get(e, k)
    if v == 0:
        return default
    return v


def environ_has(e: Pointer[Int64], k) -> int:
    """1 when `k` is a key of the view, else 0. `k in os.environ`.

    Asked of the VIEW rather than answered by `getenv(3)`, which is the whole
    difference between this and `environ_get(e, k) != 0`: a `putenv` between
    the snapshot and the question moves one of them and not the other, and
    which one moves is CPython's rule (see `putenv`'s own docstring above).
    """
    if environ_find(e, k) < 0:
        return 0
    return 1


def environ_set(e: Pointer[Int64], k, v) -> Pointer[Int64]:
    """`os.environ[k] = v`. The blob the CALLER MUST KEEP, or 0 on failure.

    **THE RETURN IS A BLOB AND NOT A STATUS, and that is the whole contract.**
    Adding a key makes the view one pair longer, and a view that has to hold
    one more pair is a bigger allocation, and growing an allocation with
    `realloc` MAY MOVE IT — so a caller that ignored this answer would go on
    reading a freed buffer, and the read would be a heap address where a string
    is expected.  So a caller writes

        e = os.environ_set(e, k, v)

    and the answer is `e` itself when the key was already there (the value's
    buffer is replaced in place and the view does not move) and a NEW blob when
    it was not.  0 means the view could not be grown, which on this target means
    `realloc` failed.

    CPython's `__setitem__` in full, in this order: `putenv` first, so a C
    library callee sees the new value, then the pair.  A key that is not there
    is APPENDED, at the end, so a caller that cares about order gets
    environment order for the variables it did not write and insertion order for
    the ones it did — which is what CPython's dict does too.
    """
    if e == 0:
        return 0
    i = environ_find(e, k)
    if i >= 0:
        free(e[2 + 2 * i])
        e[2 + 2 * i] = str_dup(v)
        fs_setenv(k, v, 1)
        return e
    n = e[0]
    var b: Pointer[Int64] = realloc(e, 8 * (1 + 2 * (n + 1)))
    if b == 0:
        return 0
    b[1 + 2 * n] = str_dup(k)
    b[2 + 2 * n] = str_dup(v)
    b[0] = n + 1
    fs_setenv(k, v, 1)
    return b


def environ_del(e: Pointer[Int64], k) -> int:
    """`del os.environ[k]`. 0, or -1 when the key is not there.

    CPython raises `KeyError` for the missing key and there is no unwinder to
    raise into, so -1 is the answer and it is a fact about the view rather than
    a guess: it is what `environ_find` returned.

    The pair is RELEASED and the LAST pair is moved into the hole, so the
    numbering stays dense and `environ_key`/`environ_value` never have to know
    that a pair was removed.  That reorders nothing a caller can rely on and
    never reallocs, which is why `environ_set` needs to and this does not: a
    view may hold one pair more than its count says it does, and the count is
    what says which words are live.  The vacated words keep stale pointers and
    are not freed twice, because `environ_free` releases exactly the first `n`
    pairs.

    `unsetenv` is called first, as CPython's `__delitem__` calls it, so a C
    library callee sees the variable go.
    """
    if e == 0:
        return 0 - 1
    i = environ_find(e, k)
    if i < 0:
        return 0 - 1
    n = e[0] - 1
    free(e[1 + 2 * i])
    free(e[2 + 2 * i])
    if i != n:
        e[1 + 2 * i] = e[1 + 2 * n]
        e[2 + 2 * i] = e[2 + 2 * n]
    e[0] = n
    fs_unsetenv(k)
    return 0


def environ_items(e: Pointer[Int64]) -> Pointer[Int64]:
    """`os.environ.items()` — which IS the view, so this returns `e` itself.

    The pairs of a view are `(environ_key(e, i), environ_value(e, i))` for
    `i < environ_count(e)`, so the items view and the view are the same words in
    the same order, and `environ_keys` below is the same two accessors again.
    A second blob for either one would be a second representation of one fact,
    and `environ_del` above reorders pairs in place — two layouts would then
    have to be kept in step with each other for no gain.
    """
    return e


def environ_keys(e: Pointer[Int64], i) -> str:
    """The `i`th key of `os.environ.keys()`, i.e. `environ_key(e, i)`.

    **THERE IS NO KEYS BLOB, and this is why.** `keys()` is the keys of the view
    in the view's order, which is `environ_key(e, i)` for `i < environ_count(e)`
    — the whole of it, with no copy and no second shape.  A `[count][key]…`
    blob was written first and is wrong in a way worth recording: `environ_free`
    releases a view's pairs at words `1 + 2i` and `2 + 2i`, so handing it a
    `[count][key]…` blob frees words `1, 3, 5, …` as if they were keys, reads
    past the end for every other one, and lands in the allocator with a double
    free — measured, SIGABRT after a whole correct run of every other operation
    in the program, which is the worst possible moment for it.  Two shapes need
    two release functions, and a caller holding one blob and not knowing which
    of the two it is holding is exactly the knowledge a shape is supposed to
    remove.
    """
    return environ_key(e, i)


def environ_free(e: Pointer[Int64]) -> int:
    """Release a view and every buffer in it. 0.

    A view is `1 + 2n` allocations — every key, every value, and the blob — and
    this is all of them, in the count's own order so a blob that `environ_del`
    has left stale words past its count cannot free one of them twice.  There is
    exactly ONE shape of blob this module hands out (`environ`, and `items()`
    which is the same words), and that is what lets this be one function.

    0 for a 0, so the same call releases "nothing" and a caller that never had
    a view does not have to test first — the bargain `listdir_free` makes.

    **A KEY OR A VALUE IS NOT A BLOB AND MUST NOT COME HERE.** Both are
    aliases into a view (`environ_key`, `environ_value`, `environ_get`), so
    freeing one would leave the view holding a pointer the C library has
    already reclaimed.  The strings `os_free` releases are a different set:
    those are the ones the path functions allocated on their own.
    """
    if e == 0:
        return 0
    n = e[0]
    i = 0
    while i < n:
        free(e[1 + 2 * i])
        free(e[2 + 2 * i])
        i = i + 1
    free(e)
    return 0


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
# The result is a word, and both ways of saying what that word holds are here:
# the DECLARED type, which is what a caller on the other side of a dylib
# boundary reads (`model.imported_callee_kind`), and the three accessors, which
# ask the blob directly.  They are not two answers to one question — the
# declared type says what KIND of thing came back, and the accessors are how a
# caller releases it and how a use site that must decide an element kind reads
# it.  `listdir_free` has no spelling in the declaration, which is why it
# exists.
#
# `-> List[String]`, and the annotation is not decoration — it is what puts the
# CONTAINER KIND in this module's manifest, and a container kind is the one
# thing a caller cannot derive: a list is one word, so the C signature is
# `int64_t` whether it is declared a list or an integer and says nothing.
# Measured, both architectures: with `-> int` an unannotated
# `var names = listdir(dir)` is an INTEGER, so `names[0]` read the local's own
# storage and answered 704698368 — a heap address — where `listdir_len` says 2.
# So the trap was not "a pointer needs an annotation" but "this declaration
# claimed the value was not one", and the two are fixed by different things:
# the declaration is now true, and an unannotated binding of a cross-image
# POINTER that has NO container kind is still REFUSED by name rather than
# silently computing `[word + 8i]` — `formal/build.py`'s
# `check_subscript_through_an_unclassified_import`, whose measured cases are
# `re.escape`'s `-> Pointer[UInt8]` and not this one.
#
# A STORE through the result is refused by name as well, and that refusal is a
# different question from the unclassified one: this blob's words are
# `malloc`'d names that THIS module walks and frees, so `names[i] = v` is a
# store into memory the caller does not own.  It is keyed on the export, not on
# the value — `formal/imports.py`'s `HOST_OWNED_BLOBS` and build.py's
# `check_imported_blob_stores` — so declaring the return type a list does not
# make it writable, and the two checks do not have to know about each other.

def listdir(path) -> List[String]:
    """The entries of the directory `path`, or 0 when there is no such
    directory.

    A BLOB, and it now SAYS SO: the declared return type is `List[String]`,
    which on this path is the annotation that means "one word pointing at
    `[count][element]…`" — exactly the layout the body below builds. That
    annotation is what lets a caller write `len(names)` and `for x in names`
    and `names[i]` instead of the three accessors below, and it is what
    `model.imported_callee_kind` reads across the dylib boundary a caller is
    really behind (`bugs/FORMAL_listdir_no_run_time_sequence.md` item 1: the
    representation was already right and the KIND was missing). It costs
    nothing: the C signature is `int64_t` either way, because a list is one
    word, so this is metadata and not an ABI change.

    The three accessors REMAIN, because they are the honest spelling for a
    caller that wants to free the blob, and `listdir_len`/`listdir_get` are
    what the element-kind refusals read when a use site must decide. The caller
    OWNS the result and every name in it, which means `listdir_free` is the
    caller's to call and a store through `names` is refused rather than
    obeyed — the header above gives the two checks that decide that.

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

def walk(root, maxdepth) -> List[String]:
    """Every directory at or below `root`, down to `maxdepth` levels, or 0 when
    `root` is not a directory.

    `List[String]` for the reason `listdir` above says: the value is one word
    pointing at a `[count][element]…` blob, so the annotation is what lets a
    caller ask its length and iterate it, and it is metadata rather than an ABI
    change.

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
