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
stating rather than assuming.  `TIMEOUT_MAX` is the one, and its value is a
PLATFORM fact that this file's first version got wrong -- see
`TIMEOUT_MAX()` below, which records what the mistake was and what the number
actually is.  The lock's own `locked()` state is one bit, and `validate_timeout`
is the two-error check over one word, which is the same "arithmetic over a word"
that `formal/hostmods/concurrent/futures.mojo` does for `Future`'s five states.

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
TIMEOUT_MAX_VALUE = 9223372036

ARG_OK = 0
ARG_BAD_TIMEOUT = 1
ARG_TIMEOUT_OVERFLOW = 2

def TIMEOUT_MAX() -> int:
    """`threading.TIMEOUT_MAX`: 9223372036 — the largest timeout the clock takes.

    THIS FILE GOT IT WRONG FIRST, and the value it had was the interesting part:
    9223372036854775807, the largest signed 64-bit integer.  That is what the
    name suggests and it is what the first version of this function returned, and
    `test_formal_admitted.py`'s `threading` group failed on it immediately:
    CPython's own answer on this target is `9223372036.0` -- a FLOAT, and a
    completely different number.

    The reason is that it is not an integer limit at all.  `threading.TIMEOUT_MAX`
    is `_thread.TIMEOUT_MAX`, which is the largest value the platform's clock can
    turn into a deadline; on this build that is `time_t`'s range in
    milliseconds, and 2^63-1 milliseconds is about 292 million years, which is
    not a number any clock represents.  So a value written from the shape of the
    NAME is wrong here, which is the whole argument for the differential test and
    the whole reason this constant is checked against CPython rather than
    reasoned about.

    The float is not an accident either, and the model keeps the INTEGER: a value
    on this path is one 64-bit integer word, and `9223372036` and `9223372036.0`
    are the same deadline.  `test_formal_admitted.py` compares `int(...)` for that
    reason and says so.
    """
    return TIMEOUT_MAX_VALUE

def validate_timeout(timeout: int) -> int:
    """`Lock.acquire(timeout=…)`'s own check: `ARG_OK`, or which of TWO errors.

    Measured on this tree's CPython 3.14.6, over the values that matter:

        timeout=-1        -> OK            (block forever: the DEFAULT)
        timeout=0         -> OK            (do not block)
        timeout=-2        -> ValueError: timeout value must be a non-negative number
        timeout=9223372036 -> OK           (exactly TIMEOUT_MAX)
        timeout=9223372037 -> OverflowError: timestamp out of range for C PyTime_t

    Three rules and not two, and the first of them is the one this file got wrong
    by writing `if timeout < 0`: **-1 IS VALID.**  It is `Lock.acquire`'s own
    default and it means "block indefinitely", so a check that refuses every
    negative number refuses the value CPython itself passes when the caller writes
    `acquire()`.  Two errors and one function because both are decided by
    comparing one word against a bound; the negative one is decided first because
    CPython's order is, and a caller that gets `ARG_BAD_TIMEOUT` for
    `TIMEOUT_MAX + 1` is told the wrong thing.
    """
    if timeout < -1:
        return ARG_BAD_TIMEOUT
    if timeout > TIMEOUT_MAX_VALUE:
        return ARG_TIMEOUT_OVERFLOW
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
"""The status an admitted call exits with; `formal/hostmods/subprocess.mojo` says why,
and the measurement that corrected its reason is there too: 125 is INSIDE 0..255 and
no exit code can be outside it, so this is a RESERVED nonzero status and the
diagnostic on stdout is the channel that says "refused", not the number."""

def _admitted(what: str) -> int:
    """Refuse to answer, naming the contract that would have to be trusted."""
    printf("threading: %s is an ADMITTED contract on this target\n", what)
    printf("threading: a thread is an object this image does not have: it links\n")
    printf("threading: libSystem and nothing else, and gets no pthread_create.\n")
    exit(ADMITTED_EXIT_STATUS)
    return 0

@admitted("the thread exists and has BEGUN running the target callable, and nothing is assumed about what the callable computed or when it finishes")
def thread_start(target: int) -> int:
    """`Thread(target=fn).start()`: begin running `fn` on a second thread.

    The parameter is the callable as a word, for the reason
    `formal/hostmods/concurrent/futures.mojo`'s `executor_submit` gives: a Python
    function is an object, and a value on this path is one 64-bit word.

    Starting a thread is a DIFFERENT admission from joining one and it is a
    separate contract for that reason: "a thread will run this" and "that thread
    has stopped" are independent facts, and a program that only joins a thread it
    did not start trusts less than one that does both.

    "Has BEGUN running" is the whole content of the admission, and the word was
    put there by measurement: `Thread.start()` returns once `Thread._bootstrap`
    has set its `_started` event, which happens BEFORE `run()` is entered, so a
    callable that sleeps for a second is still running when `start()` returns.
    The admission this replaced said the thread "has run the target callable",
    which is true under one reading and false under the other, and a claim that is
    true or false depending on which reading a proof happens to use is not a claim.
    """
    return _admitted("threading.Thread.start")

@admitted("the thread has stopped, for a join with no timeout; nothing is assumed about what it computed")
def thread_join(target: int) -> int:
    """`Thread.join()`: wait for the thread to finish."""
    return _admitted("threading.Thread.join")

@admitted("the lock is a per-object mutual exclusion inside THIS process: CPython's threading.Lock is a userspace semaphore that names no descriptor, and fcntl.flock on any descriptor neither waits for it nor is waited on by it")
def lock_acquire(fd: int) -> int:
    """`Lock.acquire()`: take the lock, blocking until it is available.

    It goes through `fcntl`'s `flock` rather than carrying its own, and the reason
    is a duplication this project does not permit: two modules that both take a
    kernel lock must go through ONE function, or a fix to how the lock is spelled
    has to be made twice and the two copies can disagree about what the lock is.

    What the admission does NOT say any more, because it was false and the audit
    measured it: it used to claim "the lock is held by the kernel on a
    descriptor".  CPython's `threading.Lock` is a `_thread.lock` — a userspace
    semaphore with no `fileno`, no `_handle` and no descriptor of any kind — and
    it does not interact with `fcntl.flock` at all: a child process took
    `LOCK_EX` on a file while this process held a `threading.Lock` over the same
    file's directory, and got it.  A lock the caller can also take from outside
    the process is not the lock `Lock.acquire` takes, and the admission now says
    which one it is.

    Two parameters in CPython's `acquire(blocking=True, timeout=-1)` and ONE
    here, and both words of that are settled by `formal/hostmods/fcntl.mojo`:
    `validate_timeout` decides the timeout, and this image has no other thread to
    block on, so `blocking` has nothing to block against.
    """
    return _admitted("threading.Lock.acquire")
