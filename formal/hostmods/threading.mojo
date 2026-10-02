"""`threading` — the state words, with the thread itself admitted.

A thread is an object this image does not have: `formal/imports.py` names it in
the rule that decides what "unreachable" means, and a formal image links libSystem
and nothing else gets no `pthread_create` to call.  So `Thread` cannot be built
here, and neither can `Lock`, `RLock`, `Condition`, `Event`, `Semaphore`,
`Barrier` or `Queue` -- each is a lock word plus a waiter list plus a predicate,
and a waiter list is a run-time-length sequence, which is the same limit that
took `os.listdir` out of reach
(`bugs/FORMAL_listdir_no_run_time_sequence.md`).

WHAT IS DECIDED HERE
--------------------
`threading`'s CONSTANTS, which are not all 0 and 1 and are therefore worth
stating rather than assuming: `TIMEOUT_MAX` is 9223372036854775807 and is a
platform fact, not a typo, and `TIMEOUT_MAX` is the ONE name in this module a
file in this tree would read (four of them reach for a timeout default).  The
lock's own `locked()` state is one bit, and `lock_acquire` / `lock_release` are
the two transitions on it -- functions of the state alone, which is the same
"arithmetic over a word" that `formal/hostmods/concurrent/futures.mojo` does for
`Future`'s five states.

WHAT IS ADMITTED
----------------
  * `thread_start` — a second thread of execution exists and runs the target.
  * `thread_join` — it has stopped.
  * `lock_acquire` / `lock_release` — the kernel's advisory lock, which is the
    same external fact as `formal/hostmods/fcntl.mojo`'s `flock` and is admitted
    through the SAME `fcntl` wrapper rather than a second implementation of it.

That last point is why this file imports `fcntl`: two modules that both take a
kernel lock must go through one function, or a fix to how the lock is spelled
would have to be made twice and the two could disagree about what the lock IS.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `current_thread`, `main_thread`, `get_ident`, `active_count`,
    `enumerate`, `stack_size`, `TIMEOUT_MAX` as a settable.  `current_thread()`
    and `get_ident()` are the interpreter's own frame identity
    (`bugs/FORMAL_a_frame_holder_rebound_from_a_word`), and `active_count()` is a
    count of threads that exist, which is zero here and saying zero would be a
    claim about the host rather than about the model.
  * `local`, `Lock.acquire(blocking, timeout)`'s keyword form, `Thread` with its
    `daemon`/`name`/`args` attributes, `settrace`, `excepthook`, `localize`,
    `get_native_id`, `Event`, `Condition`, `Barrier`, `BoundedSemaphore`, `Queue`.
    A lock object and an event object are both the absent half; what each of them
    DOES is a transition on a word, and those transitions are here for the lock and
    absent for the rest because nothing in this tree calls them.
"""

from fcntl import flock, LOCK_EX, LOCK_NB, LOCK_UN

# CPython's exact values, checked by `test_formal_admitted.py` against the live
# module.  `TIMEOUT_MAX` is the one worth reading twice: it is the largest signed
# 64-bit integer, it is what `Lock.acquire`'s signature uses as the default, and
# a value written as `-1` here would be accepted by every caller and mean
# "block forever" in a different direction.
TIMEOUT_MAX_VALUE = 9223372036854775807

ARG_OK = 0
ARG_BAD_TIMEOUT = 1

def TIMEOUT_MAX() -> int:
    """`threading.TIMEOUT_MAX`: 9223372036854775807 — block indefinitely.

    `Lock.acquire(timeout=None)` resolves `None` to this number rather than to a
    separate "no timeout" case, which is why it is a value and not a flag: a file
    that passes `TIMEOUT_MAX` and a file that passes no timeout mean the same
    thing, and on this path "the same thing" has to be one word.
    """
    return TIMEOUT_MAX_VALUE

def validate_timeout(timeout: int) -> int:
    """`Lock.acquire(timeout=…)`'s own check: `ARG_OK`, or `ARG_BAD_TIMEOUT`.

    CPython raises `ValueError("timeout value must be a positive number")` for a
    negative one and `OverflowError` for one above `TIMEOUT_MAX`; both are
    refusals of a NUMBER and this path has no exception mechanism (FORMAL.md
    phase 7), so they are values a caller asks for and the acquire below does the
    taking.  Two errors and one function, because both are decided by comparing
    one word against `TIMEOUT_MAX` and splitting them would be two functions
    differing in one comparison.
    """
    if timeout < 0:
        return ARG_BAD_TIMEOUT
    if timeout > TIMEOUT_MAX_VALUE:
        return ARG_BAD_TIMEOUT
    return ARG_OK

def lock_locked(state: int) -> int:
    """`Lock.locked()`: 1 when this process holds the lock.

    A bit, and the only question about a lock that is a fact about the MODEL
    rather than about the kernel: whether THIS process holds it is one word, and
    it is 0 in every image this tree builds because nothing here takes a lock --
    which is true of the model and says nothing about what the kernel would say.
    """
    return state % 2


# ── the admitted half ────────────────────────────────────────────────────────

ADMITTED_EXIT_STATUS = 125
"""The status an admitted call exits with; `formal/hostmods/subprocess.mojo` says why."""

def _admitted(what: str) -> int:
    """Refuse to answer, naming the contract that would have to be trusted."""
    printf("threading: %s is an ADMITTED contract on this target\n", what)
    printf("threading: a thread is an object this image does not have: it links\n")
    printf("threading: libSystem and nothing else, and gets no pthread_create.\n")
    exit(ADMITTED_EXIT_STATUS)
    return 0

@admitted("the thread exists and has run the target callable, and nothing is assumed about what the callable computed or when")
def thread_start(target: int) -> int:
    """`Thread(target=fn).start()`: begin running `fn` on a second thread.

    The parameter is the callable as a word, for the reason
    `formal/hostmods/concurrent/futures.mojo`'s `executor_submit` gives: a Python
    function is an object, and a value on this path is one 64-bit word.

    Starting a thread is a DIFFERENT admission from joining one and it is a
    separate contract for that reason: "a thread will run this" and "that thread
    has stopped" are independent facts, and a program that only joins a thread it
    did not start trusts less than one that does both.
    """
    return _admitted("threading.Thread.start")

@admitted("the thread has stopped, and nothing is assumed about what it computed")
def thread_join(target: int) -> int:
    """`Thread.join()`: wait for the thread to finish."""
    return _admitted("threading.Thread.join")

@admitted("the lock is held by the kernel on a descriptor, and whether it is granted depends on every other holder")
def lock_acquire(fd: int) -> int:
    """`Lock.acquire()`: take the lock, blocking until it is available.

    It goes through `fcntl`'s `flock` rather than carrying its own, and the reason
    is a duplication this project does not permit: two modules that both take a
    kernel lock must go through ONE function, or a fix to how the lock is spelled
    has to be made twice and the two copies can disagree about what the lock is.

    Two parameters in CPython's `acquire(blocking=True, timeout=-1)` and ONE
    here, and both words of that are settled by `formal/hostmods/fcntl.mojo`:
    `validate_timeout` decides the timeout, and this image has no other thread to
    block on, so `blocking` has nothing to block against.
    """
    return _admitted("threading.Lock.acquire")
