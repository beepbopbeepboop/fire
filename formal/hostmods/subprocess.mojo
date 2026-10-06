"""`subprocess` — the API SHAPE, with the host's answer admitted.

`formal/imports.py` used to refuse every file importing `subprocess`, and this
module exists to make the second half of that answerable: a second process is a
fact about the TARGET, but what a file SAYS is a question this tree can answer.

WHAT IS DECIDED HERE, AND WHAT IS ADMITTED
------------------------------------------
CPython's `subprocess` does two separable things, and the separation is the
whole design:

  1. It validates the arguments, and every one of those checks is a function of
     the argument's SHAPE — an int where an iterable belongs, an empty list, a
     non-str element, an unknown keyword, `capture_output` beside `stdout`.  Those
     are facts about Python that this tree can compute, so they are COMPUTED here,
     and `test_formal_admitted.py` checks every one of them against CPython's own
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

THE CALL SURFACE THIS MODELS IS MEASURED, NOT ASSUMED
------------------------------------------------------
The names and keywords below are the ones this repository's own source actually
spells, read with `ast` over every `.py` in the tree (`test_formal_subprocess.py`
re-measures them, and a name that appears without being modelled is a FAILURE
rather than a note):

    547  subprocess.run(args, capture_output=, text=, timeout=, cwd=, check=,
                        env=, errors=, shell=, input=, stdout=, stderr=, stdin=)
     18  subprocess.Popen(args, stdout=, stderr=, env=, start_new_session=,
                          cwd=, text=, pass_fds=, stdin=, errors=, preexec_fn=)
      3  subprocess.CompletedProcess(args, returncode, stdout=, stderr=)
     13  subprocess.PIPE    5 subprocess.DEVNULL    4 subprocess.STDOUT
     81  subprocess.TimeoutExpired    4 subprocess.SubprocessError
      4  subprocess.CalledProcessError

**EVERY keyword `run` is given here was measured refused before this file
declared it.**  `subprocess.run(["./x"], capture_output=True)` used to fail the
build with `call run(): unexpected keyword argument 'capture_output'`, and the
first version of this module — one parameter named `request` — could therefore
be called by NONE of those 547 call sites, however complete its contracts were.
That is a fact about the CALL, not about the host: a keyword argument to a
function in an imported module binds fine as soon as the callee has a parameter
of that name (`match(p="/x.py", pat="*.py")` builds today), so the fix is here
rather than in the ABI.  `bugs/FORMAL_host_import_row_5_measured.md` §`subprocess`
measured this row at 0 files and gave the keyword refusal as the mechanism; the
mechanism was wrong (it was a NAME mismatch in a probe, not a refusal of keyword
arguments), while the 0 was right for a different reason, which
`bugs/FORMAL_subprocess_row_measured_b7.md` re-measures over all 143 importing
files.

WHAT A CALL ACTUALLY DOES AT RUN TIME
-------------------------------------
`run` and the rest do not compute an answer and do not invent one.  They print a
diagnostic naming the contract they rest on and exit with `ADMITTED_EXIT_STATUS`.
A program that calls `subprocess.run` on this target stops with a number that says
so, rather than printing a number the source never wrote — the failure this
project treats as its worst, recorded in `bugs/FORMAL_known_limits.md`
§"fabricated a value".

**What that status can and cannot do**, because this file's earlier version of
this paragraph claimed something false about it and the claim was worth more
than the sentence it stood in.  125 is *inside* `0..255`, not outside it: it is
an ordinary child exit status (`sh -c 'exit 125'` is reported by CPython as 125),
and no exit code can be outside the range, because the kernel masks one —
`sh -c 'exit 300'` is reported as 44.  So the status cannot DISTINGUISH a refusal
from an answer, and the diagnostic printed on stdout is the channel that does;
125's real job is that it is nonzero and reserved by this tree.  The audit that
established this is `bugs/FORMAL_trust_audit_2026-10-04.md`, and
`test_formal_admitted.py`'s `truth` group re-measures both halves on every run.

That is a deliberate refusal to answer, and it is what makes the admission
honest rather than convenient.  The alternative — returning 0 — is what
`formal/arm64_proof_gen.py`'s deleted `dylib_export_contract_stub` did with
`fun n => n`, and it is a claim about the host that no test could check.

**None of the keywords changes what is admitted, and that is the reason they can
be declared at all.**  `capture_output`, `text`, `timeout`, `cwd` and the rest
select which host operations CPython would perform; every one of those branches
ends in the same refusal here, so there is no flag whose setting would make the
model answer differently.  They are declared so the call BINDS, and the model
reads none of them — an admitted call that honoured a flag would be a second,
undocumented answer.

THE ONE WORD, AND WHY A KEYWORD ARGUMENT DOES NOT BREAK IT
---------------------------------------------------------
`formal/admitted.py` declares each contract as `UInt64 → UInt64`, because
`MojoExpr.call` in `lib/ProofLib.lean` carries a single `UInt64` argument, and
`formal/arm64_proof_gen.py`'s `_call_go` REFUSES a call to an admitted operation
that passes any other number of arguments.  Every one of the 547 `run` call sites
passes exactly ONE POSITIONAL argument and the rest by keyword, so the rule is
satisfied by all of them: a keyword carries no separate Lean argument, and the
contract does not depend on it.  `run("./x", capture_output=True)` models as
`admitted_subprocess_run "./x"`, which is the same claim as `run("./x")` — and
they are the same claim, because the two calls make the model do the same thing.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `Popen` as an OBJECT, and with it `.args`/`.pid`/`.stdin`/`.stdout`/`.stderr`
    as attributes, `.stdin.write`, `.stdout.read`.  A process handle is a
    descriptor, a status word and a pair of pipes; a value cannot cross a dylib
    boundary unless it is one 64-bit word
    (`bugs/FORMAL_module_state_no_storage.md`), which is the same limit that took
    `sys.stdout` out of `formal/hostmods/sys.mojo`, and a method call on a value
    receiver is not lowered either.  What IS here is `Popen` as a FUNCTION
    returning the child's process id — which is the handle, so `.pid` needs no
    separate call — and one `popen_*` function per method, which is the same shape
    the old `popen_wait` had.
  * `subprocess.PIPE` used as a VALUE rather than called (`stdout=subprocess.PIPE`,
    13 call sites).  Reading a module-level name that is not folded to a literal is
    `bugs/FORMAL_module_state_no_storage.md`; the constants are here as the
    zero-argument functions every other hostmod uses, because a module-level name
    is folded at every read on this path and a folded function name is not a word.
  * `SubprocessError` and `SubprocessError` as a catchable type.  It is the base
    of the two exceptions above and nothing else: no operation in this module
    raises it, and a class on this path is a frame blob
    (`formal/hostmods/struct.mojo` is what a struct looks like here).
  * `subprocess.list2cmdline` — it is pure, and it belongs to a file that wants
    it; it is not here because no file in the tree calls it and the admission
    it would need (Windows quoting rules) is not this target's.
  * The `**kwargs` half of `run`/`call`/`check_call`/`check_output`.  `**` is a
    run-time-length mapping, and a mapping on this path is a bump-allocated blob
    in the frame of the function that built it
    (`bugs/FORMAL_listdir_no_run_time_sequence.md`).  Each keyword CPython's
    callers in this tree actually pass is a NAMED parameter instead, and
    `validate_args`' `ARG_UNKNOWN_KEYWORD` is where a keyword that is neither
    named nor variadic is reported.
  * `getoutput`/`getstatusoutput` are here as one call each because they differ
    only in what they return, and that difference is a word this model can carry.

WHAT IS ASSUMED OF THE HOST — the twelve contracts, in one place
-----------------------------------------------------------------
Every `@admitted` below states an assumption about the RETURNED WORD and nothing
else; `formal/admitted.py`'s `contract_text_is_scoped` enforces that rule by
refusing any contract text containing a claim about host behaviour.  They are:

  * `run` / `call` / `check_call` — the child's exit status word, which is
    `0..255` for a normal exit and `-N` for a death by signal N.  **Both halves,
    and the second is not optional**: CPython's `Popen.returncode` is negative
    when the child was killed, `subprocess.run(["sh","-c","kill -9 $$"])
    .returncode` is `-9`, and a contract claiming `0..255` alone is claiming
    something the host does not do.  `check_call` additionally returns NOTHING
    in CPython, and says so.
  * `check_output` / `getoutput` — the child's output on stdout, up to the first
    NUL byte, because a `str` on this path is a NUL-terminated `char *` and
    CPython's own answer really does contain NULs (`check_output(["sh","-c",
    "printf 'a\\0b'"])` is three bytes).  The admission states the truncation
    rather than the host's byte string, because a word that cannot hold a NUL
    cannot admit it.
  * `getstatusoutput` — the same status word, through a shell, with the output
    not carried in this word.
  * `Popen` — the child's process id, a positive integer.  THAT is the handle,
    and `popen_*` take it unchanged.
  * `popen_wait` / `popen_poll` — the same status word, and for `poll` the
    model's own `POLL_NOT_COLLECTED` while the child is still running.  The
    sentinel is a constant and not `-1`, because `-1` IS an answer: CPython
    reports `-1` for a child killed by `SIGHUP`, so `-1` would make "not
    collected" and "killed by SIGHUP" the same word.
  * `popen_kill` / `popen_terminate` — the signal reaches the child this handle
    names **while that child is still running**; once it has been collected
    CPython sends nothing at all and returns without raising.  Separate contracts
    because they are separate operations with separate defaults (`SIGKILL` and
    `SIGTERM`), and a file that trusts one is not trusting the other.
  * `popen_communicate` — the child's output on stdout and stderr, concatenated
    and truncated at the first NUL for the same reason as `check_output`'s.

  The one fact that applies to all twelve is in `formal/admitted.py` rather than
  repeated twelve times: the Lean declaration is `UInt64 → UInt64`, so the word is
  the MODEL's answer to the question the caller asked, and for most of these
  operations CPython returns something that is not a word at all (`None`, a
  `CompletedProcess`, a `Popen`, a pair).
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


# ── the decidable half: the wrappers' own keyword rules ───────────────────────
# `run` and `check_output` are not `Popen`.  They are three lines of argument
# checking wrapped around it, and both raise `ValueError` for keyword
# combinations that are individually fine — `capture_output=True` beside
# `stdout=PIPE` says "capture it twice", and CPython refuses it in the wrapper
# before `Popen` is reached.  All 508 of this repository's `capture_output=`
# call sites sit inside that rule, so it is decided here rather than left to the
# host, and it is checked against CPython's own verdict by
# `test_formal_admitted.py` in CPython's own order.
#
# These are separate functions and not extra parameters of `validate_args`
# because they are a DIFFERENT question: `validate_args` is about what `Popen`
# binds, and these are about what the wrapper refuses before binding anything.

ARG_STDIN_AND_INPUT = 8
ARG_STDOUT_AND_CAPTURE = 9
ARG_STDOUT_NOT_ALLOWED = 10
ARG_CHECK_NOT_ALLOWED = 11

def validate_run(has_input: int, has_stdin: int, capture_output: int,
                 has_stdout: int, has_stderr: int) -> int:
    """`run`'s two `ValueError` rules, in CPython's order, or `ARG_OK`.

    `run` checks `input` against `stdin` FIRST and `capture_output` against
    `stdout`/`stderr` second, and the order is observable: `run(argv,
    input=b"x", stdin=PIPE, capture_output=True)` raises the `stdin`/`input`
    `ValueError`, never the `capture_output` one.  Measured, and the table in
    `test_formal_admitted.py` has a row for it for that reason.

    Each `has_*` is 1 for "the caller passed this keyword" and 0 for "the caller
    did not" — presence, not value, because both rules are about presence:
    `capture_output=False` beside `stdout=PIPE` is accepted by CPython.
    """
    if has_input != 0 and has_stdin != 0:
        return ARG_STDIN_AND_INPUT
    if capture_output != 0 and (has_stdout != 0 or has_stderr != 0):
        return ARG_STDOUT_AND_CAPTURE
    return ARG_OK

def validate_check_output(has_stdout_kw: int, has_check_kw: int,
                          has_input: int, has_stdin: int,
                          capture_output: int) -> int:
    """`check_output`'s own two `ValueError` rules, then `run`'s, or `ARG_OK`.

    `check_output` refuses `stdout` and `check` outright — "it will be
    overridden" — because it passes both itself on the way to `run`.  It then
    FORWARDS to `run`, so `capture_output` still trips `run`'s rule with the
    same message even though `check_output` does not mention it.  That is why
    `capture_output=True` raises the `capture_output` message here and not
    `check_output`'s own, and it is the reason this is one function rather than
    two.

    `has_stdout_kw` is "the CALLER passed `stdout`", which is not the same
    question as `validate_run`'s: `check_output` passes `stdout=PIPE` itself, so
    its `capture_output` rule always fires and its `stdout` rule fires only when
    the caller also passed one.
    """
    if has_stdout_kw != 0:
        return ARG_STDOUT_NOT_ALLOWED
    if has_check_kw != 0:
        return ARG_CHECK_NOT_ALLOWED
    return validate_run(has_input, has_stdin, capture_output, 1, 0)


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


# ── the decidable half: the exception and result CONSTRUCTORS ─────────────────
# Three names this repository spells 88 times between them (81 `TimeoutExpired`,
# 4 `CalledProcessError`, 3 `CompletedProcess`), and none of the three is a type
# on this path.  What IS answerable about all three is the one field a caller
# reads off the object: `returncode` for `CompletedProcess` and
# `CalledProcessError`, `timeout` for `TimeoutExpired`.  Each is a function of an
# argument the caller already has in a word, so each is DECIDED and pinned
# against CPython's own object by `test_formal_admitted.py`.
#
# A function and not a `struct`, and the difference is the whole reason this is
# here: a struct on this path is a frame blob, so a caller could construct one
# and could not read a field out of it across the boundary
# (`bugs/FORMAL_module_state_no_storage.md`).  What these return is the field the
# caller wanted, and it is the number the caller wrote — not a value this file
# invented, which is the line `formal/admitted.py`'s scope rule draws.

def CompletedProcess(args, returncode, stdout=0, stderr=0) -> int:
    """`CompletedProcess(args, returncode, stdout, stderr)`: the `returncode` word.

    `args`/`stdout`/`stderr` are named because CPython names them and callers
    pass them, and are not read: a list and a bytes object are not words.  The
    returned word is `returncode` exactly as it was passed, which is what
    `completed_process_returncode` says about the same fact and is why the two
    are separate names — one is the constructor, the other the accessor, and
    CPython has both.
    """
    return returncode

def CalledProcessError(returncode, cmd, output=0, stderr=0) -> int:
    """`CalledProcessError(returncode, cmd, output, stderr)`: the `returncode` word.

    CPython's `.stdout` is an alias for `.output` and `.stderr` is separate; none
    of the three is a word here, so the `returncode` is what comes back.
    """
    return returncode

def TimeoutExpired(cmd, timeout, output=0, stderr=0) -> int:
    """`TimeoutExpired(cmd, timeout, output, stderr)`: the `timeout` word.

    The only field of CPython's four that is an integer, and the one a caller
    that catches this exception actually compares.  `cmd` is CPython's own spelling
    for the argument it calls `args` elsewhere, kept so a caller spelling it
    binds.
    """
    return timeout


# ── the admitted half ────────────────────────────────────────────────────────
# One call per CPython operation whose ANSWER is a fact about the host.  Each
# carries the `@admitted` text that becomes the `sorry` in the generated Lean,
# and each prints its own contract before refusing to answer, so a run of the
# image says which admission stopped it.

ADMITTED_EXIT_STATUS = 125
"""The status an admitted call exits with: NONZERO and RESERVED, not out of range.

The earlier version of this comment said 125 was outside `0..255` and therefore
could not be read as a child's exit status.  Both halves of that were false, and
both are measurable:

  * 125 is INSIDE `0..255`.  `subprocess.run(["/bin/sh","-c","exit 125"])
    .returncode` is 125 — an ordinary child, dying the ordinary way.
  * no exit code can be outside the range.  The kernel masks one: `exit 300` is
    reported as 44, and `_exit(-1)` is reported as 255.  So no number at all
    would have done the job this comment claimed for it.

What 125 IS for, therefore: it is nonzero, so a caller that only checks whether
the image answered sees that it did not, and it is the one value this tree
reserves for a refusal.  What it cannot do is tell a refusal apart from an
answer, and the diagnostic `_admitted` prints on stdout is the channel that
does.  A refusal that RETURNED a plausible number would be a fabricated answer
wearing a diagnostic's clothes; exiting is what makes the mistake impossible,
and the number only says which kind of failure it was.

`test_formal_admitted.py`'s `truth` group re-measures both halves — that a child
can exit 125, and that the OS masks a code above 255 — so the claim above cannot
rot back into the one it replaced.
"""

POLL_NOT_COLLECTED = -65
"""What `popen_poll` answers while the child is still running.

A CONSTANT of this model and not a fact about the host, which is why it is here
rather than in `popen_poll`'s `@admitted` text alone: a sentinel is a choice, and
a choice that lands inside the set of answers the host can give is a value the
caller cannot interpret.

`-1`, which this replaced, is exactly that.  CPython reports `-1` for a child
killed by `SIGHUP` — measured — so `-1` meant both "still running" and "died of
signal 1", and any proof about `poll`'s answer could not tell the two apart.

-65 is outside the whole answer set: the status of a child is `0..255` or `-N`
for a signal, and the largest signal number on this host is 31 (Linux's
`SIGRTMAX` is 64, so 65 is outside both).  The only way for a caller to see it is
for the model to have chosen it, which is the point of a sentinel.
"""

def _admitted(what: str) -> int:
    """Refuse to answer, naming the contract that would have to be trusted.

    The one place all twelve admissions share a body, and it is a function like
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

@admitted("the child's exit status word: 0..255 for a normal exit, or -N for a death by signal N")
def run(args, capture_output=0, text=0, timeout=0, check=0, input=0, cwd="",
        env="", stdout=0, stderr=0, stdin=0, shell=0, errors="") -> int:
    """`subprocess.run(argv, capture_output=…)`: run a program, wait, report.

    The return word is the exit status, which is what `run` is called for in
    every one of the 547 call sites in this tree.  `args` and the keywords are
    named after CPython's own parameters so that those calls BIND — see the
    module docstring for why that was the binding constraint and why no keyword
    here changes the admitted answer.  The model's own argument checking for the
    `capture_output`-beside-`stdout` rules is `validate_run`.

    Which is why they are declared rather than collected: a `**kwargs` is a
    run-time-length mapping (`bugs/FORMAL_listdir_no_run_time_sequence.md`), and
    12 named parameters that bind are the same program with a representation.

    The admitted status is the SIGNED one and CPython's return is not this word
    either: `run` hands back a `CompletedProcess`, and this path cannot, so what
    the caller gets here is the status `CompletedProcess.returncode` would have
    held.  `formal/admitted.py`'s generated docstring says that once for every
    contract rather than twelve times.
    """
    return _admitted("subprocess.run")

@admitted("the child's exit status word: 0..255 for a normal exit, or -N for a death by signal N; a non-zero status is returned rather than raised")
def call(args, timeout=0, cwd="", env="", shell=0) -> int:
    """`subprocess.call(argv)`: run a program and return its status.

    `run`'s sibling without the capture, and the reason the two are separate
    contracts rather than one is that their assumptions differ: `call` promises
    no exception for a failing child, so a file that only calls it is trusting
    strictly less.  It also has no `capture_output`, and CPython agrees: passing
    one to `call` is `Popen.__init__() got an unexpected keyword argument`.
    Both are about CPython's own behaviour, and both are what the admission
    states rather than what this file decides: `check_returncode` above is the
    decidable half, and this contract is the rest.
    """
    return _admitted("subprocess.call")

@admitted("CPython answers 0 when the child succeeded and raises CalledProcessError otherwise, so the status word is not one of the two answers it gives; the word below is the child's own status (0..255 for a normal exit, or -N for a death by signal N) and not a value CPython returns")
def check_call(args, cwd="", env="", shell=0) -> int:
    """`subprocess.check_call(argv)`: run a program, raise if it failed.

    The RAISE is the admitted part rather than the status: this path has no
    exception mechanism (FORMAL.md phase 7), so what is admitted is the fact that
    a non-zero status would raise, and `check_returncode` above is where the
    decidable half of that judgement lives.

    What CPython actually hands back is worth recording, because it is not what
    the admission used to say: `check_call` returns **0** on success and raises
    otherwise.  Measured on CPython 3.14 — the `return 0` is in
    `subprocess.py`'s own `check_call` — so the word this model declares is a
    status the host never gives through this function, and the `@admitted` text
    says so.  A proof concluding `check_call(p) = n` for the child's `n` would
    be reading a claim CPython does not make, and one concluding it for CPython's
    `0` would be reading a claim this model does not make; the honest admission
    names both.  There is no `timeout` parameter
    because CPython's `check_call` has none — it forwards everything to `Popen` —
    and a parameter CPython does not have is a call this module would accept and
    CPython would not.
    """
    return _admitted("subprocess.check_call")

@admitted("the child's output on stdout up to the first NUL byte, because a str on this path is a NUL-terminated char *; CPython's own answer is the whole byte string and may contain NULs")
def check_output(args, timeout=0, input=0, stderr=0, text=0, errors="",
                 cwd="", env="") -> str:
    """`subprocess.check_output(argv)`: run a program and return its stdout.

    Returns a `str` and not bytes because a `char *` is what this path has, and
    that has a consequence the contract now STATES rather than leaves implicit: a
    NUL-terminated word cannot carry the NUL bytes CPython's answer really
    contains.  `check_output(["/bin/sh","-c","printf 'a\\0b'"])` is three bytes
    in CPython; a word on this path can hold two characters and the terminator.
    The earlier admission said "an arbitrary byte string", which is true of the
    host and false of the model — an admission this file could not honour.

    No `stdout` and no `check` parameter, and their absence is the model's
    `ARG_STDOUT_NOT_ALLOWED`/`ARG_CHECK_NOT_ALLOWED`: CPython refuses both
    outright because it passes them itself.
    """
    return _admitted("subprocess.check_output")

@admitted("the child's output on stdout up to the first NUL byte, because a str on this path is a NUL-terminated char *; CPython's own answer is the whole byte string and may contain NULs")
def getoutput(cmd, encoding="", errors="") -> str:
    """`subprocess.getoutput(cmd)`: run a shell command line, return its output."""
    return _admitted("subprocess.getoutput")

@admitted("the shell command's exit status word: 0..255 for a normal exit, or -N if the shell itself was killed by signal N; the output is not carried in this word")
def getstatusoutput(cmd, encoding="", errors="") -> int:
    """`subprocess.getstatusoutput(cmd)`: run a command line, return `(status, output)`.

    Two values in CPython and one word here, so what the word is has to be
    chosen rather than left: the STATUS, with the output not carried.  A caller
    that needs the output calls `getoutput`.  Which half to keep is stated in the
    admission above, so the choice is visible rather than a reader having to
    infer it from the signature.
    """
    return _admitted("subprocess.getstatusoutput")

@admitted("the child's process id, a positive integer")
def Popen(args, bufsize=0, stdin=0, stdout=0, stderr=0, shell=0, cwd="",
          env="", text=0, start_new_session=0, pass_fds=0, errors="",
          preexec_fn=0) -> int:
    """`subprocess.Popen(argv)`: start a program and hand back its handle.

    **The returned word IS the process id**, so `.pid` needs no second call and
    `popen_*` below take this value unchanged.  CPython's `Popen` returns an
    object; a function returning one word is the honest shape for a handle on
    this path, and the process id is the only part of that handle which is a word
    at all.

    The keywords are CPython's, so the 18 `Popen` call sites in this tree bind.
    None of them is read, for the reason the module docstring gives: they select
    which host operations CPython would perform and this model performs none.
    `preexec_fn` is a CALLABLE, which is not a word either, and is named only so
    that `tools/procrun.py`'s one use of it binds.
    """
    return _admitted("subprocess.Popen")

@admitted("the child's exit status word: 0..255 for a normal exit, or -N for a death by signal N")
def popen_wait(handle, timeout=0) -> int:
    """`Popen(argv).wait(timeout=…)`: wait for the child and report its status."""
    return _admitted("Popen.wait")

@admitted("the child's exit status word once it is known (0..255 for a normal exit, or -N for a death by signal N), or -65 while the child is still running; CPython answers None there")
def popen_poll(handle) -> int:
    """`Popen(argv).poll()`: the status if it is known, `-65` while it is not.

    A separate contract from `popen_wait` and not a second spelling of it,
    because the two answer different questions and one of them has a second
    answer: `wait` blocks until there is a status, `poll` says there is not one
    yet.  That is why the sentinel is in THIS admission and not in `wait`'s.

    `-65` and not the `-1` this used to say: CPython reports `-1` for a child
    killed by `SIGHUP`, so `-1` was simultaneously "still running" and "died of
    signal 1", and a caller could not tell which.  `POLL_NOT_COLLECTED` above is
    the constant and carries the argument.
    """
    return _admitted("Popen.poll")

@admitted("the signal reaches the child this handle names while that child is still running; once the child has been collected CPython sends nothing and raises no exception")
def popen_kill(handle) -> int:
    """`Popen(argv).kill()`: stop the child.

    The contract is about delivery and not about the outcome: whether the child
    then stops is a fact about the child, and nothing about this word says so.
    `popen_terminate` is a separate contract because it is a separate operation
    with its own default signal, and a file that trusts one is not trusting the
    other.

    "Delivery" is bounded by the child still running, and that bound was found by
    measurement rather than assumed: `Popen.send_signal` calls `poll()` and
    RETURNS if the child has already been collected, so `kill()` on a child this
    process has waited for sends nothing and raises nothing at all.  An admission
    about delivery with no bound claimed a signal arrives for a child that has
    been dead for an hour.
    """
    return _admitted("Popen.kill")

@admitted("the signal reaches the child this handle names while that child is still running; once the child has been collected CPython sends nothing and raises no exception")
def popen_terminate(handle) -> int:
    """`Popen(argv).terminate()`: ask the child to stop."""
    return _admitted("Popen.terminate")

@admitted("the child's output on stdout and stderr, concatenated and truncated at the first NUL byte because a str on this path is a NUL-terminated char *; CPython's own answer is a pair of byte strings that may contain NULs")
def popen_communicate(handle, input=0, timeout=0) -> str:
    """`Popen(argv).communicate(input=…, timeout=…)`: write, close, read.

    Two values in CPython — `(stdout, stderr)` — and one word here, so the word
    is the CONCATENATION and not either half: a caller that needs them apart has
    no word to put them in, and a word that claimed to be one of the two would be
    a value this file chose.  The contract says "stdout and stderr" for that
    reason and not "stdout".  It also says where the concatenation stops, because
    a `char *` stops at the first NUL and `communicate`'s own answer does not.
    """
    return _admitted("Popen.communicate")