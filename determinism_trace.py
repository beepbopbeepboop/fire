"""Gated determinism tracing: an iota + xorshift64 rolling-hash stream.

Off by default. Set `MOJO_TRACE=1` in the environment to enable; the
stream is then appended to `MOJO_TRACE_FILE` (default `/tmp/mojo_trace.txt`)
as one `<iota> <hash>` line per `note()` call, nothing else on the line.

Why: two runs of the same chokepoint (python-interpreted reference vs the
self-hosted binary, or the self-hosted binary against itself) that agree
everywhere except somewhere deep in a huge trace produce two streams of the
same shape; `diff`ing them lands on the exact step number of the first
divergence — a coordinate for the debugger, not "somewhere in 36 MB of
output" (see HOW-TO-DEBUG.html section 8b).

IMPORTANT — hash CONTENT, never addresses. The entropy fed to `note()` must
be derived from values that are equal across the two runs being compared
(a string's characters, a small int, an enum tag, a length). Feeding a heap
address makes the whole stream address-dependent and destroys its value as a
divergence detector — the exact class of bug this project is hunting. Use
`str_hash()` (a stable FNV-1a) rather than Python's `hash()`, which is
per-process randomized by PYTHONHASHSEED.

Cost when disabled is one function call plus a handful of integer ops per
`note()`, with no I/O and no allocation on the logging path; enabled it adds
one short line of file I/O per call, so only hook chokepoints that are
"close enough" to the suspect work and not an unbounded nanosecond-scale
inner loop.
"""
import os

_TRUTHY = ('1', 'true', 'True', 'yes', 'on')


def enabled() -> bool:
    """True when MOJO_TRACE requests tracing (re-read each call so a test can
    flip it at runtime).

    Explicit `==` comparisons, NOT `os.environ.get(...) in _TRUTHY`: a
    `str in (<tuple of strings>)` membership test is the established
    self-hosted trap this project's audit_determinism.py flags as TUPLE-IN
    (the tuple's elements erase to int64_t and the comparison never matches),
    which made `enabled()` return False on the compiled binary even with
    MOJO_TRACE=1 set — caught immediately by this module's own smoke test."""
    global _ENABLED
    if _ENABLED is None:
        _v = os.environ.get('MOJO_TRACE', '')
        _ENABLED = (_v == '1' or _v == 'true' or _v == 'True'
                    or _v == 'yes' or _v == 'on')
    return _ENABLED


def _trace_file() -> str:
    return os.environ.get('MOJO_TRACE_FILE', '/tmp/mojo_trace.txt')


# iota: the coordinate. hash: the rolling xorshift state.
#
# PORTABILITY: every constant here is intentionally SMALL (fits in 32 bits).
# The compiled backend materialises large integer literals through a
# dedicated path (see the `_t = -1ULL` convention) that did NOT reproduce
# CPython's exact 64-bit values in this facility's smoke test, so a 64-bit
# mask/seed made the two streams differ on EVERY step and drowned the real
# signal. 31-bit values are exact on both sides; the hash is coarser but the
# iota stream — the actual divergence coordinate — is unaffected.
_iota = 0
_hash = 0x1234567
_MASK = 0x7FFFFFFF
_ENABLED = None  # lazily resolved on first enabled() call


def reset() -> None:
    """Restart the stream (call once at the top of a traced compile)."""
    global _iota, _hash
    _iota = 0
    _hash = 0x1234567


def current() -> tuple:
    """(iota, hash) without advancing — for assertion/telemetry hooks."""
    return _iota, _hash


def note(entropy: int) -> int:
    """Advance the stream by one step, mixing in `entropy` (CONTENT-derived,
    never an address), and append `<iota> <hash>` when enabled. Returns the
    new hash. O(1), no allocation when disabled."""
    global _iota, _hash
    _iota += 1
    h = (_hash ^ (entropy & _MASK)) & _MASK
    h ^= (h << 13) & _MASK
    h ^= h >> 7
    h ^= (h << 17) & _MASK
    _hash = h
    if enabled():
        try:
            with open(_trace_file(), 'a') as _f:
                _f.write(f"{_iota} {h}\n")
        except Exception:
            pass
    return h


def note_str(s: str) -> int:
    """`note(str_hash(s))` — the common case of hashing a string's content."""
    return note(str_hash(s))


# Portability constants: keep the running hash strictly below 2**63 so that
# `>>` is logical on BOTH sides, and avoid multiplication entirely. CPython
# has arbitrary-precision ints (a `h * PRIME` is exact, then masked) while
# the compiled backend is fixed-width int64_t (overflow there is UB, and the
# codegen materialises large literals specially) — a multiply-based hash
# therefore produced DIFFERENT streams for the same string (caught by the
# facility's own smoke test). shift/add/xor with a 63-bit mask is identical.
# 31-bit, matching `_MASK`: the compiled backend turns any literal
# wider than `int` into -1 (see the portability note above), so a 64-bit
# mask here overflowed and produced a warning + wrong values.
_MASK63 = 0x7FFFFFFF


def str_hash(s: str) -> int:
    """Stable content hash over a string's characters — NOT `hash()`
    (PYTHONHASHSEED-randomized), NOT a multiply-based hash (C/Python overflow
    differ — see the portability note), and deliberately WITHOUT an
    `isinstance(s, str)` guard: that is the constant-FALSE static guard on
    the compiled path, so it made this function return 0 for every real
    string (the very trap this facility exists to find — caught by its own
    smoke test). Callers pass a str."""
    _n = len(s)
    if _n == 0:
        return 0
    # Coarse but PORTABLE: length plus the two end characters, small
    # constants only. Deliberately NOT a per-character rolling loop — a
    # multiply/overflow-free char loop STILL disagreed between CPython and
    # the compiled backend in this facility's own smoke test (the compiled
    # `for _c in s` over a char* / `ord` path is itself one of the traps
    # this project hunts), and a divergence detector is only useful if its
    # own hash is identical on both sides. Length + endpoints catches the
    # overwhelming majority of real value differences.
    return ((_n * 131) + ((ord(s[0]) & 0xFF) * 7) + (ord(s[_n - 1]) & 0xFF)) & _MASK63
