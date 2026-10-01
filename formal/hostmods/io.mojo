"""`io` — the seek constants and the buffer size, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import io` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` for why these did NOT go at
the repository root, where the first three of them captured `import os` in the
compiler's own sources.

WHAT IS HERE, AND WHY IT IS FOUR CONSTANTS
------------------------------------------
CPython's `io` is STREAMS: `open`, `StringIO`, `BytesIO`, `FileIO`, the
`RawIOBase` / `BufferedIOBase` / `TextIOBase` hierarchy and the `Reader` /
`Writer` pair. Every one of those is an object with state — a descriptor, a
cursor and a buffer — and on this path **a value cannot cross a dylib boundary
unless it is one 64-bit word** (`bugs/FORMAL_module_state_no_storage.md`).
`formal/hostmods/sys.mojo` already says what that leaves of CPython's `sys`
streams, and this is the same statement one level up: `sys` spells
`sys.stdout.write` as two functions because a stream is not a word, and `io` is
those streams.

So what remains is the part of `io` that is CONSTANTS, and they are constants
in name only: `io.SEEK_SET` is a module-level name, and a module-level name is
inlined at its use site and crosses no boundary, so every one of them is a
zero-argument function for the reason `os.sep` is one
(`formal/hostmods/os/__init__.mojo` says it at length). Four names, four
numbers, and `test_formal_io.py` checks each against CPython's own `io`.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `open`, `open_code` — a FILE OBJECT, so the same reason as the streams.
    And the wrapper this module's predecessor doc suggested does not exist
    either: `io.open` over `os` is not writable on this target, because
    `formal/hostmods/os/_syscalls.mojo` has `fs_open_ro`, `fs_lseek` and
    `fs_close` and NO read or write call — measured by reading the file, and
    the absence is a fact about what that module implemented rather than about
    this one. A file's CONTENTS are the missing half, and they are a stream.
  * `StringIO`, `BytesIO` — a MUTABLE BUFFER WITH A CURSOR. A buffer that grows
    is a run-time-length sequence, which is the same limit that stops
    `os.listdir` and SHAKE (`bugs/FORMAL_listdir_no_run_time_sequence.md`): a
    list's capacity is the number of `append` SITES in the function that builds
    it, so a buffer whose length is only known at run time cannot be built.
    `test_formal_sweep_truth.py` is the one file in this tree blocked on `io`,
    and it wants `io.StringIO()` for a `redirect_stderr` capture — so it moves
    from a host-import refusal to a refusal naming this, which is progress and
    is recorded as such.
  * `FileIO`, `BufferedIOBase`, `BufferedReader`, `BufferedWriter`,
    `BufferedRWPair`, `BufferedRandom`, `RawIOBase`, `TextIOBase`,
    `TextIOWrapper`, `IOBase`, `IncrementalNewlineDecoder`, `BlockingIOError`,
    `UnsupportedOperation`, `Reader`, `Writer` — TYPES and EXCEPTIONS. A type
    is not a value and an exception is a raise, and this path has neither
    (`FORMAL.md` phase 7).
  * `GenericAlias`, `text_encoding`, `abc` — a typing form, a version string
    and a module respectively; see `formal/hostmods/typing.mojo` for the first
    and `formal/hostmods/os/__init__.mojo` for the third.
  * `DEFAULT_NEWLINE`, `BLOCK_SIZE`, `MAX_BUFFER_SIZE` — NOT CPython NAMES.
    Checked against this tree's CPython 3.14.6: `io` has no such attribute, and
    a module that exported a plausible number under a name CPython does not
    have is exactly the thing this directory's modules do not do.
"""

def SEEK_SET() -> int:
    """`io.SEEK_SET`: 0 — seek from the start of the stream.

    The value is libc's `SEEK_SET` and the C library's is what
    `formal/hostmods/os/_syscalls.mojo`'s `fs_lseek` takes, so a program that
    passes this to it needs no conversion.
    """
    return 0

def SEEK_CUR() -> int:
    """`io.SEEK_CUR`: 1 — seek from the current position."""
    return 1

def SEEK_END() -> int:
    """`io.SEEK_END`: 2 — seek from the end of the stream."""
    return 2

def DEFAULT_BUFFER_SIZE() -> int:
    """`io.DEFAULT_BUFFER_SIZE`: 131072, which is 2**17.

    A constant here rather than a question about the filesystem, and that is
    measured rather than assumed: this tree's CPython 3.14.6 reports
    `os.stat('/').st_blksize == 4096` and `io.DEFAULT_BUFFER_SIZE == 131072`,
    so the value is not derived from a block size on this build. A future
    CPython that derived it would make `test_formal_io.py` red, which is the
    right outcome for a module whose job is to be a mirror.

    Nothing in this tree reads it, and it is here because it is a CPython `io`
    name with an exact answer rather than because a caller needs it — the one
    exception to this directory's caller-driven rule, and the smallest possible
    one: a number is a number, and the whole cost of being wrong about it is
    checked rather than assumed.
    """
    return 131072
