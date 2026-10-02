"""`fcntl` — the flag table, with the locks admitted.

`fcntl` is CPython's window onto two POSIX facilities this target does not have.
`flock` and `lockf` are ADVISORY locks held by the KERNEL on behalf of a
descriptor, and whether a lock is granted depends on what every other process
holding the same file has done -- which is a fact about the machine, not about
this image, and is exactly the kind of external fact an admitted contract is for.
`fcntl(fd, cmd, …)` itself is the same story for the descriptor-manipulation
commands.

WHAT IS DECIDED HERE, AND IT IS THE PART THAT HAS WRONG ANSWERS
-----------------------------------------------------------------
Every CONSTANT in CPython's `fcntl` is a number this tree can state exactly, and
every one of them is checked against CPython's own module by
`test_formal_admitted.py` -- name by name, including the ones this file does NOT
export.  A module that exported a plausible number under a name CPython does not
have is precisely the thing this directory does not do.

WHAT IS ADMITTED, AND WHY IT IS THE WHOLE OF THE REST
------------------------------------------------------
  * `flock` — the return is 0 when the lock was taken, and otherwise an `errno`
    that is a fact about every OTHER holder of the file.  The contract is that
    the answer is one word and that the ADMITTED answer is not invented here: on
    this target there is no second descriptor to conflict with, so a `0` would be
    a claim about the machine's state that nothing checked.  So the call refuses,
    with 125 as `formal/hostmods/subprocess.mojo` explains.
  * `fcntl_cmd` — one call for the `F_*` commands, over a descriptor and a
    command word, for the same reason `ctypes.cdll_call` is one call: the
    commands have different arities and different argument types, and a contract
    that guessed one arity would be a claim about a C prototype nobody here has.

WHY THE CONSTANTS ARE FUNCTIONS AND NOT A TABLE
-----------------------------------------------
A module-level name on this path is folded at every read and needs no storage
(`bugs/FORMAL_module_state_no_storage.md`), so `fcntl.LOCK_EX` could be written
as a literal -- but then `formal/hostmods/os/__init__.mojo`'s rule about `os.sep`
applies: the value is folded at each read site and a function is the spelling
every other hostmod uses for a constant, so a file importing `fcntl` and a file
importing `os` read the same.  Consistency here is not tidiness: it is what lets
one test compare both modules' constants with one loop.
"""

# ── the flag table ───────────────────────────────────────────────────────────
# CPython's exact values, checked name by name by `test_formal_admitted.py`
# against `getattr(fcntl, name)`.

def LOCK_SH() -> int:
    """`fcntl.LOCK_SH`: 1 — a shared (read) lock."""
    return 1

def LOCK_EX() -> int:
    """`fcntl.LOCK_EX`: 2 — an exclusive (write) lock."""
    return 2

def LOCK_NB() -> int:
    """`fcntl.LOCK_NB`: 4 — do not block; fail immediately instead."""
    return 4

def LOCK_UN() -> int:
    """`fcntl.LOCK_UN`: 8 — release."""
    return 8

def F_DUPFD() -> int:
    """`fcntl.F_DUPFD`: 0 — `dup`, lowest free descriptor."""
    return 0

def F_GETFD() -> int:
    """`fcntl.F_GETFD`: 1."""
    return 1

def F_SETFD() -> int:
    """`fcntl.F_SETFD`: 2."""
    return 2

def F_GETFL() -> int:
    """`fcntl.F_GETFL`: 3."""
    return 3

def F_SETFL() -> int:
    """`fcntl.F_SETFL`: 4."""
    return 4

def FD_CLOEXEC() -> int:
    """`fcntl.FD_CLOEXEC`: 1 — close the descriptor across `exec`."""
    return 1

def F_DUPFD_CLOEXEC() -> int:
    """`fcntl.F_DUPFD_CLOEXEC`: 67.

    The largest number in this table by an order of magnitude, and it is here
    precisely because it is the one that would be easy to guess wrong: 64 and 65
    are `F_SETLK`/`F_SETLKW` on Linux and 67 is this one, so a value written from
    the shape of the others rather than from CPython's own module is plausible and
    wrong.  `test_formal_admitted.py` requires CPython's answer.
    """
    return 67


# ── the admitted half ────────────────────────────────────────────────────────

ADMITTED_EXIT_STATUS = 125
"""The status an admitted call exits with; `formal/hostmods/subprocess.mojo` says why."""

def _admitted(what: str) -> int:
    """Refuse to answer, naming the contract that would have to be trusted."""
    printf("fcntl: %s is an ADMITTED contract on this target\n", what)
    printf("fcntl: a lock is held by the kernel on a descriptor, so whether it\n")
    printf("fcntl: is granted depends on every other holder of the file.\n")
    exit(ADMITTED_EXIT_STATUS)
    return 0

@admitted("the answer is one word: 0 when the lock was taken, or an errno that is a fact about every other holder of the file")
def flock(fd: int, operation: int) -> int:
    """`fcntl.flock(fd, operation)`: take, convert or release an advisory lock.

    `LOCK_SH() | LOCK_NB()` is how a caller spells "shared, do not block" on this
    path, and `LOCK_EX() | LOCK_NB()` the exclusive form: the `|` is real
    arithmetic over two folded constants, not a spelling this module has to
    understand, which is the whole reason the constants are functions a caller
    can combine.

    The contract is about the SHAPE of the answer and not one word of it.  A
    target with a single descriptor and no second holder would "succeed" here, and
    saying so would be a claim about the machine's state that no test in this tree
    could check -- which is the failure `formal/admitted.py`'s
    `contract_text_is_scoped` refuses to let a contract text make.

    TWO PARAMETERS, and a CALL to it is refused by the proof generator -- stated
    here rather than left to be discovered.  `MojoExpr.call` in `lib/ProofLib.lean`
    carries one `UInt64`, so an admitted contract can only be applied to a
    one-argument call (`formal/arm64_proof_gen.py`'s `_call_go` refuses the rest,
    naming the call).  The signature above is still CPython's, because the task
    this module does is to model the API SHAPE and a signature with one parameter
    would be a signature CPython does not have; what the arity costs is the
    proof-side application, and the cost is filed rather than paid by inventing a
    one-argument spelling nobody wrote.
    """
    return _admitted("fcntl.flock")
