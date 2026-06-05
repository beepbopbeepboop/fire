#!/usr/bin/env python3
"""version.py — the single source of truth for the Mojo compiler version.

Shown by `mojo -v`, and folded into the CAS and JIT cache keys so artifacts built
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
import functools
import subprocess

# Set to "1.0", "1.1", ... for a tagged release build (overrides the git SHA).
RELEASE = None

_HERE = os.path.dirname(os.path.abspath(__file__))


@functools.lru_cache(maxsize=1)
def version() -> str:
    if RELEASE:
        return RELEASE

    def _git(*args):
        return subprocess.run(['git', '-C', _HERE, *args],
                              capture_output=True, text=True, timeout=5)

    try:
        r = _git('rev-parse', '--short', 'HEAD')
        if r.returncode == 0 and r.stdout.strip():
            v = r.stdout.strip()
            # `git diff --quiet HEAD` → 0 clean, non-0 if tracked files changed
            # (untracked files / build artifacts don't count as "dirty").
            if _git('diff', '--quiet', 'HEAD').returncode != 0:
                v += '-dirty'
            return v
    except Exception:
        pass
    return 'unknown'


if __name__ == '__main__':
    print(version())
