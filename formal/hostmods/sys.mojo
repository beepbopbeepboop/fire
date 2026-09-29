"""
sys.mojo - the `sys` module for the formal backend.

`formal/imports.py` resolves an import in four passes, and the FIRST is "a
Mojo source `<name>.mojo` or `<name>/__init__.mojo` in a search root WINS
OUTRIGHT, even over the host-module list". This file is that source for the
name `sys`, so `import sys` is no longer the refusal

    imports 'sys', which is a host module (CPython standard library), which
    has no Mojo source for this backend to compile

It lives in `formal/hostmods/` — the directory `formal/imports.py` adds to
every file's search roots as its last entry, so a file in `tools/` and a file
at the top level both find it, and nothing else in the tree does. NOT at the
repository root, where the first three of these modules were written: the root
is a search root for four independent resolvers (`imports.py`'s `Resolver`,
`module_loader.py`, the interpreter's sibling-module loader, and the gimple
backend), so a Mojo `sys` there captured `import sys` in the compiler's own
sources. See `formal/imports.py`'s `_HOSTMODS_ROOT`.

WHAT THIS TARGET CAN ANSWER
---------------------------
A formal value is one 64-bit word that lives in a function's own stack
scratch, reclaimed when the function returns (`formal/model.py`, "no
storage"). Everything below is a consequence of that and nothing here is a
guess:

  * a function is a word in and a word out, so every export here takes and
    returns scalars, and a `str` is a bare `char *`;
  * a module-level name that is not a literal-only constant has nowhere to
    live, so this module has NO state. Nothing here remembers anything
    between calls;
  * a tuple or a list is a blob carved out of a frame, so it cannot cross a
    dylib boundary at all - returning one hands the caller a frame address
    that is dead on return. That is why the version is three integers rather
    than a `version_info` tuple;
  * `argc`/`argv` do not survive to here: the entry stub
    (`ARM64Codegen.compile`) loads the test input into X0 and calls the entry
    function, so the process's command line is gone before the first
    statement runs.

SO `sys.argv`, `sys.path`, `sys.modules`, `sys.stdin`, `sys.stdout`,
`sys.stderr` and `sys.version_info` are NOT in this module, and no
implementation of them would be honest on this target. The reason in every
case is the same one - a name that outlives the frame that made it - and the
construct each of them needs is written down in
`bugs/FORMAL_module_state_no_storage.md` with the measurements.

That is the honest answer, and the alternative — shipping `sys.argv` as a
function that returns a made-up list, or `sys.stderr` as a struct with no
descriptor in it — would be a module that computes something other than what
its name says.

`sys.exit(code)` is absent for a DIFFERENT and settled reason: `doc/ABI.md`'s
export rule declines to advertise a C library symbol, and `exit` is one
(`reflect._CLIB_SYMS`; measured and settled in `bugs/FORMAL_known_limits.md`
1.1). No module dylib can therefore be called by that name. On this target
the working spelling is the library's own `exit(code)`, which lowers today as
an extern call - see `test_formal_sys.py`.

NAMES CPYTHON'S `sys` DOES NOT HAVE
-----------------------------------
Two capabilities this target has and CPython's `sys` does not expose under
these names, because in CPython they are methods on a file object this
value model cannot represent. They are spelled here as functions and are
marked at their definitions.
"""


# ── the language this compiler implements ──────────────────────────────────
#
# These answer "which language am I a program for", which is a fact about the
# COMPILER and not about the target - and it is the one question `sys.version`
# exists to answer. The micro version is CPython 3.14.6, the release this
# tree's own stdlib harness (`py314_harness.py`) runs against; a formal
# program has no patch release of its own to report.

def version() -> str:
    """`sys.version`: the language version, and which backend answered."""
    return "3.14.6 (fire formal backend)"

def version_info_major() -> int:
    """`sys.version_info[0]`. A scalar, because a tuple cannot cross a
    dylib boundary on this path - see the module docstring."""
    return 3

def version_info_minor() -> int:
    """`sys.version_info[1]`."""
    return 14

def version_info_micro() -> int:
    """`sys.version_info[2]`: the CPython release this tree targets."""
    return 6

def hexversion() -> int:
    """`sys.hexversion`: 0x030E06F0, the same three numbers packed."""
    return 132150768

def api_version() -> int:
    """`sys.api_version`: 1013, the C-level API version, which is the number
    every CPython 3.x release has reported since 3.1."""
    return 1013


# ── the target's value model ──────────────────────────────────────────────
#
# These are not guesses about the hardware; they are what a formal program can
# hold, and a program that branches on them is branching on the truth about
# the image it is running in.

def maxsize() -> int:
    """`sys.maxsize`: 2**63 - 1.

    A formal value is one 64-bit word (`formal/model.py`, "What a value is"),
    so the largest integer this target can represent is the largest signed
    64-bit one. The two architectures this backend emits for are both
    little-endian, which is why `byteorder` is a constant and not a question.
    """
    return 9223372036854775807

def byteorder() -> str:
    """`sys.byteorder`: "little" on both arm64 and x86-64."""
    return "little"

def get_int_max_str_digits() -> int:
    """`sys.get_int_max_str_digits()`: 0.

    0 is CPython's own spelling of "no limit" (the default before 3.11 and
    the value that disables the limit after it), and it is also the truth
    here: integer/string conversion on this path is `strtol` and `printf`,
    neither of which has a digit cap.
    """
    return 0

def set_int_max_str_digits(limit: int) -> int:
    """`sys.set_int_max_str_digits(limit)`: returns `limit`, changes nothing.

    There is no limit to change - see `get_int_max_str_digits`. This exists so
    a program that sets the limit before doing `int()` on untrusted input is a
    program that RUNS on this target rather than one that is refused for
    calling a function that does not exist. The value is not remembered,
    because this module has no state; a program that needs the setting to
    persist has to carry it itself.
    """
    return limit


# ── the interpreter there is not ──────────────────────────────────────────
#
# Every one of these is a question about a Python interpreter's own machinery.
# There is no interpreter here: the source is compiled to machine code and the
# call stack is the machine stack. The answers below are what that is true of,
# and each says so at its definition rather than leaving a reader to infer it
# from a number.

def getrecursionlimit() -> int:
    """`sys.getrecursionlimit()`: 0, meaning "no interpreter recursion limit".

    CPython's is a limit on the interpreter's own frame stack and is always at
    least 1. This path's recursion is bounded by the machine stack and by the
    frame the backend reserves, neither of which a program can query or raise,
    so 0 is the honest answer and `max(0, anything)` behaves the way a program
    raising a limit expects.
    """
    return 0

def setrecursionlimit(limit: int) -> int:
    """`sys.setrecursionlimit(limit)`: returns `limit`, changes nothing.

    There is no interpreter stack for a limit to govern (see
    `getrecursionlimit`), and this module has no state to record the request
    in. It returns the requested value so the call's own contract - "the new
    limit is what you asked for" - holds, and it refuses nothing: a program
    that raises a limit before recursing is a program that runs here.
    """
    return limit

def is_finalizing() -> int:
    """`sys.is_finalizing()`: 0 (False). Nothing on this target finalizes -
    there is no module teardown, no `atexit`, and no garbage collector (a
    formal value is a word in a frame, so there is nothing to collect)."""
    return 0

def get_coroutine_origin_tracking_depth() -> int:
    """`sys.get_coroutine_origin_tracking_depth()`: 0.

    `async def` lowers as an ordinary function here (`ARM64Codegen.compile`),
    so there is no coroutine machinery to track origins through.
    """
    return 0

def set_coroutine_origin_tracking_depth(depth: int) -> int:
    """`sys.set_coroutine_origin_tracking_depth(depth)`: returns `depth`,
    changes nothing - see `get_coroutine_origin_tracking_depth`."""
    return depth


# ── encodings ─────────────────────────────────────────────────────────────
#
# There is no encoding layer on this path. A `str` is a bare `char *` and
# `len` of one is `strlen`, so the bytes a program writes are the bytes its
# source contained. That makes these two answers true in the only sense this
# target can act on: nothing transcodes, and a program that hands a non-ASCII
# byte sequence to a `write` gets those exact bytes out.

def getdefaultencoding() -> str:
    """`sys.getdefaultencoding()`: "utf-8" - the encoding a `str` literal is
    read as, and the one this tree's sources are written in."""
    return "utf-8"

def getfilesystemencoding() -> str:
    """`sys.getfilesystemencoding()`: "utf-8". Paths are `char *` handed
    straight to `open(2)`, with no encoding step in between."""
    return "utf-8"

def getfilesystemencodeerrors() -> str:
    """`sys.getfilesystemencodeerrors()`: "strict" - the handler that would
    be used, and the only one that exists: a path that is not valid text is
    simply the bytes it is."""
    return "strict"


# ── the output streams there are ──────────────────────────────────────────
#
# A formal image writes through file descriptors, and `sys.stderr` cannot be
# a stream OBJECT because there is nothing to hold one - so the two writes
# CPython spells `sys.stdout.write(s)` and `sys.stderr.write(s)` are spelled
# here as functions. Both are `write(2)` on the descriptor, which is
# unbuffered: what the function returns is the byte count `write(2)` reports,
# or -1 if it failed.
#
# STRING ESCAPES ARE NOT INTERPRETED on this path, so a newline has to be a
# real byte in the source, not a `\n` in a literal. That is a property of
# string literals rather than of this module, and it is measured in
# `test_formal_sys.py` so the limitation is pinned rather than discovered.

def write_stdout(s: str) -> int:
    """Write `s` to file descriptor 1. NOT CPython's `sys` - see the module
    docstring for why `sys.stdout.write` has no spelling here.

    Returns what `write(2)` returned: the number of bytes written, or -1.
    """
    return write(1, s, strlen(s))

def write_stderr(s: str) -> int:
    """Write `s` to file descriptor 2, unbuffered. NOT CPython's `sys` -
    see the module docstring."""
    return write(2, s, strlen(s))

def flush_output() -> int:
    """Flush every buffered output stream: `fflush(NULL)`. NOT CPython's
    `sys`.

    One function rather than two because a C `FILE *` cannot be named on this
    path: there is no storage for one, so `fflush(stdout)` is not expressible
    and `fflush(NULL)` - which flushes all of them - is. In practice this
    matters for `print`, which lowers to `printf` and is therefore buffered,
    while the two `write_*` functions above are not.
    """
    return fflush(0)
