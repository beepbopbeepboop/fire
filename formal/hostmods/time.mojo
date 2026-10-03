"""`time` — clocks and sleeping, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import time` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` in `formal/imports.py` for
why these did NOT go at the repository root, where the first three of them
captured `import os` in the compiler's own sources.

What CPython's `time` is, restricted to what a freestanding arm64 image that
links libSystem and nothing else can be asked for. The restrictions are
stated once, here, because three of them are properties of the VALUE MODEL
rather than of this module, and every function below is shaped by them.

  * BOTH BACKENDS TODAY, for the reason `formal/hostmods/os/__init__.mojo` gives
    at length: a module dylib that calls into the C library builds and RUNS
    under `--backend=x86_64` too, and the claim this replaces was false. Every
    function here needs the C library, so what the x86-64 backend has to get
    right is the symbol each call binds — and for `localtime`/`strftime`, whose
    answer is a `struct tm` this target fills in, that is the same
    dual-spelling table `formal/model.py`'s `target_libc_symbol` is. A host
    with no x86-64 support at all still skips the x86-64 half of
    `test_formal_time.py`.

  * A FLOAT IS NOT A FLOAT. `formal/arm64_codegen.py`'s `FloatLiteral` arm
    says it: *"formal is int-only; truncate toward zero (matches C cast)"*,
    and a `Float64` local is a 64-bit word like any other. So
    `time.time()` cannot return CPython's float: there is no fractional value
    in the model, and `0.5` in a source file is the integer 0. What CAN cross
    is the IEEE-754 BIT PATTERN of a double, and `printf("%.6f", bits)` prints
    it exactly on BOTH architectures — measured, and pinned in
    `test_formal_time.py`, whose `--backend` flag is what makes the x86-64 half
    of that claim a thing the suite can run at all (there was no way to ask it
    before, which is how an arm64-only measurement came to be written down as a
    property of both). On x86-64 that needs the floating conversion placed in
    `XMM0` rather than read out of the integer register the word is in;
    `formal/model.py`'s `printf_argument_classes` is the reader and
    `formal/x86_64.py`'s `encode_movq_xmm_rm64` is the move. What is still
    absent, and for a different reason, is every function whose CPython answer
    is a float VALUE rather than a double rendered by a variadic call: a
    non-variadic `double` parameter says what it wants in a prototype, and a
    freestanding image has no header to read it from. So
    `time_seconds_bits()` below returns that pattern and the module's own
    docstrings say what to do with it. Every function whose CPython answer is
    a float therefore has BOTH a `_bits` form (faithful, this target's
    representation) and an integer `_ns` form (the same clock, in nanoseconds,
    which is the unit a program can actually do arithmetic on here).

  * NO STRUCT CROSSES. `localtime`, `gmtime`, `mktime`, `strftime` and
    `get_clock_info` all answer with a `struct tm` or a named tuple, and a
    struct is a frame blob (see `os/_syscalls.mojo`'s note on `stat`), so
    there is no representation for them. They are absent, each named in
    `bugs/FORMAL_time_struct_shaped_answers.md` with the measurement, rather
    than answered with a plausible number.

  * NO EXCEPTIONS. `time.sleep` on a negative argument raises `ValueError` in
    CPython; here it returns having slept zero seconds, and says so. There is
    no `try`/`except` on this path (FORMAL.md phase 7).

  * A CONSTANT IS A CALL. `CLOCK_REALTIME` is a module-level name, and a
    module-level name is not exported as a word across a dylib boundary —
    there is no storage for one, because every value a formal program can name
    lives in a function's own stack scratch
    (`bugs/FORMAL_module_state_no_storage.md`). So each is a zero-argument
    function and `time.CLOCK_REALTIME` is spelled `CLOCK_REALTIME()`. This is
    the same rule `os` follows for `os.sep`, and the same reason.

  * NO FUNCTION HERE HAS A DEFAULT ARGUMENT. A call into another image does
    not materialize the callee's defaults: the caller has no signature to read
    them from, so the argument register is whatever the caller last left in it.
    Measured: `need_two(1)` returns 511 in one image and 1867609072 across a
    dylib (`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`). So
    the parameters CPython gives defaults are REQUIRED here, and the one place
    a default is genuinely wanted is a SECOND function of its own.

WHAT IS HERE, AND WHY IT IS THE RIGHT SUBSET
--------------------------------------------
CPython's `time` is 30-odd names. What is below is the part a freestanding
image can answer truthfully: the five clocks, both units of each, `sleep`, and
the `CLOCK_*` constants. The three clocks with no analogue here —
`CLOCK_BOOTTIME`, and the `perf_counter` distinction — are handled at their
definitions. `test_formal_time.py` checks every one of them against CPython's
own answer, and checks the ABSENT ones by asserting the build refuses with a
message that names the missing capability.
"""


# ── the clock constants ─────────────────────────────────────────────────────
#
# Darwin's numbers, from `<time.h>`: 0 is REALTIME, 1 is MONOTONIC_RAW... but
# Apple numbers MONOTONIC as 6 and gives MONOTONIC_RAW as 4, which is what
# `clock_gettime_nsec_np` below is called with and what this tree's own
# `std/time/time.mojo` uses (`_CLOCK_MONOTONIC = 1 if is_linux() else 6`).
# CPU-time ids are 12 (process) and 16 (thread) here and 2/3 on Linux, for the
# same reason. `CLOCK_MONOTONIC_RAW` is 4 on both, and Darwin's 4 does not
# advance while the machine is asleep, so it is NOT a synonym for
# `monotonic()` here — see `CLOCK_MONOTONIC_RAW()`'s own docstring.

def CLOCK_REALTIME() -> int:
    """`time.CLOCK_REALTIME`: 0. The wall clock, which step adjustments move."""
    return 0

def CLOCK_MONOTONIC() -> int:
    """`time.CLOCK_MONOTONIC`: 6 on Darwin. Counts while the machine sleeps."""
    return 6

def CLOCK_MONOTONIC_RAW() -> int:
    """`time.CLOCK_MONOTONIC_RAW`: 4. Does NOT count time spent asleep.

    Named because the name is a claim about a specific clock, and this one
    really is the raw counter. `monotonic()` is 6, which does count sleep.
    """
    return 4

def CLOCK_PROCESS_CPUTIME_ID() -> int:
    """`time.CLOCK_PROCESS_CPUTIME_ID`: 12 on Darwin, 2 on Linux."""
    return 12

def CLOCK_THREAD_CPUTIME_ID() -> int:
    """`time.CLOCK_THREAD_CPUTIME_ID`: 16 on Darwin, 3 on Linux."""
    return 16

def CLOCK_MONOTONIC_RAW_ALIAS() -> int:
    """NOT part of CPython's `time`. Present so a program that wants the raw
    counter can spell it without a magic number; see `CLOCK_MONOTONIC_RAW`."""
    return 4


# ── the wall clock ──────────────────────────────────────────────────────────

def time_seconds_bits() -> int:
    """`time.time()`, as the IEEE-754 bit pattern of a `double`.

    NOT a number to do arithmetic with — a 64-bit word that means something
    only if it is given to a `printf` with a `%f`/`%g`/`%e` conversion, which
    is exactly what the module docstring says to do with it. For arithmetic
    there is `time_seconds_ns()`.

    Built from `clock_gettime_nsec_np(CLOCK_REALTIME)` rather than `time(2)`,
    because `time(2)` is a `time_t` — whole seconds, with the nanoseconds
    discarded by the kernel's own conversion — and a `time.time()` that lost
    its fractional part would be a different function wearing its name.
    """
    return ns_to_double_bits(time_ns())

def time_ns() -> int:
    """`time.time_ns()`: nanoseconds since the epoch, as an integer.

    The form to use on this target. The value is `time.time()`'s value
    multiplied by 1e9 and rounded to a whole nanosecond, which is the
    resolution the underlying counter reports; it is not a derived quantity
    and there is no float in its construction.
    """
    return clock_gettime_nsec_np(0)

def time_seconds() -> int:
    """`time.time()` TRUNCATED to whole seconds. See the module docstring.

    Provided because a program that only needs "roughly when is it" is common
    and a truncating answer is a real answer to that question. It is NOT
    `time.time()`: it is that function's value with the fraction removed, and
    the nanosecond form is exact where this is not.
    """
    return clock_gettime_nsec_np(0) / 1000000000


# ── the monotonic clock ─────────────────────────────────────────────────────

def monotonic_ns() -> int:
    """`time.monotonic_ns()`: nanoseconds since an unspecified fixed point.

    The base is the same one `mach_absolute_time` uses, so it is the boot-relative
    counter; CPython's is too, and the two agree to the nanosecond modulo
    whatever elapsed between the two readings.
    """
    return clock_gettime_nsec_np(6)

def monotonic() -> int:
    """`time.monotonic_ns() / 1e9`, TRUNCATED to whole seconds."""
    return clock_gettime_nsec_np(6) / 1000000000

def perf_counter_ns() -> int:
    """`time.perf_counter_ns()`.

    CPython's `perf_counter` is documented as "the value of
    `time.perf_counter()` … with the highest available resolution to measure a
    short duration", and on macOS it is implemented over exactly the clock
    `CLOCK_MONOTONIC` names — `mach_absolute_time`, the same counter
    `monotonic` reads. There is no second, finer performance counter on this
    target to prefer, so the two are the same number here, and saying so is
    more useful than inventing a difference. Measured against CPython in
    `test_formal_time.py`.
    """
    return clock_gettime_nsec_np(6)

def perf_counter() -> int:
    """`time.perf_counter()` TRUNCATED to whole seconds. See the module
    docstring on why the fractional form cannot be a value here."""
    return clock_gettime_nsec_np(6) / 1000000000


# ── CPU time ────────────────────────────────────────────────────────────────

def process_time_ns() -> int:
    """`time.process_time_ns()`: CPU nanoseconds for this PROCESS.

    Summing over every thread, which is what CPython's does and what Darwin's
    `CLOCK_PROCESS_CPUTIME_ID` reports.
    """
    return clock_gettime_nsec_np(12)

def process_time() -> int:
    """`time.process_time()` TRUNCATED to whole seconds."""
    return clock_gettime_nsec_np(12) / 1000000000

def thread_time_ns() -> int:
    """`time.thread_time_ns()`: CPU nanoseconds for the CALLING THREAD.

    On a formal image there is exactly one thread — the one the entry stub
    called into — so this and `process_time_ns` read the same hardware counter
    whenever nothing else is running. They are separate functions because the
    two questions are separate, and on a target with threads they would differ.
    """
    return clock_gettime_nsec_np(16)

def thread_time() -> int:
    """`time.thread_time()` TRUNCATED to whole seconds."""
    return clock_gettime_nsec_np(16) / 1000000000


# ── the raw clock interface ─────────────────────────────────────────────────

def clock_gettime_ns(clock_id) -> int:
    """`time.clock_gettime_ns(clock_id)`: nanoseconds from ANY `CLOCK_*`.

    The general form behind every function above, and the one to reach for
    when the clock is chosen at run time. `clock_id` is one of the
    `CLOCK_*()` functions' answers; there is no way to pass a name across a
    dylib boundary, so the value is what a program computes it to be.

    The clock ids Darwin defines and this can read: 0 (REALTIME), 1
    (MONOTONIC_RAW), 6 (MONOTONIC), 12 (PROCESS_CPUTIME_ID), 16
    (THREAD_CPUTIME_ID). An id outside that set is the C library's business —
    it returns `(clockid_t)-1` and sets errno, and this path has no `errno`
    (see `os/_syscalls.mojo`), so the value that comes back is what
    `clock_gettime_nsec_np` returns for an unknown id, which is 0.
    """
    return clock_gettime_nsec_np(clock_id)


# ── sleeping ────────────────────────────────────────────────────────────────

def sleep_ns(nanoseconds) -> int:
    """`time.sleep(seconds)` with the argument in NANOSECONDS. Returns 0.

    `usleep(2)`, which is `nanosleep` with the precision Darwin's `sleep`
    itself has. It is spelled in nanoseconds because a float argument is a
    truncated integer on this path, so a `sleep(0.5)` that meant half a second
    would sleep zero — silently, and with no way for the caller to tell.

    A negative argument sleeps zero and returns, where CPython raises
    `ValueError`. There is no exception on this path; the count that was
    actually slept is not returned either, because `usleep` does not report
    it and a value invented here would be a fiction.
    """
    if nanoseconds <= 0:
        return 0
    usleep(nanoseconds / 1000)
    return 0

def sleep_seconds(seconds) -> int:
    """`time.sleep(seconds)` for a WHOLE number of seconds. Returns 0.

    The form a program can use without the float caveat. Sub-second sleeps go
    through `sleep_ns`, which takes the count the caller actually wants.
    """
    if seconds <= 0:
        return 0
    usleep(seconds * 1000000)
    return 0


# ── the one piece of machinery that needs explaining ────────────────────────

def ns_to_double_bits(ns) -> int:
    """The IEEE-754 bit pattern of `ns / 1e9`, as a 64-bit word.

    So that `time_seconds_bits()` is a real conversion rather than a claim
    that one exists. The arithmetic is integer throughout, because there is no
    float to compute in — which is also why this is a conversion with a
    documented, bounded accuracy rather than an exact one:

    `ns / 1e9` is a double, and a double is `m * 2^(e-52)` with `2^52 <= m <
    2^53`. So the conversion is: find `e` with `2^e <= ns/1e9 < 2^(e+1)`,
    compute `m = round(ns * 2^(52-e) / 1e9)` to nearest with ties to even, and
    assemble `(e + 1023) << 52 | (m & (2^52 - 1))`. That is the longhand form
    of what an `scvtf` does, written out because neither that instruction nor
    a float type is reachable from a module this target compiles.

    TWO THINGS MAKE IT FIT IN 64 BITS, and both were measured rather than
    reasoned about — the obvious version of this function overflows and
    returns a wrong exponent, silently.

    1. `ns * 2^(52-e)` does not fit for any real timestamp (`e` is 30, so the
       shift is 22 and the product is ~7.5e24). The fix is to split
       `ns = whole*1e9 + frac` FIRST, so the whole part is shifted on its own
       and the fraction is divided in `rne_scaled`'s chunks — `frac < 2^30`,
       so a 28-bit chunk keeps every intermediate under `2^58`.

    2. The exponent search must not shift by a negative amount, and must not
       assume the answer is near 30. `ns` here is always ~1.8e18, but a
       program may pass any count, and a search that only works for the one
       magnitude `time_ns()` produces is a search that is wrong elsewhere.

    Correctness is pinned by `test_formal_time.py` against the exact
    rational — not against `ns/1e9` in Python, which DOUBLE-ROUNDS for any
    `ns` above `2^53` (Python converts `ns` to a float first, losing the low
    bits, and then divides) and so disagrees with the correctly-rounded answer
    on a large fraction of real timestamps. Verified exhaustively over
    `1 .. 30000` and against exact rational arithmetic over the real
    timestamp range.
    """
    if ns <= 0:
        return 0
    var whole = ns / 1000000000
    var frac = ns - whole * 1000000000

    var e = 0
    if whole == 0:
        # Below one second: e is negative. DEN <= 2^30 and ns < DEN, so
        # `ns << (-e-1)` is under 2^59 and the search is bounded at -30.
        e = 0 - 30
        while e < 0 and (ns << (0 - e - 1)) >= 1000000000:
            e = e + 1
        var m = rne_scaled(ns, 52 - e, 1000000000)
        if m >= 9007199254740992:
            m = m / 2
            e = e + 1
        return (e + 1023) * 4503599627370496 + (m - 4503599627370496)

    e = 0
    var w = whole
    while w >= 2:
        w = w / 2
        e = e + 1
    var k = 52 - e
    var m2 = (whole << k) + rne_scaled(frac, k, 1000000000)
    if m2 >= 9007199254740992:
        m2 = m2 / 2
        e = e + 1
    return (e + 1023) * 4503599627370496 + (m2 - 4503599627370496)


def rne_scaled(a, k, den):
    """`round-half-even(a * 2^k / den)`, for `a < 2^30` and `k >= 0`.

    The one place the significand is built, and the reason it is a function:
    `a * 2^k` is up to `2^112` for the arguments `ns_to_double_bits` passes, so
    the shift is applied in 28-bit CHUNKS and each partial division is carried.
    `a << 28 < 2^58` and `q << 28` is bounded by the same running total, so no
    intermediate leaves 64 bits — measured, because the version that shifted
    once returned an exponent 60 too large and printed a time in the year
    2554.

    Ties to even, which is what IEEE-754 requires and what CPython's own
    conversion does; a truncation-toward-zero here would be wrong for every
    `a*2^k/den` that lands exactly on `.5`, which the last nanosecond of a
    second very nearly does.
    """
    var q = 0
    var rem = a
    var left = k
    while left > 0:
        var take = left
        if take > 28:
            take = 28
        var x = (rem << take) / den
        var r = (rem << take) - x * den
        q = (q << take) + x
        rem = r
        left = left - take
    if 2 * rem > den:
        q = q + 1
    elif 2 * rem == den and (q % 2) == 1:
        q = q + 1
    return q
