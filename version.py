#!/usr/bin/env python3
"""version.py — the single source of truth for the Mojo compiler version.

Shown by `fire -v`, and folded into the CAS and JIT cache keys so artifacts built
by a different compiler version are never reused. Resolution order:

  1. RELEASE — a baked-in constant when set (production: "1.0", "1.1", "2.0", …);
  2. the git short SHA of HEAD, suffixed "-dirty" if tracked files are modified;
  3. "unknown" — an installed binary with no .git and no RELEASE.

The version is a *coarse* cache epoch and a defense-in-depth safety net: even if
a source file that affects codegen isn't in the CAS fingerprint list, a new
commit bumps the SHA and invalidates everything. It does NOT replace the
content fingerprint (cas.compiler_fingerprint), which is what catches uncommitted
working-tree edits during development. Both are mixed into the keys.
"""
import os
import subprocess

# Set to "1.0", "1.1", ... for a tagged release build (overrides the git SHA).
RELEASE = None

_HERE = os.path.dirname(os.path.abspath(__file__))

#: The one computed answer, and the fact that it has been computed. `None` is
#: "not yet", which is why this is not initialized to `'unknown'` — that string
#: is a possible ANSWER, and a cache primed with it would return it forever.
#:
#: **This module-level memo replaces `@functools.lru_cache(maxsize=1)`**, which
#: was the file's whole `functools` dependency and the reason
#: `tools/formal_host_import_wall.py` ranked `functools` as `alone 1` — the ONLY
#: module standing between this file and a formal build. `lru_cache` is a
#: decorator over a FUNCTION VALUE, which is a capability this path has no
#: representation for (`formal/hostmods/functools.mojo`'s own refusal: "the
#: higher-order functions are a callable this path has no representation for"),
#: and `bugs/FORMAL_eleven_of_thirteen_host_import_rows_are_closure.md` §4 named
#: this exact substitution — "a function this repository could spell as a plain
#: cached call". It is the same shape as the two rows that closed the same way
#: on 2026-10-05: `itertools` left `test_formal_run.py` and `copy` left
#: `tools/apply_extraction.py`. The dependency leaves the file; the module is
#: not written.
#:
#: **The behaviour is IDENTICAL and the difference is one comparison.** For a
#: zero-argument function `lru_cache(maxsize=1)` computes once and returns the
#: same object thereafter; that is what these two module globals are. A caller
#: that wants the memo cleared can assign `_VERSION_CACHE = None`, and
#: `functools.lru_cache` exposed `.cache_clear()` — nothing in this repository
#: calls it (`fire.py`, `cas.py` and `jit/arm64.py` are the three importers), and
#: a cache of the git SHA is not something a test wants to clear mid-run
#: anyway. The one thing `lru_cache` gave that this does not is a `cache_info`
#: for hit/miss counting, which nothing here reads.
_VERSION_CACHE = None


def version() -> str:
    """The compiler version string; computed once per process.

    The cache is a plain module global rather than a decorator because the
    decorator is the dependency: see `_VERSION_CACHE`. Recomputing on a race is
    harmless — the body reads a git SHA and shells out at most twice, and two
    racing readers would compute the same string — so there is no lock, which is
    also what `lru_cache` did not need for a single-entry cache of a pure read.
    """
    global _VERSION_CACHE
    if _VERSION_CACHE is not None:
        return _VERSION_CACHE
    if RELEASE:
        _VERSION_CACHE = RELEASE
        return _VERSION_CACHE
    # Two named helpers rather than one `_git(*args)`, and that is the SECOND
    # thing this file had to give up to build, measured on the same two
    # architectures: `*args` has no variadic ABI on the formal path — a formal
    # value is one 64-bit word, so the arguments past the fixed ones have
    # nowhere to be packed, and a tuple of them is a blob in the CALLER's frame
    # ("`version__git`: the body reads 'args', its *-parameter, and this path
    # has no variadic ABI"). There are exactly two call sites and two fixed
    # shapes, so a named parameter each is the whole of the fix, and it removes
    # the nested `def` as well — which was a closure capture this path has to
    # flatten before it can lower the function at all.
    try:
        r = subprocess.run(['git', '-C', _HERE, 'rev-parse', '--short', 'HEAD'],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            v = r.stdout.strip()
            # `git diff --quiet HEAD` → 0 clean, non-0 if tracked files changed
            # (untracked files / build artifacts don't count as "dirty").
            d = subprocess.run(['git', '-C', _HERE, 'diff', '--quiet', 'HEAD'],
                               capture_output=True, text=True, timeout=5)
            if d.returncode != 0:
                v += '-dirty'
            _VERSION_CACHE = v
            return _VERSION_CACHE
    except Exception:
        pass
    _VERSION_CACHE = 'unknown'
    return _VERSION_CACHE


if __name__ == '__main__':
    print(version())