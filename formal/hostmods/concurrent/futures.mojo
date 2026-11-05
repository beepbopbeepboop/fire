"""`concurrent.futures` — the Future's shape, with the POOL admitted.

A thread is an object this image does not have.  `formal/imports.py`'s rule for
what "unreachable" means names it first -- "a second process, a thread, a socket,
a dynamic loader for foreign code, an embedded CPython, a terminal" -- and the
answer it gets from a formal image linking libSystem and nothing else is no.
`ThreadPoolExecutor` therefore cannot be built here: not because the CALL is hard,
but because there is nothing to call.

WHAT IS DECIDED HERE, AND IT IS THE INTERESTING HALF
-----------------------------------------------------
`Future` is a box with a status, a value, an exception and a set of callbacks, and
this path CAN represent a status word and a value word.  So what is here is
`Future`'s state machine as arithmetic over one word -- `PENDING`, `RUNNING`,
`CANCELLED`, `CANCELLED_AND_NOTIFIED`, `FINISHED` are CPython's five, and
`future_state_after_submit` / `future_state_after_set_result` /
`future_state_after_cancel` are the three transitions between them that are
functions of the state alone.  `test_formal_admitted.py` drives the same table
through CPython's own `Future` and requires the same verdict, so the model is
checked against the real object rather than against a table written here.

`done()`, `running()`, `cancelled()` and `result()` are then one comparison each,
and they are the calls the thirteen files in this tree actually make on a Future
they did not create.

WHAT IS ADMITTED, AND WHY IT IS EXACTLY TWO CALLS
--------------------------------------------------
  * `executor_submit` — submitting a callable to a pool.  The callable is a
    Python function object, which is a thing this path cannot name
    (`bugs/FORMAL_module_state_no_storage.md`), and the pool is a set of threads,
    which is a thing this image does not have.
  * `executor_shutdown` — joining the pool's threads.

TWO and not one because they are different facts about the host: submitting says
a thread would run the callable, and shutting down says threads would stop.  A
file that only shuts a pool down trusts strictly less than one that submits to it,
and the `trust:` line says which.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `Future` as a CLASS.  A `concurrent.futures.Future` is a Python object with a
    `_condition` (a `threading.Condition`, i.e. a lock and a deque), a `_state`
    and a list of callbacks; the formal front end's only class-to-fields transform
    is `formal/dataclass_transform.py`, and a class whose fields come from a base
    class it does not know is refused.  What is here is the STATE, which is the
    part that is arithmetic and the part a caller can ask about.
  * `wait()`, `as_completed()`, `FIRST_COMPLETED`, `FIRST_EXCEPTION`,
    `ALL_COMPLETED`, `CancelledError`, `TimeoutError`, `Executor.map` and
    `ProcessPoolExecutor`'s distinct `BrokenProcessPool`.  `FIRST_COMPLETED` and
    `ALL_COMPLETED` are two CONSTANTS and could be here; they are absent because
    nothing in this tree reads them and `formal/hostmods/io.mojo`'s rule -- a
    number is here when a caller needs it, checked rather than assumed -- applies.
    The rest need the objects above.
  * `threading` itself is a separate module
    (`formal/hostmods/threading.mojo`), because a file importing `threading` must
    not be made to resolve `concurrent.futures` to get it, and a module reached
    through two names is two dylibs of the same source.
"""

# CPython's five `Future` states.  Read off CPython rather than invented, and
# `test_formal_admitted.py` checks each against `Future._state` on a live object
# driven through its own transitions.
FUTURE_PENDING = 0
FUTURE_RUNNING = 1
FUTURE_CANCELLED = 2
FUTURE_CANCELLED_AND_NOTIFIED = 3
FUTURE_FINISHED = 4

ARG_OK = 0

def future_state_after_submit(state: int) -> int:
    """A pending Future's state once a worker has picked its callable up.

    CPython's `Future.set_running_or_notify_cancel`, which is the transition a
    POOL performs and the only one this model can decide -- it is a function of the
    state alone.  `FINISHED` is passed through because CPython raises there rather
    than transitioning, and a model that quietly returned `RUNNING` for a finished
    Future would be a wrong answer in the direction nobody would notice.
    """
    if state == FUTURE_CANCELLED:
        return FUTURE_CANCELLED
    if state == FUTURE_CANCELLED_AND_NOTIFIED:
        return FUTURE_CANCELLED
    if state == FUTURE_FINISHED:
        return FUTURE_FINISHED
    return FUTURE_RUNNING

def future_state_after_set_result(state: int) -> int:
    """A Future's state once its callable has returned: `FINISHED`.

    The one transition every state agrees on, which is what makes it a model of
    the object rather than a table: CPython's `set_result` is legal from
    `PENDING`, `RUNNING` and (with the internal flag) `CANCELLED_AND_NOTIFIED`,
    and lands on `FINISHED` from all of them.
    """
    return FUTURE_FINISHED

def future_state_after_cancel(state: int) -> int:
    """A Future's state after `cancel()`: cancelled, or unchanged if it had run.

    CPython's rule, and the part that is arithmetic rather than a lookup: a
    Future that is already `RUNNING` or `FINISHED` cannot be cancelled and stays
    where it was, while a `PENDING` one becomes `CANCELLED` and the internal
    `_notify_condition` path becomes `CANCELLED_AND_NOTIFIED`.
    """
    if state == FUTURE_PENDING:
        return FUTURE_CANCELLED
    return state

def future_done(state: int) -> int:
    """`Future.done()`: 1 when the Future will never run again."""
    if state == FUTURE_FINISHED:
        return 1
    if state == FUTURE_CANCELLED:
        return 1
    return 0

def future_running(state: int) -> int:
    """`Future.running()`: 1 only in `RUNNING`."""
    if state == FUTURE_RUNNING:
        return 1
    return 0

def future_cancelled(state: int) -> int:
    """`Future.cancelled()`: 1 for either cancelled state.

    Both of them, and that is CPython's own rule rather than a simplification:
    `cancelled()` is true for `CANCELLED` AND for `CANCELLED_AND_NOTIFIED`, and
    treating the second as not-cancelled is a bug that appears only in the race
    `CANCELLED_AND_NOTIFIED` exists to name.
    """
    if state == FUTURE_CANCELLED:
        return 1
    if state == FUTURE_CANCELLED_AND_NOTIFIED:
        return 1
    return 0


# ── the admitted half ────────────────────────────────────────────────────────

ADMITTED_EXIT_STATUS = 125
"""The status an admitted call exits with; `formal/hostmods/subprocess.mojo` says why,
and corrects the reason: 125 is INSIDE 0..255, and no exit code can be outside
it, so this is a RESERVED nonzero status and the diagnostic is what says
"refused"."""

def _admitted(what: str) -> int:
    """Refuse to answer, naming the contract that would have to be trusted."""
    printf("concurrent.futures: %s is an ADMITTED contract on this target\n", what)
    printf("concurrent.futures: a pool is a set of threads, and this image has\n")
    printf("concurrent.futures: none: it links libSystem and nothing else.\n")
    exit(ADMITTED_EXIT_STATUS)
    return 0

@admitted("the submitted callable runs on some thread of this process or in some process of this machine; the two executors differ in which, and this model merges them, and its result is one word; nothing is assumed about which or when")
def executor_submit(callable_word: int) -> int:
    """`ThreadPoolExecutor.submit(fn, …)` / `ProcessPoolExecutor.submit(fn, …)`.

    ONE call for both executors, and the reason is that their difference is
    invisible here: a `ThreadPoolExecutor` runs its callables on threads of THIS
    process and a `ProcessPoolExecutor` on processes of this machine, and this
    image has neither, so the two would be the same admitted contract and writing
    it twice would be two declarations of one assumption.  Which of the two a
    caller wanted is a fact about the caller's intent, not about the host.

    The parameter is the CALLABLE as a word.  A Python function is an object with
    a code pointer, a closure cell and a globals dictionary
    (`bugs/FORMAL_module_state_no_storage.md`), so what crosses here is the
    ADDRESS, and the contract says the answer is one word without saying anything
    about what running that address computes.

    "Runs on some THREAD" is the model's merger and the admission now says so,
    because the admission used to say it as if it were CPython's: a
    `ProcessPoolExecutor` runs its callables in another PROCESS, so a caller who
    meant that executor is trusting something the old text did not say it was
    trusting.
    """
    return _admitted("concurrent.futures.Executor.submit")

@admitted("every thread the pool's OWN workers started has stopped by the time this returns; a thread a submitted callable started itself is not one of them")
def executor_shutdown(pool: int) -> int:
    """`Executor.shutdown(wait=True)`: stop the pool and, with `wait`, join it.

    The trust is smaller than `submit`'s and that is the point of a separate
    contract: joining threads says the pool is QUIESCENT, which a caller can
    check by observing its own program's output afterwards, and it says nothing
    about whether any callable ever ran.  One contract for both would make a file
    that only tears a pool down read as trusting as much as one that submits work
    to it.

    QUIESCENT means the pool's OWN workers, and the word "own" is in the
    admission because the audit found the wider reading false: a submitted
    callable that started its own `threading.Thread` had that thread still
    running when `Executor.shutdown(wait=True)` returned, because the pool joins
    its workers and nothing else.  "Every thread the pool started" was true on
    the narrow reading and false on the one a caller would assume, and a contract
    that is only true under its narrowest reading is a trap.
    """
    return _admitted("concurrent.futures.Executor.shutdown")
