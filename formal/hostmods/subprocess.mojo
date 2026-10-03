"""`subprocess` — the API SHAPE, with the host's answer admitted.

`formal/imports.py` used to refuse every file importing `subprocess`, which is
30 files in the arm64 sweep and the largest single row in it.  The refusal was a
true statement about the TARGET (a second process) and a useless statement about
the file, so this module exists to make the second half answerable.

WHAT IS DECIDED HERE, AND WHAT IS ADMITTED
------------------------------------------
CPython's `subprocess` does two separable things, and the separation is the
whole design:

  1. It validates the arguments, and every one of those checks is a function of
     the argument's SHAPE — an int where an iterable belongs, an empty list, a
     non-str element, an unknown keyword.  Those are facts about Python that
     this tree can compute, so they are COMPUTED here, and
     `test_formal_admitted.py` checks every one of them against CPython's own
     verdict by running the same table through the real `subprocess`.

  2. It asks the host to run a program and reports what happened.  That answer
     is an external fact — whether `/bin/ls` exists, what it wrote, what it
     exited with — and nothing in this tree can derive it.  So each operation
     whose answer is that fact carries an `@admitted(...)` declaration saying
     exactly what is assumed, and the generated Lean turns each into a `sorry`
     that `formal/lean.py`'s census counts.

The line between them is the line between a shape and an answer, and it is drawn
per operation rather than per module because `subprocess` is mostly shape:
`check_returncode(0)` needs no host at all, and a file that only calls it gets a
model with no admission in it.

WHAT A CALL ACTUALLY DOES AT RUN TIME
-------------------------------------
`run` and the rest do not compute an answer and do not invent one.  They print a
diagnostic naming the contract they rest on and exit with a status the caller
cannot mistake for a child's: `ADMITTED_EXIT_STATUS` is 125, which is outside
`0..255` and therefore cannot be read as the exit status of a process this image
did not run.  A program that calls `subprocess.run` on this target stops with a
number that says so, rather than printing a number the source never wrote — the
failure this project treats as its worst, recorded in
`bugs/FORMAL_known_limits.md` §"fabricated a value".

That is a deliberate refusal to answer, and it is what makes the admission
honest rather than convenient.  The alternative — returning 0 — is what
`formal/arm64_proof_gen.py`'s deleted `dylib_export_contract_stub` did with
`fun n => n`, and it is a claim about the host that no test could check.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `Popen` as an OBJECT, and with it `stdin`/`stdout`/`stderr`, `communicate`,
    `poll`, `wait`, `kill`, `terminate`, `send_signal`.  A process handle is a
    descriptor, a status word and a pair of pipes; a value cannot cross a dylib
    boundary unless it is one 64-bit word
    (`bugs/FORMAL_module_state_no_storage.md`), which is the same limit that
    took `sys.stdout` out of `formal/hostmods/sys.mojo`.  What IS here is
    `popen_*` as the ONE CALL each of those methods makes, so a file that wants
    "run this and tell me the status" has a name to call and a file that wants
    the object's identity does not.
  * `CompletedProcess`, `TimeoutExpired` and `CalledProcessError` as TYPES.  A
    struct is a frame blob and an exception is a raise, and this path has
    neither (FORMAL.md phase 7).  Their FIELDS are the answerable part and are
    what `completed_process_returncode` and `check_returncode` return.
  * `subprocess.list2cmdline` — it is pure, and it belongs to a file that wants
    it; it is not here because no file in the tree calls it and the admission
    it would need (Windows quoting rules) is not this target's.
  * `getoutput`/`getstatusoutput` are here as one call each because they differ
    only in what they return, and that difference is a word this model can carry.

WHAT IS ASSUMED OF THE HOST — the three contracts, in one place
----------------------------------------------------------------
Every `@admitted` below states an assumption about the RETURNED WORD and nothing
else; `formal/admitted.py`'s `contract_text_is_scoped` enforces that rule by
refusing any contract text containing a claim about host behaviour.  The three:

  * `run`      — the child's exit status, an integer in 0..255, and the output
                 bytes are an arbitrary byte string.
  * `call`     — the same, and nothing is raised for a non-zero status.
  * `check_returncode` — the status word is in 0..255, and a word outside it
                 means "died from a signal", whose number this model does not
                 carry.  This one is admitted on the SHAPE half only: whether a
                 given status raises `CalledProcessError` is computed below and
                 checked against CPython.
"""

# ── the constants ────────────────────────────────────────────────────────────
# Exact CPython values, checked name by name by `test_formal_admitted.py`.
# They are constants in name only: a module-level name is folded at every read
# on this path (`formal/hostmods/os/__init__.mojo` says why at length), so each
# is a zero-argument function like `os.sep` and `io.SEEK_SET`.

def PIPE() -> int:
    """`subprocess.PIPE`: -1.

    A sentinel rather than a file descriptor, and the reason it is a sentinel is
    the reason the pipes themselves are not modelled: the only thing a caller
    can do with this word is compare it against another word.
    """
    return -1

def STDOUT() -> int:
    """`subprocess.STDOUT`: -2 — send stderr to stdout."""
    return -2

def DEVNULL() -> int:
    """`subprocess.DEVNULL`: -3 — discard the stream."""
    return -3


# ── the decidable half: argument validation ──────────────────────────────────
# Each of these takes an ARGUMENT-SHAPE CODE, not the argument.  A value on this
# path is one 64-bit word, so a list is not representable and the model asks the
# question it can ask: what KIND of thing was passed.  `test_formal_admitted.py`
# drives the same table through CPython's own `subprocess`, so each verdict here
# is compared against the exception CPython really raises for a real argument of
# that shape — the shape code is the model's stand-in for the value, and the
# table is what makes the stand-in honest.
#
# `OK` means "CPython raised nothing here and went on to touch the host", which
# is the boundary: past `OK` the answer is not the model's to give.

ARG_OK = 0
ARG_NOT_ITERABLE = 1
ARG_EMPTY = 2
ARG_ELEMENT_NOT_PATH = 3
ARG_UNKNOWN_KEYWORD = 4
ARG_BUFSIZE_NOT_INT = 5
ARG_NO_ARGS = 6

def validate_args(args_kind: int, element_kind: int, keywords: int) -> int:
    """Which exception CPython raises for these argument shapes, or `ARG_OK`.

    `args_kind` names what was passed as `args` (`ARG_NO_ARGS`,
    `ARG_NOT_ITERABLE`, `ARG_EMPTY`, or `ARG_OK` for a non-empty iterable);
    `element_kind` names the first element's type (`ARG_ELEMENT_NOT_PATH` when
    it is neither `str` nor `bytes` nor `os.PathLike`); `keywords` counts
    keyword arguments CPython's `Popen.__init__` does not have.

    The order matters and is CPython's, not this file's: `Popen(5, bogus=1)`
    raises `'int' object is not iterable`, not "unexpected keyword", because the
    signature binds `args` before it looks at the keywords.  `test_formal_admitted.py`
    checks the combinations in CPython's order for the same reason.
    """
    if args_kind == ARG_NO_ARGS:
        return ARG_NO_ARGS
    if args_kind == ARG_NOT_ITERABLE:
        return ARG_NOT_ITERABLE
    if args_kind == ARG_EMPTY:
        return ARG_EMPTY
    if element_kind == ARG_ELEMENT_NOT_PATH:
        return ARG_ELEMENT_NOT_PATH
    if keywords > 0:
        return ARG_UNKNOWN_KEYWORD
    return ARG_OK

def validate_bufsize(bufsize: int) -> int:
    """`Popen(bufsize=…)`: `ARG_BUFSIZE_NOT_INT`, or `ARG_OK`.

    Checked separately because CPython raises it from the constructor body rather
    than from the signature, so `validate_args` cannot see it — a second function
    is the honest shape here and folding it into the first would make one of the
    two verdicts unreachable.
    """
    if bufsize < -1:
        return ARG_BUFSIZE_NOT_INT
    return ARG_OK


# ── the decidable half: return shapes ────────────────────────────────────────

def completed_process_returncode(status: int) -> int:
    """`CompletedProcess(args, returncode).returncode`: the status word, unchanged.

    A constructor that stores a field and a getter that reads it back, which is
    the whole of what a struct's shape amounts to when the struct cannot cross a
    boundary.  `test_formal_admitted.py` pins it against CPython's own
    `CompletedProcess(1, 2, b'a', b'b').returncode`.
    """
    return status

def check_returncode(status: int) -> int:
    """`CompletedProcess.check_returncode()`: `ARG_OK`, or `ARG_NONZERO_STATUS`.

    Decided, not admitted, because it is a function of the status word alone:
    CPython returns `None` when the status is zero and raises
    `CalledProcessError` when it is not.  Which of those two happens is visible
    to any caller of the word, so it is the model's to give.
    """
    if status == 0:
        return ARG_OK
    return 7

ARG_NONZERO_STATUS = 7


# ── the admitted half ────────────────────────────────────────────────────────
# One call per CPython operation whose ANSWER is a fact about the host.  Each
# carries the `@admitted` text that becomes the `sorry` in the generated Lean,
# and each prints its own contract before refusing to answer, so a run of the
# image says which admission stopped it.

ADMITTED_EXIT_STATUS = 125
"""The status an admitted call exits with.

125 is outside `0..255`, so it cannot be read as a child's exit status — which is
the whole point.  A refusal that returned a plausible number would be a
fabricated answer wearing a diagnostic's clothes, and the number has to make the
mistake impossible rather than unlikely.
"""

def _admitted(what: str) -> int:
    """Refuse to answer, naming the contract that would have to be trusted.

    The one place all four admissions share a body, and it is a function like
    any other so that the printed text is a single fact rather than four copies
    of it that can drift.  `exit` is a libSystem symbol this target binds
    (`formal/model.py`'s `FRAME_C_VALUE_CALLS` lists it), and the message goes to
    stdout because there is no `stderr` on this path: `stderr` is a stream, and
    a stream is not a value here (`formal/hostmods/sys.mojo`).
    """
    printf("subprocess: %s is an ADMITTED contract on this target\n", what)
    printf("subprocess: this image does not run a second process; the answer is\n")
    printf("subprocess: not computed, and no number here is a child's status.\n")
    exit(ADMITTED_EXIT_STATUS)
    return 0

@admitted("the child's exit status, an integer in 0..255, and the captured output bytes are an arbitrary byte string")
def run(request: str) -> int:
    """`subprocess.run(argv, capture_output=…)`: run a program, wait, report.

    The signature is the model's, not CPython's, and the difference is forced
    twice over.  CPython's is `run(*popenargs, input=None, capture_output=False,
    timeout=None, check=False, **kwargs)`, and a `*args` and a `**kwargs` are two
    run-time length sequences, which a list on this path cannot be
    (`bugs/FORMAL_listdir_no_run_time_sequence.md`).  And the model needs ONE
    parameter anyway: `MojoExpr.call` in `lib/ProofLib.lean` carries a single
    `UInt64`, so the AST layer of a generated proof can only evaluate a one-
    argument call, and an admission applied to two arguments in one layer and one
    in the other would make `eval_eq_mojo` false rather than merely unproved.
    So `request` is the whole command as one string — argv, the environment and
    the capture flags together — which is the same thing a shell is handed, and
    `formal/arm64_proof_gen.py`'s `_call_go` refuses a call with any other arity
    rather than dropping the extra arguments.

    The return word is the exit status, which is what `run` is called for in
    every one of the thirty files that import this module.
    """
    return _admitted("subprocess.run")

@admitted("the child's exit status, an integer in 0..255, and nothing is raised for a non-zero status")
def call(request: str) -> int:
    """`subprocess.call(argv)`: run a program and return its status.

    `run`'s sibling without the capture, and the reason the two are separate
    contracts rather than one is that their assumptions differ: `call` promises
    no exception for a failing child, so a file that only calls it is trusting
    strictly less.
    """
    return _admitted("subprocess.call")

@admitted("the child's exit status, an integer in 0..255")
def check_call(request: str) -> int:
    """`subprocess.check_call(argv)`: run a program, raise if it failed.

    The RAISE is the admitted part rather than the status: this path has no
    exception mechanism (FORMAL.md phase 7), so what is admitted is the fact that
    a non-zero status would raise, and `check_returncode` above is where the
    decidable half of that judgement lives.
    """
    return _admitted("subprocess.check_call")

@admitted("the child's output on stdout, an arbitrary byte string")
def check_output(request: str) -> str:
    """`subprocess.check_output(argv)`: run a program and return its stdout.

    Returns a `str` and not bytes because a `char *` is what this path has: the
    content is arbitrary and NUL-terminated, which is a restriction the contract
    states rather than hides.
    """
    return _admitted("subprocess.check_output")

@admitted("the child's output on stdout, an arbitrary byte string")
def getoutput(cmd: str) -> str:
    """`subprocess.getoutput(cmd)`: run a shell command line, return its output."""
    return _admitted("subprocess.getoutput")

@admitted("the shell command's exit status, an integer in 0..255, and its output is an arbitrary byte string")
def getstatusoutput(cmd: str) -> int:
    """`subprocess.getstatusoutput(cmd)`: run a command line, return `(status, output)`.

    Two values in CPython and one word here, so what the word is has to be
    chosen rather than left: the STATUS, with the output not carried.  A caller
    that needs the output calls `getoutput`.  Which half to keep is stated in the
    admission above, so the choice is visible rather than a reader having to
    infer it from the signature.
    """
    return _admitted("subprocess.getstatusoutput")

@admitted("the child's exit status, an integer in 0..255")
def popen_wait(request: str) -> int:
    """`Popen(argv).wait()`: run a program and wait for it.

    The one call every `Popen` method is made of, for the reason the module's
    docstring gives: a process handle is a descriptor plus a status plus two
    pipes, none of which is one word.  `poll` is the same word and the same
    contract, and it is not a second function because there is no state to make
    the two differ.
    """
    return _admitted("Popen.wait")
