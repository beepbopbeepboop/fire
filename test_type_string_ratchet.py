#!/usr/bin/env python3
"""Ratchets on the two remaining string-typed habits of the gimple backend
(doc/GIR.md, stages 4 and 2b): string type tests, and statements spelled as text.

The backend spells a type as a C string (`'int64_t'`, `'char *'`,
`'MojoList *'`) and decides things by comparing those strings. Stage 4
replaces them with `Type` objects, one method per question, so the answer to
"is this a pointer?" lives in one place. Until then this test only stops the
count growing: new code should ask a `Type`/`TypeLattice` method, not
re-spell the test.

    python3 test_type_string_ratchet.py            # check against BASELINE
    python3 test_type_string_ratchet.py --counts   # print the current counts

When a count FALLS the test fails until BASELINE is lowered to match (so the
gain is locked in), exactly as test_gimple_lint.py does.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Counted over gimple_codegen.py, mojo/middle/*.py and mojo/backend_gimple/*.py.
PATTERNS = {
    "endswith(' *')": r"""\.endswith\(\s*' \*'\s*\)""",
    "== 'int64_t'": r"""[=!]= *'int64_t'""",
    "in (.., 'int64_t', ..)": r"""\bin *\([^)]*'int64_t'[^)]*\)""",
    "== 'char *'": r"""[=!]= *'char \*'""",
    "== '_Bool'": r"""[=!]= *'_Bool'""",
    "== 'double'": r"""[=!]= *'double'""",
    "== 'MojoList *'": r"""[=!]= *'MojoList \*'""",
    # Stage 2b: a statement written with `gen._emit("...")` is text nobody
    # type-checks at the source; the builder calls (`_rt_call`, `_cast`,
    # `_copy`, `_goto`, `_binop`, ...) are checked by gimple_lint.
    "gen._emit( text": r"""\b(?:gen|self)\._emit\(""",
    # ...and `build.raw` is the builder's adapter for a statement no family
    # models yet, so it is the same debt and must not become the way around
    # the count above. Only `_emit_raw` itself should call it.
    "build.raw( text": r"""\bbuild\.raw\(""",
    # Stage 5b: the six dynamic-word sets are read and written through
    # `gen._words` (mojo/middle/valueinfo.py: `may_be_box`, `mark_tagged`, ...).
    # A direct `gen._boxed_vals` is the old spelling.
    "direct word-set use": r"""(?m)^(?![ \t]*#).*\b(?:gen|self)\._(?:boxed_vals|tagged_word_vals|dyn_word_vals|int_word_vals|maybe_kinds_vals|boxed_container_vals)\b""",
}

BASELINE = {
    "endswith(' *')": 16,
    "== 'int64_t'": 54,
    "in (.., 'int64_t', ..)": 0,
    "== 'char *'": 62,
    "== '_Bool'": 2,
    "== 'double'": 8,
    "== 'MojoList *'": 29,
    # Stage 2b is landed: every statement the lowering writes is a builder
    # call, and `build.raw` is the only text channel left (its own baseline).
    "gen._emit( text": 0,
    "build.raw( text": 1,
    "direct word-set use": 10,
}

# A pattern whose SUBJECT is narrower than "every backend module".  The
# `gen._emit( text` ratchet counts a statement spelled as GIMPLE C text;
# `emit_metal.py` emits Metal Shading Language through its own `_emit` method
# and writes no gimple statement at all, so its 21 `self._emit(` calls can
# never move.  Leaving them in made the ratchet's floor 21 instead of 0,
# where a real regression could hide behind them (measured 2026-11-21).
_NOT_THIS_PATTERNS_SUBJECT = {
    "gen._emit( text": {"mojo/backend_gimple/emit_metal.py"},
}


def sources() -> list:
    """Every backend module EXCEPT mojo/middle/types.py: that file defines the
    TypeLattice predicates, which are the one sanctioned spelling of each test."""
    types_py = os.path.join(HERE, 'mojo', 'middle', 'types.py')
    return sorted(
        p for p in glob.glob(os.path.join(HERE, 'mojo', 'backend_gimple', '*.py'))
        + glob.glob(os.path.join(HERE, 'mojo', 'middle', '*.py'))
        + [os.path.join(HERE, 'gimple_codegen.py')]
        if p != types_py)


def counts() -> dict:
    texts: list = []
    for p in sources():
        texts.append((os.path.relpath(p, HERE).replace(os.sep, '/'), open(p).read()))
    out: dict = {}
    for k in PATTERNS:
        skip = _NOT_THIS_PATTERNS_SUBJECT.get(k, set())
        n = 0
        for rel, text in texts:
            if rel in skip:
                continue
            n += len(re.findall(PATTERNS[k], text))
        out[k] = n
    return out


def per_file(only_stage4: bool = True) -> None:
    """The census a work packet should be sized from: every file's counts.

    A packet doc's table is a snapshot and goes stale; this is measured."""
    stage4 = {"endswith(' *')", "== 'int64_t'", "in (.., 'int64_t', ..)",
              "== 'char *'", "== '_Bool'", "== 'double'", "== 'MojoList *'"}
    for p in sources():
        text = open(p).read()
        nz = [(k, len(re.findall(v, text))) for k, v in PATTERNS.items()
              if (k in stage4 or not only_stage4)]
        nz = [(k, n) for k, n in nz if n]
        if nz:
            print('%-46s %s' % (os.path.relpath(p, HERE),
                                ', '.join('%s: %d' % (k, n) for k, n in nz)))


def main(argv: list) -> int:
    now = counts()
    if '--counts' in argv:
        for k in PATTERNS:
            print('%-26s %d' % (k, now[k]))
        return 0
    if '--per-file' in argv:
        per_file('--all-patterns' not in argv)
        return 0
    failures = 0
    for k in PATTERNS:
        if now[k] > BASELINE[k]:
            print('  FAIL  %s: %d, baseline %d -- ask a Type/TypeLattice method '
                  'instead of adding a string test (python3 tools/type_string_codemod.py rewrites the simple ones)' % (k, now[k], BASELINE[k]))
            failures += 1
        elif now[k] < BASELINE[k]:
            print('  FAIL  %s: %d, baseline %d -- fixed! lower BASELINE[%r] to %d '
                  'in test_type_string_ratchet.py' % (k, now[k], BASELINE[k], k, now[k]))
            failures += 1
        else:
            print('  ok    %s: %d' % (k, now[k]))
    print('passed: %d failure(s)' % failures)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
